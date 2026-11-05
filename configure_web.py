"""Store the server-side website HMAC key in Windows Credential Manager."""

import getpass
import json
import platform
import re
import uuid
from pathlib import Path


def main():
    import keyring

    if (
        platform.system() != "Windows"
        or not keyring.get_keyring().__class__.__module__.startswith(
            "keyring.backends.Windows"
        )
    ):
        raise SystemExit(
            "Vyžaduje Správce pověření Windows. Klíč nebyl uložen do souboru."
        )
    print(
        "Připojení existujícího webu. Stejný tajný klíč musí být v bezpečném nastavení hostingu webu jako CRM_SHARED_SECRET. Nikdy nepatří do JavaScriptu."
    )
    name = (
        input("Název proměnné zdroje [CRM_WEBHOOK_SECRET]: ").strip()
        or "CRM_WEBHOOK_SECRET"
    )
    if not re.fullmatch(r"CRM_WEBHOOK_[A-Z0-9_]+", name):
        raise SystemExit("Neplatný název proměnné.")
    secret = getpass.getpass(
        "Vložte sdílený klíč z bezpečného nastavení webu (nezobrazuje se): "
    )
    if len(secret) < 32:
        raise SystemExit("Použijte náhodný klíč nejméně 32 znaků.")
    path = Path(__file__).resolve().parent / ".web-settings.json"
    metadata = json.loads(path.read_text()) if path.exists() else {}
    credential = metadata.get(name) or uuid.uuid4().hex
    keyring.set_password("LahodnyCRM.Web", credential, secret)
    metadata[name] = credential
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(metadata, indent=2))
    temporary.replace(path)
    print(
        "Klíč uložen ve Windows. Restartujte CRM. Pro příjem přes e-mail připojte schránku; přímé API navíc vyžaduje veřejné CRM s HTTPS."
    )


if __name__ == "__main__":
    main()
