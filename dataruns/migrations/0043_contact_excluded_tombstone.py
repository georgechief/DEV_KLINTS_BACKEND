# Generated manually for Contact soft-tombstone (solid scoring universe).

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("dataruns", "0042_writeback_allowed_ci05"),
    ]

    operations = [
        migrations.AddField(
            model_name="contact",
            name="excluded",
            field=models.BooleanField(
                default=False,
                help_text="True when contact is outside the latest import pin (ghost).",
            ),
        ),
        migrations.AddField(
            model_name="contact",
            name="excluded_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name="contact",
            index=models.Index(
                fields=["company", "source", "excluded"],
                name="contacts_co_src_excl_idx",
            ),
        ),
    ]
