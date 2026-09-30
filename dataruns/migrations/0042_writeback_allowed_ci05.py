from django.db import migrations

WB15_CHECKS = ("CI-05",)


def seed_wb15_allowlist(apps, schema_editor):
    WritebackAllowedCheck = apps.get_model("dataruns", "WritebackAllowedCheck")
    for check_id in WB15_CHECKS:
        row, created = WritebackAllowedCheck.objects.get_or_create(
            check_id=check_id,
            defaults={
                "enabled": True,
                "note": "PRD-WB-15 CI-05 identity key repair",
            },
        )
        if not created and not row.enabled:
            row.enabled = True
            if not (row.note or "").strip():
                row.note = "PRD-WB-15 CI-05 identity key repair"
            row.save(update_fields=["enabled", "note", "updated_at"])


def unseed_wb15_allowlist(apps, schema_editor):
    WritebackAllowedCheck = apps.get_model("dataruns", "WritebackAllowedCheck")
    WritebackAllowedCheck.objects.filter(check_id__in=WB15_CHECKS).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("dataruns", "0041_writeback_allowed_le02"),
    ]

    operations = [
        migrations.RunPython(seed_wb15_allowlist, unseed_wb15_allowlist),
    ]
