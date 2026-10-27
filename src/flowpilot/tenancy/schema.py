"""Common schema of `tenants/<slug>/tenant.yaml` and of each tenant's secrets.
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
    type: Literal["whatsapp"]
    public_id: str = Field(pattern=PUBLIC_ID)
    # Meta ids may be missing while the number is being set up: the main channel stays
    # disabled until they are all there.
    app_id: str | None = Field(default=None, pattern=META_ID)
    waba_id: str | None = Field(default=None, pattern=META_ID)
    phone_number_id: str | None = Field(default=None, pattern=META_ID)
    display_phone: str | None = None
    monthly_alert_threshold: int = Field(default=2000, gt=0)

    @property
    def complete(self) -> bool:
        return all((self.app_id, self.waba_id, self.phone_number_id))


class TelegramChannel(Strict):
    type: Literal["telegram"]
    public_id: str = Field(pattern=PUBLIC_ID)
    bot_username: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_]{5,32}$")

    @property
    def complete(self) -> bool:
        return bool(self.bot_username)


Channel = Annotated[WhatsAppChannel | TelegramChannel, Field(discriminator="type")]


class Testers(Strict):
    main: list[str] = []  # in onboarding, the only ids answered on the main channel

    @field_validator("main", mode="before")
    @classmethod
    def ids_as_text(cls, value: Any) -> Any:
        # Telegram ids are written as integers in YAML.
        return [str(v) for v in value] if isinstance(value, list) else value


class Owner(Strict):
    telegram_chat_id: int | None = None
    notify: list[str] = []
    summary_monthly: bool = False

    @model_validator(mode="after")
    def _summary_needs_chat(self) -> Owner:
        if self.summary_monthly and self.telegram_chat_id is None:
            raise ValueError("summary_monthly needs telegram_chat_id")
        return self


class DemoInfo(Strict):
    # Shown under the business name in the demo selector; 72 is WhatsApp's row
    # description limit.
    description: str = Field(min_length=1, max_length=72)


class TenantFile(Strict):
    """The common part of tenant.yaml; `config` is checked later by the pack."""

    id: UUID
    slug: str = Field(pattern=SLUG, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    status: Status
    timezone: str
    pack: str
    channel: Channel | None = None
    testers: Testers = Testers()
    owner: Owner | None = None
    demo: DemoInfo | None = None
    config: dict[str, Any] = {}

    @field_validator("id")
    @classmethod
    def uuid_v7(cls, value: UUID) -> UUID:
        if value.version != 7:
            raise ValueError("id must be a UUIDv7 (manage.py new_tenant generates it)")
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
    def demo_or_channel(self) -> TenantFile:
        if self.demo is not None:
            if self.channel is not None:
                raise ValueError("a demo tenant must not have a channel")
            if self.testers.main:
                raise ValueError("a demo tenant must not have testers.main")
            if self.status not in ("active", "paused"):
                raise ValueError("a demo tenant's status must be active or paused")
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
