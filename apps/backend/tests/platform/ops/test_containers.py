"""Pure assessment of the container snapshot, against a fake var/state/ops directory."""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from autobot.ops import containers

NOW = datetime(2026, 11, 11, 10, 0, 0, tzinfo=UTC)


def container(
    service: str,
    *,
    name: str | None = None,
    status: str = "running",
    health: str = "healthy",
    restart_count: int = 0,
    oom_killed: bool = False,
    exit_code: int = 0,
    started_at: str | None = "2026-11-11T09:00:00Z",
    finished_at: str | None = None,
    image: str = "ghcr.io/owner/autobot:abc123",
) -> dict[str, object]:
    return {
        "name": name or f"autobot-{service}-1",
        "service": service,
        "status": status,
        "health": health,
        "restart_count": restart_count,
        "oom_killed": oom_killed,
        "exit_code": exit_code,
        "started_at": started_at,
        "finished_at": finished_at,
        "image": image,
    }


def write_snapshot(
    state_dir: Path,
    *,
    rows: list[dict[str, object]],
    maintenance: str | None = None,
    generated_at: str | None = None,
) -> None:
    doc = {
        "version": 1,
        "generated_at": generated_at or NOW.isoformat(),
        "project": "autobot",
        "maintenance": maintenance,
        "containers": rows,
    }
    (state_dir / "containers.json").write_text(json.dumps(doc))


def all_services(*, exclude: tuple[str, ...] = ()) -> list[dict[str, object]]:
    return [
        container(service) for service in containers.EXPECTED_SERVICES if service not in exclude
    ]


# ── read_snapshot ─────────────────────────────────────────────────────────


def test_read_snapshot_missing_file_is_none(tmp_path: Path) -> None:
    assert containers.read_snapshot(tmp_path) is None


def test_read_snapshot_corrupt_json_is_none(tmp_path: Path) -> None:
    (tmp_path / "containers.json").write_text("not json")
    assert containers.read_snapshot(tmp_path) is None


def test_read_snapshot_unknown_version_is_none(tmp_path: Path) -> None:
    write_snapshot(tmp_path, rows=[])
    data = json.loads((tmp_path / "containers.json").read_text())
    data["version"] = 2
    (tmp_path / "containers.json").write_text(json.dumps(data))
    assert containers.read_snapshot(tmp_path) is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.pop("generated_at"),
        lambda d: d["containers"].__setitem__(0, {"name": "x"}),  # missing fields
        lambda d: d["containers"][0].__setitem__("restart_count", "not-a-number"),
        lambda d: d.__setitem__("maintenance", "rollback"),  # not deploy/restore/null
        lambda d: d.__setitem__("containers", "not-a-list"),
    ],
)
def test_read_snapshot_bad_types_are_none(
    tmp_path: Path, mutate: Callable[[dict[str, object]], object]
) -> None:
    write_snapshot(tmp_path, rows=[container("web")])
    data = json.loads((tmp_path / "containers.json").read_text())
    mutate(data)
    (tmp_path / "containers.json").write_text(json.dumps(data))
    assert containers.read_snapshot(tmp_path) is None


def test_read_snapshot_parses_a_valid_document(tmp_path: Path) -> None:
    write_snapshot(tmp_path, rows=[container("web")], maintenance="deploy")
    snapshot = containers.read_snapshot(tmp_path)
    assert snapshot is not None
    assert snapshot.maintenance == "deploy"
    assert snapshot.generated_at == NOW
    assert len(snapshot.containers) == 1
    assert snapshot.containers[0].service == "web"
    assert snapshot.containers[0].started_at == datetime(2026, 11, 11, 9, 0, tzinfo=UTC)


def test_read_snapshot_null_dates_parse_as_none(tmp_path: Path) -> None:
    write_snapshot(tmp_path, rows=[container("web", started_at=None, finished_at=None)])
    snapshot = containers.read_snapshot(tmp_path)
    assert snapshot is not None
    assert snapshot.containers[0].started_at is None
    assert snapshot.containers[0].finished_at is None


# ── image_tag ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("image", "tag"),
    [
        ("ghcr.io/owner/autobot:abc123", "abc123"),
        ("postgres:18@sha256:" + "a" * 64, "18"),
        ("registry.local:5000/owner/autobot", None),  # port, not a tag
        ("autobot", None),
        ("ghcr.io/owner/autobot:", None),
    ],
)
def test_image_tag(image: str, tag: str | None) -> None:
    assert containers.image_tag(image) == tag


