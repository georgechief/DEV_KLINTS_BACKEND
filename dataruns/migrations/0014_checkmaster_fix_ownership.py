# Generated manually for CheckMaster Excel Fix Type / Fix Owner / Suggested Fix.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dataruns", "0013_audit_log_created_at_default"),
    ]

    operations = [
        migrations.AddField(
            model_name="checkmaster",
            name="suggested_fix",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Excel sheet 02 Suggested Fix (catalogue).",
            ),
        ),
        migrations.AddField(
            model_name="checkmaster",
            name="fix_type",
            field=models.CharField(
                blank=True,
                default="",
                help_text=(
                    "Excel sheet 02 Fix Type (e.g. Configuration, "
                    "Automated writeback)."
                ),
                max_length=128,
            ),
        ),
        migrations.AddField(
            model_name="checkmaster",
            name="fix_owner",
            field=models.CharField(
                blank=True,
                default="",
                help_text=(
                    "Excel sheet 02 Fix Owner: Klints (automated), Data lead, "
                    "External integrator, or CRM manager."
                ),
                max_length=64,
            ),
        ),
    ]
