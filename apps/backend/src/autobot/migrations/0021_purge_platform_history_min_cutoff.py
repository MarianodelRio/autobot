"""`purge_platform_history(cutoff)` (0015) took any `cutoff`, including `'infinity'`:
`fp_app` has `EXECUTE` on it (autobot/db/grants.py) and no other guard, so a call with
`'infinity'` erases all of `ops_alert` and `audit_event`. Clamp the cutoff inside the
function itself to at most a year ago, regardless of what the caller passes.
"""

from django.db import migrations

PURGE_FUNCTION = """
CREATE OR REPLACE FUNCTION purge_platform_history(cutoff timestamptz) RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
    DELETE FROM ops_alert WHERE resolved_at < least(cutoff, now() - interval '1 year');
    DELETE FROM audit_event WHERE at < least(cutoff, now() - interval '1 year');
$$
"""

PREVIOUS_PURGE_FUNCTION = """
CREATE OR REPLACE FUNCTION purge_platform_history(cutoff timestamptz) RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
    DELETE FROM ops_alert WHERE resolved_at < cutoff;
    DELETE FROM audit_event WHERE at < cutoff;
$$
"""


class Migration(migrations.Migration):
    dependencies = [
        ("autobot", "0020_delete_savedquery"),
    ]

    operations = [
        migrations.RunSQL(sql=PURGE_FUNCTION, reverse_sql=PREVIOUS_PURGE_FUNCTION),
    ]
