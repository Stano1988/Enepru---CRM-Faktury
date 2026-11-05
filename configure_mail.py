"""Interactive Windows setup; no command-line password and no outbound messages."""

import getpass
from pathlib import Path

from crm.mail_profile import save_profile


def main():
    print("Připojení pošty Seznam k CRM. Heslo se při psaní nezobrazuje.")
    print(
        "Použijte heslo aplikace pro IMAP/SMTP vytvořené u poskytovatele, pokud jej účet vyžaduje."
    )
    print(
        "Nastavení nesmaže, nepřesune ani neoznačí zprávy v původní schránce jako přečtené."
    )
    username = (
        input("E-mail [penb.lahodny@seznam.cz]: ").strip() or "penb.lahodny@seznam.cz"
    )
    folder = input("Složka pro příjem pošty [INBOX]: ").strip() or "INBOX"
    auto = (
        input(
            "Vytvářet poptávky také ze všech běžných e-mailů? Webové formuláře se převádějí automaticky. [a/N]: "
        )
        .strip()
        .lower()
        == "a"
    )
    if auto and folder.upper() == "INBOX":
        if (
            input(
                "Pozor: každá načtená zpráva INBOX vytvoří poptávku. Opravdu? [a/N]: "
            )
            .strip()
            .lower()
            != "a"
        ):
            auto = False
    sync_sent = (
        input("Načítat i zprávy odeslané přímo ze Seznamu? [A/n]: ").strip().lower()
        != "n"
    )
    sent_folder = (
        (input("Název odeslané složky [Sent]: ").strip() or "Sent")
        if sync_sent
        else "Sent"
    )
    password = getpass.getpass("Heslo aplikace pro poštu: ")
    if password != getpass.getpass("Zopakujte heslo: "):
        raise ValueError("Hesla se neshodují.")
    save_profile(
        Path(__file__).resolve().parent,
        username,
        password,
        folder,
        auto,
        sync_sent,
        sent_folder,
    )
    print("Nastavení uloženo; heslo je pouze ve Správci pověření Windows.")
    print(
        "Připojení nebylo tímto ověřeno. Restartujte CRM a použijte Přijatá pošta → Načíst poštu."
    )
    print("Odesílání můžete poté ověřit ručně připravenou zprávou v CRM.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as error:
        print(str(error))
        raise SystemExit(1)
    except Exception:
        print(
            "Bezpečné uložení se nezdařilo. Žádný textový soubor s heslem nebyl vytvořen."
        )
        raise SystemExit(1)
