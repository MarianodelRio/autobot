"""Graph API calls that finish connecting a tenant's WhatsApp number (ADR-016): the
app's webhook, the number's Cloud API registration and the app's subscription to the
WABA. Launched from the panel's "Alta" tab, never in a loop or a job.

Never echoes Meta's response bodies, the tokens, the PIN or the phone number: errors
carry only a short safe message. A write that may have reached Meta (a timeout after
connecting) is reported as `unknown` and never retried here.
"""

import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx
from django.conf import settings

from autobot.channels.whatsapp.adapter import GRAPH_URL
from autobot.tenancy.schema import WhatsAppChannel, WhatsAppSecrets

log = logging.getLogger(__name__)

TIMEOUT_S = 10
PIN = re.compile(r"[0-9]{6}")
_ENUM = re.compile(r"[A-Z_]{1,40}")


class RegistrationError(Exception):
    """`outcome`: "error" (Meta refused it or nothing was sent), "auth" (the token has
    no access) or "unknown" (a write that may or may not have reached Meta)."""

    def __init__(self, message: str, outcome: str = "error") -> None:
        super().__init__(message)
        self.message = message
        self.outcome = outcome


@dataclass(frozen=True)
class NumberStatus:
    registered: bool
    status: str | None
    name_status: str | None
    quality_rating: str | None


def webhook_url(channel: WhatsAppChannel) -> str:
    base = settings.PUBLIC_URL.rstrip("/")
    if not base:
        raise RegistrationError("Falta PUBLIC_URL en el servidor: no hay URL pública del webhook.")
    return f"{base}/webhooks/whatsapp/{channel.public_id}"


def _base() -> str:
    return f"{GRAPH_URL}/{settings.WHATSAPP_GRAPH_VERSION}"


def _id(value: str | None) -> str:
    if not value:
        raise RegistrationError("Faltan ids del canal.")
    return value


def _user_token(secrets: WhatsAppSecrets) -> dict[str, str]:
    return {"Authorization": f"Bearer {secrets.access_token.get_secret_value()}"}


def _app_token(channel: WhatsAppChannel, secrets: WhatsAppSecrets) -> dict[str, str]:
    token = f"{_id(channel.app_id)}|{secrets.app_secret.get_secret_value()}"
    return {"Authorization": f"Bearer {token}"}


def _refused(response: httpx.Response, message: str) -> RegistrationError:
    try:
        code = response.json().get("error", {}).get("code")
    except ValueError, AttributeError:
        code = None
    log.warning("WhatsApp registration call refused: %s %s", response.status_code, code)
    if response.status_code in (401, 403) or code == 190:
        return RegistrationError("Token de WhatsApp sin acceso a este recurso.", "auth")
    return RegistrationError(message)


def _get(url: str, headers: dict[str, str], params: dict[str, str] | None = None) -> Any:
    try:
        with httpx.Client(timeout=TIMEOUT_S) as client:
            response = client.get(url, headers=headers, params=params)
        if not response.is_success:
            raise _refused(response, "Consulta de Meta fallida.")
        return response.json()
    except httpx.HTTPError as e:
        log.warning("WhatsApp registration read failed: %s", type(e).__name__)
        raise RegistrationError("No se puede consultar Meta ahora mismo.") from None
    except ValueError:
        raise RegistrationError("Respuesta de Meta inválida.") from None


def _post(url: str, headers: dict[str, str], *, refused: str, **body: Any) -> None:
    try:
        with httpx.Client(timeout=TIMEOUT_S) as client:
            response = client.post(url, headers=headers, **body)
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as e:
        log.warning("WhatsApp registration write not connected: %s", type(e).__name__)
        raise RegistrationError("No se pudo conectar con Meta: no se ha enviado nada.") from None
    except httpx.HTTPError as e:
        log.warning("WhatsApp registration write ambiguous: %s", type(e).__name__)
        raise RegistrationError(
            "Resultado desconocido: pulsa «Comprobar» antes de repetirlo.", "unknown"
        ) from None
    if not response.is_success:
        raise _refused(response, refused)


