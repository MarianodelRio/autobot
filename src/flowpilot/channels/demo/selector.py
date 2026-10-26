"""The demo bot's business selector.

Two doors of the platform (Telegram, WhatsApp — the latter completed in a later step)
let a closed list of people try any demo tenant (`tenants/demo-*/`), with its real pack
logic. Picking a business is per door and person: the same person on Telegram and on
WhatsApp are two independent sessions.

1. `store_event` (webhook or `telegram_poll`) saves the item in `demo_event`, which has
   no RLS (the tenant is not known yet), and queues `route_demo_event` with the
   person's `demo_user_lock(channel, external_id)`.
2. `route_demo_event` decides: no access → a refusal (Telegram) or silence (WhatsApp,
   Meta bills every message); `/start`, `/negocio` or no business picked → the list of
   demo businesses; `fp_select:<slug>` → picks it and sends a synthetic `menu` to that
   tenant; anything else → forwarded to the picked tenant, as an inbound_event of the
   door's channel, processed by `process_event` as any other.

The selector's own messages (list, refusal, "Demo · …") belong to no tenant, so they
are sent here directly, once the event is marked done: at most once.
"""

import dataclasses
import json
import logging
import uuid
from typing import Any
from uuid import UUID

from django.core.cache import cache
from django.db import connections, transaction
from django.utils import timezone

from core.limits import MAX_ID_BYTES, plan_sends
from core.replies import Reply, Text
from core.ui import list_msg, paginate, row, section
from flowpilot.channels.base import InboundItem, Rejected, Sent
from flowpilot.channels.demo.doors import Door, allowed, door
from flowpilot.channels.ratelimit import WindowLimiter
from flowpilot.jobs import INBOUND, ROUTE_DEMO_EVENT, app
from flowpilot.ops.logging import bind, contextual
from flowpilot.runtime.inbound import store
from flowpilot.runtime.locks import demo_user_lock
from flowpilot.runtime.models import Channel, DemoEvent, DemoSession
from flowpilot.tenancy.registry import LoadedTenant, get_registry

log = logging.getLogger(__name__)

SELECT = "fp_select:"
PAGE = "fp_page:"
SELECTOR_COMMANDS = frozenset({"/start", "/negocio", "negocio"})

NO_ACCESS_TEXT = "No tienes acceso a esta demo."
PICK_TEXT = "👋 Demo de FlowPilot. Elige el negocio que quieres probar:"
PICKED_TEXT = "Demo · {name}. Escribe /negocio para cambiar."
NOT_AVAILABLE_TEXT = "Ese negocio no está disponible ahora mismo."
NONE_AVAILABLE_TEXT = "No hay ninguna demo disponible ahora mismo."

# A user without access on the Telegram door gets the refusal at most 3 times an hour
# (worker memory). WhatsApp never answers one: Meta bills every message.
refusals = WindowLimiter(limit=3, window_s=3600)

INSERT_EVENT = """
    INSERT INTO demo_event (id, channel, provider_event_id, payload, status, received_at)
    VALUES (%s, %s, %s, %s::jsonb, 'pending', %s)
    ON CONFLICT (channel, provider_event_id) DO NOTHING
    RETURNING id
"""


def store_event(door: Door, item: InboundItem) -> bool:
    """Save a demo door item and queue its routing; False if already received (the
    provider retried). Writes no table with RLS."""
    event_id = uuid.uuid7()
    bind(channel=str(door.channel), event_id=str(event_id))
    with transaction.atomic(using="default"), connections["default"].cursor() as cursor:
        cursor.execute(
            INSERT_EVENT,
            [
                event_id,
                door.channel,
                item.provider_event_id,
                json.dumps(item.payload),
                timezone.now(),
            ],
        )
        row_ = cursor.fetchone()
        if row_ is None:
            return False
        app.configure_task(
            ROUTE_DEMO_EVENT,
            queue=INBOUND,
            lock=demo_user_lock(door.channel, item.external_id),
        ).defer(event_id=str(row_[0]))
    return True


@contextual
def route_demo_event(event_id: UUID) -> None:
    event = DemoEvent.objects.filter(id=event_id).first()
    if event is None or event.status != DemoEvent.Status.PENDING:
        return
    bind(channel=event.channel, event_id=str(event_id))
    door_ = door(Channel(event.channel))
    if door_ is None:  # the door was switched off after the event was saved
        _finish(event)
        return
    items = door_.adapter.parse(event.payload, door_.description)
    item = items[0] if items else None
    if not isinstance(item, InboundItem):
        _finish(event)
        return
    message = item.message
    payload = message.payload or ""
    if payload.startswith((SELECT, PAGE)):
        door_.adapter.acknowledge(event.payload, door_.description, door_.secrets)

    if not allowed(door_, item):
        log.info("demo message from a user without access")
        if door_.channel == Channel.DEMO_TG:
            if refusals.hit(item.external_id):
                _finish(event)  # someone insisting: the bot must not answer without limit
            else:
                _finish_and_reply(event, door_, item.external_id, [Text(NO_ACCESS_TEXT)])
        else:
            _finish(event)  # WhatsApp: never answer (Meta bills every message)
        return

    available = _available()

    if payload.startswith(PAGE):
        page = business_list(available, _page(payload))
        _finish_and_reply(event, door_, item.external_id, [page])
    elif payload.startswith(SELECT):
        slug = payload.removeprefix(SELECT)
        tenant = next((t for t in available if t.slug == slug), None)
        if tenant is None:
            _finish_and_reply(
                event,
                door_,
                item.external_id,
                [Text(NOT_AVAILABLE_TEXT), business_list(available, 0)],
            )
        else:
            _pick(event, door_, item, tenant)
    elif _is_selector_command(message.text):
        _finish_and_reply(event, door_, item.external_id, [business_list(available, 0)])
    else:
        session = DemoSession.objects.filter(
            channel=door_.channel, external_id=item.external_id
        ).first()
        tenant = None
        if session is not None:
            tenant = next((t for t in available if t.id == session.tenant_id), None)
        if session is None:
            _finish_and_reply(event, door_, item.external_id, [business_list(available, 0)])
        elif tenant is None:
            session.delete()  # no longer available (paused, degraded, ambiguous)
            _finish_and_reply(
                event,
                door_,
                item.external_id,
                [Text(NOT_AVAILABLE_TEXT), business_list(available, 0)],
            )
        else:
            DemoSession.objects.filter(channel=door_.channel, external_id=item.external_id).update(
                selected_at=timezone.now()
            )
            store(tenant, [item], door_.channel)
            _finish(event)


