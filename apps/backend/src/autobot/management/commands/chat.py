"""`manage.py chat <pack> [--channel telegram|whatsapp]` (L4): a terminal chat with a
pack's own demo template, over `core.testing.Conversation` -- the same harness the
conversation scenarios use, with the common rules, `plan_sends` and the channel's
limits applied, but no real channel, no database and no network. For trying out a
pack's flow by hand, without a bot token or a tenant in the database."""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from autobot.tenancy.registry import load_registry, source_from_dir
from core.replies import Buttons, List, Text
from core.testing import Conversation
from core.testing.harness import ChannelType, Turn

EXIT_WORDS = {"salir", "exit", "quit"}


def _render(turn: Turn) -> tuple[str, dict[int, str]]:
    lines: list[str] = []
    pressable: dict[int, str] = {}
    n = 0
    for reply in turn.replies:
        if isinstance(reply, Text):
            lines.append(reply.body)
        elif isinstance(reply, Buttons):
            lines.append(reply.body)
            for button in reply.buttons:
                n += 1
                lines.append(f"  [{n}] {button.title}")
                pressable[n] = button.id
        elif isinstance(reply, List):
            lines.append(reply.body)
            for section in reply.sections:
                if section.title:
                    lines.append(f"-- {section.title} --")
                for row in section.rows:
                    n += 1
                    suffix = f" — {row.description}" if row.description else ""
                    lines.append(f"  [{n}] {row.title}{suffix}")
                    pressable[n] = row.id
    for action in turn.actions:
        lines.append(f"  (acción: {type(action).__name__})")
    return "\n".join(lines) or "(sin respuesta)", pressable


class Command(BaseCommand):
    help = "Chat de prueba por terminal con el demo de un pack (L4, sin canal real)."
    requires_system_checks: list[str] = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("pack", help="nombre del pack (p. ej. salon, bus)")
        parser.add_argument(
            "--channel",
            choices=["whatsapp", "telegram"],
            default="whatsapp",
            help="canal simulado, para aplicar sus límites (por defecto whatsapp)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        from packs.registry import PACKS

        name = options["pack"]
        pack = PACKS.get(name)
        if pack is None:
            raise CommandError(f"Pack desconocido {name!r}; packs disponibles: {sorted(PACKS)}")
        if pack.template is None:
            raise CommandError(f"El pack {name!r} no tiene plantilla de demo (pack.template)")
        source = source_from_dir(pack.template)
        registry = load_registry([source], PACKS)
        if registry.problems:
            problems = "; ".join(registry.problems.get(source.name, []))
            raise CommandError(f"La plantilla de {name!r} no es válida: {problems}")
        tenant = registry.tenants[0]

        calendar = None
        if pack.needs_calendar:
            if pack.test_calendar is None:
                raise CommandError(f"Pack {name!r} needs a calendar but has no test_calendar")
            calendar = pack.test_calendar()

        channel: ChannelType = options["channel"]
        conversation = Conversation(
            pack,
            config=tenant.config,
            data=tenant.data,
            calendar=calendar,
            channel=channel,
            tenant=tenant.info,
        )

        self.stdout.write(
            f"Chat de prueba: {tenant.document.slug} ({pack.name}, canal {channel}).\n"
            "Escribe un mensaje para empezar (p. ej. 'hola'), un número para pulsar una "
            "opción ofrecida, o 'salir' para terminar."
        )
        pressable: dict[int, str] = {}
        while True:
            try:
                line = input("> ")
            except EOFError, KeyboardInterrupt:
                self.stdout.write("")
                break
            line = line.strip()
            if not line:
                continue
            if line.lower() in EXIT_WORDS:
                break
            if line.isdigit():
                choice = int(line)
                payload = pressable.get(choice)
                if payload is None:
                    self.stderr.write(f"No hay ninguna opción [{choice}] en la última respuesta.")
                    continue
                turn = conversation.press(payload, check=False)
            else:
                turn = conversation.send(line)
            text, pressable = _render(turn)
            self.stdout.write(text)
