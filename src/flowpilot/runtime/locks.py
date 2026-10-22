"""Queue locks of a contact (design.md §7.1, §7.5). Procrastinate's job table has no RLS,
so a lock never carries a phone or a user id: only a hash of tenant, channel and id."""

import hashlib
from uuid import UUID


def contact_hash(tenant_id: UUID, channel: str, external_id: str) -> str:
    """`h`: the first 16 hex characters of sha256(tenant_id, channel, external_id)."""
    key = "\x00".join((str(tenant_id), channel, external_id))
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def telegram_user_lock(user_id: str) -> str:
    """`tg:<h>`: the test bot's selector handles one user's updates one at a time."""
    return f"tg:{hashlib.sha256(f'tg\x00{user_id}'.encode()).hexdigest()[:16]}"


def conversation_lock(tenant_id: UUID, channel: str, external_id: str) -> str:
    """`conv:<h>`: one contact's messages are processed one at a time, in order."""
    return f"conv:{contact_hash(tenant_id, channel, external_id)}"
