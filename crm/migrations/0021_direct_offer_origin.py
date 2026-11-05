from django.db import migrations


def identify(apps, schema_editor):
    apps.get_model("crm", "Inquiry").objects.filter(source="Přímá nabídka").update(
        origin="direct_offer"
    )


class Migration(migrations.Migration):
    dependencies = [("crm", "0020_inquiry_origin")]
    operations = [migrations.RunPython(identify, migrations.RunPython.noop)]
