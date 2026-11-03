"""CRM modules: all mutations are POST with CSRF and server-side authorization."""

import csv
import hashlib
import io
import uuid
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import FileResponse, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import forms as f
from .models import (
    BankTransaction,
    Client,
    ClientLink,
    Document,
    Expense,
    ExtraWork,
    Folder,
    Inquiry,
    InquiryAttachment,
    Invoice,
    Job,
    Message,
    Notification,
    Offer,
    Payment,
    PriceItem,
    Property,
    Requirement,
    Task,
)
from .services import (
    accept_offer,
    archive_job,
    archive_zip,
    company,
    convert_inquiry,
    create_offer,
    ensure_folders,
    event,
    export_allowed,
    issue_invoice,
    jobs_for,
    offer_available,
    prepare_reminders,
    qr_png,
    record_payment,
    require_finance,
    send_message,
)


def manager(user):
    if not user.is_superuser:
        raise PermissionDenied


def ensure_mutable(job):
    if job.archived_at:
        raise PermissionDenied("Archivovaná zakázka je pouze ke čtení.")


def form_page(request, form, title, **context):
    return render(request, "crm/form.html", {"form": form, "title": title, **context})


def detail_form(request, form, title, on_valid):
    if request.method == "POST" and form.is_valid():
        return on_valid(form)
    return form_page(request, form, title)


def report_error(request, error):
    messages.error(request, "; ".join(error.messages))


@login_required
@permission_required("crm.change_client", raise_exception=True)
def client_edit(request, pk):
    manager(request.user)
    obj = get_object_or_404(Client, pk=pk)
    form = f.ClientForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        event(request.user, "Upraven klient", client=obj.pk)
        return redirect("clients")
    return form_page(request, form, "Upravit klienta")


@login_required
@permission_required("crm.view_property", raise_exception=True)
def properties(request):
    qs = Property.objects.select_related("client")
    if not request.user.is_superuser:
        qs = qs.filter(job__in=jobs_for(request.user)).distinct()
    return render(request, "crm/properties.html", {"properties": qs})


@login_required
@permission_required("crm.add_property", raise_exception=True)
def property_form(request, pk=None):
    manager(request.user)
    obj = get_object_or_404(Property, pk=pk) if pk else None
    form = f.PropertyForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("properties")
    return form_page(request, form, "Nemovitost")


@login_required
@permission_required("crm.add_contact", raise_exception=True)
def contact_new(request):
    manager(request.user)
    form = f.ContactForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("clients")
    return form_page(request, form, "Nová kontaktní osoba")


def public_inquiry(request):
    key = request.session.setdefault("inquiry_key", str(uuid.uuid4()))
    form = f.PublicInquiryForm(
        request.POST or None, request.FILES or None, initial={"submission_key": key}
    )
    if request.method == "POST" and form.is_valid():
        if str(form.cleaned_data["submission_key"]) != key:
            return HttpResponseBadRequest("Neplatný formulář. Obnovte stránku.")
        obj, created = Inquiry.objects.get_or_create(
            submission_key=key,
            defaults={k: form.cleaned_data[k] for k in f.InquiryForm.Meta.fields},
        )
        if created:
            for upload in form.cleaned_data.get("attachments", []):
                h = hashlib.sha256()
                for chunk in upload.chunks():
                    h.update(chunk)
                upload.seek(0)
                InquiryAttachment.objects.create(
                    inquiry=obj,
                    name=Path(upload.name).name,
                    file=upload,
                    sha256=h.hexdigest(),
                )
            Message.objects.create(
                inquiry=obj,
                to=obj.email,
                subject="Přijali jsme vaši poptávku",
                body=f"Dobrý den,\n\npřijali jsme vaši poptávku P{obj.pk:05d}. Ozveme se s dalším postupem. Toto není potvrzení objednávky ani ceny.\n\nIng. Stanislav Lahodný",
                dedupe_key=f"ack:{obj.pk}",
            )
            event(None, "Přijata webová poptávka", inquiry=obj.pk)
        return render(
            request,
            "crm/public_done.html",
            {
                "title": "Poptávka byla přijata",
                "text": f"Číslo vaší poptávky je P{obj.pk:05d}. Budeme vás kontaktovat.",
            },
        )
    return render(
        request,
        "crm/public_form.html",
        {"form": form, "title": "Poptávka PENB nebo pasportu"},
    )


@login_required
@permission_required("crm.view_inquiry", raise_exception=True)
def inquiries(request):
    manager(request.user)
    qs = Inquiry.objects.select_related("job")
    state = request.GET.get("status", "")
    if state:
        qs = qs.filter(status=state)
    q = request.GET.get("q", "")
    if q:
        qs = qs.filter(
            Q(name__icontains=q) | Q(email__icontains=q) | Q(address__icontains=q)
        )
    return render(
        request,
        "crm/inquiries.html",
        {"inquiries": qs, "states": Inquiry.STATES, "selected": state, "query": q},
    )


@login_required
@permission_required("crm.add_inquiry", raise_exception=True)
def inquiry_new(request):
    manager(request.user)
    form = f.InquiryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.source = "Ručně"
        obj.save()
        return redirect("inquiry_detail", pk=obj.pk)
    return form_page(request, form, "Nová poptávka")


@login_required
@permission_required("crm.view_inquiry", raise_exception=True)
def inquiry_detail(request, pk):
    manager(request.user)
    obj = get_object_or_404(Inquiry, pk=pk)
    duplicates = Client.objects.filter(email__iexact=obj.email)
    return render(
        request, "crm/inquiry.html", {"inquiry": obj, "duplicates": duplicates}
    )


@login_required
@permission_required("crm.change_inquiry", raise_exception=True)
def inquiry_edit(request, pk):
    manager(request.user)
    obj = get_object_or_404(Inquiry, pk=pk)
    if obj.job_id or obj.status == "accepted":
        raise PermissionDenied("Potvrzenou poptávku nelze přepisovat.")
    form = f.InquiryEditForm(request.POST or None, instance=obj)
    form.fields["status"].choices = [
        x for x in Inquiry.STATES if x[0] not in ["accepted", "converted"]
    ]
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("inquiry_detail", pk=pk)
    return form_page(request, form, "Upravit poptávku")


