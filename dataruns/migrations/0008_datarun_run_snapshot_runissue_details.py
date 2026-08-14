# DataRun.run_snapshot + RunIssue.details for DCS fresh-score pipeline.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dataruns", "0007_checkmaster_is_optional"),
    ]

    operations = [
        migrations.AddField(
            model_name="datarun",
            name="run_snapshot",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Frozen scoring inputs for this DCS DataRun (PRD-DCS-03).",
            ),
        ),
        migrations.AddField(
            model_name="runissue",
            name="details",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Check evidence: matches, mismatches, reason_code, message.",
            ),
        ),
    ]
