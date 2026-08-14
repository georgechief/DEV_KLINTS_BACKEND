# Generated manually for PRD-AUDIT-01 governance audit log.

import django.db.models.deletion
from django.db import migrations, models


def clear_audit_logs(apps, schema_editor):
    AuditLog = apps.get_model("dataruns", "AuditLog")
    AuditLog.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("dataruns", "0007_checkmaster_is_optional"),
        ("tenants", "0006_connector_external_account_key"),
    ]

    operations = [
        migrations.RunPython(clear_audit_logs, migrations.RunPython.noop),
        migrations.AddField(
            model_name="auditlog",
            name="company",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="audit_logs",
                to="tenants.company",
            ),
        ),
        migrations.AddField(
            model_name="auditlog",
            name="actor_user_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="auditlog",
            name="entry_hash",
            field=models.CharField(default="0" * 64, max_length=64),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="auditlog",
            name="prev_hash",
            field=models.CharField(default="0" * 64, max_length=64),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="auditlog",
            name="summary",
            field=models.TextField(default=""),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="auditlog",
            name="tone",
            field=models.CharField(
                choices=[
                    ("info", "Info"),
                    ("risk", "Risk"),
                    ("loss", "Loss"),
                    ("revenue", "Revenue"),
                ],
                default="info",
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="auditlog",
            name="action",
            field=models.CharField(max_length=128),
        ),
        migrations.AlterField(
            model_name="auditlog",
            name="run",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="audit_logs",
                to="dataruns.run",
            ),
        ),
        migrations.AddIndex(
            model_name="auditlog",
            index=models.Index(
                fields=["company", "-created_at"],
                name="audit_logs_company_created_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="auditlog",
            constraint=models.UniqueConstraint(
                fields=("company", "entry_hash"),
                name="uniq_audit_logs_company_entry_hash",
            ),
        ),
        migrations.AlterField(
            model_name="auditlog",
            name="company",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="audit_logs",
                to="tenants.company",
            ),
        ),
    ]
