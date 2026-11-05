import base64
import hashlib
import hmac
import json
import tempfile
import time
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from .intake import decoded_attachments, receive
from .models import Inquiry, Message, Offer, WebsiteSource
from .offers import decline, prepare_followups
from .services import accept_offer, create_offer


class CompletionTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("owner")
        self.worker = get_user_model().objects.create_user("worker")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.override = override_settings(MEDIA_ROOT=self.temp.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.source = WebsiteSource.objects.get(slug="enepru")
        self.data = {
            "external_id": str(uuid.uuid4()),
            "name": "Testovací zákazník",
            "email": "customer@example.invalid",
            "phone": "123",
            "address": "Praha 1",
            "service": "penb",
            "description": "Zpracování PENB",
            "source_details": {"quote": {"total": 5000}},
        }

    def offer(self):
        inquiry = Inquiry.objects.create(
            name="Klient",
            email="customer@example.invalid",
            address="Praha 1",
            service="penb",
            description="PENB",
        )
        return create_offer(
            inquiry,
            {
                "scope": "PENB rodinného domu",
                "price": 5000,
                "due_date": timezone.localdate() + timedelta(days=30),
                "valid_until": timezone.localdate() + timedelta(days=14),
                "terms": "Po dodání podkladů",
            },
            self.admin,
        )

    def test_pdf_frozen_and_private(self):
        offer = self.offer()
        original = bytes(offer.pdf)
        self.assertTrue(original.startswith(b"%PDF-"))
        self.client.force_login(self.worker)
        self.assertEqual(self.client.get(f"/offers/{offer.pk}/pdf/").status_code, 403)
        self.client.force_login(self.admin)
        from .services import company

        supplier = company()
        supplier.name = "Změněný dodavatel"
        supplier.save()
        self.assertEqual(self.client.get(f"/offers/{offer.pk}/pdf/").content, original)

    def test_decline_blocks_acceptance_and_followup(self):
        offer = self.offer()
        Offer.objects.filter(pk=offer.pk).update(
            sent_at=timezone.now() - timedelta(days=6)
        )
        self.assertEqual(prepare_followups(), 1)
        self.assertEqual(prepare_followups(), 0)
        decline(offer)
        offer.refresh_from_db()
        self.assertTrue(offer.declined_at)
        self.assertEqual(Message.objects.get(offer=offer).state, "cancelled")
        with self.assertRaises(ValidationError):
            accept_offer(offer, {"name": "Klient"})
        self.assertEqual(prepare_followups(), 0)

    def test_confirmed_offer_cannot_be_declined(self):
        offer = self.offer()
        accept_offer(offer, {"name": "Klient"})
        with self.assertRaises(ValidationError):
            decline(offer)

    def test_public_decline_requires_csrf_and_changes_status(self):
        offer = self.offer()
        response = self.client.post(f"/nabidka/{offer.token}/", {"action": "decline"})
        self.assertEqual(response.status_code, 302)
        offer.refresh_from_db()
        self.assertTrue(offer.declined_at)
        from django.test import Client

        self.assertEqual(
            Client(enforce_csrf_checks=True)
            .post(f"/nabidka/{offer.token}/", {"action": "decline"})
            .status_code,
            403,
        )

    def test_web_signature_files_retry_and_conflict(self):
        file = b"%PDF-test"
        self.data["attachments"] = [
            {
                "name": "plan.pdf",
                "content": base64.b64encode(file).decode(),
                "sha256": hashlib.sha256(file).hexdigest(),
            }
        ]

        def submit():
            raw = json.dumps(self.data).encode()
            stamp = str(int(time.time()))
            signature = hmac.new(
                b"test-key", stamp.encode() + b"." + raw, hashlib.sha256
            ).hexdigest()
            return self.client.post(
                "/api/inquiries/enepru/",
                raw,
                content_type="application/json",
                HTTP_X_CRM_TIMESTAMP=stamp,
                HTTP_X_CRM_SIGNATURE=signature,
            )

        with override_settings(CRM_WEBHOOK_SECRET="test-key"):
            self.assertEqual(submit().status_code, 201)
            self.assertEqual(submit().status_code, 200)
            inquiry = Inquiry.objects.get()
            self.assertEqual(inquiry.attachments.count(), 1)
            self.data["description"] = "Změněný požadavek"
            self.assertEqual(submit().status_code, 409)
        self.assertEqual(Inquiry.objects.count(), 1)

    def test_invalid_file_hash_rejected_before_record(self):
        with self.assertRaises(ValidationError):
            decoded_attachments([{"name": "x.pdf", "content": "eA==", "sha256": "bad"}])
        self.assertFalse(Inquiry.objects.exists())

    def test_unverified_email_later_upgraded_without_duplicate(self):
        inquiry, _ = receive(self.source, self.data, verified=False, ack=False)
        self.assertFalse(inquiry.intake_verified)
        same, created = receive(self.source, self.data, verified=True)
        self.assertFalse(created)
        self.assertEqual(same.pk, inquiry.pk)
        self.assertTrue(same.intake_verified)

    def test_daily_backup_is_once_and_rotates_only_own_names(self):
        import os
        from pathlib import Path

        from .auto_backup import daily_backup

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"CRM_BACKUP_DIR": directory}),
        ):
            old = Path(directory) / "CRM-auto-2020-01-01.zip"
            old.write_bytes(b"old")
            manual = Path(directory) / "manual.zip"
            manual.write_bytes(b"keep")

            def backup(*args, **kwargs):
                Path(kwargs["output"]).write_bytes(b"validated-by-command-tests")

            with patch("crm.auto_backup.call_command", side_effect=backup) as command:
                path = daily_backup()
                self.assertTrue(path.exists())
                self.assertEqual(daily_backup(), path)
                self.assertEqual(command.call_count, 1)
            self.assertFalse(old.exists())
            self.assertTrue(manual.exists())

    def test_document_bundle_denies_hidden_and_deleted_files(self):
        from django.contrib.auth.models import Permission
        from django.core.files.base import ContentFile

        from .models import Document

        private = Document.objects.create(
            name="private.pdf",
            file=ContentFile(b"%PDF-private", name="private.pdf"),
            internal=True,
            uploaded_by=self.admin,
        )
        own = Document.objects.create(
            name="own.pdf",
            file=ContentFile(b"%PDF-own", name="own.pdf"),
            uploaded_by=self.worker,
        )
        self.worker.user_permissions.set(
            Permission.objects.filter(content_type__app_label="crm")
        )
        self.client.force_login(self.worker)
        self.assertEqual(
            self.client.get(f"/documents/{private.pk}/preview/").status_code, 404
        )
        self.assertEqual(
            self.client.post(
                "/documents/bundle/", {"documents": [own.pk, private.pk]}
            ).status_code,
            403,
        )
        response = self.client.get(f"/documents/{own.pk}/preview/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("sandbox", response["Content-Security-Policy"])
        response.close()
        self.client.force_login(self.admin)
        response = self.client.post("/documents/bundle/", {"documents": [own.pk]})
        self.assertEqual(response.status_code, 200)
        import io
        import zipfile

        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertEqual(archive.read(archive.namelist()[0]), b"%PDF-own")
        own.deleted_at = timezone.now()
        own.save()
        self.assertEqual(
            self.client.post("/documents/bundle/", {"documents": [own.pk]}).status_code,
            403,
        )

    def test_report_monthly_net_receipts(self):
        from decimal import Decimal

        from .models import Client, Invoice, InvoiceLine
        from .services import issue_invoice, record_payment

        client = Client.objects.create(name="Klient", billing_address="Praha 1")
        invoice = Invoice.objects.create(
            client=client, due_date=timezone.localdate() + timedelta(days=14)
        )
        InvoiceLine.objects.create(
            invoice=invoice, description="PENB", unit_price=1000, quantity=1
        )
        from .services import company

        supplier = company()
        supplier.invoice_year = timezone.localdate().year
        supplier.save()
        invoice = issue_invoice(invoice, self.admin)
        for kind, amount in [("receipt", 500), ("refund", 100)]:
            record_payment(
                invoice,
                {
                    "kind": kind,
                    "amount": Decimal(amount),
                    "date": timezone.localdate(),
                    "method": "bank",
                    "reference": "Test",
                    "request_key": uuid.uuid4(),
                },
                self.admin,
            )
        self.client.force_login(self.admin)
        response = self.client.get("/reports/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["monthly"][0]["received"], Decimal("400"))
        self.assertEqual(response.context["received"], Decimal("400"))

    def test_bundled_pdf_font_covers_czech_alphabet(self):
        from reportlab.pdfbase import pdfmetrics

        from .pdf_fonts import register

        font = pdfmetrics.getFont(register())
        for char in "ěščřžýáíéúůďťňĚŠČŘŽÝÁÍÉÚŮĎŤŇ":
            self.assertTrue(font.face.charToGlyph.get(ord(char)), char)
        self.assertIn(b"DejaVuSans", bytes(self.offer().pdf))
