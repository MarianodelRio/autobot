"""tools/bus_publicar.py — make bus-publicar TENANT=<slug> (design.md §10.1).

Marca como publicada la versión actual del dataset del tenant: crea el tag
local `datos/<slug>/AAAA-MM-DD` (fecha de hoy en Madrid) sobre `HEAD`, la base
del siguiente `make bus-revision`. Se ejecuta tras el commit y el despliegue.

Se niega si el dataset no valida, si tiene cambios sin confirmar (el tag no
describiría lo publicado) o si el tag de hoy ya existe y apunta a otro commit.
No sube el tag: lo imprime para hacer `git push`, que es una acción de la
persona.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from packs.bus.formato import validar
from tools.bus_tenant import REPO_ROOT, TenantDesconocido, dataset_dir, dataset_path, tag_prefix

ZONA_HORARIA = "Europe/Madrid"


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo_root, capture_output=True, text=True)


def main(
    argv: list[str] | None = None, repo_root: Path = REPO_ROOT, hoy: date | None = None
) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("Uso: make bus-publicar TENANT=<slug>")
        return 2
    slug = args[0]
    try:
        directorio = dataset_dir(slug, repo_root)
    except TenantDesconocido as exc:
        print(f"✗ {exc}")
        return 2

    resultado = validar(directorio)
    if resultado.errores:
        print(
            f"✗ El dataset no valida ({len(resultado.errores)} errores): ejecuta make bus-validar."
        )
        return 1

    estado = _git(repo_root, "status", "--porcelain", "--", dataset_path(slug).as_posix())
    if estado.returncode != 0:
        print(f"✗ git status falló: {estado.stderr.strip()}")
        return 1
    if estado.stdout.strip():
        print("✗ El dataset tiene cambios sin confirmar: haz commit antes de publicar.")
        return 1

    head = _git(repo_root, "rev-parse", "HEAD")
    if head.returncode != 0:
        print(f"✗ git rev-parse falló: {head.stderr.strip()}")
        return 1

    fecha = hoy or datetime.now(ZoneInfo(ZONA_HORARIA)).date()
    tag = f"{tag_prefix(slug)}{fecha.isoformat()}"
    existente = _git(repo_root, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}^{{commit}}")
    if existente.returncode == 0:
        if existente.stdout.strip() == head.stdout.strip():
            print(f"El tag {tag} ya existe y apunta a HEAD: nada que hacer.")
            return 0
        print(f"✗ El tag {tag} ya existe y apunta a otro commit; no se mueve.")
        return 1

    creado = _git(repo_root, "tag", tag, "HEAD")
    if creado.returncode != 0:
        print(f"✗ git tag falló: {creado.stderr.strip()}")
        return 1
    print(f"Publicado: {tag}")
    print(f"Súbelo con: git push origin {tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
