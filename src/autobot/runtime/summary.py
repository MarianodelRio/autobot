"""The owner's monthly summary and on-demand status
(`docs/mejoras/02-avisos-y-resumenes.md`).

Two distinct periods, always a calendar month or a prefix of one (decision 3 of the
proposal): `previous_month` for the automatic send (day 1, the month just closed) and
`month_to_date` for the on-demand status, used by `autobot.owner.menu`.
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from django.db.models import Count, Sum
from procrastinate.exceptions import AlreadyEnqueued

from autobot.jobs import OUTBOUND, PERIODIC, SEND_NOTIFICATION, SEND_OWNER_SUMMARY, app
from autobot.owner import links
from autobot.runtime.context import CalendarFactory, build_context, google_calendar
from autobot.runtime.models import Channel, MetricEvent, Notification, OutboundMessage
from autobot.tenancy.registry import LoadedTenant, get_registry
from autobot.tenancy.tx import tenant_tx
from core.dates import MONTHS_ES
from core.errors import TransientError
from core.pack import SummaryLine

log = logging.getLogger(__name__)

# The kind of Notification an owner summary is sent as (autobot.runtime.notifications
# delivers it regardless of owner.notify, which only gates per-event notices).
OWNER_SUMMARY_KIND = "owner_summary"

SUMMARY_LOCAL_HOUR = 12  # decision 10 of the proposal

# Approximate Meta price per delivered message, Spain, EUR. Not the account's real
# tariff (Meta's rate card is per recipient country and lives in each business's
# WhatsApp Manager billing panel). Last checked 2026-10-29; see
# docs/runbooks/alta-baja-negocio.md.
PRICE_EUR: dict[str, Decimal] = {
    "marketing": Decimal("0.0585"),
    "utility": Decimal("0.0166"),
    "authentication": Decimal("0.0166"),
    "service": Decimal("0.0166"),
}


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
    """Queue `send_owner_summary` for every tenant due for its automatic monthly
    summary. Returns how many were queued. Runs hourly; `_due`'s `>=` lets a worker
    outage at noon be recovered later the same day, and `send_owner_summary`'s own
    idempotency key is what actually prevents a duplicate send."""
    queued = 0
    for tenant in get_registry().tenants:
        if not _due(tenant, now):
            continue
        start, _ = previous_month(now, tenant.info.timezone)
        try:
            app.configure_task(
                SEND_OWNER_SUMMARY, queue=PERIODIC, queueing_lock=f"summary:{tenant.id}"
            ).defer(tenant_id=str(tenant.id), year=start.year, month=start.month)
        except AlreadyEnqueued:
            continue
        queued += 1
    return queued


def _due(tenant: LoadedTenant, now: datetime) -> bool:
    """Decision 14 of the proposal: only an active, non-degraded tenant, with
    `owner.summary_monthly` and a connected chat, on its own day 1 past noon local
    time (decision 10)."""
    owner = tenant.file.owner
    if tenant.file.status != "active" or tenant.is_degraded:
        return False
    if owner is None or not owner.summary_monthly or links.owner_chat(tenant.id) is None:
        return False
    local = now.astimezone(tenant.info.timezone)
    return local.day == 1 and local.hour >= SUMMARY_LOCAL_HOUR


def send_owner_summary(tenant_id: UUID, year: int, month: int) -> None:
    """The job behind `dispatch_owner_summaries`: idempotent on
    `summary:<tenant_id>:<year>-<month>`, checked before ever calling Calendar. A
    failed pack hook raises `TransientError` so Procrastinate retries it (sending a
    summary with no citas would be misleading)."""
    tenant = get_registry().by_id.get(tenant_id)
    if tenant is None:
        log.error("owner summary of unknown tenant %s", tenant_id)
        return
    idem_key = f"summary:{tenant_id}:{year}-{month:02d}"
    with tenant_tx(tenant_id):
        if Notification.objects.filter(idem_key=idem_key).exists():
            return
    start = datetime(year, month, 1, tzinfo=tenant.info.timezone)
    end = _add_months(start, 1)
    block = build_summary(tenant, start, end)
    if block.pack_failed:
        raise TransientError(f"owner summary of tenant {tenant.slug}: pack hook failed")
    text = render([block], monthly=True)
    with tenant_tx(tenant_id):
        row = Notification(
            tenant_id=tenant_id,
            idem_key=idem_key,
            audience=Notification.Audience.OWNER,
            kind=OWNER_SUMMARY_KIND,
            text=text,
        )
        Notification.objects.bulk_create([row], ignore_conflicts=True)
        if Notification.objects.filter(id=row.id).exists():
            app.configure_task(SEND_NOTIFICATION, queue=OUTBOUND, lock=f"owner:{tenant_id}").defer(
                tenant_id=str(tenant_id), notification_id=str(row.id)
            )


@dataclass(frozen=True)
class SummaryBlock:
    """One tenant's summary for `[start, end)`."""

    tenant: LoadedTenant
    start: datetime
    end: datetime
    pack_lines: list[SummaryLine]
    pack_failed: bool
    generic: _Generic
    cost: Decimal


def build_summary(
    tenant: LoadedTenant,
    start: datetime,
    end: datetime,
    *,
    calendars: CalendarFactory = google_calendar,
) -> SummaryBlock:
    """The platform metrics are read inside one short transaction; the pack's own hook
    (`Pack.summary`) runs afterwards, with none open, because `salon` calls Google
    Calendar from it."""
    with tenant_tx(tenant.id):
        recorded = _recorded_metrics(start, end)
        generic = _generic_metrics(start, end)
        cost = _messaging_cost(start, end)
    pack_lines, pack_failed = _pack_lines(tenant, start, end, recorded, calendars)
    return SummaryBlock(tenant, start, end, pack_lines, pack_failed, generic, cost)


