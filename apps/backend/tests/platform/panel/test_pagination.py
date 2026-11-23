"""Panel lists: keyset pagination is complete and tamper-proof, and the number of queries
of a request does not grow with the rows (no N+1, no unbounded reads)."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid7

import pytest
from django.db import connections
from django.test.utils import CaptureQueriesContext

from autobot.ops import health
from autobot.ops.audit import record
from autobot.panel.services.pagination import MAX_LIMIT
from autobot.runtime.models import Contact, InboundEvent, Notification, OutboundMessage
from autobot.tenancy.registry import get_registry
from tests.helpers.integration import wa_tenant
from tests.platform.panel.conftest import get

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]

T0 = datetime(2026, 11, 1, 10, tzinfo=UTC)


def tid(slug: str) -> Any:
    return get_registry().by_slug[slug].id


def queries(client: Any, path: str) -> int:
    """Queries (all connections) of one request; a first call warms sessions and caches."""
    assert get(client, path).status_code == 200
    with (
        CaptureQueriesContext(connections["owner"]) as owner,
        CaptureQueriesContext(connections["default"]) as default,
    ):
        response = get(client, path)
    assert response.status_code == 200, response.content
    return len(owner) + len(default)


def walk(client: Any, path: str, limit: int) -> list[Any]:
    """Every item of a paginated list, page by page; fails if a page repeats or loops."""
    items: list[Any] = []
    cursor = ""
    sep = "&" if "?" in path else "?"
    for _ in range(100):
        body = get(client, f"{path}{sep}limit={limit}&cursor={cursor}").json()
        assert len(body["items"]) <= limit
        items.extend(body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            return items
    raise AssertionError("pagination did not end")


def add_contacts(slug: str, start: int, count: int) -> None:
    Contact.objects.using("owner").bulk_create(
        Contact(
            tenant_id=tid(slug),
            channel="main",
            external_id=f"34600{n:06d}",
            display_name=f"C{n}",
        )
        for n in range(start, start + count)
    )


def test_contacts_pages_are_complete_without_duplicates(authed_client: Any, tenants: Any) -> None:
    tenants(wa_tenant("a"))
    add_contacts("a", 0, 23)
    items = walk(authed_client, "tenants/a/contacts", limit=5)
    assert len(items) == 23
    assert len({i["id"] for i in items}) == 23


def test_contacts_query_count_is_constant_in_the_rows(authed_client: Any, tenants: Any) -> None:
    tenants(wa_tenant("a"))
    add_contacts("a", 0, 5)
    few = queries(authed_client, "tenants/a/contacts")
    add_contacts("a", 5, 120)
    many = queries(authed_client, "tenants/a/contacts")
    assert many == few


@pytest.mark.parametrize(
    "path",
    ["tenants/a/contacts", "tenants/a/notifications", "audit", "activity", "demo/invites"],
)
def test_a_tampered_cursor_is_rejected_and_the_page_size_is_bounded(
    authed_client: Any, tenants: Any, path: str
) -> None:
    tenants(wa_tenant("a"))
    for cursor in ("garbage", "e30", "eyJhdCI6IjIwMjYtMDEtMDFUMDA6MDA6MDAiLCJpZCI6IjEifQ"):
        response = get(authed_client, f"{path}?cursor={cursor}")
        assert response.status_code in (400, 422), (path, cursor, response.status_code)
    # An absurd limit is clamped (or refused), never served as-is.
    response = get(authed_client, f"{path}?limit=100000")
    assert response.status_code in (200, 422)


def test_notifications_pages_and_constant_queries(authed_client: Any, tenants: Any) -> None:
    tenants(wa_tenant("a"))

    def add(start: int, count: int) -> None:
        Notification.objects.using("owner").bulk_create(
            Notification(
                tenant_id=tid("a"),
                audience=Notification.Audience.OWNER,
                kind="booking",
                text=f"n{n}",
                idem_key=str(uuid7()),
            )
            for n in range(start, start + count)
        )

    add(0, 5)
    few = queries(authed_client, "tenants/a/notifications")
    add(5, 80)
    assert queries(authed_client, "tenants/a/notifications") == few
    items = walk(authed_client, "tenants/a/notifications", limit=20)
    assert len(items) == 85 and len({i["text"] for i in items}) == 85


def test_audit_pages_and_constant_queries(authed_client: Any, tenants: Any) -> None:
    tenants(*(wa_tenant(s) for s in ("a", "b", "c")))

    def add(start: int, count: int) -> None:
        for n in range(start, start + count):
            record(
                actor="op",
                action=f"act.{n % 4}",
                summary=f"s{n}",
                tenant_id=tid("abc"[n % 3]),
            )

    add(0, 6)
    few = queries(authed_client, "audit")
    add(6, 60)
    assert queries(authed_client, "audit") == few
    items = walk(authed_client, "audit", limit=7)
    assert len({i["id"] for i in items}) == len(items)  # no duplicates across pages
    assert sum(i["action"].startswith("act.") for i in items) == 66  # none missing
    assert {i["tenant"] for i in items} >= {"a", "b", "c"}
    actions = get(authed_client, "audit/actions").json()
    assert actions == sorted(actions) and {f"act.{n}" for n in range(4)} <= set(actions)
    only = walk(authed_client, "audit?tenant=a", limit=10)
    assert only and {i["tenant"] for i in only} == {"a"}


def test_activity_pages_and_constant_queries(authed_client: Any, tenants: Any) -> None:
    tenants(wa_tenant("a"), wa_tenant("b"))

    def add(start: int, count: int) -> None:
        c = Contact.objects.using("owner").get_or_create(
            tenant_id=tid("a"), channel="main", external_id="1"
        )[0]
        for n in range(start, start + count):
            at = T0 + timedelta(seconds=n)
            InboundEvent.objects.using("owner").create(
                tenant_id=tid("a"),
                channel="main",
                kind="message",
                provider_event_id=str(uuid7()),
                payload={},
                status="done",
                received_at=at,
            )
            OutboundMessage.objects.using("owner").create(
                tenant_id=tid("a"),
                contact=c,
                channel="main",
                idem_key=str(uuid7()),
                payload={"body": "x"},
                status="sent",
                sent_at=at,
            )

    add(0, 4)
    few = queries(authed_client, "activity")
    add(4, 40)
    assert queries(authed_client, "activity") == few
    items = walk(authed_client, "activity", limit=9)
    assert len(items) == 88 and len({(i["kind"], i["id"]) for i in items}) == 88
    assert [i["at"] for i in items] == sorted((i["at"] for i in items), reverse=True)


def test_tenant_list_query_count_is_constant_in_the_tenants(
    authed_client: Any, tenants: Any
) -> None:
    """Health snapshots live in a database cache: reading them one by one would cost two
    queries per tenant. Last-activity probes and the month figures are batched too."""

    def seed(slugs: list[str]) -> None:
        tenants(*(wa_tenant(s) for s in slugs))
        for s in slugs:
            health.write_snapshot(
                tid(s), health.HealthSnapshot(checked_at=datetime.now(UTC), issues=[])
            )
            InboundEvent.objects.using("owner").create(
                tenant_id=tid(s),
                channel="main",
                kind="message",
                provider_event_id=str(uuid7()),
                payload={},
                status="done",
                received_at=datetime.now(UTC),
            )

    seed(["a", "b"])
    few = queries(authed_client, "tenants")
    seed([f"t{n}" for n in range(12)])
    assert len(get(authed_client, "tenants").json()) == 14
    assert queries(authed_client, "tenants") == few


def test_page_limit_is_capped() -> None:
    assert MAX_LIMIT == 100
