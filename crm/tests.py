from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client as Browser
from django.test import TestCase

from .models import Change, Client, Job


class WorkflowTests(TestCase):
    def setUp(self):
        U = get_user_model()
        self.owner = U.objects.create_superuser(
            "owner", "owner@example.com", "test-password-long"
        )
        self.worker = U.objects.create_user("worker", password="test-password-long")
        self.worker.user_permissions.set(
            Permission.objects.filter(
                content_type__app_label="crm",
                codename__in=["view_job", "change_job", "add_note", "view_client"],
            )
        )
        self.customer = Client.objects.create(
            name="Test klient", billing_address="Praha 1"
        )
        self.job = Job.objects.create(
            title="PENB domu",
            client=self.customer,
            address="Praha",
            due_date=date(2027, 2, 1),
            assigned_to=self.owner,
        )

    def test_numbering_and_login(self):
        self.assertEqual(self.job.number, "Z27/001")
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.client.post(
                "/accounts/login/",
                {"username": "owner", "password": "test-password-long"},
            ).status_code,
            302,
        )
        self.assertContains(self.client.get("/"), "Z27/001")

    def test_create_edit_and_note(self):
        self.client.force_login(self.owner)
        data = {
            "title": "Pasport",
            "client": self.customer.pk,
            "address": "Brno",
            "due_date": "2027-03-01",
            "assigned_to": self.owner.pk,
            "service": "passport",
            "status": "new",
            "description": "Původní",
            "next_step": "Zaměřit",
        }
        self.assertEqual(self.client.post("/jobs/new/", data).status_code, 302)
        job = Job.objects.get(title="Pasport")
        self.assertEqual(job.number, "Z27/002")
        data["description"] = "Doplněné zadání"
        self.client.post(f"/jobs/{job.pk}/edit/", data)
        self.assertEqual(Change.objects.get(job=job).before["description"], "Původní")
        self.client.post(f"/jobs/{job.pk}/", {"text": "Klient dodal podklady"})
        self.assertEqual(job.notes.get().author, self.owner)
        self.assertContains(
            self.client.get(f"/jobs/{job.pk}/"), "Klient dodal podklady"
        )

    def test_worker_cannot_read_or_change_foreign_job(self):
        self.client.force_login(self.worker)
        self.assertNotContains(self.client.get("/"), "PENB domu")
        self.assertEqual(self.client.get(f"/jobs/{self.job.pk}/").status_code, 404)
        self.assertEqual(self.client.get(f"/jobs/{self.job.pk}/edit/").status_code, 404)
        self.assertEqual(self.client.get("/jobs/new/").status_code, 403)
        self.assertNotContains(self.client.get("/clients/"), "Test klient")

    def test_assigned_worker_cannot_reassign(self):
        self.job.assigned_to = self.worker
        self.job.save()
        self.client.force_login(self.worker)
        data = {
            "title": "Upraveno",
            "address": "Praha",
            "due_date": "2027-02-01",
            "service": "penb",
            "status": "working",
            "description": "text",
            "next_step": "Kontrola",
            "assigned_to": self.owner.pk,
            "client": 9999,
        }
        self.assertEqual(
            self.client.post(f"/jobs/{self.job.pk}/edit/", data).status_code, 302
        )
        self.job.refresh_from_db()
        self.assertEqual(self.job.assigned_to, self.worker)
        self.assertEqual(self.job.client, self.customer)

    def test_csrf_required(self):
        browser = Browser(enforce_csrf_checks=True)
        browser.force_login(self.owner)
        self.assertEqual(
            browser.post("/clients/new/", {"name": "Bez tokenu"}).status_code, 403
        )

    def test_no_permissions_means_denied(self):
        user = get_user_model().objects.create_user("outsider")
        self.client.force_login(user)
        self.assertEqual(self.client.get("/").status_code, 403)
