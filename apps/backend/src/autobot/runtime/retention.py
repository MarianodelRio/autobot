"""Retention with bounded, tenant-scoped transactions."""

import calendar
import logging
from datetime import datetime, timedelta
from typing import Any

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
from autobot.tenancy.registry import LoadedTenant, get_registry
from autobot.tenancy.tx import tenant_tx

log = logging.getLogger(__name__)

BATCH_SIZE = 1000
JOBS_BATCH_SIZE = 2000
# Bound of one `cleanup_jobs` run (batches of JOBS_BATCH_SIZE): it always ends; the rest
# is left for the next night.
JOBS_MAX_BATCHES = 500
PROCRASTINATE_RETENTION_DAYS = 30
# A demo tenant's contacts, conversations and owner notices outlive the selector's
# own demo_event/demo_session (7/30 days) by this much, never a year like a real
# client's: someone who tried the demo for an afternoon should not stay on file
# as long as an actual customer. Applies whenever RETENTION_CLEANUP_ENABLED is on (the
# production default, compose.prod.yaml; off by default in local).
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


def _cleanup_tenant(tenant: LoadedTenant, now: datetime, cutoff: datetime) -> None:
    """`cutoff` is the tenant's own: a demo tenant's is much shorter than a real client's
    annual one (nobody who only tried the demo should stay on file for a year)."""
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


class RetentionError(Exception):
    """The nightly purge failed for some tenants (the others were purged)."""


def cleanup(*, now: datetime | None = None) -> None:
    """Purge every tenant, each one isolated from the others: a failure in one is logged
    (ids only) and the rest are still purged, then the platform-wide tables. At the end a
    `RetentionError` fails the job, so it is visible (job `failed`, ops_check) and tonight's
    leftovers are retried tomorrow."""
    # Check on execution too: an already queued job must remain inert before approval.
    if not settings.RETENTION_CLEANUP_ENABLED:
        return
    now = now or timezone.now()
    annual = year_before(now)
    demo_cutoff = now - timedelta(days=DEMO_RETENTION_DAYS)
    failed: list[str] = []
    for tenant in get_registry().tenants:
        try:
            _cleanup_tenant(tenant, now, demo_cutoff if tenant.is_demo else annual)
        except Exception:
            log.exception("retention failed for tenant %s: the others go on", tenant.id)
            failed.append(str(tenant.id))
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
    if failed:
        raise RetentionError(f"retention failed for {len(failed)} tenant(s): {', '.join(failed)}")


def cleanup_jobs() -> None:
    """Delete finished Procrastinate jobs (and their events, by cascade) older than 30
    days: the tables grow without bound otherwise. Not conditioned by
    `RETENTION_CLEANUP_ENABLED`: they hold only ids (never personal data), so there is
    nothing to approve. In batches (each its own short statement, under fp_app's
    statement_timeout), so a big backlog always progresses; at most `JOBS_MAX_BATCHES`
    per run."""
    for _ in range(JOBS_MAX_BATCHES):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM procrastinate_jobs WHERE id IN (
                    SELECT job.id FROM procrastinate_jobs job
                    WHERE job.status IN ('succeeded', 'failed', 'cancelled', 'aborted')
                      AND (SELECT max(event.at) FROM procrastinate_events event
                           WHERE event.job_id = job.id)
                          < now() - make_interval(hours => %s)
                    LIMIT %s
                )
                """,
                [PROCRASTINATE_RETENTION_DAYS * 24, JOBS_BATCH_SIZE],
            )
            deleted = cursor.rowcount
        if deleted < JOBS_BATCH_SIZE:
            return
    log.warning("jobs cleanup stopped after %s batches: the rest goes tomorrow", JOBS_MAX_BATCHES)
