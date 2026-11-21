"""Phone matching between contacts (it decides opt-out by phone number)."""

import pytest

from autobot.runtime.identity import phone_group
from autobot.runtime.models import Contact
from autobot.tenancy.tx import tenant_tx
from tests.platform.test_models import tenant

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])


def make(t, external_id: str, phone: str | None = None, channel: str = "main") -> Contact:  # type: ignore[no-untyped-def]
    return Contact.objects.using("owner").create(
        tenant=t, channel=channel, external_id=external_id, phone_e164=phone
    )


def ids(t, phone: str, **kwargs) -> list[str]:  # type: ignore[no-untyped-def]
    with tenant_tx(t.id):
        return [c.external_id for c in phone_group(t.id, phone, **kwargs)]


def test_a_number_matches_its_contacts_by_any_written_form() -> None:
    t = tenant("identity-a")
    make(t, "34600112233")
    make(t, "ES.abc123", phone="+34600112233")  # BSUID with a verified phone
    make(t, "34611000000")
    expected = ["34600112233", "ES.abc123"]
    for form in ("600112233", "+34 600 11 22 33", "34600112233"):
        assert sorted(ids(t, form)) == sorted(expected)


def test_old_contacts_stored_without_the_country_prefix_match() -> None:
    t = tenant("identity-b")
    make(t, "600112233")
    assert ids(t, "+34600112233") == ["600112233"]


def test_no_digits_means_no_group() -> None:
    t = tenant("identity-c")
    make(t, "34600112233")
    assert ids(t, "") == []
    assert ids(t, "sin número") == []


def test_other_channels_and_tenants_are_not_in_the_group() -> None:
    t, other = tenant("identity-d"), tenant("identity-e")
    make(t, "34600112233", channel="demo_wa")
    make(other, "34600112233")
    assert ids(t, "34600112233") == []
