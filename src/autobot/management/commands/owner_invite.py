"""Generate a one-time link for a business owner to connect their Telegram chat to
the notify bot (ADR-007). The code only ever
appears in this command's own output: never logged."""

from datetime import timedelta
from typing import Any

import httpx
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from autobot.channels.telegram.adapter import TelegramApiError, call
from autobot.owner.links import OWNER_INVITE_DAYS, new_invite, owner_chat
from autobot.runtime.notifications import bot_secrets
from autobot.tenancy.registry import get_registry


class Command(BaseCommand):
    help = "Generate a one-time Telegram link for a business owner."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("slug")

    def handle(self, *args: Any, **options: Any) -> None:
        tenant = get_registry().by_slug.get(options["slug"])
        if tenant is None:
            raise CommandError("Negocio desconocido.")
        if tenant.file.status == "offboarded":
            raise CommandError("El negocio está dado de baja.")
        bot = bot_secrets()
        if bot is None:
            raise CommandError("Falta NOTIFY_BOT_TOKEN.")
        try:
            with httpx.Client() as client:
                me = call(client, bot, "getMe", {})
        except TelegramApiError as e:
            raise CommandError(f"Telegram rechazó la petición: {e}") from None
        if not isinstance(me, dict) or not isinstance(me.get("username"), str):
            raise CommandError("Telegram no devolvió el nombre del bot.")
        if owner_chat(tenant.id) is not None:
            self.stdout.write("Ya hay un chat conectado; este enlace lo sustituirá cuando se use.")
        code = new_invite(tenant.id)
        expires = (timezone.now() + timedelta(days=OWNER_INVITE_DAYS)).astimezone(
            tenant.info.timezone
        )
        self.stdout.write(
            f"Enlace para {tenant.file.name} (caduca el {expires:%d/%m/%Y}): "
            f"https://t.me/{me['username']}?start={code}"
        )
