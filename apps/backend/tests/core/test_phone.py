import pytest

from core.phone import phone_key


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("600 11 22 33", "34600112233"),
        ("+34 600 11 22 33", "34600112233"),
        ("34600112233", "34600112233"),
        ("0034600112233", "0034600112233"),  # not guessed: only 9 digits get the prefix
        ("+44 7700 900123", "447700900123"),
        ("", ""),
        (None, ""),
        ("sin número", ""),
    ],
)
def test_phone_key(value: str | None, expected: str) -> None:
    assert phone_key(value) == expected


def test_spanish_forms_of_one_number_compare_equal() -> None:
    assert phone_key("600112233") == phone_key("+34600112233") == phone_key("34 600-112-233")
