"""`fold`, `strip_html` and `normalize`, which also drops punctuation."""

import pytest

from core.text import fold, normalize, strip_html


class TestFold:
    def test_lowercase(self) -> None:
        assert fold("CONFIRMADA") == "confirmada"

    def test_accent_stripped(self) -> None:
        assert fold("sí") == "si"
        assert fold("Sí") == "si"
        assert fold("SÍ") == "si"

    def test_nfc_precomposed(self) -> None:
        assert fold("\xe9") == "e"  # é precomposed
        assert fold("e\u0301") == "e"  # e + combining acute

    def test_whitespace_stripped(self) -> None:
        assert fold("  pendiente  ") == "pendiente"

    def test_empty_string(self) -> None:
        assert fold("") == ""

    def test_mixed(self) -> None:
        assert fold("  PéNdIeNtE  ") == "pendiente"

    def test_punctuation_is_kept_for_the_salon_parser(self) -> None:
        assert fold("[CFG] HORARIO 10:00-13:00") == "[cfg] horario 10:00-13:00"
        assert fold("Corte+Barba") == "corte+barba"
        assert fold("[CFG] Vacáciones") == "[cfg] vacaciones"


class TestNormalize:
    def test_lowercase(self) -> None:
        assert normalize("CONFIRMADA") == "confirmada"

    def test_accent_stripped(self) -> None:
        assert normalize("sí") == "si"
        assert normalize("Sí") == "si"
        assert normalize("SÍ") == "si"

    def test_nfc_and_nfd_are_equal(self) -> None:
        assert normalize("\xe9") == "e"  # é precomposed
        assert normalize("é") == "e"  # e + combining acute

    def test_whitespace_stripped(self) -> None:
        assert normalize("  pendiente  ") == "pendiente"

    def test_empty_string(self) -> None:
        assert normalize("") == ""

    def test_mixed(self) -> None:
        assert normalize("  PéNdIeNtE  ") == "pendiente"

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("¡Menú!", "menu"),
            ("Corte y barba", "corte y barba"),
            ("Villanueva   del\tDuque", "villanueva del duque"),
            ("Pozoblanco-Córdoba", "pozoblanco cordoba"),
            ("[CFG] Vacáciones", "cfg vacaciones"),
            ("Añora", "anora"),
            ("📅 Pedir cita", "pedir cita"),
            ("/start", "start"),
        ],
    )
    def test_punctuation_becomes_space_and_spaces_collapse(self, text: str, expected: str) -> None:
        assert normalize(text) == expected


class TestStripHtml:
    def test_no_html(self) -> None:
        assert strip_html("Nombre: Juan") == "Nombre: Juan"

    def test_br_becomes_newline(self) -> None:
        result = strip_html("Estado: confirmada<br>Recordatorio: no")
        assert result == "Estado: confirmada\nRecordatorio: no"

    @pytest.mark.parametrize("tag", ["<br>", "<BR/>", "<br />", "</p>", "</div>", "</li>"])
    def test_block_tags_become_newlines(self, tag: str) -> None:
        assert strip_html(f"a{tag}b") == "a\nb"

    def test_tags_removed(self) -> None:
        assert strip_html("<p>Hola</p>") == "Hola\n"
        assert strip_html('<b class="x">Hola</b>') == "Hola"

    def test_entities_decoded(self) -> None:
        assert strip_html("&amp;") == "&"
        assert strip_html("&nbsp;") == "\xa0"
        assert strip_html("&lt;b&gt;") == "<b>"

    def test_empty(self) -> None:
        assert strip_html("") == ""
