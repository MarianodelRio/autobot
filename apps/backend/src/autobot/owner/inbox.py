"""Storing and processing the owner bot's inbound events
(ADR-007). Follows the pattern of
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
from autobot.channels.base import InboundItem, RetryLater, Sent
from autobot.channels.ratelimit import WindowLimiter
from autobot.ops.logging import bind, contextual
from autobot.owner import links, menu, texts
from autobot.owner.operator import is_operator_chat
from autobot.runtime.event_flow import finish, finish_and_send, finish_limited
from autobot.runtime.jobs import HANDLE_OWNER_EVENT, INBOUND
from autobot.runtime.locks import owner_chat_lock
from autobot.runtime.models import OwnerEvent, OwnerLink
from autobot.runtime.notifications import bot_secrets, deliver
from autobot.runtime.queue import enqueue
from autobot.tenancy.registry import LoadedTenant
from core.replies import Reply, Text

log = logging.getLogger(__name__)

# A chat without a tenant gets the "not linked" refusal at most 3 times an hour
# (worker memory); past that, silence.
NOT_LINKED_LIMIT = WindowLimiter(limit=3, window_s=3600)

# Events accepted per chat (any chat): past it they are dropped before being saved
# (webhook process memory).
CHAT_EVENTS_PER_MINUTE = 30
chat_limiter = WindowLimiter(limit=CHAT_EVENTS_PER_MINUTE, window_s=60)

# Events accepted per minute from chats not connected to any business, all together:
# bounds what a flood of strangers can write to `owner_event` and queue.
STRANGER_EVENTS_PER_MINUTE = 60
stranger_limiter = WindowLimiter(limit=STRANGER_EVENTS_PER_MINUTE, window_s=60)

INSERT_EVENT = """
    INSERT INTO owner_event (id, provider_event_id, payload, status, received_at)
    VALUES (%s, %s, %s::jsonb, 'pending', %s)
    ON CONFLICT (provider_event_id) DO NOTHING
    RETURNING id
