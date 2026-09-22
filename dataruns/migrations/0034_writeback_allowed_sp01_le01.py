from django.db import migrations

WB08_CHECKS = ("SP-01", "LE-01")


def seed_wb08_allowlist(apps, schema_editor):
    WritebackAllowedCheck = apps.get_model("dataruns", "WritebackAllowedCheck")
    for check_id in WB08_CHECKS:
        row, created = WritebackAllowedCheck.objects.get_or_create(
            check_id=check_id,
            defaults={"enabled": True, "note": "PRD-WB-08 catalogue wave 2"},
        )
        if not created and not row.enabled:
            row.enabled = True
            if not (row.note or "").strip():
                row.note = "PRD-WB-08 catalogue wave 2"
            row.save(update_fields=["enabled", "note", "updated_at"])


def unseed_wb08_allowlist(apps, schema_editor):
    WritebackAllowedCheck = apps.get_model("dataruns", "WritebackAllowedCheck")
    WritebackAllowedCheck.objects.filter(check_id__in=WB08_CHECKS).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("dataruns", "0033_aisuggestion_content_hash"),
    ]

    operations = [
        migrations.RunPython(seed_wb08_allowlist, unseed_wb08_allowlist),
    ]
