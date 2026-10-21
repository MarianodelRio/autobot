"""`manage.py new_tenant <slug> --pack <pack> --channel whatsapp|telegram` creates
tenants/<slug>/tenant.yaml (design.md §16.1): a UUIDv7 id, a random public_id,
`status: onboarding` and the pack's config fields. Fields without a default are left
`null`, so the tenant does not validate until they are filled in."""

import re
import secrets
import string
import uuid
from argparse import ArgumentParser
from typing import Any

import yaml
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from pydantic import BaseModel, TypeAdapter
from pydantic_core import PydanticUndefined

from flowpilot.tenancy.schema import SLUG

PUBLIC_ID_ALPHABET = string.ascii_lowercase + string.digits


def public_id() -> str:
    return "".join(secrets.choice(PUBLIC_ID_ALPHABET) for _ in range(16))


def config_skeleton(schema: type[BaseModel]) -> dict[str, Any]:
    """The pack's config with its defaults, as YAML-friendly values; `null` for the
    fields without a default (required: fill them in)."""
    skeleton: dict[str, Any] = {}
    for name, info in schema.model_fields.items():
        if info.default is not PydanticUndefined:
            value = info.default
        elif info.default_factory is not None:
            value = info.default_factory()  # type: ignore[call-arg]
        else:
            skeleton[name] = None
            continue
        skeleton[name] = TypeAdapter(info.annotation or Any).dump_python(value, mode="json")
    return skeleton


class Command(BaseCommand):
    help = "Create tenants/<slug>/tenant.yaml for a new business."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("slug")
        parser.add_argument("--pack", required=True)
        parser.add_argument("--channel", required=True, choices=["whatsapp", "telegram"])
        parser.add_argument("--name", help="Business name (default: the slug)")

    def handle(self, *args: Any, **options: Any) -> None:
        from packs.registry import PACKS

        slug, pack_name = options["slug"], options["pack"]
        if not re.match(SLUG, slug):
            raise CommandError(f"Invalid slug {slug!r}: lowercase letters, digits and dashes")
        if pack_name not in PACKS:
            raise CommandError(f"Unknown pack {pack_name!r}; known: {', '.join(sorted(PACKS))}")
        directory = settings.TENANTS_DIR / slug
        if directory.exists():
            raise CommandError(f"{directory} already exists")

        channel: dict[str, Any] = {"type": options["channel"], "public_id": public_id()}
        if options["channel"] == "whatsapp":
            channel |= {"app_id": None, "waba_id": None, "phone_number_id": None}
        else:
            channel |= {"bot_username": None}
        document = {
            "id": str(uuid.uuid7()),
            "slug": slug,
            "name": options["name"] or slug,
            "status": "onboarding",
            "timezone": "Europe/Madrid",
            "pack": pack_name,
            "channel": channel,
            "testers": {"telegram": [], "main": []},
            "config": config_skeleton(PACKS[pack_name].config_schema),
        }
        directory.mkdir(parents=True)
        (directory / "tenant.yaml").write_text(
            yaml.safe_dump(document, allow_unicode=True, sort_keys=False)
        )
        self.stdout.write(f"Created {directory / 'tenant.yaml'}; next steps: design.md §16.1")
