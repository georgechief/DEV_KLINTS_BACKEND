"""PRD-HO-02 Phase 1 — activation metadata on HandoffPackage."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("dataruns", "0030_audit_logs_immutability_triggers"),
    ]

    operations = [
        migrations.AddField(
            model_name="handoffpackage",
            name="activation_meta",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
