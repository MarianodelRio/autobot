"""`pick_tester_candidates`: the pure filtering and de-duplication of the Alta tab's
"testers" step, without a database or a provider."""

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from autobot.channels.base import InboundItem
from autobot.panel.services.setup import pick_tester_candidates

NOW = datetime(2026, 11, 3, 10, tzinfo=UTC)


def sender(external_id: str, phone: str | None = None) -> InboundItem:
    return InboundItem(
        provider_event_id=f"evt-{external_id}",
        external_id=external_id,
        display_name=None,
        phone=phone,
        message=cast("Any", None),
        payload={},
    )


def at(minutes: int) -> datetime:
    return NOW - timedelta(minutes=minutes)


def test_order_is_kept_and_the_phone_loses_its_plus() -> None:
    result = pick_tester_candidates(
        [(sender("bsuid-1", "+34600000001"), at(1)), (sender("42"), at(2))], [], limit=5
    )
    assert [(c.id, c.display) for c in result] == [
        ("34600000001", "34600000001"),
        ("42", "id 42"),
    ]
    assert result[0].received_at == at(1).isoformat()


def test_existing_testers_are_skipped_by_id_or_by_phone() -> None:
    items = [
        (sender("bsuid-1", "+34600000001"), at(1)),  # its phone is already a tester
        (sender("42"), at(2)),  # its id is already a tester
        (sender("43"), at(3)),
    ]
    result = pick_tester_candidates(items, {"34600000001", "42"}, limit=5)
    assert [c.id for c in result] == ["43"]


def test_a_sender_who_wrote_twice_appears_once_with_the_newest_message() -> None:
    items = [(sender("a", "+34600000001"), at(1)), (sender("b", "+34600000001"), at(5))]
    result = pick_tester_candidates(items, [], limit=5)
    assert [(c.id, c.received_at) for c in result] == [("34600000001", at(1).isoformat())]


def test_the_limit_stops_the_scan() -> None:
    items = [(sender(str(n)), at(n)) for n in range(10)]
    assert [c.id for c in pick_tester_candidates(items, [], limit=3)] == ["0", "1", "2"]


def test_nothing_to_pick_from() -> None:
    assert pick_tester_candidates([], ["x"], limit=5) == []
