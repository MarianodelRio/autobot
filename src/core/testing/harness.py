"""The conversation harness. Each turn follows `process_event` (design.md §7.2) without
the database: effective state, global commands, the pack, `plan_sends` in strict mode
(a reply out of the common limits fails the test) and the actions. Replies and state go
through JSON, as they would in `outbound_message.payload` and `conversation.state`."""

import itertools
import json
import logging
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from core.actions import Action, NotifyOwner, SendProactive, UpdateContact
from core.conversation import (
    effective_state,
    global_command,
    menu_message,
    opt_result,
    recovery_result,
)
from core.errors import TransientError
from core.idem import IdemKeys
from core.limits import MAX_ID_BYTES, plan_sends
from core.messages import IncomingMessage
from core.pack import ContactInfo, Pack, PackContext, PackResult, TenantInfo
from core.proactive import ProactiveMessage
from core.replies import Buttons, List, Reply, Text
from core.serialization import Outbound, dump_outbound, load_outbound
from core.testing.clock import FixedClock
from core.testing.effects import MemoryEffects

type ChannelType = Literal["whatsapp", "telegram"]

DEFAULT_NOW = "2026-10-05T10:00:00+02:00"

# Run on every reply and proactive message of every turn; they raise to fail the test.
# The platform's root conftest.py registers the rendering with both channel adapters here
# (design.md §17.2): core cannot import them.
RENDER_CHECKS: list[Callable[[Outbound], None]] = []


def sample_tenant(timezone: str = "Europe/Madrid") -> TenantInfo:
    return TenantInfo(
        id=UUID("01920000-0000-7000-8000-00000000000a"),
        slug="demo",
        name="Negocio de prueba",
        timezone=ZoneInfo(timezone),
    )


def sample_contact(channel: ChannelType) -> ContactInfo:
    """A contact as each channel delivers it: WhatsApp gives a phone, Telegram does not."""
    whatsapp = channel == "whatsapp"
    return ContactInfo(
        id=UUID("01920000-0000-7000-8000-00000000000c"),
        external_id="34600000001" if whatsapp else "100000001",
        phone="+34600000001" if whatsapp else None,
        display_name="Lucía",
        opt_out=False,
    )


@dataclass
class Turn:
    """What the contact receives after one message, plus the actions it produced."""

    replies: list[Reply]
    actions: list[Action] = field(default_factory=list)

    def expect(
        self,
        *,
        text: str | None = None,
        text_contains: str | None = None,
        buttons: list[str] | None = None,
        rows: list[str] | None = None,
        list_includes: str | None = None,
        nothing: bool = False,
    ) -> Turn:
        """Check the turn and return it, so checks can be chained.

        - `text`: some reply body is exactly this.
        - `text_contains`: some reply body contains this.
        - `buttons`: the titles of the last buttons message, in order.
        - `rows`: the row titles of the last list, in order.
        - `list_includes`: some list row title contains this.
        - `nothing`: no reply at all.
        """
        bodies = [r.body for r in self.replies]
        if nothing:
            self._check(not self.replies, "expected no reply")
        if text is not None:
            self._check(text in bodies, f"no reply body is {text!r}")
        if text_contains is not None:
            self._check(
                any(text_contains in b for b in bodies), f"no reply contains {text_contains!r}"
            )
        if buttons is not None:
            last = [r for r in self.replies if isinstance(r, Buttons)]
            got = [b.title for b in last[-1].buttons] if last else None
            self._check(got == buttons, f"buttons are {got}, expected {buttons}")
        lists = [r for r in self.replies if isinstance(r, List)]
        titles = [[row.title for s in lst.sections for row in s.rows] for lst in lists]
        if rows is not None:
            got_rows = titles[-1] if titles else None
            self._check(got_rows == rows, f"rows are {got_rows}, expected {rows}")
        if list_includes is not None:
            found = any(list_includes in t for ts in titles for t in ts)
            self._check(found, f"no list row contains {list_includes!r}")
        return self

    def _check(self, ok: bool, problem: str) -> None:
        if not ok:
            raise AssertionError(f"{problem}\nReplies:\n{self.describe()}")

    def describe(self) -> str:
        lines: list[str] = []
        for r in self.replies:
            match r:
                case Text():
                    lines.append(f"  Text: {r.body!r}")
                case Buttons():
                    lines.append(f"  Buttons: {r.body!r} {[(b.id, b.title) for b in r.buttons]}")
                case List():
                    items = [(row.id, row.title) for s in r.sections for row in s.rows]
                    lines.append(f"  List: {r.body!r} {items}")
        return "\n".join(lines) or "  (none)"


