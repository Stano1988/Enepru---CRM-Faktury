"""Short everyday workflows; optional technical records stay out of the way."""

import uuid
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import Inquiry, Message
from .office import invoice_for, manager
from .services import create_offer, record_payment, send_message


def calculator_price(inquiry):
    quote = inquiry.source_details.get("quote") or {}
    if not isinstance(quote, dict):
        return None
    if quote.get("onRequest"):
        return None
    value = quote.get("total")
    if isinstance(value, bool) or value is None:
        return None
    try:
        price = Decimal(str(value))
    except (ValueError, TypeError, InvalidOperation):
        return None
    return (
        price.quantize(Decimal("0.01"))
        if price.is_finite() and Decimal("0.01") <= price < Decimal("10000000000")
        else None
    )


def offer_text(inquiry, price, due):
    amount = f"{price:.2f}".replace(".", ",") if price is not None else "[doplnit cenu]"
    return f"Dobrý den,\n\nděkujeme za Vaši poptávku.\n\nNabízíme Vám vyhotovení {inquiry.get_service_display()} pro nemovitost {inquiry.address}.\nCena celkem je {amount} Kč. Nejsme plátci DPH.\nPředpokládaný termín vyhotovení je {due:%d.%m.%Y} po dodání podkladů a domluvě zaměření.\n\nProsíme o potvrzení nabídky odpovědí na tento e-mail. Pokud se fakturační adresa liší od adresy nemovitosti, připište ji prosím spolu s fakturačním jménem, případně IČO.\n\nDěkujeme a přejeme hezký den.\nIng. Stanislav Lahodný"


