"""Generate a one-time link for a business owner to connect their Telegram chat to
the notify bot (ADR-007). The code only ever
appears in this command's own output: never logged."""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from autobot.owner.invites import InviteError, create_invite_link
from autobot.tenancy.registry import get_registry


class Command(BaseCommand):
    help = "Generate a one-time Telegram link for a business owner."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("slug")

    def handle(self, *args: Any, **options: Any) -> None:
        tenant = get_registry().by_slug.get(options["slug"])
        if tenant is None:
            raise CommandError("Negocio desconocido.")
        try:
            link = create_invite_link(tenant)
        except InviteError as e:
            raise CommandError(str(e)) from None
        if link.replaces_chat:
            self.stdout.write("Ya hay un chat conectado; este enlace lo sustituirá cuando se use.")
        expires = link.expires_at.astimezone(tenant.info.timezone)
        self.stdout.write(
            f"Enlace para {tenant.document.name} (caduca el {expires:%d/%m/%Y}): {link.url}"
        )
