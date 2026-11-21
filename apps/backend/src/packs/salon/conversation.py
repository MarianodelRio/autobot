"""Salon state machine on PackContext; JSON state, no channel or database imports."""

import re
from collections.abc import Callable, Mapping
from datetime import date, time
from typing import Any

from core.actions import NotifyOwner, UpdateContact
from core.dates import format_date_es
from core.errors import PermanentError, TransientError
from core.limits import MAX_ID_BYTES
from core.messages import IncomingMessage
from core.pack import PackContext, PackResult
from core.replies import Reply, Text
from core.text import fold, normalize
from core.ui import button, buttons_msg, row
from packs.salon import booking
from packs.salon import interactive as ui
from packs.salon.config import SalonConfig
from packs.salon.messages import booking_text, owner_notice
from packs.salon.ownership import belongs
from packs.salon.parser import parse_name, parse_service_title
from packs.salon.slots import split_periods

# Words that are never a name: they leave the booking and go back to the menu.
_ESCAPE_WORDS = frozenset(
    {
        "cancelar",
        "cancela",
        "cancelo",
        "volver",
        "vuelve",
        "atras",
        "salir",
        "sal",
        "no",
        "nada",
        "menu",
        "inicio",
        "hola",
        "buenas",
        "adios",
        "gracias",
        "ayuda",
        "stop",
    }
)
# Steps that wait for a choice among options shown: text there re-shows the step.
_TAKES_TEXT = frozenset({"BOOK_NAME", "CANCEL_CONFIRM"})  # their handlers read free text
_CHOICE_STEPS = frozenset(
    {
        "BOOK_SERVICE",
        "BOOK_DAY",
        "BOOK_PERIOD",
        "BOOK_HOUR",
        "MOVE_SELECT",
        "CANCEL_SELECT",
        "CANCEL_CONFIRM",
    }
)


def clean_name(raw: str) -> str:
    """The name as it will be stored: no markup characters or line breaks, one space."""
    return " ".join(re.sub(r"[*_`~\r\n\t]", " ", raw).split())


def expects_free_text(state: Mapping[str, Any]) -> bool:
    """The name step: `alta`/`baja` there are a name, not opt-in/out commands."""
    return state.get("step") == "BOOK_NAME"


