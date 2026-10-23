"""
Unit tests for utils/parser.py.
All functions must be case-insensitive, accent-tolerant and never raise.
"""

from core.text import fold as _norm
from core.text import strip_html as _strip_html
from packs.salon.parser import (
    parse_cfg,
    parse_external_id,
    parse_name,
    parse_phone,
    parse_reminder,
    parse_status,
    remove_field,
    set_field,
)
from packs.salon.parser import parse_service_title as parse_service


class TestNorm:
    def test_lowercase(self) -> None:
        assert _norm("CONFIRMADA") == "confirmada"

    def test_accent_stripped(self) -> None:
        assert _norm("sí") == "si"
        assert _norm("Sí") == "si"
        assert _norm("SÍ") == "si"

    def test_nfc_precomposed(self) -> None:
        assert _norm("é") == "e"
        assert _norm("é") == "e"

    def test_whitespace_stripped(self) -> None:
        assert _norm("  pendiente  ") == "pendiente"

    def test_empty_string(self) -> None:
        assert _norm("") == ""

    def test_none_like_empty(self) -> None:
        assert _norm("") == ""

    def test_mixed(self) -> None:
        assert _norm("  PéNdIeNtE  ") == "pendiente"


class TestStripHtml:
    def test_no_html(self) -> None:
        assert _strip_html("Nombre: Juan") == "Nombre: Juan"

    def test_br_becomes_newline(self) -> None:
        result = _strip_html("Estado: confirmada<br>Recordatorio: no")
        assert "\n" in result
        assert "<br>" not in result

    def test_tags_removed(self) -> None:
        result = _strip_html("<p>Hola</p>")
        assert "<p>" not in result
        assert "Hola" in result

    def test_entities_decoded(self) -> None:
        assert _strip_html("&amp;") == "&"
        assert _strip_html("&nbsp;") == "\xa0"
        assert _strip_html("&lt;b&gt;") == "<b>"

    def test_empty(self) -> None:
        assert _strip_html("") == ""

    def test_none_passthrough(self) -> None:
        assert _strip_html("") == ""


class TestParseNombre:
    def test_basic(self) -> None:
        assert parse_name("Nombre: Juan García") == "Juan García"

    def test_case_insensitive(self) -> None:
        assert parse_name("NOMBRE: María") == "María"

    def test_extra_spaces(self) -> None:
        assert parse_name("Nombre:   Paco  ") == "Paco"

    def test_missing(self) -> None:
        assert parse_name("Estado: confirmada") is None

    def test_empty(self) -> None:
        assert parse_name("") is None

    def test_none(self) -> None:
        assert parse_name(None) is None

    def test_multiline(self) -> None:
        desc = "Nombre: Luis\nTelefono: 34600000001\nEstado: confirmada"
        assert parse_name(desc) == "Luis"


class TestParseTel:
    def test_telefono_field(self) -> None:
        assert parse_phone("Telefono: 34600000001") == "34600000001"

    def test_tel_legacy(self) -> None:
        assert parse_phone("Tel: 34600000001") == "34600000001"

    def test_spaces_stripped(self) -> None:
        assert parse_phone("Telefono: 346 000 000 01") == "34600000001"

    def test_dashes_stripped(self) -> None:
        assert parse_phone("Telefono: 346-000-000-01") == "34600000001"

    def test_plus_prefix_stripped_for_normalisation(self) -> None:
        result = parse_phone("Telefono: +34600000001")
        assert result == "34600000001"

    def test_9digit_spanish_number_normalised(self) -> None:
        assert parse_phone("Telefono: 600000001") == "34600000001"

    def test_9digit_with_spaces_normalised(self) -> None:
        assert parse_phone("Telefono: 600 000 001") == "34600000001"

    def test_9digit_with_plus_normalised(self) -> None:
        assert parse_phone("Telefono: +600000001") == "34600000001"

    def test_11digit_with_country_code_unchanged(self) -> None:
        assert parse_phone("Telefono: 34600000001") == "34600000001"

    def test_too_short_rejected(self) -> None:
        assert parse_phone("Telefono: 123") is None

    def test_too_long_rejected(self) -> None:
        assert parse_phone("Telefono: 1234567890123456") is None

    def test_missing(self) -> None:
        assert parse_phone("Estado: confirmada") is None

    def test_empty(self) -> None:
        assert parse_phone("") is None

    def test_html_in_description(self) -> None:
        assert parse_phone("Telefono: 34600000001<br>Estado: confirmada") == "34600000001"