# ── assess: availability and staleness ──────────────────────────────────


def test_assess_without_a_snapshot_is_unavailable() -> None:
    result = containers.assess(None, now=NOW, release_sha="abc")
    assert result.available is False
    assert result.services == []
    assert result.findings == [
        ("containers_stale", "🟠 Sin estado de contenedores: revisa autobot-containers.timer.")
    ]


def test_assess_stale_snapshot_marks_every_service_unknown(tmp_path: Path) -> None:
    write_snapshot(
        tmp_path, rows=all_services(), generated_at=(NOW - timedelta(minutes=4)).isoformat()
    )
    snapshot = containers.read_snapshot(tmp_path)
    result = containers.assess(snapshot, now=NOW, release_sha="abc")
    assert result.stale is True
    assert {row.level for row in result.services} == {"unknown"}
    assert all(row.reason == "Datos desactualizados" for row in result.services)
    assert [kind for kind, _ in result.findings] == ["containers_stale"]


def test_assess_fresh_snapshot_is_not_stale(tmp_path: Path) -> None:
    write_snapshot(
        tmp_path, rows=all_services(), generated_at=(NOW - timedelta(minutes=2)).isoformat()
    )
    snapshot = containers.read_snapshot(tmp_path)
    result = containers.assess(snapshot, now=NOW, release_sha="")
    assert result.stale is False
    assert all(row.level == "ok" for row in result.services if row.service != "victorialogs")


# ── assess: per-row rules ─────────────────────────────────────────────────


def _snapshot_from_rows(
    rows: list[dict[str, object]], *, maintenance: str | None
) -> containers.Snapshot:
    parsed = [containers._parse_container(row) for row in rows]
    assert all(p is not None for p in parsed)
    return containers.Snapshot(
        generated_at=NOW,
        maintenance=maintenance,
        containers=tuple(p for p in parsed if p is not None),
    )


def _assess(
    rows: list[dict[str, object]], *, maintenance: str | None = None, release_sha: str = ""
) -> containers.Assessment:
    return containers.assess(
        _snapshot_from_rows(rows, maintenance=maintenance), now=NOW, release_sha=release_sha
    )


def test_missing_expected_service_is_critical() -> None:
    rows = [container(s) for s in containers.EXPECTED_SERVICES if s != "web"]
    result = _assess(rows)
    web = next(row for row in result.services if row.service == "web")
    assert web.level == "critical" and web.status == "missing"
    assert ("container_down:web", "🔴 Contenedor web: no existe.") in result.findings


def test_missing_non_critical_service_is_warning() -> None:
    rows = [container(s) for s in containers.EXPECTED_SERVICES if s != "victorialogs"]
    result = _assess(rows)
    logs = next(row for row in result.services if row.service == "victorialogs")
    assert logs.level == "warning"
    assert (
        "container_down:victorialogs",
        "🟠 Contenedor victorialogs: no existe.",
    ) in result.findings


def test_restarting_container_is_critical() -> None:
    result = _assess([container("web", status="restarting")])
    web = next(row for row in result.services if row.service == "web")
    assert web.level == "critical"
    assert ("container_down:web", "🔴 Contenedor web: reiniciándose en bucle.") in result.findings


def test_exited_container_reports_exit_code_and_oom() -> None:
    result = _assess([container("web", status="exited", exit_code=137, oom_killed=True)])
    web = next(row for row in result.services if row.service == "web")
    assert web.level == "critical"
    assert (
        "container_down:web",
        "🔴 Contenedor web: parado (código 137, sin memoria).",
    ) in result.findings


def test_unhealthy_running_container_is_critical() -> None:
    result = _assess([container("web", health="unhealthy")])
    web = next(row for row in result.services if row.service == "web")
    assert web.level == "critical"
    assert (
        "container_unhealthy:web",
        "🔴 Contenedor web: healthcheck fallando.",
    ) in result.findings


def test_recent_restart_is_a_warning_without_hiding_an_old_one() -> None:
    recent = _assess(
        [container("web", restart_count=2, started_at=(NOW - timedelta(minutes=5)).isoformat())]
    )
    web = next(row for row in recent.services if row.service == "web")
    assert web.level == "warning"
    assert web.restart_count == 2
    assert any(kind == "container_restarted:web" for kind, _ in recent.findings)

    old = _assess(
        [container("web", restart_count=2, started_at=(NOW - timedelta(hours=2)).isoformat())]
    )
    web_old = next(row for row in old.services if row.service == "web")
    assert web_old.level == "ok"  # still shown in the row, but no finding
    assert web_old.restart_count == 2
    assert not any(kind == "container_restarted:web" for kind, _ in old.findings)


