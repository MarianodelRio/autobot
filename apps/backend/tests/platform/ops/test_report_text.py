"""The operator's texts (ADR-029), from hand-made `ops.report` data: no database."""

from datetime import datetime, timedelta

from autobot.ops import report_text
from autobot.ops.report import (
    MADRID,
    Backups,
    Cleanup,
    Day,
    Figures,
    IncidentLine,
    PlatformStatus,
    Resources,
    Services,
    TenantFigures,
    TenantLine,
)
from core.limits import MAX_TEXT

NOW = datetime(2026, 11, 24, 14, 5, tzinfo=MADRID)
GOOD_BACKUPS = Backups(
    finished_at=NOW - timedelta(minutes=22),
    ok=True,
    stale=False,
    last_prune_at=NOW - timedelta(days=3),
    prune_overdue=False,
)
CLEANUP = Cleanup(enabled=True, last_at=NOW.replace(hour=4, minute=0), ok=True)


def status(**changes: object) -> PlatformStatus:
    fields: dict[str, object] = {
        "level": "ok",
        "incidents": [],
        "services": Services(running=10, total=10, stale=False, failing=[]),
        "resources": Resources(NOW, disk_pct=34.2, mem_pct=51.8, db_bytes=int(1.2 * 1024**3)),
        "backups": GOOD_BACKUPS,
        "cleanup": CLEANUP,
        "troubled": [],
    }
    fields.update(changes)
    return PlatformStatus(**fields)  # type: ignore[arg-type]


def tenant(name: str, **changes: object) -> TenantLine:
    fields: dict[str, object] = {
        "name": name,
        "slug": name.lower(),
        "demo": False,
        "status": "active",
        "level": "ok",
        "reasons": [],
        "last_activity_at": NOW - timedelta(hours=2),
    }
    fields.update(changes)
    return TenantLine(**fields)  # type: ignore[arg-type]


def test_formatting_is_spanish() -> None:
    assert report_text.number(1240) == "1.240"
    assert report_text.size(int(1.2 * 1024**3)) == "1,2 GB"
    assert report_text.size(300 * 1024**2) == "300 MB"
    assert report_text.ago(NOW - timedelta(minutes=22), NOW) == "hace 22 min"
    assert report_text.ago(NOW - timedelta(hours=5), NOW) == "hace 5 h"
    assert report_text.ago(NOW - timedelta(days=3), NOW) == "hace 3 días"
    assert report_text.clock(NOW.replace(hour=3, minute=0), NOW) == "hoy a las 03:00"
    assert report_text.clock(NOW - timedelta(days=1), NOW) == "ayer a las 14:05"
    assert report_text.clock(NOW - timedelta(days=4), NOW) == "el 20/11 a las 14:05"
    assert report_text.weekday_date(NOW) == "martes 24/11"


def test_a_healthy_status() -> None:
    text = report_text.status_text(status(), NOW)
    assert text.splitlines() == [
        "✅ *Todo en orden*",
        "",
        "Servicios: 10/10 en marcha",
        "Disco 34 % · Memoria 52 % · BD 1,2 GB",
        "Último backup: hace 22 min ✅",
        "Limpieza nocturna: ✅ hoy a las 04:00",
        "Incidencias abiertas: ninguna",
    ]


def test_a_status_with_problems_says_what_and_where() -> None:
    alerts = [
        IncidentLine("critical", "🔴 wa: el canal no responde", NOW - timedelta(minutes=10)),
        IncidentLine("warning", "🟠 Disco por encima del 80 %.", NOW - timedelta(hours=1)),
    ]
    text = report_text.status_text(
        status(
            level="critical",
            incidents=alerts,
            services=Services(running=9, total=10, stale=False, failing=["worker-inbound"]),
            backups=Backups(NOW - timedelta(hours=2), False, True, None, True),
            cleanup=Cleanup(enabled=True, last_at=NOW - timedelta(days=1), ok=False),
            troubled=["Wa"],
        ),
        NOW,
    )
    assert text.startswith("🔴 *Hay problemas*")
    assert "Servicios: 9/10 en marcha ⚠️ worker-inbound" in text
    assert "Último backup: ❌ falló, hace 2 h" in text
    assert "Limpieza nocturna: ❌ falló ayer a las 14:05" in text
    assert "Incidencias abiertas: 2 (1 🔴, 1 🟠)" in text
    assert "Clientes con problemas: 1 (Wa)" in text


def test_missing_data_is_said_never_invented() -> None:
    text = report_text.status_text(
        status(
            services=None,
            resources=None,
            backups=Backups(None, None, False, None, False),
            cleanup=Cleanup(enabled=False, last_at=None, ok=None),
        ),
        NOW,
    )
    assert "Servicios: sin datos" in text
    assert "Recursos: sin muestra reciente" in text
    assert "Último backup: sin datos" in text
    assert "Limpieza nocturna: desactivada" in text


