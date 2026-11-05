"""Client cards, personal calendar, mail intake and signed website integration."""

import hashlib
import hmac
import json
import time
from datetime import datetime

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .forms import CalendarEntryForm
from .mailbox import MAX_EMAIL_BYTES, import_email, mail_to_inquiry, sync_mailbox
from .models import (
    CalendarEntry,
    Client,
    Inquiry,
    Invoice,
    Job,
    MailAttachment,
    MailboxSync,
    Message,
    ReceivedMail,
    WebsiteSource,
)
from .office import form_page, manager
from .services import clients_for, company, event, finance, jobs_for


@login_required
@permission_required("crm.view_client", raise_exception=True)
def client_detail(request, pk):
    client = get_object_or_404(clients_for(request.user), pk=pk)
    jobs = jobs_for(request.user).filter(client=client)
    invoices = Invoice.objects.filter(client=client)
    if not request.user.is_superuser:
        invoices = invoices.filter(job__in=jobs)
    if not finance(request.user) or not request.user.has_perm("crm.view_invoice"):
        invoices = Invoice.objects.none()
    inquiries = (
        Inquiry.objects.filter(client=client)
        if request.user.is_superuser
        else Inquiry.objects.none()
    )
    return render(
        request,
        "crm/client_detail.html",
        {"client": client, "jobs": jobs, "invoices": invoices, "inquiries": inquiries},
    )


@login_required
@permission_required("crm.view_client", raise_exception=True)
def client_invoice_defaults(request, pk):
    client = get_object_or_404(clients_for(request.user), pk=pk)
    if not finance(request.user) or not request.user.has_perm("crm.add_invoice"):
        raise PermissionDenied
    return JsonResponse(
        {
            "name": client.name,
            "address": client.billing_address,
            "company_id": client.company_id,
            "tax_id": client.tax_id,
            "email": client.email,
            "payment_days": client.payment_days or company().due_days,
            "notes": client.notes,
        }
    )


@login_required
@permission_required("crm.add_calendarentry", raise_exception=True)
def calendar_entry(request, pk=None):
    obj = get_object_or_404(CalendarEntry, pk=pk, owner=request.user) if pk else None
    if pk and not request.user.has_perm("crm.change_calendarentry"):
        raise PermissionDenied
    initial = {}
    if not pk and request.GET.get("day"):
        try:
            initial["starts_at"] = datetime.strptime(
                request.GET["day"] + "T09:00", "%Y-%m-%dT%H:%M"
            )
        except ValueError:
            pass
    form = CalendarEntryForm(request.POST or None, instance=obj, initial=initial)
    form.fields["job"].queryset = (
        jobs_for(request.user)
        if request.user.has_perm("crm.view_job")
        else Job.objects.none()
    )
    if request.method == "POST" and form.is_valid():
        entry = form.save(commit=False)
        entry.owner = request.user
        entry.save()
        return redirect(
            reverse("calendar")
            + "?month="
            + timezone.localtime(entry.starts_at).strftime("%Y-%m")
        )
    return form_page(request, form, "Vlastní zápis do kalendáře")


@login_required
@permission_required("crm.delete_calendarentry", raise_exception=True)
@require_POST
def calendar_entry_delete(request, pk):
    entry = get_object_or_404(CalendarEntry, pk=pk, owner=request.user)
    entry.delete()
    return redirect("calendar")


@login_required
@permission_required("crm.view_receivedmail", raise_exception=True)
def inbox(request):
    manager(request.user)
    return render(
        request,
        "crm/inbox.html",
        {
            "mail_list": ReceivedMail.objects.select_related("inquiry"),
            "imap_enabled": settings.CRM_IMAP_ENABLED,
            "last_sync": MailboxSync.objects.first(),
        },
    )


@login_required
@permission_required("crm.add_receivedmail", raise_exception=True)
def email_import(request):
    manager(request.user)

    class ImportForm(forms.Form):
        file = forms.FileField(label="Uložený e-mail (.eml)")

    form = ImportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        upload = form.cleaned_data["file"]
        if upload.size > MAX_EMAIL_BYTES:
            form.add_error("file", "Nejvýše 25 MB.")
        elif not upload.name.lower().endswith(".eml"):
            form.add_error("file", "Vyberte soubor .eml.")
        else:
            try:
                mail, created = import_email(upload.read())
                return redirect("received_mail", pk=mail.pk)
            except ValidationError as error:
                form.add_error(None, error)
    return form_page(request, form, "Vložit e-mail do CRM", multipart=True)


@login_required
@permission_required("crm.view_receivedmail", raise_exception=True)
def received_mail(request, pk):
    manager(request.user)
    mail = get_object_or_404(ReceivedMail, pk=pk)
    return render(request, "crm/received_mail.html", {"mail": mail})