@login_required
@permission_required("crm.add_offer", raise_exception=True)
def offer_new(request, pk):
    manager(request.user)
    obj = get_object_or_404(Inquiry, pk=pk)
    initial = {
        "scope": obj.description,
        "due_date": obj.requested_date,
        "valid_until": timezone.localdate() + timedelta(days=14),
    }
    if request.GET.get("item"):
        item = get_object_or_404(PriceItem, pk=request.GET["item"], active=True)
        initial.update(scope=item.name + "\n" + item.description, price=item.unit_price)
    form = f.OfferForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            offer = create_offer(obj, form.cleaned_data, request.user)
            link = request.build_absolute_uri(
                reverse("public_offer", args=[offer.token])
            )
            Message.objects.create(
                inquiry=obj,
                offer=offer,
                to=obj.email,
                subject=f"Cenová nabídka k poptávce P{obj.pk:05d}",
                body=f"Dobrý den,\n\nnabízíme zpracování za {offer.price:.2f} Kč s termínem {offer.due_date:%d.%m.%Y}.\n\n{offer.scope}\n\n{offer.terms}\n\nNabídku prosím potvrďte a doplňte fakturační údaje zde:\n{link}",
                dedupe_key=f"offer:{offer.pk}",
            )
            return redirect("inquiry_detail", pk=pk)
        except ValidationError as e:
            form.add_error(None, e)
    return form_page(
        request,
        form,
        "Nová verze nabídky",
        catalog_items=PriceItem.objects.filter(active=True),
        inquiry=obj,
    )


def public_offer(request, token):
    obj = get_object_or_404(Offer.objects.select_related("inquiry"), token=token)
    available = offer_available(obj)
    form = f.AcceptForm(request.POST or None, initial={"name": obj.inquiry.name})
    if request.method == "POST" and form.is_valid():
        try:
            accept_offer(
                obj, {k: v for k, v in form.cleaned_data.items() if k != "consent"}
            )
            return redirect("public_offer", token=token)
        except ValidationError as e:
            form.add_error(None, e)
    return render(
        request,
        "crm/public_offer.html",
        {"offer": obj, "form": form, "available": available},
    )


@login_required
@permission_required("crm.add_job", raise_exception=True)
@require_POST
def convert(request, pk):
    manager(request.user)
    try:
        job = convert_inquiry(get_object_or_404(Inquiry, pk=pk), request.user)
        return redirect("job_detail", pk=job.pk)
    except ValidationError as e:
        report_error(request, e)
        return redirect("inquiry_detail", pk=pk)


@login_required
@permission_required("crm.add_document", raise_exception=True)
def document_new(request, pk):
    job = get_object_or_404(jobs_for(request.user), pk=pk)
    ensure_mutable(job)
    ensure_folders(job)
    form = f.DocumentForm(request.POST or None, request.FILES or None, job=job)
    if not request.user.is_superuser:
        form.fields.pop("internal")
        form.fields.pop("allowed_users", None)
        form.fields["previous"].queryset = form.fields["previous"].queryset.filter(
            internal=False
        )
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            doc = form.save(commit=False)
            doc.job = job
            doc.uploaded_by = request.user
            if doc.previous_id:
                prev = Document.objects.select_for_update().get(pk=doc.previous_id)
                if Document.objects.filter(previous=prev).exists():
                    form.add_error("previous", "Novější verze již existuje.")
                    return form_page(request, form, "Nahrát dokument", multipart=True)
                if (
                    prev.internal
                    and not request.user.is_superuser
                    and not prev.allowed_users.filter(pk=request.user.pk).exists()
                ):
                    raise PermissionDenied
                doc.version = prev.version + 1
            if not request.user.is_superuser:
                doc.internal = False
            h = hashlib.sha256()
            for chunk in doc.file.chunks():
                h.update(chunk)
            doc.sha256 = h.hexdigest()
            doc.file.seek(0)
            doc.save()
            form.save_m2m()
            event(
                request.user, "Nahrán dokument", job, document=doc.pk, sha256=doc.sha256
            )
        return redirect("job_detail", pk=pk)
    return form_page(request, form, "Nahrát podklad nebo novou verzi", multipart=True)


@login_required
@permission_required("crm.view_document", raise_exception=True)
def document_download(request, pk):
    doc = get_object_or_404(
        Document.objects.select_related("job"),
        pk=pk,
        job__in=jobs_for(request.user),
        deleted_at__isnull=True,
    )
    if (
        doc.internal
        and not request.user.is_superuser
        and not doc.allowed_users.filter(pk=request.user.pk).exists()
    ):
        raise PermissionDenied
    event(request.user, "Stažen dokument", doc.job, document=doc.pk)
    return FileResponse(
        doc.file.open("rb"),
        as_attachment=True,
        filename=Path(doc.name).name,
        content_type="application/octet-stream",
    )


@login_required
@permission_required("crm.change_document", raise_exception=True)
@require_POST
def document_action(request, pk):
    doc = get_object_or_404(Document, pk=pk, job__in=jobs_for(request.user))
    ensure_mutable(doc.job)
    if (
        doc.internal
        and not request.user.is_superuser
        and not doc.allowed_users.filter(pk=request.user.pk).exists()
    ):
        raise PermissionDenied
    action = request.POST.get("action")
    if action == "trash":
        if not request.user.has_perm("crm.delete_document"):
            raise PermissionDenied
        doc.deleted_at = timezone.now()
    elif action == "restore":
        doc.deleted_at = None
    elif action == "rename":
        name = request.POST.get("name", "").strip()
        if not name or len(name) > 240:
            return HttpResponseBadRequest("Neplatný název.")
        doc.name = name
    else:
        return HttpResponseBadRequest("Neznámá akce.")
    doc.save()
    event(request.user, "Změna dokumentu", doc.job, document=doc.pk, action_type=action)
    return redirect("job_detail", pk=doc.job_id)


