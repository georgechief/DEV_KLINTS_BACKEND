from django.db import migrations

WB13_CHECKS = ("LE-05",)


def seed_wb13_allowlist(apps, schema_editor):
    WritebackAllowedCheck = apps.get_model("dataruns", "WritebackAllowedCheck")
    for check_id in WB13_CHECKS:
        row, created = WritebackAllowedCheck.objects.get_or_create(
            check_id=check_id,
            defaults={
                "enabled": True,
                "note": "PRD-WB-13 LE-05 purchase gap",
            },
        )
        if not created and not row.enabled:
            row.enabled = True
            if not (row.note or "").strip():
                row.note = "PRD-WB-13 LE-05 purchase gap"
            row.save(update_fields=["enabled", "note", "updated_at"])


def unseed_wb13_allowlist(apps, schema_editor):
    WritebackAllowedCheck = apps.get_model("dataruns", "WritebackAllowedCheck")
    WritebackAllowedCheck.objects.filter(check_id__in=WB13_CHECKS).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("dataruns", "0039_writeback_allowed_pt04"),
    ]

    operations = [
        migrations.RunPython(seed_wb13_allowlist, unseed_wb13_allowlist),
    ]
