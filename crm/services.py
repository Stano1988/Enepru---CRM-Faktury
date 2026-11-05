"""Business operations shared by forms, actions and scheduled commands."""

import hashlib
import io
import json
import re
import zipfile
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import (
    Access,
    Automation,
    Client,
    Company,
    Document,
    Event,
    Folder,
    Inquiry,
    Invoice,
    Job,
    Message,
    Offer,
    Payment,
    Task,
)


def finance(user):
    return user.is_superuser or Access.objects.filter(user=user, finances=True).exists()


def export_allowed(user):
    return user.is_superuser or Access.objects.filter(user=user, export=True).exists()


def jobs_for(user):
    qs = Job.objects.select_related("client", "assigned_to", "property")
    if user.is_superuser or Access.objects.filter(user=user, all_jobs=True).exists():
        return qs
    return qs.filter(Q(assigned_to=user) | Q(tasks__assigned_to=user)).distinct()


def require_finance(user):
    if not finance(user):
        raise PermissionDenied


def editable(job):
    if job.archived_at:
        raise ValidationError("Archivovaná zakázka je pouze ke čtení.")


def event(user, action, job=None, **details):
    return Event.objects.create(actor=user, action=action, job=job, details=details)


def company():
    return Company.objects.get_or_create(pk=1)[0]


def ensure_folders(job):
    for name in [
        "Nabídky a objednávky",
        "Podklady od klienta",
        "Zaměření a fotografie",
        "Pracovní soubory",
        "Kontrola",
        "Finální výstupy",
        "Faktury a předání",
    ]:
        Folder.objects.get_or_create(job=job, name=name)


@transaction.atomic
def initialize_job(job):
    ensure_folders(job)
    services = ["penb", "passport"] if job.service == "both" else [job.service]
    for service in services:
        Task.objects.get_or_create(
            job=job,
            title=f"Zpracovat {dict(Job.SERVICES)[service]}",
            defaults={"assigned_to": job.assigned_to, "due_date": job.due_date},
        )


@transaction.atomic
def create_offer(inquiry, cleaned, user):
    inquiry = Inquiry.objects.select_for_update().get(pk=inquiry.pk)
    if not inquiry.address.strip():
        raise ValidationError("Před nabídkou doplňte adresu nemovitosti v poptávce.")
    if inquiry.job_id or inquiry.status == "accepted":
        raise ValidationError(
            "Potvrzenou nabídku nelze nahradit. Změny řešte jako vícepráci."
        )
    latest = inquiry.offers.first()
    inquiry.offers.filter(accepted_at__isnull=True).update(revoked=True)
    offer = Offer.objects.create(
        inquiry=inquiry, version=(latest.version + 1 if latest else 1), **cleaned
    )
    from .offers import make_pdf

    offer.pdf = make_pdf(offer)
    offer.save(update_fields=["pdf"])
    event(user, "Vytvořena verze nabídky", offer=offer.pk, inquiry=inquiry.pk)
    return offer


def offer_available(offer):
    return (
        not offer.revoked
        and not offer.accepted_at
        and not offer.declined_at
        and offer.valid_until >= timezone.localdate()
    )


@transaction.atomic
def accept_offer(offer, data):
    offer = Offer.objects.select_for_update().select_related("inquiry").get(pk=offer.pk)
    inquiry = Inquiry.objects.select_for_update().get(pk=offer.inquiry_id)
    if offer.accepted_at:
        return offer
    if not offer_available(offer) or inquiry.job_id:
        raise ValidationError("Tato nabídka již není platná.")
    offer.accepted_at = timezone.now()
    offer.acceptance = {
        **data,
        "version": offer.version,
        "price": str(offer.price),
        "scope": offer.scope,
        "terms": offer.terms,
        "due_date": offer.due_date.isoformat(),
    }
    offer.save(update_fields=["accepted_at", "acceptance"])
    Message.objects.filter(offer=offer, state__in=["draft", "failed"]).update(
        state="cancelled"
    )
    inquiry.status = "accepted"
    inquiry.save(update_fields=["status"])
    event(None, "Klient potvrdil nabídku", offer=offer.pk, inquiry=inquiry.pk)
    return offer


