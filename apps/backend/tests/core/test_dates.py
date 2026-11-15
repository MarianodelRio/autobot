"""Spanish date helpers, with a fixed aware datetime."""

from datetime import date

from core.dates import format_date_es, weekday_es


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
