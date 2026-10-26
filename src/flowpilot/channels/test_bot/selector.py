"""The test bot's business selector.

One Telegram bot of the platform lets the operator (`TEST_BOT_OPERATORS`, sees every
business) and each business's testers (`testers.telegram`) talk to any business they may
see, with its real logic. For a tenant, the test bot is its `test` channel: contacts,
conversations and messages of their own.

1. `store_update` (webhook or `telegram_poll`) saves the update in `test_bot_event`,
   which has no RLS (the tenant is not known yet), and queues `route_test_update` with
   the user's `tg:<h>` lock.
2. `route_test_update` decides: no permission → a refusal; `/start`, `/negocio` or no
   business picked → the list of businesses; `fp_select:<slug>` → picks it and sends a
   synthetic `menu` to that tenant; anything else → forwarded to the picked tenant, as
   an inbound_event of its `test` channel, processed by `process_event` as any other.

The selector's own messages (list, refusal, "🧪 Pruebas · …") belong to no tenant, so
they are sent here directly, once the update is marked done: at most once.
"""

import dataclasses
import json
import logging
import uuid
from typing import Any
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from django.db import connections, transaction
from django.utils import timezone

from core.limits import MAX_ID_BYTES, plan_sends
from core.replies import Reply, Text
from core.ui import list_msg, paginate, row, section
from flowpilot.channels.adapters import TELEGRAM, test_bot_secrets
from flowpilot.channels.base import InboundItem, Rejected, Sent
from flowpilot.channels.ratelimit import WindowLimiter
from flowpilot.jobs import INBOUND, ROUTE_TEST_UPDATE, app
from flowpilot.ops.logging import bind, contextual
from flowpilot.runtime.context import CalendarUnavailable, bound_calendar_id
from flowpilot.runtime.inbound import store
from flowpilot.runtime.locks import telegram_user_lock
from flowpilot.runtime.models import Channel, TestBotEvent, TestSession
from flowpilot.tenancy.registry import LoadedTenant, get_registry

log = logging.getLogger(__name__)

SELECT = "fp_select:"
PAGE = "fp_page:"
SELECTOR_COMMANDS = frozenset({"/start", "/negocio"})

NO_ACCESS_TEXT = "No tienes acceso al bot de pruebas."
PICK_TEXT = "🧪 Bot de pruebas. Elige el negocio que quieres probar:"
NONE_AVAILABLE_TEXT = "No hay ningún negocio disponible para probar ahora mismo."
NOT_AVAILABLE_TEXT = "Ese negocio no está disponible para pruebas ahora mismo."
PICKED_TEXT = "🧪 Pruebas · {name}. Escribe /negocio para cambiar."

# A user without access gets the refusal at most 3 times an hour (worker memory).
refusals = WindowLimiter(limit=3, window_s=3600)

INSERT_EVENT = """
    INSERT INTO test_bot_event (id, update_id, payload, status, received_at)
    VALUES (%s, %s, %s::jsonb, 'pending', %s)
    ON CONFLICT (update_id) DO NOTHING
    RETURNING id
"""


def store_update(update: dict[str, Any]) -> bool:
    """Save a test bot update and queue its routing; False if it was ignored (not a
    private chat with a person) or already received. Writes no table with RLS."""
    items = TELEGRAM.parse(update, None)
    if not items:
        return False
    (item,) = items
    assert isinstance(item, InboundItem)
    event_id = uuid.uuid7()
    bind(channel="test", event_id=str(event_id))
    with transaction.atomic(using="default"), connections["default"].cursor() as cursor:
        cursor.execute(
            INSERT_EVENT,
            [event_id, int(item.provider_event_id), json.dumps(update), timezone.now()],
        )
        row_ = cursor.fetchone()
        if row_ is None:
            return False  # Telegram retried
        app.configure_task(
            ROUTE_TEST_UPDATE, queue=INBOUND, lock=telegram_user_lock(item.external_id)
        ).defer(event_id=str(row_[0]))
    return True


@contextual
def route_test_update(event_id: UUID) -> None:
    bind(channel="test", event_id=str(event_id))
    event = TestBotEvent.objects.filter(id=event_id).first()
    if event is None or event.status != TestBotEvent.Status.PENDING:
        return
    items = TELEGRAM.parse(event.payload, None)
    item = items[0] if items else None
    if not isinstance(item, InboundItem):
        _finish(event)
        return
    user_id = int(item.external_id)
    visible = get_registry().visible_to(user_id, settings.TEST_BOT_OPERATORS)
    message = item.message
    payload = message.payload or ""
    if payload.startswith((SELECT, PAGE)):
        _acknowledge(event)  # the selector's own buttons; the others, process_event

    if not visible:
        log.info("test bot update from a user without access")
        if refusals.hit(str(user_id)):
            _finish(event)  # someone insisting: the bot must not answer without limit
        else:
            _finish_and_reply(event, user_id, [Text(NO_ACCESS_TEXT)])
        return
    available = [t for t in visible if is_available(t)]

    if payload.startswith(PAGE):
        _finish_and_reply(event, user_id, [business_list(available, _page(payload))])
    elif payload.startswith(SELECT):
        slug = payload.removeprefix(SELECT)
        tenant = next((t for t in available if t.slug == slug), None)
        if tenant is None:
            _finish_and_reply(
                event, user_id, [Text(NOT_AVAILABLE_TEXT), business_list(available, 0)]
            )
        else:
            _pick(event, item, tenant)
    elif _is_selector_command(message.text):
        _finish_and_reply(event, user_id, [business_list(available, 0)])
    else:
        session = TestSession.objects.filter(telegram_user_id=user_id).first()
        tenant = None
        if session is not None:
            tenant = next((t for t in available if t.id == session.tenant_id), None)
        if session is None:
            _finish_and_reply(event, user_id, [business_list(available, 0)])
        elif tenant is None:
            session.delete()  # no longer available (degraded, offboarded, no test calendar)
            _finish_and_reply(
                event, user_id, [Text(NOT_AVAILABLE_TEXT), business_list(available, 0)]
            )
        else:
            TestSession.objects.filter(telegram_user_id=user_id).update(selected_at=timezone.now())
            store(tenant, [item], Channel.TEST)
            _finish(event)