@transaction.atomic
def convert_inquiry(inquiry, user):
    inquiry = Inquiry.objects.select_for_update().get(pk=inquiry.pk)
    if inquiry.job_id:
        return inquiry.job
    offer = inquiry.offers.filter(accepted_at__isnull=False).first()
    if not offer:
        raise ValidationError("Nejprve musí být potvrzena nabídka.")
    data = offer.acceptance
    client = inquiry.client
    if not client:
        candidates = Client.objects.none()
        if data.get("company_id"):
            candidates = Client.objects.filter(company_id=data["company_id"])
        if not candidates.exists():
            candidates = Client.objects.filter(
                email__iexact=inquiry.email,
                name__iexact=data.get("name") or inquiry.name,
            )
        if candidates.count() > 1:
            raise ValidationError(
                "Existuje více odpovídajících klientů. Vyberte správnou kartu klienta před převodem."
            )
        client = candidates.first()
    client = client or Client.objects.create(
        name=data.get("name") or inquiry.name,
        email=inquiry.email,
        phone=inquiry.phone,
        billing_address=data.get("billing_address", ""),
        company_id=data.get("company_id", ""),
        tax_id=data.get("tax_id", ""),
        created_by=user,
    )
    job = Job.objects.create(
        title=f"{dict(Job.SERVICES)[inquiry.service]} — {inquiry.address[:120]}",
        client=client,
        address=inquiry.address,
        service=inquiry.service,
        description=inquiry.description + "\n\nSchválený rozsah:\n" + offer.scope,
        due_date=offer.due_date,
        agreed_price=offer.price,
        billing_details={
            "name": data.get("name") or inquiry.name,
            "address": data.get("billing_address", client.billing_address),
            "company_id": data.get("company_id", client.company_id),
            "tax_id": data.get("tax_id", client.tax_id),
            "email": inquiry.email,
        },
        assigned_to=user,
        next_step="Domluvit zaměření",
    )
    initialize_job(job)
    for attachment in inquiry.attachments.all():
        Document.objects.create(
            job=job,
            folder=job.folders.get(name="Podklady od klienta"),
            name=attachment.name,
            file=attachment.file.name,
            sha256=attachment.sha256,
            internal=False,
            uploaded_by=None,
            origin="Klient z poptávky",
        )
    inquiry.job, inquiry.client, inquiry.status = job, client, "converted"
    inquiry.save(update_fields=["job", "client", "status"])
    Message.objects.filter(inquiry=inquiry, job__isnull=True).update(job=job)
    event(
        user,
        "Vytvořena zakázka z potvrzené nabídky",
        job,
        inquiry=inquiry.pk,
        offer=offer.pk,
    )
    return job


def iban(account):
    """Czech domestic account → IBAN, including domestic modulo-11 checks."""
    match = re.fullmatch(r"(?:(\d{1,6})-)?(\d{1,10})/(\d{4})", account.strip())
    if not match:
        raise ValidationError("Účet musí mít formát předčíslí-číslo/kód banky.")
    prefix, number, bank = match.groups()

    def valid(part, weights):
        return sum(int(x) * w for x, w in zip(part, weights)) % 11 == 0

    prefix = (prefix or "").zfill(6)
    number = number.zfill(10)
    if not valid(prefix, [10, 5, 8, 4, 2, 1]) or not valid(
        number, [6, 3, 7, 9, 10, 5, 8, 4, 2, 1]
    ):
        raise ValidationError("Číslo účtu neprošlo kontrolou modulo 11.")
    bban = bank + prefix + number
    check = 98 - int(bban + "123500") % 97
    return f"CZ{check:02d}{bban}"


def spd(invoice):
    account = invoice.supplier["bank_account"]
    return f"SPD*1.0*ACC:{iban(account)}*AM:{invoice.total:.2f}*CC:CZK*X-VS:{invoice.variable_symbol}*DT:{invoice.due_date:%Y%m%d}"


def qr_png(invoice):
    import qrcode

    output = io.BytesIO()
    qrcode.make(spd(invoice)).save(output, format="PNG")
    return output.getvalue()