class Turn:
    def __init__(self, ctx: PackContext) -> None:
        self.ctx = ctx
        self.cfg = booking.configuration(ctx)
        self.state: dict[str, Any] = dict(ctx.state)

    def result(self, reply: Reply, *, reset: bool = False) -> PackResult:
        return PackResult(replies=[reply], state={} if reset else self.state)

    def menu(self) -> PackResult:
        return self.result(ui.menu(self.cfg), reset=True)

    def event_mode(self) -> bool:
        return self.state.get("mode") == "event"

    def days(self, page: int = 0, *, refresh: bool = False) -> PackResult:
        if refresh:
            self.state["days"] = [
                d.isoformat()
                for d in booking.available_days(
                    self.ctx,
                    self.state["service"],
                    event=self.event_mode(),
                    exclude=self.state.get("move_source"),
                )
            ]
        self.state["step"] = "BOOK_DAY"
        if not self.state.get("days"):
            text = f"{self.cfg.texts.no_days}\n📞 {self.cfg.contact_phone}"
            return self.result(ui.back(text), reset=True)
        rows = [
            row(f"day_{d}", format_date_es(date.fromisoformat(d)).capitalize())
            for d in self.state["days"]
        ]
        return self.result(
            ui.listing("Selecciona el día para tu cita:", rows, page=page, prefix="days_page")
        )

    def hours(
        self, *, refresh: bool = False, period: str | None = None, page: int = 0
    ) -> PackResult:
        day = date.fromisoformat(self.state["day"])
        if refresh:
            available, ranges = booking.availability(
                self.ctx,
                day,
                self.state["service"],
                event=self.event_mode(),
                exclude=self.state.get("move_source"),
            )
            self.state["all_slots"] = [slot.strftime("%H:%M") for slot in available]
            self.state["ranges"] = ranges
        slots = [time.fromisoformat(s) for s in self.state.get("all_slots", [])]
        if not slots:
            result = self.days(refresh=True)
            if self.state.get("days"):  # the chosen day filled up; others remain
                result.replies.insert(0, Text(self.cfg.texts.no_slots))
            return result
        morning, afternoon = split_periods(
            slots, self.state.get("ranges", self.cfg.spans(day, event=self.event_mode()))
        )
        if len(slots) > 8 and morning and afternoon and period is None:
            self.state["step"] = "BOOK_PERIOD"
            return self.result(
                buttons_msg(
                    "¿Prefieres mañana o tarde?",
                    [
                        button("period_morning", "Mañana"),
                        button("period_afternoon", "Tarde"),
                        button("back_to_day", "📅 Cambiar día"),
                    ],
                    footer=ui.FOOTER_STEP,
                )
            )
        selected = morning if period == "morning" else afternoon if period == "afternoon" else slots
        self.state.update(
            step="BOOK_HOUR", slots=[s.strftime("%H:%M") for s in selected], period=period
        )
        rows = [row(f"hour_{s:%H:%M}", f"🕒 {s:%H:%M}") for s in selected]
        return self.result(
            ui.listing(
                "Selecciona la hora:", rows, page=page, prefix="hours_page", back_id="back_to_day"
            )
        )

    def owns(self, event: Any) -> bool:
        contact = self.ctx.contact
        assert contact is not None
        return bool(
            event is not None
            and not event.all_day
            and belongs(
                event,
                str(contact.id),
                contact.phone,
                contact.external_id,
                [str(key) for key in contact.alias_ids],
            )
        )

    def appointments(self, mode: str, page: int = 0, *, refresh: bool = True) -> PackResult:
        if refresh:
            events = booking.contact_events(self.ctx)
            self.state = {
                "step": f"{mode.upper()}_SELECT",
                "appointments": [e.gcal_id for e in events],
                "appointment_labels": [f"{e.start:%d/%m/%Y %H:%M}" for e in events],
            }
        if not self.state["appointments"]:
            return self.result(ui.back(self.cfg.texts.no_bookings), reset=True)
        rows = [
            row(f"{mode}_appt:{i}", label)
            for i, label in enumerate(self.state["appointment_labels"])
        ]
        return self.result(
            ui.listing("¿Qué cita quieres elegir?", rows, page=page, prefix=f"{mode}_page")
        )

    def cancel(self, gcal_id: str) -> PackResult:
        if self.ctx.effects is None:
            raise PermanentError("Cancellation requires an effect journal")
        key, authorization = f"cancel:{gcal_id}", {"target": gcal_id}
        previous = self.ctx.effects.get(key)
        event = booking.calendar(self.ctx).get_event(gcal_id)
        notice = "Cita cancelada"
        if event is not None:
            if not self.owns(event):
                return self.result(ui.back(self.cfg.texts.missing), reset=True)
            if event.start < self.ctx.clock.now():
                return self.result(ui.back(self.cfg.texts.past_booking), reset=True)
            service_key, _ = parse_service_title(
                event.summary, {k: s.name for k, s in self.cfg.services.items()}
            )
            service_name = self.cfg.services[service_key].name if service_key else "cita"
            client_name = parse_name(event.description) or "Cliente"
            notice = owner_notice(
                "❌ Cita cancelada", client_name, f"{service_name} · {event.start:%d/%m %H:%M}"
            )
            # Record verified ownership before deletion, in a separate short transaction.
            self.ctx.effects.put(key, authorization)
            booking.calendar(self.ctx).cancel_event(gcal_id)
        elif previous != authorization:
            return self.result(ui.back(self.cfg.texts.missing), reset=True)
        result = self.result(ui.back(self.cfg.texts.cancelled), reset=True)
        result.actions.append(
            NotifyOwner(
                "booking_cancelled",
                notice,
                self.ctx.idem.event("notify:booking_cancelled"),
            )
        )
        return result

    def ask_cancel(self, gcal_id: str) -> PackResult:
        """A tap on an appointment never cancels it by itself: ask first."""
        event = booking.calendar(self.ctx).get_event(gcal_id)
        if not self.owns(event):
            return self.result(ui.back(self.cfg.texts.missing), reset=True)
        assert event is not None
        if event.start < self.ctx.clock.now():
            return self.result(ui.back(self.cfg.texts.past_booking), reset=True)
        service_key, _ = parse_service_title(
            event.summary, {k: s.name for k, s in self.cfg.services.items()}
        )
        service_name = self.cfg.services[service_key].name if service_key else "tu cita"
        label = f"{service_name} del {format_date_es(event.start.date())} a las {event.start:%H:%M}"
        self.state = {"step": "CANCEL_CONFIRM", "target": gcal_id, "label": label}
        return self.result(ui.confirm_cancel(label))

    def proactive(self, value: str) -> PackResult:
        operation, _, gcal_id = value.partition(":")
        if not gcal_id or len(value.encode()) > MAX_ID_BYTES:
            return self.result(ui.back(self.cfg.texts.missing), reset=True)
        if operation != "reminder_confirm":
            return self.cancel(gcal_id)
        event = booking.calendar(self.ctx).get_event(gcal_id)
        if not self.owns(event):
            return self.result(ui.back(self.cfg.texts.missing), reset=True)
        booking.calendar(self.ctx).patch_description(gcal_id, {"Estado": "confirmada"})
        return self.result(ui.back(self.cfg.texts.confirmed), reset=True)

    def create(self, name: str) -> PackResult:
        day, slot = date.fromisoformat(self.state["day"]), time.fromisoformat(self.state["slot"])
        moving = self.state.get("move_source")
        if moving:
            source = booking.calendar(self.ctx).get_event(moving)
            if source is not None and not self.owns(source):
                return self.result(ui.back(self.cfg.texts.missing), reset=True)
            if (
                source is None
                and booking.calendar(self.ctx).get_event(booking.event_id(self.ctx, "move")) is None
            ):
                return self.result(ui.back(self.cfg.texts.missing), reset=True)
        try:
            event = booking.reserve(
                self.ctx,
                day,
                slot,
                self.state["service"],
                name,
                event=self.event_mode(),
                operation="move" if moving else "booking",
                exclude=moving,
            )
        except booking.SlotTaken:
            result = self.hours(refresh=True)
            result.replies.insert(0, ui.back(self.cfg.texts.slot_taken))
            return result
        prefix = self.cfg.texts.moved if moving else self.cfg.texts.confirmed
        kind = "booking_moved" if moving else "booking_created"
        cancel_failed = False
        if moving:
            try:
                booking.calendar(self.ctx).cancel_event(moving)
            except PermanentError, TransientError:
                cancel_failed = True
                self.ctx.log.warning("Move created; source cancellation failed")
        svc = self.cfg.services[self.state["service"]]
        when = f"{event.start:%d/%m %H:%M}"
        if moving and source is not None:
            detail = f"{svc.name} · {source.start:%d/%m %H:%M} → {when}"
        else:
            detail = f"{svc.name} · {when}"
        title = "🔄 Cita movida" if moving else "✅ Nueva cita"
        result = self.result(
            ui.back(booking_text(prefix, svc.name, svc.price_eur, event.start)), reset=True
        )
        result.actions = [
            UpdateContact(display_name=name),
            NotifyOwner(
                kind,
                owner_notice(title, name, detail),
                self.ctx.idem.event(f"notify:{kind}"),
            ),
        ]
        if cancel_failed:
            result.replies.append(Text(self.cfg.texts.move_cancel_failed))
            old_when = f"{source.start:%d/%m %H:%M}" if source is not None else "la cita anterior"
            result.actions.append(
                NotifyOwner(
                    "move_cancel_failed",
                    owner_notice(
                        "⚠️ Revisar",
                        name,
                        f"nueva cita {svc.name} · {when}; no se pudo cancelar la anterior "
                        f"({old_when})",
                    ),
                    self.ctx.idem.event("notify:move_cancel_failed"),
                )
            )
        return result

    def handle(self, message: IncomingMessage) -> PackResult:
        assert self.ctx.contact is not None
        value = message.payload or ""
        step = self.state.get("step", "MENU")
        if message.type == "unsupported":
            if step == "BOOK_NAME":
                return self._name_prompt(self.cfg.texts.name_text_only)
            result = self._redisplay()
            result.replies.insert(0, Text(self.cfg.texts.unsupported))
            return result
        if value == "back_to_menu":
            return self.menu()
        if message.type == "text" and step not in _TAKES_TEXT:
            return self._text_reply(step)
        handler = _STEPS.get(step)
        return handler(self, message, value) if handler else self.menu()

    def _text_reply(self, step: str) -> PackResult:
        """Free text where a choice is expected."""
        if step in _CHOICE_STEPS:
            # Not a menu word: keep the contact's progress and show the step again.
            result = self._redisplay()
            result.replies.insert(0, Text(self.cfg.texts.list_hint))
            return result
        return self.menu()

    def _on_menu(self, message: IncomingMessage, value: str) -> PackResult:
        if value in ("menu_cancel", "menu_move"):
            return self.appointments(value.removeprefix("menu_"))
        if value == "menu_info" and self.cfg.info_text:
            result = self.result(ui.back("¿Necesitas algo más?"), reset=True)
            result.replies.insert(0, Text(self.cfg.info_text))
            return result
        if value in ("menu_book", "menu_book_event"):
            return self._start_booking(event=value == "menu_book_event")
        return self.menu()

    def _start_booking(self, *, event: bool) -> PackResult:
        if event and not self.cfg.special_event.active:
            return self.menu()
        try:
            count = len(booking.contact_events(self.ctx))
        except TransientError, PermanentError:
            count = 0  # Deliberately fails open, only on the limit check.
        if count >= self.cfg.max_active_bookings:
            return self.result(
                ui.back(
                    f"Ya tienes {self.cfg.max_active_bookings} citas reservadas, que es el máximo."
                ),
                reset=True,
            )
        self.state = {"step": "BOOK_SERVICE", "mode": "event" if event else "book"}
        return self.result(ui.services(self.cfg))

    def _on_select(self, message: IncomingMessage, value: str) -> PackResult:
        mode = "cancel" if self.state["step"] == "CANCEL_SELECT" else "move"
        if value.startswith(f"{mode}_page:"):
            return self.appointments(mode, int(value.rsplit(":", 1)[1]), refresh=False)
        if not value.startswith(f"{mode}_appt:"):
            return self.menu()
        raw_index = value.rsplit(":", 1)[1]
        if not raw_index.isdecimal() or len(raw_index) > 4:
            return self.menu()
        index = int(raw_index)
        if index >= len(self.state["appointments"]):
            return self.menu()
        gcal_id = self.state["appointments"][index]
        if mode == "cancel":
            return self.ask_cancel(gcal_id)
        return self._select_appointment(gcal_id)

    def _select_appointment(self, gcal_id: str) -> PackResult:
        """The contact picked an appointment to move: start the booking flow for it."""
        source = booking.calendar(self.ctx).get_event(gcal_id)
        if not self.owns(source):
            return self.result(ui.back(self.cfg.texts.missing), reset=True)
        assert source is not None
        if source.start < self.ctx.clock.now():
            return self.result(ui.back(self.cfg.texts.past_booking), reset=True)
        _, title_name = parse_service_title(
            source.summary, {k: s.name for k, s in self.cfg.services.items()}
        )
        in_event = (
            source.start.date() in self.cfg.special_event.days and self.cfg.special_event.active
        )
        self.state = {
            "step": "BOOK_SERVICE",
            "mode": "event" if in_event else "move",
            "move_source": gcal_id,
            # A manual appointment whose title isn't "<Servicio> - <Nombre>" keeps
            # its original title instead of becoming "<Servicio> - Cliente": it is
            # found the same way either way (fp_contact, waid or phone), and the
            # title change is otherwise only cosmetic.
            "move_name": parse_name(source.description)
            or title_name
            or source.summary
            or "Cliente",
        }
        return self.result(ui.services(self.cfg))

    def _on_cancel_confirm(self, message: IncomingMessage, value: str) -> PackResult:
        if value == "cancel_yes" and isinstance(self.state.get("target"), str):
            return self.cancel(self.state["target"])
        if value == "cancel_no":
            return self.result(ui.back(self.cfg.texts.cancel_kept), reset=True)
        return self._text_reply("CANCEL_CONFIRM") if message.type == "text" else self.menu()

    def _on_service(self, message: IncomingMessage, value: str) -> PackResult:
        if not value.startswith("service_"):
            return self.menu()
        key = value.removeprefix("service_")
        if key not in self.cfg.services:
            return self.menu()
        self.state["service"] = key
        return self.days(refresh=True)

    def _on_day(self, message: IncomingMessage, value: str) -> PackResult:
        if value.startswith("days_page:"):
            return self.days(int(value.split(":")[1]))
        day = value.removeprefix("day_")
        if day not in self.state.get("days", []):
            return self.menu()
        # The list may have been shown before midnight: a day already gone has no
        # slot left (`compute_slots` filters by `now`) and `hours()` would notice
        # and refresh anyway, but checking first skips that Calendar round-trip.
        if date.fromisoformat(day) < self.ctx.clock.now().date():
            return self.days(refresh=True)
        self.state["day"] = day
        return self.hours(refresh=True)

    def _on_period(self, message: IncomingMessage, value: str) -> PackResult:
        if value == "back_to_day":
            return self.days(refresh=True)
        if value in ("period_morning", "period_afternoon"):
            return self.hours(period=value.removeprefix("period_"))
        return self.menu()

    def _on_hour(self, message: IncomingMessage, value: str) -> PackResult:
        if value == "back_to_day":
            return self.days(refresh=True)
        if value.startswith("hours_page:"):
            return self.hours(period=self.state.get("period"), page=int(value.split(":")[1]))
        slot = value.removeprefix("hour_")
        if slot not in self.state.get("slots", []):
            return self.menu()
        self.state.update(step="BOOK_NAME", slot=slot)
        if self.state.get("move_source"):
            return self.create(self.state.get("move_name", "Cliente"))
        return self._name_prompt()

    def _known_name(self) -> str | None:
        assert self.ctx.contact is not None
        known = clean_name(self.ctx.contact.display_name or "")
        return known if self._name_problem(known) is None else None

    @staticmethod
    def _name_problem(name: str) -> str | None:
        """Why `name` cannot be used (None if it can). `[cfg]` would forge a calendar
        configuration event; escape words are the contact trying to leave."""
        if not 2 <= len(name) <= 100 or "[cfg]" in fold(name):
            return "Escribe un nombre de entre 2 y 100 caracteres."
        if not any(c.isalpha() for c in name):
            return "El nombre debe incluir al menos una letra. Escríbelo de nuevo."
        return None

    def _name_prompt(self, notice: str | None = None) -> PackResult:
        text = self.cfg.texts.name_prompt
        return self.result(
            ui.name_prompt(f"{notice}\n\n{text}" if notice else text, self._known_name())
        )

    def _on_name(self, message: IncomingMessage, value: str) -> PackResult:
        if value == "use_name":
            raw = self._known_name() or ""
            if not raw:
                return self._name_prompt()
        elif message.type == "text":
            raw = message.text or ""
        else:
            return self._name_prompt(self.cfg.texts.name_text_only)
        name = clean_name(raw)
        if normalize(name) in _ESCAPE_WORDS:
            return self.menu()
        problem = self._name_problem(name)
        if problem:
            return self._name_prompt(problem)
        return self.create(name)

    def _redisplay(self) -> PackResult:
        """Re-show the current step's own prompt, instead of dropping the contact's
        progress back to the menu, when the message itself could not be understood
        (a photo or audio: `message.type == "unsupported"`)."""
        step = self.state.get("step", "MENU")
        if step == "BOOK_SERVICE":
            return self.result(ui.services(self.cfg))
        if step == "BOOK_DAY":
            return self.days()
        if step == "BOOK_PERIOD":
            return self.hours()
        if step == "BOOK_HOUR":
            return self.hours(period=self.state.get("period"))
        if step == "BOOK_NAME":
            return self._name_prompt()
        if step in ("MOVE_SELECT", "CANCEL_SELECT"):
            return self.appointments(step.removesuffix("_SELECT").lower(), refresh=False)
        if step == "CANCEL_CONFIRM":
            return self.result(ui.confirm_cancel(self.state["label"]))
        return self.menu()


