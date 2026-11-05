import uuid
from builtins import property as computed_property
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import F
from django.utils import timezone


class Client(models.Model):
    name = models.CharField("Jméno / firma", max_length=200)
    email = models.EmailField("E-mail", blank=True)
    phone = models.CharField("Telefon", max_length=40, blank=True)
    company_id = models.CharField("IČO", max_length=20, blank=True)
    billing_address = models.TextField("Fakturační adresa", blank=True)
    tax_id = models.CharField("DIČ", max_length=30, blank=True)
    mailing_address = models.TextField(
        "Korespondenční adresa (pokud se liší)", blank=True
    )
    client_type = models.CharField(
        "Typ klienta",
        max_length=30,
        default="person",
        choices=[
            ("person", "Soukromá osoba"),
            ("business", "Firma / podnikatel"),
            ("association", "SVJ / družstvo"),
            ("public", "Obec / organizace"),
            ("partner", "Obchodní partner"),
        ],
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_clients",
    )
    notes = models.TextField("Poznámky a požadavky klienta", blank=True)
    payment_days = models.PositiveIntegerField(
        "Individuální splatnost (dní)",
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(3650)],
    )

    def __str__(self):
        return self.name


class Sequence(models.Model):
    year = models.PositiveIntegerField(unique=True)
    value = models.PositiveIntegerField(default=0)


class Job(models.Model):
    SERVICES = [
        ("penb", "PENB"),
        ("passport", "Pasport"),
        ("both", "PENB + pasport"),
        ("other", "Jiná služba"),
    ]
    STATES = [
        ("new", "Příprava"),
        ("waiting", "Čeká na podklady"),
        ("survey", "Zaměření"),
        ("working", "Zpracování"),
        ("review", "Kontrola"),
        ("ready", "Připraveno k předání"),
        ("delivered", "Předáno"),
        ("closed", "Uzavřeno"),
    ]
    number = models.CharField("Číslo", max_length=24, unique=True, editable=False)
    title = models.CharField("Název zakázky", max_length=250)
    client = models.ForeignKey(Client, on_delete=models.PROTECT, verbose_name="Klient")
    address = models.TextField("Adresa nemovitosti")
    service = models.CharField(
        "Služba", max_length=20, choices=SERVICES, default="penb"
    )
    status = models.CharField("Stav", max_length=20, choices=STATES, default="new")
    due_date = models.DateField("Termín vyhotovení")
    description = models.TextField("Popis zakázky", blank=True)
    next_step = models.CharField("Další krok", max_length=250, blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        verbose_name="Odpovědná osoba",
    )
    property = models.ForeignKey(
        "Property",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        verbose_name="Nemovitost",
    )
    contact = models.ForeignKey(
        "Contact",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        verbose_name="Kontakt pro zaměření",
    )
    internal_due = models.DateField("Interní termín", null=True, blank=True)
    agreed_price = models.DecimalField(
        "Schválená cena",
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )
    billing_text = models.TextField("Text pro fakturu (nepovinné)", blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    retain_until = models.DateField("Uchovat do", null=True, blank=True)
    hold = models.BooleanField("Pozastavená skartace", default=False)
    archive_manifest = models.JSONField(default=dict, blank=True)
    billing_details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["due_date", "id"]

    @computed_property
    def overdue(self):
        return self.due_date < timezone.localdate() and self.status not in (
            "delivered",
            "closed",
        )

    def save(self, *args, **kwargs):
        if self.number:
            with transaction.atomic():
                old = type(self).objects.select_for_update().filter(pk=self.pk).first()
                if old and old.archived_at:
                    fields = [
                        f.attname
                        for f in self._meta.concrete_fields
                        if f.name not in ["retain_until", "hold"]
                    ]
                    if any(getattr(old, key) != getattr(self, key) for key in fields):
                        from django.core.exceptions import ValidationError

                        raise ValidationError("Archivovanou zakázku nelze měnit.")
                return super().save(*args, **kwargs)
        # Pilot numbering starts in 2027; later years have their own series.
        year = max(2027, timezone.localdate().year)
        with transaction.atomic():
            seq, _ = Sequence.objects.get_or_create(year=year)
            seq = Sequence.objects.select_for_update().get(pk=seq.pk)
            if seq.value >= 999:
                from django.core.exceptions import ValidationError

                raise ValidationError(
                    "Roční řada 999 zakázek je vyčerpaná. Je třeba rozšířit formát čísel a VS."
                )
            Sequence.objects.filter(pk=seq.pk).update(value=F("value") + 1)
            seq.refresh_from_db()
            self.number = f"Z{year % 100:02d}/{seq.value:03d}"
            super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.number} — {self.title}"


