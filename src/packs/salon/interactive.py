"""Common reply builders, ported from Peluqueria/utils/interactive."""

from collections.abc import Sequence

from core.replies import Buttons, List, Row
from core.ui import button, buttons_msg, list_msg, paginate, row, section, trunc
from packs.salon.config import SalonConfig

FOOTER = "Cualquier texto te llevará de vuelta al menú principal"


def back(text: str) -> Buttons:
    return buttons_msg(text, [button("back_to_menu", "↩️ Volver al menú")], footer=FOOTER)


def menu(cfg: SalonConfig) -> List:
    return listing(
        cfg.texts.welcome + f"\n📞 {cfg.contact_phone}",
        [row("menu_book", "📅 Pedir cita")],
        header=trunc(f"✂️ {cfg.business_name}", 60),
    )


def listing(
    body: str,
    rows: Sequence[Row],
    *,
    page: int = 0,
    prefix: str = "page",
    back_id: str = "back_to_menu",
    header: str | None = None,
) -> List:
    return list_msg(
        body,
        "Ver opciones",
        [section(None, paginate(rows, page, more_id=f"{prefix}:{page + 1}", back_id=back_id))],
        header=header,
        footer=FOOTER,
    )


def services(cfg: SalonConfig) -> List:
    rows = [
        row(f"service_{key}", s.name, f"{s.price_eur:g} €" if s.price_eur is not None else None)
        for key, s in cfg.services.items()
    ]
    # Up to nine services plus back, without pagination.
    return list_msg(
        "¿Qué servicio quieres?",
        "Ver servicios",
        [section(None, [*rows, row("back_to_menu", "↩️ Volver al menú")])],
        footer=FOOTER,
    )
