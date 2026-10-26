"""Structured logs and deliberately minimal, scrubbed Sentry error events."""

import functools
import inspect
import json
import logging
import re
import traceback
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from django.conf import settings

_context: ContextVar[dict[str, str] | None] = ContextVar("log_context", default=None)


@contextmanager
def context(**values: str) -> Iterator[None]:
    token = _context.set({**(_context.get() or {}), **values})
    try:
        yield
    finally:
        _context.reset(token)


def bind(**values: str) -> None:
    _context.set({**(_context.get() or {}), **values})


def contextual[**P, R](function: Callable[P, R]) -> Callable[P, R]:
    """Bind safe identifiers on runtime entry points, propagating into HTTP clients."""

    @functools.wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        values = {"job": function.__name__}
        bound = inspect.signature(function).bind_partial(*args, **kwargs).arguments
        for argument, field in (("tenant_id", "tenant"), ("event_id", "event_id")):
            if argument in bound:
                values[field] = str(bound[argument])
        with context(**values):
            try:
                return function(*args, **kwargs)
            except Exception:
                if settings.SENTRY_DSN:
                    import sentry_sdk

                    sentry_sdk.capture_exception()
                raise

    return wrapped


def async_contextual[**P, R](function: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    @functools.wraps(function)
    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        with context(job=function.__name__):
            try:
                return await function(*args, **kwargs)
            except Exception:
                if settings.SENTRY_DSN:
                    import sentry_sdk

                    sentry_sdk.capture_exception()
                raise

    return wrapped


def redact(value: str) -> str:
    # Known configured values protect opaque tokens even if no recognizable prefix
    # is present. Access only an already-loaded registry, avoiding recursive logging.
    secrets = [
        settings.SECRET_KEY,
        settings.DEMO_TELEGRAM_TOKEN,
        settings.DEMO_TELEGRAM_WEBHOOK_SECRET,
        settings.DEMO_WHATSAPP_APP_SECRET,
        settings.DEMO_WHATSAPP_ACCESS_TOKEN,
        settings.DEMO_WHATSAPP_VERIFY_TOKEN,
        settings.NOTIFY_BOT_TOKEN,
        settings.SENTRY_DSN,
        settings.HEALTHCHECKS_PING_URL,
    ]
    from flowpilot.tenancy.registry import get_registry

    if get_registry.cache_info().currsize:
        for tenant in get_registry().tenants:
            if tenant.secrets is not None:
                for secret in tenant.secrets.__dict__.values():
                    if hasattr(secret, "get_secret_value"):
                        secrets.append(secret.get_secret_value())
    for secret in sorted(set(secrets) - {""}, key=len, reverse=True):
        value = value.replace(secret, "[REDACTED]")
    value = re.sub(
        r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?)(?:(?:bearer|basic)\s+)?[^\s,;\"']+",
        r"\1[REDACTED]",
        value,
    )
    value = re.sub(r"(?i)(?:bearer\s+)[^\s,;\"']+", "Bearer [REDACTED]", value)
    value = re.sub(r"(?i)(bot)\d+:[A-Za-z0-9_-]+", r"\1[REDACTED]", value)
    value = re.sub(
        r"(?i)((?:access_token|bot_token|token|secret|password)[\"']?\s*[:=]\s*[\"']?)[^\s,;&\"']+",
        r"\1[REDACTED]",
        value,
    )
    # Phones: contiguous digits or commonly formatted international/local numbers.
    value = re.sub(
        r"(?<![\w-])\+?\d(?:[ .()-]?\d){6,14}(?![\w-])",
        lambda match: "***" + re.sub(r"\D", "", match[0])[-4:],
        value,
    )
    return value


class PrivacyFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        if record.exc_info:
            record.exc_text = redact("".join(traceback.format_exception(*record.exc_info)))
        for field in ("tenant", "channel", "event_id", "job"):
            setattr(
                record,
                field,
                redact(str(getattr(record, field, (_context.get() or {}).get(field, "")))),
            )
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # Also scrub here, so direct formatter use cannot bypass privacy protection.
        PrivacyFilter().filter(record)
        data = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "msg": record.getMessage(),
            "service": settings.SERVICE_NAME,
        }
        data.update(
            {
                field: getattr(record, field, "")
                for field in ("tenant", "channel", "event_id", "job")
            }
        )
        if record.exc_text:
            data["exception"] = record.exc_text
        return json.dumps(data, ensure_ascii=False)


def before_send(event: Any, hint: Any) -> Any:
    """Allow only diagnostic identifiers and stack locations out of the process.

    Requests, SDK contexts, arbitrary extras, breadcrumbs, locals, source lines and
    exception text can contain PII or unstructured secrets. Never transmit them.
    """
    clean = {
        key: event[key]
        for key in (
            "event_id",
            "timestamp",
            "level",
            "platform",
            "release",
            "environment",
            "logger",
        )
        if key in event
    }
    tags = {**(_context.get() or {}), **event.get("tags", {})}
    extra = event.get("extra", {})
    clean["tags"] = {
        field: redact(str(extra.get(field, tags.get(field, ""))))
        for field in ("tenant", "channel", "event_id", "job")
    }
    if "exception" in event:
        values = []
        for value in event["exception"].get("values", []):
            frames = [
                {
                    key: frame[key]
                    for key in ("filename", "function", "lineno", "module")
                    if key in frame
                }
                for frame in value.get("stacktrace", {}).get("frames", [])
            ]
            values.append(
                {
                    "type": value.get("type", "Exception"),
                    "value": "Exception details withheld",
                    "stacktrace": {"frames": frames},
                }
            )
        clean["exception"] = {"values": values}
    if "logentry" in event:
        clean["logentry"] = {
            "message": redact(
                str(event["logentry"].get("formatted") or event["logentry"].get("message", ""))
            )
        }

    # Scrub all remaining strings, including stack filenames and tag values.
    def scrub(value: Any) -> Any:
        if isinstance(value, str):
            return redact(value)
        if isinstance(value, dict):
            return {k: scrub(v) for k, v in value.items()}
        if isinstance(value, list):
            return [scrub(v) for v in value]
        return value

    return scrub(clean)


def initialize_sentry() -> None:
    if not settings.SENTRY_DSN:
        return
    import sentry_sdk
    from sentry_sdk.integrations.dedupe import DedupeIntegration
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        release=settings.RELEASE_SHA or None,
        environment=settings.ENVIRONMENT,
        send_default_pii=False,
        include_local_variables=False,
        max_request_body_size="never",
        default_integrations=False,
        integrations=[
            DedupeIntegration(),
            DjangoIntegration(),
            LoggingIntegration(level=None, event_level=logging.ERROR),
        ],
        before_send=before_send,
        before_breadcrumb=lambda crumb, hint: None,
    )


class LogContextMiddleware:
    def __init__(self, get_response: Callable[..., Any]) -> None:
        self.get_response = get_response

    def __call__(self, request: Any) -> Any:
        with context(job="request"):
            return self.get_response(request)
