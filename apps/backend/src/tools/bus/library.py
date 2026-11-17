"""`make bus-subir NOMBRE=<nombre> DIR=<dir> COMMENT="..." [PROD=1]` (C21): sube un
conjunto de horarios validado a la biblioteca (ADR-013), nunca a un cliente.

1. Valida el contenido en local (`packs.bus.formato.validar`).
2. Prueba la subida en el destino (local o, con `PROD=1`, el servidor por SSH) sin
   escribir nada (`--dry-run`), y lee su versión vigente (`current-sha`).
3. Sube la versión nueva con `--base-sha`: si alguien subió otra entre medias, el
   destino la rechaza en vez de sobrescribirla a ciegas.
"""

import io
import os
import shlex
import subprocess
import sys
import tarfile
from pathlib import Path

from packs.bus.formato import validar
from tools.bus.tenant import REPO_ROOT

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


def main(argv: list[str] | None = None, repo_root: Path = REPO_ROOT) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Sube un conjunto de horarios a la biblioteca.")
    parser.add_argument("--nombre", default=os.environ.get("NOMBRE", ""))
    parser.add_argument("--dir", default=os.environ.get("DIR", ""))
    parser.add_argument("--comment", default=os.environ.get("COMMENT", ""))
    parser.add_argument("--prod", action="store_true", default=os.environ.get("PROD") == "1")
    args = parser.parse_args(argv)

    if not args.nombre or not args.dir or not args.comment.strip():
        print("✗ Hacen falta NOMBRE, DIR y COMMENT", file=sys.stderr)
        return 2
    directory = repo_root / args.dir if not Path(args.dir).is_absolute() else Path(args.dir)
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


if __name__ == "__main__":
    raise SystemExit(main())
