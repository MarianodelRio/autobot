"""Pure assessment of the container snapshot written by deploy/scripts/containers.sh."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

EXPECTED_SERVICES = (
    "caddy",
    "web",
    "worker-inbound",
    "worker-outbound",
    "panel",
    "db",
    "victorialogs",
)
APP_IMAGE_SERVICES = frozenset({"web", "worker-inbound", "worker-outbound", "panel"})
NON_CRITICAL = frozenset({"victorialogs"})  # same rule as deploy.sh: logs are never critical
STALE_AFTER = timedelta(minutes=3)
RESTART_WINDOW = timedelta(minutes=30)  # = ops_alert's cooldown: one alert per incident
KIND_MAX_LENGTH = 64  # ops_alert.kind is max_length=64

LEVEL_RANK = {"ok": 0, "notice": 1, "warning": 2, "critical": 3}


@dataclass(frozen=True)
class Container:
    name: str
    service: str
    status: str
    health: str
    restart_count: int
    oom_killed: bool
    exit_code: int
    started_at: datetime | None
    finished_at: datetime | None
    image: str


@dataclass(frozen=True)
class Snapshot:
    generated_at: datetime
    maintenance: str | None
    containers: tuple[Container, ...]


@dataclass(frozen=True)
class ServiceState:
    service: str
    name: str | None
    status: str
    health: str
    restart_count: int
    oom_killed: bool
    started_at: datetime | None
    image_tag: str | None
    image_matches: bool | None
    level: str
    reason: str | None


@dataclass(frozen=True)
class Assessment:
    available: bool
    generated_at: datetime | None
    stale: bool
    maintenance: str | None
    services: list[ServiceState]
    findings: list[tuple[str, str]]


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    # A naive value would raise TypeError when compared with the aware `now`.
    return parsed if parsed.utcoffset() is not None else None


def _parse_container(data: Any) -> Container | None:
    if not isinstance(data, dict):
        return None
    try:
        name, service, status, health, image = (
            data["name"],
            data["service"],
            data["status"],
            data["health"],
            data["image"],
        )
        restart_count, exit_code, oom_killed = (
            data["restart_count"],
            data["exit_code"],
            data["oom_killed"],
        )
    except KeyError:
        return None
    if not all(isinstance(v, str) for v in (name, service, status, health, image)):
        return None
    if not isinstance(restart_count, int) or not isinstance(exit_code, int):
        return None
    if not isinstance(oom_killed, bool):
        return None
    started_at, finished_at = data.get("started_at"), data.get("finished_at")
    if started_at is not None and not isinstance(started_at, str):
        return None
    if finished_at is not None and not isinstance(finished_at, str):
        return None
    return Container(
        name=name,
        service=service,
        status=status,
        health=health,
        restart_count=restart_count,
        oom_killed=oom_killed,
        exit_code=exit_code,
        started_at=_parse_datetime(started_at),
        finished_at=_parse_datetime(finished_at),
        image=image,
    )


def read_snapshot(state_dir: Path) -> Snapshot | None:
    """`None` on anything unexpected (missing file, bad JSON, wrong version, wrong
    field types); never raises, so a corrupt snapshot degrades to "unavailable"
    rather than crashing the panel or ops_check."""
    try:
        text = (state_dir / "containers.json").read_text()
    except OSError:
        return None
    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or data.get("version") != 1:
        return None
    generated_at = _parse_datetime(data.get("generated_at"))
    if generated_at is None:
        return None
    maintenance = data.get("maintenance")
    if maintenance is not None and maintenance not in ("deploy", "restore"):
        return None
    raw_containers = data.get("containers")
    if not isinstance(raw_containers, list):
        return None
    containers: list[Container] = []
    for raw in raw_containers:
        container = _parse_container(raw)
        if container is None:
            return None
        containers.append(container)
    return Snapshot(
        generated_at=generated_at, maintenance=maintenance, containers=tuple(containers)
    )


def image_tag(image: str) -> str | None:
    """The tag, only when its ':' comes after the image's last '/' (so a registry
    port, e.g. "registry:5000/repo", is never mistaken for one); the digest of a
    pinned image is stripped first."""
    tail = image.rsplit("/", 1)[-1].split("@", 1)[0]
    if ":" not in tail:
        return None
    return tail.rsplit(":", 1)[1] or None


def _short(value: str | None) -> str:
    return (value or "?")[:12]


def _stale_row(service: str, container: Container | None) -> ServiceState:
    if container is None:
        return ServiceState(
            service=service,
            name=None,
            status="missing",
            health="none",
            restart_count=0,
            oom_killed=False,
            started_at=None,
            image_tag=None,
            image_matches=None,
            level="unknown",
            reason="Datos desactualizados",
        )
    return ServiceState(
        service=service,
        name=container.name,
        status=container.status,
        health=container.health,
        restart_count=container.restart_count,
        oom_killed=container.oom_killed,
        started_at=container.started_at,
        image_tag=image_tag(container.image),
        image_matches=None,
        level="unknown",
        reason="Datos desactualizados",
    )


def _row(
    service: str, container: Container | None, *, now: datetime, release_sha: str, expected: bool
) -> tuple[ServiceState, list[tuple[str, str]]]:
    findings: list[tuple[str, str]] = []
    non_critical = service in NON_CRITICAL
    down_level = "warning" if non_critical else "critical"
    down_emoji = "🟠" if non_critical else "🔴"
    level, reason = "ok", None

    def consider(new_level: str, new_reason: str) -> None:
        nonlocal level, reason
        if LEVEL_RANK[new_level] > LEVEL_RANK[level]:
            level, reason = new_level, new_reason

    if container is None:
        consider(down_level, "No existe")
        findings.append(
            (f"container_down:{service}", f"{down_emoji} Contenedor {service}: no existe.")
        )
        return (
            ServiceState(
                service=service,
                name=None,
                status="missing",
                health="none",
                restart_count=0,
                oom_killed=False,
                started_at=None,
                image_tag=None,
                image_matches=None,
                level=level,
                reason=reason,
            ),
            findings,
        )

    tag = image_tag(container.image)
    if not expected:
        # An orphan only needs removing: a stopped one must not page as a service down.
        return (
            ServiceState(
                service=service,
                name=container.name,
                status=container.status,
                health=container.health,
                restart_count=container.restart_count,
                oom_killed=container.oom_killed,
                started_at=container.started_at,
                image_tag=tag,
                image_matches=None,
                level="warning",
                reason="No esperado: ¿huérfano de un despliegue?",
            ),
            [
                (
                    f"container_unexpected:{service}",
                    f"🟠 Contenedor {service} no esperado: ¿huérfano de un despliegue?",
                )
            ],
        )

    running = container.status == "running"
    if container.status == "restarting":
        consider(down_level, "Reiniciándose en bucle")
        findings.append(
            (
                f"container_down:{service}",
                f"{down_emoji} Contenedor {service}: reiniciándose en bucle.",
            )
        )
    elif not running:
        oom = ", sin memoria" if container.oom_killed else ""
        consider(down_level, f"Parado (código {container.exit_code}{oom})")
        findings.append(
            (
                f"container_down:{service}",
                f"{down_emoji} Contenedor {service}: parado (código {container.exit_code}{oom}).",
            )
        )
    if running and container.health == "unhealthy":
        consider("critical", "Healthcheck fallando")
        findings.append(
            (f"container_unhealthy:{service}", f"🔴 Contenedor {service}: healthcheck fallando.")
        )
    if (
        running
        and container.restart_count > 0
        and container.started_at is not None
        and container.started_at >= now - RESTART_WINDOW
    ):
        oom = ", el último sin memoria" if container.oom_killed else ""
        consider(
            "warning",
            f"Se ha reiniciado ({container.restart_count} reinicios desde su creación{oom})",
        )
        findings.append(
            (
                f"container_restarted:{service}",
                f"🟠 Contenedor {service}: se ha reiniciado"
                f" ({container.restart_count} reinicios desde su creación{oom}).",
            )
        )
    image_matches: bool | None = None
    if service in APP_IMAGE_SERVICES and release_sha:
        image_matches = tag == release_sha
        if not image_matches:
            consider(
                "warning", f"Imagen {_short(tag)} distinta de la desplegada {_short(release_sha)}"
            )
            findings.append(
                (
                    f"container_image:{service}",
                    f"🟠 Contenedor {service}: imagen {_short(tag)}"
                    f" distinta de la desplegada {_short(release_sha)}.",
                )
            )
    if running and container.health == "starting":
        consider("notice", "Arrancando")
    return (
        ServiceState(
            service=service,
            name=container.name,
            status=container.status,
            health=container.health,
            restart_count=container.restart_count,
            oom_killed=container.oom_killed,
            started_at=container.started_at,
            image_tag=tag,
            image_matches=image_matches,
            level=level,
            reason=reason,
        ),
        findings,
    )


def _extend(findings: list[tuple[str, str]], seen: set[str], new: list[tuple[str, str]]) -> None:
    for kind, text in new:
        kind = kind[:KIND_MAX_LENGTH]
        if kind in seen:
            continue
        seen.add(kind)
        findings.append((kind, text))


def assess(snapshot: Snapshot | None, *, now: datetime, release_sha: str) -> Assessment:
    if snapshot is None:
        return Assessment(
            available=False,
            generated_at=None,
            stale=False,
            maintenance=None,
            services=[],
            findings=[
                (
                    "containers_stale",
                    "🟠 Sin estado de contenedores: revisa autobot-containers.timer.",
                )
            ],
        )
    by_service: dict[str, list[Container]] = {}
    for container in snapshot.containers:
        by_service.setdefault(container.service, []).append(container)
    unexpected_services = sorted(s for s in by_service if s not in EXPECTED_SERVICES)

    if snapshot.generated_at < now - STALE_AFTER:
        services = []
        none_fallback: list[Container | None] = [None]
        for service in (*EXPECTED_SERVICES, *unexpected_services):
            for maybe_container in by_service.get(service) or none_fallback:
                services.append(_stale_row(service, maybe_container))
        return Assessment(
            available=True,
            generated_at=snapshot.generated_at,
            stale=True,
            maintenance=snapshot.maintenance,
            services=services,
            findings=[
                (
                    "containers_stale",
                    "🟠 Estado de contenedores sin actualizar desde hace más de 3 minutos:"
                    " revisa autobot-containers.timer.",
                )
            ],
        )

    services = []
    findings: list[tuple[str, str]] = []
    seen_kinds: set[str] = set()
    for service in EXPECTED_SERVICES:
        containers = by_service.get(service)
        if not containers:
            row, row_findings = _row(service, None, now=now, release_sha=release_sha, expected=True)
            services.append(row)
            _extend(findings, seen_kinds, row_findings)
            continue
        for container in containers:
            row, row_findings = _row(
                service, container, now=now, release_sha=release_sha, expected=True
            )
            services.append(row)
            _extend(findings, seen_kinds, row_findings)
    for service in unexpected_services:
        for container in by_service[service]:
            row, row_findings = _row(
                service, container, now=now, release_sha=release_sha, expected=False
            )
            services.append(row)
            _extend(findings, seen_kinds, row_findings)

    if snapshot.maintenance == "deploy":
        findings = []
    elif snapshot.maintenance == "restore":
        findings = [
            ("containers_restore", "🟠 Restauración a medias: existe var/.restore-incomplete.")
        ]

    return Assessment(
        available=True,
        generated_at=snapshot.generated_at,
        stale=False,
        maintenance=snapshot.maintenance,
        services=services,
        findings=findings,
    )
