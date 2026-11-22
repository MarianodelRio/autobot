"""The demo bot's business selector.

Two doors of the platform (Telegram, WhatsApp — the latter completed in a later step)
let a closed list of people try any demo tenant (initialized from a pack template),
with its real pack logic. Picking a business is per door and person: Telegram and
WhatsApp are two independent sessions for the same person.

1. `store_event` (webhook or `telegram_poll`) saves the item in `demo_event`, which has
   no RLS (the tenant is not known yet), and queues `route_demo_event` with the
   person's `demo_user_lock(channel, external_id)`.
2. `route_demo_event` decides: no access and no valid invite code to redeem
   (`channels/demo/invites.py`) → a refusal (Telegram) or silence (WhatsApp, Meta
   bills every message); `/start`, `/negocio` or no business picked → the list of
   demo businesses; `fp_select:<slug>` → picks it and sends a synthetic `menu` to that
   tenant; anything else → forwarded to the picked tenant, as an inbound_event of the
   door's channel, processed by `process_event` as any other.

The selector's own messages (list, refusal, "Demo · …") belong to no tenant, so they
are sent here directly, once the event is marked done: at most once. The one exception
is a message that certainly was not sent (the provider asked to wait, or there was no
connection) while nothing else had been sent for that event: the event is reopened and
the job retried (`TransientError`), so the answer is not lost in silence.

Nothing is kept of a person without access longer than needed: on WhatsApp their events
are not even saved, and on Telegram the saved update is emptied once the refusal is out.
Every person is also limited in how many events per minute are accepted.
"""

import dataclasses
import json
import logging
import uuid
from typing import Literal
from uuid import UUID

from django.core.cache import cache
from django.db import connections, transaction
from django.utils import timezone

from autobot.channels.base import InboundItem, Rejected, RetryLater, Sent, StatusItem
from autobot.channels.demo import invites
from autobot.channels.demo.doors import Door, allowed, door
from autobot.channels.ratelimit import WindowLimiter
from autobot.ops.logging import bind, contextual
from autobot.runtime.cache import (
    SELECTOR_OWNER,
    demo_outbound_owner,
    record_auth_outcome,
    remember_demo_outbound,
)
from autobot.runtime.event_flow import finish, finish_and_send, finish_limited
from autobot.runtime.inbound import store
from autobot.runtime.jobs import INBOUND, ROUTE_DEMO_EVENT
from autobot.runtime.locks import demo_user_lock
from autobot.runtime.models import Channel, DemoEvent, DemoSession, OutboundMessage
from autobot.runtime.queue import enqueue
from autobot.tenancy.registry import LoadedTenant, get_registry
from autobot.tenancy.tx import tenant_tx
from core.errors import TransientError
from core.limits import MAX_ID_BYTES, plan_sends
from core.replies import Reply, Text
from core.ui import list_msg, paginate, row, section

log = logging.getLogger(__name__)

SELECT = "fp_select:"
PAGE = "fp_page:"
SELECTOR_COMMANDS = frozenset({"/start", "/negocio", "negocio"})

NO_ACCESS_TEXT = "No tienes acceso a esta demo."
PICK_TEXT = "👋 Demo de Autobot. Elige el negocio que quieres probar:"
PICKED_TEXT = "Demo · {name}. Escribe /negocio para cambiar."
NOT_AVAILABLE_TEXT = "Ese negocio no está disponible ahora mismo."
NONE_AVAILABLE_TEXT = "No hay ninguna demo disponible ahora mismo."

# A user without access on the Telegram door gets the refusal at most 3 times an hour
# (worker memory). WhatsApp never answers one: Meta bills every message.
refusals = WindowLimiter(limit=3, window_s=3600)

# Events accepted per person and door: past it they are dropped before being saved
# (webhook process memory).
EVENTS_PER_MINUTE = 30
event_limiter = WindowLimiter(limit=EVENTS_PER_MINUTE, window_s=60)

# Events accepted per door from people with no access (not on the list, no grant): past
# it they are dropped before being saved, whoever sends them. Bounds what a flood of
# strangers can write to `demo_event` and queue (webhook process memory).
STRANGER_EVENTS_PER_MINUTE = 60
stranger_limiter = WindowLimiter(limit=STRANGER_EVENTS_PER_MINUTE, window_s=60)

# The "Demo · {business}" notice already sent for an event (a retry must not repeat it).
NOTICE_SENT_KEY = "demo:picked:{event_id}"
NOTICE_SENT_TTL_S = 3600

INSERT_EVENT = """
    INSERT INTO demo_event (id, channel, provider_event_id, payload, status, received_at)
    VALUES (%s, %s, %s, %s::jsonb, 'pending', %s)
    ON CONFLICT (channel, provider_event_id) DO NOTHING
    RETURNING id
"""


