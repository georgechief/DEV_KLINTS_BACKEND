from django.db import migrations, models


def enable_sandbox_for_existing_companies(apps, schema_editor):
    Company = apps.get_model("tenants", "Company")
    Company.objects.filter(writeback_sandbox_enabled=False).update(
        writeback_sandbox_enabled=True,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0008_company_writeback_sandbox_enabled"),
    ]

    operations = [
        migrations.AlterField(
            model_name="company",
            name="writeback_sandbox_enabled",
            field=models.BooleanField(
                default=True,
                help_text="Allow sandbox writeback execute (preview → approve → Manago/Shopify).",
            ),
        ),
        migrations.RunPython(
            enable_sandbox_for_existing_companies,
            migrations.RunPython.noop,
        ),
    ]
