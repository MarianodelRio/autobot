"""UI helpers: truncation, title limits and pagination, on `core.replies`."""

import pytest

from core.limits import LimitError
from core.replies import Buttons, List, Row
from core.ui import button, buttons_msg, list_msg, paginate, row, section, trunc


class TestTrunc:
    def test_short_text_unchanged(self) -> None:
        assert trunc("Hola", 20) == "Hola"

    def test_long_text_truncated(self) -> None:
        assert len(trunc("A" * 30, 20)) == 20

    def test_exact_length_unchanged(self) -> None:
        assert trunc("A" * 20, 20) == "A" * 20


class TestBuilders:
    def test_button_title_truncated_to_20(self) -> None:
        assert button("menu_book", "📅 Pedir cita muy larga de verdad").title == (
            "📅 Pedir cita muy lar"
        )

    def test_row_title_24_and_description_72(self) -> None:
        r = row("day_1", "T" * 30, "D" * 80)
        assert len(r.title) == 24
        assert r.description is not None and len(r.description) == 72

    def test_row_without_description(self) -> None:
        assert row("menu", "↩️ Volver al menú").description is None
        assert row("menu", "Volver", "").description is None

    def test_buttons_msg(self) -> None:
        msg = buttons_msg("¿Qué necesitas?", [button("a", "A"), button("b", "B")], header="🚌")
        assert msg == Buttons("¿Qué necesitas?", [button("a", "A"), button("b", "B")], "🚌")

    def test_buttons_msg_rejects_a_fourth_button(self) -> None:
        with pytest.raises(LimitError, match="4 buttons"):
            buttons_msg("x", [button(str(i), "B") for i in range(4)])

    def test_buttons_msg_rejects_long_ids(self) -> None:
        with pytest.raises(LimitError, match="bytes"):
            buttons_msg("x", [button("a" * 65, "B")])

    def test_list_msg_truncates_the_button_label(self) -> None:
        msg = list_msg("Elige", "Ver todos los servicios", [section("S", [row("a", "A")])])
        assert msg.button_label == "Ver todos los servic"

    def test_list_msg_rejects_eleven_rows(self) -> None:
        rows = [row(f"r{i}", "R") for i in range(11)]
        with pytest.raises(LimitError, match="11 list rows"):
            list_msg("Elige", "Ver", [section("S", rows)])

    def test_list_msg_rejects_a_long_body(self) -> None:
        with pytest.raises(LimitError, match="list body"):
            list_msg("b" * 1025, "Ver", [section("S", [row("a", "A")])])


def items(n: int) -> list[Row]:
    return [row(f"loc:{i}", f"Pueblo {i}") for i in range(1, n + 1)]


class TestPaginate:
    def test_single_page_has_only_back(self) -> None:
        rows = paginate(items(3), 0, more_id="lines:1", back_id="menu")
        assert [r.id for r in rows] == ["loc:1", "loc:2", "loc:3", "menu"]

    def test_first_of_two_pages_has_more_and_back(self) -> None:
        rows = paginate(items(10), 0, more_id="lines:1", back_id="menu")
        assert [r.id for r in rows] == [*(f"loc:{i}" for i in range(1, 9)), "lines:1", "menu"]
        assert rows[-2].title == "➡️ Ver más"

    def test_last_page_has_no_more(self) -> None:
        rows = paginate(items(10), 1, more_id="lines:2", back_id="menu")
        assert [r.id for r in rows] == ["loc:9", "loc:10", "menu"]

    def test_pages_lose_or_repeat_nothing(self) -> None:
        all_items = items(20)
        seen = [
            r
            for page in range(3)
            for r in paginate(all_items, page, more_id="more", back_id="back")
            if r.id not in ("more", "back")
        ]
        assert seen == all_items

    def test_every_page_fits_a_list(self) -> None:
        for page in range(3):
            rows = paginate(items(20), page, more_id="more", back_id="back")
            assert len(rows) <= 10
            list_msg("Elige", "Ver", [section("S", rows)])

    def test_out_of_range_page_falls_back_to_first(self) -> None:
        first = paginate(items(10), 0, more_id="more", back_id="back")
        assert paginate(items(10), 5, more_id="more", back_id="back") == first
        assert paginate(items(10), -1, more_id="more", back_id="back") == first

    def test_empty_items_still_offer_back(self) -> None:
        assert [r.id for r in paginate([], 0, more_id="more", back_id="back")] == ["back"]

    def test_custom_titles_and_page_size(self) -> None:
        rows = paginate(
            items(5),
            0,
            per_page=2,
            more_id="m",
            back_id="b",
            more_title="➡️ Más líneas",
            back_title="↩️ Menú",
        )
        assert [(r.id, r.title) for r in rows[-2:]] == [("m", "➡️ Más líneas"), ("b", "↩️ Menú")]

    def test_page_size_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            paginate(items(3), 0, per_page=0, more_id="m", back_id="b")

    def test_result_is_a_list_reply_row(self) -> None:
        msg = list_msg("x", "Ver", [section(None, paginate(items(2), 0, more_id="m", back_id="b"))])
        assert isinstance(msg, List)
