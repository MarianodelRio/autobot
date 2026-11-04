"""`autobot.tenancy.links.channel_link`; `tests/tools/test_qr.py` covers the full
edge cases through `tools.qr`, which re-exports it."""

from autobot.tenancy.links import channel_link
from autobot.tenancy.schema import TelegramChannel, WhatsAppChannel


def test_whatsapp_link() -> None:
    channel = WhatsAppChannel(
        type="whatsapp", public_id="testpubid", display_phone="+34 600 12 34 56"
    )
    assert channel_link(channel) == "https://wa.me/34600123456"


def test_telegram_link() -> None:
    channel = TelegramChannel(type="telegram", public_id="testpubid", bot_username="business_bot")
    assert channel_link(channel) == "https://t.me/business_bot"
