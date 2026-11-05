"""Local metadata + Windows Credential Manager; never a plaintext password file."""

import json
import platform
import uuid
from pathlib import Path

SERVICE = "LahodnyCRM.Mail"
FILENAME = ".mail-settings.json"


def save_profile(
    base_dir,
    username,
    password,
    folder="INBOX",
    auto_create=False,
    sync_sent=False,
    sent_folder="Sent",
):
    import keyring

    if (
        platform.system() != "Windows"
        or not keyring.get_keyring().__class__.__module__.startswith(
            "keyring.backends.Windows"
        )
    ):
        raise RuntimeError(
            "Není dostupný Správce pověření Windows. Heslo nebylo uloženo do souboru."
        )
    if not username or "@" not in username or not password:
        raise ValueError("Doplňte e-mail a heslo aplikace.")
    base_dir = Path(base_dir)
    path = base_dir / FILENAME
    credential_id = uuid.uuid4().hex
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        credential_id = old.get("credential_id") or credential_id
    keyring.set_password(SERVICE, credential_id, password)
    profile = {
        "credential_id": credential_id,
        "username": username,
        "imap_host": "imap.seznam.cz",
        "imap_port": 993,
        "smtp_host": "smtp.seznam.cz",
        "smtp_port": 465,
        "smtp_ssl": True,
        "smtp_tls": False,
        "folder": folder,
        "auto_create": bool(auto_create),
        "sync_sent": bool(sync_sent),
        "sent_folder": sent_folder,
        "enabled": True,
    }
    temporary = base_dir / (FILENAME + ".tmp")
    temporary.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.chmod(0o600)
    temporary.replace(path)


def load_profile(base_dir):
    path = Path(base_dir) / FILENAME
    if not path.exists():
        return {}
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
        import keyring

        profile["password"] = (
            keyring.get_password(SERVICE, profile["credential_id"]) or ""
        )
        return profile
    except Exception:
        # Let CRM run; configuring the mailbox again restores the missing binding.
        return {"profile_error": True}
