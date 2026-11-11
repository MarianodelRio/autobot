"""Composite tenant FK for `notification.contact_id` (0022), matching the
`outbound_message_contact_fk` pattern from 0002_tenant_isolation: a notification can
only point to a contact of its own tenant, enforced at the database, not just in code.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("autobot", "0022_notification_contact"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                "ALTER TABLE notification ADD CONSTRAINT notification_contact_fk"
                " FOREIGN KEY (tenant_id, contact_id) REFERENCES contact (tenant_id, id)"
                " ON DELETE CASCADE"
            ),
            reverse_sql="ALTER TABLE notification DROP CONSTRAINT notification_contact_fk",
        ),
    ]
