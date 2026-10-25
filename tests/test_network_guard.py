"""The whole suite is offline; local PostgreSQL sockets and HTTP doubles still work."""

import socket

import httpx
import pytest


@pytest.mark.parametrize("lookup", ["getaddrinfo", "gethostbyname", "gethostbyname_ex"])
def test_external_dns_is_blocked(lookup: str) -> None:
    with pytest.raises(pytest.fail.Exception, match="External network disabled"):
        if lookup == "getaddrinfo":
            socket.getaddrinfo("api.telegram.org", 443)
        else:
            getattr(socket, lookup)("api.telegram.org")


@pytest.mark.parametrize("method", ["connect", "connect_ex"])
def test_direct_external_connection_is_blocked(method: str) -> None:
    with (
        socket.socket() as client,
        pytest.raises(pytest.fail.Exception, match="External network disabled"),
    ):
        getattr(client, method)(("203.0.113.1", 443))


def test_loopback_sockets_still_work() -> None:
    assert socket.getaddrinfo("localhost", 5432)
    with socket.socket() as server, socket.socket() as client:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        client.connect(server.getsockname())
        accepted, address = server.accept()
        accepted.close()
        assert address[0] == "127.0.0.1"


def test_http_mock_transport_still_works() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))
    with httpx.Client(transport=transport) as client:
        assert client.get("https://api.telegram.org/simulated").json() == {"ok": True}