@login_required
@permission_required("crm.add_folder", raise_exception=True)
def folder_new(request, pk):
    from django import forms

    job = get_object_or_404(jobs_for(request.user), pk=pk)
    ensure_mutable(job)

    class FolderForm(forms.Form):
        name = forms.CharField(label="Název složky", max_length=120)

    form = FolderForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        Folder.objects.get_or_create(job=job, name=form.cleaned_data["name"])
        return redirect("job_detail", pk=pk)
    return form_page(request, form, "Nová složka")


@login_required
@permission_required("crm.add_task", raise_exception=True)
def task_new(request, pk):
    job = get_object_or_404(jobs_for(request.user), pk=pk)
    ensure_mutable(job)
    form = f.TaskForm(
        request.POST or None,
        initial={"assigned_to": request.user, "due_date": job.due_date},
    )
    if not request.user.is_superuser:
        form.fields["assigned_to"].queryset = type(request.user).objects.filter(
            pk=request.user.pk
        )
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.job = job
        obj.save()
        event(request.user, "Vytvořen úkol", job, task=obj.pk)
        return redirect("job_detail", pk=pk)
    return form_page(request, form, "Nový úkol / zaměření")


@login_required
@permission_required("crm.change_task", raise_exception=True)
def task_edit(request, pk):
    task = get_object_or_404(Task, pk=pk, job__in=jobs_for(request.user))
    ensure_mutable(task.job)
    if not request.user.is_superuser and task.assigned_to_id != request.user.pk:
        raise PermissionDenied
    form = f.TaskForm(request.POST or None, instance=task)
    if not request.user.is_superuser:
        form.fields.pop("assigned_to")
    if request.method == "POST" and form.is_valid():
        form.save()
        event(request.user, "Upraven úkol", task.job, task=task.pk)
        return redirect("job_detail", pk=task.job_id)
    return form_page(request, form, "Úkol / zaměření")


@login_required
@permission_required("crm.add_requirement", raise_exception=True)
def requirement_new(request, pk):
    job = get_object_or_404(jobs_for(request.user), pk=pk)
    ensure_mutable(job)
    form = f.RequirementForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.job = job
        obj.save()
        return redirect("job_detail", pk=pk)
    return form_page(request, form, "Požadovaný podklad")


@login_required
@permission_required("crm.change_requirement", raise_exception=True)
@require_POST
def requirement_update(request, pk):
    req = get_object_or_404(Requirement, pk=pk, job__in=jobs_for(request.user))
    ensure_mutable(req.job)
    state = request.POST.get("state")
    if state not in dict(Requirement._meta.get_field("state").choices):
        return HttpResponseBadRequest()
    req.state = state
    req.save()
    event(
        request.user, "Změněn stav podkladu", req.job, requirement=req.pk, state=state
    )
    return redirect("job_detail", pk=req.job_id)


@login_required
@permission_required("crm.add_expense", raise_exception=True)
def expense_new(request, pk):
    require_finance(request.user)
    job = get_object_or_404(jobs_for(request.user), pk=pk)
    ensure_mutable(job)
    form = f.ExpenseForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.job = job
        obj.save()
        event(request.user, "Zapsán náklad", job, expense=obj.pk)
        return redirect("job_detail", pk=pk)
    return form_page(request, form, "Náklad / odměna / provize")


@login_required
@permission_required("crm.view_task", raise_exception=True)
def calendar(request):
    import calendar as month_calendar
    from datetime import date

    today = timezone.localdate()
    try:
        year, month = map(
            int, request.GET.get("month", today.strftime("%Y-%m")).split("-")
        )
        selected = date(year, month, 1)
        if not 2000 <= year <= 2100:
            raise ValueError
    except (ValueError, TypeError):
        selected = today.replace(day=1)
    tasks = (
        Task.objects.filter(job__in=jobs_for(request.user))
        .select_related("job", "assigned_to")
        .order_by("due_date", "id")
    )
    buckets = {}
    for task in tasks:
        day = (
            timezone.localtime(task.starts_at).date()
            if task.starts_at
            else task.due_date
        )
        buckets.setdefault(day, []).append(task)
    weeks = [
        [
            {
                "date": day,
                "tasks": buckets.get(day, []),
                "outside": day.month != selected.month,
                "today": day == today,
            }
            for day in week
        ]
        for week in month_calendar.Calendar(firstweekday=0).monthdatescalendar(
            selected.year, selected.month
        )
    ]
    return render(
        request,
        "crm/calendar.html",
        {"tasks": tasks, "weeks": weeks, "month": selected.strftime("%Y-%m")},
    )


@login_required
@permission_required("crm.view_invoice", raise_exception=True)
def invoices(request):
    require_finance(request.user)
    qs = Invoice.objects.select_related("job", "client").prefetch_related(
        "lines", "payments"
    )
    if not request.user.is_superuser:
        qs = qs.filter(job__in=jobs_for(request.user))
    return render(request, "crm/invoices.html", {"invoices": qs})


def invoice_for(user, pk):
    require_finance(user)
    qs = Invoice.objects.select_related("client", "job")
    if not user.is_superuser:
        qs = qs.filter(job__in=jobs_for(user))
    return get_object_or_404(qs, pk=pk)


