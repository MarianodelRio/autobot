"""The owner's monthly summary (`docs/mejoras/02-avisos-y-resumenes.md`).

Two distinct periods, always a calendar month or a prefix of one (decision 3 of the
proposal): `previous_month` for the automatic send (day 1, the month just closed) and
`month_to_date` for the on-demand status (not wired yet: it needs the notify bot's
inbound webhook, left for a separate change). Because of that, `build_summary` never
crosses a month boundary mid-calculation, which is why `_messaging_cost`'s free tier
needs no sub-period splitting.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from django.db.models import Count, Sum

from core.dates import MONTHS_ES
from core.pack import SummaryMetric
from flowpilot.jobs import OUTBOUND, SEND_NOTIFICATION, app
from flowpilot.runtime.models import MetricEvent, Notification, OutboundMessage
from flowpilot.tenancy.registry import LoadedTenant, get_registry
from flowpilot.tenancy.tx import tenant_tx

log = logging.getLogger(__name__)

# The kind of Notification an owner summary is sent as (flowpilot.runtime.notifications
# delivers it regardless of owner.notify, which only gates per-event notices).
OWNER_SUMMARY_KIND = "owner_summary"

# Approximate WhatsApp per-message price by template category (EUR), for Spain. Not the
# real tariff of any account: Meta's rate card is per country/currency and lives in each
# business's WhatsApp Business Manager billing panel. Last checked 2026-10-27, documented
# in docs/runbooks/alta-baja-negocio.md.
PRICE_EUR: dict[str, Decimal] = {
    "service": Decimal("0.0730"),
    "utility": Decimal("0.0394"),
    "marketing": Decimal("0.0988"),
    "authentication": Decimal("0.0363"),
}
SERVICE_FREE_TIER = 1000  # free "service" messages per WhatsApp number per month


def previous_month(now: datetime, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """The full calendar month before `now`'s month, in `tz`: on 1 November, [1
    October, 1 November)."""
    end = _month_start(now, tz)
    start = _add_months(end, -1)
    return start, end


def month_to_date(now: datetime, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """From day 1 of `now`'s month, 00:00 in `tz`, up to `now` itself."""
    return _month_start(now, tz), now


def _month_start(now: datetime, tz: ZoneInfo) -> datetime:
    local = now.astimezone(tz)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _add_months(at: datetime, months: int) -> datetime:
    total = at.month - 1 + months
    year, month = at.year + total // 12, total % 12 + 1
    return at.replace(year=year, month=month)


def dispatch_owner_summaries(now: datetime) -> int:
    """Queue the automatic monthly summary for every active tenant whose owner wants it
    and whose local day is 1. Returns how many were queued."""
    queued = 0
    for tenant in get_registry().tenants:
        if not _due(tenant, now):
            continue
        owner = tenant.file.owner
        assert owner is not None and owner.telegram_chat_id is not None  # validated at load
        start, end = previous_month(now, tenant.info.timezone)
        idem_key = f"summary:{tenant.id}:{start.year}-{start.month:02d}"
        with tenant_tx(tenant.id):
            text = build_summary(tenant, start, end)
            row = Notification(
                tenant_id=tenant.id,
                idem_key=idem_key,
                audience=Notification.Audience.OWNER,
                kind=OWNER_SUMMARY_KIND,
                text=text,
            )
            Notification.objects.bulk_create([row], ignore_conflicts=True)
            sent = Notification.objects.filter(id=row.id).exists()
            if sent:
                app.configure_task(
                    SEND_NOTIFICATION, queue=OUTBOUND, lock=f"owner:{tenant.id}"
                ).defer(tenant_id=str(tenant.id), notification_id=str(row.id))
        if sent:
            queued += 1
    return queued


def _due(tenant: LoadedTenant, now: datetime) -> bool:
    """Decision 14 of the proposal: only an active, non-degraded tenant, with
    `owner.summary_monthly`, on its own day 1."""
    owner = tenant.file.owner
    if tenant.file.status != "active" or tenant.is_degraded:
        return False
    if owner is None or not owner.summary_monthly:
        return False
    return now.astimezone(tenant.info.timezone).day == 1


def build_summary(tenant: LoadedTenant, start: datetime, end: datetime) -> str:
    """The summary text for `[start, end)`, run inside the caller's `tenant_tx`."""
    pack_metrics = _pack_metrics(tenant, start, end)
    generic = _generic_metrics(start, end)
    cost = _messaging_cost(start, end)
    return _render(start, end, pack_metrics, generic, cost)


def _pack_metrics(
    tenant: LoadedTenant, start: datetime, end: datetime
) -> list[tuple[SummaryMetric, Decimal]]:
    if tenant.pack is None:
        return []
    totals = dict(
        MetricEvent.objects.filter(created_at__gte=start, created_at__lt=end)
        .values("kind")
        .annotate(total=Sum("value"))
        .values_list("kind", "total")
    )
    return [(m, totals.get(m.kind, Decimal(0))) for m in tenant.pack.summary_metrics]


@dataclass(frozen=True)
class _Generic:
    users: int
    messages: int


def _generic_metrics(start: datetime, end: datetime) -> _Generic:
    """ "Usuarios" over `OutboundMessage`, never `Contact.last_activity_at` (decision 9):
    that field only keeps the last activity instant, which would drop a contact active
    in this closed period but also later, before the automatic summary runs."""
    messages = OutboundMessage.objects.filter(created_at__gte=start, created_at__lt=end)
    users = messages.values("contact_id").distinct().count()
    return _Generic(users=users, messages=messages.count())


def _messaging_cost(start: datetime, end: datetime) -> Decimal:
    """Decision 10: WhatsApp only (a Telegram send never gets `pricing_category`); the
    "service" category has a 1,000-message monthly free tier, the others are billed from
    the first message. Both periods always start on day 1, so this never needs to look
    outside `[start, end)` to know how many free messages are left."""
    counts = dict(
        OutboundMessage.objects.filter(
            created_at__gte=start, created_at__lt=end, pricing_category__isnull=False
        )
        .values("pricing_category")
        .annotate(total=Count("id"))
        .values_list("pricing_category", "total")
    )
    cost = Decimal(0)
    for category, price in PRICE_EUR.items():
        count = counts.get(category, 0)
        if category == "service":
            count = max(0, count - SERVICE_FREE_TIER)
        cost += price * count
    return cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _render(
    start: datetime,
    end: datetime,
    pack_metrics: list[tuple[SummaryMetric, Decimal]],
    generic: _Generic,
    cost: Decimal,
) -> str:
    month = MONTHS_ES[start.month - 1]
    full_month = end == _add_months(start, 1)
    header = (
        f"📊 Resumen de {month}"
        if full_month
        else f"📊 Estado de {month} (hasta hoy, día {end.day})"
    )
    lines = [header]
    lines += [f"• {metric.label}: {_format(total, metric.unit)}" for metric, total in pack_metrics]
    lines.append(f"• Usuarios: {generic.users}")
    lines.append(f"• Mensajes: {generic.messages}")
    lines.append(f"• Coste aproximado de mensajería: {_eur(cost)}")
    return "\n".join(lines)


def _format(value: Decimal, unit: str) -> str:
    return _eur(value) if unit == "eur" else str(int(value))


def _eur(value: Decimal) -> str:
    integer, _, decimals = f"{value:,.2f}".partition(".")
    return f"{integer.replace(',', '.')},{decimals} €"
