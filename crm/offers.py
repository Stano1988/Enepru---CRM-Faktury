"""Versioned offer documents and explicit client decisions."""

import io
from datetime import timedelta
from xml.sax.saxutils import escape

from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Inquiry, Message, Offer
from .office import manager
from .services import company, event


def make_pdf(offer):
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    from .pdf_fonts import register

    font_name = register()
    styles = getSampleStyleSheet()
    for style in styles.byName.values():
        style.fontName = font_name
    supplier = company()
    parts = [
        ("Title", f"Cenová nabídka P{offer.inquiry_id:05d} / {offer.version}"),
        (
            "Normal",
            f"{supplier.name}\n{supplier.address}\nIČO: {supplier.company_id}\n{supplier.email}",
        ),
        ("Heading2", "Zákazník a nemovitost"),
        (
            "Normal",
            f"{offer.inquiry.name}\n{offer.inquiry.email}\n{offer.inquiry.address}",
        ),
        ("Heading2", "Rozsah a výstupy"),
        ("Normal", offer.scope),
        ("Heading2", f"Cena celkem: {offer.price:.2f} Kč"),
        (
            "Normal",
            f"Dodavatel není plátce DPH.\nTermín vyhotovení: {offer.due_date:%d.%m.%Y}\nPlatnost nabídky do: {offer.valid_until:%d.%m.%Y}",
        ),
        ("Heading2", "Podmínky"),
        ("Normal", offer.terms),
    ]
    out = io.BytesIO()
    story = []
    for style, text in parts:
        story.extend(
            [
                Paragraph(escape(text).replace("\n", "<br/>"), styles[style]),
                Spacer(1, 12),
            ]
        )
    SimpleDocTemplate(out, title="Cenová nabídka", author=supplier.name).build(story)
    return out.getvalue()


@login_required
@permission_required("crm.view_offer", raise_exception=True)
def download(request, pk):
    manager(request.user)
    offer = get_object_or_404(Offer.objects.select_related("inquiry"), pk=pk)
    if not offer.pdf:
        # Freeze legacy versions once; never regenerate a stored offer from edited settings.
        with transaction.atomic():
            offer = Offer.objects.select_for_update().get(pk=pk)
            if not offer.pdf:
                offer.pdf = make_pdf(offer)
                offer.save(update_fields=["pdf"])
    response = HttpResponse(bytes(offer.pdf), content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="Nabidka-P{offer.inquiry_id:05d}-v{offer.version}.pdf"'
    )
    return response


@transaction.atomic
def decline(offer):
    inquiry = Inquiry.objects.select_for_update().get(pk=offer.inquiry_id)
    offer = Offer.objects.select_for_update().get(pk=offer.pk)
    if offer.accepted_at or inquiry.job_id:
        raise ValidationError(
            "Potvrzenou nabídku již nelze odmítnout. Kontaktujte dodavatele."
        )
    if offer.declined_at:
        return
    if offer.revoked or offer.valid_until < timezone.localdate():
        raise ValidationError("Tato verze nabídky již není platná.")
    offer.declined_at = timezone.now()
    offer.save(update_fields=["declined_at"])
    inquiry.status = "lost"
    inquiry.lost_reason = "Klient odmítl nabídku přes odkaz"
    inquiry.save(update_fields=["status", "lost_reason"])
    Message.objects.filter(offer=offer, state="draft").update(state="cancelled")
    event(None, "Klient odmítl nabídku", offer=offer.pk, inquiry=inquiry.pk)


@login_required
@permission_required("crm.change_offer", raise_exception=True)
@require_POST
@transaction.atomic
def revoke(request, pk):
    manager(request.user)
    offer = get_object_or_404(Offer.objects.select_for_update(), pk=pk)
    if offer.accepted_at:
        from django.http import HttpResponseBadRequest

        return HttpResponseBadRequest("Potvrzenou nabídku řešte změnou zakázky.")
    offer.revoked = True
    offer.save(update_fields=["revoked"])
    Message.objects.filter(offer=offer, state="draft").update(state="cancelled")
    event(request.user, "Odvolána nabídka", offer=offer.pk)
    return redirect("inquiry_detail", pk=offer.inquiry_id)


def prepare_followups():
    """One reviewable reminder, never unsolicited automatic offer dispatch."""
    count = 0
    for offer in (
        Offer.objects.filter(
            sent_at__lte=timezone.now() - timedelta(days=5),
            accepted_at__isnull=True,
            declined_at__isnull=True,
            revoked=False,
            valid_until__gte=timezone.localdate(),
            inquiry__job__isnull=True,
        )
        .exclude(inquiry__status="lost")
        .select_related("inquiry")
    ):
        _, created = Message.objects.get_or_create(
            dedupe_key=f"offer-followup:{offer.pk}",
            defaults={
                "inquiry": offer.inquiry,
                "offer": offer,
                "to": offer.inquiry.email,
                "subject": f"Připomenutí nabídky P{offer.inquiry_id:05d}",
                "body": f"Dobrý den,\n\npřipomínáme naši nabídku na {offer.scope} za {offer.price:.2f} Kč. Nabídka platí do {offer.valid_until:%d.%m.%Y}. Pro potvrzení použijte odkaz v původní zprávě nebo nám odpovězte.\n\nIng. Stanislav Lahodný",
            },
        )
        count += created
    return count
