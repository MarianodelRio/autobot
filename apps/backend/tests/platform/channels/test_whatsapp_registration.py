"""The error paths of `whatsapp/registration.py`'s Graph calls: what Meta refusing,
being unreachable or answering garbage becomes. Never the response body, never a token."""

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from autobot.channels.whatsapp import registration
from autobot.channels.whatsapp.registration import RegistrationError

URL = "https://graph.facebook.com/v1/123"
HEADERS = {"Authorization": "Bearer secret-token"}
REAL_CLIENT = httpx.Client  # before any test patches it


def use_transport(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> None:
    def client(**kwargs: Any) -> httpx.Client:
        return REAL_CLIENT(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "Client", client)


def answer(status: int, body: Any = None) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(status, json=body)


def raises(error: Exception) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    return handler


def test_get_returns_the_json(monkeypatch: pytest.MonkeyPatch) -> None:
    use_transport(monkeypatch, answer(200, {"status": "CONNECTED"}))
    assert registration._get(URL, HEADERS) == {"status": "CONNECTED"}


@pytest.mark.parametrize(
    ("status", "body", "outcome"),
    [
        (400, {"error": {"code": 100}}, "error"),
        (500, None, "error"),
        (400, {"error": "not an object"}, "error"),  # no code to read: still refused
        (401, {"error": {"code": 190}}, "auth"),
        (403, {}, "auth"),
        (400, {"error": {"code": 190}}, "auth"),
    ],
)
def test_get_refusals(
    monkeypatch: pytest.MonkeyPatch, status: int, body: Any, outcome: str
) -> None:
    use_transport(monkeypatch, answer(status, body))
    with pytest.raises(RegistrationError) as error:
        registration._get(URL, HEADERS)
    assert error.value.outcome == outcome
    assert "secret-token" not in error.value.message


def test_get_unreachable_and_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    use_transport(monkeypatch, raises(httpx.ConnectError("no route")))
    with pytest.raises(RegistrationError, match="No se puede consultar"):
        registration._get(URL, HEADERS)
    use_transport(monkeypatch, lambda request: httpx.Response(200, content=b"<html>"))
    with pytest.raises(RegistrationError, match="inválida"):
        registration._get(URL, HEADERS)


def test_post_success(monkeypatch: pytest.MonkeyPatch) -> None:
    use_transport(monkeypatch, answer(200, {"success": True}))
    registration._post(URL, HEADERS, refused="No", json={"pin": "123456"})


def test_post_refused_uses_the_callers_message(monkeypatch: pytest.MonkeyPatch) -> None:
    use_transport(monkeypatch, answer(400, {"error": {"code": 100, "message": "PIN 123456"}}))
    with pytest.raises(RegistrationError) as error:
        registration._post(URL, HEADERS, refused="Meta no acepta el registro.", json={})
    assert error.value.message == "Meta no acepta el registro."
    assert error.value.outcome == "error"
    assert "123456" not in error.value.message


def test_post_auth_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    use_transport(monkeypatch, answer(401, {"error": {"code": 190}}))
    with pytest.raises(RegistrationError) as error:
        registration._post(URL, HEADERS, refused="No", json={})
    assert error.value.outcome == "auth"


def test_post_not_connected_means_nothing_was_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    use_transport(monkeypatch, raises(httpx.ConnectTimeout("slow")))
    with pytest.raises(RegistrationError) as error:
        registration._post(URL, HEADERS, refused="No", json={})
    assert error.value.outcome == "error"
    assert "no se ha enviado nada" in error.value.message


def test_post_timeout_after_connecting_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    use_transport(monkeypatch, raises(httpx.ReadTimeout("slow")))
    with pytest.raises(RegistrationError) as error:
        registration._post(URL, HEADERS, refused="No", json={})
    assert error.value.outcome == "unknown"
