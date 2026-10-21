import logging

import pytest

from core.limits import (
    MAX_INTERACTIVE_BODY,
    MAX_TEXT,
    SEPARATOR,
    LimitError,
    check,
    plan_sends,
)
from core.replies import Button, Buttons, List, Reply, Row, Section, Text


def buttons(*titles: str, body: str = "Elige") -> Buttons:
    return Buttons(body, [Button(f"b{i}", t) for i, t in enumerate(titles)])


def rows_list(n: int, *, title: str = "Fila", body: str = "Elige") -> List:
    return List(body, "Ver", [Section("Opciones", [Row(f"r{i}", title) for i in range(n)])])


def assert_fits(reply: Reply) -> None:
    assert check(reply) == ([], [])


# ── Rule 1: consecutive texts are merged ──────────────────────────────────


def test_consecutive_texts_are_merged() -> None:
    assert plan_sends([Text("Hola"), Text("¿Qué tal?")]) == [Text(f"Hola{SEPARATOR}¿Qué tal?")]


def test_texts_are_not_merged_beyond_the_text_limit() -> None:
    a, b = "a" * 3000, "b" * 3000
    assert plan_sends([Text(a), Text(b)]) == [Text(a), Text(b)]


def test_merged_text_exactly_at_the_limit_stays_merged() -> None:
    a = "a" * (MAX_TEXT - len(SEPARATOR) - 10)
    assert plan_sends([Text(a), Text("b" * 10)]) == [Text(f"{a}{SEPARATOR}{'b' * 10}")]


def test_no_replies_plan_nothing() -> None:
    assert plan_sends([]) == []


# ── Rule 2: a text goes inside the following interactive if it fits ──────


def test_text_goes_into_following_buttons_body() -> None:
    planned = plan_sends([Text("Hecho"), buttons("Menú", body="¿Algo más?")])
    assert planned == [buttons("Menú", body=f"Hecho{SEPARATOR}¿Algo más?")]


def test_several_texts_go_into_following_list_body() -> None:
    planned = plan_sends([Text("A"), Text("B"), rows_list(2, body="C")])
    assert planned == [rows_list(2, body=f"A{SEPARATOR}B{SEPARATOR}C")]


def test_text_and_interactive_exactly_at_1024_are_joined() -> None:
    text = "t" * (MAX_INTERACTIVE_BODY - len(SEPARATOR) - 5)
    planned = plan_sends([Text(text), buttons("Ok", body="x" * 5)])
    assert len(planned) == 1
    assert isinstance(planned[0], Buttons)
    assert len(planned[0].body) == MAX_INTERACTIVE_BODY


def test_text_and_interactive_over_1024_stay_separate() -> None:
    text = "t" * (MAX_INTERACTIVE_BODY - len(SEPARATOR) - 4)
    interactive = buttons("Ok", body="x" * 5)
    assert plan_sends([Text(text), interactive]) == [Text(text), interactive]


def test_text_after_interactive_is_not_merged_backwards() -> None:
    interactive = buttons("Ok")
    assert plan_sends([interactive, Text("Fin")]) == [interactive, Text("Fin")]


def test_order_is_kept() -> None:
    first, second = buttons("Uno"), rows_list(1)
    assert plan_sends([first, Text("medio"), second]) == [
        first,
        rows_list(1, body=f"medio{SEPARATOR}Elige"),
    ]


# ── Rule 3: limits ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("reply", "fits"),
    [
        (Text("a" * MAX_TEXT), True),
        (Text("a" * (MAX_TEXT + 1)), False),
        (buttons("Ok", body="a" * MAX_INTERACTIVE_BODY), True),
        (buttons("Ok", body="a" * (MAX_INTERACTIVE_BODY + 1)), False),
        (rows_list(1, body="a" * MAX_INTERACTIVE_BODY), True),
        (rows_list(1, body="a" * (MAX_INTERACTIVE_BODY + 1)), False),
        (buttons("A", "B", "C"), True),
        (buttons("A", "B", "C", "D"), False),
        (buttons("t" * 20), True),
        (buttons("t" * 21), False),
        (rows_list(10), True),
        (rows_list(11), False),
        (rows_list(1, title="t" * 24), True),
        (rows_list(1, title="t" * 25), False),
        (List("x", "Ver", [Section("s", [Row("r", "t", "d" * 72)])]), True),
        (List("x", "Ver", [Section("s", [Row("r", "t", "d" * 73)])]), False),
        (List("x", "v" * 20, [Section("s", [Row("r", "t")])]), True),
        (List("x", "v" * 21, [Section("s", [Row("r", "t")])]), False),
        (List("x", "Ver", [Section("s" * 24, [Row("r", "t")])]), True),
        (List("x", "Ver", [Section("s" * 25, [Row("r", "t")])]), False),
        (Buttons("x", [Button("b", "B")], header="h" * 60, footer="f" * 60), True),
        (Buttons("x", [Button("b", "B")], header="h" * 61), False),
        (Buttons("x", [Button("b", "B")], footer="f" * 61), False),
    ],
)
def test_limits(reply: Reply, fits: bool) -> None:
    fatal, long = check(reply)
    assert fatal == []
    assert (long == []) is fits