def invoice_pdf(invoice):
    from .invoice_layout import render

    return render(invoice)


@transaction.atomic
def issue_invoice(invoice, user):
    require_finance(user)
    invoice = (
        Invoice.objects.select_for_update()
        .select_related("client", "job")
        .get(pk=invoice.pk)
    )
    if invoice.issued_at:
        return invoice
    for line in invoice.lines.all():
        line.full_clean()
    if invoice.subtotal <= 0:
        raise ValidationError("Faktura musí mít kladnou hodnotu položek.")
    if invoice.advance_id:
        advance = Invoice.objects.select_for_update().get(pk=invoice.advance_id)
        if (
            invoice.kind != "invoice"
            or advance.kind != "advance"
            or not advance.issued_at
            or advance.balance > 0
            or advance.client_id != invoice.client_id
            or advance.job_id != invoice.job_id
        ):
            raise ValidationError(
                "Záloha musí být uhrazená a patřit stejnému klientovi a zakázce."
            )
        if advance.total > invoice.subtotal:
            raise ValidationError(
                "Záloha převyšuje hodnotu plnění. Je nutné individuální vypořádání."
            )
        invoice.advance_amount = advance.total
    if invoice.due_date < invoice.issue_date:
        raise ValidationError("Splatnost nesmí být před datem vystavení.")
    company()
    cfg = Company.objects.select_for_update().get(pk=1)
    if not 2000 <= cfg.invoice_year <= 2099 or not 1 <= cfg.invoice_next <= 999999:
        raise ValidationError("Neplatné nastavení číselné řady.")
    if invoice.issue_date.year != cfg.invoice_year:
        raise ValidationError(
            "Rok vystavení neodpovídá nastavené číselné řadě. Upravte datum nebo nastavení fakturace."
        )
    yy = cfg.invoice_year % 100
    invoice.number = f"PF {yy:02d}{cfg.invoice_next:03d}"
    if invoice.job:
        base = invoice.job.number.replace("Z", "").replace("/", "")
        if not re.fullmatch(r"\d{5}", base):
            raise ValidationError("Formát zakázky neumožňuje VS. Zkontrolujte řadu.")
        order = (
            Invoice.objects.filter(job=invoice.job, issued_at__isnull=False).count() + 1
        )
        if order > 99:
            raise ValidationError("Vyčerpáno 99 dokladů na zakázku.")
        invoice.variable_symbol = f"{base}{order:02d}"
    else:
        # Standalone uses invoice digits; large series use a disjoint nine-digit namespace.
        invoice.variable_symbol = (
            f"{yy:02d}{cfg.invoice_next:03d}"
            if cfg.invoice_next < 10000
            else f"9{yy:02d}{cfg.invoice_next:06d}"
        )
    if Invoice.objects.exclude(pk=invoice.pk).filter(number=invoice.number).exists():
        raise ValidationError(
            "Číslo faktury již existuje. Opravte další pořadí v nastavení."
        )
    invoice.recipient = invoice.recipient or {
        "name": invoice.client.name,
        "address": invoice.client.billing_address,
        "company_id": invoice.client.company_id,
        "tax_id": invoice.client.tax_id,
        "email": invoice.client.email,
    }
    if not invoice.recipient.get("name") or not invoice.recipient.get("address"):
        raise ValidationError("Doplňte jméno a fakturační adresu odběratele.")
    invoice.supplier = {
        key: getattr(cfg, key)
        for key in [
            "name",
            "address",
            "company_id",
            "email",
            "bank_account",
            "bank_name",
        ]
    }
    iban(cfg.bank_account)
    invoice.pdf = invoice_pdf(invoice)
    invoice.issued_at = timezone.now()
    invoice.save()
    cfg.invoice_next += 1
    cfg.save(update_fields=["invoice_next"])
    event(
        user,
        "Vystavena faktura",
        invoice.job,
        invoice=invoice.pk,
        number=invoice.number,
        vs=invoice.variable_symbol,
    )
    return invoice


