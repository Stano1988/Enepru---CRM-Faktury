"""Read-only mail intake. External HTML is converted to text, never rendered."""

import hashlib
import hmac
import imaplib
import json
import re
import ssl
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

from .models import (
    Client,
    Document,
    Inquiry,
    InquiryAttachment,
    MailAttachment,
    MailboxCursor,
    MailboxSync,
    Message,
    ReceivedMail,
    WebsiteSource,
)
from .services import event

MAX_EMAIL_BYTES = 25 * 1024 * 1024
ALLOWED = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".heic",
    ".docx",
    ".xlsx",
    ".xlsm",
    ".dwg",
    ".dxf",
    ".ifc",
    ".txt",
    ".csv",
    ".zip",
    ".xml",
    ".odt",
    ".ods",
    ".doc",
    ".xls",
}


class PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.blocked = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.blocked += 1
        if tag in ("br", "p", "div", "li", "tr"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.blocked = max(0, self.blocked - 1)

    def handle_data(self, data):
        if not self.blocked:
            self.parts.append(data)


@transaction.atomic
def import_email(raw, source="Soubor EML", outgoing=False):
    if len(raw) > MAX_EMAIL_BYTES:
        raise ValidationError("E-mail smí mít nejvýše 25 MB.")
    fingerprint = hashlib.sha256(raw).hexdigest()
    existing = ReceivedMail.objects.filter(fingerprint=fingerprint).first()
    if existing:
        if outgoing and not existing.is_sent:
            existing.is_sent = True
            existing.save(update_fields=["is_sent"])
        elif not outgoing and not existing.is_received:
            existing.is_received = True
            existing.save(update_fields=["is_received"])
        return existing, False
    try:
        parsed = BytesParser(policy=policy.default).parsebytes(raw)
        sender_name, sender_email = parseaddr(str(parsed.get("From", "")))
        validate_email(sender_email)
        body_part = parsed.get_body(preferencelist=("plain", "html"))
        body = body_part.get_content() if body_part else ""
        if not isinstance(body, str):
            body = ""
        if body_part and body_part.get_content_type() == "text/html":
            parser = PlainHTML()
            parser.feed(body)
            body = "".join(parser.parts)
        sent_at = None
        if parsed.get("Date"):
            try:
                sent_at = parsedate_to_datetime(str(parsed["Date"]))
                if timezone.is_naive(sent_at):
                    sent_at = timezone.make_aware(sent_at)
            except (ValueError, TypeError, OverflowError):
                pass
        references = re.findall(
            r"<[^<>\s]{1,995}>",
            str(parsed.get("In-Reply-To", ""))
            + " "
            + str(parsed.get("References", "")),
        )[-30:]
        parent = (
            Message.objects.filter(
                message_id__in=references,
                to__iexact=sender_email,
            )
            .order_by("-id")
            .first()
        )
        recipients = [
            address
            for name, address in getaddresses(
                parsed.get_all("To", []) + parsed.get_all("Cc", [])
            )
            if address
        ][:30]
        own_message = (
            Message.objects.filter(message_id=str(parsed.get("Message-ID", "")))
            .exclude(message_id="")
            .first()
            if outgoing
            else None
        )
        external_parent = (
            ReceivedMail.objects.filter(message_id__in=references)
            .exclude(inquiry__isnull=True, job__isnull=True)
            .order_by("-received_at")
            .first()
        )
        if (
            external_parent
            and not outgoing
            and sender_email.casefold()
            not in [address.casefold() for address in external_parent.recipients]
            and sender_email.casefold() != external_parent.sender_email.casefold()
        ):
            external_parent = None
        linked = own_message or parent or external_parent
        mail = ReceivedMail.objects.create(
            is_received=not outgoing,
            is_sent=outgoing,
            recipients=recipients,
            job=linked.job if linked else None,
            invoice=linked.invoice if linked else None,
            fingerprint=fingerprint,
            message_id=str(parsed.get("Message-ID", ""))[:998],
            references=references,
            sender_name=sender_name[:200],
            sender_email=sender_email,
            subject=str(parsed.get("Subject", "Bez předmětu"))[:250],
            body=body[:200000],
            sent_at=sent_at,
            source=source[:100],
            inquiry=linked.inquiry if linked else None,
        )
        structured = {}
        structured_verified = False
        structured_error = ""
        metadata_parts = [
            part
            for part in parsed.walk()
            if part.get_content_type() == "application/vnd.enepru.inquiry+json"
        ]
        if len(metadata_parts) > 1:
            structured_error = (
                "Více metadat poptávky v jednom e-mailu. Vyžaduje kontrolu."
            )
        elif metadata_parts:
            raw_meta = metadata_parts[0].get_payload(decode=True) or b""
            try:
                if len(raw_meta) > 64000:
                    raise ValueError
                structured = json.loads(raw_meta)
                if (
                    not isinstance(structured, dict)
                    or structured.get("schema") != "enepru.inquiry.v1"
                ):
                    raise ValueError
                source_obj = WebsiteSource.objects.filter(
                    slug=structured.get("source_slug"), active=True
                ).first()
                if not source_obj:
                    structured_error = (
                        "Neznámý nebo vypnutý web. Zkontrolujte zdroj v nastavení webů."
                    )
                else:
                    from .intake import website_secret

                    secret = website_secret(source_obj)
                    signature = str(parsed.get("X-CRM-Mail-Signature", ""))
                    if secret:
                        structured_verified = hmac.compare_digest(
                            hmac.new(
                                secret.encode(), raw_meta, hashlib.sha256
                            ).hexdigest(),
                            signature,
                        )
                        if not structured_verified:
                            structured_error = "Podpis údajů poptávky neodpovídá. Zkontrolujte propojení webu."
            except (ValueError, TypeError):
                structured = {}
                structured_error = "Neplatná metadata webové poptávky."
        elif str(parsed.get("Subject", "")).startswith("Nezávazná poptávka"):
            # Backward-compatible ENEPRU mail: the client is in Reply-To, not From.
            _, reply_to = parseaddr(str(parsed.get("Reply-To", "")))
            labels = {}
            for line in body.splitlines():
                key, sep, value = line.partition(":")
                if sep and key not in labels:
                    labels[key] = value.strip()
            if reply_to and labels.get("E-mail", "").casefold() == reply_to.casefold():
                validate_email(reply_to)
                import uuid

                address = labels.get("Adresa", "")
                if not address:
                    address = ", ".join(
                        labels.get(key, "")
                        for key in [
                            "Obec",
                            "Číslo popisné / parcelní",
                            "Katastrální území",
                        ]
                        if labels.get(key)
                    )
                service = (
                    "passport"
                    if "pasport" in mail.subject.casefold()
                    else ("other" if "dotaz" in mail.subject.casefold() else "penb")
                )
                if service == "penb" and labels.get("Také pasport") == "True":
                    service = "both"
                structured = {
                    "schema": "enepru.inquiry.v1",
                    "source_slug": "enepru",
                    "external_id": str(
                        uuid.uuid5(uuid.NAMESPACE_URL, "legacy-mail:" + fingerprint)
                    ),
                    "name": labels.get("Jméno") or reply_to,
                    "email": reply_to,
                    "phone": labels.get("Telefon", ""),
                    "address": address,
                    "service": service,
                    "description": body,
                    "source_details": {"legacy_mail": True},
                }
        mail.structured = structured
        mail.structured_verified = structured_verified
        mail.structured_error = structured_error
        mail.save(
            update_fields=["structured", "structured_verified", "structured_error"]
        )
        skipped = []
        total = 0
        count = 0
        for part in parsed.iter_attachments():
            if part.get_content_type() == "application/vnd.enepru.inquiry+json":
                continue
            name = Path(part.get_filename() or "priloha").name[:240]
            content = part.get_payload(decode=True)
            if (
                not content
                or Path(name).suffix.lower() not in ALLOWED
                or count >= 10
                or total + len(content) > MAX_EMAIL_BYTES
            ):
                skipped.append(name)
                continue
            count += 1
            total += len(content)
            MailAttachment.objects.create(
                mail=mail,
                name=name,
                file=ContentFile(content, name=name),
                sha256=hashlib.sha256(content).hexdigest(),
            )
        mail.skipped_attachments = skipped
        mail.save(update_fields=["skipped_attachments"])
        if linked and linked.inquiry_id and not outgoing:
            inquiry = linked.inquiry
            inquiry.last_reply_at = timezone.now()
            if inquiry.status == "waiting":
                inquiry.status = "review"
            inquiry.save(update_fields=["last_reply_at", "status"])
            for attachment in mail.attachments.all():
                if not inquiry.attachments.filter(
                    sha256=attachment.sha256, name=attachment.name
                ).exists():
                    InquiryAttachment.objects.create(
                        inquiry=inquiry,
                        file=attachment.file.name,
                        name=attachment.name,
                        sha256=attachment.sha256,
                    )
                if inquiry.job_id and not inquiry.job.archived_at:
                    from .services import ensure_folders

                    ensure_folders(inquiry.job)
                    if not inquiry.job.documents.filter(
                        sha256=attachment.sha256, name=attachment.name
                    ).exists():
                        Document.objects.create(
                            job=inquiry.job,
                            folder=inquiry.job.folders.get(name="Podklady od klienta"),
                            name=attachment.name,
                            file=attachment.file.name,
                            sha256=attachment.sha256,
                            uploaded_by=None,
                            internal=False,
                            origin="Klient e-mailem",
                        )
            event(
                None,
                "Přijata e-mailová odpověď k poptávce",
                linked.job,
                inquiry=linked.inquiry_id,
                mail=mail.pk,
            )
        return mail, True
    except (ValueError, LookupError, UnicodeError) as error:
        raise ValidationError(
            "Soubor se nepodařilo přečíst jako platný e-mail."
        ) from error


@transaction.atomic
def mail_to_inquiry(mail, user=None):
    mail = ReceivedMail.objects.select_for_update().get(pk=mail.pk)
    if mail.inquiry_id:
        return mail.inquiry
    if not mail.is_received:
        raise ValidationError(
            "Odeslaná zpráva není nová poptávka. Přiřaďte ji k existujícímu záznamu."
        )
    if mail.structured:
        if mail.structured_error:
            raise ValidationError(mail.structured_error)
        from .intake import receive

        source_obj = WebsiteSource.objects.filter(
            slug=mail.structured.get("source_slug"), active=True
        ).first()
        if not source_obj:
            raise ValidationError("Neznámý nebo vypnutý zdroj webu.")
        files = []
        for attachment in mail.attachments.order_by("pk"):
            with attachment.file.open("rb") as stream:
                content = stream.read()
            files.append((attachment.name, content, attachment.sha256))
        manifest = mail.structured.get("attachment_manifest")
        if mail.structured_verified and manifest != [
            {"name": name, "sha256": digest} for name, content, digest in files
        ]:
            raise ValidationError(
                "Podklady neodpovídají podepsanému seznamu příloh. Zkontrolujte úplnost zprávy."
            )
        inquiry, created = receive(
            source_obj,
            mail.structured,
            attachments=files,
            actor=user,
            ack=False,
            verified=mail.structured_verified,
        )
        mail.inquiry = inquiry
        mail.save(update_fields=["inquiry"])
        return inquiry
    if mail.structured_error:
        raise ValidationError(mail.structured_error)
    text = (mail.subject + "\n" + mail.body).casefold()
    penb = "penb" in text or "energetick" in text
    passport = "pasport" in text
    service = (
        "both"
        if penb and passport
        else ("passport" if passport else ("penb" if penb else "other"))
    )
    candidates = Client.objects.filter(email__iexact=mail.sender_email)
    client = candidates.first() if candidates.count() == 1 else None
    inquiry = Inquiry.objects.create(
        name=mail.sender_name or mail.sender_email,
        email=mail.sender_email,
        address="",
        service=service,
        description=f"{mail.subject}\n\n{mail.body}",
        source="E-mail",
        client=client,
    )
    for attachment in mail.attachments.all():
        InquiryAttachment.objects.create(
            inquiry=inquiry,
            name=attachment.name,
            file=attachment.file.name,
            sha256=attachment.sha256,
        )
    mail.inquiry = inquiry
    mail.save(update_fields=["inquiry"])
    event(user, "Vytvořena poptávka z e-mailu", inquiry=inquiry.pk, mail=mail.pk)
    return inquiry


def _sync_folder(folder, outgoing=False):
    """IMAP PEEK + readonly SELECT: never delete, move, or mark user mail read."""
    if not settings.CRM_IMAP_ENABLED:
        raise ValidationError(
            "Příjem pošty není připojený. Lze zatím vložit e-mail jako soubor .eml."
        )
    if (
        not settings.CRM_IMAP_PASSWORD
        or not settings.CRM_IMAP_HOST
        or not settings.CRM_IMAP_USER
    ):
        raise ValidationError("Chybí bezpečné nastavení přístupu IMAP.")
    imported = 0
    try:
        with imaplib.IMAP4_SSL(
            settings.CRM_IMAP_HOST,
            settings.CRM_IMAP_PORT,
            ssl_context=ssl.create_default_context(),
            timeout=20,
        ) as mailbox:
            mailbox.login(settings.CRM_IMAP_USER, settings.CRM_IMAP_PASSWORD)
            status, _ = mailbox.select(folder, readonly=True)
            if status != "OK":
                raise RuntimeError("Složka není dostupná.")
            _, validity = mailbox.response("UIDVALIDITY")
            validity_value = (validity[0] if validity and validity[0] else b"").decode(
                "ascii"
            )
            if not validity_value.isdigit():
                raise RuntimeError("Server neposkytl identitu složky.")
            key = hashlib.sha256(
                f"{settings.CRM_IMAP_HOST}:{settings.CRM_IMAP_USER}:{folder}:{validity_value}".encode()
            ).hexdigest()
            cursor, _ = MailboxCursor.objects.get_or_create(key=key)
            status, data = mailbox.uid("search", None, "ALL")
            if status != "OK":
                raise RuntimeError("Hledání zpráv selhalo.")
            all_uids = sorted(int(value) for value in (data[0] or b"").split())
            # First run starts with the newest fifty, later runs drain backlog oldest-first.
            candidates = [uid for uid in all_uids if uid > cursor.last_uid]
            candidates = candidates[-50:] if not cursor.last_uid else candidates[:50]
            for uid in candidates:
                status, size_data = mailbox.uid("fetch", str(uid), "(RFC822.SIZE)")
                encoded = b" ".join(
                    x if isinstance(x, bytes) else x[0] for x in size_data if x
                )
                match = re.search(rb"RFC822.SIZE (\d+)", encoded)
                if status != "OK" or not match:
                    raise RuntimeError("Nelze ověřit velikost zprávy.")
                if int(match.group(1)) > MAX_EMAIL_BYTES:
                    # Do not advance the cursor over an unprocessed message silently.
                    raise ValidationError(
                        "Schránka obsahuje zprávu nad 25 MB. Zpracujte ji ručně nebo zvolte zvláštní složku poptávek."
                    )
                status, items = mailbox.uid("fetch", str(uid), "(BODY.PEEK[])")
                raw = next((item[1] for item in items if isinstance(item, tuple)), None)
                if status != "OK" or raw is None:
                    raise RuntimeError("Načítání zprávy selhalo.")
                mail, created = import_email(raw, "IMAP: " + folder, outgoing=outgoing)
                if not outgoing and (
                    settings.CRM_IMAP_AUTO_CREATE
                    or (
                        settings.CRM_IMAP_AUTO_WEB
                        and mail.structured
                        and not mail.structured_error
                    )
                ):
                    try:
                        mail_to_inquiry(mail)
                    except ValidationError as error:
                        mail.structured_error = "; ".join(error.messages)[:300]
                        mail.save(update_fields=["structured_error"])
                imported += int(created)
                with transaction.atomic():
                    locked = MailboxCursor.objects.select_for_update().get(pk=cursor.pk)
                    locked.last_uid = max(locked.last_uid, uid)
                    locked.checked_at = timezone.now()
                    locked.save()
            MailboxSync.objects.create(imported=imported)
            return imported
    except ValidationError:
        MailboxSync.objects.create(
            imported=imported,
            error="Synchronizace zastavena; zkontrolujte velikost a podobu zpráv.",
        )
        raise
    except Exception as error:
        # Never store server responses; they can contain credentials.
        MailboxSync.objects.create(
            imported=imported,
            error="Příjem IMAP selhal. Zkontrolujte připojení, oprávnění a přihlašovací údaje.",
        )
        raise ValidationError(
            "Příjem pošty selhal. Zkontrolujte bezpečné nastavení IMAP a dostupnost serveru."
        ) from error


def sync_mailbox():
    imported = _sync_folder(settings.CRM_IMAP_FOLDER)
    if getattr(settings, "CRM_IMAP_SYNC_SENT", False):
        imported += _sync_folder(settings.CRM_IMAP_SENT_FOLDER, outgoing=True)
    MailboxSync.objects.create(imported=imported)
    return imported