def store_event(door: Door, item: InboundItem) -> bool:
    """Save a demo door item and queue its routing; False if already received (the
    provider retried). Writes no table with RLS."""
    if event_limiter.hit(f"{door.channel}:{item.external_id}"):
        log.warning("demo events of a person over the limit dropped")
        return False
    if not allowed(door, item):
        if door.channel == Channel.DEMO_WA and invites.candidate_code(door, item) is None:
            return False  # WhatsApp never answers a stranger: there is nothing to keep
        if stranger_limiter.hit(str(door.channel)):
            log.warning("demo events of people without access over the limit dropped")
            return False
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
        enqueue(
            ROUTE_DEMO_EVENT,
            {"event_id": str(row_[0])},
            queue=INBOUND,
            lock=demo_user_lock(door.channel, item.external_id),
        )
    return True


@contextual
def route_demo_event(event_id: UUID) -> None:
    event = DemoEvent.objects.filter(id=event_id).first()
    if event is None or event.status != DemoEvent.Status.PENDING:
        return
    bind(channel=event.channel, event_id=str(event_id))
    door_ = door(Channel(event.channel))
    if door_ is None:  # the door was switched off after the event was saved
        finish(DemoEvent, event.id)
        return
    items = door_.adapter.parse(event.payload, door_.description)
    item = items[0] if items else None
    if not isinstance(item, InboundItem):
        finish(DemoEvent, event.id)
        return
    payload = item.message.payload or ""
    if payload.startswith((SELECT, PAGE)):
        door_.adapter.acknowledge(event.payload, door_.description, door_.secrets)
    access = _gate_access(event, door_, item)
    if access is None:
        return
    available = _available()
    if access == "redeemed":
        # The message *was* the code: not forwarded to any business, and not kept.
        _finish_and_reply(event, door_, item, [business_list(available, 0)])
        _scrub(event)
    elif payload.startswith(PAGE):
        _handle_page(event, door_, item, available)
    elif payload.startswith(SELECT):
        _handle_select(event, door_, item, available)
    elif _is_selector_command(item.message.text):
        _finish_and_reply(event, door_, item, [business_list(available, 0)])
    else:
        _handle_session_message(event, door_, item, available)


def _gate_access(
    event: DemoEvent, door_: Door, item: InboundItem
) -> Literal["allowed", "redeemed"] | None:
    """`"allowed"` if the person may use the demo (their id is on the door's list or they
    hold a grant), `"redeemed"` if this very message redeemed an invite code. Otherwise
    the refusal is dealt with (Telegram: at most a few times an hour; WhatsApp: never,
    Meta bills every message) and None returned."""
    if allowed(door_, item):
        return "allowed"
    if invites.redeem(door_, item):
        return "redeemed"
    log.info("demo message from a user without access")
    if door_.channel == Channel.DEMO_TG:
        finish_limited(
            DemoEvent,
            event.id,
            refusals,
            item.external_id,  # someone insisting: the bot must not answer without limit
            lambda: _reply(door_, item, [Text(NO_ACCESS_TEXT)]),
            "demo reply not sent",
        )
    else:
        finish(DemoEvent, event.id)  # WhatsApp: never answer
    _scrub(event)  # nothing of a stranger is kept
    return None


def _handle_page(
    event: DemoEvent, door_: Door, item: InboundItem, available: list[LoadedTenant]
) -> None:
    page = business_list(available, _page(item.message.payload or ""))
    _finish_and_reply(event, door_, item, [page])


def _handle_select(
    event: DemoEvent, door_: Door, item: InboundItem, available: list[LoadedTenant]
) -> None:
    slug = (item.message.payload or "").removeprefix(SELECT)
    tenant = next((t for t in available if t.slug == slug), None)
    if tenant is None:
        _finish_and_reply(
            event, door_, item, [Text(NOT_AVAILABLE_TEXT), business_list(available, 0)]
        )
    else:
        _pick(event, door_, item, tenant)


def _handle_session_message(
    event: DemoEvent, door_: Door, item: InboundItem, available: list[LoadedTenant]
) -> None:
    """Anything else goes to the business the person picked, if it is still available."""
    session = DemoSession.objects.filter(
        channel=door_.channel, external_id=item.external_id
    ).first()
    if session is None:
        _finish_and_reply(event, door_, item, [business_list(available, 0)])
        return
    tenant = next((t for t in available if t.id == session.tenant_id), None)
    if tenant is None:
        session.delete()  # no longer available (paused, degraded, ambiguous)
        _finish_and_reply(
            event, door_, item, [Text(NOT_AVAILABLE_TEXT), business_list(available, 0)]
        )
        return
    DemoSession.objects.filter(pk=session.pk).update(selected_at=timezone.now())
    store(tenant, [item], door_.channel)
    finish(DemoEvent, event.id)


def _available() -> list[LoadedTenant]:
    """Demo tenants a person may pick: active, not degraded nor ambiguous."""
    return [
        t
        for t in get_registry().demo_tenants()
        if t.document.status == "active" and not t.is_degraded
    ]