# Step -> handler of what the contact sent there. Handlers see the message and its payload.
_STEPS: dict[str, Callable[[Turn, IncomingMessage, str], PackResult]] = {
    "MENU": Turn._on_menu,
    "BOOK_SERVICE": Turn._on_service,
    "BOOK_DAY": Turn._on_day,
    "BOOK_PERIOD": Turn._on_period,
    "BOOK_HOUR": Turn._on_hour,
    "BOOK_NAME": Turn._on_name,
    "MOVE_SELECT": Turn._on_select,
    "CANCEL_SELECT": Turn._on_select,
    "CANCEL_CONFIRM": Turn._on_cancel_confirm,
}


def _is_strings(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _valid_select(state: Mapping[str, Any], cfg: SalonConfig) -> bool:
    return (
        _is_strings(state.get("appointments"))
        and _is_strings(state.get("appointment_labels"))
        and len(state["appointments"]) == len(state["appointment_labels"])
    )


def _valid_confirm(state: Mapping[str, Any], cfg: SalonConfig) -> bool:
    return isinstance(state.get("target"), str) and isinstance(state.get("label"), str)


def _valid_day(state: Mapping[str, Any], cfg: SalonConfig) -> bool:
    return (
        state["service"] in cfg.services
        and isinstance(state["days"], list)
        and all(isinstance(d, str) and date.fromisoformat(d) for d in state["days"])
    )


def _times_ok(state: Mapping[str, Any], *keys: str) -> bool:
    return all(time.fromisoformat(slot) for key in keys for slot in state[key])


def _valid_period(state: Mapping[str, Any], cfg: SalonConfig) -> bool:
    date.fromisoformat(state["day"])
    return state["service"] in cfg.services and _times_ok(state, "all_slots")


def _valid_hour(state: Mapping[str, Any], cfg: SalonConfig) -> bool:
    date.fromisoformat(state["day"])
    return state["service"] in cfg.services and _times_ok(state, "all_slots", "slots")


def _valid_name(state: Mapping[str, Any], cfg: SalonConfig) -> bool:
    date.fromisoformat(state["day"])
    return state["service"] in cfg.services and bool(time.fromisoformat(state["slot"]))


def _always(state: Mapping[str, Any], cfg: SalonConfig) -> bool:
    return True


# Step -> check that the stored state has what the step needs (it comes from JSON that
# may be stale or damaged). A step missing here is invalid.
_VALIDATORS: dict[str, Callable[[Mapping[str, Any], SalonConfig], bool]] = {
    "MENU": _always,
    "BOOK_SERVICE": _always,
    "MOVE_SELECT": _valid_select,
    "CANCEL_SELECT": _valid_select,
    "CANCEL_CONFIRM": _valid_confirm,
    "BOOK_DAY": _valid_day,
    "BOOK_PERIOD": _valid_period,
    "BOOK_HOUR": _valid_hour,
    "BOOK_NAME": _valid_name,
}


def valid_state(turn: Turn) -> bool:
    validator = _VALIDATORS.get(turn.state.get("step", "MENU"))
    if validator is None:
        return False
    try:
        return validator(turn.state, turn.cfg)
    except KeyError, ValueError, TypeError:
        return False


def handle(ctx: PackContext, message: IncomingMessage) -> PackResult:
    turn = Turn(ctx)
    if message.payload and message.payload.partition(":")[0] in (
        "reminder_confirm",
        "reminder_cancel",
        "booking_cancel",
    ):
        return turn.proactive(message.payload)
    if turn.state.get("mode") == "event" and not turn.cfg.special_event.active:
        return turn.menu()
    if not valid_state(turn):
        return turn.menu()
    # Parse callback pages separately: service failures and programming errors must
    # reach the runtime's recovery/retry handling instead of being hidden as navigation.
    if message.payload and "_page:" in message.payload:
        page = message.payload.rsplit(":", 1)[-1]
        if not page.isdecimal() or len(page) > 4:
            return turn.menu()
    return turn.handle(message)