@login_required
@permission_required("crm.add_invoice", raise_exception=True)
def invoice_form(request, pk=None):
    require_finance(request.user)
    obj = invoice_for(request.user, pk) if pk else Invoice()
    if obj.issued_at:
        raise PermissionDenied("Vystavený doklad nelze přepsat.")
    initial = {}
    job = None
    if not pk and request.GET.get("job"):
        job = get_object_or_404(jobs_for(request.user), pk=request.GET["job"])
        ensure_mutable(job)
        obj.job = job
        obj.client = job.client
    if obj.job_id:
        ensure_mutable(obj.job)
    if obj.client_id:
        c = obj.client
        r = obj.recipient or (obj.job.billing_details if obj.job_id else {})
        initial.update(
            recipient_name=r.get("name", c.name),
            recipient_address=r.get("address", c.billing_address),
            recipient_company_id=r.get("company_id", c.company_id),
            recipient_email=r.get("email", c.email),
            recipient_tax_id=r.get("tax_id", c.tax_id),
        )
    cfg = company()
    if not pk:
        from datetime import date

        initial["issue_date"] = max(timezone.localdate(), date(cfg.invoice_year, 1, 1))
    initial["due_date"] = obj.due_date or initial.get(
        "issue_date", obj.issue_date
    ) + timedelta(days=cfg.due_days)
    form = f.InvoiceForm(request.POST or None, instance=obj, initial=initial)
    if not request.user.is_superuser:
        form.fields["job"].queryset = jobs_for(request.user)
        form.fields["client"].queryset = Client.objects.filter(
            job__in=jobs_for(request.user)
        ).distinct()
    advances = Invoice.objects.filter(kind="advance", issued_at__isnull=False)
    if not request.user.is_superuser:
        advances = advances.filter(job__in=jobs_for(request.user))
    if obj.pk:
        advances = advances.exclude(pk=obj.pk)
    form.fields["advance"].queryset = advances
    line_initial = (
        [
            {
                "description": f"{obj.job.get_service_display()} — {obj.job.address}",
                "quantity": 1,
                "unit_price": obj.job.agreed_price,
            }
        ]
        if obj.job_id and not pk
        else []
    )
    if not pk and request.GET.get("item"):
        item = get_object_or_404(PriceItem, pk=request.GET["item"], active=True)
        line_initial = [
            {"description": item.name, "quantity": 1, "unit_price": item.unit_price}
        ]
    lines = f.LineFormSet(
        request.POST or None,
        instance=obj,
        initial=line_initial if request.method != "POST" else None,
    )
    if request.method == "POST" and form.is_valid() and lines.is_valid():
        if form.cleaned_data.get("job"):
            ensure_mutable(form.cleaned_data["job"])
        with transaction.atomic():
            obj = form.save()
            lines.instance = obj
            lines.save()
            event(request.user, "Uložen návrh faktury", obj.job, invoice=obj.pk)
        return redirect("invoice_detail", pk=obj.pk)
    return render(
        request,
        "crm/invoice_form.html",
        {
            "form": form,
            "lines": lines,
            "title": "Návrh faktury",
            "catalog_items": PriceItem.objects.filter(active=True),
            "job_param": obj.job_id or "",
        },
    )


@login_required
@permission_required("crm.view_invoice", raise_exception=True)
def invoice_detail(request, pk):
    obj = invoice_for(request.user, pk)
    return render(request, "crm/invoice.html", {"invoice": obj})


@login_required
@permission_required("crm.change_invoice", raise_exception=True)
@require_POST
def invoice_action(request, pk):
    obj = invoice_for(request.user, pk)
    if obj.job:
        ensure_mutable(obj.job)
    action = request.POST.get("action")
    try:
        if action == "issue":
            issue_invoice(obj, request.user)
        elif action == "printed":
            if not obj.issued_at:
                raise ValidationError("Nejprve vystavte fakturu.")
            obj.printed_at = timezone.now()
            obj.save(update_fields=["printed_at"])
            event(request.user, "Potvrzen tisk faktury", obj.job, invoice=obj.pk)
        elif action == "pause":
            obj.reminders_paused = not obj.reminders_paused
            obj.save(update_fields=["reminders_paused"])
        elif action == "message":
            if not obj.issued_at:
                raise ValidationError("Nejprve vystavte fakturu.")
            msg = Message.objects.create(
                invoice=obj,
                job=obj.job,
                to=obj.recipient.get("email") or obj.client.email,
                subject=f"Faktura {obj.number}",
                body=f"Dobrý den,\n\nv příloze zasíláme {obj.number} na částku {obj.total:.2f} Kč. Splatnost {obj.due_date:%d.%m.%Y}, variabilní symbol {obj.variable_symbol}.\n\nDěkujeme.\nIng. Stanislav Lahodný",
            )
            return redirect("message_edit", pk=msg.pk)
        else:
            return HttpResponseBadRequest()
    except ValidationError as e:
        report_error(request, e)
    return redirect("invoice_detail", pk=pk)


@login_required
@permission_required("crm.view_invoice", raise_exception=True)
def invoice_file(request, pk, kind):
    obj = invoice_for(request.user, pk)
    if not obj.issued_at:
        return HttpResponseBadRequest("Nejprve vystavte doklad.")
    if kind != "pdf" and obj.total <= 0:
        return HttpResponseBadRequest("Doklad je plně vyúčtovaný zálohou.")
    if kind == "pdf":
        res = HttpResponse(bytes(obj.pdf), content_type="application/pdf")
        res["Content-Disposition"] = (
            f'inline; filename="{obj.number.replace(" ", "-")}.pdf"'
        )
        return res
    return HttpResponse(qr_png(obj), content_type="image/png")


@login_required
@permission_required("crm.add_payment", raise_exception=True)
def payment_new(request, pk):
    obj = invoice_for(request.user, pk)
    form = f.PaymentForm(
        request.POST or None,
        initial={"amount": max(obj.balance, Decimal("0")), "request_key": uuid.uuid4()},
    )
    if request.method == "POST" and form.is_valid():
        try:
            record_payment(obj, form.cleaned_data, request.user)
            return redirect("invoice_detail", pk=pk)
        except ValidationError as e:
            form.add_error(None, e)
    return form_page(request, form, "Zaevidovat přijatou platbu")


@login_required
@permission_required("crm.view_message", raise_exception=True)
def outbox(request):
    manager(request.user)
    return render(
        request,
        "crm/outbox.html",
        {
            "messages_list": Message.objects.all(),
            "email_enabled": __import__(
                "django.conf", fromlist=["settings"]
            ).settings.CRM_EMAIL_ENABLED,
        },
    )


@login_required
@permission_required("crm.change_message", raise_exception=True)
def message_edit(request, pk):
    manager(request.user)
    obj = get_object_or_404(Message, pk=pk)
    if obj.state not in ["draft", "failed"]:
        return redirect("outbox")
    form = f.MessageForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("outbox")
    return form_page(request, form, "Zkontrolovat e-mail před odesláním")


@login_required
@permission_required("crm.change_message", raise_exception=True)
@require_POST
def message_send(request, pk):
    manager(request.user)
    try:
        msg = send_message(get_object_or_404(Message, pk=pk), request.user)
        if msg.state == "sent":
            messages.success(
                request,
                "Zpráva byla přijata poštovním serverem. Doručení příjemci není tímto potvrzeno.",
            )
        elif msg.state == "failed":
            messages.error(request, msg.error)
    except ValidationError as e:
        report_error(request, e)
    return redirect("outbox")


