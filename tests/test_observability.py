"""Structured logging and Sentry prevent secrets/PII while keeping diagnostic ids."""

import json
import logging
import sys
from typing import Any
from uuid import UUID

import pytest

from autobot.ops.logging import JsonFormatter, before_send, context, contextual, redact


@pytest.mark.parametrize("phone", ["+34612345678", "612345678", "+34 612 345 678", "612-345-678"])
def test_phone_mask(settings: Any, phone: str) -> None:
    assert phone not in redact(f"Teléfono {phone}")
    assert "5678" in redact(phone)


def test_json_fields_and_exception_privacy(settings: Any) -> None:
    settings.NOTIFY_BOT_TOKEN = 'opaque$token"secret'
    settings.HEALTHCHECKS_PING_URL = "https://hc.invalid/private"
    event_id = "0192c764-1111-7111-8111-123456789123"
    try:
        raise ValueError(f"+34612345678 {settings.NOTIFY_BOT_TOKEN}")
    except ValueError:
        record = logging.LogRecord(
            "test",
            logging.ERROR,
            __file__,
            1,
            "token=%s phone=%s",
            (settings.NOTIFY_BOT_TOKEN, "+34612345678"),
            sys.exc_info(),
        )
    with context(tenant="salon", channel="main", event_id=event_id, job="process_event"):
        output = JsonFormatter().format(record)
    data = json.loads(output)
    assert data["event_id"] == event_id
    assert (
        set(("ts", "level", "msg", "service", "tenant", "channel", "event_id", "job"))
        <= data.keys()
    )
    assert data["tenant"] == "salon" and data["job"] == "process_event"
    assert settings.NOTIFY_BOT_TOKEN not in output and "+34612345678" not in output
    assert "ValueError" in data["exception"]


def test_authorization_and_telegram_url(settings: Any) -> None:
    output = redact(
        "Authorization: Bearer arbitraryopaque https://api.telegram.org/bot123456:unconfiguredSecret/sendMessage"
    )
    assert "arbitraryopaque" not in output and "unconfiguredSecret" not in output


def test_sentry_scrubber_removes_requests_locals_and_raw_exception(settings: Any) -> None:
    settings.NOTIFY_BOT_TOKEN = 'opaque$token"secret'
    event_id = "0192c764-1111-7111-8111-123456789123"
    event = {
        "event_id": "0192c764111171118111123456789123",
        "timestamp": 1792920000.0,
        "request": {"data": {"phone": "+34612345678"}},
        "user": {"email": "private@example.org"},
        "extra": {"event_id": event_id, "tenant": "salon", "payload": "secret"},
        "breadcrumbs": [{"url": "https://secret.invalid"}],
        "exception": {
            "values": [
                {
                    "type": "ValueError",
                    "value": "private@example.org",
                    "stacktrace": {
                        "frames": [
                            {
                                "filename": "app.py",
                                "lineno": 12345678,
                                "vars": {"secret": settings.NOTIFY_BOT_TOKEN},
                                "pre_context": ["secret"],
                            }
                        ]
                    },
                }
            ]
        },
    }
    result = before_send(event, {})
    serialized = json.dumps(result)
    assert "private@example.org" not in serialized and "secret" not in serialized
    assert result["tags"]["event_id"] == event_id
    assert result["timestamp"] == event["timestamp"]
    assert result["exception"]["values"][0]["stacktrace"]["frames"][0]["lineno"] == 12345678


def test_worker_exception_captured_before_context_reset(settings: Any, monkeypatch: Any) -> None:
    import sentry_sdk

    settings.SENTRY_DSN = "https://public@example.invalid/1"
    seen = []
    monkeypatch.setattr(sentry_sdk, "capture_exception", lambda: seen.append(before_send({}, {})))

    @contextual
    def run(tenant_id: UUID) -> None:
        raise ValueError("private")

    tenant_id = UUID("0192c764-1111-7111-8111-123456789123")
    with context(tenant="", channel="", event_id="", job=""):
        with pytest.raises(ValueError):
            run(tenant_id)
        assert seen[0]["tags"]["tenant"] == str(tenant_id)
        assert before_send({}, {})["tags"]["tenant"] == ""