"""


def store_owner_event(item: InboundItem) -> bool:
    """Save an owner bot item and queue its handling; False if already received (the
    provider retried) or dropped for exceeding a limit. Writes no table with RLS."""
    if chat_limiter.hit(item.external_id):
        log.warning("owner bot events of a chat over the limit dropped")
        return False
    known = is_operator_chat(item.external_id) or (
        OwnerLink.objects.filter(chat_id=int(item.external_id)).exists()
    )
    if not known and stranger_limiter.hit("all"):
        log.warning("owner bot events of unlinked chats over the limit dropped")
        return False
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
        enqueue(
            HANDLE_OWNER_EVENT,
            {"event_id": str(row[0])},
            queue=INBOUND,
            lock=owner_chat_lock(int(item.external_id)),
        )
    return True


@contextual
def handle_owner_event(event_id: UUID) -> None:
    event = OwnerEvent.objects.filter(id=event_id).first()
    if event is None or event.status != OwnerEvent.Status.PENDING:
        return
    bind(event_id=str(event_id))
    _process(event)
    # Done (a retry raised before reaching here): the update, which may hold a link
    # code or a chat's text, is no longer needed. `provider_event_id` still dedupes.
    OwnerEvent.objects.filter(id=event.id, status=OwnerEvent.Status.DONE).update(payload={})


def _process(event: OwnerEvent) -> None:
    items = TELEGRAM.parse(event.payload, None)
    item = items[0] if items else None
    if not isinstance(item, InboundItem):
        finish(OwnerEvent, event.id)
        return
    if item.message.type == "button":
        _acknowledge(event.payload)
    chat_id = int(item.external_id)

    body: str | None = None
    linked_slug: str | None = None
    code = _start_code((item.message.text or "").strip())
    if code:
        started = _handle_start_code(event, chat_id, code)
        if started is None:
            return  # the invite was invalid: already answered (or not, past the limit)
        body, linked_slug = started

    tenants = links.tenants_of_chat(chat_id)
    operator = is_operator_chat(chat_id)
    if not tenants and not operator:
        _reply_limited(event, chat_id, texts.not_linked())  # someone insisting: no answer
        return

    chat = menu.OwnerChat(chat_id=chat_id, tenants=tenants, operator=operator)
    if body is None:
        payload = item.message.payload or ""
        body = (menu.answer(chat, payload) if payload else None) or texts.greeting(
            tenants, operator=operator
        )

    slug = linked_slug or (tenants[0].slug if len(tenants) == 1 else None)
    _finish_and_reply(event, chat_id, menu.menu_replies(chat, body), slug=slug)


def _handle_start_code(event: OwnerEvent, chat_id: int, code: str) -> tuple[str, str | None] | None:
    """Redeem `/start <code>`: the text to answer with and the linked tenant's slug (None
    if none was linked), or None when the code is invalid and that was already answered."""
    result = links.start_link(code, chat_id)
    if result.status == "invalid":
        _reply_limited(event, chat_id, texts.invite_invalid())  # someone guessing codes
        return None
    if result.status == "taken":
        return texts.chat_taken(), None
    assert result.tenant is not None
    if result.replaced_chat_id is not None:
        _notify_replaced_chat(event, result.replaced_chat_id, result.tenant)
    return texts.linked(result.tenant), result.tenant.slug


def _notify_replaced_chat(event: OwnerEvent, old_chat_id: int, tenant: LoadedTenant) -> None:
    """Tell the chat that was connected that it no longer is (someone with a link took
    its place). Sent once, right after the link changed hands (a retry of the event
    finds the code spent), through the notify bot like any other message; no transaction
    is open. Never retried blindly: a failure is only logged, without the chat id."""
    outcome = deliver(Text(texts.chat_replaced(tenant)), str(old_chat_id), event.id)
    if not isinstance(outcome, Sent):
        log.warning(
            "owner bot notice to the replaced chat not sent: %s",
            type(outcome).__name__ if outcome is not None else "bot unconfigured",
        )


def _reply_limited(event: OwnerEvent, chat_id: int, body: str) -> None:
    """Answer a chat without a tenant, at most a few times an hour; past that, silence."""
    finish_limited(
        OwnerEvent,
        event.id,
        NOT_LINKED_LIMIT,
        str(chat_id),
        lambda: _send(event, chat_id, Text(body)),
        "owner bot reply not sent",
    )


def _start_code(text: str) -> str | None:
    """The code of `/start <code>` or `/start@bot <code>` (Telegram adds the bot's name in
    groups and when the command is picked from a menu), or None."""
    words = text.split(maxsplit=1)
    if not words or words[0].split("@")[0].lower() != "/start" or len(words) < 2:
        return None
    return words[1].strip() or None


def _acknowledge(payload: dict[str, Any]) -> None:
    secrets = bot_secrets()
    if secrets is not None:
        TELEGRAM.acknowledge(payload, None, secrets)


def _send(event: OwnerEvent, chat_id: int, reply: Reply) -> bool:
    """Send the reply; True if it certainly was not sent and may be retried. Logs only
    the event id, never the chat id or any code."""
    outcome = deliver(reply, str(chat_id), event.id)
    if isinstance(outcome, RetryLater):
        return True
    if not isinstance(outcome, Sent):
        log.warning("owner bot reply not sent: %s", type(outcome).__name__)
    return False


def _send_all(event: OwnerEvent, chat_id: int, replies: list[Reply]) -> bool:
    """Send the replies in order; True (retry) only if the first one certainly did not
    go out. Once one went out, a later failure is logged, never retried: a retry would
    repeat what was already sent."""
    first, *rest = replies
    if _send(event, chat_id, first):
        return True
    for reply in rest:
        if _send(event, chat_id, reply):
            log.warning("owner bot reply only partly sent: the rest is not retried")
            break
    return False


def _finish_and_reply(
    event: OwnerEvent, chat_id: int, replies: list[Reply], *, slug: str | None = None
) -> None:
    """Mark the event done, then answer: a retry never repeats the answer."""
    if slug:
        bind(tenant=slug)
    finish_and_send(
        OwnerEvent, event.id, lambda: _send_all(event, chat_id, replies), "owner bot reply not sent"
    )
