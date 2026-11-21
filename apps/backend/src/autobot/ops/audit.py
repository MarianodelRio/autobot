"""Audit log of every write the panel and the operator commands make."""

from typing import Any, Protocol
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


class HasId(Protocol):
    @property
    def id(self) -> UUID: ...


def _check(details: Any) -> None:
    if isinstance(details, dict):
        for key, value in details.items():
            if key in FORBIDDEN_KEYS:
                raise ValueError(f"audit details cannot carry a secret-shaped key: {key}")
            _check(value)
    elif isinstance(details, list):
        for value in details:
            _check(value)


def _clean(value: Any) -> Any:
    """Drop NUL characters: PostgreSQL rejects them in `text` and `jsonb`, and an audit
    write must never fail (nor roll back the action it records) over free text."""
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {_clean(key): _clean(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_clean(item) for item in value]
    return value


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
    details = _clean(details or {})
    _check(details)
    actor, action, summary = _clean(actor), _clean(action), _clean(summary)
    target_type, target_id = _clean(target_type), _clean(target_id)
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


def record_tenant(
    actor: str, action: str, tenant: HasId | UUID, summary: str, **details: Any
) -> None:
    """`record` for an event whose target is a tenant (a `LoadedTenant`, a `Tenant` or
    its id); any extra keyword arguments become the event's `details`."""
    tenant_id = tenant if isinstance(tenant, UUID) else tenant.id
    record(
        actor=actor,
        action=action,
        summary=summary,
        tenant_id=tenant_id,
        target_type="tenant",
        target_id=str(tenant_id),
        details=details or None,
    )