@transaction.atomic
def record_payment(invoice, data, user):
    require_finance(user)
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if not invoice.issued_at:
        raise ValidationError("Návrh faktury nelze uhradit.")
    amount = data["amount"]
    if (
        not amount.is_finite()
        or amount <= 0
        or amount >= Decimal("10000000000")
        or amount.as_tuple().exponent < -2
    ):
        raise ValidationError("Neplatná částka platby.")
    existing = Payment.objects.filter(request_key=data["request_key"]).first()
    if existing:
        if (
            existing.invoice_id != invoice.pk
            or existing.voided_at
            or existing.amount != data["amount"]
        ):
            raise ValidationError("Tento platební požadavek byl již použit.")
        return existing
    if (
        data.get("kind") == "refund"
        and invoice.kind == "advance"
        and Invoice.objects.filter(advance=invoice, issued_at__isnull=False).exists()
    ):
        raise ValidationError(
            "Záloha je již vyúčtovaná. Je nutné opravit i navazující doklad."
        )
    if data.get("kind") == "refund" and data["amount"] > invoice.paid:
        raise ValidationError("Nelze vrátit více než dosud přijatou částku.")
    payment, created = Payment.objects.get_or_create(
        request_key=data["request_key"],
        defaults={
            **{k: v for k, v in data.items() if k != "request_key"},
            "invoice": invoice,
            "recorded_by": user,
        },
    )
    if payment.invoice_id != invoice.pk or payment.voided_at:
        raise ValidationError("Platební požadavek již byl použit pro jinou fakturu.")
    if created:
        event(
            user,
            "Zaevidována platba",
            invoice.job,
            invoice=invoice.pk,
            amount=str(payment.amount),
        )
    if invoice.balance <= 0:
        invoice.messages.filter(reminder=True, state__in=["draft", "failed"]).update(
            state="cancelled"
        )
    return payment


def send_message(message, user=None):
    # Commit the claim before touching SMTP. A crash leaves "sending" for manual
    # reconciliation instead of silently re-sending a possibly accepted email.
    with transaction.atomic():
        message = (
            Message.objects.select_for_update()
            .select_related("invoice", "offer", "inquiry")
            .get(pk=message.pk)
        )
        if message.state not in ("draft", "failed"):
            return message
        if message.invoice:
            inv = Invoice.objects.select_for_update().get(pk=message.invoice_id)
            if not inv.issued_at:
                raise ValidationError("Nejprve vystavte fakturu.")
            if message.reminder and (
                inv.balance <= 0
                or inv.reminders_paused
                or inv.due_date >= timezone.localdate()
            ):
                message.state = "cancelled"
                message.save(update_fields=["state"])
                return message
            if message.reminder:
                message.body = reminder_body(inv)
        if message.offer and not offer_available(message.offer):
            raise ValidationError("Nabídka již není platná.")
        if not settings.CRM_EMAIL_ENABLED:
            raise ValidationError(
                "Odesílání není připojené. Nastavte bezpečně SMTP a CRM_EMAIL_ENABLED=1."
            )
        if not message.message_id:
            from email.utils import make_msgid

            message.message_id = make_msgid(
                domain=settings.DEFAULT_FROM_EMAIL.split("@")[-1]
            )
        message.state = "sending"
        message.save(update_fields=["state", "body", "message_id"])
    headers = {"Message-ID": message.message_id}
    if message.in_reply_to and re.fullmatch(r"<[^<>\s]{1,995}>", message.in_reply_to):
        headers.update(
            {"In-Reply-To": message.in_reply_to, "References": message.in_reply_to}
        )
    mail = EmailMessage(
        message.subject,
        message.body,
        settings.DEFAULT_FROM_EMAIL,
        [message.to],
        headers=headers,
    )
    if message.invoice:
        mail.attach(
            f"{message.invoice.number.replace(' ', '-')}.pdf",
            bytes(message.invoice.pdf),
            "application/pdf",
        )
    if message.offer:
        from .offers import make_pdf

        offer = message.offer
        if not offer.pdf:
            offer.pdf = make_pdf(offer)
            offer.save(update_fields=["pdf"])
        mail.attach(
            f"Nabidka-P{offer.inquiry_id:05d}-v{offer.version}.pdf",
            bytes(offer.pdf),
            "application/pdf",
        )
    try:
        if mail.send(fail_silently=False) != 1:
            raise RuntimeError("Mail backend nepřijal zprávu.")
    except Exception:
        message.state = "failed"
        message.error = "Odesílání selhalo. Správce musí zkontrolovat SMTP a doručení před opakováním."
        message.save(update_fields=["state", "error"])
        return message
    now = timezone.now()
    with transaction.atomic():
        message.state = "sent"
        message.sent_at = now
        message.error = ""
        message.save()
        if message.invoice and not message.reminder:
            Invoice.objects.filter(pk=message.invoice_id).update(sent_at=now)
        if message.offer:
            Offer.objects.filter(pk=message.offer_id).update(sent_at=now)
            Inquiry.objects.filter(pk=message.offer.inquiry_id).exclude(
                status__in=["accepted", "converted"]
            ).update(status="offered")
        event(user, "Odeslán e-mail", message.job, message=message.pk)
    return message