class JobChild(models.Model):
    """Serialize writes with the parent and enforce archive lock on child records."""

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if (
                self.job_id
                and Job.objects.select_for_update().get(pk=self.job_id).archived_at
            ):
                from django.core.exceptions import ValidationError

                raise ValidationError("Archivovaná zakázka je pouze ke čtení.")
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            if (
                self.job_id
                and Job.objects.select_for_update().get(pk=self.job_id).archived_at
            ):
                from django.core.exceptions import ValidationError

                raise ValidationError("Archivovaná zakázka je pouze ke čtení.")
            return super().delete(*args, **kwargs)


class Note(JobChild):
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class Change(JobChild):
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="changes")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    before = models.JSONField()
    after = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class Access(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="crm_access"
    )
    all_jobs = models.BooleanField("Vidí všechny zakázky", default=False)
    finances = models.BooleanField("Přístup k financím a cenám", default=False)
    export = models.BooleanField("Smí exportovat", default=False)

    def __str__(self):
        return str(self.user)


class Company(models.Model):
    name = models.CharField(
        "Dodavatel", max_length=200, default="Ing. Stanislav Lahodný"
    )
    address = models.TextField("Adresa", default="Pikárec 119\n592 53 Pikárec")
    company_id = models.CharField("IČO", max_length=20, default="21639108")
    email = models.EmailField(default="penb.lahodny@seznam.cz")
    bank_account = models.CharField("Účet", max_length=40, default="267467312/0600")
    bank_name = models.CharField("Banka", max_length=100, default="MONETA Money Bank")
    invoice_year = models.PositiveIntegerField("Rok číselné řady faktur", default=2027)
    invoice_next = models.PositiveIntegerField("Další pořadí faktury", default=1)
    due_days = models.PositiveIntegerField("Splatnost ve dnech", default=14)
    retention_years = models.PositiveIntegerField(
        "Doba uchování v letech",
        default=5,
        validators=[MinValueValidator(5), MaxValueValidator(99)],
    )

    def __str__(self):
        return self.name