@login_required
@permission_required("crm.add_message", raise_exception=True)
@require_POST
def requirements_message(request, pk):
    manager(request.user)
    job = get_object_or_404(jobs_for(request.user), pk=pk)
    ensure_mutable(job)
    missing = job.requirements.exclude(state="checked")
    msg = Message.objects.create(
        job=job,
        to=job.client.email,
        subject=f"Podklady k zakázce {job.number}",
        body="Dobrý den,\n\nprosíme o doplnění následujících podkladů:\n"
        + "\n".join("- " + r.title for r in missing)
        + "\n\nDěkujeme.",
    )
    return redirect("message_edit", pk=msg.pk)


@login_required
@permission_required("crm.add_handover", raise_exception=True)
def handover_new(request, pk):
    job = get_object_or_404(jobs_for(request.user), pk=pk)
    ensure_mutable(job)
    form = f.HandoverForm(
        request.POST or None,
        initial={"recipient": job.client.name, "method": "Elektronicky"},
    )
    if request.method == "POST" and form.is_valid():
        docs = job.documents.filter(final=True, deleted_at__isnull=True)
        if not docs.exists():
            form.add_error(None, "Nejprve nahrajte a označte finální výstup.")
        else:
            obj = form.save(commit=False)
            obj.job = job
            obj.files = list(docs.values("id", "name", "version", "sha256"))
            obj.save()
            job.status = "delivered"
            job.save(update_fields=["status"])
            event(request.user, "Zaznamenáno předání", job, handover=obj.pk)
            return redirect("job_detail", pk=pk)
    return form_page(request, form, "Zaznamenat předání výstupů")


@login_required
@permission_required("crm.change_job", raise_exception=True)
@require_POST
def archive(request, pk):
    manager(request.user)
    job = get_object_or_404(Job, pk=pk)
    try:
        archive_job(job, request.user)
        messages.success(
            request,
            "Zakázka archivována. Doba uchování je nastavitelná; právní lhůty ověřte podle dokumentace.",
        )
    except ValidationError as e:
        report_error(request, e)
    return redirect("job_detail", pk=pk)


@login_required
@permission_required("crm.view_document", raise_exception=True)
def archive_download(request, pk):
    manager(request.user)
    if not export_allowed(request.user):
        raise PermissionDenied
    job = get_object_or_404(jobs_for(request.user), pk=pk)
    try:
        content = archive_zip(job)
    except ValidationError as e:
        return HttpResponseBadRequest("; ".join(e.messages))
    event(request.user, "Exportována dokumentace", job)
    r = HttpResponse(content, content_type="application/zip")
    r["Content-Disposition"] = (
        f'attachment; filename="{job.number.replace("/", "-")}.zip"'
    )
    return r


@login_required
def reports(request):
    manager(request.user)
    require_finance(request.user)
    from django import forms

    class PeriodForm(forms.Form):
        start = forms.DateField(
            label="Od", required=False, widget=forms.DateInput(attrs={"type": "date"})
        )
        end = forms.DateField(
            label="Do", required=False, widget=forms.DateInput(attrs={"type": "date"})
        )

    form = PeriodForm(request.GET)
    jobs = Job.objects.all()
    inv = Invoice.objects.filter(issued_at__isnull=False)
    payments = Payment.objects.filter(voided_at__isnull=True)
    expenses = Expense.objects.all()
    inq = Inquiry.objects.all()
    if form.is_valid():
        for key, lookup in [("start", "gte"), ("end", "lte")]:
            d = form.cleaned_data.get(key)
            if d:
                jobs = jobs.filter(**{f"created_at__date__{lookup}": d})
                inv = inv.filter(**{f"issue_date__{lookup}": d})
                payments = payments.filter(**{f"date__{lookup}": d})
                expenses = expenses.filter(**{f"date__{lookup}": d})
                inq = inq.filter(**{f"created_at__date__{lookup}": d})
    else:
        return render(request, "crm/reports.html", {"period": form})
    billed = sum((i.subtotal for i in inv if i.kind == "invoice"), Decimal("0"))
    received = sum((p.signed_amount for p in payments), Decimal("0"))
    cost = expenses.aggregate(n=Sum("amount"))["n"] or Decimal("0")
    balances = [i for i in inv if i.balance > 0]
    ages = {
        "Ve splatnosti": Decimal("0"),
        "1–30 dní": Decimal("0"),
        "31–60 dní": Decimal("0"),
        "61–90 dní": Decimal("0"),
        "Nad 90 dní": Decimal("0"),
    }
    for i in balances:
        days = (timezone.localdate() - i.due_date).days
        key = (
            "Ve splatnosti"
            if days <= 0
            else (
                "1–30 dní"
                if days <= 30
                else (
                    "31–60 dní"
                    if days <= 60
                    else ("61–90 dní" if days <= 90 else "Nad 90 dní")
                )
            )
        )
        ages[key] += i.balance
    capacity = (
        Task.objects.filter(job__in=jobs, done=False)
        .values("assigned_to__username")
        .annotate(hours=Sum("estimated_hours"), tasks=Count("id"))
    )
    lost = inq.filter(status="lost").values("lost_reason").annotate(count=Count("id"))
    rows = []
    for j in jobs:
        ji = list(j.invoices.filter(issued_at__isnull=False, kind="invoice"))
        jcost = j.expenses.aggregate(n=Sum("amount"))["n"] or Decimal("0")
        rows.append(
            {
                "job": j,
                "billed": sum((i.subtotal for i in ji), Decimal("0")),
                "received": sum(
                    (i.paid for i in j.invoices.filter(issued_at__isnull=False)),
                    Decimal("0"),
                ),
                "cost": jcost,
                "contribution": j.agreed_price - jcost,
            }
        )
    if request.GET.get("export") == "csv":
        if not export_allowed(request.user):
            raise PermissionDenied
        output = io.StringIO()
        w = csv.writer(output, delimiter=";")
        w.writerow(
            [
                "Zakázka",
                "Klient",
                "Schválená cena",
                "Vyfakturováno",
                "Přijato",
                "Přímé náklady",
                "Příspěvek před režií",
            ]
        )
        for r in rows:
            w.writerow(
                [
                    r["job"].number,
                    safe_csv(r["job"].client.name),
                    r["job"].agreed_price,
                    r["billed"],
                    r["received"],
                    r["cost"],
                    r["contribution"],
                ]
            )
        res = HttpResponse(
            "\ufeff" + output.getvalue(), content_type="text/csv; charset=utf-8"
        )
        res["Content-Disposition"] = 'attachment; filename="report.csv"'
        return res
    return render(
        request,
        "crm/reports.html",
        {
            "period": form,
            "agreed": jobs.aggregate(n=Sum("agreed_price"))["n"] or 0,
            "billed": billed,
            "received": received,
            "cost": cost,
            "balances": balances,
            "rows": rows,
            "by_state": jobs.values("status").annotate(count=Count("id")),
            "by_source": inq.values("source").annotate(count=Count("id")),
            "inquiry_count": inq.count(),
            "accepted_count": inq.filter(status__in=["accepted", "converted"]).count(),
            "aging": ages.items(),
            "capacity": capacity,
            "lost": lost,
            "conversion": round(
                100
                * inq.filter(status__in=["accepted", "converted"]).count()
                / inq.count(),
                1,
            )
            if inq.count()
            else 0,
            "by_service": jobs.values("service").annotate(count=Count("id")),
            "by_cost": expenses.values("kind").annotate(amount=Sum("amount")),
            "overdue": jobs.exclude(status__in=["delivered", "closed"])
            .filter(due_date__lt=timezone.localdate())
            .count(),
        },
    )


