from django.db import migrations, models

DEFAULT_CHECKS = ("CI-01", "CC-03", "WB-SHOP-01")


def seed_default_allowlist(apps, schema_editor):
    WritebackAllowedCheck = apps.get_model("dataruns", "WritebackAllowedCheck")
    for check_id in DEFAULT_CHECKS:
        WritebackAllowedCheck.objects.get_or_create(
            check_id=check_id,
            defaults={"enabled": True},
        )


def unseed_default_allowlist(apps, schema_editor):
    WritebackAllowedCheck = apps.get_model("dataruns", "WritebackAllowedCheck")
    WritebackAllowedCheck.objects.filter(check_id__in=DEFAULT_CHECKS).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("dataruns", "0024_alter_workflowbuildpackage_pilot"),
        ("tenants", "0008_company_writeback_sandbox_enabled"),
    ]

    operations = [
        migrations.CreateModel(
            name="WritebackAllowedCheck",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("check_id", models.CharField(max_length=16, unique=True)),
                ("enabled", models.BooleanField(default=True)),
                ("note", models.CharField(blank=True, default="", max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "writeback_allowed_checks",
                "ordering": ["check_id"],
            },
        ),
        migrations.RunPython(seed_default_allowlist, unseed_default_allowlist),
    ]