class Contact(models.Model):
    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="contacts", verbose_name="Klient"
    )
    name = models.CharField("Jméno", max_length=200)
    role = models.CharField("Role", max_length=120, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField("Telefon", max_length=40, blank=True)

    def __str__(self):
        return f"{self.name} ({self.role})"


class Property(models.Model):
    client = models.ForeignKey(Client, on_delete=models.PROTECT, verbose_name="Klient")
    name = models.CharField("Název nemovitosti", max_length=200)
    address = models.TextField("Adresa")
    cadastral_area = models.CharField(
        "Katastrální území a kód", max_length=200, blank=True
    )
    parcels = models.TextField("Parcelní čísla", blank=True)
    building_type = models.CharField("Typ budovy", max_length=100, blank=True)
    technical_notes = models.TextField(
        "Technické údaje (plochy, podlaží, rok výstavby, systémy)", blank=True
    )

    def __str__(self):
        return self.name


class Inquiry(models.Model):
    STATES = [
        ("new", "Nová"),
        ("review", "Posuzuje se"),
        ("waiting", "Čeká na doplnění"),
        ("offered", "Nabídka odeslána"),
        ("accepted", "Potvrzená"),
        ("lost", "Odmítnutá"),
        ("converted", "Převedena na zakázku"),
    ]
    origin = models.CharField(
        max_length=20,
        choices=[("inquiry", "Poptávka"), ("direct_offer", "Přímá nabídka")],
        default="inquiry",
    )
    website = models.ForeignKey(
        "WebsiteSource", null=True, blank=True, on_delete=models.PROTECT
    )
    intake_hash = models.CharField(max_length=64, blank=True)
    last_reply_at = models.DateTimeField(null=True, blank=True)
    name = models.CharField("Jméno / firma", max_length=200)
    email = models.EmailField()
    phone = models.CharField("Telefon", max_length=40, blank=True)
    address = models.TextField("Adresa nemovitosti")
    service = models.CharField("Služba", choices=Job.SERVICES, max_length=20)
    description = models.TextField("Popis požadavku")
    requested_date = models.DateField("Požadovaný termín", null=True, blank=True)
    source = models.CharField("Zdroj", max_length=100, default="Web")
    status = models.CharField("Stav", choices=STATES, max_length=20, default="new")
    lost_reason = models.TextField("Důvod odmítnutí", blank=True)
    client = models.ForeignKey(Client, null=True, blank=True, on_delete=models.PROTECT)
    job = models.OneToOneField(Job, null=True, blank=True, on_delete=models.PROTECT)
    submission_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"P{self.pk:05d} — {self.name}"


class Offer(models.Model):
    inquiry = models.ForeignKey(
        Inquiry, on_delete=models.PROTECT, related_name="offers"
    )
    version = models.PositiveIntegerField()
    scope = models.TextField("Rozsah a výstupy")
    price = models.DecimalField(
        "Cena Kč",
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    due_date = models.DateField("Termín vyhotovení")
    valid_until = models.DateField("Platnost nabídky do")
    terms = models.TextField(
        "Podmínky",
        default="Termín předpokládá včasné dodání úplných podkladů a umožnění zaměření. Vícepráce pouze po odsouhlasení.",
    )
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    sent_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    declined_at = models.DateTimeField(null=True, blank=True)
    acceptance = models.JSONField(default=dict, blank=True)
    revoked = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["inquiry", "version"], name="unique_offer_version"
            )
        ]
        ordering = ["-version"]


class Folder(JobChild):
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="folders")
    name = models.CharField("Název složky", max_length=120)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["job", "name"], name="unique_job_folder")
        ]

    def __str__(self):
        return self.name


def document_path(instance, filename):
    from pathlib import Path

    return f"private/{uuid.uuid4().hex}{Path(filename).suffix.lower()}"


class Document(JobChild):
    job = models.ForeignKey(
        Job, null=True, blank=True, on_delete=models.PROTECT, related_name="documents"
    )
    folder = models.ForeignKey(
        Folder, null=True, blank=True, on_delete=models.PROTECT, verbose_name="Složka"
    )
    name = models.CharField("Název", max_length=240)
    file = models.FileField(upload_to=document_path)
    sha256 = models.CharField(max_length=64)
    version = models.PositiveIntegerField(default=1)
    previous = models.OneToOneField(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="next_version",
    )
    final = models.BooleanField("Finální výstup", default=False)
    internal = models.BooleanField("Interní dokument", default=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT
    )
    origin = models.CharField(max_length=40, default="Pracovník")
    allowed_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="shared_documents",
        verbose_name="Povolení uživatelé pro interní dokument",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["folder__name", "name", "-version"]


class Task(JobChild):
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField("Úkol", max_length=250)
    description = models.TextField("Pokyny / výsledek", blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, verbose_name="Odpovídá"
    )
    due_date = models.DateField("Termín")
    kind = models.CharField(
        "Druh",
        max_length=20,
        choices=[
            ("work", "Práce"),
            ("survey", "Zaměření"),
            ("check", "Kontrola"),
            ("documents", "Podklady"),
        ],
        default="work",
    )
    starts_at = models.DateTimeField(
        "Začátek návštěvy / schůzky", null=True, blank=True
    )
    estimated_hours = models.DecimalField(
        "Odhad hodin",
        max_digits=7,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )
    actual_hours = models.DecimalField(
        "Skutečné hodiny",
        max_digits=7,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )
    done = models.BooleanField("Dokončeno", default=False)

    class Meta:
        ordering = ["done", "due_date"]


