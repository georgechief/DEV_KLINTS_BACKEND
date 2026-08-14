# Generated manually — normalize connector type values.

from django.db import migrations, models


def normalize_connector_types(apps, schema_editor):
    Connector = apps.get_model("tenants", "Connector")
    Connector.objects.filter(name="manago_ai").update(type="cdp")
    Connector.objects.filter(name="shopify").update(type="ecommerce")


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0006_connector_external_account_key"),
    ]

    operations = [
        migrations.RunPython(normalize_connector_types, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="connector",
            name="type",
            field=models.CharField(
                choices=[("cdp", "CDP"), ("ecommerce", "Ecommerce")],
                max_length=64,
            ),
        ),
    ]
