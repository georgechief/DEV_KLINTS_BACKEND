# Generated manually for contacts / orders / contact_metrics + FK fixes.

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dataruns", "0003_dbml_schema_alignment"),
        ("tenants", "0003_alter_company_domain_alter_company_name_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="Contact",
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
                ("external_id", models.TextField()),
                ("email", models.TextField(blank=True, default="")),
                ("phone", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="contacts",
                        to="tenants.company",
                    ),
                ),
            ],
            options={
                "db_table": "contacts",
            },
        ),
        migrations.CreateModel(
            name="Order",
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
                ("external_id", models.TextField()),
                ("amount", models.DecimalField(decimal_places=6, max_digits=20)),
                ("currency", models.TextField()),
                (
                    "status",
                    models.TextField(
                        choices=[
                            ("paid", "Paid"),
                            ("refunded", "Refunded"),
                            ("failed", "Failed"),
                        ]
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="orders",
                        to="tenants.company",
                    ),
                ),
                (
                    "contact",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="orders",
                        to="dataruns.contact",
                    ),
                ),
            ],
            options={
                "db_table": "orders",
            },
        ),
        migrations.CreateModel(
            name="ContactMetric",
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
                ("total_orders", models.IntegerField(default=0)),
                (
                    "total_revenue",
                    models.DecimalField(decimal_places=6, default=0, max_digits=20),
                ),
                ("last_order_at", models.DateTimeField(blank=True, null=True)),
                (
                    "avg_order_value",
                    models.DecimalField(decimal_places=6, default=0, max_digits=20),
                ),
                (
                    "ltv",
                    models.DecimalField(decimal_places=6, default=0, max_digits=20),
                ),
                ("lifecycle_stage", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "contact",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="metrics",
                        to="dataruns.contact",
                    ),
                ),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="contact_metrics",
                        to="dataruns.run",
                    ),
                ),
            ],
            options={
                "db_table": "contact_metrics",
            },
        ),
        # Clear legacy text contact_id / entity_id rows before typed columns
        # (tables are empty or demo-only in current environments).
        migrations.RunSQL(
            sql="DELETE FROM lifecycle_profile_contacts;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql="DELETE FROM run_issue_impact;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql="DELETE FROM run_issues;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RemoveField(
            model_name="lifecycleprofilecontact",
            name="contact_id",
        ),
        migrations.AddField(
            model_name="lifecycleprofilecontact",
            name="contact",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="lifecycle_profile_contacts",
                to="dataruns.contact",
            ),
        ),
        migrations.AlterField(
            model_name="lifecycleprofilecontact",
            name="lifecycle_profile",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="profile_contacts",
                to="dataruns.lifecycleprofile",
            ),
        ),
        migrations.AlterField(
            model_name="runissue",
            name="entity_id",
            field=models.UUIDField(),
        ),
        migrations.AddIndex(
            model_name="contact",
            index=models.Index(
                fields=["company", "external_id"],
                name="contacts_company_external_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="contact",
            index=models.Index(fields=["email"], name="contacts_email_idx"),
        ),
        migrations.AddConstraint(
            model_name="contact",
            constraint=models.UniqueConstraint(
                fields=("company", "external_id"),
                name="uniq_contacts_company_external_id",
            ),
        ),
        migrations.AddIndex(
            model_name="order",
            index=models.Index(fields=["contact"], name="orders_contact_idx"),
        ),
        migrations.AddIndex(
            model_name="order",
            index=models.Index(
                fields=["company", "external_id"],
                name="orders_company_external_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="order",
            constraint=models.UniqueConstraint(
                fields=("company", "external_id"),
                name="uniq_orders_company_external_id",
            ),
        ),
        migrations.AddIndex(
            model_name="contactmetric",
            index=models.Index(fields=["run"], name="contact_metrics_run_idx"),
        ),
        migrations.AddIndex(
            model_name="contactmetric",
            index=models.Index(fields=["contact"], name="contact_metrics_contact_idx"),
        ),
        migrations.AddConstraint(
            model_name="contactmetric",
            constraint=models.UniqueConstraint(
                fields=("run", "contact"),
                name="uniq_contact_metrics_run_contact",
            ),
        ),
        migrations.AddIndex(
            model_name="lifecycleprofilecontact",
            index=models.Index(
                fields=["run", "contact"],
                name="lpc_run_contact_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="runissue",
            index=models.Index(fields=["run"], name="run_issues_run_idx"),
        ),
        migrations.AddIndex(
            model_name="runissue",
            index=models.Index(fields=["entity_id"], name="run_issues_entity_id_idx"),
        ),
    ]
