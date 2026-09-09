from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0007_normalize_connector_types"),
    ]

    operations = [
        migrations.AddField(
            model_name="company",
            name="writeback_sandbox_enabled",
            field=models.BooleanField(
                default=False,
                help_text="Allow sandbox writeback execute (preview → approve → Manago/Shopify).",
            ),
        ),
    ]
