"""Sube o baja un conjunto de horarios de la biblioteca (ADR-013), nunca de un
cliente:

- `make bus-subir NOMBRE=<nombre> DIR=<dir> COMMENT="..." [PROD=1]`: valida
  en local, prueba la subida sin escribir y sube con `--base-sha` (leído justo antes,
  así que una subida de otra persona entre medias la rechaza en vez de sobrescribirla).
- `make bus-bajar NOMBRE=<nombre> [DIR=<dir>] [VERSION=<n>] [PROD=1]`: descarga la
  entrada vigente (o `VERSION`) a `var/datos/<nombre>/`, para seguir editándola.
"""

import argparse
import io
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory

from packs.bus.formato import validar
from tools._paths import REPO_ROOT
from tools.bus.tenant import TenantDesconocido, published_dir

PACK = "bus"
DATASET = "timetable"


def _manage_command(args: list[str], production: bool) -> list[str]:
    if production:
        host = os.environ.get("HOST", "autobot")
        return [
            "ssh",
            f"deploy@{host}",
            shlex.join(["/srv/autobot/deploy/scripts/manage.sh", *args]),
        ]
    return [sys.executable, str(REPO_ROOT / "apps" / "backend" / "manage.py"), *args]


def _run(
    args: list[str], production: bool, input_bytes: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        _manage_command(args, production),
        cwd=REPO_ROOT,
        input=input_bytes,
        capture_output=True,
        check=False,
    )


def _tar(directory: Path) -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        archive.add(directory, arcname=".")
    return stream.getvalue()


def _last_line(output: bytes) -> str:
    """The command's own `self.stdout.write(...)` output, stripped of the JSON log
    lines `manage.py` also prints to stdout before it."""
    lines = [line for line in output.decode(errors="replace").splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _resolve_dir(raw: str, repo_root: Path, default_name: str) -> Path:
    if raw:
        return repo_root / raw if not Path(raw).is_absolute() else Path(raw)
    # Same layout `tools.bus.tenant.dataset_path` uses, so bus-validar/-formatear/
    # -revision (keyed by NOMBRE, not by this tool's own --dir) find it unchanged.
    return repo_root / "var" / "datos" / default_name / "timetable"


def _push(args: argparse.Namespace, repo_root: Path) -> int:
    if not args.nombre or not args.comment.strip():
        print("✗ Hacen falta NOMBRE y COMMENT", file=sys.stderr)
        return 2
    directory = _resolve_dir(args.dir, repo_root, args.nombre)
    if not directory.is_dir():
        print(f"✗ No existe el directorio {directory}", file=sys.stderr)
        return 2

    resultado = validar(directory)
    if resultado.errores:
        print(
            f"✗ El dataset no valida ({len(resultado.errores)} error(es));"
            " ejecuta make bus-validar",
            file=sys.stderr,
        )
        for error in resultado.errores:
            print(f"  - {error}", file=sys.stderr)
        return 1

    payload = _tar(directory)
    destino = "el servidor" if args.prod else "local"

    dry = _run(
        [
            "dataset_library",
            "push",
            PACK,
            DATASET,
            args.nombre,
            "-",
            "--comment",
            args.comment,
            "--dry-run",
        ],
        args.prod,
        payload,
    )
    if dry.returncode:
        sys.stderr.write(dry.stderr.decode(errors="replace"))
        return 1
    print(f"Prueba en {destino}: {_last_line(dry.stdout)}")

    sha = _run(["dataset_library", "current-sha", PACK, DATASET, args.nombre], args.prod)
    if sha.returncode:
        sys.stderr.write(sha.stderr.decode(errors="replace"))
        return 1
    base_sha = _last_line(sha.stdout).removeprefix("SHA:")

    push_args = [
        "dataset_library",
        "push",
        PACK,
        DATASET,
        args.nombre,
        "-",
        "--comment",
        args.comment,
    ]
    if base_sha:
        push_args += ["--base-sha", base_sha]
    push = _run(push_args, args.prod, payload)
    if push.returncode:
        sys.stderr.write(push.stderr.decode(errors="replace"))
        return 1
    print(f"Subido a {destino}: {_last_line(push.stdout)}")
    return 0


def _replace(source: Path, target: Path) -> None:
    """Atomically swaps `target`'s contents for `source`'s, keeping the old
    directory as a backup until the rename of the new one succeeds."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".bus-copy-", dir=target.parent) as staging:
        prepared = Path(staging) / "new"
        shutil.copytree(source, prepared, symlinks=True)
        backup = Path(staging) / "old"
        if target.exists():
            target.rename(backup)
        try:
            prepared.rename(target)
        except OSError:
            if backup.exists():
                backup.rename(target)
            raise


def _pull(args: argparse.Namespace, repo_root: Path) -> int:
    if not args.nombre:
        print("✗ Hace falta NOMBRE", file=sys.stderr)
        return 2
    directory = _resolve_dir(args.dir, repo_root, args.nombre)
    pull_args = ["dataset_library", "pull", PACK, DATASET, args.nombre, "-"]
    if args.version is not None:
        pull_args += ["--version", str(args.version)]
    result = _run(pull_args, args.prod)
    if result.returncode:
        sys.stderr.write(result.stderr.decode(errors="replace"))
        return 1
    with TemporaryDirectory(prefix="autobot-bus-pull-") as temporary:
        extracted = Path(temporary) / "extracted"
        extracted.mkdir()
        with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:gz") as archive:
            archive.extractall(extracted, filter="data")
        _replace(extracted, directory)
        # Also refreshes the base `bus-revision` diffs against by default, same
        # as the old per-tenant flow did on every download.
        _replace(extracted, published_dir(args.nombre, repo_root))
    print(f"Descargado en {directory}")
    return 0


def main(argv: list[str] | None = None, repo_root: Path = REPO_ROOT) -> int:
    parser = argparse.ArgumentParser(description="Sube o baja horarios de la biblioteca.")
    parser.add_argument("action", choices=["push", "pull"])
    parser.add_argument("--nombre", default=os.environ.get("NOMBRE", ""))
    parser.add_argument("--dir", default=os.environ.get("DIR", ""))
    parser.add_argument("--comment", default=os.environ.get("COMMENT", ""))
    version_env = os.environ.get("VERSION", "")
    parser.add_argument("--version", type=int, default=int(version_env) if version_env else None)
    parser.add_argument("--prod", action="store_true", default=os.environ.get("PROD") == "1")
    args = parser.parse_args(argv)
    try:
        if args.action == "push":
            return _push(args, repo_root)
        return _pull(args, repo_root)
    except (OSError, UnicodeError, tarfile.TarError, TenantDesconocido) as error:
        print(f"✗ {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
