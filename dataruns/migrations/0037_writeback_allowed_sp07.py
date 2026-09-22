from django.db import migrations

WB09_CHECKS = ("SP-07",)


def seed_wb09_allowlist(apps, schema_editor):
    WritebackAllowedCheck = apps.get_model("dataruns", "WritebackAllowedCheck")
    for check_id in WB09_CHECKS:
        row, created = WritebackAllowedCheck.objects.get_or_create(
            check_id=check_id,
            defaults={"enabled": True, "note": "PRD-WB-09 SP-07 namespace clean"},
        )
        if not created and not row.enabled:
            row.enabled = True
            if not (row.note or "").strip():
                row.note = "PRD-WB-09 SP-07 namespace clean"
            row.save(update_fields=["enabled", "note", "updated_at"])


def unseed_wb09_allowlist(apps, schema_editor):
    WritebackAllowedCheck = apps.get_model("dataruns", "WritebackAllowedCheck")
    WritebackAllowedCheck.objects.filter(check_id__in=WB09_CHECKS).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("dataruns", "0036_writeback_disallow_sp01_not_in_mvp1_42"),
    ]

    operations = [
        migrations.RunPython(seed_wb09_allowlist, unseed_wb09_allowlist),
    ]
