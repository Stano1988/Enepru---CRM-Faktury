import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Vytvoří konzistentní SQLite zálohu a soubory s kontrolními součty. Výstup obsahuje soukromé údaje."

    def add_arguments(self, parser):
        parser.add_argument("--output", required=True)

    def handle(self, *args, **options):
        if settings.DATABASES["default"]["ENGINE"] != "django.db.backends.sqlite3":
            raise CommandError(
                "Pro PostgreSQL použijte pg_dump a samostatné zálohování úložiště."
            )
        path = Path(options["output"]).resolve()
        if path.exists():
            raise CommandError("Výstup již existuje; nebude přepsán.")
        media = Path(settings.MEDIA_ROOT).resolve()
        if path.is_relative_to(media):
            raise CommandError("Záloha nesmí být v úložišti podkladů.")
        # Stop writes while collecting media to make the full DB/file snapshot consistent.
        from django.db import connection, transaction

        with transaction.atomic():
            connection.ensure_connection()
            connection.cursor().execute("UPDATE crm_company SET id=id WHERE id=1")
            import tempfile

            with tempfile.TemporaryDirectory() as tmp:
                backup = Path(tmp) / "db.sqlite3"
                source = sqlite3.connect(str(settings.DATABASES["default"]["NAME"]))
                target = sqlite3.connect(str(backup))
                try:
                    source.backup(target)
                finally:
                    target.close()
                    source.close()
                manifest = {}
                with zipfile.ZipFile(path, "x", zipfile.ZIP_DEFLATED) as z:
                    entries = [("db.sqlite3", backup)]
                    if media.exists():
                        entries += [
                            ("media/" + str(f.relative_to(media)), f)
                            for f in media.rglob("*")
                            if f.is_file()
                        ]
                    for name, f in entries:
                        content = f.read_bytes()
                        z.writestr(name, content)
                        manifest[name] = hashlib.sha256(content).hexdigest()
                    z.writestr("checksums.json", json.dumps(manifest, indent=2))
        try:
            path.chmod(0o600)
        except OSError:
            pass
        self.stdout.write(
            self.style.SUCCESS(
                "Záloha vytvořena. Tajný klíč zálohujte odděleně bezpečným způsobem."
            )
        )
