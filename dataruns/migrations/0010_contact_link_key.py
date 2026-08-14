# Generated manually for CI-05 person.external_key (Manago externalId).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dataruns", "0009_contact_order_source_uniqueness"),
    ]

    operations = [
        migrations.AddField(
            model_name="contact",
            name="link_key",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Cross-system link key (Manago externalId / Shopify customer id).",
            ),
        ),
        migrations.AddIndex(
            model_name="contact",
            index=models.Index(
                fields=["company", "link_key"],
                name="contacts_co_link_key_idx",
            ),
        ),
    ]