def test_rows_are_counted_across_sections() -> None:
    reply = List(
        "x",
        "Ver",
        [
            Section("a", [Row(f"a{i}", "t") for i in range(6)]),
            Section("b", [Row(f"b{i}", "t") for i in range(5)]),
        ],
    )
    assert check(reply)[1] == ["11 list rows (max 10)"]


def test_ten_rows_across_sections_fit() -> None:
    reply = List(
        "x",
        "Ver",
        [
            Section("a", [Row(f"a{i}", "t") for i in range(6)]),
            Section("b", [Row(f"b{i}", "t") for i in range(4)]),
        ],
    )
    assert_fits(reply)


@pytest.mark.parametrize(
    "reply",
    [
        Buttons("x", [Button("a" * 64, "Ok")]),
        Buttons("x", [Button("ñ" * 32, "Ok")]),  # 64 bytes
        List("x", "Ver", [Section(None, [Row("r" * 64, "t")])]),
    ],
)
def test_ids_up_to_64_bytes_are_accepted(reply: Reply) -> None:
    assert_fits(reply)
    assert plan_sends([reply], strict=True) == [reply]


@pytest.mark.parametrize(
    "reply",
    [
        Buttons("x", [Button("a" * 65, "Ok")]),
        Buttons("x", [Button("ñ" * 33, "Ok")]),  # 33 characters but 66 bytes
        List("x", "Ver", [Section(None, [Row("r" * 65, "t")])]),
    ],
)
def test_ids_over_64_bytes_are_rejected_even_outside_tests(reply: Reply) -> None:
    with pytest.raises(LimitError, match="bytes"):
        plan_sends([reply])


@pytest.mark.parametrize(
    ("reply", "error"),
    [
        (Text(""), "empty"),
        (Buttons("", [Button("b", "B")]), "empty"),
        (Buttons("x", []), "no buttons"),
        (List("x", "Ver", [Section("s", [])]), "no rows"),
        (Buttons("x", [Button("b", "B"), Button("b", "C")]), "repeated"),
        (Buttons("x", [Button("", "B")]), "empty"),
        (Buttons("x", [Button("a", "Igual"), Button("b", "Igual")]), "titles are repeated"),
        (
            List("x", "Ver", [Section("a", [Row("r", "t")]), Section("b", [Row("r", "u")])]),
            "repeated",
        ),
        (List("x", "Ver", [Section("a", [Row("r", "t")]), Section("b", [])]), "no rows"),
        (
            List("x", "Ver", [Section("a", [Row("r", "t")]), Section(None, [Row("s", "u")])]),
            "title",
        ),
    ],
)
def test_structural_problems_always_raise(reply: Reply, error: str) -> None:
    with pytest.raises(LimitError, match=error):
        plan_sends([reply])


# ── Strict mode fails; production truncates and logs ──────────────────────


def test_strict_mode_raises_on_any_limit() -> None:
    with pytest.raises(LimitError, match="4 buttons"):
        plan_sends([buttons("A", "B", "C", "D")], strict=True)


def test_production_truncates_and_logs(caplog: pytest.LogCaptureFixture) -> None:
    secret = "Lucía García +34600000001 " * 200
    with caplog.at_level(logging.WARNING, logger="core.limits"):
        planned = plan_sends([Text(secret)])
    assert planned == [Text(secret[:MAX_TEXT])]
    assert "truncated" in caplog.text
    assert "Lucía" not in caplog.text and "+34" not in caplog.text


def test_truncation_fits_every_limit() -> None:
    reply = List(
        "b" * 2000,
        "v" * 30,
        [
            Section("s" * 30, [Row(f"a{i}", "t" * 30, "d" * 80) for i in range(7)]),
            Section("otra", [Row(f"b{i}", "t") for i in range(7)]),
            Section("vacía al truncar", [Row("c0", "t")]),
        ],
        header="h" * 80,
        footer="f" * 80,
    )
    (planned,) = plan_sends([reply])
    assert_fits(planned)
    assert isinstance(planned, List)
    assert [r.id for s in planned.sections for r in s.rows] == [
        *(f"a{i}" for i in range(7)),
        "b0",
        "b1",
        "b2",
    ]
    assert len(planned.sections) == 2

    (planned_buttons,) = plan_sends([buttons("t" * 30, "B", "C", "D", body="b" * 2000)])
    assert_fits(planned_buttons)


@pytest.mark.parametrize(
    "replies",
    [
        [Text(""), Text("a")],
        [Text("a"), Text("")],
        [Text("hola"), Buttons("", [Button("b", "B")])],
    ],
)
def test_merging_does_not_hide_fatal_problems(replies: list[Reply]) -> None:
    with pytest.raises(LimitError, match="empty"):
        plan_sends(replies)


def test_titles_that_become_equal_when_truncated_raise() -> None:
    reply = Buttons(
        "x", [Button("a", "Reservar mañana tarde 1"), Button("b", "Reservar mañana tarde 2")]
    )
    with pytest.raises(LimitError, match="titles are repeated"):
        plan_sends([reply])
