from django.db import migrations

# SP-01 is not in MVP1 42 check masters and has no DCS executor.
# WB-08 ships LE-01 only; remove SP-01 from the execute allowlist.


def disable_sp01_allowlist(apps, schema_editor):
    WritebackAllowedCheck = apps.get_model("dataruns", "WritebackAllowedCheck")
    WritebackAllowedCheck.objects.filter(check_id="SP-01").delete()


def restore_sp01_allowlist(apps, schema_editor):
    WritebackAllowedCheck = apps.get_model("dataruns", "WritebackAllowedCheck")
    WritebackAllowedCheck.objects.get_or_create(
        check_id="SP-01",
        defaults={"enabled": True, "note": "PRD-WB-08 (reverted — not MVP1 42)"},
    )


class Migration(migrations.Migration):
    dependencies = [
        ("dataruns", "0035_writeback_allowed_sp01_le01_ensure_enabled"),
    ]

    operations = [
        migrations.RunPython(disable_sp01_allowlist, restore_sp01_allowlist),
    ]
