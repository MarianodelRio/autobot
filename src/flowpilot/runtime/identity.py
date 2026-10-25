"""Verified phone relationships, queried only within the caller's tenant_tx."""

import re
from uuid import UUID

from django.db.models import Q

from flowpilot.runtime.models import Channel, Contact
from flowpilot.tenancy.schema import BSUID


def phone_key(value: str | None) -> str:
    digits = re.sub(r"\D", "", value or "")
    return "34" + digits if len(digits) == 9 else digits


def phone_group(tenant_id: UUID, phone: str, *, lock: bool = False) -> list[Contact]:
    digits = phone_key(phone)
    if not digits:
        return []
    numbers = [digits]
    if digits.startswith("34") and len(digits) == 11:
        numbers.append(digits[2:])
    query = Contact.objects.filter(tenant_id=tenant_id, channel=Channel.MAIN)
    if lock:
        query = query.select_for_update()
    return list(
        query.filter(Q(phone_e164=f"+{digits}") | Q(external_id__in=numbers)).order_by("id")
    )


def aliases_for(contact: Contact) -> tuple[UUID, ...]:
    if (
        contact.channel != Channel.MAIN
        or not contact.phone_e164
        or not BSUID.fullmatch(contact.external_id)
    ):
        return ()
    group = phone_group(contact.tenant_id, contact.phone_e164)
    scoped = [c for c in group if BSUID.fullmatch(c.external_id)]
    if len(scoped) != 1 or scoped[0].id != contact.id:
        return ()
    number = phone_key(contact.phone_e164)
    return tuple(
        c.id for c in group if c.external_id.isdecimal() and phone_key(c.external_id) == number
    )
