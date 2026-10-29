"""Pack contract."""

import logging
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from core.actions import Action
from core.clock import Clock
from core.effects import EffectJournal
from core.idem import IdemKeys
from core.messages import IncomingMessage
from core.proactive import TemplateSpec
from core.replies import Reply


@dataclass(frozen=True)
class TenantInfo:
    id: UUID
    slug: str
    name: str
    timezone: ZoneInfo


@dataclass(frozen=True)
class ContactInfo:
    id: UUID
    external_id: str
    phone: str | None
    display_name: str | None
    opt_out: bool
    alias_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True)
class HealthIssue:
    code: str
    message: str


@dataclass(frozen=True)
class SummaryLine:
    """One line of the owner's summary, contributed by the pack
    (`docs/mejoras/02-avisos-y-resumenes.md` §4.1)."""

    icon: str  # one emoji
    label: str
    value: Decimal
    unit: Literal["count", "eur"] = "count"
    note: str | None = None  # shown in brackets after the value


# ctx has contact=None and no calendar lock; [start, end) is the reported period, aware
# in the tenant's own timezone; recorded are the tenant's MetricEvent totals by kind in
# that period. Runs without an open transaction: the pack may call Calendar.
type SummaryHook = Callable[
    [PackContext, datetime, datetime, Mapping[str, Decimal]], list[SummaryLine]
]


@dataclass(frozen=True)
class PackContext:
    tenant: TenantInfo
    config: BaseModel  # the pack's validated config
    data: object | None  # what load_data returned
    contact: ContactInfo | None  # None in periodic handlers
    state: Mapping[str, Any]  # current state (read-only)
    clock: Clock
    # Only if the pack needs_calendar, already bound to the channel's calendar. Its
    # Protocol lives in the pack (packs/salon/ports.py), which core cannot import.
    calendar: Any
    lock: Callable[[str], AbstractContextManager[None]]  # key prefixed with tenant and calendar
    idem: IdemKeys
    log: logging.Logger | logging.LoggerAdapter[logging.Logger]
    # Communication capability, without exposing which channel the pack runs on.
    can_contact_by_phone: bool = False
    effects: EffectJournal | None = None


@dataclass
class PackResult:
    replies: list[Reply] = field(default_factory=list)
    state: dict[str, Any] | None = None  # None = unchanged; {} = reset
    actions: list[Action] = field(default_factory=list)


@dataclass(frozen=True)
class Periodic:
    name: str
    every_min: int
    handler: Callable[[PackContext], list[Action]]  # ctx has contact=None and state={}
    max_delay_min: int = 60


@dataclass(frozen=True, kw_only=True)
class Pack:
    name: str
    config_schema: type[BaseModel]
    state_version: int
    conversation_timeout_min: int = 30
    handle_message: Callable[[PackContext, IncomingMessage], PackResult]
    periodic: list[Periodic] = field(default_factory=list)
    needs_calendar: bool = False
    load_data: Callable[[TenantInfo, BaseModel, Path], object] | None = None
    health: Callable[[PackContext], list[HealthIssue]] | None = None
    templates: list[TemplateSpec] = field(default_factory=list)
    summary: SummaryHook | None = None