def prepare_reminders():
    cfg, _ = Automation.objects.get_or_create(pk=1)
    if not cfg.enabled:
        return 0
    count = 0
    today = timezone.localdate()
    for invoice in Invoice.objects.filter(
        issued_at__isnull=False, due_date__lt=today, reminders_paused=False
    ).select_related("client"):
        if invoice.balance <= 0:
            continue
        stages = [
            (stage, days)
            for stage, days in enumerate(
                [cfg.reminder_days, cfg.second_days, cfg.final_days], 1
            )
            if (today - invoice.due_date).days >= days
        ]
        if not stages:
            continue
        stage, days = stages[-1]
        if invoice.messages.filter(
            reminder=True, state="sent", reminder_stage__gte=stage
        ).exists():
            continue
        key = f"reminder:{invoice.pk}:{invoice.due_date}:stage{stage}"
        invoice.messages.filter(
            reminder=True, state__in=["draft", "failed"], reminder_stage__lt=stage
        ).update(state="cancelled")
        msg, created = Message.objects.get_or_create(
            dedupe_key=key,
            defaults={
                "invoice": invoice,
                "job": invoice.job,
                "to": invoice.recipient.get("email") or invoice.client.email,
                "subject": f"{stage}. připomenutí úhrady {invoice.number}",
                "body": reminder_body(invoice),
                "reminder": True,
                "reminder_stage": stage,
            },
        )
        if created:
            count += 1
        if cfg.auto_send and msg.state == "draft" and msg.to:
            try:
                send_message(msg)
            except ValidationError:
                pass
    return count


def reminder_body(invoice):
    return f"Dobrý den,\n\npřipomínáme neuhrazenou částku {invoice.balance:.2f} Kč k dokladu {invoice.number}, splatnému {invoice.due_date:%d.%m.%Y}. Variabilní symbol: {invoice.variable_symbol}.\nPokud jste již zaplatili, dejte nám prosím vědět.\n\nDěkujeme."


@transaction.atomic
def archive_job(job, user, confirm_complete=False):
    job = Job.objects.select_for_update().get(pk=job.pk)
    if job.archived_at:
        return job
    if job.status not in ["delivered", "closed"]:
        raise ValidationError("Nejprve zaznamenejte předání a dokončení práce.")
    unfinished = list(job.tasks.filter(done=False).values_list("id", flat=True))
    if unfinished and not confirm_complete:
        raise ValidationError(
            "Dokončete otevřené úkoly nebo při archivaci potvrďte jejich uzavření."
        )
    if unfinished:
        job.tasks.filter(pk__in=unfinished).update(done=True)
        event(
            user,
            "Při archivaci potvrzeno dokončení otevřených úkolů",
            job,
            tasks=unfinished,
        )
    now = timezone.now()
    year = now.year + max(5, company().retention_years)
    try:
        until = now.date().replace(year=year)
    except ValueError:
        until = now.date().replace(year=year, day=28)
    job.archived_at = now
    job.retain_until = until
    job.status = "closed"
    job.archive_manifest = build_manifest(job)
    job.save()
    event(user, "Archivována zakázka", job, retain_until=str(until))
    return job