def test_image_mismatch_is_a_warning_only_for_app_services() -> None:
    result = _assess(
        [container("web", image="ghcr.io/owner/autobot:old"), container("db", image="postgres:18")],
        release_sha="new",
    )
    web = next(row for row in result.services if row.service == "web")
    db = next(row for row in result.services if row.service == "db")
    assert web.image_matches is False and web.level == "warning"
    assert db.image_matches is None  # db is not an APP_IMAGE_SERVICES member
    assert any(kind == "container_image:web" for kind, _ in result.findings)


def test_no_release_sha_skips_the_image_check() -> None:
    result = _assess([container("web", image="ghcr.io/owner/autobot:old")], release_sha="")
    web = next(row for row in result.services if row.service == "web")
    assert web.image_matches is None
    assert not any(kind.startswith("container_image") for kind, _ in result.findings)


def test_starting_health_is_a_notice_with_no_finding() -> None:
    result = _assess([container("web", health="starting")])
    web = next(row for row in result.services if row.service == "web")
    assert web.level == "notice" and web.reason == "Arrancando"
    assert not any(
        kind.startswith("container_") and kind.endswith(":web") for kind, _ in result.findings
    )


def test_unexpected_service_is_a_warning_regardless_of_state() -> None:
    rows = all_services() + [container("worker", name="autobot-worker-1")]
    result = _assess(rows)
    worker = next(row for row in result.services if row.service == "worker")
    assert worker.level == "warning"
    assert (
        "container_unexpected:worker",
        "🟠 Contenedor worker no esperado: ¿huérfano de un despliegue?",
    ) in result.findings


def test_stopped_orphan_is_only_unexpected_never_down() -> None:
    rows = all_services() + [
        container("worker", name="autobot-worker-1", status="exited", exit_code=137)
    ]
    result = _assess(rows)
    worker = next(row for row in result.services if row.service == "worker")
    assert worker.level == "warning"
    assert [kind for kind, _ in result.findings] == ["container_unexpected:worker"]


def test_naive_dates_are_rejected_instead_of_crashing_assess(tmp_path: Path) -> None:
    write_snapshot(tmp_path, rows=all_services(), generated_at="2026-11-11T10:00:00")
    assert containers.read_snapshot(tmp_path) is None
    write_snapshot(tmp_path, rows=[container("web", started_at="2026-11-11T09:59:00")])
    snapshot = containers.read_snapshot(tmp_path)
    assert snapshot is not None and snapshot.containers[0].started_at is None
    containers.assess(snapshot, now=NOW, release_sha="")


def test_multiple_containers_for_one_service_deduplicate_the_same_kind() -> None:
    rows = [
        container("worker-outbound", name="autobot-worker-outbound-1", health="unhealthy"),
        container("worker-outbound", name="autobot-worker-outbound-2", health="unhealthy"),
    ]
    result = _assess(rows)
    unhealthy_findings = [
        k for k, _ in result.findings if k == "container_unhealthy:worker-outbound"
    ]
    assert len(unhealthy_findings) == 1
    assert sum(1 for row in result.services if row.service == "worker-outbound") == 2


def test_kind_is_clipped_to_64_characters() -> None:
    long_service = "x" * 100
    rows = all_services() + [container(long_service)]
    result = _assess(rows)
    unexpected = [k for k, _ in result.findings if k.startswith("container_unexpected:")]
    assert unexpected and len(unexpected[0]) <= 64


# ── assess: maintenance windows ───────────────────────────────────────────


def test_deploy_maintenance_suppresses_findings_but_keeps_rows() -> None:
    rows = [container(s) for s in containers.EXPECTED_SERVICES if s != "web"]
    result = _assess(rows, maintenance="deploy")
    assert result.findings == []
    web = next(row for row in result.services if row.service == "web")
    assert web.level == "critical"  # the row still tells the truth


def test_restore_maintenance_reports_only_the_restore_finding() -> None:
    rows = [container(s) for s in containers.EXPECTED_SERVICES if s != "web"]
    result = _assess(rows, maintenance="restore")
    assert result.findings == [
        ("containers_restore", "🟠 Restauración a medias: existe var/.restore-incomplete.")
    ]
