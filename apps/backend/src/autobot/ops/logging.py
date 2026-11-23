"""Structured logs and deliberately minimal, scrubbed Sentry error events."""

import functools
import inspect
import json
import logging
import re
import threading
import traceback
import weakref
from collections.abc import Awaitable, Callable, Iterable, Iterator
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
        from autobot.tenancy.registry import registry_scope

        with context(**values), registry_scope():
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
        from autobot.tenancy.registry import registry_scope

        with context(job=function.__name__), registry_scope():
            try:
                return await function(*args, **kwargs)
            except Exception:
                if settings.SENTRY_DSN:
                    import sentry_sdk

                    sentry_sdk.capture_exception()
                raise

    return wrapped


_REDACTED = "[REDACTED]"
_PREFIX = 4
_LONG_PREFIX = 12


class _SecretIndex:
    """All known secret values, searched in one pass over the text.

    Every secret is indexed by its first `_PREFIX` characters (fewer if one is shorter),
    so a log line costs one dict lookup per position, whatever the number of tenants.
    Every occurrence of every secret is found; overlapping or adjacent ones are merged
    and redacted as one, so no fragment of a secret survives."""

    def __init__(self, secrets: Iterable[str]) -> None:
        values = sorted(set(secrets) - {""}, key=len, reverse=True)
        self.size = min((len(value) for value in values), default=0)
        # Long secrets are bucketed by a long prefix: tokens of one provider share their
        # first characters (every Meta token starts with "EAA"), and a short bucket key
        # would put all tenants' tokens in one bucket, back to O(tenants) per match.
        # The few short secrets get their own small index.
        long = [value for value in values if len(value) >= _LONG_PREFIX]
        short = [value for value in values if len(value) < _LONG_PREFIX]
        self.indexes: list[tuple[int, dict[str, list[str]]]] = []
        for group, width in (
            (long, _LONG_PREFIX),
            (short, min(min((len(value) for value in short), default=0), _PREFIX)),
        ):
            if not group or width == 0:
                continue
            by_prefix: dict[str, list[str]] = {}
            for value in group:
                by_prefix.setdefault(value[:width], []).append(value)
            self.indexes.append((width, by_prefix))
        self.by_prefix = {key: hits for _, index in self.indexes for key, hits in index.items()}

    def redact(self, text: str) -> str:
        if not self.indexes or len(text) < self.size:
            return text
        found: list[tuple[int, int]] = []
        for width, by_prefix in self.indexes:
            for start in range(len(text) - width + 1):
                candidates = by_prefix.get(text[start : start + width])
                if candidates is None:
                    continue
                for value in candidates:
                    if text.startswith(value, start):
                        found.append((start, start + len(value)))
        spans: list[list[int]] = []
        for start, end in sorted(found):
            if spans and start <= spans[-1][1]:
                spans[-1][1] = max(spans[-1][1], end)
            else:
                spans.append([start, end])
        if not spans:
            return text
        parts: list[str] = []
        last = 0
        for start, end in spans:
            parts += [text[last:start], _REDACTED]
            last = end
        parts.append(text[last:])
        return "".join(parts)


_index_lock = threading.Lock()
# A few entries, not one: a job pinned to an older registry and a thread on the newest
# one would otherwise rebuild the index on every alternation. Weak references so an old
# registry is freed as soon as nothing else holds it.
_index_cache: list[tuple[weakref.ref[Any] | None, tuple[str, ...], _SecretIndex]] = []
_INDEX_ENTRIES = 3


def _settings_secrets() -> tuple[str, ...]:
    return (
        settings.SECRET_KEY,
        *settings.SECRETS_ENCRYPTION_KEYS,
        settings.DEMO_TELEGRAM_TOKEN,
        settings.DEMO_TELEGRAM_WEBHOOK_SECRET,
        settings.DEMO_WHATSAPP_APP_SECRET,
        settings.DEMO_WHATSAPP_ACCESS_TOKEN,
        settings.DEMO_WHATSAPP_VERIFY_TOKEN,
        settings.NOTIFY_BOT_TOKEN,
        settings.SENTRY_DSN,
        settings.HEALTHCHECKS_PING_URL,
    )


def _secret_index() -> _SecretIndex:
    """The index for the loaded registry, rebuilt only when the registry (its identity:
    a reload publishes a new object) or the configured secrets change."""
    from autobot.tenancy.registry import loaded_registry

    # Known configured values protect opaque tokens even if no recognizable prefix
    # is present. Access only an already-loaded registry, avoiding recursive logging.
    registry = loaded_registry()
    configured = _settings_secrets()
    for reference, known, index in _index_cache:
        owner = None if reference is None else reference()
        if owner is registry and (reference is None) == (registry is None) and known == configured:
            return index
    secrets = list(configured)
    if registry is not None:
        for tenant in registry.tenants:
            if tenant.secrets is not None:
                for secret in tenant.secrets.__dict__.values():
                    if hasattr(secret, "get_secret_value"):
                        secrets.append(secret.get_secret_value())
    index = _SecretIndex(secrets)
    entry = (None if registry is None else weakref.ref(registry), configured, index)
    with _index_lock:
        live = [item for item in _index_cache if item[0] is None or item[0]() is not None]
        _index_cache[:] = [entry, *live][:_INDEX_ENTRIES]
    return index


def redact(value: str) -> str:
    value = _secret_index().redact(value)
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
        if getattr(record, "_privacy_scrubbed", False):
            return True  # already scrubbed by a handler's filter: do not redo the work
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
        record._privacy_scrubbed = True
        return True


def record_dict(record: logging.LogRecord) -> dict[str, Any]:
    # Also scrub here, so direct formatter/handler use cannot bypass privacy protection.
    PrivacyFilter().filter(record)
    data = {
        "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
        "level": record.levelname,
        "msg": record.getMessage(),
        "service": settings.SERVICE_NAME,
    }
    data.update(
        {field: getattr(record, field, "") for field in ("tenant", "channel", "event_id", "job")}
    )
    if record.exc_text:
        data["exception"] = record.exc_text
    return data


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(record_dict(record), ensure_ascii=False)


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