def build_manifest(job):
    payload = {
        "job": job.number,
        "title": job.title,
        "description": job.description,
        "address": job.address,
        "client": {
            "name": job.client.name,
            "address": job.client.billing_address,
            "email": job.client.email,
        },
        "billing_details": job.billing_details,
        "agreed_price": str(job.agreed_price),
        "archived_at": str(job.archived_at),
        "retain_until": str(job.retain_until),
        "documents": [],
        "notes": list(job.notes.values("text", "author__username", "created_at")),
        "history": list(job.changes.values("before", "after", "created_at")),
        "events": list(job.events.values("action", "details", "created_at")),
        "handovers": list(
            job.handovers.values("recipient", "method", "date", "files", "note")
        ),
        "tasks": list(
            job.tasks.values(
                "title",
                "description",
                "due_date",
                "assigned_to__username",
                "actual_hours",
                "done",
            )
        ),
        "requirements": list(job.requirements.values("title", "state")),
        "expenses": list(
            job.expenses.values("title", "kind", "amount", "recipient", "paid", "date")
        ),
        "extra_work": list(
            job.extra_work.values("description", "price", "new_due_date", "accepted_at")
        ),
        "inquiries": list(
            Inquiry.objects.filter(job=job).values(
                "name", "email", "address", "description", "created_at"
            )
        ),
        "offers": list(
            Offer.objects.filter(inquiry__job=job).values(
                "version",
                "scope",
                "price",
                "terms",
                "due_date",
                "accepted_at",
                "acceptance",
            )
        ),
        "messages": list(
            job.messages.values("to", "subject", "body", "state", "sent_at")
        ),
        "payments": list(
            Payment.objects.filter(invoice__job=job).values(
                "invoice__number",
                "amount",
                "date",
                "kind",
                "method",
                "reference",
                "voided_at",
                "void_reason",
            )
        ),
    }
    return json.loads(json.dumps(payload, default=str))


def archive_zip(job):
    out = io.BytesIO()
    manifest = dict(job.archive_manifest or build_manifest(job))
    manifest["documents"] = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for doc in job.documents.filter(deleted_at__isnull=True):
            with doc.file.open("rb") as f:
                content = f.read()
            digest = hashlib.sha256(content).hexdigest()
            if digest != doc.sha256:
                raise ValidationError(f"Kontrolní součet nesouhlasí: {doc.name}")
            path = f"dokumenty/{doc.pk}_v{doc.version}_{Path(doc.name).name}"
            z.writestr(path, content)
            manifest["documents"].append(
                {
                    "path": path,
                    "sha256": digest,
                    "version": doc.version,
                    "folder": doc.folder.name,
                }
            )
        for inv in job.invoices.filter(issued_at__isnull=False):
            z.writestr(f"faktury/{inv.number.replace(' ', '-')}.pdf", bytes(inv.pdf))
        financial = {
            "exported_at": str(timezone.now()),
            "note": "Aktuální finance jsou samostatné od uzamčeného pracovního archivu.",
            "invoices": [
                {
                    "number": inv.number,
                    "total": str(inv.total),
                    "paid": str(inv.paid),
                    "balance": str(inv.balance),
                    "state": inv.state,
                }
                for inv in job.invoices.filter(issued_at__isnull=False)
            ],
        }
        z.writestr(
            "finance-current.json", json.dumps(financial, ensure_ascii=False, indent=2)
        )
        z.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2, default=str),
        )
    return out.getvalue()


@transaction.atomic
def accept_extra(extra):
    from .models import ExtraWork

    extra = ExtraWork.objects.select_for_update().get(pk=extra.pk)
    job = Job.objects.select_for_update().get(pk=extra.job_id)
    editable(job)
    if extra.accepted_at:
        return extra
    job.agreed_price += extra.price
    job.due_date = extra.new_due_date
    job.save(update_fields=["agreed_price", "due_date"])
    extra.accepted_at = timezone.now()
    extra.save(update_fields=["accepted_at"])
    event(
        None,
        "Klient schválil vícepráci",
        job,
        extra=extra.pk,
        price=str(extra.price),
        new_due_date=str(extra.new_due_date),
    )
    return extra