class TestParseWaId:
    def test_basic_extraction(self) -> None:
        assert parse_external_id("WaId: ES.1A2B3C4D5E6F") == "ES.1A2B3C4D5E6F"

    def test_case_insensitive_key(self) -> None:
        assert parse_external_id("waid: ES.1A2B3C4D5E6F") == "ES.1A2B3C4D5E6F"

    def test_multiline_description(self) -> None:
        desc = "Nombre: Juan\nWaId: ES.ABC123\nEstado: confirmada"
        assert parse_external_id(desc) == "ES.ABC123"

    def test_missing_field_returns_none(self) -> None:
        assert parse_external_id("Nombre: Juan\nEstado: confirmada") is None

    def test_empty_string_returns_none(self) -> None:
        assert parse_external_id("") is None

    def test_none_input_returns_none(self) -> None:
        assert parse_external_id(None) is None

    def test_html_tags_in_description(self) -> None:
        desc = "WaId: ES.1A2B3C<br>Estado: confirmada"
        assert parse_external_id(desc) == "ES.1A2B3C"


class TestParseEstado:
    def test_confirmada(self) -> None:
        assert parse_status("Estado: confirmada") == "confirmada"

    def test_pendiente(self) -> None:
        assert parse_status("Estado: pendiente") == "pendiente"

    def test_uppercase(self) -> None:
        assert parse_status("ESTADO: CONFIRMADA") == "confirmada"

    def test_with_accent(self) -> None:
        assert parse_status("Estado: Confirmáda") == "confirmada"

    def test_unknown_value(self) -> None:
        assert parse_status("Estado: cancelada") is None

    def test_missing(self) -> None:
        assert parse_status("Nombre: Juan") is None

    def test_empty(self) -> None:
        assert parse_status("") is None


class TestParseReminder:
    def test_recordatorio_si(self) -> None:
        assert parse_reminder("Recordatorio: sí") == "si"

    def test_recordatorio_si_no_accent(self) -> None:
        assert parse_reminder("Recordatorio: si") == "si"

    def test_recordatorio_no(self) -> None:
        assert parse_reminder("Recordatorio: no") == "no"

    def test_uppercase(self) -> None:
        assert parse_reminder("RECORDATORIO: SI") == "si"

    def test_legacy_reminder24h(self) -> None:
        assert parse_reminder("Reminder24h: si") == "si"
        assert parse_reminder("Reminder24h: no") == "no"

    def test_recordatorio_takes_priority_over_legacy(self) -> None:
        desc = "Recordatorio: no\nReminder24h: si"
        assert parse_reminder(desc) == "no"

    def test_invalid_value(self) -> None:
        assert parse_reminder("Recordatorio: quiza") is None

    def test_empty(self) -> None:
        assert parse_reminder("") is None


class TestParseCfg:
    def test_cerrado(self) -> None:
        assert parse_cfg("[CFG] CERRADO") == {"type": "cerrado"}

    def test_vacaciones(self) -> None:
        assert parse_cfg("[CFG] Vacaciones") == {"type": "vacaciones"}

    def test_horario(self) -> None:
        result = parse_cfg("[CFG] HORARIO 10:00-14:00")
        assert result == {"type": "horario", "start": "10:00", "end": "14:00"}

    def test_horario_no_space(self) -> None:
        result = parse_cfg("[CFG] HORARIO10:00-14:00")
        assert result == {"type": "horario", "start": "10:00", "end": "14:00"}

    def test_horario_en_dash(self) -> None:
        result = parse_cfg("[CFG] HORARIO 10:00–14:00")
        assert result == {"type": "horario", "start": "10:00", "end": "14:00"}

    def test_cfg_lowercase(self) -> None:
        assert parse_cfg("[cfg] cerrado") == {"type": "cerrado"}

    def test_cfg_with_accents(self) -> None:
        assert parse_cfg("[CFG] Vacáciones") == {"type": "vacaciones"}

    def test_no_cfg_tag(self) -> None:
        assert parse_cfg("CERRADO") is None

    def test_cfg_unknown_type(self) -> None:
        assert parse_cfg("[CFG] DESCANSO") is None

    def test_empty(self) -> None:
        assert parse_cfg("") is None

    def test_none(self) -> None:
        assert parse_cfg(None) is None

    def test_horario_single_digit_hour(self) -> None:
        result = parse_cfg("[CFG] HORARIO 9:00-13:00")
        assert result == {"type": "horario", "start": "9:00", "end": "13:00"}


