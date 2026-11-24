"""The operator's daily summary (ADR-029): from 09:00 Madrid time, once a day, retried
only when it certainly did not go out."""

from collections.abc import Iterator
from datetime import datetime
from typing import Any

import pytest
from django.core.cache import cache
from pytest_django import Settings

from autobot.channels.base import Ambiguous, RetryLater
from autobot.ops import daily
from autobot.ops.report import MADRID
from autobot.runtime import notifications
from autobot.runtime.jobs import OPS_DAILY_SUMMARY, PERIODIC, app
from tests.helpers.integration import Providers, providers, wa_tenant

__all__ = ["providers"]  # re-exported fixture

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]

OPS_CHAT = 777
TOKEN = "123:NOTIFY-TOKEN"
NINE = datetime(2026, 11, 24, 9, 5, tzinfo=MADRID)


@pytest.fixture(autouse=True)
def ops_chat(settings: Settings, tenants: Any) -> Iterator[None]:
    settings.NOTIFY_BOT_TOKEN = TOKEN
    settings.OPS_TELEGRAM_CHAT_ID = str(OPS_CHAT)
    tenants(wa_tenant())
    cache.delete(daily.daily_key(NINE.date()))
    yield


def test_it_runs_hourly_on_the_periodic_queue() -> None:
    (task,) = [
        t for t in app.periodic_registry.periodic_tasks.values() if t.task.name == OPS_DAILY_SUMMARY
    ]
    assert task.cron == "5 * * * *" and task.task.queue == PERIODIC


def test_not_before_nine_then_once_a_day(providers: Providers) -> None:
    assert not daily.send_daily_summary(NINE.replace(hour=8))
    assert providers.texts(OPS_CHAT, TOKEN) == []
    assert daily.send_daily_summary(NINE)
    assert not daily.send_daily_summary(NINE.replace(hour=15))  # already sent today
    (text,) = providers.texts(OPS_CHAT, TOKEN)
    assert text.startswith("☀️ <b>Resumen diario</b>")
    assert "<b>Ayer</b>, lunes 23/11" in text


def test_a_send_that_certainly_failed_is_retried_the_next_hour(
    providers: Providers, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(daily, "deliver", lambda *args: RetryLater(kind="network"))
    assert not daily.send_daily_summary(NINE)
    monkeypatch.setattr(daily, "deliver", notifications.deliver)
    assert daily.send_daily_summary(NINE.replace(hour=10))
    assert len(providers.texts(OPS_CHAT, TOKEN)) == 1


def test_an_ambiguous_send_is_not_repeated(monkeypatch: pytest.MonkeyPatch) -> None:
    sends: list[Any] = []

    def ambiguous(*args: Any) -> Ambiguous:
        sends.append(args)
        return Ambiguous("5xx")

    monkeypatch.setattr(daily, "deliver", ambiguous)
    assert not daily.send_daily_summary(NINE)
    assert not daily.send_daily_summary(NINE.replace(hour=10))
    assert len(sends) == 1


def test_nothing_without_a_recipient(settings: Settings, providers: Providers) -> None:
    settings.OPS_TELEGRAM_CHAT_ID = ""
    assert not daily.send_daily_summary(NINE)
    assert providers.telegram == []
    settings.OPS_TELEGRAM_CHAT_ID = str(OPS_CHAT)
    assert daily.send_daily_summary(NINE)  # nothing was claimed meanwhile
