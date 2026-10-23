"""Plan and apply metadata for appointments created by the original WhatsApp bot."""

import hashlib
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from core.errors import PermanentError, TransientError
from packs.salon.parser import parse_external_id, parse_phone, parse_service_title
from packs.salon.ports import CalendarPort
from packs.salon.slots import classify


@dataclass
class MigrationReport:
    migrated: int = 0
    skipped: int = 0
    failed: int = 0


def migrate(
    calendar: CalendarPort,
    services: Mapping[str, str],
    start: datetime,
    contact_for: Callable[[str, str | None], str],
    *,
    dry_run: bool = True,
) -> MigrationReport:
    report = MigrationReport()
    for event in calendar.list_future_events(start):
        external_id = parse_external_id(event.description)
        if (
            event.all_day
            or event.status == "cancelled"
            or event.start < start
            or event.private.get("fp_key")
            or classify(event) == "config"
            or not external_id
            or len(external_id) > 200
            or re.fullmatch(r"(?:[A-Z]{2}\.[A-Za-z0-9]+|[0-9]{7,15})", external_id) is None
        ):
            report.skipped += 1
            continue
        service_key, _ = parse_service_title(event.summary, services)
        field = re.search(r"(?im)^\s*servicio\s*:\s*([a-z0-9_]+)\s*$", event.description)
        if field and field[1] in services:
            service_key = field[1]
        if service_key is None:
            report.skipped += 1
            continue
        if not dry_run:
            try:
                contact_id = contact_for(external_id, parse_phone(event.description))
                owner = event.private.get("fp_contact")
                if owner and owner != contact_id:
                    report.failed += 1
                    continue
                calendar.patch_private(
                    event.gcal_id,
                    {
                        "fp_contact": contact_id,
                        "fp_key": "legacy:" + hashlib.sha256(event.gcal_id.encode()).hexdigest(),
                        "fp_service": service_key,
                    },
                )
            except PermanentError, TransientError:
                report.failed += 1
                continue
        report.migrated += 1
    return report
