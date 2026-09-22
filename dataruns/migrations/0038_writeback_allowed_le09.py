from django.db import migrations

WB10_CHECKS = ("LE-09",)


def seed_wb10_allowlist(apps, schema_editor):
    WritebackAllowedCheck = apps.get_model("dataruns", "WritebackAllowedCheck")
    for check_id in WB10_CHECKS:
        row, created = WritebackAllowedCheck.objects.get_or_create(
            check_id=check_id,
            defaults={
                "enabled": True,
                "note": "PRD-WB-10 LE-09 return event backfill",
            },
        )
        if not created and not row.enabled:
            row.enabled = True
            if not (row.note or "").strip():
                row.note = "PRD-WB-10 LE-09 return event backfill"
            row.save(update_fields=["enabled", "note", "updated_at"])


def unseed_wb10_allowlist(apps, schema_editor):
    WritebackAllowedCheck = apps.get_model("dataruns", "WritebackAllowedCheck")
    WritebackAllowedCheck.objects.filter(check_id__in=WB10_CHECKS).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("dataruns", "0037_writeback_allowed_sp07"),
    ]

    operations = [
        migrations.RunPython(seed_wb10_allowlist, unseed_wb10_allowlist),
    ]
