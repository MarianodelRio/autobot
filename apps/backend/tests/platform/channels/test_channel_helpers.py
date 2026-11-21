"""Small shared helpers of the channel layer: HTTP outcome parsing, the adapters' synthetic
text messages and the demo outbound-owner cache."""

import math
from uuid import uuid7

import httpx
import pytest

from autobot.channels.adapters import TELEGRAM, WHATSAPP
from autobot.channels.base import InboundItem
from autobot.channels.http_outcome import MAX_RETRY_AFTER_S, clamp_retry_after, safe_json_dict
from autobot.runtime.cache import SELECTOR_OWNER, demo_outbound_owner, remember_demo_outbound


@pytest.mark.parametrize(
    ("value", "expected"),
    [(5, 5), (0, 0), (-1, None), (math.nan, None), (math.inf, None), (10**9, MAX_RETRY_AFTER_S)],
)
def test_clamp_retry_after(value: float, expected: float | None) -> None:
    assert clamp_retry_after(value) == expected


def test_safe_json_dict() -> None:
    assert safe_json_dict(httpx.Response(200, json={"a": 1})) == {"a": 1}
    assert safe_json_dict(httpx.Response(200, json=[1])) == {}
    assert safe_json_dict(httpx.Response(200, content=b"nope")) == {}


def test_telegram_synthetic_text_parses_back_as_the_same_person() -> None:
    update = {
        "update_id": 7,
        "callback_query": {
            "id": "cb",
            "from": {"id": 42, "first_name": "Ana"},
            "data": "fp_select:x",
            "message": {"chat": {"id": 42, "type": "private"}, "message_id": 1, "date": 1},
        },
    }
    (item,) = TELEGRAM.parse(TELEGRAM.synthetic_text(update, "menu"), None)
    assert isinstance(item, InboundItem)
    assert (item.external_id, item.message.type, item.message.text) == ("42", "text", "menu")


def test_whatsapp_synthetic_text_keeps_only_the_sender() -> None:
    from autobot.tenancy.schema import WhatsAppChannel

    channel = WhatsAppChannel(
        type="whatsapp", public_id="testpubid", phone_number_id="111", display_phone="+34600123456"
    )
    body = {
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": "111"},
                            "messages": [
                                {
                                    "from": "34600123456",
                                    "id": "wamid.1",
                                    "timestamp": "1700000000",
                                    "type": "interactive",
                                    "interactive": {"type": "list_reply"},
                                }
                            ],
                        },
                    }
                ]
            }
        ]
    }
    (item,) = WHATSAPP.parse(WHATSAPP.synthetic_text(body, "menu"), channel)
    assert isinstance(item, InboundItem)
    assert (item.external_id, item.message.text) == ("34600123456", "menu")


@pytest.mark.django_db
def test_demo_outbound_owner_roundtrip() -> None:
    tenant, mine, unknown = uuid7(), uuid7(), uuid7()
    remember_demo_outbound(mine, tenant)
    assert demo_outbound_owner(mine) == tenant
    selector = uuid7()
    remember_demo_outbound(selector, None)
    assert demo_outbound_owner(selector) == SELECTOR_OWNER
    assert demo_outbound_owner(unknown) is None
