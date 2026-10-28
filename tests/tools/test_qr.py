"""Public channel links and actual offline SVG generation for both channel types."""

from pathlib import Path
from xml.etree import ElementTree

import pytest

from autobot.tenancy.schema import TelegramChannel, WhatsAppChannel
from tests.tenancy.helpers import demo_tenant_yaml, tenant_yaml, write_tenants
from tools.qr import channel_link, main, tenant_link


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


@pytest.mark.parametrize("kind", ["whatsapp", "telegram"])
def test_cli_generates_real_svg_without_services(tmp_path: Path, kind: str) -> None:
    doc = tenant_yaml("local")
    if kind == "whatsapp":
        doc["channel"]["display_phone"] = "+34 600 12 34 56"
    else:
        doc["channel"] = {
            "type": "telegram",
            "public_id": "testpubid",
            "bot_username": "business_bot",
        }
        doc["testers"]["main"] = ["100000001"]
    write_tenants(tmp_path, doc)
    # No secrets file, Django setup or DB is needed for local public QR generation.
    assert main(["local"], repo_root=tmp_path) == 0
    svg = ElementTree.parse(tmp_path / "qr" / "local.svg").getroot()
    assert svg.tag == "{http://www.w3.org/2000/svg}svg"
    assert svg.find("{http://www.w3.org/2000/svg}path") is not None
    assert svg.find("{http://www.w3.org/2000/svg}rect").attrib["fill"] == "white"  # type: ignore[union-attr]


def test_unknown_or_mismatched_tenant_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        tenant_link("missing", tmp_path)
    tenants = write_tenants(tmp_path, tenant_yaml("real"))
    (tenants / "real").rename(tenants / "other")
    with pytest.raises(ValueError, match="no coincide"):
        tenant_link("other", tenants)
    with pytest.raises(ValueError, match="inválido"):
        tenant_link("../real", tenants)


def test_demo_tenant_has_no_channel_to_link(tmp_path: Path) -> None:
    tenants = write_tenants(tmp_path, demo_tenant_yaml("demo-a"))
    with pytest.raises(ValueError, match="no tiene canal propio"):
        tenant_link("demo-a", tenants)


def test_custom_output_and_svg_extension(tmp_path: Path) -> None:
    doc = tenant_yaml("local")
    doc["channel"]["display_phone"] = "+34 600 12 34 56"
    write_tenants(tmp_path, doc)
    output = tmp_path / "print" / "code.svg"
    assert main(["local", "--output", str(output)], repo_root=tmp_path) == 0
    assert output.is_file()
    with pytest.raises(SystemExit) as error:
        main(["local", "--output", str(tmp_path / "code.png")], repo_root=tmp_path)
    assert error.value.code == 2
