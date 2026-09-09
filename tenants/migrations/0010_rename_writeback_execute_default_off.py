from django.db import migrations, models


def disable_writeback_execute_for_all_companies(apps, schema_editor):
    Company = apps.get_model("tenants", "Company")
    Company.objects.all().update(writeback_execute_enabled=False)


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0009_company_writeback_sandbox_default_true"),
    ]

    operations = [
        migrations.RenameField(
            model_name="company",
            old_name="writeback_sandbox_enabled",
            new_name="writeback_execute_enabled",
        ),
        migrations.RunPython(
            disable_writeback_execute_for_all_companies,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="company",
            name="writeback_execute_enabled",
            field=models.BooleanField(
                default=False,
                help_text="Allow writeback execute on Fix (preview → approve → Manago/Shopify). Default off (PRD-WB-03).",
            ),
        ),
    ]
