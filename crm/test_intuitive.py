import tempfile
import uuid
from datetime import timedelta
from decimal import Decimal
from email.message import EmailMessage
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import (
    Client,
    Inquiry,
    Invoice,
    InvoiceLine,
    Message,
    Payment,
    ReceivedMail,
)
from .services import company, initialize_job, issue_invoice


class IntuitiveTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_superuser("owner")
        self.worker = get_user_model().objects.create_user("worker")
        self.client.force_login(self.owner)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.override = override_settings(MEDIA_ROOT=self.temp.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.inquiry = Inquiry.objects.create(
            name="Zákazník",
            email="customer@example.invalid",
            address="Ukázková 12, Praha",
            service="penb",
            description="Vyhotovení PENB",
            source_details={"quote": {"total": 12500, "passport": False}},
        )

    def reply_data(self):
        response = self.client.get(f"/inquiries/{self.inquiry.pk}/reply/")
        form = response.context["form"]
        return {name: form[name].value() for name in form.fields}

    def invoice(self):
        customer = Client.objects.create(
            name="Zákazník", billing_address="Ukázková 12\nPraha"
        )
        invoice = Invoice.objects.create(
            client=customer, due_date=timezone.localdate() + timedelta(days=14)
        )
        InvoiceLine.objects.create(
            invoice=invoice,
            description="Vyhotovení PENB včetně zaměření, průkaz a půdorysy",
            unit_price=12500,
            quantity=1,
        )
        cfg = company()
        cfg.invoice_year = timezone.localdate().year
        cfg.save()
        return issue_invoice(invoice, self.owner)

    def test_quote_reply_confirmation_job_invoice_price(self):
        data = self.reply_data()
        self.assertEqual(data["price"], Decimal("12500"))
        self.assertIn("12500,00 Kč", data["body"])
        self.assertIn("děkujeme za Vaši poptávku", data["body"])
        self.assertEqual(
            self.client.post(f"/inquiries/{self.inquiry.pk}/reply/", data).status_code,
            302,
        )
        self.assertEqual(
            self.client.post(f"/inquiries/{self.inquiry.pk}/reply/", data).status_code,
            302,
        )
        self.assertEqual(self.inquiry.offers.count(), 1)
        message = Message.objects.get(inquiry=self.inquiry)
        self.assertEqual(message.state, "draft")
        offer = self.inquiry.offers.get()
        confirm = {
            "name": "Fakturační zákazník",
            "billing_address": "Jiná 2\nBrno",
            "company_id": "",
            "tax_id": "",
            "consent": "on",
            "evidence": "Potvrzení odpovědí e-mailem",
        }
        self.assertEqual(
            self.client.post(f"/offers/{offer.pk}/confirm/", confirm).status_code, 302
        )
        self.assertEqual(
            self.client.post(f"/inquiries/{self.inquiry.pk}/convert/").status_code, 302
        )
        self.inquiry.refresh_from_db()
        job = self.inquiry.job
        self.assertEqual(job.agreed_price, Decimal("12500"))
        self.assertFalse(job.requirements.exists())
        initial = (
            self.client.get(f"/invoices/new/?job={job.pk}").context["form"].initial
        )
        self.assertEqual(initial["amount"], Decimal("12500"))
        self.assertEqual(initial["recipient_address"], "Jiná 2\nBrno")
        self.assertNotContains(
            self.client.get(f"/jobs/{job.pk}/"), "Kontrola požadovaných podkladů"
        )

    @override_settings(
        CRM_EMAIL_ENABLED=True,
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    )
    def test_send_reply_once_with_frozen_pdf_and_czech_subject(self):
        data = self.reply_data()
        data["intent"] = "send"
        for _ in range(2):
            self.assertEqual(
                self.client.post(
                    f"/inquiries/{self.inquiry.pk}/reply/", data
                ).status_code,
                302,
            )
        from django.core import mail

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["customer@example.invalid"])
        self.assertEqual(mail.outbox[0].attachments[0].mimetype, "application/pdf")
        self.inquiry.refresh_from_db()
        self.assertEqual(self.inquiry.status, "offered")

    def test_quote_on_request_or_invalid_does_not_invent_price(self):
        for quote in [
            {"total": None},
            {"total": "NaN"},
            {"total": 1200, "onRequest": True},
            "bad",
        ]:
            self.inquiry.source_details = {"quote": quote}
            self.inquiry.save()
            self.assertIsNone(
                self.client.get(f"/inquiries/{self.inquiry.pk}/reply/")
                .context["form"]
                .initial["price"]
            )

    def test_paid_action_permission_partial_remainder_and_no_duplicate(self):
        invoice = self.invoice()
        from .services import record_payment

        record_payment(
            invoice,
            {
                "amount": Decimal("2500"),
                "date": timezone.localdate(),
                "request_key": uuid.uuid4(),
                "method": "bank",
                "kind": "receipt",
            },
            self.owner,
        )
        message = Message.objects.create(
            invoice=invoice,
            to="customer@example.invalid",
            subject="Upomínka",
            body="Neodesílat",
            reminder=True,
        )
        response = self.client.get(f"/invoices/{invoice.pk}/paid/")
        key = response.context["form"]["request_key"].value()
        data = {"date": timezone.localdate().isoformat(), "request_key": key}
        self.assertEqual(
            self.client.post(f"/invoices/{invoice.pk}/paid/", data).status_code, 302
        )
        self.assertEqual(
            self.client.post(f"/invoices/{invoice.pk}/paid/", data).status_code, 302
        )
        self.assertEqual(Payment.objects.filter(invoice=invoice).count(), 2)
        invoice.refresh_from_db()
        self.assertEqual(invoice.balance, 0)
        message.refresh_from_db()
        self.assertEqual(message.state, "cancelled")
        self.client.force_login(self.worker)
        self.assertEqual(
            self.client.post(f"/invoices/{invoice.pk}/paid/", data).status_code, 403
        )

    def test_ordered_menu_and_czech_permissions(self):
        response = self.client.get("/")
        html = response.content.decode()
        nav = html.split('<nav id="main-menu">')[1].split("</nav>")[0]
        labels = [
            "✉ Pošta",
            "Klienti",
            "Poptávky a nabídky",
            "Zakázky",
            "Faktury",
            "Dokumenty",
            "Kalendář",
            "Reporty",
            "Nastavení a další možnosti",
        ]
        positions = [nav.index(label) for label in labels]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("Nemovitosti", nav)
        response = self.client.get(f"/users/{self.worker.pk}/edit/")
        self.assertContains(response, "Zakázky — prohlížet")
        self.assertNotContains(response, "Can view")

    def test_sorting_preserves_filters_and_rejects_arbitrary_fields(self):
        other = Inquiry.objects.create(
            name="Abecedně první",
            email="first@example.invalid",
            address="Brno",
            service="penb",
            description="PENB",
        )
        response = self.client.get("/inquiries/?sort=name&status=new")
        self.assertEqual(list(response.context["inquiries"])[0], other)
        self.assertContains(response, "sort=-name&amp;status=new")
        self.assertEqual(
            self.client.get("/inquiries/?sort=client__password").status_code, 200
        )
        response = self.client.get("/inquiries/?sort=-name")
        self.assertEqual(list(response.context["inquiries"])[0], self.inquiry)

    def email(self, outgoing=False, reference=None):
        message = EmailMessage()
        message["From"] = (
            "owner@example.invalid" if outgoing else "customer@example.invalid"
        )
        message["To"] = (
            "customer@example.invalid" if outgoing else "owner@example.invalid"
        )
        message["Subject"] = "Odpověď"
        message["Message-ID"] = "<" + uuid.uuid4().hex + "@example.invalid>"
        if reference:
            message["In-Reply-To"] = reference
        message.set_content("Text odpovědi")
        return message

    def test_external_sent_mail_and_reply_link_not_a_new_inquiry(self):
        from django.core.exceptions import ValidationError

        from .mailbox import import_email, mail_to_inquiry

        outgoing = self.email(True)
        record, _ = import_email(outgoing.as_bytes(), outgoing=True)
        self.assertTrue(record.is_sent)
        self.assertFalse(record.is_received)
        with self.assertRaises(ValidationError):
            mail_to_inquiry(record, self.owner)
        record.inquiry = self.inquiry
        record.save()
        incoming, _ = import_email(self.email(False, outgoing["Message-ID"]).as_bytes())
        self.assertEqual(incoming.inquiry, self.inquiry)
        self.assertContains(
            self.client.get("/outbox/?folder=sent"), "customer@example.invalid"
        )

    @override_settings(
        CRM_IMAP_ENABLED=True,
        CRM_IMAP_HOST="imap.example.invalid",
        CRM_IMAP_USER="test",
        CRM_IMAP_PASSWORD="test-only",
        CRM_IMAP_FOLDER="INBOX",
        CRM_IMAP_SYNC_SENT=True,
        CRM_IMAP_SENT_FOLDER="Sent",
        CRM_IMAP_AUTO_CREATE=False,
    )
    def test_both_folders_use_readonly_and_independent_cursors(self):
        from .mailbox import sync_mailbox

        raw_in = self.email().as_bytes()
        raw_out = self.email(True).as_bytes()
        connection = MagicMock()
        connection.__enter__.return_value = connection
        current = [""]

        def select(folder, readonly):
            current[0] = folder
            return "OK", []

        connection.select.side_effect = select
        connection.response.return_value = ("UIDVALIDITY", [b"1"])

        def uid(command, *args):
            raw = raw_in if current[0] == "INBOX" else raw_out
            if command == "search":
                return "OK", [b"1"]
            if args[-1] == "(RFC822.SIZE)":
                return "OK", [f"1 (RFC822.SIZE {len(raw)})".encode()]
            return "OK", [(b"BODY", raw)]

        connection.uid.side_effect = uid
        with patch("crm.mailbox.imaplib.IMAP4_SSL", return_value=connection):
            self.assertEqual(sync_mailbox(), 2)
            self.assertEqual(sync_mailbox(), 0)
        self.assertEqual(ReceivedMail.objects.filter(is_received=True).count(), 1)
        self.assertEqual(ReceivedMail.objects.filter(is_sent=True).count(), 1)
        self.assertTrue(
            all(call.kwargs["readonly"] for call in connection.select.call_args_list)
        )
        self.assertFalse(connection.store.called)
        self.assertFalse(connection.expunge.called)

    def test_invoice_template_has_original_geometry_without_original_customer(self):
        from .invoice_layout import template

        source = template()
        self.assertIn("D48:F49", source["merges"])
        self.assertEqual(source["first_row"], 3)
        self.assertNotIn("Oekoplan", str(source))
        self.assertNotIn("Rašínova", str(source))
        self.assertNotIn("26013", str(source))
        self.assertTrue(bytes(self.invoice().pdf).startswith(b"%PDF-"))

    @override_settings(
        CRM_EMAIL_ENABLED=True,
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    )
    def test_reply_to_external_mail_keeps_thread_and_invoice(self):
        from .mailbox import import_email

        invoice = self.invoice()
        native = Message.objects.create(
            invoice=invoice,
            to="customer@example.invalid",
            subject="Faktura",
            body="Text",
            state="sent",
            message_id="<invoice-original@example.invalid>",
        )
        incoming, _ = import_email(self.email(False, native.message_id).as_bytes())
        self.assertEqual(incoming.invoice, invoice)
        self.assertEqual(
            self.client.post(
                f"/inbox/{incoming.pk}/reply/",
                {
                    "to": "customer@example.invalid",
                    "subject": "Re: Faktura",
                    "body": "Děkujeme za zprávu.",
                    "intent": "send",
                },
            ).status_code,
            302,
        )
        from django.core import mail

        self.assertEqual(
            mail.outbox[0].extra_headers["In-Reply-To"], incoming.message_id
        )
        self.assertEqual(Message.objects.filter(invoice=invoice).count(), 2)

    def test_direct_sent_copy_does_not_duplicate_native_sent_row(self):
        from .mailbox import import_email

        raw = self.email(True)
        Message.objects.create(
            to="customer@example.invalid",
            subject="Unikátní odeslaná zpráva",
            body="Text",
            state="sent",
            message_id=raw["Message-ID"],
            sent_at=timezone.now(),
        )
        import_email(raw.as_bytes(), outgoing=True)
        rows = self.client.get("/outbox/?folder=sent").context["mail_rows"]
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["external"])

    def test_simple_multiple_upload_and_unsupported_preview_download(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from .models import Job

        invoice = self.invoice()
        job = Job.objects.create(
            client=invoice.client,
            title="PENB",
            address="Praha 1",
            due_date=timezone.localdate() + timedelta(days=10),
            assigned_to=self.owner,
        )
        initialize_job(job)
        files = [
            SimpleUploadedFile("podklady.pdf", b"%PDF-test"),
            SimpleUploadedFile("vykres.dwg", b"dwg-test"),
        ]
        self.assertEqual(
            self.client.post(f"/jobs/{job.pk}/upload/", {"files": files}).status_code,
            302,
        )
        self.assertEqual(job.documents.count(), 2)
        document = job.documents.get(name="vykres.dwg")
        response = self.client.get(f"/documents/{document.pk}/preview/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        response.close()
        self.client.force_login(self.worker)
        self.assertEqual(
            self.client.post(f"/jobs/{job.pk}/upload/", {}).status_code, 403
        )

    @override_settings(
        CRM_IMAP_ENABLED=True,
        CRM_IMAP_HOST="imap.example.invalid",
        CRM_IMAP_USER="test",
        CRM_IMAP_PASSWORD="test-only",
        CRM_IMAP_FOLDER="INBOX",
        CRM_IMAP_SYNC_SENT=False,
        CRM_IMAP_AUTO_CREATE=False,
        CRM_IMAP_AUTO_WEB=True,
        CRM_WEBHOOK_SECRET="",
    )
    def test_web_form_auto_converts_but_ordinary_email_does_not(self):
        import json

        from .mailbox import sync_mailbox

        web = self.email()
        web.replace_header("Subject", "Webová poptávka")
        data = {
            "schema": "enepru.inquiry.v1",
            "source_slug": "enepru",
            "external_id": str(uuid.uuid4()),
            "name": "Automatická webová poptávka",
            "email": "customer@example.invalid",
            "phone": "123",
            "address": "Praha 1",
            "service": "penb",
            "description": "PENB",
            "source_details": {"quote": {"total": 5000}},
        }
        web.add_attachment(
            json.dumps(data).encode(),
            maintype="application",
            subtype="vnd.enepru.inquiry+json",
            filename="enepru-poptavka.json",
        )
        messages = {1: web.as_bytes(), 2: self.email().as_bytes()}
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.select.return_value = ("OK", [])
        connection.response.return_value = ("UIDVALIDITY", [b"1"])

        def uid(command, *args):
            if command == "search":
                return "OK", [b"1 2"]
            raw = messages[int(args[0])]
            if args[-1] == "(RFC822.SIZE)":
                return "OK", [f"1 (RFC822.SIZE {len(raw)})".encode()]
            return "OK", [(b"BODY", raw)]

        connection.uid.side_effect = uid
        with patch("crm.mailbox.imaplib.IMAP4_SSL", return_value=connection):
            self.assertEqual(sync_mailbox(), 2)
        self.assertTrue(
            Inquiry.objects.filter(name="Automatická webová poptávka").exists()
        )
        self.assertEqual(ReceivedMail.objects.filter(inquiry__isnull=True).count(), 1)

    @override_settings(
        CRM_EMAIL_ENABLED=True,
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    )
    def test_invoice_email_can_be_sent_from_its_prefilled_editor(self):
        invoice = self.invoice()
        message = Message.objects.create(
            invoice=invoice,
            to="customer@example.invalid",
            subject="Faktura",
            body="V příloze posíláme fakturu.",
        )
        data = {
            "to": message.to,
            "subject": message.subject,
            "body": message.body,
            "intent": "send",
        }
        self.assertEqual(
            self.client.post(f"/outbox/{message.pk}/edit/", data)["Location"],
            f"/invoices/{invoice.pk}/",
        )
        from django.core import mail

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].attachments[0].mimetype, "application/pdf")
        self.assertEqual(
            self.client.post(f"/outbox/{message.pk}/edit/", data).status_code, 200
        )
        self.assertEqual(len(mail.outbox), 1)
