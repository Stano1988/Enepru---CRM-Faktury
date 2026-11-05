"""Daily local recovery snapshot; external copies are configured separately."""

import io
import os
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.utils import timezone


def daily_backup():
    directory = Path(
        os.environ.get("CRM_BACKUP_DIR", str(settings.BASE_DIR / "backups"))
    ).resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    today = timezone.localdate()
    target = directory / f"CRM-auto-{today.isoformat()}.zip"
    if target.exists():
        return target
    temporary = directory / f".CRM-auto-{today.isoformat()}.partial"
    # A leftover interrupted write is never considered a valid backup.
    temporary.unlink(missing_ok=True)
    try:
        call_command("backup_crm", output=str(temporary), stdout=io.StringIO())
        temporary.replace(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    # Keep 30 daily snapshots. Only our own exact dated files may be rotated.
    from datetime import date

    for path in directory.glob("CRM-auto-????-??-??.zip"):
        try:
            day = date.fromisoformat(path.name[9:-4])
        except ValueError:
            continue
        if day < today - timedelta(days=30):
            path.unlink()
    return target
