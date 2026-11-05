from django.core.cache import cache
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django_otp import devices_for_user


class SecurityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not request.user.is_verified():
            if any(
                devices_for_user(request.user, confirmed=True)
            ) and request.path not in [reverse("mfa_verify"), reverse("logout")]:
                return redirect("mfa_verify")
        # Bound public submission volume, without trusting caller-supplied forwarding headers.
        if request.method == "POST" and (
            request.path == "/poptavka/" or request.path.startswith("/klient/")
        ):
            import hashlib

            key = (
                "public:"
                + hashlib.sha256(
                    request.META.get("REMOTE_ADDR", "").encode()
                ).hexdigest()
            )
            cache.add(key, 0, 3600)
            if cache.incr(key) > 30:
                return HttpResponse(
                    "Příliš mnoho požadavků. Zkuste to později.", status=429
                )
        response = self.get_response(request)
        if not request.path.startswith("/static/"):
            response["Cache-Control"] = "private, no-store"
            response["Referrer-Policy"] = "same-origin"
            response.setdefault(
                "Content-Security-Policy",
                (
                    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
                ),
            )
        return response
