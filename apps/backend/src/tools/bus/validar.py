"""tools/bus/validar.py — make bus-validar NOMBRE=<nombre>.

Valida el dataset de horarios del tenant con `packs.bus.formato` e imprime
errores y avisos agrupados. Sale con código 1 si hay errores, 0 en caso
contrario.
"""

from __future__ import annotations

import sys
from pathlib import Path

from packs.bus.formato import validar
from tools._paths import REPO_ROOT
from tools.bus.tenant import dataset_from_argv


def main(argv: list[str] | None = None, repo_root: Path = REPO_ROOT) -> int:
    directorio = dataset_from_argv(argv, "Uso: make bus-validar NOMBRE=<nombre>", repo_root)
    if isinstance(directorio, int):
        return directorio
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
