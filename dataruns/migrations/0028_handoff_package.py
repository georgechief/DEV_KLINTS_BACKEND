# PRD-HO-01 Step 2 — HandoffPackage model

import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dataruns", "0027_alter_workflowqaresult_status"),
        ("tenants", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="HandoffPackage",
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
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("STAGED", "STAGED"),
                            ("APPROVED_FOR_ACTIVATION", "APPROVED_FOR_ACTIVATION"),
                            ("REJECTED", "REJECTED"),
                            ("ACTIVATED", "ACTIVATED"),
                        ],
                        default="STAGED",
                        max_length=32,
                    ),
                ),
                ("payload", models.JSONField(default=dict)),
                ("manifest_hash", models.CharField(db_index=True, max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="handoff_packages",
                        to="tenants.company",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="handoff_packages",
                        to="tenants.user",
                    ),
                ),
                (
                    "package",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="handoffs",
                        to="dataruns.workflowbuildpackage",
                    ),
                ),
                (
                    "qa_result",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="handoffs",
                        to="dataruns.workflowqaresult",
                    ),
                ),
            ],
            options={
                "db_table": "handoff_packages",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(
                        fields=["company", "package", "-created_at"],
                        name="handoff_co_pkg_created_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("company", "package", "qa_result"),
                        name="handoff_pkg_co_pkg_qa_uniq",
                    ),
                ],
            },
        ),
    ]
