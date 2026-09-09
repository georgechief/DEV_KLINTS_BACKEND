# Generated manually for PRD-QA-01 — align WorkflowQaResult.status choices

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dataruns", "0026_workflow_qa_result"),
    ]

    operations = [
        migrations.AlterField(
            model_name="workflowqaresult",
            name="status",
            field=models.CharField(
                choices=[("PASS", "PASS"), ("FAIL", "FAIL")],
                max_length=8,
            ),
        ),
    ]
