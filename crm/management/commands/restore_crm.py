import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Ověří a obnoví zálohu do nové složky. Nikdy nepřepisuje běžící databázi."

    def add_arguments(self, parser):
        parser.add_argument("archive")
        parser.add_argument("--destination", required=True)

    def handle(self, *args, **options):
        archive = Path(options["archive"])
        destination = Path(options["destination"]).resolve()
        if destination.exists():
            raise CommandError(
                "Cílová složka již existuje. Zvolte novou prázdnou cestu."
            )
        try:
            with zipfile.ZipFile(archive) as z:
                if sum(i.file_size for i in z.infolist()) > 2 * 1024**3:
                    raise CommandError(
                        "Záloha přesahuje limit 2 GB; použijte spravovanou obnovu."
                    )
                checksums = json.loads(z.read("checksums.json"))
                if "db.sqlite3" not in checksums:
                    raise CommandError("Chybí databáze.")
                verified = []
                for name, digest in checksums.items():
                    target = (destination / name).resolve()
                    if not target.is_relative_to(destination) or not (
                        name == "db.sqlite3" or name.startswith("media/")
                    ):
                        raise CommandError("Neplatná cesta v záloze.")
                    content = z.read(name)
                    if hashlib.sha256(content).hexdigest() != digest:
                        raise CommandError("Kontrolní součet zálohy nesouhlasí.")
                    verified.append((target, content))
                destination.mkdir(parents=True)
                for target, content in verified:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
            with sqlite3.connect(destination / "db.sqlite3") as db:
                if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise CommandError("Obnovená databáze je poškozená.")
        except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as e:
            raise CommandError("Neplatný formát zálohy.") from e
        self.stdout.write(
            self.style.SUCCESS(
                "Záloha ověřena a obnovena do nové složky. Před přepnutím aplikaci zastavte."
            )
        )
