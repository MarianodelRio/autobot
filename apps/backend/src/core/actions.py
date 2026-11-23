"""What a pack wants to happen besides replying."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from core.proactive import TemplateSpec


@dataclass(frozen=True)
class ContactRef:
    """An existing contact, or a phone with no contact yet (manual bookings)."""

    contact_id: UUID | None = None
    phone: str | None = None

    def __post_init__(self) -> None:
        if (self.contact_id is None) == (self.phone is None):
            raise ValueError("ContactRef needs exactly one of contact_id or phone")


@dataclass(frozen=True)
class SendProactive:
    to: ContactRef
    template: TemplateSpec
    params: list[str]
    button_payloads: list[str]
    idem_key: str
    # Latest moment at which the message is still useful (a reminder after the appointment
    # has started is not); an aware datetime. The platform stops retrying at the earlier of
    # this and its own 24 h limit (ADR-024).
    not_after: datetime | None = None


@dataclass(frozen=True)
class NotifyOwner:
    kind: str
    text: str
    idem_key: str


@dataclass(frozen=True)
class UpdateContact:
    display_name: str | None = None
    opt_out: bool | None = None


@dataclass(frozen=True)
class RecordMetric:
    """A business event for the owner's periodic summary (`autobot.runtime.summary`)."""

    kind: str
    idem_key: str
    value: Decimal = Decimal(1)


type Action = SendProactive | NotifyOwner | UpdateContact | RecordMetric
