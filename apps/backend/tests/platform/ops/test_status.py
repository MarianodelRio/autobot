"""Health levels have one precedence shared by all panel views."""

from types import SimpleNamespace
from typing import Any
from uuid import uuid7

import pytest
from django.utils import timezone

from autobot.ops import status
from autobot.ops.health import Issue
from autobot.tenancy.registry import LoadedTenant
from autobot.tenancy.schema import TenantDocument
from tests.helpers.integration import tg_tenant


@pytest.mark.parametrize(
    ("issues", "age", "level"),
    [
        ([], 0, "ok"),
        ([], 86401, "unknown"),
        ([Issue("x", "Notice")], 0, "notice"),
        ([Issue("x", "Warning", "🟠")], 0, "warning"),
        ([Issue("x", "Critical", "🔴")], 0, "critical"),
        ([Issue("x", "Persistent failure", "🔴")], 86401, "critical"),
    ],
)
def test_cached_health_levels(
    issues: list[Issue], age: int, level: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    cached = {"checked_at": timezone.now().timestamp() - age, "issues": issues}
    monkeypatch.setattr(status, "cache", SimpleNamespace(get=lambda key: cached))
    tenant = LoadedTenant(document=TenantDocument.model_validate(tg_tenant()))
    assert status.tenant_status(tenant).level == level


def test_missing_cache_degradation_and_active_disabled_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(status, "cache", SimpleNamespace(get=lambda key: None))
    tenant = LoadedTenant(document=TenantDocument.model_validate(tg_tenant()))
    assert status.tenant_status(tenant).level == "unknown"
    tenant.main_disabled.append("missing secrets")
    assert status.tenant_status(tenant).level == "critical"
    tenant.degraded.append("broken config")
    assert "Configuración degradada" in status.tenant_status(tenant).reasons


def test_alert_severity_and_tenant_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(status, "cache", SimpleNamespace(get=lambda key: None))
    tenant = LoadedTenant(document=TenantDocument.model_validate(tg_tenant()))
    unrelated: Any = SimpleNamespace(tenant_id=uuid7(), severity="critical")
    warning: Any = SimpleNamespace(tenant_id=tenant.id, severity="warning")
    critical: Any = SimpleNamespace(tenant_id=tenant.id, severity="critical")
    assert status.tenant_status(tenant, open_alerts=[unrelated]).level == "unknown"
    assert status.tenant_status(tenant, open_alerts=[warning]).level == "warning"
    assert status.tenant_status(tenant, open_alerts=[warning, critical]).level == "critical"


def test_notice_alert_and_info_health(monkeypatch: pytest.MonkeyPatch) -> None:
    cached = {"checked_at": timezone.now().timestamp(), "issues": [Issue("x", "Info", "🟢")]}
    monkeypatch.setattr(status, "cache", SimpleNamespace(get=lambda key: cached))
    tenant = LoadedTenant(document=TenantDocument.model_validate(tg_tenant()))
    assert status.tenant_status(tenant).level == "ok"
    alert: Any = SimpleNamespace(tenant_id=tenant.id, severity="notice")
    assert status.tenant_status(tenant, open_alerts=[alert]).level == "notice"
