"""Queue locks of a contact. Procrastinate's job table has no RLS, so a lock never
carries a phone or a user id: only a keyed hash of tenant, channel and id.

The hash is an HMAC with a key of the platform (derived from `SECRET_KEY`), not a bare
sha256: a phone number or a Telegram id has too little entropy to resist a dictionary
attack on a plain hash, and the lock is readable by anyone who can read the job table.
It stays stable across processes (web, workers) as long as `SECRET_KEY` does; rotating it
only changes the locks of jobs queued afterwards (older jobs keep theirs, and for a
moment a contact's old and new jobs may not exclude each other)."""

import hashlib
import hmac
from functools import cache
from uuid import UUID

from django.conf import settings

_PURPOSE = b"autobot.queue-lock.v1"


@cache
def _key(secret: str) -> bytes:
    return hmac.new(secret.encode(), _PURPOSE, hashlib.sha256).digest()


def _hash(*parts: str) -> str:
    """The first 16 hex characters of HMAC-SHA256(platform key, parts)."""
    message = "\x00".join(parts).encode()
    return hmac.new(_key(str(settings.SECRET_KEY)), message, hashlib.sha256).hexdigest()[:16]


def contact_hash(tenant_id: UUID, channel: str, external_id: str) -> str:
    """`h`: a keyed hash of (tenant_id, channel, external_id)."""
    return _hash(str(tenant_id), channel, external_id)


def demo_user_lock(channel: str, external_id: str) -> str:
    """`demo:<h>`: the demo selector handles one person's updates, on one door, one
    at a time."""
    return f"demo:{_hash('demo', channel, external_id)}"


def owner_chat_lock(chat_id: int) -> str:
    """`ownerchat:<h>`: the owner bot handles one chat's updates one at a time."""
    return f"ownerchat:{_hash('ownerchat', str(chat_id))}"


def conversation_lock(tenant_id: UUID, channel: str, external_id: str) -> str:
    """`conv:<h>`: one contact's messages are processed one at a time, in order."""
    return f"conv:{contact_hash(tenant_id, channel, external_id)}"
