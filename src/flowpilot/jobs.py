"""Procrastinate app and job registry (design.md §4.4, §7.5).

`procrastinate.contrib.django` builds the app on the `default` alias (fp_app) and imports
this module (PROCRASTINATE_AUTODISCOVER_MODULE_NAME = "jobs"), so every job is declared
here: `process_event`, `send_message`, `run_periodic`… arrive with T-3.x.

Rules for every job (CLAUDE.md): arguments, locks and logs carry only ids, never phone
numbers, user ids or personal data; every job is idempotent.
"""

from procrastinate.contrib.django import app

# One worker serves the three queues (§7.5); separate queues show what gets stuck.
INBOUND = "inbound"  # process_event, apply_status, route_test_update
OUTBOUND = "outbound"  # send_message, send_notification
PERIODIC = "periodic"  # run_periodic, ops_check, retention_cleanup
QUEUES = (INBOUND, OUTBOUND, PERIODIC)

# Job names, so they can be deferred before their task is declared here (T-3.5).
PROCESS_EVENT = "process_event"  # (tenant_id, event_id), lock conv:<h>
APPLY_STATUS = "apply_status"  # (tenant_id, event_id), no lock

__all__ = ["APPLY_STATUS", "INBOUND", "OUTBOUND", "PERIODIC", "PROCESS_EVENT", "QUEUES", "app"]