class Requirement(JobChild):
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="requirements")
    title = models.CharField("Požadovaný podklad", max_length=250)
    state = models.CharField(
        "Stav",
        max_length=20,
        choices=[
            ("missing", "Chybí"),
            ("received", "Přijato"),
            ("checked", "Zkontrolováno"),
            ("replace", "Nutno doplnit"),
        ],
        default="missing",
    )


class Expense(JobChild):
    job = models.ForeignKey(Job, on_delete=models.PROTECT, related_name="expenses")
    title = models.CharField("Náklad / odměna", max_length=250)
    kind = models.CharField(
        "Druh",
        max_length=20,
        choices=[
            ("external", "Externí práce"),
            ("travel", "Doprava"),
            ("commission", "Provize"),
            ("other", "Ostatní"),
        ],
        default="other",
    )
    recipient = models.CharField("Příjemce / dodavatel", max_length=200, blank=True)
    amount = models.DecimalField(
        "Částka Kč",
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    date = models.DateField("Datum", default=timezone.localdate)
    paid = models.BooleanField("Zaplaceno", default=False)


class Invoice(models.Model):
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_invoices",
    )
    job = models.ForeignKey(
        Job,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="invoices",
        verbose_name="Zakázka (nepovinné)",
    )
    client = models.ForeignKey(Client, on_delete=models.PROTECT, verbose_name="Klient")
    number = models.CharField(max_length=30, null=True, blank=True, unique=True)
    variable_symbol = models.CharField(
        max_length=10, null=True, blank=True, unique=True
    )
    kind = models.CharField(
        "Druh",
        max_length=20,
        choices=[("invoice", "Faktura"), ("advance", "Zálohová výzva")],
        default="invoice",
    )
    issue_date = models.DateField("Datum vystavení", default=timezone.localdate)
    due_date = models.DateField("Splatnost")
    issued_at = models.DateTimeField(null=True, blank=True)
    advance = models.OneToOneField(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="settlement",
        verbose_name="Odečíst uhrazenou zálohu",
    )
    advance_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    recipient = models.JSONField(default=dict)
    supplier = models.JSONField(default=dict)
    pdf = models.BinaryField(null=True, editable=False)
    printed_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    reminders_paused = models.BooleanField(
        "Pozastavit upomínky (spor / odklad)", default=False
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]

    @computed_property
    def subtotal(self):
        return sum((line.total for line in self.lines.all()), Decimal("0.00"))

    @computed_property
    def total(self):
        return self.subtotal - self.advance_amount

    @computed_property
    def paid(self):
        return sum(
            (p.signed_amount for p in self.payments.filter(voided_at__isnull=True)),
            Decimal("0.00"),
        )

    @computed_property
    def balance(self):
        return self.total - self.paid

    @computed_property
    def state(self):
        if not self.issued_at:
            return "Návrh"
        if self.balance <= 0:
            return "Uhrazeno"
        if self.due_date < timezone.localdate():
            return "Po splatnosti"
        if self.paid > 0:
            return "Částečně uhrazeno"
        return "Čeká na úhradu"

    def __str__(self):
        return self.number or f"Návrh #{self.pk}"

    def save(self, *args, **kwargs):
        if self.pk:
            old = type(self).objects.filter(pk=self.pk, issued_at__isnull=False).first()
            if old:
                protected = [
                    "job_id",
                    "client_id",
                    "number",
                    "variable_symbol",
                    "kind",
                    "issue_date",
                    "due_date",
                    "issued_at",
                    "recipient",
                    "supplier",
                    "pdf",
                    "advance_id",
                    "advance_amount",
                ]
                if any(getattr(old, key) != getattr(self, key) for key in protected):
                    from django.core.exceptions import ValidationError

                    raise ValidationError(
                        "Vystavený doklad nelze přepisovat. Použijte odpovídající opravný postup."
                    )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.issued_at:
            from django.core.exceptions import ValidationError

            raise ValidationError("Vystavený doklad nelze smazat.")
        return super().delete(*args, **kwargs)


