"""Hardening of the production compose files: images pinned, no slow-query parameters
in the log, and the two hand-rolled containers (caddy, db) capability-dropped."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[4]
BASE = yaml.safe_load((ROOT / "deploy/compose/compose.yaml").read_text())
PROD = yaml.safe_load((ROOT / "deploy/compose/compose.prod.yaml").read_text())
LOCAL = yaml.safe_load((ROOT / "deploy/compose/compose.local.yaml").read_text())
WORKERS = ("worker-inbound", "worker-calendar", "worker-periodic", "worker-outbound")


def test_db_image_is_pinned_by_digest() -> None:
    assert "@sha256:" in BASE["services"]["db"]["image"]


def test_victorialogs_caps_disk_usage_independently_of_time_retention() -> None:
    """A11: a safety net against the 31d time-based retention filling the disk."""
    command = " ".join(BASE["services"]["victorialogs"]["command"])
    assert "-retentionPeriod=31d" in command
    assert "-retention.maxDiskSpaceUsageBytes=" in command


def test_caddy_image_is_pinned_by_digest() -> None:
    assert "@sha256:" in PROD["services"]["caddy"]["image"]


def test_slow_query_log_never_includes_parameter_values() -> None:
    command = " ".join(PROD["services"]["db"]["command"])
    assert "log_parameter_max_length=0" in command
    assert "log_parameter_max_length_on_error=0" in command


def _db_settings() -> dict[str, str]:
    command = PROD["services"]["db"]["command"]
    return dict(item.split("=", 1) for item in command if "=" in item and not item.startswith("-"))


def test_postgres_is_tuned_for_the_4_vcpu_8_gb_target() -> None:
    settings = _db_settings()
    assert settings["shared_buffers"] == "1GB"
    assert settings["effective_cache_size"] == "4GB"
    assert settings["work_mem"] == "8MB"
    assert settings["maintenance_work_mem"] == "256MB"
    assert settings["random_page_cost"] == "1.1"
    assert settings["effective_io_concurrency"] == "200"
    assert settings["wal_compression"] == "on"
    assert settings["checkpoint_completion_target"] == "0.9"
    assert settings["max_wal_size"] == "2GB"
    assert settings["max_connections"] == "200"


def test_the_slow_query_log_stays_off_while_statements_carry_literals() -> None:
    """Django binds in the client, so a logged statement would hold personal data."""
    assert _db_settings()["log_min_duration_statement"] == "-1"


def _megabytes(value: str) -> int:
    return int(value.removesuffix("m"))


def test_db_memory_fits_shared_buffers_and_the_sum_of_limits_fits_the_vps() -> None:
    db = PROD["services"]["db"]
    assert _megabytes(db["mem_limit"]) >= 2 * 1024  # shared_buffers 1 GB + connections + cache
    assert int(db["shm_size"].removesuffix("mb")) >= 512
    total = sum(_megabytes(service["mem_limit"]) for service in PROD["services"].values())
    assert total <= 6 * 1024, total  # 8 GB VPS: the rest is kernel, page cache and swap


def test_retention_cleanup_is_on_by_default_in_production() -> None:
    assert PROD["x-app-env"]["RETENTION_CLEANUP_ENABLED"] == "${RETENTION_CLEANUP_ENABLED:-true}"


def test_caddy_and_db_drop_capabilities_and_cannot_gain_new_ones() -> None:
    for name in ("caddy", "db"):
        service = PROD["services"][name]
        assert service["cap_drop"] == ["ALL"]
        assert "no-new-privileges:true" in service["security_opt"]


def test_app_services_mount_the_container_snapshot_read_only() -> None:
    for name in ("web", "web-panel", *WORKERS):
        service = PROD["services"][name]
        assert "../../var/state/ops:/run/ops:ro" in service["volumes"]
        assert service["environment"]["OPS_STATE_DIR"] == "/run/ops"


def test_init_roles_does_not_grant_table_permissions() -> None:
    # Table permissions belong to apply_grants (grants.py); init-roles.sh runs on every
    # deploy and would reopen what grants.py restricts.
    script = (ROOT / "deploy" / "postgres" / "init-roles.sh").read_text()
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))
    assert "TO fp_app" in code  # CONNECT / schema USAGE only
    assert "ON ALL TABLES" not in code
    assert "ON ALL SEQUENCES" not in code
    assert "GRANT SELECT, INSERT" not in code


def queues_and_concurrency(service: str) -> tuple[set[str], int]:
    command = BASE["services"][service]["command"].split()
    return set(command[command.index("--queues") + 1].split(",")), int(
        command[command.index("--concurrency") + 1]
    )


def test_worker_topology_isolates_calendar_and_periodic_work() -> None:
    """ADR-023: each pool of slots serves its own queues, so a slow dependency only holds
    its own."""
    assert queues_and_concurrency("worker-inbound") == ({"inbound"}, 4)
    assert queues_and_concurrency("worker-calendar") == ({"inbound_ext"}, 8)
    assert queues_and_concurrency("worker-periodic") == ({"periodic", "ops"}, 2)
    assert queues_and_concurrency("worker-outbound") == ({"outbound"}, 8)


def test_every_queue_has_a_worker_and_ops_runs_only_where_it_cannot_starve_others() -> None:
    from autobot.runtime.jobs import QUEUES

    served = [queues_and_concurrency(w)[0] for w in WORKERS]
    for queue in QUEUES:
        assert any(queue in queues for queues in served), queue
    # ops_check makes slow external calls: only the periodic worker serves it.
    assert [w for w in WORKERS if "ops" in queues_and_concurrency(w)[0]] == ["worker-periodic"]


def test_workers_have_the_same_hardening_and_a_connection_budget() -> None:
    for name in WORKERS:
        service = PROD["services"][name]
        assert service["mem_limit"] == "384m" and service["pids_limit"] == 128
        assert service["networks"] == ["egress", "data", "logs"]
        env = service["environment"]
        pool = int(env["WORKER_DB_POOL_MAX"])
        concurrency = queues_and_concurrency(name)[1]
        assert pool >= concurrency, name  # room for the finish of every running job
        assert int(env["PYTHON_CPU_COUNT"]) + 4 >= concurrency, name  # asyncio's thread pool


def test_the_database_allows_the_worst_case_connections() -> None:
    command = PROD["services"]["db"]["command"]
    limit = int(next(c for c in command if c.startswith("max_connections=")).split("=")[1])
    web = 2 * 4 + 4  # gunicorn threads + a recycling worker
    web_panel = 24
    workers = sum(
        int(PROD["services"][w]["environment"]["WORKER_DB_POOL_MAX"]) + queues_and_concurrency(w)[1]
        for w in WORKERS
    )
    assert limit >= 200
    assert web + web_panel + workers + 5 < limit


def test_local_compose_runs_the_same_four_workers() -> None:
    for name in WORKERS:
        assert LOCAL["services"][name]["entrypoint"] == ["python", "/dev-worker.py"]
        assert LOCAL["services"][name]["environment"]["SERVICE_NAME"] == name
