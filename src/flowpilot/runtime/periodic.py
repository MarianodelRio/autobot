"""Periodic work of the packs.

Each pack `Periodic` is a Procrastinate periodic task (`dispatch_periodic`, registered in
`flowpilot/jobs.py`). When it fires it *dispatches*: for each active tenant of the pack it
queues `run_periodic(tenant_id, name, scheduled_at)` on the `periodic` queue, with a
queueing lock per tenant and name, so two equal runs are never pending at once.
Procrastinate defers each scheduled instant only once.

`run_periodic` builds a context without contact, runs the handler without a transaction
and applies its actions in one. A run later than `max_delay_min` is dropped and logged.
"""

import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from django.conf import settings
from django.utils import timezone
from procrastinate.exceptions import AlreadyEnqueued

from core.actions import NotifyOwner, SendProactive
from core.pack import Pack, Periodic
from flowpilot.jobs import PERIODIC, RUN_PERIODIC, app
from flowpilot.ops.logging import bind, contextual
from flowpilot.ops.state import record
from flowpilot.runtime.context import (
    CalendarFactory,
    CalendarUnavailable,
    bound_calendar_id,
    build_context,
    google_calendar,
)
from flowpilot.runtime.models import Channel
from flowpilot.runtime.outbound import defer_sends
from flowpilot.runtime.process import apply_actions
from flowpilot.tenancy.registry import LoadedTenant, get_registry
from flowpilot.tenancy.tx import tenant_tx

log = logging.getLogger(__name__)


def active_tenants(pack: str) -> list[LoadedTenant]:
    """Tenants of `pack` with at least one eligible main or test periodic context."""
    return [t for t in get_registry().serving(pack) if channels_for(t)]


def channels_for(tenant: LoadedTenant) -> list[Channel]:
    if tenant.is_degraded or tenant.file.status == "offboarded":
        return []
    channels = [Channel.MAIN] if is_active(tenant) else []
    if tenant.pack is not None and tenant.pack.needs_calendar and settings.TEST_BOT_TOKEN:
        try:
            if bound_calendar_id(tenant, Channel.TEST) is not None:
                channels.append(Channel.TEST)
        except CalendarUnavailable:
            pass
    return channels


def is_active(tenant: LoadedTenant) -> bool:
    """`active`, not degraded, and with its main channel enabled. Onboarding and paused
    tenants get no periodic work on their main channel (an onboarding tenant must not
    send reminders to real customers), nor does one whose channel lacks secrets or ids:
    its notices would fail and their stable keys would be spent for good. The test
    calendar sweep runs on its own channel."""
    if tenant.file.status == "active" and not tenant.is_degraded and not tenant.main_enabled:
        log.warning("tenant %s gets no periodic work: its main channel is disabled", tenant.slug)
        return False
    return tenant.file.status == "active" and not tenant.is_degraded


def dispatch(pack: str, name: str, timestamp: int) -> int:
    """Queue one `run_periodic` per active tenant of `pack`; returns how many."""
    queued = 0
    for tenant in active_tenants(pack):
        try:
            app.configure_task(
                RUN_PERIODIC, queue=PERIODIC, queueing_lock=f"periodic:{tenant.id}:{name}"
            ).defer(tenant_id=str(tenant.id), name=name, scheduled_at=timestamp)
        except AlreadyEnqueued:
            log.warning(
                "periodic %s of tenant %s still pending: not queued again", name, tenant.slug
            )
            continue
        queued += 1
    return queued


@contextual
def run_periodic(
    tenant_id: UUID,
    name: str,
    scheduled_at: int,
    *,
    calendars: CalendarFactory = google_calendar,
) -> None:
    tenant = get_registry().by_id.get(tenant_id)
    periodic = _periodic(tenant.pack, name) if tenant is not None else None
    if tenant is None or periodic is None or not channels_for(tenant):
        log.info("periodic %s for tenant %s no longer applies: skipped", name, tenant_id)
        return
    due = datetime.fromtimestamp(scheduled_at, UTC)
    late = timezone.now() - due
    if late > timedelta(minutes=periodic.max_delay_min):
        log.warning(
            "periodic %s of tenant %s dropped: %d min late (max %d)",
            name,
            tenant.slug,
            late.total_seconds() // 60,
            periodic.max_delay_min,
        )
        return
    failures: list[Exception] = []
    for channel in channels_for(tenant):
        try:
            bind(tenant=tenant.slug, channel=str(channel))
            ctx = build_context(
                tenant, channel, contact=None, state={}, event_id=None, calendars=calendars
            )
            actions = periodic.handler(ctx)  # no transaction during Calendar calls
            if channel == Channel.TEST:
                actions = [
                    replace(a, idem_key=f"test:{a.idem_key}")
                    if isinstance(a, (SendProactive, NotifyOwner))
                    else a
                    for a in actions
                ]
            with tenant_tx(tenant.id):
                messages = apply_actions(
                    tenant, channel, actions, contact=None, event=None, now=timezone.now()
                )
                defer_sends(tenant.id, messages)
            record(tenant.id, channel, failed=False, sweep=name == "calendar_sweep")
        except Exception as exc:
            record(tenant.id, channel, failed=True)
            # A failed real calendar must not prevent a test-calendar sweep (or vice versa).
            log.warning("periodic %s of tenant %s failed on channel %s", name, tenant.slug, channel)
            failures.append(exc)
    if failures:
        raise failures[0]


def _periodic(pack: Pack | None, name: str) -> Periodic | None:
    if pack is None:
        return None
    return next((p for p in pack.periodic if p.name == name), None)
