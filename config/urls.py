from django.contrib import admin
from django.urls import include, path

from crm.accounts import ConfiguredPasswordReset

urlpatterns = [
    path(
        "accounts/password_reset/",
        ConfiguredPasswordReset.as_view(),
        name="password_reset",
    ),
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("crm.urls")),
]
