"""Retention with bounded, tenant-scoped transactions."""

import calendar
from datetime import datetime, timedelta
from typing import Any

from asgiref.sync import async_to_sync
from django.conf import settings
from django.db import connection
from django.db.models import Q, QuerySet
from django.utils import timezone

from autobot.runtime.models import (
    Contact,
    Conversation,
    DemoAccessGrant,
    DemoEvent,
    DemoInvite,
    DemoSession,
    InboundEvent,
    MetricEvent,
    Notification,
    OutboundMessage,
    OwnerEvent,
)
from autobot.tenancy.registry import get_registry
from autobot.tenancy.tx import tenant_tx

BATCH_SIZE = 1000
PROCRASTINATE_RETENTION_DAYS = 30
# A demo tenant's contacts, conversations and owner notices outlive the selector's
# own demo_event/demo_session (7/30 days) by this much, never a year like a real
# client's (D4): someone who tried the demo for an afternoon should not stay on file
# as long as an actual customer. Not active yet (RETENTION_CLEANUP_ENABLED=false).
DEMO_RETENTION_DAYS = 30
# How long a revoked or expired invite stays visible in the panel before it is
# purged, so a recent "código revocado"/"caducado" is still explainable there.
INVITE_RETENTION_DAYS = 30


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
    demo_cutoff = now - timedelta(days=DEMO_RETENTION_DAYS)
    for tenant in get_registry().tenants:
        # A demo tenant's own cutoff is much shorter than a real client's annual one
        # (D4): nobody who only tried the demo should stay on file for a year.
        cutoff = demo_cutoff if tenant.is_demo else annual
        expired = Q(last_activity_at__lte=cutoff) | Q(
            last_activity_at__isnull=True, created_at__lte=cutoff
        )
        operations: list[tuple[QuerySet[Any], dict[str, Any] | None]] = [
            (InboundEvent.objects.filter(received_at__lte=now - timedelta(days=90)), None),
            (
                InboundEvent.objects.filter(received_at__lte=now - timedelta(days=30)).filter(
                    Q(payload__isnull=False) | ~Q(effect_state={})
                ),
                {"payload": None, "effect_state": {}},
            ),
            (OutboundMessage.objects.filter(created_at__lte=cutoff), None),
            (
                OutboundMessage.objects.filter(
                    created_at__lte=now - timedelta(days=30), payload__isnull=False
                ),
                {"payload": None},
            ),
            (Notification.objects.filter(created_at__lte=cutoff), None),
            (MetricEvent.objects.filter(created_at__lte=cutoff), None),
            # A contact that opted out is NOT purged: the opt-out is the suppression
            # that stops later reminders (a manual appointment for the same phone would
            # create a fresh contact and message it). Only its name is cleared; the
            # identifier stays as the minimal suppression record (see
            # docs/procedimientos/retencion-rgpd.md). `contact_forget` still erases it.
            (Contact.objects.filter(expired, opt_out=False), None),
            (
                Contact.objects.filter(expired, opt_out=True).exclude(display_name=""),
                {"display_name": ""},
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
        DemoEvent.objects.filter(received_at__lte=now - timedelta(days=7)),
        DemoSession.objects.filter(selected_at__lte=now - timedelta(days=30)),
        OwnerEvent.objects.filter(received_at__lte=now - timedelta(days=7)),
        # A grant with a set expiry (copied from its invite) outlives it by nothing;
        # a grant from a never-expiring invite stays, like a closed-list entry.
        DemoAccessGrant.objects.filter(expires_at__lte=now),
        # Revoked or expired invites: kept a while so the panel can still explain a
        # recent "código revocado"/"caducado". An invite that only ran out of uses
        # (max_uses reached) is harmless and stays, same as a spent closed-list entry.
        DemoInvite.objects.filter(
            Q(revoked_at__lte=now - timedelta(days=INVITE_RETENTION_DAYS))
            | Q(
                expires_at__lte=now - timedelta(days=INVITE_RETENTION_DAYS),
                revoked_at__isnull=True,
            )
        ),
    ):
        while apply_batches(query):
            pass
    # SECURITY DEFINER (autobot/db/grants.py): fp_app has no DELETE on ops_alert or audit_event.
    with connection.cursor() as cursor:
        cursor.execute("SELECT purge_platform_history(%s)", [annual])


def cleanup_jobs() -> None:
    """Delete finished Procrastinate jobs (and their events, by cascade) older than 30
    days: the tables grow without bound otherwise (X15). Not conditioned by
    `RETENTION_CLEANUP_ENABLED`: they hold only ids (never personal data), so there is
    nothing to approve. Procrastinate has no sync variant of this manager method."""
    from autobot.runtime.jobs import app

    async_to_sync(app.job_manager.delete_old_jobs)(
        nb_hours=PROCRASTINATE_RETENTION_DAYS * 24,
        include_failed=True,
        include_cancelled=True,
        include_aborted=True,
    )
