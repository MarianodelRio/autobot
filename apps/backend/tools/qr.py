"""Generate a tenant's public channel QR locally, without loading channel secrets."""

import argparse
from pathlib import Path

import qrcode  # type: ignore[import-untyped]
import qrcode.image.svg  # type: ignore[import-untyped]
import yaml
from pydantic import ValidationError

from autobot.tenancy.links import channel_link
from autobot.tenancy.schema import TenantDocument

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

__all__ = ["channel_link", "generate", "main", "tenant_link_from_file"]


def _document(path: Path) -> TenantDocument:
    try:
        return TenantDocument.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except OSError, UnicodeError, yaml.YAMLError, ValidationError:
        raise ValueError("No se pudo leer un documento de negocio válido.") from None


def tenant_link_from_file(path: Path) -> str:
    document = _document(path)
    if document.channel is None:
        raise ValueError("Un negocio de demo no tiene canal propio.")
    return channel_link(document.channel)


def generate(link: str, output: Path) -> None:
    """White background and the standard quiet zone keep the printed code readable."""
    if output.suffix.lower() != ".svg":
        raise ValueError("El archivo de salida debe tener extensión .svg.")
    image = qrcode.make(link, image_factory=qrcode.image.svg.SvgPathFillImage, border=4)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(output))


def main(argv: list[str] | None = None, repo_root: Path = REPO_ROOT) -> int:
    parser = argparse.ArgumentParser(description="Genera el QR del canal público de un negocio.")
    parser.add_argument("file", type=Path, help="document.yaml exportado del negocio.")
    parser.add_argument("--output", type=Path, help="Archivo SVG (por defecto qr/<slug>.svg).")
    args = parser.parse_args(argv)
    try:
        document = _document(args.file)
        if document.channel is None:
            raise ValueError("Un negocio de demo no tiene canal propio.")
        link = channel_link(document.channel)
        output = args.output or repo_root / "qr" / f"{document.slug}.svg"
        generate(link, output)
    except ValueError as exc:
        parser.exit(2, f"{exc}\n")
    except OSError:
        parser.exit(2, "No se pudo escribir el archivo QR.\n")
    print(f"{output}: {link}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
