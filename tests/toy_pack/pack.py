"""A toy pack that exercises the conversation harness and the runtime. Only used in tests;
never registered in `packs.registry`."""

from pydantic import BaseModel

from core.actions import Action, ContactRef, NotifyOwner, SendProactive
from core.errors import TransientError
from core.messages import IncomingMessage
from core.pack import Pack, PackContext, PackResult, Periodic
from core.proactive import TemplateSpec
from core.replies import Text
from core.ui import button, buttons_msg, list_msg, paginate, row, section

TEMPLATE_THANKS = TemplateSpec(
    name="toy_thanks",
    language="es_ES",
    text="Gracias por elegir {1}. ¿Te ha gustado?",
    buttons=["Sí"],
)


class ToyConfig(BaseModel):
    greeting: str = "¡Hola!"
    colors: list[str] = ["Rojo", "Verde", "Azul"]


def menu(ctx: PackContext) -> PackResult:
    config = ctx.config
    assert isinstance(config, ToyConfig)
    return PackResult(
        replies=[
            buttons_msg(
                f"{config.greeting} ¿Qué quieres hacer?",
                [
                    button("greet", "Saludar"),
                    button("color", "Elegir color"),
                    button("fail", "Probar error"),
                ],
            )
        ],
        state={},
    )


def handle(ctx: PackContext, msg: IncomingMessage) -> PackResult:
    config = ctx.config
    assert isinstance(config, ToyConfig)
    step = ctx.state.get("step")

    if msg.type == "unsupported":
        result = menu(ctx)
        return PackResult(
            replies=[Text("Solo entiendo texto y botones."), *result.replies], state={}
        )

    if step == "ask_name" and msg.type == "text" and msg.text:
        name = msg.text.strip()
        result = menu(ctx)
        notify = NotifyOwner("greeted", f"Nuevo saludo de {name}", ctx.idem.event("notify:greeted"))
        return PackResult(
            replies=[Text(f"¡Encantado, *{name}*!"), *result.replies], state={}, actions=[notify]
        )

    match msg.payload:
        case "greet":
            return PackResult(replies=[Text("¿Cómo te llamas?")], state={"step": "ask_name"})
        case "color":
            rows = [row(f"pick_{i}", c) for i, c in enumerate(config.colors)]
            page = paginate(rows, 0, more_id="more_colors", back_id="menu")
            return PackResult(
                replies=[list_msg("Elige un color", "Ver colores", [section("Colores", page)])],
                state={"step": "color"},
            )
        case str(p) if p.startswith("pick_") and step == "color":
            color = config.colors[int(p.removeprefix("pick_"))]
            assert ctx.contact is not None
            thanks = SendProactive(
                to=ContactRef(contact_id=ctx.contact.id),
                template=TEMPLATE_THANKS,
                params=[color],
                button_payloads=["thanks_yes"],
                idem_key=ctx.idem.event("thanks"),
            )
            return PackResult(replies=[Text(f"Has elegido {color}.")], state={}, actions=[thanks])
        case "thanks_yes":
            return PackResult(replies=[Text("¡Me alegro!")])
        case "fail":
            raise TransientError("toy failure")
        case _:
            return menu(ctx)


def daily_summary(ctx: PackContext) -> list[Action]:
    day = ctx.clock.now().date().isoformat()
    return [NotifyOwner("daily", "Resumen del día", ctx.idem.stable(f"daily:{day}"))]


pack = Pack(
    name="toy",
    config_schema=ToyConfig,
    state_version=1,
    handle_message=handle,
    periodic=[Periodic("daily_summary", every_min=1440, handler=daily_summary)],
    templates=[TEMPLATE_THANKS],
)
