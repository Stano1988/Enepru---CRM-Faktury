from django import forms

from .models import Client, Job


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = [
            "name",
            "client_type",
            "email",
            "phone",
            "company_id",
            "tax_id",
            "billing_address",
            "mailing_address",
        ]


class JobForm(forms.ModelForm):
    class Meta:
        model = Job
        fields = [
            "title",
            "client",
            "address",
            "service",
            "status",
            "due_date",
            "assigned_to",
            "next_step",
            "description",
            "property",
            "contact",
            "internal_due",
            "agreed_price",
        ]
        widgets = {
            k: forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
            for k in ["due_date", "internal_due"]
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["agreed_price"].required = False

    def clean_agreed_price(self):
        return self.cleaned_data.get("agreed_price") or 0

    def clean(self):
        data = super().clean()
        for field in ["property", "contact"]:
            obj = data.get(field)
            if obj and data.get("client") and obj.client_id != data["client"].pk:
                self.add_error(field, "Záznam patří jinému klientovi.")
        return data


class NoteForm(forms.Form):
    text = forms.CharField(
        label="Nová interní poznámka",
        widget=forms.Textarea(attrs={"rows": 3}),
        max_length=10000,
    )


from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory
from django.utils import timezone

from .models import (
    ClientLink,
    Company,
    Contact,
    Document,
    Expense,
    ExtraWork,
    Handover,
    Inquiry,
    Invoice,
    InvoiceLine,
    Message,
    Offer,
    Payment,
    Property,
    Requirement,
    Task,
)


class PropertyForm(forms.ModelForm):
    class Meta:
        model = Property
        fields = [
            "client",
            "name",
            "address",
            "cadastral_area",
            "parcels",
            "building_type",
            "technical_notes",
        ]


class ContactForm(forms.ModelForm):
    class Meta:
        model = Contact
        fields = ["client", "name", "role", "email", "phone"]


class InquiryForm(forms.ModelForm):
    class Meta:
        model = Inquiry
        fields = [
            "name",
            "email",
            "phone",
            "address",
            "service",
            "description",
            "requested_date",
        ]
        widgets = {
            "requested_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
        }


class PublicInquiryForm(InquiryForm):
    submission_key = forms.UUIDField(widget=forms.HiddenInput)
    website = forms.CharField(required=False, widget=forms.HiddenInput)
    privacy = forms.BooleanField(
        label="Beru na vědomí zpracování údajů pro vyřízení této poptávky."
    )

    def clean_website(self):
        if self.cleaned_data["website"]:
            raise ValidationError("Formulář nebyl přijat.")
        return ""


class InquiryEditForm(forms.ModelForm):
    class Meta:
        model = Inquiry
        fields = [
            "name",
            "email",
            "phone",
            "address",
            "service",
            "description",
            "requested_date",
            "source",
            "status",
            "lost_reason",
            "client",
        ]
        widgets = {
            "requested_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
        }


class OfferForm(forms.ModelForm):
    class Meta:
        model = Offer
        fields = ["scope", "price", "due_date", "valid_until", "terms"]
        widgets = {
            k: forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
            for k in ["due_date", "valid_until"]
        }

    def clean(self):
        data = super().clean()
        if data.get("valid_until") and data["valid_until"] < timezone.localdate():
            self.add_error("valid_until", "Platnost již uplynula.")
        if data.get("due_date") and data["due_date"] < timezone.localdate():
            self.add_error("due_date", "Termín je v minulosti.")
        return data


class AcceptForm(forms.Form):
    tax_id = forms.CharField(label="DIČ (pokud máte)", max_length=30, required=False)
    name = forms.CharField(label="Fakturační jméno / firma", max_length=200)
    billing_address = forms.CharField(
        label="Fakturační adresa", widget=forms.Textarea(attrs={"rows": 3})
    )
    company_id = forms.CharField(label="IČO", max_length=20, required=False)
    consent = forms.BooleanField(
        label="Potvrzuji uvedený rozsah, cenu, termín a podmínky nabídky."
    )


class DocumentForm(forms.ModelForm):
    previous = forms.ModelChoiceField(
        label="Nová verze dokumentu (nepovinné)",
        queryset=Document.objects.none(),
        required=False,
    )

    class Meta:
        model = Document
        fields = [
            "folder",
            "name",
            "file",
            "previous",
            "final",
            "internal",
            "allowed_users",
        ]

    def __init__(self, *args, job, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["folder"].queryset = job.folders.all()
        self.fields["previous"].queryset = job.documents.filter(
            deleted_at__isnull=True, next_version__isnull=True
        )

    def clean_file(self):
        from pathlib import Path

        f = self.cleaned_data["file"]
        allowed = {
            ".pdf",
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".heic",
            ".docx",
            ".xlsx",
            ".xlsm",
            ".dwg",
            ".dxf",
            ".ifc",
            ".txt",
            ".csv",
            ".zip",
            ".xml",
            ".odt",
            ".ods",
            ".doc",
            ".xls",
        }
        if Path(f.name).suffix.lower() not in allowed:
            raise ValidationError("Tento typ souboru není povolen.")
        if f.size > 25 * 1024 * 1024:
            raise ValidationError("Maximum je 25 MB na soubor.")
        return f


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = [
            "title",
            "description",
            "assigned_to",
            "due_date",
            "kind",
            "starts_at",
            "estimated_hours",
            "actual_hours",
            "done",
        ]
        widgets = {
            "due_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["starts_at"].widget = forms.DateTimeInput(
            attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
        )


class RequirementForm(forms.ModelForm):
    class Meta:
        model = Requirement
        fields = ["title", "state"]


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ["title", "kind", "recipient", "amount", "date", "paid"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}


class InvoiceForm(forms.ModelForm):
    recipient_name = forms.CharField(label="Odběratel", max_length=200)
    recipient_address = forms.CharField(
        label="Fakturační adresa", widget=forms.Textarea(attrs={"rows": 3})
    )
    recipient_company_id = forms.CharField(
        label="IČO odběratele", max_length=20, required=False
    )
    recipient_email = forms.EmailField(label="E-mail odběratele")
    recipient_tax_id = forms.CharField(
        label="DIČ odběratele", max_length=30, required=False
    )

    class Meta:
        model = Invoice
        fields = ["client", "job", "kind", "issue_date", "due_date", "advance"]
        widgets = {
            k: forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
            for k in ["issue_date", "due_date"]
        }

    def clean(self):
        data = super().clean()
        if (
            data.get("job")
            and data.get("client")
            and data["job"].client_id != data["client"].pk
        ):
            self.add_error("client", "Klient neodpovídá vybrané zakázce.")
        if (
            data.get("due_date")
            and data.get("issue_date")
            and data["due_date"] < data["issue_date"]
        ):
            self.add_error("due_date", "Splatnost nesmí být před vystavením.")
        advance = data.get("advance")
        if advance:
            if (
                data.get("kind") != "invoice"
                or advance.kind != "advance"
                or not advance.issued_at
                or advance.balance > 0
                or advance.client_id != getattr(data.get("client"), "pk", None)
                or advance.job_id != getattr(data.get("job"), "pk", None)
            ):
                self.add_error(
                    "advance",
                    "Vyberte uhrazenou zálohovou výzvu stejného klienta a zakázky.",
                )
        return data

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.recipient = {
            "name": self.cleaned_data["recipient_name"],
            "address": self.cleaned_data["recipient_address"],
            "company_id": self.cleaned_data["recipient_company_id"],
            "email": self.cleaned_data["recipient_email"],
            "tax_id": self.cleaned_data["recipient_tax_id"],
        }
        if commit:
            obj.save()
        return obj


LineFormSet = inlineformset_factory(
    Invoice,
    InvoiceLine,
    fields=["description", "quantity", "unit_price"],
    extra=3,
    can_delete=True,
    min_num=1,
    validate_min=True,
    max_num=100,
    validate_max=True,
)


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ["amount", "kind", "date", "method", "reference", "request_key"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "request_key": forms.HiddenInput(),
        }


class MessageForm(forms.ModelForm):
    class Meta:
        model = Message
        fields = ["to", "subject", "body"]


class HandoverForm(forms.ModelForm):
    class Meta:
        model = Handover
        fields = ["recipient", "method", "date", "note"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}


class CompanyForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = [
            "name",
            "address",
            "company_id",
            "email",
            "bank_account",
            "bank_name",
            "invoice_year",
            "invoice_next",
            "due_days",
            "retention_years",
        ]

    def clean_bank_account(self):
        from .services import iban

        iban(self.cleaned_data["bank_account"])
        return self.cleaned_data["bank_account"]


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFiles(forms.FileField):
    def clean(self, data, initial=None):
        if not data:
            return []
        values = data if isinstance(data, (list, tuple)) else [data]
        if len(values) > 5:
            raise ValidationError("Najednou lze nahrát nejvýše 5 souborů.")
        values = [super(MultipleFiles, self).clean(x, initial) for x in values]
        if sum(x.size for x in values) > 25 * 1024 * 1024:
            raise ValidationError("Celkem lze nahrát nejvýše 25 MB.")
        allowed = {
            ".pdf",
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".heic",
            ".docx",
            ".xlsx",
            ".xlsm",
            ".dwg",
            ".dxf",
            ".ifc",
            ".txt",
            ".csv",
            ".zip",
            ".xml",
            ".odt",
            ".ods",
            ".doc",
            ".xls",
        }
        from pathlib import Path

        for value in values:
            if Path(value.name).suffix.lower() not in allowed:
                raise ValidationError("Nepovolený typ souboru: " + value.name)
        return values


PublicInquiryForm.base_fields["attachments"] = MultipleFiles(
    label="Podklady (nejvýše 5 souborů, celkem 25 MB)",
    required=False,
    widget=MultipleFileInput(),
)


class PortalUploadForm(forms.Form):
    attachments = MultipleFiles(label="Přidat podklady", widget=MultipleFileInput())
    note = forms.CharField(
        label="Zpráva k podkladům",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        max_length=2000,
    )


class ClientLinkForm(forms.ModelForm):
    class Meta:
        model = ClientLink
        fields = ["expires", "allow_outputs"]
        widgets = {
            "expires": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
        }

    def clean_expires(self):
        d = self.cleaned_data["expires"]
        if d < timezone.localdate():
            raise ValidationError("Platnost nemůže být v minulosti.")
        return d


class ExtraWorkForm(forms.ModelForm):
    class Meta:
        model = ExtraWork
        fields = ["description", "price", "new_due_date"]
        widgets = {
            "new_due_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
        }