def is_available(tenant: LoadedTenant) -> bool:
    """May be tested now: not degraded, offboarded nor ambiguous, and with a test
    calendar of its own if its pack needs a calendar. Paused and onboarding
    tenants can be tested."""
    if tenant.is_degraded or tenant.ambiguous or tenant.file.status == "offboarded":
        return False
    try:
        bound_calendar_id(tenant, Channel.TEST)
    except CalendarUnavailable:
        return False
    return True


def business_list(tenants: list[LoadedTenant], page: int) -> Reply:
    """The businesses a user may pick, 8 per page, by name and pack."""
    if not tenants:
        return Text(NONE_AVAILABLE_TEXT)
    rows = []
    for t in sorted(tenants, key=lambda t: t.file.name.lower()):
        option = f"{SELECT}{t.slug}"
        if len(option.encode()) > MAX_ID_BYTES:  # a slug longer than 54 characters
            log.warning("tenant %s cannot be listed: its slug is too long", t.slug)
            continue
        rows.append(row(option, t.file.name, t.file.pack))
    pages = max(1, -(-len(rows) // 8))
    page = page if 0 <= page < pages else 0
    shown = paginate(rows, page, more_id=f"{PAGE}{page + 1}", back_id=f"{PAGE}0")
    return list_msg(PICK_TEXT, "Ver negocios", [section(None, shown)])


def _pick(event: TestBotEvent, item: InboundItem, tenant: LoadedTenant) -> None:
    """Save the choice, say which business it is and send it a synthetic `menu`, so its
    pack answers with its menu. The notice goes first, so it arrives before the menu; if
    the job is cut before the end, a retry may repeat it, never the menu."""
    user_id = int(item.external_id)
    _reply(user_id, [Text(PICKED_TEXT.format(name=tenant.file.name))])
    TestSession.objects.update_or_create(
        telegram_user_id=user_id,
        defaults={"tenant_id": tenant.id, "selected_at": timezone.now()},
    )
    (parsed,) = TELEGRAM.parse(_synthetic_menu(event), None)
    assert isinstance(parsed, InboundItem)  # what process_event will read back
    menu = dataclasses.replace(parsed, provider_event_id=f"select:{item.provider_event_id}")
    store(tenant, [menu], Channel.TEST)
    _finish(event)


def _synthetic_menu(event: TestBotEvent) -> dict[str, Any]:
    """A Telegram update with the text `menu` from the same user, as the runtime reads
    it."""
    update: dict[str, Any] = event.payload
    callback = update.get("callback_query") or {}
    sender: dict[str, Any] = callback.get("from") or update["message"]["from"]
    return {
        "update_id": update["update_id"],
        "message": {
            "message_id": 0,
            "from": sender,
            "chat": {"id": sender["id"], "type": "private"},
            "date": int(event.received_at.timestamp()),
            "text": "menu",
        },
    }


def _is_selector_command(text: str | None) -> bool:
    words = (text or "").split()
    return bool(words) and words[0].split("@")[0].lower() in SELECTOR_COMMANDS


def _page(payload: str) -> int:
    try:
        return int(payload.removeprefix(PAGE))
    except ValueError:
        return 0


def _finish(event: TestBotEvent) -> None:
    TestBotEvent.objects.filter(id=event.id, status=TestBotEvent.Status.PENDING).update(
        status=TestBotEvent.Status.DONE
    )


def _finish_and_reply(event: TestBotEvent, user_id: int, replies: list[Reply]) -> None:
    """Mark the update done, then answer: a retry never repeats the answer."""
    _finish(event)
    _reply(user_id, replies)


def _reply(user_id: int, replies: list[Reply]) -> None:
    secrets = test_bot_secrets()
    if secrets is None:
        log.error("test bot has no token: its selector cannot answer")
        return
    for reply in plan_sends(replies):
        outcome = TELEGRAM.send(
            TELEGRAM.render(reply, None), str(user_id), None, secrets, uuid.uuid7()
        )
        if isinstance(outcome, Rejected) and outcome.kind == "auth":
            cache.set("bot:test:auth", True, timeout=None)
        elif isinstance(outcome, Sent):
            cache.delete("bot:test:auth")
        if not isinstance(outcome, Sent):
            log.warning("test bot selector message not sent: %s", type(outcome).__name__)


def _acknowledge(event: TestBotEvent) -> None:
    secrets = test_bot_secrets()
    if secrets is not None:
        TELEGRAM.acknowledge(event.payload, None, secrets)
