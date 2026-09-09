# Generated manually for PRD-WF-01 Phase 1

import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dataruns", "0022_assessment_report_ai_narratives"),
        ("tenants", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkflowBuildPackage",
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
                ("payload", models.JSONField(default=dict)),
                ("provisional_supplemental", models.BooleanField(default=False)),
                ("blueprint_content_hash", models.CharField(max_length=64)),
                ("package_content_hash", models.CharField(db_index=True, max_length=64)),
                ("dcs_data_run_id", models.IntegerField(blank=True, null=True)),
                ("af_assessment_id", models.UUIDField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="workflow_build_packages",
                        to="tenants.company",
                    ),
                ),
                (
                    "generated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="workflow_build_packages",
                        to="tenants.user",
                    ),
                ),
                (
                    "pilot",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="build_packages",
                        to="dataruns.usecasepilot",
                        to_field="use_case_id",
                    ),
                ),
            ],
            options={
                "db_table": "workflow_build_packages",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(
                        fields=["company", "pilot_id", "-created_at"],
                        name="wf_bpkg_co_uc_created_idx",
                    )
                ],
            },
        ),
    ]
