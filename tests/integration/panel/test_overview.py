"""`GET overview` / `build_overview()`: the Resumen screen's one call (DESIGN §9.4)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid7
from zoneinfo import ZoneInfo

import pytest

from autobot.ops.models import OpsAlert
from autobot.panel.services.overview import build_overview
from autobot.runtime.models import Contact, InboundEvent, MetricEvent, OutboundMessage
from autobot.tenancy.registry import get_registry
from tests.integration.helpers import demo_tenant, wa_tenant

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]

MADRID = ZoneInfo("Europe/Madrid")
NOW = datetime(2026, 11, 3, 10, tzinfo=UTC)


def tenant_id(slug: str) -> UUID:
    return get_registry().by_slug[slug].id


def contact(slug: str, n: int = 1) -> Contact:
    return Contact.objects.using("owner").create(
        tenant_id=tenant_id(slug), channel="main", external_id=f"3460000{n:04d}"
    )


def inbound(slug: str, at: datetime) -> InboundEvent:
    return InboundEvent.objects.using("owner").create(
        tenant_id=tenant_id(slug),
        channel="main",
        kind=InboundEvent.Kind.MESSAGE,
        provider_event_id=str(uuid7()),
        payload={},
        status=InboundEvent.Status.DONE,
        received_at=at,
    )


def outbound(
    slug: str,
    c: Contact,
    *,
    status: str = "sent",
    at: datetime | None = None,
    billable: bool | None = None,
    pricing_category: str | None = None,
    unknown_at: datetime | None = None,
) -> OutboundMessage:
    return OutboundMessage.objects.using("owner").create(
        tenant_id=tenant_id(slug),
        contact=c,
        channel="main",
        idem_key=str(uuid7()),
        kind=OutboundMessage.Kind.REPLY,
        payload={},
        status=status,
        billable=billable,
        pricing_category=pricing_category,
        sent_at=at if status == "sent" else None,
        unknown_at=unknown_at,
    )


def alert(kind: str, severity: str, *, resolved: bool = False) -> OpsAlert:
    return OpsAlert.objects.using("owner").create(
        kind=kind,
        severity=severity,
        text=f"{severity} {kind}",
        resolved_at=NOW if resolved else None,
        resolved_by="auto" if resolved else "",
    )


def test_known_data_produces_every_figure(tenants: Any) -> None:
    tenants(wa_tenant("a"), wa_tenant("b"), demo_tenant("demo"))
    ca1, ca2 = contact("a", 1), contact("a", 2)
    cb = contact("b", 3)
    cd = contact("demo", 4)

    # Outside the month: must never be counted.
    inbound("a", NOW.replace(month=10, day=31))

    inbound("a", NOW - timedelta(hours=1))
    inbound("a", NOW - timedelta(hours=2))
    inbound("a", NOW - timedelta(days=2))
    outbound("a", ca1, billable=True, pricing_category="utility", at=NOW - timedelta(hours=1))
    outbound("a", ca2, billable=True, pricing_category="marketing", at=NOW - timedelta(days=2))
    outbound("a", ca1, status="failed")
    outbound("a", ca1, status="unknown", unknown_at=NOW - timedelta(minutes=30))

    inbound("b", NOW - timedelta(hours=3))
    inbound("b", NOW - timedelta(hours=4))
    outbound("b", cb, billable=True, pricing_category="utility", at=NOW - timedelta(hours=3))

    inbound("demo", NOW - timedelta(hours=1))
    outbound("demo", cd, at=NOW - timedelta(hours=1))

    overview = build_overview(NOW)

    assert overview.month.inbound == 6
    assert overview.month.outbound == 4
    assert overview.month.users == 4  # ca1, ca2, cb, cd
    assert overview.month.billable == 3
    assert overview.month.cost_eur == Decimal("0.10")
    by_slug = {row.slug: row for row in overview.tenant_rows}
    assert by_slug["a"].inbound_month == 3 and by_slug["a"].outbound_month == 2
    assert by_slug["a"].cost_eur_month == Decimal("0.08")
    assert by_slug["b"].inbound_month == 2 and by_slug["b"].outbound_month == 1
    assert by_slug["b"].cost_eur_month == Decimal("0.02")
    assert by_slug["demo"].cost_eur_month == Decimal("0.00")
    assert overview.tenants.model_dump() == {
        "active": 2,
        "onboarding": 0,
        "paused": 0,
        "demos": 1,
        "total": 3,
    }


def test_cost_eur_is_the_sum_of_per_tenant_costs(tenants: Any) -> None:
    tenants(wa_tenant("a"), wa_tenant("b"))
    outbound("a", contact("a"), billable=True, pricing_category="utility", at=NOW)
    outbound("b", contact("b", 2), billable=True, pricing_category="marketing", at=NOW)
    overview = build_overview(NOW)
    assert overview.month.cost_eur == sum(
        (row.cost_eur_month for row in overview.tenant_rows), Decimal(0)
    )


@pytest.mark.parametrize(
    ("at", "counted"),
    [
        (datetime(2026, 10, 31, 22, 59, tzinfo=UTC), False),  # 23:59 CEST, October
        (datetime(2026, 10, 31, 23, 0, tzinfo=UTC), True),  # 00:00 CET, 1 November
    ],
)
def test_month_boundary_is_midnight_in_madrid(tenants: Any, at: datetime, counted: bool) -> None:
    tenants(wa_tenant("a"))
    inbound("a", at)
    overview = build_overview(NOW)
    assert overview.month.inbound == (1 if counted else 0)


@pytest.mark.parametrize(
    ("severity", "resolved", "expected"),
    [
        ("critical", False, "critical"),
        ("warning", False, "warning"),
        ("notice", False, "ok"),
        ("critical", True, "ok"),
    ],
)
def test_status_level_from_open_alerts(
    tenants: Any, severity: str, resolved: bool, expected: str
) -> None:
    tenants(wa_tenant("a"))
    alert("stuck", severity, resolved=resolved)
    assert build_overview(NOW).status.level == expected


def test_stale_outbound_also_raises_the_level_to_critical(tenants: Any) -> None:
    tenants(wa_tenant("a"))
    outbound("a", contact("a"), status="failed")
    assert build_overview(NOW).status.level == "critical"


def test_incidents_open_counts_alerts_and_stale_outbound(tenants: Any) -> None:
    tenants(wa_tenant("a"))
    alert("open-one", "warning")
    alert("open-two", "critical")
    alert("closed", "warning", resolved=True)
    outbound("a", contact("a"), status="failed")
    outbound("a", contact("a", 2), status="unknown", unknown_at=NOW - timedelta(minutes=30))
    outbound("a", contact("a", 3), status="unknown", unknown_at=NOW - timedelta(minutes=2))
    overview = build_overview(NOW)
    # 2 open alerts + 1 failed + 1 stale unknown (the recent unknown is not stale yet).
    assert overview.incidents_open == 4


def test_metrics_are_grouped_by_pack_and_kind_with_a_known_label(tenants: Any) -> None:
    tenants(wa_tenant("a"), wa_tenant("b"))
    for slug, value in (("a", 2), ("a", 3), ("b", 5)):
        MetricEvent.objects.using("owner").create(
            tenant_id=tenant_id(slug), kind="schedule_query", value=value, idem_key=str(uuid7())
        )
    metrics = build_overview(NOW).month.metrics
    assert len(metrics) == 1
    assert metrics[0].pack == "toy"
    assert metrics[0].kind == "schedule_query"
    assert metrics[0].label == "Consultas de horario"
    assert metrics[0].total == Decimal("10")


def test_query_budget(tenants: Any, django_assert_max_num_queries: Any) -> None:
    tenants(wa_tenant("a"), wa_tenant("b"), demo_tenant("demo"))
    outbound("a", contact("a"), billable=True, pricing_category="utility", at=NOW)
    with django_assert_max_num_queries(25, using="owner"):
        build_overview(NOW)