def safe_csv(value):
    value = str(value)
    return "'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value


@login_required
@permission_required("crm.add_banktransaction", raise_exception=True)
def bank_import(request):
    from django import forms

    manager(request.user)
    require_finance(request.user)

    class ImportForm(forms.Form):
        file = forms.FileField(label="CSV: id;date;amount;vs;note")

    form = ImportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        upload = form.cleaned_data["file"]
        if upload.size > 2 * 1024 * 1024:
            form.add_error("file", "Maximum je 2 MB.")
        else:
            try:
                reader = csv.DictReader(
                    io.StringIO(upload.read().decode("utf-8-sig")), delimiter=";"
                )
                if not {"id", "date", "amount", "vs", "note"} <= set(
                    reader.fieldnames or []
                ):
                    raise ValueError("Chybí sloupce id;date;amount;vs;note.")
                from datetime import date

                data = []
                seen = set()
                for row in reader:
                    amount = Decimal(row["amount"].replace(",", "."))
                    day = date.fromisoformat(row["date"])
                    vs = row["vs"].strip()
                    key = row["id"].strip()
                    if (
                        not amount.is_finite()
                        or amount <= 0
                        or amount >= Decimal("10000000000")
                        or len(key) > 200
                        or not key
                        or key in seen
                        or not vs.isdigit()
                        or len(vs) > 10
                        or amount.as_tuple().exponent < -2
                    ):
                        raise ValueError(
                            "Neplatné ID, částka nebo VS. Importujte pouze příjmy."
                        )
                    seen.add(key)
                    data.append((key, day, amount, vs, row.get("note", "")[:300]))
                with transaction.atomic():
                    for key, day, amount, vs, note in data:
                        row, created = BankTransaction.objects.get_or_create(
                            external_id=key,
                            defaults={
                                "date": day,
                                "amount": amount,
                                "variable_symbol": vs,
                                "note": note,
                            },
                        )
                        if not created:
                            if (row.date, row.amount, row.variable_symbol) != (
                                day,
                                amount,
                                vs,
                            ):
                                raise ValueError(
                                    "Stejné bankovní ID obsahuje odlišná data."
                                )
                            continue
                        candidates = Invoice.objects.filter(
                            variable_symbol=vs, issued_at__isnull=False
                        )
                        if candidates.count() == 1:
                            invoice = candidates.get()
                            if invoice.balance == amount and not (
                                invoice.job and invoice.job.archived_at
                            ):
                                row.payment = record_payment(
                                    invoice,
                                    {
                                        "amount": amount,
                                        "date": day,
                                        "method": "bank",
                                        "reference": key,
                                        "request_key": uuid.uuid5(
                                            uuid.NAMESPACE_URL, "bank:" + key
                                        ),
                                    },
                                    request.user,
                                )
                                row.save()
                messages.success(
                    request,
                    "Výpis zpracován. Nejednoznačné platby zůstávají k ručnímu přiřazení.",
                )
                return redirect("bank_transactions")
            except (
                ValueError,
                InvalidOperation,
                UnicodeDecodeError,
                ValidationError,
            ) as e:
                form.add_error(None, "Import odmítnut: " + str(e))
    return form_page(request, form, "Import bankovního CSV", multipart=True)


@login_required
@permission_required("crm.view_banktransaction", raise_exception=True)
def bank_transactions(request):
    manager(request.user)
    require_finance(request.user)
    return render(
        request,
        "crm/bank.html",
        {"transactions": BankTransaction.objects.select_related("payment__invoice")},
    )


@login_required
@permission_required("crm.change_banktransaction", raise_exception=True)
def bank_match(request, pk):
    from django import forms

    manager(request.user)
    require_finance(request.user)
    obj = get_object_or_404(BankTransaction, pk=pk, payment__isnull=True)

    class MatchForm(forms.Form):
        invoice = forms.ModelChoiceField(
            label="Přiřadit k faktuře",
            queryset=Invoice.objects.filter(issued_at__isnull=False),
        )

    form = MatchForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            obj = BankTransaction.objects.select_for_update().get(pk=pk)
            if not obj.payment_id:
                try:
                    obj.payment = record_payment(
                        form.cleaned_data["invoice"],
                        {
                            "amount": obj.amount,
                            "date": obj.date,
                            "method": "bank",
                            "reference": obj.external_id,
                            "request_key": uuid.uuid5(
                                uuid.NAMESPACE_URL, "bank:" + obj.external_id
                            ),
                        },
                        request.user,
                    )
                    obj.save()
                except ValidationError as e:
                    form.add_error(None, e)
                    return form_page(request, form, "Přiřadit platbu")
        return redirect("bank_transactions")
    return form_page(
        request, form, f"Přiřadit {obj.amount} Kč / VS {obj.variable_symbol}"
    )


