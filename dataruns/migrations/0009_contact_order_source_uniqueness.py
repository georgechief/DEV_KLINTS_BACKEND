# Platform-scoped uniqueness for contacts and orders (Shopify vs Manago).

from django.db import migrations, models


def backfill_unknown_source(apps, schema_editor):
    Contact = apps.get_model("dataruns", "Contact")
    Order = apps.get_model("dataruns", "Order")
    Contact.objects.filter(source="").update(source="unknown")
    Order.objects.filter(source="").update(source="unknown")


class Migration(migrations.Migration):

    dependencies = [
        ("dataruns", "0008_datarun_run_snapshot_runissue_details"),
    ]

    operations = [
        migrations.AddField(
            model_name="contact",
            name="source",
            field=models.TextField(
                choices=[
                    ("shopify", "Shopify"),
                    ("manago_ai", "Manago"),
                    ("unknown", "Unknown"),
                ],
                default="unknown",
                help_text="Origin platform; required for cross-platform uniqueness.",
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="source",
            field=models.TextField(
                choices=[
                    ("shopify", "Shopify"),
                    ("manago_ai", "Manago"),
                    ("unknown", "Unknown"),
                ],
                default="unknown",
                help_text="Origin platform; required for cross-platform uniqueness.",
            ),
        ),
        migrations.RunPython(backfill_unknown_source, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="contact",
            name="uniq_contacts_company_external_id",
        ),
        migrations.RemoveConstraint(
            model_name="order",
            name="uniq_orders_company_external_id",
        ),
        migrations.RemoveIndex(
            model_name="contact",
            name="contacts_company_external_idx",
        ),
        migrations.RemoveIndex(
            model_name="order",
            name="orders_company_external_idx",
        ),
        migrations.AddIndex(
            model_name="contact",
            index=models.Index(
                fields=["company", "source", "external_id"],
                name="contacts_co_src_ext_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="order",
            index=models.Index(
                fields=["company", "source", "external_id"],
                name="orders_co_src_ext_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="contact",
            constraint=models.UniqueConstraint(
                fields=("company", "source", "external_id"),
                name="uniq_contacts_company_source_external_id",
            ),
        ),
        migrations.AddConstraint(
            model_name="order",
            constraint=models.UniqueConstraint(
                fields=("company", "source", "external_id"),
                name="uniq_orders_company_source_external_id",
            ),
        ),
    ]
