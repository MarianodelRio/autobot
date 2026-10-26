"""Generate a tenant's public channel QR locally, without loading channel secrets."""

import argparse
import re
from pathlib import Path

import qrcode  # type: ignore[import-untyped]
import qrcode.image.svg  # type: ignore[import-untyped]
import yaml
from pydantic import ValidationError

from flowpilot.tenancy.schema import SLUG, Channel, TenantFile

REPO_ROOT = Path(__file__).resolve().parent.parent


def channel_link(channel: Channel) -> str:
    """Use the public phone, never Meta's phone_number_id, or the business bot name."""
    if channel.type == "telegram":
        if not channel.bot_username:
            raise ValueError("Falta channel.bot_username para generar el QR de Telegram.")
        return f"https://t.me/{channel.bot_username}"
    phone = channel.display_phone or ""
    if not re.fullmatch(r"\+?[0-9 ()\-.]+", phone):
        raise ValueError("Configura channel.display_phone con el número internacional del negocio.")
    digits = re.sub(r"[^0-9]", "", phone)
    if not re.fullmatch(r"[1-9][0-9]{6,14}", digits):
        raise ValueError(
            "channel.display_phone debe incluir el prefijo internacional (7–15 cifras)."
        )
    return f"https://wa.me/{digits}"


def tenant_link(slug: str, tenants_dir: Path = REPO_ROOT / "tenants") -> str:
    if len(slug) > 64 or re.fullmatch(SLUG, slug) is None:
        raise ValueError("Slug de negocio inválido.")
    try:
        file = TenantFile.model_validate(
            yaml.safe_load((tenants_dir / slug / "tenant.yaml").read_text(encoding="utf-8"))
        )
    except OSError, UnicodeError, yaml.YAMLError, ValidationError:
        raise ValueError(f"No se pudo leer una configuración válida para {slug}.") from None
    if file.slug != slug:
        raise ValueError("El slug de tenant.yaml no coincide con su directorio.")
    if file.channel is None:
        raise ValueError("Un negocio de demo no tiene canal propio.")
    return channel_link(file.channel)


def generate(link: str, output: Path) -> None:
    """White background and the standard quiet zone keep the printed code readable."""
    if output.suffix.lower() != ".svg":
        raise ValueError("El archivo de salida debe tener extensión .svg.")
    image = qrcode.make(link, image_factory=qrcode.image.svg.SvgPathFillImage, border=4)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(output))


def main(argv: list[str] | None = None, repo_root: Path = REPO_ROOT) -> int:
    parser = argparse.ArgumentParser(description="Genera el QR del canal público de un negocio.")
    parser.add_argument("slug")
    parser.add_argument("--output", type=Path, help="Archivo SVG (por defecto qr/<slug>.svg).")
    args = parser.parse_args(argv)
    try:
        link = tenant_link(args.slug, repo_root / "tenants")
        output = args.output or repo_root / "qr" / f"{args.slug}.svg"
        generate(link, output)
    except ValueError as exc:
        parser.exit(2, f"{exc}\n")
    except OSError:
        parser.exit(2, "No se pudo escribir el archivo QR.\n")
    print(f"{output}: {link}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
