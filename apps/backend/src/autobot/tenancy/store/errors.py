"""Store errors and the validation helpers every write shares."""

from typing import Any

from pydantic import ValidationError
from pydantic_core import ErrorDetails

from autobot.tenancy.schema import TenantDocument

# The identity of a tenant: what a publish or an import may never change.
IDENTITY = (
    ("id",),
    ("slug",),
    ("pack",),
    ("status",),
    ("channel", "type"),
    ("channel", "public_id"),
)


class StoreError(Exception):
    def __init__(self, code: str, message: str, details: list[str] | None = None) -> None:
        self.code, self.message, self.details = code, message, details or []
        super().__init__(message)


# Pydantic's own error type → a short, generic Spanish message. `value_error`
# (a pack's or the schema's own `raise ValueError(...)`, already written in Spanish)
# keeps its message instead, since it is the only type with business meaning.
_TYPE_MESSAGES: dict[str, str] = {
    "missing": "falta este campo",
    "string_type": "debe ser un texto",
    "string_too_short": "es demasiado corto",
    "string_too_long": "es demasiado largo",
    "string_pattern_mismatch": "no tiene el formato esperado",
    "int_type": "debe ser un número entero",
    "int_parsing": "debe ser un número entero",
    "float_type": "debe ser un número",
    "bool_type": "debe ser verdadero o falso",
    "list_type": "debe ser una lista",
    "too_short": "tiene muy pocos elementos",
    "too_long": "tiene demasiados elementos",
    "dict_type": "debe ser un objeto",
    "extra_forbidden": "campo no reconocido",
    "literal_error": "valor no permitido",
    "greater_than": "debe ser mayor que el mínimo",
    "greater_than_equal": "debe ser mayor o igual que el mínimo",
    "less_than": "debe ser menor que el máximo",
    "less_than_equal": "debe ser menor o igual que el máximo",
    "uuid_parsing": "no es un identificador válido",
    "date_parsing": "no es una fecha válida",
    "datetime_parsing": "no es una fecha y hora válidas",
    "url_parsing": "no es una URL válida",
    "union_tag_invalid": "tipo no reconocido",
    "union_tag_not_found": "falta el campo que indica el tipo",
}


def _message(item: ErrorDetails) -> str:
    if item["type"] == "value_error":
        # "Value error, <custom message>" → "<custom message>" (the message a pack's
        # or the schema's own validator raised, already in Spanish).
        return str(item["msg"]).removeprefix("Value error, ")
    return _TYPE_MESSAGES.get(item["type"], "valor no válido")


def validation_error(error: ValidationError, prefix: str = "") -> StoreError:
    details = [
        f"{prefix}{'.'.join(str(part) for part in item['loc']) or '(root)'}: {_message(item)}"
        for item in error.errors(include_input=False, include_context=False)
    ]
    return StoreError("validation_error", "La configuración no es válida", details)


def validated_document(raw: dict[str, Any]) -> dict[str, Any]:
    try:
        return TenantDocument.model_validate(raw).model_dump(mode="json")
    except ValidationError as error:
        raise validation_error(error) from None


def value_at(document: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = document
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    return value


def identity_changed(new: dict[str, Any], current: dict[str, Any]) -> bool:
    return any(value_at(new, path) != value_at(current, path) for path in IDENTITY)
