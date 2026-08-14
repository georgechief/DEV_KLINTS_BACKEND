# Generated manually for CheckMaster.is_optional (FE-03 / FD-03 optional ERP).

from django.db import migrations, models


def set_fd03_optional(apps, schema_editor):
    CheckMaster = apps.get_model("dataruns", "CheckMaster")
    CheckMaster.objects.filter(check_id="FD-03").update(is_optional=True)
    CheckMaster.objects.exclude(check_id="FD-03").update(is_optional=False)


class Migration(migrations.Migration):

    dependencies = [
        ("dataruns", "0006_dcs_master_review_updates"),
    ]

    operations = [
        migrations.AddField(
            model_name="checkmaster",
            name="is_optional",
            field=models.BooleanField(
                default=False,
                help_text="Optional gate/check: FAIL must not block app shell (FE-03).",
            ),
        ),
        migrations.RunPython(set_fd03_optional, migrations.RunPython.noop),
    ]
