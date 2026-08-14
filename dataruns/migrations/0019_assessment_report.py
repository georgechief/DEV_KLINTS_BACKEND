# Generated for PRD-RPT-01 assessment report payload storage.

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("dataruns", "0018_writeback_approval_token"),
        ("tenants", "0007_normalize_connector_types"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AssessmentReport",
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
                (
                    "variant",
                    models.CharField(
                        choices=[
                            ("PAID_FULL", "Paid full"),
                            ("FREE_DIAGNOSTIC", "Free diagnostic"),
                        ],
                        default="PAID_FULL",
                        max_length=32,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[("READY", "Ready"), ("FAILED", "Failed")],
                        default="READY",
                        max_length=32,
                    ),
                ),
                ("period_from", models.DateField(blank=True, null=True)),
                ("period_to", models.DateField(blank=True, null=True)),
                ("window_since", models.DateTimeField(blank=True, null=True)),
                ("window_until", models.DateTimeField(blank=True, null=True)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("payload_hash", models.CharField(max_length=64)),
                ("template_version", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "architecture_assessment",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="assessment_reports",
                        to="dataruns.architectureassessment",
                    ),
                ),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="assessment_reports",
                        to="tenants.company",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="assessment_reports_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "dcs_data_run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="assessment_reports",
                        to="dataruns.datarun",
                    ),
                ),
            ],
            options={
                "db_table": "assessment_reports",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(
                        fields=["company", "-created_at"],
                        name="assessment__company_8a1f2d_idx",
                    )
                ],
            },
        ),
    ]
