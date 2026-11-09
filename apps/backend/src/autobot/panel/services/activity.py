"""Readable descriptions of retained channel payloads."""

import base64
import contextlib
import json
from datetime import datetime
from typing import Any
from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q
from django.utils.dateparse import parse_datetime
from ninja import Schema

from autobot.ops.audit import record
from autobot.panel.errors import ApiError
from autobot.runtime.models import InboundEvent, Notification, OutboundMessage
from autobot.tenancy.models import Tenant

UNAVAILABLE = "(contenido no disponible)"

SOURCES: dict[str, tuple[Any, str]] = {
    "inbound": (InboundEvent, "received_at"),
    "outbound": (OutboundMessage, "created_at"),
    "notification": (Notification, "created_at"),
}


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def describe_inbound(channel: str, payload: Any) -> str:
    data = _mapping(payload)
    if channel in ("telegram", "demo_tg") or "message" in data or "callback_query" in data:
        message = _mapping(data.get("message"))
        callback = _mapping(data.get("callback_query"))
        value = message.get("text") or callback.get("data")
    else:
        message = data
        with contextlib.suppress(KeyError, IndexError, TypeError):
            message = _mapping(data["entry"][0]["changes"][0]["value"]["messages"][0])
        interactive = _mapping(message.get("interactive"))
        value = (
            _mapping(message.get("text")).get("body")
            or _mapping(interactive.get("button_reply")).get("title")
            or _mapping(interactive.get("list_reply")).get("title")
        )
    return value if isinstance(value, str) and value else UNAVAILABLE


def describe_outbound(payload: Any) -> str:
    data = _mapping(payload)
    values: list[str] = []

    def add(value: Any) -> None:
        if isinstance(value, str) and value:
            values.append(value)

    add(data.get("body"))
    for button in data.get("buttons", []) if isinstance(data.get("buttons"), list) else []:
        add(_mapping(button).get("title"))
    for section in data.get("sections", []) if isinstance(data.get("sections"), list) else []:
        rows = _mapping(section).get("rows")
        for row in rows if isinstance(rows, list) else []:
            add(_mapping(row).get("title"))
    template = _mapping(data.get("template"))
    add(template.get("text"))
    return " · ".join(values) or UNAVAILABLE


class ActivityItem(Schema):
    id: str
    at: datetime
    kind: str
    tenant: str | None
    channel: str | None
    label: str
    status: str | None


class ActivityPage(Schema):
    items: list[ActivityItem]
    next_cursor: str | None


class ActivityDetail(Schema):
    contact: str | None
    text: str
    facts: list[str]
    tenant: str | None
    contact_link: str | None


def encode_cursor(at: datetime, rank: int, id: str) -> str:
    raw = json.dumps({"at": at.isoformat(), "rank": rank, "id": id}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, int, str]:
    try:
        data = json.loads(
            base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        )
        at = parse_datetime(data["at"])
        rank = data["rank"]
        id = data["id"]
        if (
            at is None
            or at.utcoffset() is None
            or type(rank) is not int
            or rank not in range(3)
            or not isinstance(id, str)
        ):
            raise ValueError
        UUID(id)
        return at, rank, id
    except ValueError, TypeError, KeyError, json.JSONDecodeError, OverflowError:
        raise ApiError("bad_request", "Cursor no válido.", 400) from None


def activity_page(
    *, tenant: str = "", kinds: str = "", status: str = "", cursor: str = "", limit: int = 50
) -> ActivityPage:
    position = decode_cursor(cursor) if cursor else None
    selected = set(kinds.split(",")) if kinds else set()
    slugs = dict(Tenant.objects.using("owner").values_list("id", "slug"))
    tenant_id = next((id for id, slug in slugs.items() if slug == tenant), None) if tenant else None
    if tenant and tenant_id is None:
        return ActivityPage(items=[], next_cursor=None)
    rows: list[tuple[datetime, int, Any, ActivityItem]] = []
    for rank, (kind, (model, field)) in enumerate(SOURCES.items()):
        if selected and kind not in selected:
            continue
        qs = model.objects.using("owner").all()
        if tenant_id:
            qs = qs.filter(tenant_id=tenant_id)
        if kind == "inbound":
            qs = qs.filter(kind="message")
        if status:
            if kind in ("inbound", "outbound", "notification"):
                qs = qs.filter(status=status)
            else:
                continue
        if position:
            at, cr, cid = position
            condition = Q(**{field + "__lt": at})
            if rank > cr:
                condition |= Q(**{field: at})
            elif rank == cr:
                condition |= Q(**{field: at, "id__lt": cid})
            qs = qs.filter(condition)
        for obj in qs.order_by("-" + field, "-id")[: limit + 1]:
            at = getattr(obj, field)
            slug = slugs.get(obj.tenant_id)
            channel = getattr(obj, "channel", None)
            if kind == "inbound":
                label, state = "Mensaje recibido", obj.status
            elif kind == "outbound":
                label, state = "Respuesta", obj.status
            else:
                label, state = "Aviso al dueño", obj.status
            item = ActivityItem(
                id=str(obj.pk),
                at=at,
                kind=kind,
                tenant=slug,
                channel=channel,
                label=label,
                status=state,
            )
            rows.append((at, rank, obj.pk, item))
    # Stable sorts preserve each source's native ID ordering.
    rows.sort(key=lambda row: row[1])
    rows.sort(key=lambda row: row[0], reverse=True)
    page = rows[:limit]
    next_cursor = (
        encode_cursor(page[-1][0], page[-1][1], str(page[-1][2])) if len(rows) > limit else None
    )
    return ActivityPage(items=[row[3] for row in page], next_cursor=next_cursor)


def activity_detail(kind: str, id: str, actor: str) -> ActivityDetail:
    if kind not in SOURCES:
        raise ApiError("not_found", "Tipo de actividad no válido.", 404)
    model, _field = SOURCES[kind]
    try:
        UUID(id)
    except ValueError:
        raise ApiError("not_found", "No se encuentra esa actividad.", 404) from None
    qs = model.objects.using("owner")
    if kind == "outbound":
        qs = qs.select_related("contact")
    try:
        obj = qs.get(pk=id)
    except ObjectDoesNotExist:
        raise ApiError("not_found", "No se encuentra esa actividad.", 404) from None

    slug = (
        Tenant.objects.using("owner")
        .filter(pk=obj.tenant_id)
        .values_list("slug", flat=True)
        .first()
    )
    contact_link = f"/clientes/{slug}?tab=contactos" if slug else None
    facts: list[str] = []
    if kind == "inbound":
        contact = None
        text = describe_inbound(obj.channel, obj.payload)
        if obj.error:
            facts.append(f"Error: {obj.error}")
    elif kind == "outbound":
        contact = obj.contact.display_name or obj.contact.external_id
        text = describe_outbound(obj.payload)
        if obj.last_error:
            facts.append(f"Error: {obj.last_error}")
        if obj.pricing_category:
            facts.append(f"Categoría: {obj.pricing_category}")
        if obj.billable is not None:
            facts.append("Facturable" if obj.billable else "No facturable")
    else:
        contact = None
        text = obj.text

    record(
        actor=actor,
        action="activity.view",
        summary="Consulta de actividad",
        tenant_id=obj.tenant_id,
        target_type=kind,
        target_id=str(id),
    )
    return ActivityDetail(
        contact=contact, text=text, facts=facts, tenant=slug, contact_link=contact_link
    )
