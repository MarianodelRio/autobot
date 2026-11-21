"""Persistent operation cooldowns must survive cache capacity pressure."""

from datetime import datetime
from uuid import UUID

from django.core.cache import cache
from django.core.cache.backends.db import DatabaseCache
from django.db import connections
from django.db.backends.utils import CursorWrapper

from autobot.channels.base import Rejected, SendOutcome, Sent


class CooldownCache(DatabaseCache):
    """Keep Django's database cache API, but never evict unexpired cooldowns."""

    _table: str  # Initialized by DatabaseCache; absent from django-stubs.

    def _cull(self, db: str, cursor: CursorWrapper, now: datetime, num: int) -> None:
        connection = connections[db]
        table = connection.ops.quote_name(self._table)
        cursor.execute(
            f"DELETE FROM {table} WHERE expires < %s",
            [connection.ops.adapt_datetimefield_value(now)],
        )


def auth_flag_key(channel: str) -> str:
    """The cache key of a bot whose last send was refused for authentication: `notify`
    (the notices bot) or a demo channel. Read by `ops/check.py` and the panel."""
    return f"bot:{channel}:auth"


def record_auth_outcome(channel: str, outcome: SendOutcome | None) -> None:
    """Raise the bot's auth flag when a send was refused for authentication, lower it
    when one went out."""
    if isinstance(outcome, Rejected) and outcome.kind == "auth":
        cache.set(auth_flag_key(channel), True, timeout=None)
    elif isinstance(outcome, Sent):
        cache.delete(auth_flag_key(channel))


# Which tenant (or the selector itself) an outbound message of the WhatsApp demo door
# belongs to, by our outbound id: a delivery status echoes it back, so it can be routed
# without looking in every demo tenant. It holds no personal data; a miss (expired, or
# a message from before this existed) falls back to the slow search.
DEMO_OUTBOUND_TTL_S = 7 * 24 * 3600
SELECTOR_OWNER = "selector"


def _demo_outbound_key(outbound_id: UUID) -> str:
    return f"demo:out:{outbound_id}"


def remember_demo_outbound(outbound_id: UUID, owner: UUID | None) -> None:
    """`owner`: the demo tenant that sent it, or None for the selector's own message."""
    cache.set(
        _demo_outbound_key(outbound_id),
        SELECTOR_OWNER if owner is None else str(owner),
        timeout=DEMO_OUTBOUND_TTL_S,
    )


def demo_outbound_owner(outbound_id: UUID) -> UUID | str | None:
    """The tenant id, `SELECTOR_OWNER`, or None when unknown."""
    value = cache.get(_demo_outbound_key(outbound_id))
    if value is None:
        return None
    if value == SELECTOR_OWNER:
        return SELECTOR_OWNER
    try:
        return UUID(str(value))
    except ValueError:
        return None