def _recorded_metrics(start: datetime, end: datetime) -> dict[str, Decimal]:
    """`MetricEvent` totals of the tenant in `[start, end)`, by `kind`."""
    return dict(
        MetricEvent.objects.filter(created_at__gte=start, created_at__lt=end)
        .values("kind")
        .annotate(total=Sum("value"))
        .values_list("kind", "total")
    )


def _pack_lines(
    tenant: LoadedTenant,
    start: datetime,
    end: datetime,
    recorded: Mapping[str, Decimal],
    calendars: CalendarFactory,
) -> tuple[list[SummaryLine], bool]:
    """`([], False)` for a degraded tenant or a pack without `summary`. A hook that
    raises is logged by exception type only (never tenant data) and reported as
    failed: the caller decides whether that means skipping or retrying the send."""
    if tenant.pack is None or tenant.pack.summary is None:
        return [], False
    try:
        ctx = build_context(
            tenant, Channel.MAIN, contact=None, state={}, event_id=None, calendars=calendars
        )
        return tenant.pack.summary(ctx, start, end, recorded), False
    except Exception as exc:
        log.warning(
            "owner summary: pack hook of tenant %s failed (%s)", tenant.slug, type(exc).__name__
        )
        return [], True


@dataclass(frozen=True)
class _Generic:
    users: int
    messages: int


def _generic_metrics(start: datetime, end: datetime) -> _Generic:
    """ "Usuarios" and "mensajes" over the `OutboundMessage` actually sent in the period
    (decision 9 of the proposal): `status="sent"`, by `sent_at`, never `created_at` (a
    message can be created in one period and sent, or fail, in a later one) nor
    `Contact.last_activity_at` (that field only keeps the last activity instant, which
    would drop a contact active in this closed period but also later, before the
    automatic summary runs)."""
    sent = OutboundMessage.objects.filter(
        status=OutboundMessage.Status.SENT, sent_at__gte=start, sent_at__lt=end
    )
    users = sent.values("contact_id").distinct().count()
    return _Generic(users=users, messages=sent.count())


def _messaging_cost(start: datetime, end: datetime) -> Decimal:
    """Decision 9: every message Meta actually billed (`billable=True`), by `sent_at`,
    priced per `pricing_category` at `PRICE_EUR`. Meta already applies its own free
    tiers and marks them `billable=False`, so none is computed here. A category not in
    `PRICE_EUR` (e.g. a new one Meta adds) is priced at the highest known rate, so the
    cost never falls short in silence, and is logged without any personal data."""
    counts = dict(
        OutboundMessage.objects.filter(billable=True, sent_at__gte=start, sent_at__lt=end)
        .values("pricing_category")
        .annotate(total=Count("id"))
        .values_list("pricing_category", "total")
    )
    highest = max(PRICE_EUR.values())
    cost = Decimal(0)
    for category, count in counts.items():
        price = PRICE_EUR.get(category) if category is not None else None
        if price is None:
            log.warning(
                "owner summary: unknown pricing category %r priced at the highest rate", category
            )
            price = highest
        cost += price * count
    return cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def render(blocks: Sequence[SummaryBlock], *, monthly: bool) -> str:
    """One or several tenants' blocks for the same period (several only for a demo
    chat shared between businesses, decision 3 of the proposal), as the text of a
    `Notification` or the on-demand status."""
    head = header(blocks[0].start, blocks[0].end, monthly=monthly)
    sections = [f"{b.tenant.info.name}\n\n" + "\n".join(block_lines(b)) for b in blocks]
    text = head + "\n" + "\n\n".join(sections)
    if any(line.unit == "eur" for b in blocks for line in b.pack_lines):
        text += "\n\n" + note(monthly=monthly)
    return text


def header(start: datetime, end: datetime, *, monthly: bool) -> str:
    month = MONTHS_ES[start.month - 1]
    if monthly:
        return f"📊 *Tu resumen de {month}*"
    return f"📊 *Así va {month}* (hasta hoy, día {end.day})"


def block_lines(b: SummaryBlock) -> list[str]:
    """A block's metric lines, as `render` and the owner bot's on-demand status
    (which substitutes a whole block for a tenant that is not usable) both need."""
    lines = [_line(line) for line in b.pack_lines]
    lines.append(f"👥 Clientes atendidos: {b.generic.users}")
    lines.append(f"💬 Mensajes enviados: {b.generic.messages}")
    if show_cost(b.tenant):
        lines.append(f"📱 Coste de WhatsApp: {_eur(b.cost)}")
    return lines


def show_cost(tenant: LoadedTenant) -> bool:
    """Decision 9: the cost line only means something for WhatsApp (or a demo tenant,
    whose messages come through the shared WhatsApp door)."""
    channel = tenant.file.channel
    return tenant.is_demo or (channel is not None and channel.type == "whatsapp")


def note(*, monthly: bool) -> str:
    base = "ℹ️ Ingresos según tus precios actuales; coste aproximado"
    return base + (" (la factura real está en tu cuenta de Meta)." if monthly else ".")


def _line(line: SummaryLine) -> str:
    text = f"{line.icon} {line.label}: {_format(line.value, line.unit)}"
    return f"{text} ({line.note})" if line.note else text


def _format(value: Decimal, unit: str) -> str:
    return _eur(value) if unit == "eur" else str(int(value))


def _eur(value: Decimal) -> str:
    integer, _, decimals = f"{value:,.2f}".partition(".")
    return f"{integer.replace(',', '.')},{decimals} €"
