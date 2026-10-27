"""Owner periodic summaries: periods, metric aggregation, rendering and the automatic
daily dispatch (`docs/mejoras/02-avisos-y-resumenes.md`). The on-demand status (the
notify bot's inbound webhook) is a separate, not-yet-implemented change."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from flowpilot.runtime import summary
from flowpilot.runtime.models import Contact, MetricEvent, Notification, OutboundMessage
from flowpilot.tenancy.models import Tenant
from flowpilot.tenancy.registry import get_registry
from flowpilot.tenancy.tx import tenant_tx
from tests.integration.helpers import jobs, wa_tenant

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]

MADRID = ZoneInfo("Europe/Madrid")
START = datetime(2026, 10, 1, tzinfo=MADRID)
END = datetime(2026, 11, 1, tzinfo=MADRID)


def contact(t: Tenant, external_id: str) -> Contact:
    return Contact.objects.using("owner").create(tenant=t, channel="main", external_id=external_id)


def message(t: Tenant, c: Contact, idem: str, created: datetime, **extra: Any) -> OutboundMessage:
    row = OutboundMessage.objects.using("owner").create(
        tenant=t, contact=c, channel="main", idem_key=idem, kind="reply", payload={}, **extra
    )
    OutboundMessage.objects.using("owner").filter(pk=row.pk).update(created_at=created)
    return row


def metric(t: Tenant, idem: str, kind: str, value: Decimal, created: datetime) -> MetricEvent:
    row = MetricEvent.objects.using("owner").create(tenant=t, idem_key=idem, kind=kind, value=value)
    MetricEvent.objects.using("owner").filter(pk=row.pk).update(created_at=created)
    return row


# ── previous_month ──────────────────────────────────────────────────────


def test_previous_month_normal() -> None:
    now = datetime(2026, 11, 1, 10, tzinfo=UTC)
    assert summary.previous_month(now, MADRID) == (START, END)


def test_previous_month_crosses_the_year() -> None:
    now = datetime(2026, 1, 1, 10, tzinfo=UTC)
    assert summary.previous_month(now, MADRID) == (
        datetime(2025, 12, 1, tzinfo=MADRID),
        datetime(2026, 1, 1, tzinfo=MADRID),
    )


# ── _generic_metrics ──────────────────────────────────────────────────────


def test_generic_metrics_keeps_a_contact_also_active_afterwards(tenants: Any) -> None:
    """Decision 9: counting over OutboundMessage (not Contact.last_activity_at) must not
    lose a contact that is also active after the period, before the summary runs."""
    tenants(wa_tenant())
    t = Tenant.objects.using("owner").get(slug="wa")
    a, b = contact(t, "a"), contact(t, "b")
    message(t, a, "m1", datetime(2026, 10, 10, tzinfo=MADRID))
    message(t, a, "m2", datetime(2026, 11, 5, tzinfo=MADRID))  # after the period: not counted
    message(t, b, "m3", datetime(2026, 10, 20, tzinfo=MADRID))
    with tenant_tx(t.id):
        generic = summary._generic_metrics(START, END)
    assert (generic.users, generic.messages) == (2, 2)


# ── _messaging_cost ───────────────────────────────────────────────────────


@pytest.mark.parametrize(("count", "billed"), [(3, 0), (4, 1), (5, 2)])
def test_messaging_cost_service_free_tier_cutoff(
    tenants: Any, monkeypatch: pytest.MonkeyPatch, count: int, billed: int
) -> None:
    monkeypatch.setattr(summary, "SERVICE_FREE_TIER", 3)
    tenants(wa_tenant())
    t = Tenant.objects.using("owner").get(slug="wa")
    c = contact(t, "a")
    for i in range(count):
        message(t, c, f"s{i}", datetime(2026, 10, 10, tzinfo=MADRID), pricing_category="service")
    with tenant_tx(t.id):
        cost = summary._messaging_cost(START, END)
    assert cost == (billed * summary.PRICE_EUR["service"]).quantize(Decimal("0.01"))


def test_messaging_cost_other_categories_have_no_free_tier_and_telegram_is_excluded(
    tenants: Any,
) -> None:
    tenants(wa_tenant())
    t = Tenant.objects.using("owner").get(slug="wa")
    c = contact(t, "a")
    when = datetime(2026, 10, 10, tzinfo=MADRID)
    message(t, c, "u1", when, pricing_category="utility")
    message(t, c, "mk1", when, pricing_category="marketing")
    message(t, c, "auth1", when, pricing_category="authentication")
    message(t, c, "tg1", when)  # a Telegram send: no pricing_category
    with tenant_tx(t.id):
        cost = summary._messaging_cost(START, END)
    expected = (
        summary.PRICE_EUR["utility"]
        + summary.PRICE_EUR["marketing"]
        + summary.PRICE_EUR["authentication"]
    )
    assert cost == expected.quantize(Decimal("0.01"))


# ── build_summary / _render ───────────────────────────────────────────────


def test_build_summary_renders_pack_metrics_first_then_generic(tenants: Any) -> None:
    tenants(wa_tenant())
    loaded = get_registry().by_slug["wa"]
    t = Tenant.objects.using("owner").get(slug="wa")
    c = contact(t, "a")
    metric(t, "g1", "greeted", Decimal(3), datetime(2026, 10, 5, tzinfo=MADRID))
    message(t, c, "m1", datetime(2026, 10, 6, tzinfo=MADRID))
    with tenant_tx(t.id):
        text = summary.build_summary(loaded, START, END)
    assert text == (
        "📊 Resumen de octubre\n"
        "• Saludos: 3\n"
        "• Usuarios: 1\n"
        "• Mensajes: 1\n"
        "• Coste aproximado de mensajería: 0,00 €"
    )


def test_build_summary_with_no_activity_shows_zeros_not_omitted(tenants: Any) -> None:
    tenants(wa_tenant())
    loaded = get_registry().by_slug["wa"]
    with tenant_tx(loaded.id):
        text = summary.build_summary(loaded, START, END)
    assert text == (
        "📊 Resumen de octubre\n"
        "• Saludos: 0\n"
        "• Usuarios: 0\n"
        "• Mensajes: 0\n"
        "• Coste aproximado de mensajería: 0,00 €"
    )


# ── dispatch_owner_summaries ────────────────────────────────────────────


def test_dispatch_skips_inactive_and_unsubscribed_tenants(tenants: Any) -> None:
    tenants(
        wa_tenant(
            "paused", status="paused", owner={"telegram_chat_id": 1, "summary_monthly": True}
        ),
        wa_tenant(
            "onboarding",
            status="onboarding",
            owner={"telegram_chat_id": 1, "summary_monthly": True},
        ),
        wa_tenant("off", owner={"telegram_chat_id": 1, "summary_monthly": False}),
    )
    now = datetime(2026, 11, 1, 11, tzinfo=UTC)
    assert summary.dispatch_owner_summaries(now) == 0
    assert not Notification.objects.using("owner").exists()


def test_dispatch_only_fires_on_day_one_local(tenants: Any) -> None:
    tenants(wa_tenant(owner={"telegram_chat_id": 555, "summary_monthly": True}))
    mid_month = datetime(2026, 11, 15, 11, tzinfo=UTC)
    assert summary.dispatch_owner_summaries(mid_month) == 0
    assert not Notification.objects.using("owner").exists()


def test_dispatch_uses_the_closed_previous_month_and_is_idempotent(tenants: Any) -> None:
    tenants(wa_tenant(owner={"telegram_chat_id": 555, "summary_monthly": True}))
    t = Tenant.objects.using("owner").get(slug="wa")
    wa = get_registry().by_slug["wa"]
    c = contact(t, "a")
    message(t, c, "oct", datetime(2026, 10, 15, tzinfo=MADRID))  # closed month: counted
    message(t, c, "nov", datetime(2026, 11, 1, 9, tzinfo=MADRID))  # current month: not counted
    now = datetime(2026, 11, 1, 11, tzinfo=UTC)

    assert summary.dispatch_owner_summaries(now) == 1
    (notice,) = Notification.objects.using("owner").all()
    assert notice.tenant_id == wa.id and notice.kind == "owner_summary"
    assert "Resumen de octubre" in notice.text
    assert "Usuarios: 1" in notice.text
    queued = [j for j in jobs() if j[0] == "send_notification"]
    assert [(j[1], j[2]) for j in queued] == [
        (f"owner:{wa.id}", {"tenant_id": str(wa.id), "notification_id": str(notice.id)})
    ]

    # A second run the same day 1 (e.g. a retried job) must not duplicate the send.
    assert summary.dispatch_owner_summaries(now) == 0
    assert Notification.objects.using("owner").count() == 1
