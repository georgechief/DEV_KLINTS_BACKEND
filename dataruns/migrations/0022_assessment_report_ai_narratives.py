# Generated for PRD-AI-01 report_narrative storage (outside hashed payload).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dataruns", "0021_ai_call_nullable_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="assessmentreport",
            name="ai_narratives",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="AI report_narrative stored outside the hashed payload (PRD-AI-01).",
            ),
        ),
    ]