def _available() -> list[LoadedTenant]:
    """Demo tenants a person may pick: active, not degraded nor ambiguous."""
    return [
        t for t in get_registry().demo_tenants() if t.file.status == "active" and not t.is_degraded
    ]


def business_list(tenants: list[LoadedTenant], page: int) -> Reply:
    """The demo businesses a person may pick, 8 per page, by name and description."""
    if not tenants:
        return Text(NONE_AVAILABLE_TEXT)
    rows = []
    for t in sorted(tenants, key=lambda t: t.file.name.lower()):
        option = f"{SELECT}{t.slug}"
        if len(option.encode()) > MAX_ID_BYTES:  # a slug longer than 54 characters
            log.warning("demo tenant %s cannot be listed: its slug is too long", t.slug)
            continue
        description = t.file.demo.description if t.file.demo is not None else ""
        rows.append(row(option, t.file.name, description))
    pages = max(1, -(-len(rows) // 8))
    page = page if 0 <= page < pages else 0
    shown = paginate(rows, page, more_id=f"{PAGE}{page + 1}", back_id=f"{PAGE}0")
    return list_msg(PICK_TEXT, "Ver negocios", [section(None, shown)])


def _pick(event: DemoEvent, door_: Door, item: InboundItem, tenant: LoadedTenant) -> None:
    """Save the choice, say which business it is and send it a synthetic `menu`, so its
    pack answers with its menu. The notice goes first, so it arrives before the menu; if
    the job is cut before the end, a retry may repeat it, never the menu."""
    _reply(door_, item.external_id, [Text(PICKED_TEXT.format(name=tenant.file.name))])
    DemoSession.objects.update_or_create(
        channel=door_.channel,
        external_id=item.external_id,
        defaults={"tenant_id": tenant.id, "selected_at": timezone.now()},
    )
    menu = _synthetic_menu(door_, item)
    store(tenant, [menu], door_.channel)
    _finish(event)


def _synthetic_menu(door_: Door, item: InboundItem) -> InboundItem:
    """A `menu` item from the same person, the way `process_event` reads it back."""
    if door_.channel == Channel.DEMO_TG:
        update: dict[str, Any] = item.payload
        callback = update.get("callback_query") or {}
        sender: dict[str, Any] = callback.get("from") or update["message"]["from"]
        body = {
            "update_id": update["update_id"],
            "message": {
                "message_id": 0,
                "from": sender,
                "chat": {"id": sender["id"], "type": "private"},
                "date": int(timezone.now().timestamp()),
                "text": "menu",
            },
        }
    else:
        raise NotImplementedError("WhatsApp demo door: completed in a later step")
    (parsed,) = door_.adapter.parse(body, door_.description)
    assert isinstance(parsed, InboundItem)
    return dataclasses.replace(parsed, provider_event_id=f"select:{item.provider_event_id}")


def _is_selector_command(text: str | None) -> bool:
    words = (text or "").split()
    return bool(words) and words[0].split("@")[0].lower() in SELECTOR_COMMANDS


def _page(payload: str) -> int:
    try:
        return int(payload.removeprefix(PAGE))
    except ValueError:
        return 0


def _finish(event: DemoEvent) -> None:
    DemoEvent.objects.filter(id=event.id, status=DemoEvent.Status.PENDING).update(
        status=DemoEvent.Status.DONE
    )


def _finish_and_reply(
    event: DemoEvent, door_: Door, external_id: str, replies: list[Reply]
) -> None:
    """Mark the event done, then answer: a retry never repeats the answer."""
    _finish(event)
    _reply(door_, external_id, replies)


def _reply(door_: Door, external_id: str, replies: list[Reply]) -> None:
    for reply in plan_sends(replies):
        outcome = door_.adapter.send(
            door_.adapter.render(reply, door_.description),
            external_id,
            door_.description,
            door_.secrets,
            uuid.uuid7(),
        )
        if isinstance(outcome, Rejected) and outcome.kind == "auth":
            cache.set(f"bot:{door_.channel}:auth", True, timeout=None)
        elif isinstance(outcome, Sent):
            cache.delete(f"bot:{door_.channel}:auth")
        if not isinstance(outcome, Sent):
            log.warning("demo selector message not sent: %s", type(outcome).__name__)
