from django.core.management.base import BaseCommand

from crm.services import run_daily


class Command(BaseCommand):
    help = (
        "Připraví upomínky; odešle je pouze při výslovně povolené automatizaci a SMTP."
    )

    def handle(self, *args, **options):
        count = run_daily()
        self.stdout.write(self.style.SUCCESS(f"Připraveno upomínek: {count}"))