class Conversation:
    """One contact talking to a pack.

    ```python
    chat = Conversation(toy.pack, channel="telegram")
    chat.send("hola").expect(buttons=["Saludar", "Elegir color"])
    chat.press("greet").expect(text_contains="nombre")
    ```

    `attempts` is how many times a `TransientError` is tried with the same event before
    the recovery text, as the job retries in production (§7.5).
    """

    def __init__(
        self,
        pack: Pack,
        *,
        config: BaseModel | None = None,
        data: object | None = None,
        channel: ChannelType = "whatsapp",
        tenant: TenantInfo | None = None,
        calendar: Any = None,
        now: str | datetime = DEFAULT_NOW,
        attempts: int = 1,
    ) -> None:
        if attempts < 1:
            raise ValueError("attempts must be at least 1")
        self.pack = pack
        self.config = config if config is not None else pack.config_schema()
        self.data = data
        self.channel = channel
        self.tenant = tenant or sample_tenant()
        self.calendar = calendar
        self.clock = FixedClock(_aware(now), self.tenant.timezone)
        self.attempts = attempts
        self.contact = sample_contact(channel)
        self.state: dict[str, Any] = {}
        self.state_version: int | None = None
        self.last_inbound_at: datetime | None = None
        self.turns: list[Turn] = []
        self.actions: list[Action] = []
        self.locks: list[str] = []
        self._event_ids = (
            UUID(int=0x0192_0000_0000_7000_8000_0000_0000_0000 + n) for n in itertools.count(1)
        )
        self._effects: dict[str, dict[str, Any]] = {}
        self._pressable: set[str] = set()
        self._last: _Snapshot | None = None

    # ── Driving the conversation ──────────────────────────────────────────

    def now(self, at: str | datetime) -> None:
        self.clock.set(_aware(at))

    def send(self, text: str) -> Turn:
        return self._turn(IncomingMessage("text", text, None, self.clock.now()))

    def press(self, payload: str, *, check: bool = True) -> Turn:
        """Press a button or list row by its id. With `check`, the id must have been
        offered earlier in the conversation (in a reply, or in a proactive message to
        this contact)."""
        if check and payload not in self._pressable:
            raise AssertionError(
                f"{payload!r} was never offered; offered: {sorted(self._pressable)}"
            )
        return self._turn(IncomingMessage("button", None, payload, self.clock.now()))

    def unsupported(self) -> Turn:
        """An audio, image, sticker… which the pack must answer by asking for text."""
        return self._turn(IncomingMessage("unsupported", None, None, self.clock.now()))

    def replay(self) -> Turn:
        """Process the last message again with the same event id, as a retry after the
        worker died between tx1 and tx2 (§7.2): everything the first attempt saved
        (state, contact changes, actions, replies) is undone first. Only the pack's own
        side effects (e.g. a fake calendar) remain, as in production."""
        if self._last is None:
            raise AssertionError("nothing to replay")
        last = self._last
        self.state, self.state_version = last.state, last.state_version
        self.last_inbound_at, self.contact = last.last_inbound_at, last.contact
        del self.actions[last.actions :]
        del self.turns[last.turns :]
        self._pressable = set(last.pressable)
        return self._turn(last.message, last.event_id)

    def run_periodic(self, name: str) -> list[Action]:
        """Run one of the pack's periodic handlers, as `run_periodic` does (§7.6)."""
        (periodic,) = [p for p in self.pack.periodic if p.name == name]
        actions = periodic.handler(self._context(None, {}, IdemKeys(None)))
        self._apply(actions)
        return actions

    @property
    def proactive(self) -> list[SendProactive]:
        return [a for a in self.actions if isinstance(a, SendProactive)]

    @property
    def notifications(self) -> list[NotifyOwner]:
        return [a for a in self.actions if isinstance(a, NotifyOwner)]

    # ── One turn, in the order of process_event ───────────────────────────

    def _turn(self, message: IncomingMessage, event_id: UUID | None = None) -> Turn:
        event_id = event_id or next(self._event_ids)
        self._last = _Snapshot(
            message=message,
            event_id=event_id,
            state=_json_copy(self.state),
            state_version=self.state_version,
            last_inbound_at=self.last_inbound_at,
            contact=self.contact,
            actions=len(self.actions),
            turns=len(self.turns),
            pressable=frozenset(self._pressable),
        )
        now = self.clock.now()
        effective = effective_state(
            self.state,
            self.state_version,
            self.last_inbound_at,
            pack_state_version=self.pack.state_version,
            timeout_min=self.pack.conversation_timeout_min,
            now=now,
        )
        state = effective.state
        command = global_command(message)
        idem = IdemKeys(event_id)
        if command == "menu":
            state = {}
            result = self._handle(state, menu_message(now), idem)
        elif command is not None:
            result = opt_result(command)
        else:
            result = self._handle(state, message, idem)

        planned = plan_sends([*effective.notices, *result.replies], strict=True)
        replies = [_through_json(r) for r in planned]
        for r in replies:
            _render(r)
        new_state = state if result.state is None else result.state
        self.state = _json_copy(new_state)  # as stored in conversation.state
        self.state_version = self.pack.state_version
        self.last_inbound_at = now
        self._apply(result.actions)
        for r in replies:
            if isinstance(r, Buttons):
                self._pressable.update(b.id for b in r.buttons)
            elif isinstance(r, List):
                self._pressable.update(row.id for s in r.sections for row in s.rows)
        turn = Turn(replies, list(result.actions))
        self.turns.append(turn)
        return turn

    def _handle(
        self, state: dict[str, Any], message: IncomingMessage, idem: IdemKeys
    ) -> PackResult:
        for attempt in range(1, self.attempts + 1):
            # A fresh copy per attempt: mutating ctx.state must not leak, as in production.
            ctx = self._context(self.contact, _json_copy(state), idem)
            try:
                return self.pack.handle_message(ctx, message)
            except TransientError:
                # Retried with the same event; after the last attempt the runtime answers
                # with the recovery text. Any other exception propagates, so a bug fails
                # the test.
                if attempt == self.attempts:
                    break
        return recovery_result()

    def _context(
        self, contact: ContactInfo | None, state: dict[str, Any], idem: IdemKeys
    ) -> PackContext:
        return PackContext(
            tenant=self.tenant,
            config=self.config,
            data=self.data,
            contact=contact,
            state=state,
            clock=self.clock,
            calendar=self.calendar if self.pack.needs_calendar else None,
            lock=self._lock,
            idem=idem,
            effects=MemoryEffects(
                self._effects,
                (
                    f"{self.tenant.id}:{idem.event_id}:{contact.id if contact else None}:"
                    f"{self.channel}:{id(self.calendar)}"
                ),
            )
            if idem.event_id is not None
            else None,
            log=logging.getLogger(f"packs.{self.pack.name}"),
            can_contact_by_phone=self.channel == "whatsapp",
        )

    def _apply(self, actions: list[Action]) -> None:
        for action in actions:
            match action:
                case UpdateContact():
                    if action.display_name is not None:
                        self.contact = replace(self.contact, display_name=action.display_name)
                    if action.opt_out is not None:
                        self.contact = replace(self.contact, opt_out=action.opt_out)
                case SendProactive():
                    self._check_proactive(action)
                    _render(
                        ProactiveMessage(action.template, action.params, action.button_payloads)
                    )
                    if action.to.contact_id == self.contact.id:
                        self._pressable.update(action.button_payloads)
                case NotifyOwner():
                    pass
            self.actions.append(action)

    def _check_proactive(self, action: SendProactive) -> None:
        template = action.template
        if template not in self.pack.templates:
            raise AssertionError(f"template {template.name} is not declared in pack.templates")
        if len(action.button_payloads) != len(template.buttons):
            raise AssertionError(f"template {template.name} has {len(template.buttons)} buttons")
        for payload in action.button_payloads:
            if not payload or len(payload.encode()) > MAX_ID_BYTES:
                raise AssertionError(f"button payload of {template.name} is empty or too long")
        n = len(action.params)
        expected = [f"{{{i}}}" for i in range(1, n + 1)]
        if any(p not in template.text for p in expected) or f"{{{n + 1}}}" in template.text:
            raise AssertionError(f"template {template.name} takes other parameters")

    def _lock(self, key: str) -> AbstractContextManager[None]:
        self.locks.append(key)
        return _no_lock()


@dataclass(frozen=True)
class _Snapshot:
    """What `replay` needs to undo a turn."""

    message: IncomingMessage
    event_id: UUID
    state: dict[str, Any]
    state_version: int | None
    last_inbound_at: datetime | None
    contact: ContactInfo
    actions: int
    turns: int
    pressable: frozenset[str]


@contextmanager
def _no_lock() -> Iterator[None]:
    yield


def _render(out: Outbound) -> None:
    for check in RENDER_CHECKS:
        check(out)


def _aware(at: str | datetime) -> datetime:
    return datetime.fromisoformat(at) if isinstance(at, str) else at


def _json_copy(state: dict[str, Any]) -> dict[str, Any]:
    """As PostgreSQL's jsonb stores it (which also rejects NaN)."""
    copied: dict[str, Any] = json.loads(json.dumps(state, allow_nan=False))
    return copied


def _through_json(reply: Reply) -> Reply:
    out = load_outbound(json.loads(json.dumps(dump_outbound(reply))))
    assert not isinstance(out, ProactiveMessage)
    return out
