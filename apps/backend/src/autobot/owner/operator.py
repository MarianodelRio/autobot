"""The operator's menu in the notify bot (ADR-029): read-only questions about the
platform, answered only in the operator's chat (`OPS_TELEGRAM_CHAT_ID`, the one that
receives the incident pushes). A new option is one more entry of `OPERATOR_MENU`.

Read-only on purpose: Telegram is not the panel (SSH tunnel, password and code), so
nothing here changes anything, and no answer carries personal data, only figures,
states and business names (`ops.report`)."""

from django.conf import settings
from django.utils import timezone

from autobot.ops import report, report_text
from autobot.owner.options import MenuOption, OwnerChat


def is_operator_chat(chat_id: int | str) -> bool:
    configured = settings.OPS_TELEGRAM_CHAT_ID.strip()
    return bool(configured) and configured == str(chat_id).strip()


def status(chat: OwnerChat) -> str:
    now = timezone.now()
    return report_text.status_text(report.platform_status(now), now)


def incidents(chat: OwnerChat) -> str:
    return report_text.incidents_text(report.open_incidents(), timezone.now())


def today(chat: OwnerChat) -> str:
    now = timezone.now()
    start, end = report.day_bounds(now)
    return report_text.day_text(report.day_figures(start, end), report_text.today_title(now))


def tenants(chat: OwnerChat) -> str:
    now = timezone.now()
    return report_text.tenants_text(report.tenant_lines(now), now)


def backups(chat: OwnerChat) -> str:
    now = timezone.now()
    return report_text.backups_text(report.backups(now), report.cleanup(), now)


OPERATOR_MENU: list[MenuOption] = [
    MenuOption("ops:status", "🩺 Estado", status),
    MenuOption("ops:alerts", "🚨 Incidencias", incidents),
    MenuOption("ops:today", "📊 Hoy", today),
    MenuOption("ops:tenants", "🏪 Clientes", tenants),
    MenuOption("ops:backups", "💾 Backups", backups),
]
