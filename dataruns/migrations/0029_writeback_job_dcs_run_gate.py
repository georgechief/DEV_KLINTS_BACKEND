"""PRD-WB-04 — bind writeback jobs to DCS run + rollback timestamp."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dataruns", "0028_handoff_package"),
    ]

    operations = [
        migrations.AddField(
            model_name="writebackjob",
            name="dcs_data_run_id",
            field=models.IntegerField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="writebackjob",
            name="rolled_back_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name="writebackjob",
            index=models.Index(
                fields=["company", "check_id", "dcs_data_run_id", "mode", "-created_at"],
                name="wb_job_co_check_run_mode",
            ),
        ),
    ]