@login_required
def settings_view(request):
    manager(request.user)
    form = f.CompanyForm(request.POST or None, instance=company())
    if request.method == "POST" and form.is_valid():
        form.save()
        event(request.user, "Upraveno nastavení dodavatele a číselných řad")
        messages.success(request, "Nastavení uloženo. Vystavené doklady se nemění.")
        return redirect("settings")
    return form_page(
        request, form, "Dodavatel, číslování a splatnost", backup_available=True
    )


@login_required
@require_POST
def run_automation(request):
    manager(request.user)
    count = prepare_reminders()
    messages.success(
        request,
        f"Připraveno upomínek: {count}. Odesílání se řídí nastavením automatizace.",
    )
    return redirect("outbox")


@login_required
@permission_required("crm.add_clientlink", raise_exception=True)
def client_link_new(request, pk):
    manager(request.user)
    job = get_object_or_404(Job, pk=pk)
    ensure_mutable(job)
    form = f.ClientLinkForm(
        request.POST or None,
        initial={"expires": timezone.localdate() + timedelta(days=30)},
    )
    if request.method == "POST" and form.is_valid():
        link = form.save(commit=False)
        link.job = job
        link.save()
        event(request.user, "Vytvořen klientský odkaz", job, link=link.pk)
        return redirect("job_detail", pk=pk)
    return form_page(request, form, "Vytvořit klientský odkaz")


@login_required
@require_POST
def client_link_revoke(request, pk):
    manager(request.user)
    link = get_object_or_404(ClientLink, pk=pk)
    link.revoked = True
    link.save(update_fields=["revoked"])
    event(request.user, "Zneplatněn klientský odkaz", link.job, link=link.pk)
    return redirect("job_detail", pk=link.job_id)


def portal_link(token):
    return get_object_or_404(
        ClientLink.objects.select_related("job"),
        token=token,
        revoked=False,
        expires__gte=timezone.localdate(),
    )


def client_portal(request, token):
    link = portal_link(token)
    job = link.job
    form = f.PortalUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        if job.archived_at:
            raise PermissionDenied("Archiv je pouze ke čtení.")
        ensure_folders(job)
        folder = job.folders.get(name="Podklady od klienta")
        with transaction.atomic():
            for upload in form.cleaned_data["attachments"]:
                digest = hashlib.sha256()
                for chunk in upload.chunks():
                    digest.update(chunk)
                upload.seek(0)
                Document.objects.create(
                    job=job,
                    folder=folder,
                    name=Path(upload.name).name,
                    file=upload,
                    sha256=digest.hexdigest(),
                    internal=False,
                    uploaded_by=None,
                    origin="Klient přes odkaz",
                )
            event(
                None,
                "Klient dodal podklady",
                job,
                link=link.pk,
                note=form.cleaned_data["note"],
            )
        return render(
            request,
            "crm/public_done.html",
            {
                "title": "Podklady byly uloženy",
                "text": "Děkujeme, dokumenty zkontrolujeme.",
            },
        )
    outputs = (
        job.documents.filter(final=True, internal=False, deleted_at__isnull=True)
        if link.allow_outputs
        else []
    )
    return render(
        request,
        "crm/portal.html",
        {"link": link, "job": job, "form": form, "outputs": outputs},
    )


def portal_document(request, token, pk):
    link = portal_link(token)
    if not link.allow_outputs:
        raise PermissionDenied
    doc = get_object_or_404(
        Document,
        pk=pk,
        job=link.job,
        internal=False,
        final=True,
        deleted_at__isnull=True,
    )
    event(None, "Klient stáhl výstup", doc.job, document=doc.pk, link=link.pk)
    return FileResponse(
        doc.file.open("rb"),
        as_attachment=True,
        filename=Path(doc.name).name,
        content_type="application/octet-stream",
    )


@login_required
@permission_required("crm.add_extrawork", raise_exception=True)
def extra_new(request, pk):
    manager(request.user)
    require_finance(request.user)
    job = get_object_or_404(Job, pk=pk)
    ensure_mutable(job)
    form = f.ExtraWorkForm(request.POST or None, initial={"new_due_date": job.due_date})
    if request.method == "POST" and form.is_valid():
        extra = form.save(commit=False)
        extra.job = job
        extra.save()
        link = request.build_absolute_uri(reverse("extra_accept", args=[extra.token]))
        msg = Message.objects.create(
            job=job,
            to=job.client.email,
            subject=f"Změna rozsahu {job.number}",
            body=f"Dobrý den,\n\nnavrhujeme následující změnu:\n{extra.description}\n\nNavýšení ceny: {extra.price:.2f} Kč\nNový termín: {extra.new_due_date:%d.%m.%Y}\n\nProsíme o schválení na odkazu:\n{link}",
        )
        return redirect("message_edit", pk=msg.pk)
    return form_page(request, form, "Navrhnout vícepráci ke schválení")


def extra_accept(request, token):
    from django import forms

    from .services import accept_extra

    obj = get_object_or_404(ExtraWork.objects.select_related("job"), token=token)

    class ConsentForm(forms.Form):
        consent = forms.BooleanField(
            label="Souhlasím se změnou rozsahu, navýšením ceny a novým termínem."
        )

    form = ConsentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            accept_extra(obj)
            return redirect("extra_accept", token=token)
        except ValidationError as e:
            form.add_error(None, e)
    return render(request, "crm/extra.html", {"extra": obj, "form": form})


