"""Local Windows/Linux launcher. No debug server and no embedded credentials."""

import argparse
import ipaddress
import os
import threading
import time
import webbrowser


def main():
    parser = argparse.ArgumentParser(description="Lahodný CRM — lokální spuštění")
    parser.add_argument("--lan", help="Soukromá IPv4 adresa PC pro domácí Wi-Fi")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    local_ip = "127.0.0.1"
    host = "127.0.0.1"
    if args.lan:
        address = ipaddress.IPv4Address(args.lan)
        if (
            not address.is_private
            or address.is_unspecified
            or address.is_multicast
            or address.is_loopback
        ):
            parser.error("Zadejte skutečnou soukromou IPv4 adresu domácí sítě.")
        local_ip = str(address)
        host = "0.0.0.0"
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    os.environ["CRM_DEBUG"] = "0"
    os.environ["CRM_ALLOWED_HOSTS"] = "localhost,127.0.0.1" + (
        "," + local_ip if args.lan else ""
    )
    import django

    django.setup()
    from django.core.management import call_command
    from django.core.wsgi import get_wsgi_application

    call_command("migrate", interactive=False, verbosity=0)
    call_command("collectstatic", interactive=False, verbosity=0)
    from django.contrib.auth import get_user_model

    if not get_user_model().objects.filter(is_superuser=True).exists():
        print("Nejprve vytvořte vlastní účet správce. Heslo se při psaní nezobrazuje.")
        call_command("createsuperuser", interactive=True)

    def automation_loop():
        from django.db import close_old_connections

        from crm.services import run_daily

        while True:
            try:
                close_old_connections()
                run_daily()
                from crm.auto_backup import daily_backup

                daily_backup()
            except Exception:
                print("Automatizace nedokončena; zkontrolujte správu CRM.")
            finally:
                close_old_connections()
            time.sleep(300)

    threading.Thread(target=automation_loop, daemon=True).start()
    from waitress import serve

    url = f"http://{local_ip}:{args.port}"
    print(f"CRM: {url}\nUkončení: Ctrl+C. Počítač musí zůstat zapnutý.")
    if args.lan:
        print(
            "Pouze důvěryhodná domácí síť a testovací data. Pro vzdálený přístup je nutné HTTPS nasazení."
        )
    if not args.no_browser:
        threading.Timer(2, lambda: webbrowser.open(url)).start()
    serve(
        get_wsgi_application(),
        host=host,
        port=args.port,
        threads=4,
        max_request_body_size=30 * 1024 * 1024,
    )


if __name__ == "__main__":
    main()
