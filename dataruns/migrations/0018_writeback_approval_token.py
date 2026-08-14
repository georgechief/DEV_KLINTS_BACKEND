# Generated manually for BL-017 approval tokens.

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):
    dependencies = [
        ("dataruns", "0017_writeback_job"),
        ("tenants", "0007_normalize_connector_types"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WritebackApprovalToken",
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
                ("schema_version", models.CharField(default="1.0.0", max_length=16)),
                ("actor_id", models.CharField(max_length=64)),
                ("actor_role", models.CharField(max_length=32)),
                ("scope", models.JSONField(blank=True, default=list)),
                ("object_id", models.CharField(max_length=16)),
                ("object_version", models.CharField(max_length=32)),
                ("diff_hash", models.CharField(max_length=64)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PENDING", "Pending"),
                            ("APPROVED", "Approved"),
                            ("REJECTED", "Rejected"),
                            ("EXPIRED", "Expired"),
                            ("REVOKED", "Revoked"),
                        ],
                        default="PENDING",
                        max_length=16,
                    ),
                ),
                ("issued_at", models.DateTimeField(default=timezone.now)),
                ("expires_at", models.DateTimeField()),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("consumed_at", models.DateTimeField(blank=True, null=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "actor_user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="requested_writeback_approvals",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "approver_user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="approved_writeback_approvals",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="writeback_approval_tokens",
                        to="tenants.company",
                    ),
                ),
                (
                    "writeback_job",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="approval_tokens",
                        to="dataruns.writebackjob",
                    ),
                ),
            ],
            options={
                "db_table": "writeback_approval_tokens",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(
                        fields=["company", "status", "-created_at"],
                        name="writeback_a_company_0f0f0f_idx",
                    ),
                    models.Index(
                        fields=["diff_hash", "object_id"],
                        name="writeback_a_diff_ha_1a1a1a_idx",
                    ),
                ],
            },
        ),
    ]
