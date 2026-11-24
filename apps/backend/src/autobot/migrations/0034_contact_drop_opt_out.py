"""Nothing sets `Contact.opt_out` since the BAJA command was retired (ADR-028): a person
who wants no more messages asks the business and is forgotten from the panel."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("autobot", "0033_outbound_not_after"),
    ]

    operations = [
        migrations.RemoveField(model_name="contact", name="opt_out"),
        migrations.RemoveField(model_name="contact", name="opt_out_at"),
    ]
