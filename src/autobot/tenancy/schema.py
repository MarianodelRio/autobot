"""Common schema of versioned tenant documents and channel secrets.
The `config` section is validated by the pack's own schema."""

import re
from typing import Annotated, Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

SLUG = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
PUBLIC_ID = r"^[a-z0-9]{8,32}$"
META_ID = r"^\d{1,32}$"
BSUID = re.compile(r"^[A-Z]{2}\.[A-Za-z0-9]{1,128}$")
PHONE = re.compile(r"^\d{7,15}$")
TELEGRAM_ID = re.compile(r"^\d{1,20}$")

Status = Literal["onboarding", "active", "paused", "offboarded"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WhatsAppChannel(Strict):
    type: Literal["whatsapp"] = Field(title="Tipo de canal")
    public_id: str = Field(
        pattern=PUBLIC_ID, title="Identificador público", description="Parte de la URL del webhook."
    )
    # Meta ids may be missing while the number is being set up: the main channel stays
    # disabled until they are all there.
    app_id: str | None = Field(default=None, pattern=META_ID, title="Id de la app de Meta")
    waba_id: str | None = Field(
        default=None, pattern=META_ID, title="Id de la cuenta de WhatsApp Business"
    )
    phone_number_id: str | None = Field(
        default=None, pattern=META_ID, title="Id del número de teléfono (Meta)"
    )
    display_phone: str | None = Field(
        default=None,
        title="Teléfono público",
        description="Número internacional mostrado en el enlace y el QR (wa.me/<número>).",
    )
    monthly_alert_threshold: int = Field(
        default=2000,
        gt=0,
        title="Umbral de aviso mensual",
        description="Mensajes facturables al mes a partir del cual se avisa.",
    )

    @property
    def complete(self) -> bool:
        return all((self.app_id, self.waba_id, self.phone_number_id))


class TelegramChannel(Strict):
    type: Literal["telegram"] = Field(title="Tipo de canal")
    public_id: str = Field(
        pattern=PUBLIC_ID, title="Identificador público", description="Parte de la URL del webhook."
    )
    bot_username: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9_]{5,32}$",
        title="Usuario del bot",
        description="Sin la @; forma el enlace público (t.me/<usuario>).",
    )

    @property
    def complete(self) -> bool:
        return bool(self.bot_username)


Channel = Annotated[WhatsAppChannel | TelegramChannel, Field(discriminator="type")]


class Testers(Strict):
    main: list[str] = Field(
        default=[],
        title="Testers del canal principal",
        description="Los únicos ids que pueden escribir por el canal principal durante el alta.",
    )

    @field_validator("main", mode="before")
    @classmethod
    def ids_as_text(cls, value: Any) -> Any:
        # Telegram ids are written as integers in YAML.
        return [str(v) for v in value] if isinstance(value, list) else value


class Owner(Strict):
    notify: list[str] = Field(
        default=[],
        title="Avisos al dueño",
        description="Tipos de aviso que recibe por su chat enlazado (p. ej. una cita nueva).",
    )
    summary_monthly: bool = Field(default=False, title="Resumen mensual automático")


class DemoInfo(Strict):
    # Shown under the business name in the demo selector; 72 is WhatsApp's row
    # description limit.
    description: str = Field(
        min_length=1,
        max_length=72,
        title="Descripción en el selector de demos",
        description="Se muestra bajo el nombre del negocio al elegir la demo.",
    )


class TenantDocument(Strict):
    """The common tenant document; `config` is checked later by the pack."""

    id: UUID = Field(title="Identificador")
    slug: str = Field(pattern=SLUG, max_length=64, title="Slug")
    name: str = Field(min_length=1, max_length=200, title="Nombre del negocio")
    status: Status = Field(title="Estado")
    timezone: str = Field(title="Zona horaria", description="Nombre IANA, p. ej. Europe/Madrid.")
    pack: str = Field(title="Pack")
    channel: Channel | None = Field(default=None, title="Canal")
    testers: Testers = Field(default=Testers(), title="Testers")
    owner: Owner | None = Field(default=None, title="Dueño")
    demo: DemoInfo | None = Field(default=None, title="Demo")
    config: dict[str, Any] = Field(default={}, title="Configuración del pack")

    @field_validator("id")
    @classmethod
    def uuid_v7(cls, value: UUID) -> UUID:
        if value.version != 7:
            raise ValueError("id must be a UUIDv7")
        return value

    @field_validator("timezone")
    @classmethod
    def known_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError, ValueError:
            raise ValueError(f"unknown time zone {value!r}") from None
        return value

    @model_validator(mode="after")
    def demo_or_channel(self) -> TenantDocument:
        if self.demo is not None:
            if self.channel is not None:
                raise ValueError("a demo tenant must not have a channel")
            if self.testers.main:
                raise ValueError("a demo tenant must not have testers.main")
            if self.status not in ("active", "paused", "offboarded"):
                raise ValueError("a demo tenant's status must be active, paused or offboarded")
            return self
        if self.channel is None:
            raise ValueError("channel is required for a non-demo tenant")
        if self.channel.type == "whatsapp":
            wrong = [i for i in self.testers.main if not (BSUID.match(i) or PHONE.match(i))]
            kind = "a BSUID or a phone number (digits only)"
        else:
            wrong = [i for i in self.testers.main if not TELEGRAM_ID.match(i)]
            kind = "a Telegram user id"
        if wrong:
            raise ValueError(f"testers.main must hold {kind} for a {self.channel.type} channel")
        return self


class WhatsAppSecrets(Strict):
    app_secret: SecretStr
    access_token: SecretStr
    verify_token: SecretStr


class TelegramSecrets(Strict):
    bot_token: SecretStr
    webhook_secret: SecretStr = Field(min_length=32)


type ChannelSecrets = WhatsAppSecrets | TelegramSecrets

SECRETS_SCHEMA: dict[str, type[WhatsAppSecrets] | type[TelegramSecrets]] = {
    "whatsapp": WhatsAppSecrets,
    "telegram": TelegramSecrets,
}
