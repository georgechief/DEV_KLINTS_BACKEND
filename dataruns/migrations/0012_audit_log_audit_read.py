from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dataruns", "0011_merge_0008_audit_log_governance_0010_contact_link_key"),
    ]

    operations = [
        migrations.AddField(
            model_name="auditlog",
            name="audit_read",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddIndex(
            model_name="auditlog",
            index=models.Index(
                fields=["company", "audit_read", "-created_at"],
                name="audit_logs_co_read_created_idx",
            ),
        ),
    ]
