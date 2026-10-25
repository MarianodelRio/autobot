"""Manually discover an owner's chat; never changes tenant configuration (§11)."""

import secrets
import time
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from flowpilot.channels.adapters import TELEGRAM
from flowpilot.channels.telegram.adapter import TelegramApiError, call
from flowpilot.runtime.notifications import bot_secrets
from flowpilot.tenancy.registry import get_registry


class Command(BaseCommand):
    help = "Link an owner to the outbound notification bot (manual, temporary polling)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("slug")
        parser.add_argument("--timeout", type=int, default=300)

    def handle(self, *args: Any, **options: Any) -> None:
        tenant = get_registry().by_slug.get(options["slug"])
        if tenant is None:
            raise CommandError("Negocio desconocido.")
        bot = bot_secrets()
        if bot is None:
            raise CommandError("Falta NOTIFY_BOT_TOKEN (M-6.1).")
        if options["timeout"] <= 0:
            raise CommandError("El tiempo de espera debe ser positivo.")
        code = secrets.token_urlsafe(24)
        try:
            info = call(TELEGRAM.client, bot, "getWebhookInfo", {})
            if not isinstance(info, dict) or info.get("url"):
                raise CommandError("El bot de avisos debe estar sin webhook.")
            me = call(TELEGRAM.client, bot, "getMe", {})
            if not isinstance(me, dict) or not isinstance(me.get("username"), str):
                raise CommandError("Telegram no devolvió el nombre del bot.")
            self.stdout.write(f"Envía /start {code} a @{me['username']} (caduca en esta sesión).")
            deadline = time.monotonic() + options["timeout"]
            offset: int | None = None
            while time.monotonic() < deadline:
                remaining = max(1, min(25, int(deadline - time.monotonic())))
                params: dict[str, Any] = {"timeout": remaining, "allowed_updates": ["message"]}
                if offset is not None:
                    params["offset"] = offset
                updates = call(TELEGRAM.client, bot, "getUpdates", params, remaining + 10)
                for update in updates if isinstance(updates, list) else []:
                    if not isinstance(update, dict) or not isinstance(update.get("update_id"), int):
                        continue
                    offset = update["update_id"] + 1
                    msg = update.get("message")
                    if not isinstance(msg, dict) or msg.get("text") != f"/start {code}":
                        continue
                    chat, sender = msg.get("chat"), msg.get("from")
                    if (
                        isinstance(chat, dict)
                        and chat.get("type") == "private"
                        and isinstance(chat.get("id"), int)
                        and not isinstance(chat["id"], bool)
                        and isinstance(sender, dict)
                        and sender.get("id") == chat["id"]
                        and not sender.get("is_bot", False)
                    ):
                        self.stdout.write(
                            f"Añade owner.telegram_chat_id: {chat['id']} "
                            f"a tenants/{tenant.file.slug}/tenant.yaml."
                        )
                        return
        except TelegramApiError as e:
            raise CommandError(f"Telegram rechazó la vinculación: {e}") from None
        except KeyboardInterrupt:
            raise CommandError("Vinculación cancelada.") from None
        raise CommandError("El código ha caducado sin recibir una vinculación válida.")
