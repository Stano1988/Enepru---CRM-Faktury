import hashlib
import hmac
import json
import ssl
import tempfile
import time
import uuid
from datetime import date, timedelta
from decimal import Decimal
from email.message import EmailMessage
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from .mailbox import import_email, mail_to_inquiry, sync_mailbox
from .models import (
    Access,
    CalendarEntry,
    Client,
    Document,
    Handover,
    Inquiry,
    Invoice,
    InvoiceLine,
    Job,
    MailboxCursor,
    Message,
    WebsiteSource,
)
from .services import (
    accept_offer,
    archive_job,
    convert_inquiry,
    create_offer,
    initialize_job,
    issue_invoice,
    record_payment,
    send_message,
)


class RefinedWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        U = get_user_model()
        cls.owner = U.objects.create_superuser(
            "owner", "owner@example.invalid", "test-long-password"
        )
        cls.worker = U.objects.create_user("worker", password="test-long-password")
        cls.worker.user_permissions.set(
            Permission.objects.filter(content_type__app_label="crm")
        )
        cls.customer = Client.objects.create(
            name="Opakovaný klient",
            email="client@example.invalid",
            billing_address="Praha 1",
            notes="Požaduje delší splatnost a předem zavolat.",
            payment_days=30,
        )
        cls.job = Job.objects.create(
            title="PENB domu",
            client=cls.customer,
            address="Dům 1",
            service="penb",
            assigned_to=cls.owner,
            due_date=date(2027, 3, 1),
            agreed_price=12000,
        )
        initialize_job(cls.job)

    def setUp(self):
        self.client.force_login(self.owner)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        override = override_settings(MEDIA_ROOT=temp.name)
        override.enable()
        self.addCleanup(override.disable)

    def invoice_data(self, client=None, job=None):
        return {
            "client": client.pk if client else "",
            "job": job.pk if job else "",
            "kind": "invoice",
            "issue_date": "2027-01-01",
            "due_date": "2027-01-31",
            "recipient_name": "Nový odběratel",
            "recipient_address": "Brno 1",
            "recipient_email": "new@example.invalid",
            "recipient_company_id": "",
            "recipient_tax_id": "",
            "billing_text": "Fakturujeme vám za vyhotovení PENB a výjezd.",
            "amount": "12500.00",
        }

    def raw_mail(
        self,
        subject="Poptávka PENB",
        body="Prosím o nabídku PENB.",
        reference=None,
        attachment=False,
        html=False,
    ):
        mail = EmailMessage()
        mail["From"] = "Opakovaný klient <client@example.invalid>"
        mail["To"] = "penb.lahodny@seznam.cz"
        mail["Subject"] = subject
        mail["Message-ID"] = "<" + uuid.uuid4().hex + "@example.invalid>"
        if reference:
            mail["In-Reply-To"] = reference
        if html:
            mail.set_content(body, subtype="html")
        else:
            mail.set_content(body)
        if attachment:
            mail.add_attachment(
                b"%PDF-podklady",
                maintype="application",
                subtype="pdf",
                filename="podklady.pdf",
            )
        return mail.as_bytes()

    def test_client_card_notes_and_defaults(self):
        response = self.client.get(f"/clients/{self.customer.pk}/")
        self.assertContains(response, "Požaduje delší splatnost")
        self.assertContains(response, "30 dní")
        self.assertContains(response, self.job.number)
        initial = (
            self.client.get(f"/invoices/new/?job={self.job.pk}").context["form"].initial
        )
        self.assertEqual(initial["amount"], 12000)
        self.assertEqual(initial["due_date"], date(2027, 1, 31))
        self.assertIn("PENB", initial["billing_text"])
        defaults = self.client.get(
            f"/clients/{self.customer.pk}/invoice-defaults/"
        ).json()
        self.assertEqual(defaults["payment_days"], 30)

    def test_client_notes_change_history_and_duplicate_prevention(self):
        data = {
            "name": self.customer.name,
            "client_type": "person",
            "email": self.customer.email,
            "phone": "",
            "company_id": "",
            "tax_id": "",
            "billing_address": "Praha 1",
            "mailing_address": "",
            "notes": "Nové požadavky",
            "payment_days": "60",
        }
        self.assertEqual(
            self.client.post(f"/clients/{self.customer.pk}/edit/", data).status_code,
            302,
        )
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.payment_days, 60)
        self.assertEqual(self.customer.changes.count(), 1)
        result = self.client.post("/clients/new/", data)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(Client.objects.count(), 1)

    def test_client_access_still_scoped(self):
        self.client.force_login(self.worker)
        self.assertEqual(
            self.client.get(f"/clients/{self.customer.pk}/").status_code, 404
        )
        self.assertEqual(
            self.client.get(
                f"/clients/{self.customer.pk}/invoice-defaults/"
            ).status_code,
            404,
        )

    def test_simple_invoice_has_no_product_table(self):
        page = self.client.get(f"/invoices/new/?job={self.job.pk}")
        self.assertContains(page, "Fakturujeme vám za")
        self.assertNotContains(page, "lines-TOTAL_FORMS")
        self.assertNotContains(page, "Množství")
        self.assertNotContains(page, "Ceník služeb")
        response = self.client.post(
            "/invoices/new/", self.invoice_data(self.customer, self.job)
        )
        self.assertEqual(response.status_code, 302)
        invoice = Invoice.objects.get()
        self.assertEqual(invoice.subtotal, 12500)
        self.assertEqual(invoice.lines.count(), 1)
        self.assertEqual(invoice.lines.get().quantity, 1)

    def test_invoice_without_prior_client_or_job(self):
        Access.objects.create(user=self.worker, finances=True)
        self.client.force_login(self.worker)
        response = self.client.post("/invoices/new/", self.invoice_data())
        self.assertEqual(response.status_code, 302)
        invoice = Invoice.objects.get()
        self.assertIsNone(invoice.job_id)
        self.assertEqual(invoice.created_by, self.worker)
        self.assertEqual(invoice.client.created_by, self.worker)
        self.assertEqual(self.client.get(response.url).status_code, 200)
        self.assertContains(self.client.get("/clients/"), "Nový odběratel")
        # Repeating a new free invoice reuses the same counterpart.
        self.client.post("/invoices/new/", self.invoice_data())
        self.assertEqual(Client.objects.filter(email="new@example.invalid").count(), 1)

    def test_job_without_prior_client_inquiry_or_offer(self):
        data = {
            "title": "Přímá zakázka",
            "address": "Brno",
            "service": "passport",
            "status": "new",
            "due_date": "2027-04-01",
            "assigned_to": self.owner.pk,
            "new_client_name": "Přímo zadaný klient",
            "new_client_email": "direct@example.invalid",
            "new_client_address": "Brno 2",
            "agreed_price": "5000",
        }
        response = self.client.post("/jobs/new/", data)
        self.assertEqual(response.status_code, 302)
        job = Job.objects.get(title="Přímá zakázka")
        self.assertEqual(job.client.email, "direct@example.invalid")
        self.assertFalse(Inquiry.objects.exists())

    def test_offer_without_prior_inquiry(self):
        data = {
            "customer_name": "Zájemce",
            "customer_email": "offer@example.invalid",
            "address": "Praha",
            "service": "penb",
            "scope": "PENB domu",
            "price": "5000",
            "due_date": (timezone.localdate() + timedelta(days=60)).isoformat(),
            "valid_until": (timezone.localdate() + timedelta(days=14)).isoformat(),
            "terms": "Podmínky",
        }
        response = self.client.post("/offers/new/", data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Inquiry.objects.get().source, "Přímá nabídka")

    def test_repeat_inquiry_uses_stored_client_and_preferences(self):
        inquiry = Inquiry.objects.create(
            name=self.customer.name,
            email=self.customer.email,
            address="Dům 2",
            service="penb",
            description="Opakovaná zakázka",
        )
        offer = create_offer(
            inquiry,
            {
                "scope": "PENB",
                "price": Decimal("4000"),
                "due_date": date(2027, 6, 1),
                "valid_until": date(2027, 3, 1),
                "terms": "Podmínky",
            },
            self.owner,
        )
        accept_offer(offer, {"name": self.customer.name, "billing_address": "Praha 1"})
        job = convert_inquiry(inquiry, self.owner)
        self.assertEqual(job.client_id, self.customer.pk)
        self.assertEqual(Client.objects.count(), 1)
        self.assertEqual(job.client.payment_days, 30)

    def test_calendar_personal_note_without_job_and_private(self):
        data = {
            "title": "Zavolat partnerovi",
            "starts_at": "2027-03-02T09:00",
            "ends_at": "2027-03-02T10:00",
            "notes": "Domluvit spolupráci",
            "job": "",
        }
        response = self.client.post("/calendar/new/", data)
        self.assertEqual(response.status_code, 302)
        entry = CalendarEntry.objects.get()
        self.assertIsNone(entry.job_id)
        self.assertContains(
            self.client.get("/calendar/?month=2027-03"), "Zavolat partnerovi"
        )
        self.client.force_login(self.worker)
        self.assertNotContains(
            self.client.get("/calendar/?month=2027-03"), "Zavolat partnerovi"
        )
        self.assertEqual(
            self.client.get(f"/calendar/{entry.pk}/edit/").status_code, 404
        )

    def test_calendar_deadline_moves_with_job(self):
        page = self.client.get("/calendar/?month=2027-03")
        day = next(
            d
            for week in page.context["weeks"]
            for d in week
            if d["date"] == date(2027, 3, 1)
        )
        self.assertEqual(day["deadlines"][0].pk, self.job.pk)
        self.job.due_date = date(2027, 3, 20)
        self.job.save()
        page = self.client.get("/calendar/?month=2027-03")
        days = {d["date"]: d["deadlines"] for w in page.context["weeks"] for d in w}
        self.assertFalse(days[date(2027, 3, 1)])
        self.assertEqual(days[date(2027, 3, 20)][0].pk, self.job.pk)

    def test_job_filters_sort_and_invalid_inputs(self):
        other = Job.objects.create(
            title="Pasport",
            client=self.customer,
            address="Brno",
            service="passport",
            status="working",
            assigned_to=self.owner,
            due_date=date(2027, 4, 1),
        )
        self.assertEqual(self.client.get("/?sort=-due_date").context["jobs"][0], other)
        self.assertEqual(
            list(self.client.get("/?service=passport&status=working").context["jobs"]),
            [other],
        )
        self.assertFalse(self.client.get("/?due_from=2028-01-01").context["jobs"])
        self.assertTrue(self.client.get("/?sort=unknown").context["filters"].errors)
        self.assertEqual(self.client.get("/?due_from=bad").status_code, 200)

    def test_archive_five_years_without_financial_prerequisite(self):
        invoice = Invoice.objects.create(
            job=self.job,
            client=self.customer,
            issue_date=date(2027, 1, 1),
            due_date=date(2027, 1, 15),
        )
        InvoiceLine.objects.create(
            invoice=invoice, description="PENB", unit_price=12000, quantity=1
        )
        invoice = issue_invoice(invoice, self.owner)
        self.job.tasks.update(done=True)
        self.job.status = "delivered"
        self.job.save()
        Handover.objects.create(job=self.job, recipient="Klient", method="Elektronicky")
        job = archive_job(self.job, self.owner)
        self.assertEqual(job.retain_until.year, timezone.localdate().year + 5)
        self.assertEqual(
            self.client.get(f"/invoices/new/?job={job.pk}").status_code, 200
        )
        record_payment(
            invoice,
            {
                "amount": Decimal("12000"),
                "date": date(2027, 1, 2),
                "method": "bank",
                "reference": "Úhrada",
                "request_key": uuid.uuid4(),
            },
            self.owner,
        )
        self.assertEqual(invoice.state, "Uhrazeno")
        self.assertEqual(self.client.get(f"/jobs/{job.pk}/edit/").status_code, 403)

    def test_document_without_job_and_later_assignment(self):
        self.client.force_login(self.worker)
        response = self.client.post(
            "/documents/upload/", {"files": SimpleUploadedFile("plan.pdf", b"%PDF-doc")}
        )
        self.assertEqual(response.status_code, 302)
        doc = Document.objects.get()
        self.assertIsNone(doc.job_id)
        self.assertEqual(
            self.client.get(f"/documents/{doc.pk}/download/").status_code, 200
        )
        self.job.assigned_to = self.worker
        self.job.save()
        self.assertEqual(
            self.client.post(
                f"/documents/{doc.pk}/assign/", {"job": self.job.pk}
            ).status_code,
            302,
        )
        doc.refresh_from_db()
        self.assertEqual(doc.job_id, self.job.pk)
        self.assertEqual(
            self.client.get(f"/documents/{doc.pk}/download/").status_code, 200
        )

    def test_eml_import_create_once_and_reuse_client(self):
        raw = self.raw_mail(attachment=True)
        mail, created = import_email(raw)
        same, repeated = import_email(raw)
        self.assertTrue(created)
        self.assertFalse(repeated)
        self.assertEqual(same.pk, mail.pk)
        inquiry = mail_to_inquiry(mail, self.owner)
        self.assertEqual(mail_to_inquiry(mail, self.owner).pk, inquiry.pk)
        self.assertEqual(inquiry.client_id, self.customer.pk)
        self.assertEqual(inquiry.attachments.count(), 1)
        self.assertEqual(inquiry.service, "penb")
        self.assertEqual(inquiry.address, "")

    def test_inbound_html_is_not_executable(self):
        mail, _ = import_email(
            self.raw_mail(
                body="<p>Prosím o pasport</p><script>alert(1)</script>", html=True
            )
        )
        self.assertIn("Prosím o pasport", mail.body)
        self.assertNotIn("alert(1)", mail.body)
        self.assertNotContains(
            self.client.get(f"/inbox/{mail.pk}/"), "<script>alert(1)</script>"
        )

    def test_email_reply_updates_inquiry_and_preserves_attachments(self):
        inquiry = Inquiry.objects.create(
            name=self.customer.name,
            email=self.customer.email,
            address="Dům",
            service="penb",
            description="Dotaz",
            status="waiting",
        )
        Message.objects.create(
            inquiry=inquiry,
            to=self.customer.email,
            subject="Dotaz",
            body="Text",
            message_id="<our-message@example.invalid>",
            state="sent",
        )
        mail, _ = import_email(
            self.raw_mail(reference="<our-message@example.invalid>", attachment=True)
        )
        self.assertEqual(mail.inquiry_id, inquiry.pk)
        inquiry.refresh_from_db()
        self.assertEqual(inquiry.status, "review")
        self.assertIsNotNone(inquiry.last_reply_at)
        self.assertEqual(inquiry.attachments.count(), 1)

    @override_settings(
        CRM_IMAP_ENABLED=True,
        CRM_IMAP_HOST="imap.example.invalid",
        CRM_IMAP_USER="test",
        CRM_IMAP_PASSWORD="test-only",
        CRM_IMAP_FOLDER="Poptavky",
        CRM_IMAP_AUTO_CREATE=True,
    )
    def test_imap_readonly_peek_cursor_and_no_duplicates(self):
        raw = self.raw_mail()
        connection = MagicMock()
        mailbox = connection.__enter__.return_value
        mailbox.select.return_value = ("OK", [b"1"])
        mailbox.response.return_value = ("UIDVALIDITY", [b"5"])

        def command(name, *args):
            if name == "search":
                return "OK", [b"7"]
            if args[1] == "(RFC822.SIZE)":
                return "OK", [f"7 (RFC822.SIZE {len(raw)})".encode()]
            return "OK", [(b"7 BODY[]", raw)]

        mailbox.uid.side_effect = command
        with patch(
            "crm.mailbox.imaplib.IMAP4_SSL", return_value=connection
        ) as constructor:
            self.assertEqual(sync_mailbox(), 1)
            self.assertEqual(sync_mailbox(), 0)
        self.assertEqual(Inquiry.objects.count(), 1)
        self.assertEqual(MailboxCursor.objects.get().last_uid, 7)
        self.assertTrue(mailbox.select.call_args.kwargs["readonly"])
        context = constructor.call_args.kwargs["ssl_context"]
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertFalse(
            any(
                call.args[0].lower() in ("store", "expunge", "delete")
                for call in mailbox.uid.call_args_list
            )
        )

    @override_settings(
        CRM_EMAIL_ENABLED=True,
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    )
    def test_outgoing_id_matches_reply_tracking_header(self):
        from django.core import mail

        message = Message.objects.create(
            to=self.customer.email, subject="Nabídka", body="Text"
        )
        send_message(message, self.owner)
        message.refresh_from_db()
        self.assertEqual(mail.outbox[0].extra_headers["Message-ID"], message.message_id)

    def signed(self, payload, secret="test-web-key", slug="enepru", stamp=None):
        raw = json.dumps(payload).encode()
        stamp = str(stamp or int(time.time()))
        signature = hmac.new(
            secret.encode(), stamp.encode() + b"." + raw, hashlib.sha256
        ).hexdigest()
        return self.client.post(
            f"/api/inquiries/{slug}/",
            data=raw,
            content_type="application/json",
            HTTP_X_CRM_TIMESTAMP=stamp,
            HTTP_X_CRM_SIGNATURE=signature,
        )

    @override_settings(CRM_WEBHOOK_SECRET="test-web-key")
    def test_website_signed_idempotence_and_source(self):
        data = {
            "external_id": str(uuid.uuid4()),
            "name": "Webový klient",
            "email": "web@example.invalid",
            "address": "Praha",
            "service": "penb",
            "description": "PENB",
        }
        self.assertEqual(self.signed(data).status_code, 201)
        self.assertEqual(self.signed(data).status_code, 200)
        inquiry = Inquiry.objects.get()
        self.assertEqual(inquiry.source, "Enepru.cz")
        inquiry.description = "Doplněno v CRM"
        inquiry.save()
        self.assertEqual(self.signed(data).status_code, 200)
        self.assertEqual(
            self.signed({**data, "description": "Odlišný obsah"}).status_code, 409
        )
        self.assertEqual(self.signed(data, secret="wrong").status_code, 403)
        self.assertEqual(
            self.signed(data, stamp=int(time.time()) - 1000).status_code, 403
        )

    @override_settings(CRM_WEBHOOK_SECRET="test-web-key")
    def test_two_websites_separate_keys_and_ids(self):
        second = WebsiteSource.objects.create(
            name="Druhý web",
            slug="druhy",
            domain="druhy.invalid",
            secret_env="CRM_WEBHOOK_SECOND",
        )
        data = {
            "external_id": str(uuid.uuid4()),
            "name": "Web klient",
            "email": "web@example.invalid",
            "address": "Praha",
            "service": "penb",
            "description": "PENB",
        }
        self.assertEqual(self.signed(data).status_code, 201)
        with patch.dict("os.environ", {"CRM_WEBHOOK_SECOND": "second-key"}):
            self.assertEqual(self.signed(data, slug="druhy").status_code, 403)
            self.assertEqual(
                self.signed(data, slug="druhy", secret="second-key").status_code, 201
            )
        self.assertEqual(Inquiry.objects.count(), 2)
        self.assertEqual(Inquiry.objects.filter(website=second).count(), 1)

    def test_new_pages_render(self):
        for path in [
            "/clients/",
            "/calendar/new/",
            "/documents/",
            "/documents/upload/",
            "/inbox/",
            "/inbox/import/",
            "/websites/",
            "/offers/new/",
        ]:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_archive_does_not_require_handover_or_invoice_module(self):
        self.job.status = "closed"
        self.job.save()
        archive_job(self.job, self.owner, confirm_complete=True)
        self.job.refresh_from_db()
        self.assertIsNotNone(self.job.archived_at)
        self.assertFalse(self.job.handovers.exists())
        self.assertFalse(self.job.invoices.exists())
        self.assertFalse(self.job.tasks.filter(done=False).exists())

    def test_hidden_client_is_not_reused_to_expose_notes(self):
        Access.objects.create(user=self.worker, finances=True)
        self.client.force_login(self.worker)
        data = self.invoice_data()
        data.update(
            recipient_name=self.customer.name, recipient_email=self.customer.email
        )
        response = self.client.post("/invoices/new/", data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "není v rozsahu vašich oprávnění")
        self.assertNotContains(response, "Požaduje delší splatnost")
        self.assertFalse(Invoice.objects.exists())

    def test_long_free_invoice_text_generates_pdf(self):
        invoice = Invoice.objects.create(
            client=self.customer,
            issue_date=date(2027, 1, 1),
            due_date=date(2027, 1, 31),
        )
        InvoiceLine.objects.create(
            invoice=invoice,
            description=("PENB a zaměření stavby. " * 220)[:5000],
            quantity=1,
            unit_price=12000,
        )
        invoice = issue_invoice(invoice, self.owner)
        self.assertTrue(bytes(invoice.pdf).startswith(b"%PDF-"))

    def test_empty_library_upload_is_not_success(self):
        response = self.client.post("/documents/upload/", {})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Document.objects.exists())

    def test_new_website_needs_only_name_and_domain(self):
        response = self.client.post(
            "/websites/",
            {"name": "Druhý web", "domain": "druhy-web.cz", "active": "on"},
        )
        self.assertEqual(response.status_code, 302)
        source = WebsiteSource.objects.get(domain="druhy-web.cz")
        self.assertEqual(source.slug, "druhy-web-cz")
        self.assertTrue(source.secret_env.startswith("CRM_WEBHOOK_"))

    def test_paper_invoice_without_email(self):
        data = self.invoice_data()
        data["recipient_email"] = ""
        response = self.client.post("/invoices/new/", data)
        self.assertEqual(response.status_code, 302)
        invoice = issue_invoice(Invoice.objects.get(), self.owner)
        self.assertTrue(invoice.pdf)
        self.assertFalse(invoice.recipient["email"])

    def test_send_intent_without_email_does_not_issue(self):
        data = self.invoice_data()
        data["recipient_email"] = ""
        data["intent"] = "prepare_send"
        response = self.client.post("/invoices/new/", data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Invoice.objects.exists())
