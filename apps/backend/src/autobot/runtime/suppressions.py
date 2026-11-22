"""The suppression ledger (ADR-019): what `privacy.forget` and `privacy.purge` erased,
without personal data, so `privacy_reapply` can erase it again after a restore.

An identity (phone, Telegram id, BSUID) has too little entropy for a bare hash, so it is
an HMAC with a key derived from `SECRET_KEY` (same scheme as `runtime/locks.py`). The
hash is stable as long as `SECRET_KEY` is, and a restore already needs it (`.env`)."""

import hashlib
import hmac
from collections.abc import Iterable
from functools import cache
from typing import Any
from uuid import UUID

from django.conf import settings

from autobot.ops.models import PrivacySuppression

FORGET = "forget"
PURGE = "purge"
_PURPOSE = b"autobot.privacy-ledger.v1"


@cache
def _key(secret: str) -> bytes:
    return hmac.new(secret.encode(), _PURPOSE, hashlib.sha256).digest()


def identity_hash(channel: str, external_id: str) -> str:
    """The full HMAC-SHA256 (hex) of (channel, identity) under the platform key."""
    message = f"{channel}\x00{external_id}".encode()
    return hmac.new(_key(str(settings.SECRET_KEY)), message, hashlib.sha256).hexdigest()


def record(
    kind: str,
    tenant_id: UUID,
    *,
    contact_id: UUID | None = None,
    channel: str = "",
    identities: Iterable[str] = (),
) -> PrivacySuppression:
    """Write a ledger row; call it inside the erasure's own transaction."""
    return PrivacySuppression.objects.using("owner").create(
        kind=kind,
        tenant_id=tenant_id,
        contact_id=contact_id,
        channel=channel,
        identity_hashes=sorted({identity_hash(channel, item) for item in identities if item}),
    )


def as_dict(row: PrivacySuppression) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "at": row.at.isoformat(),
        "kind": row.kind,
        "tenant_id": str(row.tenant_id),
        "contact_id": str(row.contact_id) if row.contact_id else None,
        "channel": row.channel,
        "identity_hashes": list(row.identity_hashes),
    }


def export_rows() -> list[dict[str, Any]]:
    return [as_dict(row) for row in PrivacySuppression.objects.using("owner").order_by("at", "id")]
