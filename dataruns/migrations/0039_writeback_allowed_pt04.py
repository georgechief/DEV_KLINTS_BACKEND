from django.db import migrations

WB11_CHECKS = ("PT-04",)


def seed_wb11_allowlist(apps, schema_editor):
    WritebackAllowedCheck = apps.get_model("dataruns", "WritebackAllowedCheck")
    for check_id in WB11_CHECKS:
        row, created = WritebackAllowedCheck.objects.get_or_create(
            check_id=check_id,
            defaults={
                "enabled": True,
                "note": "PRD-WB-11 PT-04 klints_net_ltv",
            },
        )
        if not created and not row.enabled:
            row.enabled = True
            if not (row.note or "").strip():
                row.note = "PRD-WB-11 PT-04 klints_net_ltv"
            row.save(update_fields=["enabled", "note", "updated_at"])


def unseed_wb11_allowlist(apps, schema_editor):
    WritebackAllowedCheck = apps.get_model("dataruns", "WritebackAllowedCheck")
    WritebackAllowedCheck.objects.filter(check_id__in=WB11_CHECKS).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("dataruns", "0038_writeback_allowed_le09"),
    ]

    operations = [
        migrations.RunPython(seed_wb11_allowlist, unseed_wb11_allowlist),
    ]
