"""Error classes of rejected sends: each adapter reads its own `last_error` formats."""

import pytest

from autobot.channels.base import ChannelType
from autobot.ops.send_errors import SendErrorClass, classify, describe


@pytest.mark.parametrize(
    ("last_error", "expected"),
    [
        # synchronous rejections ("{kind}: HTTP <status>, error <code>[/<subcode>]")
        ("other: HTTP 400, error 131047", "outside_window"),
        ("other: HTTP 400, error 131047/2494073", "outside_window"),
        ("recipient: HTTP 400, error 131026", "undeliverable"),
        ("recipient: HTTP 400, error 131021", "undeliverable"),
        ("recipient: HTTP 400, error 131030", "undeliverable"),
        ("other: HTTP 400, error 131049", "marketing_declined"),
        ("other: HTTP 400, error 131048", "spam_limit"),
        ("auth: HTTP 401, error 190", "auth"),
        ("auth: HTTP 401", "auth"),
        ("other: HTTP 429", "rate"),
        ("other: HTTP 400, error 130429", "rate"),
        ("other: HTTP 400, error 100", "other"),
        ("other: HTTP 400", "other"),
        # asynchronous `failed` statuses ("status failed: <codes>")
        ("status failed: 131047", "outside_window"),
        ("status failed: 131026", "undeliverable"),
        ("status failed: 131049", "marketing_declined"),
        ("status failed: 131048", "spam_limit"),
        ("status failed: 131000,131047", "outside_window"),
        ("status failed: 999999", "other"),
        ("status failed: ?", "other"),
    ],
)
def test_whatsapp_errors(last_error: str, expected: SendErrorClass) -> None:
    assert classify("whatsapp", last_error) == expected


@pytest.mark.parametrize(
    ("last_error", "expected"),
    [
        ("auth: HTTP 401, error 401", "auth"),
        ("recipient: HTTP 403, error 403", "blocked"),
        ("recipient: HTTP 403, error 403 (bot was blocked by the user)", "blocked"),
        ("recipient: HTTP 403, error 403 (user is deactivated)", "undeliverable"),
        (
            "recipient: HTTP 403, error 403 (bot can't initiate conversation with a user)",
            "undeliverable",
        ),
        ("other: HTTP 400, error 400 (chat not found)", "undeliverable"),
        ("other: HTTP 400, error 400", "other"),
        ("other: HTTP 429", "rate"),
        ("HTTP 502", "other"),
    ],
)
def test_telegram_errors(last_error: str, expected: SendErrorClass) -> None:
    assert classify("telegram", last_error) == expected


@pytest.mark.parametrize("channel", ["whatsapp", "telegram"])
@pytest.mark.parametrize(
    ("last_error", "expected"),
    [
        ("other: payload expired", "expired_payload"),
        ("other: main channel disabled", "channel_disabled"),
        ("other: channel has no phone_number_id", "channel_disabled"),
        ("retry later (rate)", "rate"),
        ("auth: anything", "auth"),
        ("interrupted while sending", "other"),
        ("expired before it could be delivered", "other"),
        ("", "other"),
    ],
)
def test_internal_texts_are_the_same_on_both_channels(
    channel: ChannelType, last_error: str, expected: SendErrorClass
) -> None:
    assert classify(channel, last_error) == expected


def test_every_class_has_spanish_text_and_other_carries_the_code() -> None:
    classes: list[SendErrorClass] = [
        "outside_window",
        "undeliverable",
        "blocked",
        "auth",
        "rate",
        "marketing_declined",
        "spam_limit",
        "expired_payload",
        "channel_disabled",
        "other",
    ]
    for cls in classes:
        info = describe(cls)
        assert info.cls == cls and info.title and info.advice.endswith(".")
    assert describe("outside_window").advice.startswith("Fuera de la ventana de 24 h")
    assert describe("other", "other: HTTP 400, error 100").advice == (
        "Rechazado por el proveedor (código 100)."
    )
    assert describe("other", "status failed: 999").advice.endswith("(código 999).")
    assert describe("other", "other: HTTP 400").advice == "Rechazado por el proveedor."
