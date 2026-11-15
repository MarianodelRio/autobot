"""`manage.py chat` (L4): a terminal chat with a pack's demo template, over
`core.testing.Conversation`. No database, no channel, no network."""

import io
from collections.abc import Iterator

import pytest
from django.core.management import CommandError, call_command


def chat(
    monkeypatch: pytest.MonkeyPatch, pack: str, lines: list[str], *, channel: str | None = None
) -> str:
    answers: Iterator[str] = iter([*lines, "salir"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    out = io.StringIO()
    err = io.StringIO()
    args = [pack]
    if channel:
        args += ["--channel", channel]
    call_command("chat", *args, stdout=out, stderr=err)
    return out.getvalue() + err.getvalue()


def test_unknown_pack_is_a_command_error(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(CommandError, match="Pack desconocido"):
        chat(monkeypatch, "not-a-pack", [])


def test_salon_offers_its_main_menu(monkeypatch: pytest.MonkeyPatch) -> None:
    output = chat(monkeypatch, "salon", ["hola"])
    assert "Pedir cita" in output
    assert "demo-peluqueria" in output


def test_bus_offers_its_main_menu(monkeypatch: pytest.MonkeyPatch) -> None:
    output = chat(monkeypatch, "bus", ["hola"])
    assert "Ver horarios" in output
    assert "demo-autobuses" in output


def test_pressing_a_numbered_option_works(monkeypatch: pytest.MonkeyPatch) -> None:
    output = chat(monkeypatch, "bus", ["hola", "1"])
    assert "pueblo" in output.lower()


def test_an_out_of_range_number_is_reported_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = chat(monkeypatch, "bus", ["hola", "99"])
    assert "No hay ninguna opción [99]" in output


def test_channel_option_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    output = chat(monkeypatch, "salon", ["hola"], channel="telegram")
    assert "canal telegram" in output