@login_required
@permission_required("crm.add_inquiry", raise_exception=True)
@require_POST
def email_convert(request, pk):
    manager(request.user)
    if not request.user.has_perm("crm.view_receivedmail"):
        raise PermissionDenied
    try:
        inquiry = mail_to_inquiry(get_object_or_404(ReceivedMail, pk=pk), request.user)
    except ValidationError as error:
        messages.error(request, "; ".join(error.messages))
        return redirect("received_mail", pk=pk)
    messages.success(
        request,
        "Poptávka uložena. Zkontrolujte službu a doplňte adresu nemovitosti před nabídkou.",
    )
    return redirect("inquiry_detail", pk=inquiry.pk)


@login_required
@permission_required("crm.view_mailattachment", raise_exception=True)
def email_attachment(request, pk):
    manager(request.user)
    item = get_object_or_404(MailAttachment, pk=pk)
    return FileResponse(
        item.file.open("rb"),
        as_attachment=True,
        filename=item.name,
        content_type="application/octet-stream",
    )


@login_required
@permission_required("crm.add_receivedmail", raise_exception=True)
@require_POST
def email_sync(request):
    manager(request.user)
    try:
        messages.success(request, f"Příjem dokončen. Nových zpráv: {sync_mailbox()}.")
    except ValidationError as error:
        messages.error(request, "; ".join(error.messages))
    return redirect("inbox")


@csrf_exempt
@require_POST
def website_inquiry(request, slug="enepru"):
    # Machine-to-machine endpoint: HMAC is the authentication, never a browser secret.
    source = get_object_or_404(WebsiteSource, slug=slug, active=True)
    from .intake import decoded_attachments, receive, website_secret

    secret = website_secret(source)
    if not secret:
        return JsonResponse(
            {"error": "Napojení tohoto webu není nastavené."}, status=503
        )
    if len(request.body) > 24 * 1024 * 1024:
        return JsonResponse({"error": "Příliš velký požadavek."}, status=413)
    stamp = request.headers.get("X-CRM-Timestamp", "")
    try:
        if abs(time.time() - int(stamp)) > 300:
            raise ValueError
    except ValueError:
        return JsonResponse({"error": "Neplatný čas podpisu."}, status=403)
    expected = hmac.new(
        secret.encode(), stamp.encode() + b"." + request.body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, request.headers.get("X-CRM-Signature", "")):
        return JsonResponse({"error": "Neplatný podpis."}, status=403)
    try:
        data = json.loads(request.body)
        attachments = decoded_attachments(data.get("attachments", []))
        obj, created = receive(source, data, attachments=attachments)
    except (ValueError, TypeError, AttributeError):
        return JsonResponse({"error": "Neplatné JSON."}, status=400)
    except ValidationError as error:
        return JsonResponse(
            {"error": "; ".join(error.messages)},
            status=409 if getattr(error, "code", None) == "conflict" else 400,
        )
    return JsonResponse(
        {"id": obj.pk, "number": f"P{obj.pk:05d}", "created": created},
        status=201 if created else 200,
    )


@login_required
def websites(request, pk=None):
    manager(request.user)
    if pk is not None:
        source = get_object_or_404(WebsiteSource, pk=pk)
    else:
        source = None

    class SourceForm(forms.ModelForm):
        class Meta:
            model = WebsiteSource
            fields = ["name", "slug", "domain", "secret_env", "active"]

        def clean_domain(self):
            value = self.cleaned_data["domain"].strip().lower()
            import re

            if not re.fullmatch(r"[a-z0-9.-]+", value) or "." not in value:
                raise forms.ValidationError("Zadejte doménu bez https:// a bez cesty.")
            return value

        def clean_secret_env(self):
            import re

            value = self.cleaned_data.get("secret_env", "")
            if not value:
                return value
            if not re.fullmatch(r"CRM_WEBHOOK_[A-Z0-9_]+", value):
                raise forms.ValidationError(
                    "Název musí začínat CRM_WEBHOOK_ a obsahovat jen velká písmena, číslice a podtržítka. Nezadávejte sem samotný klíč."
                )
            return value

        def clean(self):
            from django.utils.text import slugify

            data = super().clean()
            if not data.get("slug") and data.get("domain"):
                data["slug"] = slugify(data["domain"].replace(".", "-"))
            if not data.get("secret_env") and data.get("slug"):
                data["secret_env"] = (
                    "CRM_WEBHOOK_" + data["slug"].upper().replace("-", "_") + "_KEY"
                )
            return data

    form = SourceForm(
        request.POST or None,
        instance=source,
        initial={} if source else {"secret_env": "", "slug": ""},
    )
    form.fields["slug"].required = False
    form.fields["secret_env"].required = False
    if source:
        form.fields["slug"].disabled = True
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        event(request.user, "Upraven zdroj webových poptávek", website=obj.pk)
        return redirect("websites")
    sources = []
    for item in WebsiteSource.objects.all():
        from .intake import website_secret

        ready = bool(website_secret(item))
        sources.append(
            {
                "source": item,
                "configured": ready,
                "endpoint": reverse("website_source_inquiry", args=[item.slug]),
            }
        )
    return render(
        request,
        "crm/websites.html",
        {"sources": sources, "form": form, "editing": source},
    )


