"""Retention with bounded, tenant-scoped transactions."""

import calendar
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.db.models import Q, QuerySet
from django.utils import timezone

from flowpilot.runtime.models import (
    Contact,
    Conversation,
    InboundEvent,
    Notification,
    OutboundMessage,
    TestBotEvent,
    TestSession,
)
from flowpilot.tenancy.registry import get_registry
from flowpilot.tenancy.tx import tenant_tx

BATCH_SIZE = 1000


def year_before(now: datetime) -> datetime:
    year = now.year - 1
    return now.replace(year=year, day=min(now.day, calendar.monthrange(year, now.month)[1]))


def apply_batches(query: QuerySet[Any], values: dict[str, Any] | None = None) -> int:
    """Caller owns the short transaction; process at most one batch."""
    ids = list(query.order_by("pk").values_list("pk", flat=True)[:BATCH_SIZE])
    if not ids:
        return 0
    selected = query.filter(pk__in=ids)
    if values is None:
        selected.delete()
    else:
        selected.update(**values)
    return len(ids)


def cleanup(*, now: datetime | None = None) -> None:
    # Check on execution too: an already queued job must remain inert before approval.
    if not settings.RETENTION_CLEANUP_ENABLED:
        return
    now = now or timezone.now()
    annual = year_before(now)
    for tenant in get_registry().tenants:
        operations: list[tuple[QuerySet[Any], dict[str, Any] | None]] = [
            (InboundEvent.objects.filter(received_at__lte=now - timedelta(days=90)), None),
            (
                InboundEvent.objects.filter(received_at__lte=now - timedelta(days=30)).filter(
                    Q(payload__isnull=False) | ~Q(effect_state={})
                ),
                {"payload": None, "effect_state": {}},
            ),
            (OutboundMessage.objects.filter(created_at__lte=annual), None),
            (
                OutboundMessage.objects.filter(
                    created_at__lte=now - timedelta(days=30), payload__isnull=False
                ),
                {"payload": None},
            ),
            (Notification.objects.filter(created_at__lte=annual), None),
            (
                Contact.objects.filter(
                    Q(last_activity_at__lte=annual)
                    | Q(last_activity_at__isnull=True, created_at__lte=annual)
                ),
                None,
            ),
        ]
        if tenant.pack is not None:
            operations.append(
                (
                    Conversation.objects.exclude(state={}).filter(
                        Q(last_inbound_at__isnull=True)
                        | Q(
                            last_inbound_at__lt=now
                            - timedelta(minutes=tenant.pack.conversation_timeout_min)
                        )
                    ),
                    {"state": {}, "state_version": None},
                )
            )
        for query, values in operations:
            while True:
                with tenant_tx(tenant.id):
                    count = apply_batches(query, values)
                if not count:
                    break
    for query in (
        TestBotEvent.objects.filter(received_at__lte=now - timedelta(days=7)),
        TestSession.objects.filter(selected_at__lte=now - timedelta(days=30)),
    ):
        while apply_batches(query):
            pass
