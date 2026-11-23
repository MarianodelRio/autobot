"""Alert kind -> runbook page (ADR-018).

Every alert `kind` raised by `autobot/ops/check.py` and `autobot/ops/containers.py` (and
the manual `deploy_*` ones) maps to a page under `docs/`. The panel shows it as «Ver
runbook» and links to the documentation site served at `/docs/`. The table in
`docs/incidencias/README.md` is the human-readable twin of this one.

Paths are relative to `docs/`, optionally with a `#section` anchor.
`tests/platform/ops/test_runbooks.py` checks that each file exists and that every kind in
the sources is covered here or listed in `NO_RUNBOOK`.
"""

DOCS_URL_PREFIX = "/docs/"

_RESOURCES = "incidencias/recursos-copias-y-certificado.md"

# Exact kinds.
RUNBOOKS: dict[str, str] = {
    "inbound_delay": "incidencias/cola-y-latido.md",
    "failed_jobs": "incidencias/cola-y-latido.md",
    "inbound_stuck": "incidencias/cola-y-latido.md",
    "outbound_stuck": "incidencias/envios-unknown.md",
    "outbound_failed": "incidencias/envios-unknown.md",
    "notification_failed": "incidencias/envios-unknown.md",
    "owner_unlinked": "incidencias/envios-unknown.md#avisos-retenidos",
    "provider_outage": "incidencias/envios-unknown.md",
    "calendar_outage": "incidencias/calendar.md",
    "check_failed": "incidencias/cola-y-latido.md",
    "registry": "incidencias/negocio-o-canal.md",
    "tenant_unavailable": "incidencias/negocio-o-canal.md",
    "auth": "incidencias/negocio-o-canal.md",
    "tenant_silent": "incidencias/negocio-o-canal.md#negocio-en-silencio",
    "webhook_unsubscribed": "incidencias/negocio-o-canal.md#webhook-sin-suscripcion",
    "webhook_errors": "incidencias/negocio-o-canal.md#webhook-sin-suscripcion",
    "number_quality": "incidencias/negocio-o-canal.md#calidad-del-numero",
    "containers_stale": "incidencias/contenedor-caido.md",
    "containers_restore": "procedimientos/restaurar.md",
    "deploy_aborted": "incidencias/volver-atras.md",
    "deploy_rollback": "incidencias/volver-atras.md",
    "backup_prune_overdue": "procedimientos/backups.md#caducar-snapshots",
    "disk": "procedimientos/mantenimiento.md#disco-lleno",
    "disk_critical": "procedimientos/mantenimiento.md#disco-lleno",
    "inodes": f"{_RESOURCES}#inodos-agotados",
    "inodes_critical": f"{_RESOURCES}#inodos-agotados",
    "memory_high": f"{_RESOURCES}#memoria-swap-o-carga-altas",
    "swap_high": f"{_RESOURCES}#memoria-swap-o-carga-altas",
    "load_high": f"{_RESOURCES}#memoria-swap-o-carga-altas",
    "backup_stale": f"{_RESOURCES}#backup-atrasado-o-fallido",
    "tls_expiring": f"{_RESOURCES}#certificado-a-punto-de-caducar",
    "tls_expiring_critical": f"{_RESOURCES}#certificado-a-punto-de-caducar",
    "tls_invalid": f"{_RESOURCES}#certificado-a-punto-de-caducar",
    "queue_lag_unknown": "incidencias/cola-y-latido.md",
}

# Kinds with a variable suffix (`calendar:<channel>`, `container_down:<service>`...),
# matched by prefix.
PREFIX_RUNBOOKS: dict[str, str] = {
    "auth:": "incidencias/negocio-o-canal.md",
    "bot:": "incidencias/negocio-o-canal.md",
    "errors:": "incidencias/negocio-o-canal.md",
    "health:": "incidencias/negocio-o-canal.md",
    "calendar:": "incidencias/calendar.md",
    "sweep:": "incidencias/calendar.md",
    "container_": "incidencias/contenedor-caido.md",
    "queue_lag:": "incidencias/cola-y-latido.md",
}

# Kinds that deliberately have no runbook: a message-volume threshold, nothing to repair.
NO_RUNBOOK: frozenset[str] = frozenset({"billing", "billing:demo_wa"})


def _url(doc_path: str) -> str:
    file, _, anchor = doc_path.partition("#")
    page = file.removesuffix(".md").removesuffix("README").rstrip("/")
    url = f"{DOCS_URL_PREFIX}{page}/" if page else DOCS_URL_PREFIX
    return f"{url}#{anchor}" if anchor else url


def runbook_path(kind: str) -> str | None:
    """The `docs/`-relative page (and optional `#anchor`) for an alert kind, or None."""
    if kind in NO_RUNBOOK:
        return None
    if kind in RUNBOOKS:
        return RUNBOOKS[kind]
    for prefix, path in PREFIX_RUNBOOKS.items():
        if kind.startswith(prefix):
            return path
    return None


def runbook_url(kind: str) -> str | None:
    """The documentation URL (`/docs/<page>/`) for an alert kind, or None."""
    path = runbook_path(kind)
    return _url(path) if path else None