@login_required
@permission_required("crm.add_offer", raise_exception=True)
def direct_offer(request):
    from datetime import timedelta

    from .forms import DirectOfferForm
    from .services import create_offer

    manager(request.user)
    initial = {"valid_until": timezone.localdate() + timedelta(days=14)}
    if request.GET.get("client"):
        c = get_object_or_404(Client, pk=request.GET["client"])
        initial.update(client=c, customer_name=c.name, customer_email=c.email)
    form = DirectOfferForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        with transaction.atomic():
            inquiry = Inquiry.objects.create(
                name=data["customer_name"],
                email=data["customer_email"],
                address=data["address"],
                service=data["service"],
                description=data["scope"],
                source="Přímá nabídka",
                origin="direct_offer",
                client=data.get("client"),
            )
            offer = create_offer(
                inquiry,
                {
                    k: data[k]
                    for k in ["scope", "price", "due_date", "valid_until", "terms"]
                },
                request.user,
            )
            link = request.build_absolute_uri(
                reverse("public_offer", args=[offer.token])
            )
            Message.objects.create(
                inquiry=inquiry,
                offer=offer,
                to=inquiry.email,
                subject="Cenová nabídka",
                body=f"Dobrý den,\n\n{offer.scope}\n\nCena {offer.price:.2f} Kč, termín {offer.due_date:%d.%m.%Y}.\n\n{offer.terms}\n\nNabídku můžete potvrdit na odkazu:\n{link}",
                dedupe_key=f"offer:{offer.pk}",
            )
        return redirect("inquiry_detail", pk=inquiry.pk)
    return form_page(request, form, "Nová nabídka bez předchozí poptávky")


@login_required
@permission_required("crm.view_document", raise_exception=True)
def documents(request):
    from .services import documents_for

    query = request.GET.get("q", "").strip()
    docs = documents_for(request.user).select_related("job", "folder", "uploaded_by")
    if query:
        docs = docs.filter(Q(name__icontains=query) | Q(job__number__icontains=query))
    if request.GET.get("standalone"):
        docs = docs.filter(job__isnull=True)
    return render(request, "crm/documents.html", {"documents": docs, "query": query})


@login_required
@permission_required("crm.add_document", raise_exception=True)
def library_upload(request):
    from .forms import MultipleFiles
    from .models import Document
    from .services import ensure_folders

    class LibraryForm(forms.Form):
        files = MultipleFiles(
            label="Soubory (nejvýše 5, celkem 25 MB)",
            widget=__import__(
                "crm.forms", fromlist=["MultipleFileInput"]
            ).MultipleFileInput(),
        )
        job = forms.ModelChoiceField(
            label="Zakázka (nepovinné)", queryset=Job.objects.none(), required=False
        )

    form = LibraryForm(request.POST or None, request.FILES or None)
    form.fields["job"].queryset = jobs_for(request.user)
    if request.method == "POST" and form.is_valid():
        job = form.cleaned_data.get("job")
        if job and job.archived_at:
            raise PermissionDenied("Pracovní archiv je uzamčený.")
        with transaction.atomic():
            folder = None
            if job:
                ensure_folders(job)
                folder = job.folders.get(name="Podklady od klienta")
            for upload in form.cleaned_data["files"]:
                digest = hashlib.sha256()
                for chunk in upload.chunks():
                    digest.update(chunk)
                upload.seek(0)
                doc = Document.objects.create(
                    job=job,
                    folder=folder,
                    name=upload.name[:240],
                    file=upload,
                    sha256=digest.hexdigest(),
                    uploaded_by=request.user,
                    internal=not bool(job),
                )
                event(request.user, "Uložen dokument", job, document=doc.pk)
        return redirect("documents")
    return form_page(request, form, "Uložit dokumenty i bez zakázky", multipart=True)


@login_required
@permission_required("crm.change_document", raise_exception=True)
def library_assign(request, pk):
    from .services import documents_for, ensure_folders

    doc = get_object_or_404(
        documents_for(request.user), pk=pk, job__isnull=True, deleted_at__isnull=True
    )

    class AssignForm(forms.Form):
        job = forms.ModelChoiceField(
            label="Přiřadit k zakázce", queryset=Job.objects.none()
        )

    form = AssignForm(request.POST or None)
    form.fields["job"].queryset = jobs_for(request.user).filter(
        archived_at__isnull=True
    )
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            job = form.cleaned_data["job"]
            ensure_folders(job)
            doc.job = job
            doc.folder = job.folders.get(name="Podklady od klienta")
            doc.save()
            if not request.user.is_superuser:
                doc.allowed_users.add(request.user)
            event(
                request.user,
                "Přiřazen samostatný dokument k zakázce",
                job,
                document=doc.pk,
            )
        return redirect("job_detail", pk=job.pk)
    return form_page(request, form, "Přiřadit dokument k zakázce")
