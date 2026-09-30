from django.db import migrations

WB14_CHECKS = ("LE-02",)


def seed_wb14_allowlist(apps, schema_editor):
    WritebackAllowedCheck = apps.get_model("dataruns", "WritebackAllowedCheck")
    for check_id in WB14_CHECKS:
        row, created = WritebackAllowedCheck.objects.get_or_create(
            check_id=check_id,
            defaults={
                "enabled": True,
                "note": "PRD-WB-14 LE-02 purchase value correct",
            },
        )
        if not created and not row.enabled:
            row.enabled = True
            if not (row.note or "").strip():
                row.note = "PRD-WB-14 LE-02 purchase value correct"
            row.save(update_fields=["enabled", "note", "updated_at"])


def unseed_wb14_allowlist(apps, schema_editor):
    WritebackAllowedCheck = apps.get_model("dataruns", "WritebackAllowedCheck")
    WritebackAllowedCheck.objects.filter(check_id__in=WB14_CHECKS).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("dataruns", "0040_writeback_allowed_le05"),
    ]

    operations = [
        migrations.RunPython(seed_wb14_allowlist, unseed_wb14_allowlist),
    ]
