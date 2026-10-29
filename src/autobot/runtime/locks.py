"""Queue locks of a contact. Procrastinate's job table has no RLS,
so a lock never carries a phone or a user id: only a hash of tenant, channel and id."""

import hashlib
from uuid import UUID


def contact_hash(tenant_id: UUID, channel: str, external_id: str) -> str:
    """`h`: the first 16 hex characters of sha256(tenant_id, channel, external_id)."""
    key = "\x00".join((str(tenant_id), channel, external_id))
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def demo_user_lock(channel: str, external_id: str) -> str:
    """`demo:<h>`: the demo selector handles one person's updates, on one door, one
    at a time."""
    key = f"{channel}\x00{external_id}"
    return f"demo:{hashlib.sha256(key.encode()).hexdigest()[:16]}"


def owner_chat_lock(chat_id: int) -> str:
    """`ownerchat:<h>`: the owner bot handles one chat's updates one at a time."""
    return f"ownerchat:{hashlib.sha256(str(chat_id).encode()).hexdigest()[:16]}"


def conversation_lock(tenant_id: UUID, channel: str, external_id: str) -> str:
    """`conv:<h>`: one contact's messages are processed one at a time, in order."""
    return f"conv:{contact_hash(tenant_id, channel, external_id)}"
