"""Access to `OwnerLink` and the `/start <code>` linking flow
(`docs/mejoras/02-avisos-y-resumenes.md` §5). No table here has RLS: the chat is not
known to belong to any tenant until this module says so."""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal
from uuid import UUID

from django.utils import timezone

from autobot.runtime.models import OwnerLink
from autobot.tenancy.registry import LoadedTenant, get_registry

OWNER_INVITE_DAYS = 7


def owner_chat(tenant_id: UUID) -> int | None:
    link = OwnerLink.objects.filter(tenant_id=tenant_id).first()
    return link.chat_id if link is not None else None


def tenants_of_chat(chat_id: int) -> list[LoadedTenant]:
    """Tenants connected to this chat, excluding any no longer usable (offboarded or
    sharing an id with another tenant)."""
    registry = get_registry()
    tenant_ids = OwnerLink.objects.filter(chat_id=chat_id).values_list("tenant_id", flat=True)
    tenants = (registry.by_id.get(tid) for tid in tenant_ids)
    return [
        t for t in tenants if t is not None and t.file.status != "offboarded" and not t.ambiguous
    ]


def new_invite(tenant_id: UUID) -> str:
    """A fresh invite code for `tenant_id`, replacing any pending one. Returns the
    plaintext code: it is never stored, only its sha256."""
    code = secrets.token_urlsafe(24)
    digest = hashlib.sha256(code.encode()).hexdigest()
    expires = timezone.now() + timedelta(days=OWNER_INVITE_DAYS)
    OwnerLink.objects.update_or_create(
        tenant_id=tenant_id, defaults={"invite_hash": digest, "invite_expires_at": expires}
    )
    return code


def unlink(tenant_id: UUID) -> bool:
    """Clear the chat and any pending invite (§5.2). True if a connected chat was
    removed."""
    had_chat = OwnerLink.objects.filter(tenant_id=tenant_id, chat_id__isnull=False).exists()
    OwnerLink.objects.filter(tenant_id=tenant_id).update(
        chat_id=None, linked_at=None, invite_hash=None, invite_expires_at=None
    )
    return had_chat


@dataclass(frozen=True)
class LinkResult:
    status: Literal["linked", "invalid", "taken"]
    tenant: LoadedTenant | None = None


def start_link(code: str, chat_id: int) -> LinkResult:
    """The `/start <code>` flow (§5.3). The code is single-use: linking clears the
    invite, so a replay of the same code always answers `invalid`."""
    digest = hashlib.sha256(code.encode()).hexdigest()
    link = OwnerLink.objects.filter(
        invite_hash=digest, invite_expires_at__gt=timezone.now()
    ).first()
    if link is None:
        return LinkResult("invalid")
    tenant = get_registry().by_id.get(link.tenant_id)
    if tenant is None or tenant.file.status == "offboarded":
        return LinkResult("invalid")
    if not tenant.is_demo and _chat_taken_by_another_real_tenant(chat_id, tenant.id):
        return LinkResult("taken")
    updated = OwnerLink.objects.filter(id=link.id, invite_hash=digest).update(
        chat_id=chat_id, linked_at=timezone.now(), invite_hash=None, invite_expires_at=None
    )
    if not updated:  # consumed by a concurrent request between the read and here
        return LinkResult("invalid")
    return LinkResult("linked", tenant)


def _chat_taken_by_another_real_tenant(chat_id: int, tenant_id: UUID) -> bool:
    """Decision 3 of the proposal: a chat may be connected to at most one real
    business; only demo tenants may share a chat."""
    registry = get_registry()
    other_ids = (
        OwnerLink.objects.filter(chat_id=chat_id)
        .exclude(tenant_id=tenant_id)
        .values_list("tenant_id", flat=True)
    )
    return any(
        (other := registry.by_id.get(other_id)) is not None
        and not other.is_demo
        and other.file.status != "offboarded"
        for other_id in other_ids
    )
