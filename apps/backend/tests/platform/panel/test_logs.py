"""LogsQL quoting, time boundaries and the VictoriaLogs HTTP contract."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch
from urllib.parse import urlencode

import httpx
import pytest

from autobot.panel.services.logs import LogFilters, build_query, prepare
from tests.helpers.integration import tg_tenant
from tests.platform.panel.conftest import get

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])
NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


def test_query_defaults_escaping_and_limits() -> None:
    value = 'a"\\b | drop *'
    with patch("autobot.panel.services.logs.timezone.now", return_value=NOW):
        query = build_query(LogFilters(level=value, service=value, q=value, limit=2000))
    assert json.dumps(value, ensure_ascii=False) in query
    assert "level:=" + json.dumps(value) in query
    assert "service:=" + json.dumps(value) in query
    assert "_msg:" + json.dumps(value) in query
    assert "2026-11-04T11:00:00+00:00" in query
    assert query.endswith("| sort by (_time) desc | limit 1001")
    with patch("autobot.panel.services.logs.timezone.now", return_value=NOW):
        assert build_query(LogFilters()).endswith("limit 201")


def test_31_day_boundary() -> None:
    now = datetime(2026, 11, 4, 12, tzinfo=UTC)
    boundary = now - timedelta(days=31)
    with patch("autobot.panel.services.logs.timezone.now", return_value=now):
        filters, clipped = prepare(LogFilters(start=boundary - timedelta(days=1)))
    assert clipped
    assert filters.start == boundary
    with patch("autobot.panel.services.logs.timezone.now", return_value=now):
        filters, clipped = prepare(LogFilters(start=boundary + timedelta(hours=1)))
    assert not clipped
    assert filters.start == boundary + timedelta(hours=1)


def test_31_day_boundary_tolerates_client_clock_skew() -> None:
    now = datetime(2026, 11, 4, 12, tzinfo=UTC)
    boundary = now - timedelta(days=31)
    with patch("autobot.panel.services.logs.timezone.now", return_value=now):
        filters, clipped = prepare(LogFilters(start=boundary - timedelta(seconds=2)))
        assert not clipped
        assert filters.start == boundary  # the real clipping stays
        _, clipped = prepare(LogFilters(start=boundary - timedelta(minutes=2)))
        assert clipped


def test_http_contract(
    authed_client: Any, tenants: Any, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc = tg_tenant()
    tenants(doc)
    settings.VICTORIALOGS_URL = "http://logs.test/"
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.method == "GET"
        assert request.url.path == "/select/logsql/query"
        query = request.url.params["query"]
        assert f'tenant:="{doc["id"]}"' in query
        assert f'tenant:="{doc["slug"]}"' in query
        assert query.endswith("limit 3")
        assert request.extensions["timeout"]["read"] == 10.0
        return httpx.Response(
            200, text="\n".join(json.dumps({"tenant": doc["id"], "_msg": str(i)}) for i in range(3))
        )

    original = httpx.Client
    monkeypatch.setattr(
        "autobot.panel.services.logs.httpx.Client",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    response = get(authed_client, "logs?" + urlencode({"tenant": doc["id"], "limit": 2}))
    assert response.status_code == 200, response.content
    data = response.json()
    assert len(data["items"]) == 2 and data["truncated"]
    assert data["items"][0]["tenant"] == doc["slug"]
    assert not data["clipped"]
    assert len(seen) == 1


@pytest.mark.parametrize("failure", ["unconfigured", "timeout", "http", "invalid", "shape"])
def test_unavailable(
    authed_client: Any, settings: Any, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    settings.VICTORIALOGS_URL = "" if failure == "unconfigured" else "http://logs.test"

    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "timeout":
            raise httpx.ReadTimeout("timeout", request=request)
        return httpx.Response(
            500 if failure == "http" else 200, text="[]" if failure == "shape" else "invalid"
        )

    original = httpx.Client
    monkeypatch.setattr(
        "autobot.panel.services.logs.httpx.Client",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    response = get(authed_client, "logs")
    assert response.status_code == 503
    assert response.json()["code"] == "logs_unavailable"


def test_clipped_and_invalid_ranges(
    authed_client: Any, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.VICTORIALOGS_URL = "http://logs.test"
    original = httpx.Client
    monkeypatch.setattr(
        "autobot.panel.services.logs.httpx.Client",
        lambda **kwargs: original(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, text="")), **kwargs
        ),
    )
    with patch("autobot.panel.services.logs.timezone.now", return_value=NOW):
        response = get(authed_client, "logs?" + urlencode({"start": "2026-10-01T00:00:00Z"}))
        assert response.json() == {"items": [], "truncated": False, "clipped": True}
        assert get(
            authed_client,
            "logs?" + urlencode({"start": "2026-10-01T00:00:00Z", "end": "2026-10-02T00:00:00Z"}),
        ).json()["clipped"]
        for params in (
            {"limit": 0},
            {"start": "2026-11-05T00:00:00Z"},
            {"start": "2026-11-02T00:00:00"},
        ):
            assert get(authed_client, "logs?" + urlencode(params)).status_code == 400