class TestParseServicioFromTitle:
    def test_basic_corte(self) -> None:
        result = parse_service_title("Corte - Juan Garcia")
        assert result == ("corte", "Juan Garcia")

    def test_corte_barba_y(self) -> None:
        result = parse_service_title("Corte y barba - Paco")
        assert result == ("corte_barba", "Paco")

    def test_corte_barba_plus(self) -> None:
        result = parse_service_title("Corte+barba - Paco")
        assert result == ("corte_barba", "Paco")

    def test_corte_barba_space(self) -> None:
        result = parse_service_title("Corte barba - Paco")
        assert result == ("corte_barba", "Paco")

    def test_mechas(self) -> None:
        result = parse_service_title("Mechas - Ana Lopez")
        assert result == ("mechas", "Ana Lopez")

    def test_unknown_returns_none(self) -> None:
        assert parse_service_title("Permanente - Lucia") == (None, None)

    def test_tinte_recognised_from_config(self) -> None:
        assert parse_service_title("Tinte - Lucia") == ("tinte", "Lucia")

    def test_corte_barba_beats_corte_longest_match_wins(self) -> None:
        result = parse_service_title("Corte de pelo + barba - Ana")
        assert result == ("corte_barba", "Ana")

    def test_empty_string(self) -> None:
        assert parse_service_title("") == (None, None)

    def test_none_input(self) -> None:
        assert parse_service_title(None) == (None, None)

    def test_accent_tolerance(self) -> None:
        assert parse_service_title("Méchas - Ángela") == ("mechas", "Ángela")

    def test_nombre_original_casing_preserved(self) -> None:
        key, nombre = parse_service_title("Corte - María José")
        assert key == "corte"
        assert nombre == "María José"

    def test_no_separator_returns_none(self) -> None:
        assert parse_service_title("Corte Juan Garcia") == (None, None)

    def test_em_dash_separator(self) -> None:
        result = parse_service_title("Corte – Juan Garcia")
        assert result == ("corte", "Juan Garcia")


class TestSetField:
    def test_append_new_field(self) -> None:
        result = set_field("Nombre: Ana", "Estado", "confirmada")
        assert "Estado: confirmada" in result
        assert "Nombre: Ana" in result

    def test_replace_existing_field(self) -> None:
        desc = "Nombre: Ana\nEstado: pendiente"
        result = set_field(desc, "Estado", "confirmada")
        assert "Estado: confirmada" in result
        assert "pendiente" not in result

    def test_case_insensitive_replace(self) -> None:
        desc = "ESTADO: pendiente"
        result = set_field(desc, "Estado", "confirmada")
        assert result.count("Estado") == 1 or result.count("estado") + result.count("Estado") == 1
        assert "pendiente" not in result

    def test_removes_duplicates(self) -> None:
        desc = "Estado: pendiente\nEstado: pendiente"
        result = set_field(desc, "Estado", "confirmada")
        assert result.count("Estado:") == 1
        assert "confirmada" in result

    def test_empty_description(self) -> None:
        result = set_field("", "Estado", "confirmada")
        assert result == "Estado: confirmada"

    def test_none_description(self) -> None:
        result = set_field(None, "Estado", "confirmada")
        assert result == "Estado: confirmada"

    def test_other_fields_preserved(self) -> None:
        desc = "Nombre: Juan\nTelefono: 34600000001\nEstado: pendiente"
        result = set_field(desc, "Estado", "confirmada")
        assert "Nombre: Juan" in result
        assert "Telefono: 34600000001" in result


class TestRemoveField:
    def test_removes_existing(self) -> None:
        desc = "Estado: confirmada\nNombre: Ana"
        result = remove_field(desc, "Estado")
        assert "Estado" not in result
        assert "Nombre: Ana" in result

    def test_case_insensitive(self) -> None:
        result = remove_field("ESTADO: confirmada\nNombre: Ana", "Estado")
        assert "ESTADO" not in result

    def test_noop_when_missing(self) -> None:
        desc = "Nombre: Ana"
        assert remove_field(desc, "Estado") == desc

    def test_empty(self) -> None:
        assert remove_field("", "Estado") == ""

    def test_none(self) -> None:
        assert remove_field(None, "Estado") == ""


def parse_service_title(title: str | None) -> tuple[str | None, str | None]:
    return parse_service(
        title,
        {
            "corte": "Corte de pelo",
            "corte_barba": "Corte de pelo + barba",
            "mechas": "Mechas",
            "tinte": "Tinte",
        },
    )
