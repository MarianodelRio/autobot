"""The shared steps of the platform's own event handlers (`DemoEvent`, `OwnerEvent`):
no tenant yet, so no RLS. An event is marked done *before* anything is answered, so a
retry never repeats an answer; the one exception is an answer that certainly was not
sent, which reopens the event and retries the job."""

from collections.abc import Callable
from uuid import UUID

from autobot.channels.ratelimit import WindowLimiter
from autobot.runtime.models import DemoEvent, OwnerEvent
from core.errors import TransientError

type EventModel = type[DemoEvent] | type[OwnerEvent]


def finish(model: EventModel, event_id: UUID) -> None:
    model.objects.filter(id=event_id, status=model.Status.PENDING).update(status=model.Status.DONE)


def finish_and_send(model: EventModel, event_id: UUID, send: Callable[[], bool], what: str) -> None:
    """Mark the event done, then `send()`. It returns True when nothing went out and it
    may be retried: then the event is reopened and the job retried (nothing was sent, so
    nothing repeats)."""
    finish(model, event_id)
    if send():
        model.objects.filter(id=event_id, status=model.Status.DONE).update(
            status=model.Status.PENDING
        )
        raise TransientError(what)


def finish_limited(
    model: EventModel,
    event_id: UUID,
    limiter: WindowLimiter,
    key: str,
    send: Callable[[], bool],
    what: str,
) -> None:
    """Someone insisting gets no answer past the limit; otherwise `finish_and_send`."""
    if limiter.hit(key):
        finish(model, event_id)
    else:
        finish_and_send(model, event_id, send, what)
