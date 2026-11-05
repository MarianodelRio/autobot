"""Resolve an ambiguous (`unknown`) outbound send by hand, as a last resort when the
panel is not reachable (docs/incidencias/envios-unknown.md)."""

from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser

from autobot.ops import actions

ACTOR = "command:outbound_resolve"


class Command(BaseCommand):
    help = "Resuelve un envío ambiguo: marcarlo como enviado o autorizar su reenvío."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("outbound_id", type=UUID)
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--mark-sent", action="store_true")
        group.add_argument("--resend", action="store_true")
        parser.add_argument("--confirm", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        if not options["confirm"]:
            risk = (
                "Reenviar un envío ambiguo puede duplicarlo si el proveedor sí lo entregó."
                if options["resend"]
                else "Marcarlo como enviado da por buena una entrega que no se pudo confirmar."
            )
            raise CommandError(f"{risk} Repita con --confirm si asume ese riesgo.")
        fn = actions.resend if options["resend"] else actions.mark_sent
        result = fn(options["outbound_id"], actor=ACTOR)
        if not result.ok:
            raise CommandError(result.message)
        self.stdout.write(result.message)
