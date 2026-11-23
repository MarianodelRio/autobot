"""Host watchdog (deploy/scripts/watchdog.sh), exercised with fake df, docker and curl."""

import fcntl
import os
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
TOKEN = "123456:SECRET-TOKEN-VALUE"


def setup(tmp_path: Path, *, env_text: str | None = None) -> tuple[Path, Path]:
    scripts = tmp_path / "deploy" / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(ROOT / "deploy/scripts/watchdog.sh", scripts / "watchdog.sh")
    var = tmp_path / "var"
    (var / "state" / "ops").mkdir(parents=True)
    (var / "state" / "ops" / "containers.json").write_text("{}\n")  # fresh
    (tmp_path / ".env").write_text(
        env_text
        if env_text is not None
        else f'OTHER=1\nNOTIFY_BOT_TOKEN={TOKEN}\nOPS_TELEGRAM_CHAT_ID="-1001"  # ops\n'
    )
    binaries = tmp_path / "bin"
    binaries.mkdir()
    (binaries / "df").write_text(
        "#!/usr/bin/env bash\n"
        "echo 'Avail Size'\n"
        'echo "${FAKE_DF_AVAIL:-50} ${FAKE_DF_SIZE:-100}"\n'
    )
    (binaries / "docker").write_text(
        "#!/usr/bin/env bash\n"
        "[[ $1 != ps ]] || { [[ ${FAKE_DB_MISSING:-} == 1 ]] || echo dbid; exit 0; }\n"
        'echo "${FAKE_DB_STATUS:-running/healthy}"\n'
    )
    (binaries / "curl").write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "$*" >>"$TEST_LOG.args"\n'
        'cat >>"$TEST_LOG.stdin"\n'
        "[[ ${CURL_FAIL:-} != 1 ]] || exit 22\n"
        'printf x >>"$TEST_LOG.sent"\n'
    )
    for tool in binaries.iterdir():
        tool.chmod(0o755)
    return scripts / "watchdog.sh", binaries


def run(
    script: Path, binaries: Path, tmp_path: Path, **environment: str
) -> subprocess.CompletedProcess[str]:
    env = {
        k: v for k, v in os.environ.items() if k not in ("NOTIFY_BOT_TOKEN", "OPS_TELEGRAM_CHAT_ID")
    }
    env |= {"PATH": f"{binaries}:{os.environ['PATH']}", "TEST_LOG": str(tmp_path / "curl")}
    return subprocess.run(
        ["bash", str(script)],
        env={**env, **environment},
        capture_output=True,
        text=True,
        check=False,
    )


def sent(tmp_path: Path) -> int:
    path = tmp_path / "curl.sent"
    return len(path.read_text()) if path.exists() else 0


