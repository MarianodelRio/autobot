"""The operator's daily summary (ADR-029): every day from 09:00 Madrid time, the
platform's state and yesterday's figures, to the operator's chat. It goes even when
nothing happened: a day without it says that something is wrong.

`ops_daily_summary` runs every hour; the first run past `DAILY_HOUR` sends it. The day's
cache key claims it first, so it goes at most once a day; it is released only when the
send certainly did not go out (`RetryLater`), and the next hour tries again."""

import logging
from datetime import date, datetime, timedelta
from uuid import uuid4

from django.conf import settings
from django.core.cache import cache

from autobot.channels.base import RetryLater, Sent
from autobot.ops import report, report_text
from autobot.runtime.notifications import bot_secrets, deliver
from core.replies import Text

log = logging.getLogger(__name__)

DAILY_HOUR = 9  # Madrid time
KEY_TTL_S = int(timedelta(days=2).total_seconds())


def daily_key(day: date) -> str:
    return f"ops:daily:{day.isoformat()}"


def send_daily_summary(now: datetime) -> bool:
    """Send today's summary if it is due and not sent yet; True if it went out."""
    local = now.astimezone(report.MADRID)
    if local.hour < DAILY_HOUR:
        return False
    if not settings.OPS_TELEGRAM_CHAT_ID or bot_secrets() is None:
        log.info("daily summary not sent: recipient or bot unconfigured")
        return False
    key = daily_key(local.date())
    if not cache.add(key, True, timeout=KEY_TTL_S):
        return False  # already sent today (or being sent)
    start, end = report.day_bounds(now, days_ago=1)
    text = report_text.daily_text(report.platform_status(now), report.day_figures(start, end), now)
    outcome = deliver(Text(text), str(settings.OPS_TELEGRAM_CHAT_ID), uuid4())
    if isinstance(outcome, Sent):
        return True
    if isinstance(outcome, RetryLater):
        cache.delete(key)  # certainly not sent: the next hour tries again
    log.warning("daily summary not sent: %s", type(outcome).__name__)
    return False
