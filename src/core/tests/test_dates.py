"""Ported from Peluquería `tests/test_slots.py` (TestGetNextDays, TestFormatDateEs),
with a fixed aware datetime instead of patching `datetime` and `pytz`."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from core.dates import format_date_es, next_days, weekday_es

TZ = ZoneInfo("Europe/Madrid")
SUNDAY = {6}


class TestNextDays:
    def test_skips_the_given_weekdays(self) -> None:
        days = next_days(datetime(2026, 3, 23, 9, tzinfo=TZ), 14, skip_weekdays=SUNDAY)
        assert all(d.weekday() != 6 for d in days)

    def test_includes_today_if_not_skipped(self) -> None:
        days = next_days(datetime(2026, 3, 23, 9, tzinfo=TZ), 7, skip_weekdays=SUNDAY)
        assert days[0] == date(2026, 3, 23)

    def test_skips_today_if_sunday(self) -> None:
        days = next_days(datetime(2026, 3, 29, 9, tzinfo=TZ), 7, skip_weekdays=SUNDAY)
        assert days[0] == date(2026, 3, 30)

    def test_count_within_window(self) -> None:
        # range(8): Mon 23 … Sat 28, Sun 29 (skipped), Mon 30 → 7 days
        days = next_days(datetime(2026, 3, 23, 9, tzinfo=TZ), 7, skip_weekdays=SUNDAY)
        assert len(days) == 7

    def test_without_skipped_days_returns_every_day(self) -> None:
        days = next_days(datetime(2026, 3, 23, 9, tzinfo=TZ), 2)
        assert days == [date(2026, 3, 23), date(2026, 3, 24), date(2026, 3, 25)]

    def test_today_is_taken_in_the_clock_zone(self) -> None:
        # 23:30 UTC on Sunday 29 is already Monday 30 in Madrid (summer time)
        late = datetime(2026, 3, 29, 23, 30, tzinfo=ZoneInfo("UTC")).astimezone(TZ)
        assert next_days(late, 0) == [date(2026, 3, 30)]

    def test_naive_datetime_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            next_days(datetime(2026, 3, 23), 7)


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