def _enum(value: Any) -> str | None:
    return value if isinstance(value, str) and _ENUM.fullmatch(value) else None


def number_status(channel: WhatsAppChannel, secrets: WhatsAppSecrets) -> NumberStatus:
    data = _get(
        f"{_base()}/{_id(channel.phone_number_id)}",
        _user_token(secrets),
        {"fields": "status,platform_type,code_verification_status,name_status,quality_rating"},
    )
    if not isinstance(data, dict):
        raise RegistrationError("Respuesta de Meta inválida.")
    return NumberStatus(
        registered=data.get("platform_type") == "CLOUD_API",
        status=_enum(data.get("status")),
        name_status=_enum(data.get("name_status")),
        quality_rating=_enum(data.get("quality_rating")),
    )


def register_number(channel: WhatsAppChannel, secrets: WhatsAppSecrets, pin: str) -> bool:
    """True if registered now, False if it already was: Meta limits registration
    attempts, so it is never repeated on a registered number."""
    if not PIN.fullmatch(pin):
        raise ValueError("pin must be exactly 6 digits")
    if number_status(channel, secrets).registered:
        return False
    _post(
        f"{_base()}/{_id(channel.phone_number_id)}/register",
        _user_token(secrets),
        refused="Meta no ha aceptado el registro: revisa el PIN y que el número esté"
        " verificado en WhatsApp Manager.",
        json={"messaging_product": "whatsapp", "pin": pin},
    )
    return True


def app_subscribed(channel: WhatsAppChannel, secrets: WhatsAppSecrets) -> bool:
    data = _get(f"{_base()}/{_id(channel.waba_id)}/subscribed_apps", _user_token(secrets))
    try:
        ids = {row.get("whatsapp_business_api_data", {}).get("id") for row in data["data"]}
    except KeyError, TypeError, AttributeError:
        raise RegistrationError("Respuesta de Meta inválida.") from None
    return _id(channel.app_id) in ids


def subscribe_app(channel: WhatsAppChannel, secrets: WhatsAppSecrets) -> None:
    _post(
        f"{_base()}/{_id(channel.waba_id)}/subscribed_apps",
        _user_token(secrets),
        refused="Meta no ha aceptado la suscripción de la app a la cuenta.",
    )


def _field_names(fields: Any) -> set[Any]:
    if not isinstance(fields, list):
        return set()
    return {f.get("name") if isinstance(f, dict) else f for f in fields}


def app_webhook_status(channel: WhatsAppChannel, secrets: WhatsAppSecrets, url: str) -> bool:
    data = _get(f"{_base()}/{_id(channel.app_id)}/subscriptions", _app_token(channel, secrets))
    try:
        rows = data["data"]
        return any(
            row.get("object") == "whatsapp_business_account"
            and row.get("active") is True
            and row.get("callback_url") == url
            and "messages" in _field_names(row.get("fields"))
            for row in rows
        )
    except KeyError, TypeError, AttributeError:
        raise RegistrationError("Respuesta de Meta inválida.") from None


def configure_app_webhook(channel: WhatsAppChannel, secrets: WhatsAppSecrets, url: str) -> None:
    """Meta verifies `url` right away with a GET to our webhook, which answers 404
    until the tenant has its three ids and three secrets."""
    _post(
        f"{_base()}/{_id(channel.app_id)}/subscriptions",
        _app_token(channel, secrets),
        refused="Meta no ha aceptado el webhook: comprueba que el canal tiene los tres ids"
        " y los tres secretos y que la URL pública responde.",
        data={
            "object": "whatsapp_business_account",
            "callback_url": url,
            "verify_token": secrets.verify_token.get_secret_value(),
            "fields": "messages",
        },
    )
