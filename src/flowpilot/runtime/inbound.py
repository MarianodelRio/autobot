"""Save what a channel received and queue its processing (design.md §7.1).

Shared by the webhooks and, later, by `telegram_poll` and the test bot's selector, so
every entry takes the same path. No external calls: only the database.
"""

import json
import uuid

from django.db import connections
from django.utils import timezone

from flowpilot.channels.base import InboundItem, ParsedItem
from flowpilot.jobs import APPLY_STATUS, INBOUND, PROCESS_EVENT, app
from flowpilot.runtime.locks import conversation_lock
from flowpilot.runtime.models import Channel, InboundEvent
from flowpilot.tenancy.registry import LoadedTenant
from flowpilot.tenancy.tx import tenant_tx

Status = InboundEvent.Status

INSERT_EVENT = """
    INSERT INTO inbound_event
        (id, tenant_id, channel, kind, provider_event_id, payload, status, received_at)
    VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)
    ON CONFLICT (tenant_id, channel, provider_event_id) DO NOTHING
    RETURNING id
"""


def initial_status(tenant: LoadedTenant, item: ParsedItem) -> InboundEvent.Status:
    """`ignored` (saved, never processed) when the main channel must not answer: the
    tenant is paused or degraded, or in onboarding and the sender is not in
    testers.main (matched by its id or, in WhatsApp, its phone: since BSUIDs the id is
    not the phone). Delivery statuses of our own messages are not subject to testers."""
    if tenant.is_degraded or tenant.file.status == "paused":
        return Status.IGNORED
    if tenant.file.status == "onboarding" and isinstance(item, InboundItem):
        testers = tenant.file.testers.main
        phone = item.phone.removeprefix("+") if item.phone else None
        if item.external_id not in testers and phone not in testers:
            return Status.IGNORED
    return Status.PENDING


def store(tenant: LoadedTenant, items: list[ParsedItem]) -> int:
    """Save each item of the main channel as an inbound_event (a duplicate is skipped)
    and queue its job in the same transaction, so the job exists only if the event was
    committed. Returns how many events were new."""
    created = 0
    for item in items:
        status = initial_status(tenant, item)
        kind = (
            InboundEvent.Kind.MESSAGE if isinstance(item, InboundItem) else InboundEvent.Kind.STATUS
        )
        with tenant_tx(tenant.id), connections["default"].cursor() as cursor:
            cursor.execute(
                INSERT_EVENT,
                [
                    uuid.uuid7(),
                    tenant.id,
                    Channel.MAIN,
                    kind,
                    item.provider_event_id,
                    json.dumps(item.payload),
                    status,
                    timezone.now(),
                ],
            )
            row = cursor.fetchone()
            if row is None:
                continue  # already received: the provider retried
            created += 1
            if status != Status.PENDING:
                continue
            ids = {"tenant_id": str(tenant.id), "event_id": str(row[0])}
            if isinstance(item, InboundItem):
                lock = conversation_lock(tenant.id, Channel.MAIN, item.external_id)
                app.configure_task(PROCESS_EVENT, queue=INBOUND, lock=lock).defer(**ids)
            else:
                app.configure_task(APPLY_STATUS, queue=INBOUND).defer(**ids)
    return created
