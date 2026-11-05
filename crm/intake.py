"""One idempotent intake used by HTTPS API and authenticated website mail."""

import base64
import binascii
import hashlib
import json
import os
import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction

from .models import Inquiry, InquiryAttachment, Message
from .services import event

SCHEMA = "enepru.inquiry.v1"
MIME = "application/vnd.enepru.inquiry+json"


def website_secret(source):
    return (
        settings.CRM_WEBHOOK_SECRET
        if source.secret_env == "CRM_WEBHOOK_SECRET"
        else os.environ.get(source.secret_env, "")
        or getattr(settings, "CRM_WEBSITE_KEYS", {}).get(source.secret_env, "")
    )


def decoded_attachments(items):
    if not isinstance(items, list) or len(items) > 10:
        raise ValidationError("Nejvýše 10 příloh.")
    output = []
    total = 0
    for item in items:
        if not isinstance(item, dict):
            raise ValidationError("Neplatná příloha.")
        name = Path(str(item.get("name", "")).replace("\\", "/")).name[:240]
        if Path(name).suffix.lower() not in {
            ".pdf",
            ".png",
            ".jpg",
            ".jpeg",
            ".zip",
            ".dwg",
            ".dxf",
            ".docx",
            ".xlsx",
        }:
            raise ValidationError("Nepovolený typ přílohy.")
        try:
            content = base64.b64decode(item["content"], validate=True)
        except (KeyError, TypeError, ValueError, binascii.Error) as error:
            raise ValidationError("Poškozený obsah přílohy.") from error
        total += len(content)
        if not content or len(content) > 10 * 1024 * 1024 or total > 15 * 1024 * 1024:
            raise ValidationError("Přílohy smějí mít nejvýše 15 MB celkem.")
        digest = hashlib.sha256(content).hexdigest()
        if item.get("sha256") != digest:
            raise ValidationError("Kontrolní součet přílohy nesouhlasí.")
        output.append((name, content, digest))
    return output


@transaction.atomic
def receive(source, data, attachments=None, actor=None, ack=True, verified=True):
    from .forms import InquiryForm

    if not isinstance(data, dict):
        raise ValidationError("Neplatná poptávka.")
    try:
        external = uuid.UUID(data["external_id"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValidationError("Neplatný identifikátor poptávky.") from error
    if not source.active:
        raise ValidationError("Zdroj poptávek je vypnutý.")
    form = InquiryForm(data)
    form.fields["address"].required = False
    if not form.is_valid():
        raise ValidationError(form.errors.as_text())
    details = data.get("source_details") or {}
    if not isinstance(details, dict) or len(json.dumps(details)) > 64000:
        raise ValidationError("Neplatné doplňující údaje.")
    files = attachments or []
    normalized = dict(form.cleaned_data)
    if details or files:
        normalized = {
            "fields": normalized,
            "details": details,
            "attachments": [(name, digest) for name, content, digest in files],
        }
    digest = hashlib.sha256(
        json.dumps(normalized, sort_keys=True, default=str).encode()
    ).hexdigest()
    key = uuid.uuid5(uuid.NAMESPACE_URL, f"{source.slug}:{external}")
    obj, created = Inquiry.objects.get_or_create(
        submission_key=key,
        defaults={
            **form.cleaned_data,
            "source": source.name if verified else "Webový e-mail (neověřený zdroj)",
            "website": source if verified else None,
            "intake_hash": digest,
            "source_details": details,
            "intake_verified": verified,
        },
    )
    if not created and obj.intake_hash != digest:
        raise ValidationError(
            "Stejné ID poptávky obsahuje jiný obsah.", code="conflict"
        )
    if not created and verified and not obj.intake_verified:
        obj.intake_verified = True
        obj.website = source
        obj.source = source.name
        obj.save(update_fields=["intake_verified", "website", "source"])
        event(actor, "Ověřen původ dříve přijaté webové poptávky", inquiry=obj.pk)
    if created:
        for name, content, digest in files:
            InquiryAttachment.objects.create(
                inquiry=obj,
                name=name,
                file=ContentFile(content, name=name),
                sha256=digest,
            )
        if ack:
            Message.objects.create(
                inquiry=obj,
                to=obj.email,
                subject="Přijali jsme vaši poptávku",
                body=f"Dobrý den,\n\npřijali jsme vaši poptávku P{obj.pk:05d}. Ozveme se s nabídkou. Toto není potvrzení objednávky ani konečné ceny.\n\nIng. Stanislav Lahodný",
                dedupe_key=f"ack:{obj.pk}",
            )
        event(
            actor,
            "Přijata webová poptávka",
            inquiry=obj.pk,
            website=source.pk,
            verified=verified,
        )
    return obj, created