@login_required
@permission_required("crm.change_document", raise_exception=True)
def document_edit(request, pk):
    from django import forms

    doc = get_object_or_404(Document, pk=pk, job__in=jobs_for(request.user))
    ensure_mutable(doc.job)
    if (
        doc.internal
        and not request.user.is_superuser
        and not doc.allowed_users.filter(pk=request.user.pk).exists()
    ):
        raise PermissionDenied

    class EditForm(forms.ModelForm):
        class Meta:
            model = Document
            fields = ["name", "folder", "final", "internal", "allowed_users"]

    form = EditForm(request.POST or None, instance=doc)
    form.fields["folder"].queryset = doc.job.folders.all()
    if not request.user.is_superuser:
        form.fields.pop("internal")
        form.fields.pop("allowed_users", None)
    if request.method == "POST" and form.is_valid():
        form.save()
        event(request.user, "Upravena metadata dokumentu", doc.job, document=doc.pk)
        return redirect("job_detail", pk=doc.job_id)
    return form_page(request, form, "Název, složka a vlastnosti dokumentu")


@login_required
@permission_required("crm.view_inquiryattachment", raise_exception=True)
def inquiry_attachment(request, pk):
    manager(request.user)
    doc = get_object_or_404(InquiryAttachment, pk=pk)
    return FileResponse(
        doc.file.open("rb"),
        as_attachment=True,
        filename=Path(doc.name).name,
        content_type="application/octet-stream",
    )


@login_required
@require_POST
def notification_read(request, pk):
    item = get_object_or_404(Notification, pk=pk, user=request.user)
    item.read_at = timezone.now()
    item.save(update_fields=["read_at"])
    return redirect("dashboard")


@login_required
def catalog(request):
    manager(request.user)
    require_finance(request.user)
    return render(request, "crm/catalog.html", {"items": PriceItem.objects.all()})


@login_required
def catalog_edit(request, pk=None):
    from django import forms

    manager(request.user)
    require_finance(request.user)
    obj = get_object_or_404(PriceItem, pk=pk) if pk else None

    class PriceForm(forms.ModelForm):
        class Meta:
            model = PriceItem
            fields = ["name", "description", "unit_price", "active"]

    form = PriceForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("catalog")
    return form_page(request, form, "Ceníková položka")


@login_required
@permission_required("crm.change_payment", raise_exception=True)
def payment_void(request, pk):
    from django import forms

    from .services import void_payment

    payment = get_object_or_404(Payment, pk=pk)
    invoice = invoice_for(request.user, payment.invoice_id)

    class ReasonForm(forms.Form):
        reason = forms.CharField(
            label="Důvod zrušení chybného přiřazení",
            widget=forms.Textarea,
            max_length=2000,
        )

    form = ReasonForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            void_payment(payment, request.user, form.cleaned_data["reason"])
            return redirect("invoice_detail", pk=invoice.pk)
        except ValidationError as e:
            form.add_error(None, e)
    return form_page(request, form, "Zrušit chybný záznam platby (historie zůstane)")


@login_required
@permission_required("crm.add_client", raise_exception=True)
def ares_lookup(request):
    import json
    from urllib.error import HTTPError, URLError
    from urllib.request import urlopen

    from django import forms

    class AresForm(forms.Form):
        company_id = forms.RegexField(label="IČO (8 číslic)", regex=r"^\d{8}$")

    form = AresForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with urlopen(
                "https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/"
                + form.cleaned_data["company_id"],
                timeout=10,
            ) as response:
                data = json.loads(response.read(1024 * 1024))
            name = data.get("obchodniJmeno", "")
            if not name:
                raise ValueError("Subjekt nebyl nalezen.")
            request.session["ares_client"] = {
                "name": name,
                "company_id": data.get("ico"),
                "tax_id": data.get("dic", ""),
                "billing_address": data.get("sidlo", {}).get("textovaAdresa", ""),
                "client_type": "business",
            }
            return redirect("client_new")
        except (URLError, HTTPError, ValueError, KeyError):
            form.add_error(
                None,
                "ARES není dostupný nebo subjekt nebyl nalezen. Klienta lze vyplnit ručně. Síť musí povolovat ares.gov.cz.",
            )
    return form_page(request, form, "Načíst klienta z ARESu")


@login_required
@permission_required("crm.view_job", raise_exception=True)
def archives(request):
    qs = jobs_for(request.user).filter(archived_at__isnull=False)
    if request.GET.get("expiring"):
        qs = qs.filter(retain_until__lte=timezone.localdate() + timedelta(days=90))
    return render(request, "crm/archives.html", {"jobs": qs})


@login_required
@permission_required("crm.change_job", raise_exception=True)
def retention_edit(request, pk):
    from django import forms

    manager(request.user)
    job = get_object_or_404(Job, pk=pk, archived_at__isnull=False)

    class RetentionForm(forms.Form):
        retain_until = forms.DateField(
            label="Uchovat do",
            widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        )
        hold = forms.BooleanField(
            label="Pozastavit skartaci (kontrola / spor)", required=False
        )
        reason = forms.CharField(
            label="Důvod změny", widget=forms.Textarea, max_length=2000
        )

    form = RetentionForm(
        request.POST or None,
        initial={"retain_until": job.retain_until, "hold": job.hold},
    )
    if request.method == "POST" and form.is_valid():
        if form.cleaned_data["retain_until"] < job.retain_until:
            form.add_error(
                "retain_until", "V tomto formuláři lze dobu uchování pouze prodloužit."
            )
        else:
            job.retain_until = form.cleaned_data["retain_until"]
            job.hold = form.cleaned_data["hold"]
            job.save(update_fields=["retain_until", "hold"])
            event(
                request.user,
                "Změněna doba uchování",
                job,
                reason=form.cleaned_data["reason"],
                until=str(job.retain_until),
                hold=job.hold,
            )
            return redirect("archives")
    return form_page(request, form, "Doba uchování a blokace skartace")


@login_required
@require_POST
def backup_download(request):
    import tempfile

    from django.core.management import call_command

    manager(request.user)
    if not export_allowed(request.user):
        raise PermissionDenied
    temp = tempfile.TemporaryDirectory()
    try:
        path = Path(temp.name) / "crm-backup.zip"
        call_command("backup_crm", output=str(path), stdout=io.StringIO())
        response = FileResponse(
            path.open("rb"),
            as_attachment=True,
            filename=f"lahodny-crm-zaloha-{timezone.localdate()}.zip",
            content_type="application/zip",
        )
        response._resource_closers.append(temp.cleanup)
        event(request.user, "Stažena úplná záloha CRM")
        return response
    except Exception:
        temp.cleanup()
        raise