def test_incidents_list_the_open_ones_and_cap_the_rest() -> None:
    assert report_text.incidents_text([], NOW) == "🚨 *Incidencias abiertas*\n\nNinguna. ✅"
    many = [IncidentLine("warning", f"🟠 fallo {i}", NOW - timedelta(hours=1)) for i in range(40)]
    text = report_text.incidents_text(many, NOW)
    assert text.startswith("🚨 *Incidencias abiertas: 40*")
    assert "🟠 fallo 0\n   desde hace 1 h" in text
    assert "fallo 15" not in text and "… y 25 incidencias más en el panel." in text
    assert len(text) <= MAX_TEXT


def test_a_reopened_event_says_how_many_are_new() -> None:
    line = IncidentLine("warning", "🟠 wa: rechazados (3).", NOW - timedelta(hours=1), 3)
    text = report_text.incidents_text([line], NOW)
    assert "desde hace 1 h · 3 nuevos desde tu revisión" in text


def test_a_day_with_totals_busiest_first_and_demos_together() -> None:
    day = Day(
        start=NOW.replace(hour=0, minute=0),
        end=NOW,
        tenants=[
            TenantFigures("Lola", False, Figures(received=340, sent=318, failed=2)),
            TenantFigures("Bus Norte", False, Figures(received=900, sent=880, new_contacts=37)),
            TenantFigures("Quieto", False, Figures()),
            TenantFigures("Demo bus", True, Figures(received=12, sent=11)),
        ],
    )
    assert report_text.day_text(day, report_text.today_title(NOW)).splitlines() == [
        "📊 *Hoy*, hasta las 14:05",
        "",
        "Recibidos 1.252 · Enviados 1.209 · Fallos 2 · Contactos nuevos 37",
        "",
        "Bus Norte: 900 recibidos · 880 enviados",
        "Lola: 340 recibidos · 318 enviados · ⚠️ 2 fallos",
        "Demos: 12 recibidos · 11 enviados",
    ]


def test_a_day_without_messages() -> None:
    day = Day(start=NOW, end=NOW, tenants=[TenantFigures("Lola", False, Figures())])
    assert report_text.day_text(day, "📊 *Hoy*") == "📊 *Hoy*\n\nSin mensajes."


def test_tenants_put_problems_first_and_summarise_demos() -> None:
    lines = [
        tenant("Bus Norte"),
        tenant("Lola", level="critical", reasons=["Canal principal desactivado"]),
        tenant("Nuevo", status="onboarding", last_activity_at=None),
        tenant("Demo bus", demo=True),
        tenant("Demo salón", demo=True, level="warning"),
    ]
    text = report_text.tenants_text(lines, NOW)
    assert text.startswith("🏪 *Clientes*: 2 activos · 1 en alta · 0 en pausa\n\n")
    assert text.index("🔴 Lola · activo") < text.index("🟢 Bus Norte · activo")
    assert "🔴 Lola · activo\n   último mensaje hace 2 h\n   Canal principal desactivado" in text
    assert "🟢 Nuevo · en alta\n   sin mensajes" in text
    assert text.endswith("Demos: 2, 1 con problemas")


def test_many_tenants_still_fit_one_text() -> None:
    lines = [tenant(f"Negocio con un nombre bastante largo {i}") for i in range(300)]
    text = report_text.tenants_text(lines, NOW)
    assert "… y 285 clientes más en el panel." in text
    assert len(text) <= MAX_TEXT


def test_backups_and_cleanup() -> None:
    text = report_text.backups_text(GOOD_BACKUPS, CLEANUP, NOW)
    assert text.splitlines() == [
        "💾 *Copias y limpieza*",
        "",
        "Último backup: hace 22 min ✅",
        "Caducar copias: hace 3 días ✅",
        "Limpieza nocturna: ✅ hoy a las 04:00",
    ]
    overdue = Backups(NOW, True, False, NOW - timedelta(days=12), True)
    assert "Caducar copias: hace 12 días ⚠️ toca make backup-prune" in report_text.backups_text(
        overdue, CLEANUP, NOW
    )


def test_the_daily_summary_is_status_and_yesterday() -> None:
    yesterday = Day(
        start=datetime(2026, 11, 23, tzinfo=MADRID),
        end=datetime(2026, 11, 24, tzinfo=MADRID),
        tenants=[TenantFigures("Lola", False, Figures(received=5, sent=5))],
    )
    text = report_text.daily_text(status(), yesterday, NOW)
    assert text.startswith("☀️ *Resumen diario*\n\n✅ *Todo en orden*")
    assert "📊 *Ayer*, lunes 23/11\n\nRecibidos 5 · Enviados 5" in text
    assert len(text) <= MAX_TEXT
