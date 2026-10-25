"""Salon state machine on PackContext; JSON state, no channel or database imports."""

from datetime import date, time
from typing import Any

from core.actions import NotifyOwner, UpdateContact
from core.dates import format_date_es
from core.errors import PermanentError, TransientError
from core.messages import IncomingMessage
from core.pack import PackContext, PackResult
from core.replies import Reply, Text
from core.ui import button, buttons_msg, row
from packs.salon import booking
from packs.salon import interactive as ui
from packs.salon.messages import booking_text
from packs.salon.ownership import belongs
from packs.salon.parser import parse_name, parse_service_title
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
            available, ranges = booking.availability(
                self.ctx, day, self.state["service"], event=self.event_mode()
            )
            self.state["all_slots"] = [slot.strftime("%H:%M") for slot in available]
            self.state["ranges"] = ranges
        slots = [time.fromisoformat(s) for s in self.state.get("all_slots", [])]
        if not slots:
            return self.days(refresh=True)
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
                "step": "VIEW" if mode == "view" else f"{mode.upper()}_SELECT",
                "appointments": [e.gcal_id for e in events],
                "appointment_labels": [f"{e.start:%d/%m/%Y %H:%M}" for e in events],
            }
        if not self.state["appointments"]:
            return self.result(ui.back(self.cfg.texts.no_bookings), reset=True)
        if mode == "view":
            labels = self.state["appointment_labels"]
            if page < 0 or page * 8 >= len(labels):
                page = 0
            text = "Tus próximas citas:\n" + "\n".join(labels[page * 8 : (page + 1) * 8])
            buttons = [button("back_to_menu", "↩️ Volver al menú")]
            if (page + 1) * 8 < len(labels):
                buttons.insert(0, button(f"view_page:{page + 1}", "➡️ Ver más"))
            return self.result(buttons_msg(text, buttons, footer=ui.FOOTER))
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
        if event is not None:
            if not self.owns(event):
                return self.result(ui.back(self.cfg.texts.missing), reset=True)
            # Record verified ownership before deletion, in a separate short transaction.
            self.ctx.effects.put(key, authorization)
            booking.calendar(self.ctx).cancel_event(gcal_id)
        elif previous != authorization:
            return self.result(ui.back(self.cfg.texts.missing), reset=True)
        result = self.result(ui.back(self.cfg.texts.cancelled), reset=True)
        result.actions.append(
            NotifyOwner(
                "booking_cancelled",
                "Cita cancelada",
                self.ctx.idem.event("notify:booking_cancelled"),
            )
        )
        return result

    def proactive(self, value: str) -> PackResult:
        operation, _, gcal_id = value.partition(":")
        if not gcal_id or len(value.encode()) > 64:
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
        result = self.result(
            ui.back(booking_text(prefix, svc.name, svc.price_eur, event.start)), reset=True
        )
        result.actions = [
            UpdateContact(display_name=name),
            NotifyOwner(
                kind,
                f"{svc.name}, {event.start:%d/%m %H:%M}",
                self.ctx.idem.event(f"notify:{kind}"),
            ),
        ]
        if cancel_failed:
            result.replies.append(Text(self.cfg.texts.move_cancel_failed))
            result.actions.append(
                NotifyOwner(
                    "move_cancel_failed",
                    "Nueva cita creada; revisar cancelación de la anterior",
                    self.ctx.idem.event("notify:move_cancel_failed"),
                )
            )
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
        if step == "MENU" and value in ("menu_view", "menu_cancel", "menu_move"):
            return self.appointments(value.removeprefix("menu_"))
        if step == "MENU" and value == "menu_info" and self.cfg.info_text:
            result = self.result(ui.back("¿Necesitas algo más?"), reset=True)
            result.replies.insert(0, Text(self.cfg.info_text))
            return result
        if step == "MENU" and value in ("menu_book", "menu_book_event"):
            if value == "menu_book_event" and not self.cfg.special_event.active:
                return self.menu()
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
            self.state = {
                "step": "BOOK_SERVICE",
                "mode": "event" if value == "menu_book_event" else "book",
            }
            return self.result(ui.services(self.cfg))
        if step == "VIEW" and value.startswith("view_page:"):
            return self.appointments("view", int(value.rsplit(":", 1)[1]), refresh=False)
        if step in ("CANCEL_SELECT", "MOVE_SELECT"):
            mode = "cancel" if step == "CANCEL_SELECT" else "move"
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
                return self.cancel(gcal_id)
            source = booking.calendar(self.ctx).get_event(gcal_id)
            if not self.owns(source):
                return self.result(ui.back(self.cfg.texts.missing), reset=True)
            assert source is not None
            _, title_name = parse_service_title(
                source.summary, {k: s.name for k, s in self.cfg.services.items()}
            )
            self.state = {
                "step": "BOOK_SERVICE",
                "mode": "event"
                if source.start.date() in self.cfg.special_event.days
                and self.cfg.special_event.active
                else "move",
                "move_source": gcal_id,
                "move_name": parse_name(source.description) or title_name or "Cliente",
            }
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
            if self.state.get("move_source"):
                return self.create(self.state.get("move_name", "Cliente"))
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
    if step in ("VIEW", "MOVE_SELECT", "CANCEL_SELECT"):
        return (
            isinstance(state.get("appointments"), list)
            and isinstance(state.get("appointment_labels"), list)
            and len(state["appointments"]) == len(state["appointment_labels"])
            and all(isinstance(item, str) for item in state["appointments"])
            and all(isinstance(item, str) for item in state["appointment_labels"])
        )
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
