from django.db import migrations


def add_default(apps, schema_editor):
    apps.get_model("crm", "WebsiteSource").objects.get_or_create(
        slug="enepru",
        defaults={
            "name": "Enepru.cz",
            "domain": "enepru.cz",
            "secret_env": "CRM_WEBHOOK_SECRET",
        },
    )


class Migration(migrations.Migration):
    dependencies = [("crm", "0013_websitesource")]
    operations = [migrations.RunPython(add_default, migrations.RunPython.noop)]
