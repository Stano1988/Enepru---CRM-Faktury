from django.urls import path

from . import accounts, office, views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("clients/", views.clients, name="clients"),
    path("clients/new/", views.client_new, name="client_new"),
    path("jobs/new/", views.job_new, name="job_new"),
    path("jobs/<int:pk>/", views.job_detail, name="job_detail"),
    path("jobs/<int:pk>/edit/", views.job_edit, name="job_edit"),
]

urlpatterns += [
    path("clients/<int:pk>/edit/", office.client_edit, name="client_edit"),
    path("contacts/new/", office.contact_new, name="contact_new"),
    path("properties/", office.properties, name="properties"),
    path("properties/new/", office.property_form, name="property_new"),
    path("properties/<int:pk>/edit/", office.property_form, name="property_edit"),
    path("inquiries/", office.inquiries, name="inquiries"),
    path("inquiries/new/", office.inquiry_new, name="inquiry_new"),
    path("inquiries/<int:pk>/", office.inquiry_detail, name="inquiry_detail"),
    path("inquiries/<int:pk>/edit/", office.inquiry_edit, name="inquiry_edit"),
    path("inquiries/<int:pk>/offer/", office.offer_new, name="offer_new"),
    path("inquiries/<int:pk>/convert/", office.convert, name="convert"),
    path("poptavka/", office.public_inquiry, name="public_inquiry"),
    path("nabidka/<uuid:token>/", office.public_offer, name="public_offer"),
    path("jobs/<int:pk>/documents/new/", office.document_new, name="document_new"),
    path(
        "documents/<int:pk>/download/",
        office.document_download,
        name="document_download",
    ),
    path("documents/<int:pk>/action/", office.document_action, name="document_action"),
    path("jobs/<int:pk>/folders/new/", office.folder_new, name="folder_new"),
    path("jobs/<int:pk>/tasks/new/", office.task_new, name="task_new"),
    path("tasks/<int:pk>/edit/", office.task_edit, name="task_edit"),
    path(
        "jobs/<int:pk>/requirements/new/",
        office.requirement_new,
        name="requirement_new",
    ),
    path(
        "requirements/<int:pk>/update/",
        office.requirement_update,
        name="requirement_update",
    ),
    path(
        "jobs/<int:pk>/requirements/message/",
        office.requirements_message,
        name="requirements_message",
    ),
    path("jobs/<int:pk>/expenses/new/", office.expense_new, name="expense_new"),
    path("calendar/", office.calendar, name="calendar"),
    path("invoices/", office.invoices, name="invoices"),
    path("invoices/new/", office.invoice_form, name="invoice_new"),
    path("invoices/<int:pk>/", office.invoice_detail, name="invoice_detail"),
    path("invoices/<int:pk>/edit/", office.invoice_form, name="invoice_edit"),
    path("invoices/<int:pk>/action/", office.invoice_action, name="invoice_action"),
    path(
        "invoices/<int:pk>/pdf/",
        office.invoice_file,
        {"kind": "pdf"},
        name="invoice_pdf",
    ),
    path(
        "invoices/<int:pk>/qr/", office.invoice_file, {"kind": "qr"}, name="invoice_qr"
    ),
    path("invoices/<int:pk>/payment/", office.payment_new, name="payment_new"),
    path("outbox/", office.outbox, name="outbox"),
    path("outbox/<int:pk>/edit/", office.message_edit, name="message_edit"),
    path("outbox/<int:pk>/send/", office.message_send, name="message_send"),
    path("jobs/<int:pk>/handover/", office.handover_new, name="handover_new"),
    path("jobs/<int:pk>/archive/", office.archive, name="archive"),
    path("jobs/<int:pk>/export/", office.archive_download, name="archive_download"),
    path("reports/", office.reports, name="reports"),
    path("bank/", office.bank_transactions, name="bank_transactions"),
    path("bank/import/", office.bank_import, name="bank_import"),
    path("bank/<int:pk>/match/", office.bank_match, name="bank_match"),
    path("settings/", office.settings_view, name="settings"),
    path("automations/run/", office.run_automation, name="run_automation"),
]

urlpatterns += [
    path("users/", accounts.users, name="users"),
    path("users/new/", accounts.user_edit, name="user_new"),
    path("users/<int:pk>/edit/", accounts.user_edit, name="user_edit"),
    path("security/setup/", accounts.mfa_setup, name="mfa_setup"),
    path("security/verify/", accounts.mfa_verify, name="mfa_verify"),
]

urlpatterns += [
    path("jobs/<int:pk>/client-link/", office.client_link_new, name="client_link_new"),
    path(
        "client-links/<int:pk>/revoke/",
        office.client_link_revoke,
        name="client_link_revoke",
    ),
    path("klient/<uuid:token>/", office.client_portal, name="client_portal"),
    path(
        "klient/<uuid:token>/soubor/<int:pk>/",
        office.portal_document,
        name="portal_document",
    ),
    path("jobs/<int:pk>/extra/", office.extra_new, name="extra_new"),
    path("viceprace/<uuid:token>/", office.extra_accept, name="extra_accept"),
    path("documents/<int:pk>/edit/", office.document_edit, name="document_edit"),
    path(
        "inquiry-attachments/<int:pk>/",
        office.inquiry_attachment,
        name="inquiry_attachment",
    ),
]

urlpatterns += [
    path(
        "notifications/<int:pk>/read/",
        office.notification_read,
        name="notification_read",
    )
]

urlpatterns += [
    path("catalog/", office.catalog, name="catalog"),
    path("catalog/new/", office.catalog_edit, name="catalog_new"),
    path("catalog/<int:pk>/edit/", office.catalog_edit, name="catalog_edit"),
]

urlpatterns += [
    path("payments/<int:pk>/void/", office.payment_void, name="payment_void")
]

urlpatterns += [
    path("clients/ares/", office.ares_lookup, name="ares_lookup"),
    path("archives/", office.archives, name="archives"),
    path("archives/<int:pk>/retention/", office.retention_edit, name="retention_edit"),
]

urlpatterns += [path("profile/", accounts.profile, name="profile")]

urlpatterns += [
    path("settings/backup/", office.backup_download, name="backup_download")
]
