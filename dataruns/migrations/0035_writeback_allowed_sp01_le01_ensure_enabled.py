from django.db import migrations

WB08_CHECKS = ("SP-01", "LE-01")


def ensure_wb08_allowlist_enabled(apps, schema_editor):
    """Idempotent re-enable if 0034 already ran with get_or_create-only defaults."""
    WritebackAllowedCheck = apps.get_model("dataruns", "WritebackAllowedCheck")
    for check_id in WB08_CHECKS:
        row, _created = WritebackAllowedCheck.objects.get_or_create(
            check_id=check_id,
            defaults={"enabled": True, "note": "PRD-WB-08 catalogue wave 2"},
        )
        updates: list[str] = []
        if not row.enabled:
            row.enabled = True
            updates.append("enabled")
        if not (row.note or "").strip():
            row.note = "PRD-WB-08 catalogue wave 2"
            updates.append("note")
        if updates:
            updates.append("updated_at")
            row.save(update_fields=updates)


def noop_reverse(apps, schema_editor):
    # Keep rows; 0034 reverse deletes them if rolled back as a pair.
    return


class Migration(migrations.Migration):
    dependencies = [
        ("dataruns", "0034_writeback_allowed_sp01_le01"),
    ]

    operations = [
        migrations.RunPython(ensure_wb08_allowlist_enabled, noop_reverse),
    ]
