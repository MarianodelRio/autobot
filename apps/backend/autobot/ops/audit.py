"""Audit log of every write the panel and the operator commands make."""

from typing import Any
from uuid import UUID

from django.db import transaction

from autobot.ops.models import AuditEvent

FORBIDDEN_KEYS = frozenset(
    {
        "token",
        "secret",
        "password",
        "access_token",
        "app_secret",
        "verify_token",
        "bot_token",
        "webhook_secret",
        "otp",
    }
)


def _check(details: Any) -> None:
    if isinstance(details, dict):
        for key, value in details.items():
            if key in FORBIDDEN_KEYS:
                raise ValueError(f"audit details cannot carry a secret-shaped key: {key}")
            _check(value)
    elif isinstance(details, list):
        for value in details:
            _check(value)


def record(
    *,
    actor: str,
    action: str,
    summary: str,
    tenant_id: UUID | None = None,
    target_type: str = "",
    target_id: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    details = details or {}
    _check(details)
    with transaction.atomic(using="owner"):
        AuditEvent.objects.using("owner").create(
            actor=actor,
            action=action,
            summary=summary,
            tenant_id=tenant_id,
            target_type=target_type,
            target_id=target_id,
            details=details,
        )
