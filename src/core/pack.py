"""Pack contract (design.md §8.1, §8.2)."""

import logging
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from core.actions import Action
from core.clock import Clock
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


@dataclass(frozen=True)
class HealthIssue:
    code: str
    message: str


@dataclass(frozen=True)
class PackContext:
    tenant: TenantInfo
    config: BaseModel  # the pack's validated config
    data: object | None  # what load_data returned
    contact: ContactInfo | None  # None in periodic handlers
    state: Mapping[str, Any]  # current state (read-only)
    clock: Clock
    # Only if the pack needs_calendar, already bound to the channel's calendar (§6.5). Its
    # Protocol lives in the pack (packs/salon/ports.py), which core cannot import.
    calendar: Any
    lock: Callable[[str], AbstractContextManager[None]]  # key prefixed with tenant and calendar
    idem: IdemKeys
    log: logging.Logger | logging.LoggerAdapter[logging.Logger]


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
