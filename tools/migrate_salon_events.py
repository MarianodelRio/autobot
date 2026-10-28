"""Operator-only legacy migration. Run --dry-run before applying; never run by a worker.

PYTHONPATH=src uv run python -m tools.migrate_salon_events <slug> [--dry-run]
"""

import argparse
import os
from collections.abc import Callable
from datetime import datetime
from typing import Any

import django
from django.utils import timezone

from core.errors import PermanentError, TransientError


def main(
    argv: list[str] | None = None,
    *,
    calendars: Callable[[str], Any] | None = None,
    at: datetime | None = None,
) -> int:
    from django.db import DatabaseError

    from autobot.runtime.context import build_context, google_calendar
    from autobot.runtime.identity import phone_group, phone_key
    from autobot.runtime.models import Channel, Contact
    from autobot.tenancy.registry import get_registry
    from autobot.tenancy.schema import BSUID
    from autobot.tenancy.tx import tenant_tx
    from packs.salon.booking import calendar, configuration
    from packs.salon.migration import migrate

    parser = argparse.ArgumentParser(
        description="Migrar metadatos de citas heredadas del bot anterior"
    )
    parser.add_argument("slug")
    parser.add_argument(
        "--dry-run", action="store_true", help="Solo informar; no escribir en Calendar ni BD"
    )
    args = parser.parse_args(argv)
    tenant = get_registry().by_slug.get(args.slug)
    if tenant is None or tenant.is_degraded or tenant.file.pack != "salon":
        print("El tenant no existe o no es un salón válido.")
        return 2
    if (
        tenant.file.channel is None
        or tenant.file.channel.type != "whatsapp"
        or tenant.file.status == "offboarded"
    ):
        print("La migración heredada requiere un tenant de WhatsApp que no esté dado de baja.")
        return 2
    ctx = build_context(
        tenant,
        Channel.MAIN,
        contact=None,
        state={},
        event_id=None,
        calendars=calendars or google_calendar,
    )
    cfg = configuration(ctx)

    def contact_for(external_id: str, phone: str | None) -> str:
        try:
            with tenant_tx(tenant.id):
                number = phone_key(phone or (external_id if external_id.isdecimal() else ""))
                group = phone_group(tenant.id, number, lock=True) if number else []
                exact = (
                    Contact.objects.select_for_update()
                    .filter(tenant_id=tenant.id, channel=Channel.MAIN, external_id=external_id)
                    .first()
                )
                if exact is not None and all(c.id != exact.id for c in group):
                    group.append(exact)
                bsuid = [c for c in group if BSUID.fullmatch(c.external_id)]
                explicit_bsuid = bool(BSUID.fullmatch(external_id))
                if len(bsuid) > 1 or (
                    explicit_bsuid and any(c.external_id != external_id for c in bsuid)
                ):
                    raise PermanentError("Ambiguous legacy contact identity")
                # A scoped user id is explicit identity, unlike a legacy phone id.
                # A phone match must never replace that explicit identity.
                selected = (
                    exact
                    if explicit_bsuid
                    else (bsuid[0] if bsuid else exact or (group[0] if group else None))
                )
                if selected is None:
                    selected = Contact.objects.create(
                        tenant_id=tenant.id,
                        channel=Channel.MAIN,
                        external_id=external_id,
                        phone_e164=f"+{number}"
                        if number and not BSUID.fullmatch(external_id)
                        else None,
                    )
                opted_out = selected.opt_out or any(c.opt_out for c in group)
                unreachable = selected.unreachable or any(c.unreachable for c in group)
                if (selected.opt_out, selected.unreachable) != (opted_out, unreachable):
                    selected.opt_out, selected.unreachable = opted_out, unreachable
                    selected.save(update_fields=["opt_out", "unreachable"])
                return str(selected.id)
        except DatabaseError:
            raise PermanentError("Contact could not be prepared") from None

    try:
        report = migrate(
            calendar(ctx),
            {key: svc.name for key, svc in cfg.services.items()},
            at or timezone.now(),
            contact_for,
            dry_run=args.dry_run,
        )
    except PermanentError, TransientError:
        print("No se pudo leer el calendario; revisa su acceso antes de reintentar.")
        return 1
    mode = "Simulación" if args.dry_run else "Migración"
    print(
        f"{mode}: {report.migrated} candidatas/completadas; "
        f"{report.skipped} omitidas; {report.failed} fallidas."
    )
    return 1 if report.failed else 0


if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()
    raise SystemExit(main())