class InvoiceLine(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    description = models.TextField("Fakturujeme vám za")
    quantity = models.DecimalField(
        "Množství",
        max_digits=9,
        decimal_places=2,
        default=1,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    unit_price = models.DecimalField(
        "Jednotková cena Kč",
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )

    @computed_property
    def total(self):
        return (self.quantity * self.unit_price).quantize(Decimal("0.01"))

    def save(self, *args, **kwargs):
        if self.invoice.issued_at:
            from django.core.exceptions import ValidationError

            raise ValidationError("Položky vystaveného dokladu jsou uzamčené.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.invoice.issued_at:
            from django.core.exceptions import ValidationError

            raise ValidationError("Položky vystaveného dokladu jsou uzamčené.")
        return super().delete(*args, **kwargs)


class Payment(models.Model):
    invoice = models.ForeignKey(
        Invoice, on_delete=models.PROTECT, related_name="payments"
    )
    kind = models.CharField(
        "Druh platby",
        max_length=20,
        choices=[("receipt", "Přijatá úhrada"), ("refund", "Vrácení peněz")],
        default="receipt",
    )
    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.TextField(blank=True)
    amount = models.DecimalField(
        "Přijatá částka Kč",
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    date = models.DateField("Datum úhrady", default=timezone.localdate)
    method = models.CharField(
        "Způsob",
        max_length=20,
        choices=[("bank", "Převodem"), ("cash", "Hotově")],
        default="bank",
    )
    reference = models.CharField("Reference / poznámka", max_length=200, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    request_key = models.UUIDField(default=uuid.uuid4, unique=True)

    @computed_property
    def signed_amount(self):
        return -self.amount if self.kind == "refund" else self.amount


class BankTransaction(models.Model):
    external_id = models.CharField(max_length=200, unique=True)
    date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    variable_symbol = models.CharField(max_length=10, blank=True)
    note = models.CharField(max_length=300, blank=True)
    payment = models.OneToOneField(
        Payment, null=True, blank=True, on_delete=models.PROTECT
    )


class Message(models.Model):
    job = models.ForeignKey(
        Job, null=True, blank=True, on_delete=models.PROTECT, related_name="messages"
    )
    inquiry = models.ForeignKey(
        Inquiry,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="messages",
    )
    invoice = models.ForeignKey(
        Invoice,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="messages",
    )
    offer = models.ForeignKey(Offer, null=True, blank=True, on_delete=models.PROTECT)
    message_id = models.CharField(max_length=998, null=True, blank=True, unique=True)
    to = models.EmailField("Příjemce")
    subject = models.CharField("Předmět", max_length=250)
    body = models.TextField("Text zprávy")
    state = models.CharField(
        max_length=20,
        choices=[
            ("draft", "Návrh"),
            ("sending", "Odesílá se"),
            ("sent", "Odesláno"),
            ("failed", "Selhalo"),
            ("cancelled", "Zrušeno"),
        ],
        default="draft",
    )
    reminder = models.BooleanField(default=False)
    reminder_stage = models.PositiveIntegerField(default=0)
    sent_at = models.DateTimeField(null=True, blank=True)
    error = models.CharField(max_length=300, blank=True)
    dedupe_key = models.CharField(max_length=150, unique=True, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class Automation(models.Model):
    reminder_days = models.PositiveIntegerField(
        "První upomínka po počtu dní", default=7
    )
    second_days = models.PositiveIntegerField("Druhá upomínka po počtu dní", default=14)
    final_days = models.PositiveIntegerField("Třetí upomínka po počtu dní", default=30)
    enabled = models.BooleanField("Připravovat upomínky", default=True)
    auto_send = models.BooleanField("Automaticky odesílat upomínky", default=False)

    def __str__(self):
        return "Pravidla automatizace"


class Event(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT
    )
    job = models.ForeignKey(
        Job, null=True, on_delete=models.PROTECT, related_name="events"
    )
    action = models.CharField(max_length=200)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class Handover(JobChild):
    job = models.ForeignKey(Job, on_delete=models.PROTECT, related_name="handovers")
    recipient = models.CharField("Příjemce", max_length=200)
    method = models.CharField("Způsob předání", max_length=100)
    date = models.DateField("Datum předání", default=timezone.localdate)
    files = models.JSONField(default=list)
    note = models.TextField("Poznámka / potvrzení převzetí", blank=True)


class InquiryAttachment(models.Model):
    inquiry = models.ForeignKey(
        Inquiry, on_delete=models.PROTECT, related_name="attachments"
    )
    file = models.FileField(upload_to=document_path)
    name = models.CharField(max_length=240)
    sha256 = models.CharField(max_length=64)


class ClientLink(models.Model):
    job = models.ForeignKey(Job, on_delete=models.PROTECT, related_name="client_links")
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    expires = models.DateField("Platnost do")
    revoked = models.BooleanField(default=False)
    allow_outputs = models.BooleanField("Zpřístupnit finální výstupy", default=False)
    created_at = models.DateTimeField(auto_now_add=True)


class ExtraWork(JobChild):
    job = models.ForeignKey(Job, on_delete=models.PROTECT, related_name="extra_work")
    description = models.TextField("Změna rozsahu")
    price = models.DecimalField(
        "Navýšení ceny Kč",
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    new_due_date = models.DateField("Nový termín")
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    accepted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Notification(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="crm_notifications",
    )
    job = models.ForeignKey(Job, on_delete=models.CASCADE)
    title = models.CharField(max_length=250)
    key = models.CharField(max_length=150, unique=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class PriceItem(models.Model):
    name = models.CharField("Služba / položka", max_length=250)
    description = models.TextField("Rozsah", blank=True)
    unit_price = models.DecimalField(
        "Výchozí cena Kč",
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    active = models.BooleanField("Aktivní", default=True)

    def __str__(self):
        return f"{self.name} — {self.unit_price} Kč"


class ClientChange(models.Model):
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="changes")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class CalendarEntry(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField("Název zápisu", max_length=250)
    notes = models.TextField("Poznámky", blank=True)
    starts_at = models.DateTimeField("Začátek")
    ends_at = models.DateTimeField("Konec (nepovinné)", null=True, blank=True)
    job = models.ForeignKey(
        Job,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        verbose_name="Zakázka (nepovinné)",
    )

    class Meta:
        ordering = ["starts_at", "id"]


class ReceivedMail(models.Model):
    fingerprint = models.CharField(max_length=64, unique=True)
    message_id = models.CharField(max_length=998, blank=True)
    references = models.JSONField(default=list)
    sender_name = models.CharField(max_length=200, blank=True)
    sender_email = models.EmailField()
    subject = models.CharField(max_length=250)
    body = models.TextField()
    sent_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    source = models.CharField(max_length=100, default="Soubor EML")
    inquiry = models.ForeignKey(
        Inquiry,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="received_mail",
    )
    skipped_attachments = models.JSONField(default=list)

    class Meta:
        ordering = ["-received_at", "-id"]


class MailAttachment(models.Model):
    mail = models.ForeignKey(
        ReceivedMail, on_delete=models.CASCADE, related_name="attachments"
    )
    file = models.FileField(upload_to=document_path)
    name = models.CharField(max_length=240)
    sha256 = models.CharField(max_length=64)


class MailboxCursor(models.Model):
    key = models.CharField(max_length=64, unique=True)
    last_uid = models.PositiveBigIntegerField(default=0)
    checked_at = models.DateTimeField(null=True, blank=True)


class MailboxSync(models.Model):
    checked_at = models.DateTimeField(auto_now_add=True)
    imported = models.PositiveIntegerField(default=0)
    error = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-checked_at", "-id"]


class WebsiteSource(models.Model):
    name = models.CharField("Název webu", max_length=100)
    slug = models.SlugField("Identifikátor", unique=True)
    domain = models.CharField("Doména", max_length=250)
    secret_env = models.CharField(
        "Název bezpečné proměnné s klíčem",
        max_length=100,
        unique=True,
        default="CRM_WEBHOOK_SECRET",
    )
    active = models.BooleanField("Přijímat poptávky", default=True)

    def __str__(self):
        return self.name
