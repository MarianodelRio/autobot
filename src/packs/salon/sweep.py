"""One Calendar read per sweep; the runtime persists/deduplicates the actions."""

from datetime import timedelta
from uuid import UUID

from core.actions import Action, ContactRef, SendProactive
from core.dates import format_date_es
from core.pack import PackContext
from packs.salon import booking
from packs.salon.messages import TEMPLATE_CONFIRMATION, TEMPLATE_REMINDER
from packs.salon.parser import parse_name, parse_phone, parse_status
from packs.salon.slots import classify


def run(ctx: PackContext) -> list[Action]:
    cfg, now = booking.configuration(ctx), ctx.clock.now()
    if not cfg.reminders_enabled and not cfg.manual_confirmations_enabled:
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
        owner = event.private.get("fp_contact")
        if owner:
            try:
                target = ContactRef(contact_id=UUID(owner))
            except ValueError:
                ctx.log.warning("Calendar event has an invalid contact reference")
                continue
        elif phone := parse_phone(event.description):
            target = ContactRef(phone=phone)
        else:
            continue
        # Google permits ids longer than the common callback limit. Never truncate an
        # identifier: that could point a confirmation/cancellation at another event.
        if len(f"reminder_confirm:{event.gcal_id}".encode()) > 64:
            ctx.log.warning("Calendar event id exceeds the callback limit; notice skipped")
            continue
        at = event.start.astimezone(ctx.tenant.timezone)
        params = [format_date_es(at.date()).capitalize(), at.strftime("%H:%M")]
        hours = (event.start - now).total_seconds() / 3600
        if (
            cfg.reminders_enabled
            and cfg.reminder_window_hours[0] <= hours <= cfg.reminder_window_hours[1]
        ):
            actions.append(
                SendProactive(
                    target,
                    TEMPLATE_REMINDER,
                    params,
                    [f"reminder_confirm:{event.gcal_id}", f"reminder_cancel:{event.gcal_id}"],
                    ctx.idem.stable(f"reminder:{event.gcal_id}:{event.start.isoformat()}"),
                )
            )
        if (
            kind == "manual"
            and cfg.manual_confirmations_enabled
            and event.created is not None
            and cfg.manual_confirmations_since is not None
            and event.created >= cfg.manual_confirmations_since
        ):
            actions.append(
                SendProactive(
                    target,
                    TEMPLATE_CONFIRMATION,
                    [parse_name(event.description) or "Cliente", *params],
                    [f"booking_cancel:{event.gcal_id}"],
                    ctx.idem.stable(f"confirm:{event.gcal_id}"),
                )
            )
            if parse_status(event.description) is None:
                booking.calendar(ctx).patch_description(event.gcal_id, {"Estado": "pendiente"})
    return actions