def test_a_healthy_host_sends_nothing(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    result = run(script, binaries, tmp_path)
    assert result.returncode == 0, result.stderr
    assert sent(tmp_path) == 0


def test_full_disk_alerts_once_per_hour_and_never_leaks_the_token(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    for _ in range(3):
        result = run(script, binaries, tmp_path, FAKE_DF_AVAIL="5", FAKE_DF_SIZE="100")
        assert result.returncode == 0, result.stderr
        assert TOKEN not in result.stdout + result.stderr
    assert sent(tmp_path) == 1  # rate-limited
    args = (tmp_path / "curl.args").read_text()
    assert TOKEN not in args  # not visible in `ps`
    assert "--fail" in args and "--max-time 10" in args
    assert "--data-urlencode chat_id=-1001" in args
    assert "Disco al 95%" in args
    assert TOKEN in (tmp_path / "curl.stdin").read_text()  # only through the config on stdin


def test_the_alert_repeats_after_the_interval_and_a_recovery_is_reported(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    run(script, binaries, tmp_path, FAKE_DF_AVAIL="5")
    state = tmp_path / "var" / "state" / "watchdog" / "disk"
    assert state.exists()
    old = time.time() - 7200
    state.write_text(f"{int(old)}\n")
    run(script, binaries, tmp_path, FAKE_DF_AVAIL="5")
    assert sent(tmp_path) == 2
    run(script, binaries, tmp_path, FAKE_DF_AVAIL="50")
    assert sent(tmp_path) == 3
    assert "Disco recuperado" in (tmp_path / "curl.args").read_text()
    assert not state.exists()
    run(script, binaries, tmp_path, FAKE_DF_AVAIL="50")
    assert sent(tmp_path) == 3  # the recovery is only said once


def test_a_failed_send_is_retried_on_the_next_run(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    run(script, binaries, tmp_path, FAKE_DF_AVAIL="5", CURL_FAIL="1")
    assert not (tmp_path / "var" / "state" / "watchdog" / "disk").exists()
    run(script, binaries, tmp_path, FAKE_DF_AVAIL="5")
    assert sent(tmp_path) == 1


def test_an_unhealthy_or_missing_db_alerts(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    run(script, binaries, tmp_path, FAKE_DB_STATUS="running/unhealthy")
    assert sent(tmp_path) == 1
    assert "running/unhealthy" in (tmp_path / "curl.args").read_text()
    run(script, binaries, tmp_path, FAKE_DB_MISSING="1")
    assert sent(tmp_path) == 1  # same condition, still within the hour
    assert (tmp_path / "var" / "state" / "watchdog" / "db").exists()


def test_a_stale_host_snapshot_alerts(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    snapshot = tmp_path / "var" / "state" / "ops" / "containers.json"
    old = time.time() - 20 * 60
    os.utime(snapshot, (old, old))
    run(script, binaries, tmp_path)
    assert sent(tmp_path) == 1
    assert "containers.json" in (tmp_path / "curl.args").read_text()


def test_a_missing_snapshot_counts_as_stale(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    (tmp_path / "var" / "state" / "ops" / "containers.json").unlink()
    run(script, binaries, tmp_path)
    assert sent(tmp_path) == 1


def test_db_and_snapshot_checks_are_skipped_during_a_deploy(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    old = time.time() - 3600
    os.utime(tmp_path / "var" / "state" / "ops" / "containers.json", (old, old))
    with open(tmp_path / "var" / ".deploy.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        result = run(script, binaries, tmp_path, FAKE_DB_STATUS="starting/none")
    assert result.returncode == 0, result.stderr
    assert sent(tmp_path) == 0


def test_the_disk_is_still_checked_during_a_deploy(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path)
    with open(tmp_path / "var" / ".deploy.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        run(script, binaries, tmp_path, FAKE_DF_AVAIL="2")
    assert sent(tmp_path) == 1


def test_without_the_ops_bot_configured_it_says_so_and_sends_nothing(tmp_path: Path) -> None:
    script, binaries = setup(tmp_path, env_text="OTHER=1\n")
    result = run(script, binaries, tmp_path, FAKE_DF_AVAIL="2")
    assert result.returncode == 0
    assert "cannot alert" in result.stderr
    assert sent(tmp_path) == 0


def test_the_systemd_units_and_the_installers_know_the_watchdog() -> None:
    timer = (ROOT / "deploy/systemd/autobot-watchdog.timer").read_text()
    service = (ROOT / "deploy/systemd/autobot-watchdog.service").read_text()
    assert "OnCalendar=*:0/5" in timer
    assert "User=deploy" in service
    assert "Requires=docker.service" not in service  # it must run, and report, without Docker
    assert "ExecStart=/srv/autobot/deploy/scripts/watchdog.sh" in service
    bootstrap = (ROOT / "deploy/scripts/bootstrap-server.sh").read_text()
    assert "systemctl enable --now autobot-watchdog.timer" in bootstrap
    assert "autobot-watchdog.service /etc/systemd/system/" in bootstrap
    install_vm = (ROOT / "deploy/scripts/install-vm.sh").read_text()
    assert install_vm.count("autobot-watchdog") >= 2
