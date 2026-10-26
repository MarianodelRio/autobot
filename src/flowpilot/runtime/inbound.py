"""Save what a channel received and queue its processing.

Shared by the webhooks and the test bot's selector (and, through it, `telegram_poll`), so
every entry takes the same path. No external calls: only the database.
"""

import json
import uuid

from django.db import connections
from django.utils import timezone

from flowpilot.channels.base import InboundItem, ParsedItem
from flowpilot.jobs import APPLY_STATUS, INBOUND, PROCESS_EVENT, app
from flowpilot.ops.logging import bind
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
    tenant is paused, or in onboarding and the sender is not in testers.main (matched by
    its id or, in WhatsApp, its phone: since BSUIDs the id is not the phone). Delivery
    statuses of our own messages are not subject to testers. A degraded tenant's events
    stay pending: process_event answers them with the generic text."""
    if tenant.file.status == "paused":
        return Status.IGNORED
    if tenant.file.status == "onboarding" and isinstance(item, InboundItem):
        testers = tenant.file.testers.main
        phone = item.phone.removeprefix("+") if item.phone else None
        if item.external_id not in testers and phone not in testers:
            return Status.IGNORED
    return Status.PENDING


def store(tenant: LoadedTenant, items: list[ParsedItem], channel: Channel = Channel.MAIN) -> int:
    """Save each item as an inbound_event of `channel` (a duplicate is skipped) and queue
    its job in the same transaction, so the job exists only if the event was committed.
    Returns how many events were new. On the `test` channel the selector already checked
    who may talk to the tenant, so its events are always pending."""
    created = 0
    for item in items:
        status = initial_status(tenant, item) if channel == Channel.MAIN else Status.PENDING
        kind = (
            InboundEvent.Kind.MESSAGE if isinstance(item, InboundItem) else InboundEvent.Kind.STATUS
        )
        event_id = uuid.uuid7()
        bind(tenant=tenant.slug, channel=str(channel), event_id=str(event_id))
        with tenant_tx(tenant.id), connections["default"].cursor() as cursor:
            cursor.execute(
                INSERT_EVENT,
                [
                    event_id,
                    tenant.id,
                    channel,
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
                lock = conversation_lock(tenant.id, channel, item.external_id)
                app.configure_task(PROCESS_EVENT, queue=INBOUND, lock=lock).defer(**ids)
            else:
                app.configure_task(APPLY_STATUS, queue=INBOUND).defer(**ids)
    return created
