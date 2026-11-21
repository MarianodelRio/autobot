"""`autobot.tenancy.links.channel_link`: the public link of a channel, for both types.
`tests/tools/test_qr.py` only covers the QR generation built on top of it."""

import pytest

from autobot.tenancy.links import channel_link
from autobot.tenancy.schema import TelegramChannel, WhatsAppChannel


@pytest.mark.parametrize("phone", ["+34 600 12 34 56", "34600123456", "+34 (600) 123-456"])
def test_whatsapp_link_uses_public_phone(phone: str) -> None:
    channel = WhatsAppChannel(
        type="whatsapp", public_id="testpubid", phone_number_id="9988776655", display_phone=phone
    )
    assert channel_link(channel) == "https://wa.me/34600123456"


def test_telegram_link_uses_business_bot() -> None:
    channel = TelegramChannel(type="telegram", public_id="testpubid", bot_username="business_bot")
    assert channel_link(channel) == "https://t.me/business_bot"


@pytest.mark.parametrize(
    "phone", [None, "", "0034600123456", "+0001234567", "123", "+34foo600123456", "+" + "1" * 16]
)
def test_missing_or_invalid_public_phone_is_rejected(phone: str | None) -> None:
    with pytest.raises(ValueError):
        channel_link(WhatsAppChannel(type="whatsapp", public_id="testpubid", display_phone=phone))


def test_missing_telegram_username_is_rejected() -> None:
    with pytest.raises(ValueError):
        channel_link(TelegramChannel(type="telegram", public_id="testpubid"))