def business_list(tenants: list[LoadedTenant], page: int) -> Reply:
    """The demo businesses a person may pick, 8 per page, by name and description."""
    if not tenants:
        return Text(NONE_AVAILABLE_TEXT)
    rows = []
    for t in sorted(tenants, key=lambda t: t.document.name.lower()):
        option = f"{SELECT}{t.slug}"
        if len(option.encode()) > MAX_ID_BYTES:  # a slug longer than 54 characters
            log.warning("demo tenant %s cannot be listed: its slug is too long", t.slug)
            continue
        description = t.document.demo.description if t.document.demo is not None else ""
        rows.append(row(option, t.document.name, description))
    pages = max(1, -(-len(rows) // 8))
    page = page if 0 <= page < pages else 0
    shown = paginate(rows, page, more_id=f"{PAGE}{page + 1}", back_id=f"{PAGE}0")
    return list_msg(PICK_TEXT, "Ver negocios", [section(None, shown)])


def _pick(event: DemoEvent, door_: Door, item: InboundItem, tenant: LoadedTenant) -> None:
    """Save the choice, say which business it is and send it a synthetic `menu`, so its
    pack answers with its menu. The notice goes first, so it arrives before the menu; if
    the job is cut before the end, a retry may repeat it, never the menu."""
    notice_key = NOTICE_SENT_KEY.format(event_id=event.id)
    if cache.get(notice_key) is None:
        if _reply(door_, item, [Text(PICKED_TEXT.format(name=tenant.document.name))]):
            raise TransientError("demo notice not sent")  # nothing done yet: retried whole
        cache.set(notice_key, True, timeout=NOTICE_SENT_TTL_S)
    DemoSession.objects.update_or_create(
        channel=door_.channel,
        external_id=item.external_id,
        defaults={"tenant_id": tenant.id, "selected_at": timezone.now()},
    )
    menu = _synthetic_menu(door_, item)
    store(tenant, [menu], door_.channel)
    finish(DemoEvent, event.id)


def _synthetic_menu(door_: Door, item: InboundItem) -> InboundItem:
    """A `menu` item from the same person, the way `process_event` reads it back."""
    body = door_.adapter.synthetic_text(item.payload, "menu")
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


def _scrub(event: DemoEvent) -> None:
    """Empty the saved update (the person is not known to the demo, so nothing of theirs
    is worth keeping). The event is already done: it is never parsed again."""
    DemoEvent.objects.filter(id=event.id, status=DemoEvent.Status.DONE).update(payload={})


def _finish_and_reply(
    event: DemoEvent, door_: Door, item: InboundItem, replies: list[Reply]
) -> None:
    finish_and_send(
        DemoEvent, event.id, lambda: _reply(door_, item, replies), "demo reply not sent"
    )


def route_demo_status(item: StatusItem) -> None:
    """A WhatsApp demo door delivery status: find which demo tenant's outbound_message
    it belongs to and queue it there, like any other event of that tenant. Only database
    reads: no external call.

    Our outbound id (echoed by Meta) is remembered, per message, with the tenant that sent
    it (`runtime.cache.remember_demo_outbound`), so the usual case is a single lookup. Only
    when it is not remembered (expired, or no echoed id) is every demo tenant searched, each
    in its own `tenant_tx`: RLS is never bypassed."""
    ref: UUID | None = None
    if item.outbound_ref:
        try:
            ref = UUID(item.outbound_ref)
        except ValueError:
            ref = None
    owner = demo_outbound_owner(ref) if ref is not None else None
    if owner == SELECTOR_OWNER:
        return  # the selector's own message: it belongs to no tenant
    if isinstance(owner, UUID):
        tenant = get_registry().by_id.get(owner)
        if tenant is not None and tenant.is_demo:
            store(tenant, [item], Channel.DEMO_WA)
            return
    for tenant in get_registry().demo_tenants():
        with tenant_tx(tenant.id):
            found = (
                OutboundMessage.objects.filter(id=ref).exists()
                if ref is not None
                else OutboundMessage.objects.filter(
                    provider_message_id=item.provider_message_id
                ).exists()
            )
        if found:
            store(tenant, [item], Channel.DEMO_WA)
            return
    log.info("demo WhatsApp status for an unknown outbound message")


def _reply(door_: Door, item: InboundItem, replies: list[Reply]) -> bool:
    """Send the replies in order. True if the first one certainly was not sent and may be
    retried (`RetryLater`: no connection, or the provider asked to wait): then nothing
    went out. A failure after something was sent only stops the rest (resending would
    repeat what arrived)."""
    # WhatsApp: the phone when known (a BSUID recipient needs a feature Meta's test
    # numbers lack), like runtime.outbound._recipient; Telegram: the chat id.
    recipient = item.phone or item.external_id
    maybe_sent = False
    for reply in plan_sends(replies):
        outbound_id = uuid.uuid7()
        if door_.channel == Channel.DEMO_WA:
            remember_demo_outbound(outbound_id, None)  # its status belongs to no tenant
        outcome = door_.adapter.send(
            door_.adapter.render(reply, door_.description),
            recipient,
            door_.description,
            door_.secrets,
            outbound_id,
        )
        record_auth_outcome(str(door_.channel), outcome)
        if isinstance(outcome, RetryLater):
            log.warning("demo selector message not sent: RetryLater")
            if not maybe_sent:
                return True
            break
        if not isinstance(outcome, Sent):
            log.warning("demo selector message not sent: %s", type(outcome).__name__)
        maybe_sent = maybe_sent or not isinstance(outcome, Rejected)
    return False
