"""Storing and processing the owner bot's inbound events
(`docs/mejoras/02-avisos-y-resumenes.md` §6). Follows the pattern of
`autobot.channels.demo.selector`: the event is marked done *before* any reply is
sent, so a retry never repeats an answer."""

import json
import logging
import uuid
from typing import Any
from uuid import UUID

from django.db import connections, transaction
from django.utils import timezone

from autobot.channels.adapters import TELEGRAM
from autobot.channels.base import InboundItem, Sent
from autobot.channels.ratelimit import WindowLimiter
from autobot.jobs import HANDLE_OWNER_EVENT, INBOUND, app
from autobot.ops.logging import bind, contextual
from autobot.owner import links, menu, texts
from autobot.runtime.locks import owner_chat_lock
from autobot.runtime.models import OwnerEvent
from autobot.runtime.notifications import bot_secrets, deliver
from core.replies import Reply, Text

log = logging.getLogger(__name__)

# A chat without a tenant gets the "not linked" refusal at most 3 times an hour
# (worker memory); past that, silence.
NOT_LINKED_LIMIT = WindowLimiter(limit=3, window_s=3600)

INSERT_EVENT = """
    INSERT INTO owner_event (id, provider_event_id, payload, status, received_at)
    VALUES (%s, %s, %s::jsonb, 'pending', %s)
    ON CONFLICT (provider_event_id) DO NOTHING
    RETURNING id
"""


def store_owner_event(item: InboundItem) -> bool:
    """Save an owner bot item and queue its handling; False if already received (the
    provider retried). Writes no table with RLS."""
    event_id = uuid.uuid7()
    bind(event_id=str(event_id))
    with transaction.atomic(using="default"), connections["default"].cursor() as cursor:
        cursor.execute(
            INSERT_EVENT,
            [event_id, item.provider_event_id, json.dumps(item.payload), timezone.now()],
        )
        row = cursor.fetchone()
        if row is None:
            return False
        app.configure_task(
            HANDLE_OWNER_EVENT, queue=INBOUND, lock=owner_chat_lock(int(item.external_id))
        ).defer(event_id=str(row[0]))
    return True


@contextual
def handle_owner_event(event_id: UUID) -> None:
    event = OwnerEvent.objects.filter(id=event_id).first()
    if event is None or event.status != OwnerEvent.Status.PENDING:
        return
    bind(event_id=str(event_id))
    items = TELEGRAM.parse(event.payload, None)
    item = items[0] if items else None
    if not isinstance(item, InboundItem):
        _finish(event)
        return
    if item.message.type == "button":
        _acknowledge(event.payload)
    chat_id = int(item.external_id)

    text_in = (item.message.text or "").strip()
    body: str | None = None
    linked_slug: str | None = None
    if text_in.startswith("/start"):
        code = text_in.removeprefix("/start").strip()
        if code:
            result = links.start_link(code, chat_id)
            if result.status == "invalid":
                _finish_and_reply(event, chat_id, texts.invite_invalid())
                return
            if result.status == "taken":
                body = texts.chat_taken()
            else:
                assert result.tenant is not None
                body, linked_slug = texts.linked(result.tenant), result.tenant.slug

    tenants = links.tenants_of_chat(chat_id)
    if not tenants:
        if NOT_LINKED_LIMIT.hit(str(chat_id)):
            _finish(event)  # someone insisting: the bot must not answer without limit
        else:
            _finish_and_reply(event, chat_id, texts.not_linked())
        return

    chat = menu.OwnerChat(chat_id=chat_id, tenants=tenants)
    if body is None:
        payload = item.message.payload or ""
        body = (menu.answer(chat, payload) if payload else None) or texts.greeting(tenants)

    slug = linked_slug or (tenants[0].slug if len(tenants) == 1 else None)
    _finish_and_reply(event, chat_id, menu.menu_reply(chat, body), slug=slug)


def _acknowledge(payload: dict[str, Any]) -> None:
    secrets = bot_secrets()
    if secrets is not None:
        TELEGRAM.acknowledge(payload, None, secrets)


def _finish(event: OwnerEvent) -> None:
    OwnerEvent.objects.filter(id=event.id, status=OwnerEvent.Status.PENDING).update(
        status=OwnerEvent.Status.DONE
    )


def _finish_and_reply(
    event: OwnerEvent, chat_id: int, body: str | Reply, *, slug: str | None = None
) -> None:
    """Mark the event done, then answer: a retry never repeats the answer. Logs only
    the event id and, if known, the tenant slug -- never the chat id or any code."""
    _finish(event)
    if slug:
        bind(tenant=slug)
    reply = Text(body) if isinstance(body, str) else body
    outcome = deliver(reply, str(chat_id), event.id)
    if not isinstance(outcome, Sent):
        log.warning("owner bot reply not sent: %s", type(outcome).__name__)
