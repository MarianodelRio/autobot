"""Salon state machine on PackContext; JSON state, no channel or database imports."""

from datetime import date, time
from typing import Any

from core.actions import NotifyOwner, UpdateContact
from core.dates import format_date_es
from core.errors import PermanentError, TransientError
from core.messages import IncomingMessage
from core.pack import PackContext, PackResult
from core.replies import Reply
from core.ui import button, buttons_msg, row
from packs.salon import booking
from packs.salon import interactive as ui
from packs.salon.messages import booking_text
from packs.salon.slots import split_periods


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
                    self.ctx, self.state["service"], event=self.event_mode()
                )
            ]
        self.state["step"] = "BOOK_DAY"
        if not self.state.get("days"):
            return self.result(ui.back(self.cfg.texts.no_slots), reset=True)
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
            self.state["all_slots"] = [
                s.strftime("%H:%M")
                for s in booking.day_slots(
                    self.ctx, day, self.state["service"], event=self.event_mode()
                )
            ]
        slots = [time.fromisoformat(s) for s in self.state.get("all_slots", [])]
        if not slots:
            return self.days(refresh=True)
        morning, afternoon = split_periods(slots, self.cfg.spans(day, event=self.event_mode()))
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
                    footer=ui.FOOTER,
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

    def create(self, name: str) -> PackResult:
        day, slot = date.fromisoformat(self.state["day"]), time.fromisoformat(self.state["slot"])
        try:
            event = booking.reserve(
                self.ctx, day, slot, self.state["service"], name, event=self.event_mode()
            )
        except booking.SlotTaken:
            result = self.hours(refresh=True)
            result.replies.insert(0, ui.back(self.cfg.texts.slot_taken))
            return result
        svc = self.cfg.services[self.state["service"]]
        result = self.result(
            ui.back(booking_text(self.cfg.texts.confirmed, svc.name, svc.price_eur, event.start)),
            reset=True,
        )
        result.actions = [
            UpdateContact(display_name=name),
            NotifyOwner(
                "booking_created",
                f"Nueva cita: {svc.name}, {event.start:%d/%m %H:%M}",
                self.ctx.idem.event("notify:booking_created"),
            ),
        ]
        return result

    def handle(self, message: IncomingMessage) -> PackResult:
        assert self.ctx.contact is not None
        value = message.payload or ""
        step = self.state.get("step", "MENU")
        if message.type == "unsupported":
            return self.result(ui.back(self.cfg.texts.name_text_only))
        if value == "back_to_menu":
            return self.menu()
        if step == "BOOK_NAME":
            if value == "use_name":
                name = self.ctx.contact.display_name or ""
            elif message.type == "text":
                name = message.text or ""
            else:
                return self.result(ui.back(self.cfg.texts.name_text_only))
            name = name.strip().replace("\n", " ").replace("\r", "")
            if not 2 <= len(name) <= 100:
                return self.result(ui.back("Escribe un nombre de entre 2 y 100 caracteres."))
            return self.create(name)
        if message.type == "text":
            return self.menu()
        if step == "MENU" and value == "menu_book":
            try:
                count = len(booking.contact_events(self.ctx))
            except TransientError, PermanentError:
                count = 0  # The source bot deliberately fails open only on the limit check.
            if count >= self.cfg.max_active_bookings:
                return self.result(
                    ui.back(
                        f"Ya tienes {self.cfg.max_active_bookings} citas reservadas, "
                        "que es el máximo."
                    ),
                    reset=True,
                )
            self.state = {"step": "BOOK_SERVICE", "mode": "book"}
            return self.result(ui.services(self.cfg))
        if step == "BOOK_SERVICE" and value.startswith("service_"):
            key = value.removeprefix("service_")
            if key not in self.cfg.services:
                return self.menu()
            self.state["service"] = key
            return self.days(refresh=True)
        if step == "BOOK_DAY":
            if value.startswith("days_page:"):
                return self.days(int(value.split(":")[1]))
            day = value.removeprefix("day_")
            if day not in self.state.get("days", []):
                return self.menu()
            self.state["day"] = day
            return self.hours(refresh=True)
        if value == "back_to_day" and step in ("BOOK_HOUR", "BOOK_PERIOD"):
            return self.days(refresh=True)
        if step == "BOOK_PERIOD" and value in ("period_morning", "period_afternoon"):
            return self.hours(period=value.removeprefix("period_"))
        if step == "BOOK_HOUR":
            if value.startswith("hours_page:"):
                return self.hours(period=self.state.get("period"), page=int(value.split(":")[1]))
            slot = value.removeprefix("hour_")
            if slot not in self.state.get("slots", []):
                return self.menu()
            self.state.update(step="BOOK_NAME", slot=slot)
            if self.ctx.contact.display_name and 2 <= len(self.ctx.contact.display_name) <= 100:
                return self.result(
                    buttons_msg(
                        self.cfg.texts.name_prompt,
                        [button("use_name", f"Usar {self.ctx.contact.display_name}")],
                        footer=ui.FOOTER,
                    )
                )
            return self.result(ui.back(self.cfg.texts.name_prompt))
        return self.menu()


def valid_state(turn: Turn) -> bool:
    state = turn.state
    step = state.get("step", "MENU")
    if step in ("MENU", "BOOK_SERVICE"):
        return True
    if step not in ("BOOK_DAY", "BOOK_PERIOD", "BOOK_HOUR", "BOOK_NAME"):
        return False
    try:
        if state["service"] not in turn.cfg.services:
            return False
        if step == "BOOK_DAY":
            return isinstance(state["days"], list) and all(
                isinstance(d, str) and date.fromisoformat(d) for d in state["days"]
            )
        date.fromisoformat(state["day"])
        if step == "BOOK_NAME":
            time.fromisoformat(state["slot"])
        else:
            for slot in state["all_slots"]:
                time.fromisoformat(slot)
            if step == "BOOK_HOUR":
                for slot in state["slots"]:
                    time.fromisoformat(slot)
        return True
    except KeyError, ValueError, TypeError:
        return False


def handle(ctx: PackContext, message: IncomingMessage) -> PackResult:
    turn = Turn(ctx)
    if not valid_state(turn):
        return turn.menu()
    # Parse callback pages separately: service failures and programming errors must
    # reach the runtime's recovery/retry handling instead of being hidden as navigation.
    if message.payload and "_page:" in message.payload:
        page = message.payload.rsplit(":", 1)[-1]
        if not page.isdecimal() or len(page) > 4:
            return turn.menu()
    return turn.handle(message)
