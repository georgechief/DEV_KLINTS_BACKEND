# PRD-QA-01 / BL-018 — WorkflowQaResult model

import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dataruns", "0025_writeback_allowed_check"),
        ("tenants", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkflowQaResult",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("use_case_id", models.CharField(db_index=True, max_length=16)),
                ("score", models.FloatField()),
                ("status", models.CharField(max_length=8)),
                ("payload", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="workflow_qa_results",
                        to="tenants.company",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="workflow_qa_results",
                        to="tenants.user",
                    ),
                ),
                (
                    "package",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="qa_results",
                        to="dataruns.workflowbuildpackage",
                    ),
                ),
            ],
            options={
                "db_table": "workflow_qa_results",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(
                        fields=["company", "package", "-created_at"],
                        name="wf_qa_co_pkg_created_idx",
                    )
                ],
            },
        ),
    ]
