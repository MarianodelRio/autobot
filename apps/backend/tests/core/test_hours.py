import pytest

from core.hours import parse_range, validate_ranges


def test_parse_range() -> None:
    assert parse_range("08:00-15:30") == ("08:00", "15:30")


@pytest.mark.parametrize(
    "ranges",
    [
        ["08:00-15:00"],
        ["10:00-14:00", "09:00-10:00"],
        ["09:00-10:00", "10:00-11:00"],
        ["9:00-10:00"],
    ],
)
def test_valid_ranges(ranges: list[str]) -> None:
    validate_ranges(ranges)


@pytest.mark.parametrize(
    ("ranges", "message"),
    [
        ([], "al menos un tramo"),
        (["10:00-10:00"], "empezar antes de acabar"),
        (["11:00-10:00"], "empezar antes de acabar"),
        (["09:00-11:00", "10:00-12:00"], "se solapan"),
        (["9:00-10:00", "09:30-10:30"], "se solapan"),  # compared as times, not as text
    ],
)
def test_invalid_ranges(ranges: list[str], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        validate_ranges(ranges)