def run_daily():
    if settings.CRM_IMAP_ENABLED:
        from .mailbox import sync_mailbox

        try:
            sync_mailbox()
        except ValidationError:
            pass
    from .models import Notification

    today = timezone.localdate()
    for job in Job.objects.exclude(status__in=["delivered", "closed"]).filter(
        due_date__lte=today + timedelta(days=3)
    ):
        title = f"{job.number}: " + (
            "zakázka po termínu"
            if job.due_date < today
            else "blíží se termín vyhotovení"
        )
        Notification.objects.get_or_create(
            key=f"job:{job.pk}:{job.due_date}:{today}",
            defaults={"user": job.assigned_to, "job": job, "title": title},
        )
    for task in Task.objects.filter(
        done=False, due_date__lte=today + timedelta(days=1)
    ):
        Notification.objects.get_or_create(
            key=f"task:{task.pk}:{task.due_date}:{today}",
            defaults={
                "user": task.assigned_to,
                "job": task.job,
                "title": f"{task.job.number}: úkol {task.title}",
            },
        )
    if settings.CRM_EMAIL_ENABLED:
        for message in Message.objects.filter(
            state="draft", dedupe_key__startswith="ack:"
        ):
            send_message(message)
    from .offers import prepare_followups

    prepare_followups()
    return prepare_reminders()


@transaction.atomic
def void_payment(payment, user, reason):
    require_finance(user)
    invoice = Invoice.objects.select_for_update().get(pk=payment.invoice_id)
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.voided_at:
        return
    if not reason.strip():
        raise ValidationError("Uveďte důvod zrušení chybného přiřazení.")
    if (
        invoice.kind == "advance"
        and Invoice.objects.filter(advance=invoice, issued_at__isnull=False).exists()
    ):
        raise ValidationError(
            "Záloha je již vyúčtovaná. Nejprve je nutné vypořádat navazující doklad."
        )
    payment.voided_at = timezone.now()
    payment.void_reason = reason.strip()
    payment.save(update_fields=["voided_at", "void_reason"])
    from .models import BankTransaction

    BankTransaction.objects.filter(payment=payment).update(payment=None)
    event(
        user,
        "Zrušeno chybné přiřazení platby",
        invoice.job,
        payment=payment.pk,
        reason=reason,
    )


def matching_client(name, email="", company_id="", actor=None):
    candidates = (
        Client.objects.filter(company_id=company_id)
        if company_id
        else Client.objects.none()
    )
    if not candidates.exists() and email:
        candidates = Client.objects.filter(email__iexact=email, name__iexact=name)
    if candidates.count() > 1:
        raise ValidationError(
            "Existuje více odpovídajících klientů. Vyberte správnou uloženou kartu."
        )
    client = candidates.first()
    if (
        client
        and actor
        and not actor.is_superuser
        and not clients_for(actor).filter(pk=client.pk).exists()
    ):
        raise ValidationError(
            "Odpovídající karta klienta není v rozsahu vašich oprávnění. Požádejte správce o přidělení."
        )
    return client


@transaction.atomic
def resolve_client(
    name, email="", phone="", address="", company_id="", tax_id="", actor=None
):
    return matching_client(name, email, company_id, actor) or Client.objects.create(
        name=name,
        email=email,
        phone=phone,
        billing_address=address,
        company_id=company_id,
        tax_id=tax_id,
        created_by=actor,
    )


def documents_for(user):
    qs = Document.objects.all()
    if user.is_superuser:
        return qs
    base = (
        Q(job__in=jobs_for(user))
        | Q(job__isnull=True, uploaded_by=user)
        | Q(job__isnull=True, allowed_users=user)
    )
    visible = (
        Q(internal=False)
        | Q(allowed_users=user)
        | Q(job__isnull=True, uploaded_by=user)
    )
    return qs.filter(base & visible).distinct()


def clients_for(user):
    if user.is_superuser:
        return Client.objects.all()
    return Client.objects.filter(
        Q(job__in=jobs_for(user)) | Q(created_by=user)
    ).distinct()
