"""Spanish date helpers, with a fixed aware datetime."""

from datetime import date, time

import pytest

from core.dates import (
    MONTH_NUMBER,
    WEEKDAY_KEYS,
    WEEKDAY_LABEL,
    WEEKDAYS_ES,
    format_date_es,
    minutes_of,
    parse_hhmm,
    weekday_es,
)


class TestFormatDateEs:
    def test_monday(self) -> None:
        assert format_date_es(date(2026, 3, 23)) == "lunes 23 de marzo"

    def test_friday(self) -> None:
        assert format_date_es(date(2026, 3, 27)) == "viernes 27 de marzo"

    def test_december(self) -> None:
        assert format_date_es(date(2026, 12, 25)) == "viernes 25 de diciembre"

    def test_accented_weekdays(self) -> None:
        assert format_date_es(date(2026, 3, 25)) == "miércoles 25 de marzo"
        assert weekday_es(date(2026, 3, 28)) == "sábado"

    def test_capitalise_helper(self) -> None:
        assert format_date_es(date(2026, 3, 23)).capitalize() == "Lunes 23 de marzo"


def test_weekday_keys_and_labels_line_up() -> None:
    assert len(WEEKDAY_KEYS) == 7 and WEEKDAY_KEYS[0] == "lunes"
    assert [WEEKDAY_LABEL[k] for k in WEEKDAY_KEYS] == list(WEEKDAYS_ES)
    assert WEEKDAY_KEYS[date(2026, 3, 25).weekday()] == "miercoles"


def test_month_number() -> None:
    assert MONTH_NUMBER["enero"] == 1 and MONTH_NUMBER["septiembre"] == 9
    assert sorted(MONTH_NUMBER.values()) == list(range(1, 13))


def test_parse_hhmm_and_minutes_of() -> None:
    assert parse_hhmm("09:30") == time(9, 30)
    assert parse_hhmm("9:05") == time(9, 5)
    assert minutes_of("00:00") == 0
    assert minutes_of("09:30") == 570
    assert minutes_of(time(23, 59)) == 1439


def test_parse_hhmm_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_hhmm("930")
