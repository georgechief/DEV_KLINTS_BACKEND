from django.db import migrations

WB19_CHECKS = ("SP-03",)


def seed_wb19_allowlist(apps, schema_editor):
    WritebackAllowedCheck = apps.get_model("dataruns", "WritebackAllowedCheck")
    for check_id in WB19_CHECKS:
        row, created = WritebackAllowedCheck.objects.get_or_create(
            check_id=check_id,
            defaults={
                "enabled": True,
                "note": "PRD-WB-19 SP-03 detail schema normalise",
            },
        )
        if not created and not row.enabled:
            row.enabled = True
            if not (row.note or "").strip():
                row.note = "PRD-WB-19 SP-03 detail schema normalise"
            row.save(update_fields=["enabled", "note", "updated_at"])


def unseed_wb19_allowlist(apps, schema_editor):
    WritebackAllowedCheck = apps.get_model("dataruns", "WritebackAllowedCheck")
    WritebackAllowedCheck.objects.filter(check_id__in=WB19_CHECKS).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("dataruns", "0043_contact_excluded_tombstone"),
    ]

    operations = [
        migrations.RunPython(seed_wb19_allowlist, unseed_wb19_allowlist),
    ]
