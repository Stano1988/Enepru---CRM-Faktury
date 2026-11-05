import base64
import io
import secrets

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Permission
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django_otp import devices_for_user
from django_otp import login as otp_login
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from .models import Access
from .office import form_page, manager

PERMISSION_NAMES = {
    "client": "Klienti",
    "sequence": "Číselné řady zakázek",
    "job": "Zakázky",
    "note": "Poznámky",
    "change": "Historie zakázek",
    "access": "Přístup uživatelů",
    "company": "Údaje firmy",
    "contact": "Kontaktní osoby",
    "property": "Evidence nemovitostí (volitelné)",
    "inquiry": "Poptávky",
    "offer": "Nabídky",
    "folder": "Složky",
    "document": "Dokumenty",
    "task": "Úkoly a zaměření",
    "requirement": "Starší požadavky na podklady",
    "expense": "Náklady a odměny",
    "invoice": "Faktury",
    "invoiceline": "Text faktury",
    "payment": "Úhrady",
    "banktransaction": "Importované bankovní platby",
    "message": "Odchozí pošta",
    "automation": "Automatizace",
    "event": "Události",
    "handover": "Předání",
    "inquiryattachment": "Přílohy poptávek",
    "clientlink": "Odkazy pro klienty",
    "extrawork": "Vícepráce",
    "notification": "Upozornění",
    "priceitem": "Ceník (volitelné)",
    "clientchange": "Historie klientů",
    "calendarentry": "Vlastní zápisy v kalendáři",
    "receivedmail": "Přijatá pošta",
    "mailattachment": "Přílohy pošty",
    "mailboxcursor": "Stav příjmu pošty",
    "mailboxsync": "Kontroly schránky",
    "websitesource": "Připojené weby",
}


class CzechPermissions(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        action = {
            "add": "vytvářet",
            "change": "upravovat",
            "delete": "mazat",
            "view": "prohlížet",
        }.get(obj.codename.split("_", 1)[0], "spravovat")
        return f"{PERMISSION_NAMES.get(obj.content_type.model, 'Ostatní nastavení')} — {action}"


class UserForm(forms.ModelForm):
    password = forms.CharField(
        label="Nové heslo (prázdné = beze změny)",
        widget=forms.PasswordInput,
        required=False,
    )
    all_jobs = forms.BooleanField(label="Vidí všechny zakázky", required=False)
    finances = forms.BooleanField(label="Vidí finance a ceny", required=False)
    export = forms.BooleanField(label="Smí exportovat", required=False)
    user_permissions = CzechPermissions(
        label="Povolené činnosti",
        queryset=Permission.objects.filter(content_type__app_label="crm")
        .select_related("content_type")
        .order_by("content_type__model", "codename"),
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )

    class Meta:
        model = get_user_model()
        fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "is_active",
            "user_permissions",
        ]

    def clean_password(self):
        password = self.cleaned_data.get("password")
        if not self.instance.pk and not password:
            raise forms.ValidationError("Pro nový účet zadejte heslo.")
        if password:
            validate_password(password, self.instance)
        return password


@login_required
def users(request):
    manager(request.user)
    return render(request, "crm/users.html", {"users": get_user_model().objects.all()})


@login_required
def user_edit(request, pk=None):
    manager(request.user)
    obj = get_object_or_404(get_user_model(), pk=pk) if pk else None
    access = Access.objects.filter(user=obj).first() if obj else None
    initial = {
        name: getattr(access, name, False)
        for name in ["all_jobs", "finances", "export"]
    }
    form = UserForm(request.POST or None, instance=obj, initial=initial)
    if request.method == "POST" and form.is_valid():
        if obj and obj.pk == request.user.pk and not form.cleaned_data["is_active"]:
            form.add_error("is_active", "Nemůžete deaktivovat právě používaný účet.")
        else:
            with transaction.atomic():
                user = form.save(commit=False)
                if form.cleaned_data["password"]:
                    user.set_password(form.cleaned_data["password"])
                user.save()
                form.save_m2m()
                Access.objects.update_or_create(
                    user=user,
                    defaults={
                        name: form.cleaned_data[name]
                        for name in ["all_jobs", "finances", "export"]
                    },
                )
            return redirect("users")
    return render(
        request,
        "crm/user_form.html",
        {"form": form, "title": "Uživatel a jeho oprávnění"},
    )


class TokenForm(forms.Form):
    token = forms.CharField(
        label="Kód z ověřovací aplikace nebo jednorázový obnovovací kód",
        max_length=30,
        strip=True,
        widget=forms.TextInput(attrs={"autocomplete": "one-time-code"}),
    )


@login_required
def mfa_setup(request):
    if TOTPDevice.objects.filter(user=request.user, confirmed=True).exists():
        return render(request, "crm/mfa.html", {"configured": True})
    device = TOTPDevice.objects.filter(user=request.user, confirmed=False).first()
    if not device:
        device = TOTPDevice.objects.create(
            user=request.user, name="Ověřovací aplikace", confirmed=False
        )
    form = TokenForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            device = TOTPDevice.objects.select_for_update().get(pk=device.pk)
            if device.verify_token(form.cleaned_data["token"]):
                device.confirmed = True
                device.save()
                otp_login(request, device)
                recovery, _ = StaticDevice.objects.get_or_create(
                    user=request.user, name="Obnovovací kódy"
                )
                recovery.token_set.all().delete()
                tokens = [secrets.token_hex(8) for _ in range(10)]
                for token in tokens:
                    StaticToken.objects.create(device=recovery, token=token)
                return render(request, "crm/mfa.html", {"tokens": tokens})
        form.add_error("token", "Kód není platný nebo byl použit. Zkuste aktuální kód.")
    import qrcode

    output = io.BytesIO()
    qrcode.make(device.config_url).save(output, format="PNG")
    return render(
        request,
        "crm/mfa.html",
        {"form": form, "qr": base64.b64encode(output.getvalue()).decode()},
    )


@login_required
def mfa_verify(request):
    if request.user.is_verified():
        return redirect("dashboard")
    devices = list(devices_for_user(request.user, confirmed=True))
    if not devices:
        return redirect("mfa_setup")
    form = TokenForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        for device in devices:
            with transaction.atomic():
                locked = type(device).objects.select_for_update().get(pk=device.pk)
                if locked.verify_token(form.cleaned_data["token"]):
                    otp_login(request, locked)
                    return redirect("dashboard")
        form.add_error("token", "Neplatný kód. Po opakovaných chybách chvíli vyčkejte.")
    return form_page(request, form, "Druhý krok přihlášení")


@login_required
def profile(request):
    class ProfileForm(forms.ModelForm):
        class Meta:
            model = get_user_model()
            fields = ["first_name", "last_name", "email"]

    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("profile")
    return form_page(request, form, "Můj profil")


from django.conf import settings
from django.contrib.auth.views import PasswordResetView
from django.http import HttpResponseRedirect


class ConfiguredPasswordReset(PasswordResetView):
    def form_valid(self, form):
        if not settings.CRM_EMAIL_ENABLED:
            return HttpResponseRedirect(self.get_success_url())
        return super().form_valid(form)
