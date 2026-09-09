# PRD-GAP-01 Slice A1 — OrchestrationTask model

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dataruns", "0031_handoffpackage_activation_meta"),
        ("tenants", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="OrchestrationTask",
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
                ("task_id", models.CharField(max_length=128)),
                ("task_type", models.CharField(max_length=32)),
                ("status", models.CharField(default="PENDING", max_length=32)),
                ("title", models.CharField(blank=True, default="", max_length=512)),
                ("check_id", models.CharField(blank=True, default="", max_length=16)),
                ("priority_class", models.CharField(blank=True, default="", max_length=8)),
                ("priority_inputs", models.JSONField(blank=True, default=dict)),
                ("priority_score", models.FloatField(default=0.0)),
                ("depends_on", models.JSONField(blank=True, default=list)),
                ("wave", models.PositiveSmallIntegerField(default=0)),
                ("capability_dependencies", models.JSONField(blank=True, default=list)),
                ("approval", models.JSONField(blank=True, default=dict)),
                ("idempotency_key", models.CharField(max_length=256)),
                ("provenance", models.JSONField(blank=True, default=dict)),
                ("source_refs", models.JSONField(blank=True, default=dict)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="orchestration_tasks",
                        to="tenants.company",
                    ),
                ),
            ],
            options={
                "db_table": "orchestration_tasks",
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.AddIndex(
            model_name="orchestrationtask",
            index=models.Index(
                fields=["company", "status", "-created_at"],
                name="orch_task_co_status_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="orchestrationtask",
            index=models.Index(
                fields=["company", "task_type", "-created_at"],
                name="orch_task_co_type_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="orchestrationtask",
            constraint=models.UniqueConstraint(
                fields=("company", "idempotency_key"),
                name="orch_task_co_idempotency_uniq",
            ),
        ),
    ]