class ReplyForm(forms.Form):
    def __init__(self, *args, inquiry=None, **kwargs):
        self.inquiry = inquiry
        super().__init__(*args, **kwargs)

    def clean(self):
        data = super().clean()
        if self.inquiry and not self.inquiry.address.strip():
            raise ValidationError(
                "Před nabídkou doplň adresu nemovitosti v poptávce. Kontakt a text zůstanou uložené."
            )
        return data

    price = forms.DecimalField(
        label="Cena celkem Kč",
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )
    due_date = forms.DateField(
        label="Předpokládaný termín vyhotovení",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    subject = forms.CharField(label="Předmět", max_length=250)
    body = forms.CharField(
        label="Text e-mailu", widget=forms.Textarea(attrs={"rows": 15})
    )

    def clean_due_date(self):
        value = self.cleaned_data["due_date"]
        if value < timezone.localdate():
            raise ValidationError("Vyberte dnešní nebo budoucí datum.")
        return value


@login_required
@permission_required("crm.add_offer", raise_exception=True)
def reply(request, pk):
    manager(request.user)
    inquiry = get_object_or_404(Inquiry, pk=pk)
    if inquiry.job_id or inquiry.status == "accepted":
        return redirect("inquiry_detail", pk=pk)
    latest = inquiry.offers.first()
    draft = (
        Message.objects.filter(
            offer=latest, state="draft", dedupe_key__startswith="easy-offer:"
        ).first()
        if latest and not latest.revoked
        else None
    )
    price = latest.price if latest else calculator_price(inquiry)
    due = (
        latest.due_date
        if latest
        else inquiry.requested_date or timezone.localdate() + timedelta(days=14)
    )
    initial = {
        "price": price,
        "due_date": due,
        "subject": draft.subject
        if draft
        else f"Nabídka – {inquiry.get_service_display()} – {inquiry.address}",
        "body": draft.body if draft else offer_text(inquiry, price, due),
    }
    form = ReplyForm(request.POST or None, initial=initial, inquiry=inquiry)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                inquiry = Inquiry.objects.select_for_update().get(pk=pk)
                offer = inquiry.offers.first()
                if (
                    not offer
                    or offer.revoked
                    or offer.accepted_at
                    or offer.declined_at
                    or offer.price != form.cleaned_data["price"]
                    or offer.due_date != form.cleaned_data["due_date"]
                ):
                    offer = create_offer(
                        inquiry,
                        {
                            "price": form.cleaned_data["price"],
                            "due_date": form.cleaned_data["due_date"],
                            "valid_until": timezone.localdate() + timedelta(days=14),
                            "scope": f"{inquiry.get_service_display()} – {inquiry.address}",
                            "terms": "Termín po dodání podkladů a domluvě zaměření.",
                        },
                        request.user,
                    )
                msg, created = Message.objects.get_or_create(
                    dedupe_key=f"easy-offer:{offer.pk}",
                    defaults={
                        "inquiry": inquiry,
                        "offer": offer,
                        "to": inquiry.email,
                        "subject": form.cleaned_data["subject"],
                        "body": form.cleaned_data["body"],
                    },
                )
                if not created and msg.state == "draft":
                    msg.subject = form.cleaned_data["subject"]
                    msg.body = form.cleaned_data["body"]
                    msg.save(update_fields=["subject", "body"])
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
            return redirect("inquiry_detail", pk=pk)
        if request.POST.get("intent") == "send":
            try:
                msg = send_message(msg, request.user)
                if msg.state == "sent":
                    messages.success(
                        request,
                        "Nabídka odeslána. U poptávky se nyní zobrazuje Nabídka odeslána.",
                    )
                else:
                    messages.error(
                        request, msg.error or "Zprávu je potřeba zkontrolovat v Poště."
                    )
            except ValidationError as error:
                messages.error(request, " ".join(error.messages) + " Návrh je uložený.")
        else:
            messages.success(
                request, "Nabídka uložená jako návrh. Zatím nebyla odeslána."
            )
        return redirect("inquiry_detail", pk=pk)
    return render(
        request,
        "crm/reply.html",
        {
            "inquiry": inquiry,
            "form": form,
            "price_from_web": calculator_price(inquiry),
            "price_partial": inquiry.service == "both",
        },
    )


@login_required
@permission_required("crm.add_payment", raise_exception=True)
def paid(request, pk):
    invoice = invoice_for(request.user, pk)
    if not invoice.issued_at or invoice.balance <= 0:
        return redirect("invoice_detail", pk=pk)

    class PaidForm(forms.Form):
        date = forms.DateField(
            label="Datum zaplacení",
            initial=timezone.localdate,
            widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        )
        request_key = forms.UUIDField(widget=forms.HiddenInput)

    form = PaidForm(request.POST or None, initial={"request_key": uuid.uuid4()})
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                from .models import Invoice

                invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
                if invoice.balance > 0:
                    record_payment(
                        invoice,
                        {
                            "amount": invoice.balance,
                            "date": form.cleaned_data["date"],
                            "kind": "receipt",
                            "method": "bank",
                            "reference": "Ručně označeno jako zaplaceno",
                            "request_key": form.cleaned_data["request_key"],
                        },
                        request.user,
                    )
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
            return redirect("invoice_detail", pk=pk)
        messages.success(
            request, "Faktura je zaplacená. Další upomínky se nepřipravují."
        )
        return redirect("invoice_detail", pk=pk)
    return render(request, "crm/mark_paid.html", {"invoice": invoice, "form": form})


@login_required
@permission_required("crm.change_offer", raise_exception=True)
def confirm(request, pk):
    from .forms import AcceptForm
    from .models import Offer
    from .services import accept_offer, event

    manager(request.user)
    offer = get_object_or_404(
        Offer.objects.select_related("inquiry", "inquiry__client"), pk=pk
    )
    inquiry = offer.inquiry
    if offer.accepted_at:
        return redirect("inquiry_detail", pk=inquiry.pk)

    class Confirmation(AcceptForm):
        evidence = forms.CharField(
            label="Jak zákazník potvrdil nabídku",
            initial="Potvrzeno e-mailem",
            max_length=1000,
        )

    client = inquiry.client
    initial = {
        "name": client.name if client else inquiry.name,
        "billing_address": client.billing_address if client else inquiry.address,
        "company_id": client.company_id if client else "",
        "tax_id": client.tax_id if client else "",
    }
    form = Confirmation(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            accept_offer(
                offer,
                {
                    key: value
                    for key, value in form.cleaned_data.items()
                    if key != "consent"
                },
            )
            event(
                request.user,
                "Zaznamenáno potvrzení zákazníka",
                offer=offer.pk,
                inquiry=inquiry.pk,
                evidence=form.cleaned_data["evidence"],
            )
            messages.success(
                request,
                "Nabídka potvrzená. Nyní můžeš vytvořit zakázku bez přepisování údajů.",
            )
            return redirect("inquiry_detail", pk=inquiry.pk)
        except ValidationError as error:
            form.add_error(None, error)
    return render(request, "crm/confirm_offer.html", {"form": form, "offer": offer})


@login_required
@permission_required("crm.change_receivedmail", raise_exception=True)
def mail_link(request, pk):
    from .models import Job, ReceivedMail
    from .services import event

    manager(request.user)
    mail = get_object_or_404(ReceivedMail, pk=pk)

    class LinkForm(forms.Form):
        inquiry = forms.ModelChoiceField(
            label="Poptávka nebo nabídka",
            queryset=Inquiry.objects.all(),
            required=False,
        )
        job = forms.ModelChoiceField(
            label="Zakázka", queryset=Job.objects.all(), required=False
        )

        def clean(self):
            data = super().clean()
            inquiry = data.get("inquiry")
            job = data.get("job")
            if inquiry and inquiry.job_id and job and inquiry.job_id != job.pk:
                raise ValidationError("Poptávka patří k jiné zakázce.")
            return data

    form = LinkForm(
        request.POST or None, initial={"inquiry": mail.inquiry_id, "job": mail.job_id}
    )
    if request.method == "POST" and form.is_valid():
        mail.inquiry = form.cleaned_data["inquiry"]
        mail.job = form.cleaned_data["job"] or (
            mail.inquiry.job if mail.inquiry and mail.inquiry.job_id else None
        )
        mail.save(update_fields=["inquiry", "job"])
        event(
            request.user,
            "Přiřazena komunikace",
            mail.job,
            mail=mail.pk,
            inquiry=mail.inquiry_id,
        )
        return redirect("received_mail", pk=pk)
    return render(
        request,
        "crm/form.html",
        {"form": form, "title": "Přiřadit e-mail k poptávce nebo zakázce"},
    )


@login_required
@permission_required("crm.add_message", raise_exception=True)
def mail_reply(request, pk):
    from .forms import MessageForm
    from .models import ReceivedMail

    manager(request.user)
    original = get_object_or_404(ReceivedMail, pk=pk)
    recipient = (
        original.sender_email
        if original.is_received
        else next(iter(original.recipients), "")
    )
    subject = (
        original.subject
        if original.subject.casefold().startswith("re:")
        else "Re: " + original.subject
    )
    form = MessageForm(
        request.POST or None,
        initial={
            "to": recipient,
            "subject": subject[:250],
            "body": "Dobrý den,\n\n\n\nIng. Stanislav Lahodný",
        },
    )
    if request.method == "POST" and form.is_valid():
        msg = form.save(commit=False)
        msg.inquiry = original.inquiry
        msg.job = original.job or (
            original.inquiry.job
            if original.inquiry and original.inquiry.job_id
            else None
        )
        msg.invoice = original.invoice
        msg.in_reply_to = original.message_id
        msg.save()
        if request.POST.get("intent") == "send":
            try:
                result = send_message(msg, request.user)
                messages.success(
                    request, "E-mail odeslán."
                ) if result.state == "sent" else messages.error(request, result.error)
            except ValidationError as error:
                messages.error(
                    request, " ".join(error.messages) + " Návrh zůstal uložený."
                )
        else:
            messages.success(request, "Odpověď uložená do rozepsané pošty.")
        return redirect("outbox")
    return render(request, "crm/compose.html", {"form": form, "original": original})


@login_required
@permission_required("crm.add_document", raise_exception=True)
def job_upload(request, pk):
    import hashlib

    from .forms import MultipleFileInput, MultipleFiles
    from .models import Document
    from .office import ensure_mutable
    from .services import ensure_folders, event, jobs_for

    job = get_object_or_404(jobs_for(request.user), pk=pk)
    ensure_mutable(job)

    class UploadForm(forms.Form):
        files = MultipleFiles(
            label="Vyber podklady (lze více najednou)", widget=MultipleFileInput()
        )

    form = UploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        ensure_folders(job)
        count = 0
        for upload in form.cleaned_data["files"]:
            digest = hashlib.sha256()
            for chunk in upload.chunks():
                digest.update(chunk)
            upload.seek(0)
            Document.objects.create(
                job=job,
                folder=job.folders.get(name="Podklady od klienta"),
                name=upload.name,
                file=upload,
                sha256=digest.hexdigest(),
                uploaded_by=request.user,
                origin="Nahráno k zakázce",
            )
            count += 1
        event(request.user, "Nahrány podklady", job, count=count)
        messages.success(request, f"Přidáno souborů: {count}.")
        return redirect("job_detail", pk=pk)
    return render(
        request,
        "crm/form.html",
        {"form": form, "title": "Přidat podklady k zakázce", "multipart": True},
    )
