import hashlib
import io
import json
import tempfile
import uuid
import zipfile
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import (
    BankTransaction,
    Client,
    ClientLink,
    Company,
    Document,
    ExtraWork,
    Handover,
    Inquiry,
    Invoice,
    InvoiceLine,
    Job,
    Message,
    Notification,
    Payment,
)
from .services import (
    accept_extra,
    accept_offer,
    archive_job,
    archive_zip,
    company,
    convert_inquiry,
    create_offer,
    iban,
    initialize_job,
    issue_invoice,
    prepare_reminders,
    qr_png,
    record_payment,
    run_daily,
    send_message,
    spd,
)


class OfficeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        U = get_user_model()
        cls.owner = U.objects.create_superuser(
            "owner", "owner@example.com", "test-long-password"
        )
        cls.worker = U.objects.create_user("worker", password="test-long-password")
        cls.worker.user_permissions.set(
            Permission.objects.filter(content_type__app_label="crm")
        )
        cls.customer = Client.objects.create(
            name="Klient Černý",
            email="customer@example.com",
            billing_address="Ulice 12\nPraha",
            company_id="12345678",
        )
        cls.job = Job.objects.create(
            title="PENB a pasport",
            client=cls.customer,
            address="Dům 1",
            service="both",
            assigned_to=cls.owner,
            due_date=timezone.localdate() + timedelta(days=30),
            agreed_price=12000,
        )
        initialize_job(cls.job)

    def setUp(self):
        self.client.force_login(self.owner)
        self.temp = tempfile.TemporaryDirectory()
        self.media = override_settings(MEDIA_ROOT=self.temp.name)
        self.media.enable()
        self.addCleanup(self.media.disable)
        self.addCleanup(self.temp.cleanup)

    def draft(self, job=True):
        invoice = Invoice.objects.create(
            job=self.job if job else None,
            client=self.customer,
            issue_date=date(2027, 1, 1),
            due_date=date(2027, 1, 15),
        )
        InvoiceLine.objects.create(
            invoice=invoice, description="Zpracování PENB", quantity=1, unit_price=12000
        )
        return invoice

    def issued(self, job=True):
        return issue_invoice(self.draft(job), self.owner)

    def inquiry_offer(self):
        inquiry = Inquiry.objects.create(
            name="Nový klient",
            email="new@example.com",
            address="Objekt Brno",
            service="both",
            description="PENB + pasport",
        )
        offer = create_offer(
            inquiry,
            {
                "scope": "PENB a pasport domu",
                "price": Decimal("10000"),
                "due_date": timezone.localdate() + timedelta(days=20),
                "valid_until": timezone.localdate() + timedelta(days=10),
                "terms": "Podmínky",
            },
            self.owner,
        )
        return inquiry, offer

    def test_owner_pages_render(self):
        for url in [
            "/",
            "/clients/",
            "/properties/",
            "/inquiries/",
            "/calendar/",
            "/invoices/",
            "/outbox/",
            "/reports/",
            "/settings/",
            "/bank/",
            f"/jobs/{self.job.pk}/",
            "/inquiries/new/",
            "/invoices/new/",
            "/properties/new/",
            "/contacts/new/",
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_public_inquiry_replay_is_idempotent(self):
        self.client.logout()
        self.assertEqual(self.client.get("/poptavka/").status_code, 200)
        key = self.client.session["inquiry_key"]
        data = {
            "submission_key": key,
            "privacy": "on",
            "name": "Klient",
            "email": "new@example.com",
            "address": "Praha",
            "service": "penb",
            "description": "Žádám PENB",
        }
        for _ in range(2):
            self.assertContains(
                self.client.post("/poptavka/", data), "Poptávka byla přijata"
            )
        self.assertEqual(Inquiry.objects.count(), 1)
        self.assertEqual(Message.objects.count(), 1)

    def test_offer_confirmation_conversion_and_replay(self):
        inquiry, offer = self.inquiry_offer()
        self.client.logout()
        url = f"/nabidka/{offer.token}/"
        self.assertContains(self.client.get(url), "10000")
        data = {
            "name": "Odběratel",
            "billing_address": "Brno 12",
            "company_id": "1234",
            "consent": "on",
        }
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.client.force_login(self.owner)
        job = convert_inquiry(inquiry, self.owner)
        self.assertEqual(convert_inquiry(inquiry, self.owner).pk, job.pk)
        self.assertEqual(job.client.billing_address, "Brno 12")
        self.assertEqual(job.agreed_price, 10000)
        self.assertEqual(job.tasks.count(), 2)
        self.assertEqual(job.folders.count(), 7)

    def test_revoked_and_expired_offer_cannot_be_accepted(self):
        inquiry, old = self.inquiry_offer()
        create_offer(
            inquiry,
            {
                "scope": "Nová",
                "price": Decimal("11000"),
                "due_date": timezone.localdate() + timedelta(days=20),
                "valid_until": timezone.localdate() + timedelta(days=10),
                "terms": "Jiné",
            },
            self.owner,
        )
        with self.assertRaises(ValidationError):
            accept_offer(old, {"name": "A", "billing_address": "B"})
        latest = inquiry.offers.first()
        latest.valid_until = timezone.localdate() - timedelta(days=1)
        latest.save()
        with self.assertRaises(ValidationError):
            accept_offer(latest, {})

    def test_unaccepted_inquiry_cannot_become_job(self):
        inquiry, _ = self.inquiry_offer()
        with self.assertRaises(ValidationError):
            convert_inquiry(inquiry, self.owner)

    def test_invoice_number_vs_pdf_snapshot_qr(self):
        inv = self.issued()
        self.assertEqual(inv.number, "PF 27001")
        self.assertEqual(inv.variable_symbol, "2700101")
        self.assertTrue(bytes(inv.pdf).startswith(b"%PDF-"))
        self.assertIn("X-VS:2700101", spd(inv))
        self.assertIn("AM:12000.00", spd(inv))
        self.assertTrue(qr_png(inv).startswith(b"\x89PNG"))
        original = bytes(inv.pdf)
        self.customer.billing_address = "Změněná"
        self.customer.save()
        inv.refresh_from_db()
        self.assertEqual(inv.recipient["address"], "Ulice 12\nPraha")
        self.assertEqual(bytes(inv.pdf), original)
        issue_invoice(inv, self.owner)
        self.assertEqual(Company.objects.get(pk=1).invoice_next, 2)
        second = self.issued()
        self.assertEqual(second.variable_symbol, "2700102")
        standalone = self.issued(False)
        self.assertEqual(standalone.number, "PF 27003")
        self.assertNotEqual(len(standalone.variable_symbol), 7)

    def test_invalid_iban_rolls_back_number(self):
        cfg = company()
        cfg.bank_account = "1/0600"
        cfg.save()
        inv = self.draft()
        with self.assertRaises(ValidationError):
            issue_invoice(inv, self.owner)
        inv.refresh_from_db()
        self.assertIsNone(inv.number)
        self.assertEqual(company().invoice_next, 1)

    def test_partial_full_payment_and_reminder_cancellation(self):
        cfg = company()
        cfg.invoice_year = timezone.localdate().year
        cfg.save()
        inv = self.draft()
        inv.issue_date = timezone.localdate() - timedelta(days=30)
        inv.due_date = timezone.localdate() - timedelta(days=15)
        inv.save()
        inv = issue_invoice(inv, self.owner)
        self.assertEqual(prepare_reminders(), 1)
        self.assertEqual(prepare_reminders(), 0)
        key = uuid.uuid4()
        data = {
            "amount": Decimal("5000"),
            "date": timezone.localdate(),
            "method": "bank",
            "reference": "test",
            "request_key": key,
        }
        record_payment(inv, data, self.owner)
        record_payment(inv, data, self.owner)
        self.assertEqual(inv.payments.count(), 1)
        self.assertEqual(inv.balance, Decimal("7000"))
        record_payment(
            inv,
            {**data, "amount": Decimal("7000"), "request_key": uuid.uuid4()},
            self.owner,
        )
        self.assertEqual(inv.state, "Uhrazeno")
        self.assertEqual(inv.messages.get().state, "cancelled")
        self.assertEqual(prepare_reminders(), 0)

    @override_settings(
        CRM_EMAIL_ENABLED=True,
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    )
    def test_mail_pdf_attachment_and_idempotence(self):
        from django.core import mail

        inv = self.issued()
        msg = Message.objects.create(
            invoice=inv, to="test@example.com", subject="Faktura", body="Dobrý den"
        )
        send_message(msg, self.owner)
        send_message(msg, self.owner)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].attachments[0].mimetype, "application/pdf")
        inv.refresh_from_db()
        self.assertIsNotNone(inv.sent_at)

    def test_disabled_mail_is_not_marked_sent(self):
        msg = Message.objects.create(to="test@example.com", subject="Test", body="Text")
        with self.assertRaises(ValidationError):
            send_message(msg, self.owner)
        msg.refresh_from_db()
        self.assertEqual(msg.state, "draft")

    @override_settings(CRM_EMAIL_ENABLED=True)
    def test_mail_failure_not_marked_sent_or_secret_logged(self):
        msg = Message.objects.create(to="test@example.com", subject="Test", body="Text")
        with patch(
            "crm.services.EmailMessage.send",
            side_effect=RuntimeError("secret-password"),
        ):
            send_message(msg, self.owner)
        msg.refresh_from_db()
        self.assertEqual(msg.state, "failed")
        self.assertNotIn("secret-password", msg.error)

    def test_upload_download_version_and_foreign_access(self):
        folder = self.job.folders.first()
        data = {
            "folder": folder.pk,
            "name": "Půdorys.pdf",
            "file": SimpleUploadedFile("plan.pdf", b"%PDF-test"),
            "internal": "on",
        }
        self.assertEqual(
            self.client.post(f"/jobs/{self.job.pk}/documents/new/", data).status_code,
            302,
        )
        doc = self.job.documents.get()
        self.assertEqual(doc.sha256, hashlib.sha256(b"%PDF-test").hexdigest())
        self.assertEqual(
            self.client.get(f"/documents/{doc.pk}/download/").status_code, 200
        )
        self.client.force_login(self.worker)
        self.assertEqual(
            self.client.get(f"/documents/{doc.pk}/download/").status_code, 404
        )
        self.job.assigned_to = self.worker
        self.job.save()
        self.assertEqual(
            self.client.get(f"/documents/{doc.pk}/download/").status_code, 404
        )
        response = self.client.get(f"/jobs/{self.job.pk}/")
        self.assertNotContains(response, "Půdorys.pdf")
        self.assertNotContains(response, "12000")

    def test_archive_requires_completion_and_blocks_mutation(self):
        with self.assertRaises(ValidationError):
            archive_job(self.job, self.owner)
        self.job.status = "delivered"
        self.job.save()
        self.job.tasks.update(done=True)
        Handover.objects.create(
            job=self.job, recipient="Klient", method="Osobně", files=[]
        )
        archive_job(self.job, self.owner)
        self.assertEqual(
            self.client.post(f"/jobs/{self.job.pk}/", {"text": "Změna"}).status_code,
            403,
        )
        self.assertEqual(self.client.get(f"/jobs/{self.job.pk}/edit/").status_code, 403)
        self.assertEqual(
            self.client.get(f"/jobs/{self.job.pk}/documents/new/").status_code, 403
        )
        response = self.client.get(f"/jobs/{self.job.pk}/export/")
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            self.assertIn("manifest.json", z.namelist())

    def test_bank_duplicate_and_auto_match(self):
        inv = self.issued()
        content = f"id;date;amount;vs;note\ntx1;2027-01-01;12000;{inv.variable_symbol};Platba\n".encode()
        for _ in range(2):
            response = self.client.post(
                "/bank/import/", {"file": SimpleUploadedFile("bank.csv", content)}
            )
            self.assertEqual(response.status_code, 302)
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(BankTransaction.objects.count(), 1)
        self.assertEqual(inv.state, "Uhrazeno")

    def test_financial_modules_denied_even_with_model_permissions(self):
        self.client.force_login(self.worker)
        for path in ["/invoices/", "/reports/", "/bank/", "/outbox/", "/settings/"]:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 403)

    def test_invoice_form_round_trip(self):
        data = {
            "client": self.customer.pk,
            "job": self.job.pk,
            "kind": "invoice",
            "issue_date": "2027-01-01",
            "due_date": "2027-01-15",
            "recipient_name": "Novák",
            "recipient_address": "Praha 1",
            "recipient_email": "novak@example.com",
            "recipient_company_id": "",
            "lines-TOTAL_FORMS": "1",
            "lines-INITIAL_FORMS": "0",
            "lines-MIN_NUM_FORMS": "1",
            "lines-MAX_NUM_FORMS": "100",
            "lines-0-description": "PENB",
            "lines-0-quantity": "1",
            "lines-0-unit_price": "12300",
            "billing_text": "Fakturujeme vám za vyhotovení PENB",
            "amount": "12300",
        }
        res = self.client.post("/invoices/new/", data)
        self.assertEqual(res.status_code, 302)
        inv = Invoice.objects.get()
        self.assertEqual(inv.total, 12300)
        self.assertEqual(self.client.get(f"/invoices/{inv.pk}/").status_code, 200)
        self.assertEqual(
            self.client.post(
                f"/invoices/{inv.pk}/action/", {"action": "issue"}
            ).status_code,
            302,
        )
        inv.refresh_from_db()
        self.assertIsNotNone(inv.issued_at)
        self.assertEqual(self.client.get(f"/invoices/{inv.pk}/edit/").status_code, 403)

    def test_report_export_formula_escaping(self):
        self.customer.name = '=HYPERLINK("bad")'
        self.customer.save()
        res = self.client.get("/reports/?export=csv")
        self.assertEqual(res.status_code, 200)
        self.assertIn("'=HYPERLINK", res.content.decode("utf-8"))

    def test_iban_known_account_checksum(self):
        value = iban("267467312/0600")
        rearranged = value[4:] + value[:4]
        digits = "".join(str(ord(c) - 55) if c.isalpha() else c for c in rearranged)
        self.assertEqual(int(digits) % 97, 1)

    def test_client_portal_upload_scope_and_revoke(self):
        link = ClientLink.objects.create(
            job=self.job, expires=timezone.localdate() + timedelta(days=10)
        )
        self.client.logout()
        res = self.client.get(f"/klient/{link.token}/")
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, "12000")
        res = self.client.post(
            f"/klient/{link.token}/",
            {
                "attachments": SimpleUploadedFile("podklad.pdf", b"%PDF-client"),
                "note": "Nové podklady",
            },
        )
        self.assertEqual(res.status_code, 200)
        doc = self.job.documents.get()
        self.assertIsNone(doc.uploaded_by)
        self.assertEqual(doc.origin, "Klient přes odkaz")
        doc.final = True
        doc.save()
        self.assertEqual(
            self.client.get(f"/klient/{link.token}/soubor/{doc.pk}/").status_code, 403
        )
        link.allow_outputs = True
        link.save()
        self.assertEqual(
            self.client.get(f"/klient/{link.token}/soubor/{doc.pk}/").status_code, 200
        )
        link.revoked = True
        link.save()
        self.assertEqual(self.client.get(f"/klient/{link.token}/").status_code, 404)

    def test_inquiry_attachments_transfer_to_job(self):
        self.client.get("/poptavka/")
        key = self.client.session["inquiry_key"]
        res = self.client.post(
            "/poptavka/",
            {
                "submission_key": key,
                "privacy": "on",
                "name": "A",
                "email": "a@example.com",
                "address": "Praha",
                "service": "penb",
                "description": "PENB",
                "attachments": SimpleUploadedFile("plan.pdf", b"%PDF-plan"),
            },
        )
        self.assertEqual(res.status_code, 200)
        inquiry = Inquiry.objects.get()
        self.assertEqual(inquiry.attachments.count(), 1)
        offer = create_offer(
            inquiry,
            {
                "scope": "PENB",
                "price": Decimal("1000"),
                "due_date": timezone.localdate() + timedelta(days=20),
                "valid_until": timezone.localdate() + timedelta(days=10),
                "terms": "Podmínky",
            },
            self.owner,
        )
        accept_offer(offer, {"name": "A", "billing_address": "Praha"})
        job = convert_inquiry(inquiry, self.owner)
        self.assertEqual(
            job.documents.get().file.name, inquiry.attachments.get().file.name
        )

    def test_extra_work_acceptance_is_idempotent(self):
        extra = ExtraWork.objects.create(
            job=self.job,
            description="Doplnění",
            price=1000,
            new_due_date=timezone.localdate() + timedelta(days=40),
        )
        accept_extra(extra)
        accept_extra(extra)
        self.job.refresh_from_db()
        self.assertEqual(self.job.agreed_price, 13000)
        self.assertEqual(self.job.due_date, extra.new_due_date)

    def test_advance_settlement_and_reports(self):
        advance = self.draft()
        advance.kind = "advance"
        advance.save()
        advance.lines.update(unit_price=5000)
        advance = issue_invoice(advance, self.owner)
        record_payment(
            advance,
            {
                "amount": Decimal("5000"),
                "date": timezone.localdate(),
                "method": "bank",
                "reference": "záloha",
                "request_key": uuid.uuid4(),
            },
            self.owner,
        )
        final = self.draft()
        final.advance = advance
        final.save()
        final = issue_invoice(final, self.owner)
        self.assertEqual(final.advance_amount, 5000)
        self.assertEqual(final.total, 7000)
        response = self.client.get("/reports/")
        self.assertEqual(response.context["billed"], 12000)
        self.assertEqual(response.context["received"], 5000)

    def test_mfa_enrolment_verification_and_recovery(self):
        from django_otp.oath import totp
        from django_otp.plugins.otp_totp.models import TOTPDevice

        self.assertEqual(self.client.get("/security/setup/").status_code, 200)
        device = TOTPDevice.objects.get(user=self.owner)
        token = str(
            totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits)
        ).zfill(device.digits)
        res = self.client.post("/security/setup/", {"token": token})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.context["tokens"]), 10)
        recovery = res.context["tokens"][0]
        self.client.logout()
        self.client.force_login(self.owner)
        self.assertRedirects(
            self.client.get("/"), "/security/verify/", fetch_redirect_response=False
        )
        self.assertEqual(
            self.client.post("/security/verify/", {"token": recovery}).status_code, 302
        )
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_role_settings_do_not_allow_superuser_escalation(self):
        self.client.force_login(self.worker)
        self.assertEqual(self.client.get("/users/").status_code, 403)
        self.client.force_login(self.owner)
        response = self.client.post(
            f"/users/{self.worker.pk}/edit/",
            {
                "username": "worker",
                "email": "worker@example.com",
                "is_active": "on",
                "is_superuser": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.worker.refresh_from_db()
        self.assertFalse(self.worker.is_superuser)

    def test_daily_notifications_idempotent_and_access(self):
        self.job.due_date = timezone.localdate()
        self.job.save()
        run_daily()
        run_daily()
        self.assertEqual(Notification.objects.filter(key__startswith="job:").count(), 1)
        self.assertContains(self.client.get("/"), "blíží se termín vyhotovení")
        self.client.force_login(self.worker)
        self.assertNotContains(self.client.get("/"), "blíží se termín vyhotovení")

    def test_archive_client_snapshot_is_immutable(self):
        self.job.status = "delivered"
        self.job.save()
        self.job.tasks.update(done=True)
        Handover.objects.create(
            job=self.job, recipient="Klient", method="Osobně", files=[]
        )
        archived = archive_job(self.job, self.owner)
        self.customer.name = "Změněný klient"
        self.customer.save()
        archived.refresh_from_db()
        with zipfile.ZipFile(io.BytesIO(archive_zip(archived))) as z:
            manifest = json.loads(z.read("manifest.json"))
            self.assertEqual(manifest["client"]["name"], "Klient Černý")

    def test_issued_invoice_and_lines_reject_edits(self):
        inv = self.issued()
        inv.recipient = {"name": "Přepsáno"}
        with self.assertRaises(ValidationError):
            inv.save()
        line = inv.lines.get()
        line.unit_price = 1
        with self.assertRaises(ValidationError):
            line.save()
        with self.assertRaises(ValidationError):
            line.delete()

    def test_refund_and_void_preserve_history(self):
        inv = self.issued()
        payment = record_payment(
            inv,
            {
                "amount": Decimal("13000"),
                "date": timezone.localdate(),
                "method": "bank",
                "reference": "přeplatek",
                "request_key": uuid.uuid4(),
            },
            self.owner,
        )
        self.assertEqual(inv.balance, -1000)
        record_payment(
            inv,
            {
                "amount": Decimal("1000"),
                "kind": "refund",
                "date": timezone.localdate(),
                "method": "bank",
                "reference": "vrácení přeplatku",
                "request_key": uuid.uuid4(),
            },
            self.owner,
        )
        self.assertEqual(inv.balance, 0)
        from .services import void_payment

        void_payment(payment, self.owner, "Chybně přiřazeno")
        payment.refresh_from_db()
        self.assertIsNotNone(payment.voided_at)
        self.assertEqual(inv.payments.count(), 2)

    def test_internal_document_can_be_shared_with_selected_worker(self):
        self.job.assigned_to = self.worker
        self.job.save()
        folder = self.job.folders.first()
        doc = Document.objects.create(
            job=self.job,
            folder=folder,
            name="Interní.pdf",
            file=SimpleUploadedFile("internal.pdf", b"%PDF-internal"),
            sha256=hashlib.sha256(b"%PDF-internal").hexdigest(),
            internal=True,
            uploaded_by=self.owner,
        )
        self.client.force_login(self.worker)
        self.assertEqual(
            self.client.get(f"/documents/{doc.pk}/download/").status_code, 404
        )
        doc.allowed_users.add(self.worker)
        self.assertEqual(
            self.client.get(f"/documents/{doc.pk}/download/").status_code, 200
        )
        self.assertContains(self.client.get(f"/jobs/{self.job.pk}/"), "Interní.pdf")

    def test_ares_lookup_prefills_without_changing_existing_client(self):
        import urllib.request
        from unittest.mock import MagicMock

        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {
                "obchodniJmeno": "Ukázková s.r.o.",
                "ico": "12345678",
                "sidlo": {"textovaAdresa": "Praha 1"},
            }
        ).encode()
        with patch.object(urllib.request, "urlopen", return_value=response):
            result = self.client.post("/clients/ares/", {"company_id": "12345678"})
        self.assertEqual(result.status_code, 302)
        page = self.client.get("/clients/new/")
        self.assertContains(page, "Ukázková s.r.o.")
        self.assertEqual(Client.objects.count(), 1)

    def test_security_headers_preserve_same_origin_login(self):
        self.client.logout()
        response = self.client.get("/accounts/login/")
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertIn("no-store", response["Cache-Control"])

    def test_archive_lock_enforced_for_model_children(self):
        self.job.status = "delivered"
        self.job.save()
        self.job.tasks.update(done=True)
        Handover.objects.create(
            job=self.job, recipient="Klient", method="Osobně", files=[]
        )
        archived = archive_job(self.job, self.owner)
        task = archived.tasks.first()
        task.title = "Změna archivu"
        with self.assertRaises(ValidationError):
            task.save()
        archived.description = "Přepsaný popis"
        with self.assertRaises(ValidationError):
            archived.save()

    def test_prefilled_job_invoice_can_be_saved_unchanged(self):
        url = f"/invoices/new/?job={self.job.pk}"
        page = self.client.get(url)
        form = page.context["form"]
        data = {}
        for name, field in form.fields.items():
            value = form[name].value()
            data[name] = "" if value is None else str(value)
        # Browser posts rendered date strings rather than Python date objects.
        for name in ["issue_date", "due_date"]:
            value = form[name].value()
            data[name] = value.isoformat() if hasattr(value, "isoformat") else value
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Invoice.objects.get().total, self.job.agreed_price)

    def test_archived_file_checksum_detects_corruption(self):
        Document.objects.create(
            job=self.job,
            folder=self.job.folders.first(),
            name="plan.pdf",
            file=SimpleUploadedFile("plan.pdf", b"%PDF-plan"),
            sha256="0" * 64,
            internal=False,
            uploaded_by=self.owner,
        )
        with self.assertRaises(ValidationError):
            archive_zip(self.job)
