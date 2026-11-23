"""One Calendar read per sweep; the runtime persists/deduplicates the actions."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from core.actions import Action, ContactRef, SendProactive
from core.dates import format_date_es
from core.errors import PermanentError, TransientError
from core.limits import MAX_ID_BYTES
from core.pack import PackContext
from packs.salon import booking
from packs.salon.messages import TEMPLATE_CONFIRMATION, TEMPLATE_REMINDER
from packs.salon.parser import parse_name, parse_phone, parse_status
from packs.salon.ports import CalEvent
from packs.salon.slots import classify


def run(ctx: PackContext) -> list[Action]:
    cfg, now = booking.configuration(ctx), ctx.clock.now()
    manual_enabled = cfg.manual_confirmations_enabled and ctx.can_contact_by_phone
    if cfg.manual_confirmations_enabled and not ctx.can_contact_by_phone:
        ctx.log.info("Manual confirmations skipped: phone recipients unavailable in this context")
    if not cfg.reminders_enabled and not manual_enabled:
        return []
    events = booking.calendar(ctx).list_events(
        now, now + timedelta(days=cfg.booking_window_days + 1)
    )
    actions: list[Action] = []
    for event in events:
        if event.all_day or event.status == "cancelled" or event.start <= now:
            continue
        kind = classify(event)
        if kind not in ("bot", "manual"):
            continue
        target = _target(ctx, event)
        if target is None:
            continue
        # Google permits ids longer than the common callback limit. Never truncate an
        # identifier: that could point a confirmation/cancellation at another event.
        if len(f"reminder_confirm:{event.gcal_id}".encode()) > MAX_ID_BYTES:
            ctx.log.warning("Calendar event id exceeds the callback limit; notice skipped")
            continue
        at = event.start.astimezone(ctx.tenant.timezone)
        params = [format_date_es(at.date()).capitalize(), at.strftime("%H:%M")]
        hours = (event.start - now).total_seconds() / 3600
        if (
            cfg.reminders_enabled
            and cfg.reminder_window_hours[0] <= hours <= cfg.reminder_window_hours[1]
        ):
            actions.append(_reminder(ctx, event, target, params))
        if (
            kind == "manual"
            and manual_enabled
            and event.created is not None
            and cfg.manual_confirmations_since is not None
            and event.created >= cfg.manual_confirmations_since
        ):
            confirmation = _confirmation(ctx, event, target, params, now)
            if confirmation is not None:
                actions.append(confirmation)
    return actions


def _target(ctx: PackContext, event: CalEvent) -> ContactRef | None:
    """Who to write to: the contact that owns the event, or the phone written in a manual
    one; None if the event has neither."""
    owner = event.private.get("fp_contact")
    if owner:
        try:
            return ContactRef(contact_id=UUID(owner))
        except ValueError:
            ctx.log.warning("Calendar event has an invalid contact reference")
            return None
    phone = parse_phone(event.description)
    return ContactRef(phone=phone) if phone else None


# A reminder or confirmation that arrives later than this before the appointment is useless.
NOTICE_LEAD = timedelta(minutes=30)


def _not_after(event: CalEvent) -> datetime:
    """Thirty minutes before the start, computed in UTC: subtracting from a datetime that
    carries a zone (not a fixed offset) is wall-clock arithmetic, which is wrong on the
    nights the clocks change."""
    return event.start.astimezone(UTC) - NOTICE_LEAD


def _reminder(
    ctx: PackContext, event: CalEvent, target: ContactRef, params: list[str]
) -> SendProactive:
    return SendProactive(
        target,
        TEMPLATE_REMINDER,
        params,
        [f"reminder_confirm:{event.gcal_id}", f"reminder_cancel:{event.gcal_id}"],
        ctx.idem.stable(f"reminder:{event.gcal_id}:{event.start.isoformat()}"),
        not_after=_not_after(event),
    )


def _confirmation(
    ctx: PackContext, event: CalEvent, target: ContactRef, params: list[str], now: datetime
) -> SendProactive | None:
    """Ask the client of a manual booking to confirm or cancel it, and mark it pending.
    None (and no marker) if the notice would be born expired: an appointment starting in
    less than `NOTICE_LEAD` must not be left "pendiente" with nobody told."""
    if _not_after(event) <= now:
        return None
    if parse_status(event.description) is None:
        try:
            booking.calendar(ctx).patch_description(event.gcal_id, {"Estado": "pendiente"})
        except (TransientError, PermanentError) as e:
            # A failed patch must not abort the rest of the sweep: the
            # confirmation notice is still sent (idempotent by idem_key), only
            # the "Estado" marker is retried on the next sweep.
            ctx.log.warning(
                "patch_description failed for a manual confirmation; continuing the sweep: %s",
                type(e).__name__,
            )
    return SendProactive(
        target,
        TEMPLATE_CONFIRMATION,
        [parse_name(event.description) or "Cliente", *params],
        [f"booking_cancel:{event.gcal_id}"],
        ctx.idem.stable(f"confirm:{event.gcal_id}"),
        not_after=_not_after(event),
    )
