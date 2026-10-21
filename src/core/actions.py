"""What a pack wants to happen besides replying (design.md §8.2)."""

from dataclasses import dataclass
from uuid import UUID

from core.proactive import TemplateSpec


@dataclass(frozen=True)
class ContactRef:
    """An existing contact, or a phone with no contact yet (manual bookings, §9.6)."""

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


@dataclass(frozen=True)
class NotifyOwner:
    kind: str
    text: str
    idem_key: str


@dataclass(frozen=True)
class UpdateContact:
    display_name: str | None = None
    opt_out: bool | None = None


type Action = SendProactive | NotifyOwner | UpdateContact
