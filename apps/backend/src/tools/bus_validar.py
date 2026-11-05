"""tools/bus_validar.py — make bus-validar TENANT=<slug>.

Valida el dataset de horarios del tenant con `packs/bus/formato.py` e imprime
errores y avisos agrupados. Sale con código 1 si hay errores, 0 en caso
contrario.
"""

from __future__ import annotations

import sys
from pathlib import Path

from packs.bus.formato import validar
from tools.bus_tenant import REPO_ROOT, TenantDesconocido, dataset_dir


def main(argv: list[str] | None = None, repo_root: Path = REPO_ROOT) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("Uso: make bus-validar TENANT=<slug>")
        return 2
    try:
        directorio = dataset_dir(args[0], repo_root)
    except TenantDesconocido as exc:
        print(f"✗ {exc}")
        return 2
    resultado = validar(directorio)

    if resultado.errores:
        print(f"ERRORES ({len(resultado.errores)}):")
        for error in resultado.errores:
            print(f"  ✗ {error}")
    else:
        print("Sin errores.")

    if resultado.avisos:
        print(f"\nAVISOS ({len(resultado.avisos)}):")
        for aviso in resultado.avisos:
            print(f"  ⚠ {aviso}")

    return 1 if resultado.errores else 0


if __name__ == "__main__":
    sys.exit(main())
