"""Event ownership, including the original bot's WaId/Telefono fields."""

from collections.abc import Sequence

from packs.salon.parser import parse_external_id, parse_phone
from packs.salon.ports import CalEvent


def phone_key(value: str | None) -> str:
    import re

    digits = re.sub(r"\D", "", value or "")
    return "34" + digits if len(digits) == 9 else digits


def belongs(
    event: CalEvent,
    contact_id: str,
    phone: str | None,
    external_id: str | None,
    alias_ids: Sequence[str] = (),
) -> bool:
    owner = event.private.get("fp_contact")
    if owner:
        return owner in (contact_id, *alias_ids)
    legacy = parse_external_id(event.description)
    number = parse_phone(event.description)
    return bool(
        (legacy and external_id and legacy == external_id)
        or (number and phone and phone_key(number) == phone_key(phone))
    )
