"""Readable descriptions of retained channel payloads."""

import base64
import contextlib
import json
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import connections
from django.db.models import Q
from django.utils.dateparse import parse_datetime
from ninja import Schema

from autobot.ops.models import AuditEvent, OpsAlert
from autobot.panel.errors import ApiError
from autobot.runtime.models import InboundEvent, Notification, OutboundMessage
from autobot.tenancy.models import Tenant

UNAVAILABLE = "(contenido no disponible)"


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
    icon: str
    title: str
    detail: str
    status: str | None
    link: str | None


class ActivityPage(Schema):
    items: list[ActivityItem]
    next_cursor: str | None


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
            or rank not in range(6)
            or not isinstance(id, str)
        ):
            raise ValueError
        if rank == 5:
            if int(id) < 0 or str(int(id)) != id:
                raise ValueError
        else:
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
    sources: list[tuple[str, Any, str]] = [
        ("inbound", InboundEvent, "received_at"),
        ("outbound", OutboundMessage, "created_at"),
        ("notification", Notification, "created_at"),
        ("alert", OpsAlert, "first_seen_at"),
        ("audit", AuditEvent, "at"),
    ]
    rows: list[tuple[datetime, int, Any, ActivityItem]] = []
    for rank, (kind, model, field) in enumerate(sources):
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
            elif kind == "alert":
                if status not in ("open", "resolved"):
                    continue
                qs = qs.filter(resolved_at__isnull=status == "open")
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
        if kind == "outbound":
            qs = qs.select_related("contact")
        for obj in qs.order_by("-" + field, "-id")[: limit + 1]:
            at = getattr(obj, field)
            slug = slugs.get(obj.tenant_id)
            channel = getattr(obj, "channel", None)
            link = f"/clientes/{slug}" if slug else None
            if kind == "inbound":
                title, detail, state, icon = (
                    "Mensaje recibido",
                    describe_inbound(channel or "", obj.payload),
                    obj.status,
                    "📩",
                )
            elif kind == "outbound":
                title, detail, state, icon = (
                    f"Respuesta a {obj.contact.display_name or obj.contact.external_id}",
                    describe_outbound(obj.payload),
                    obj.status,
                    "📤",
                )
                if obj.last_error:
                    detail += f" · {obj.last_error}"
                if obj.pricing_category:
                    detail += f" · {obj.pricing_category}"
                if obj.billable is not None:
                    detail += " · facturable" if obj.billable else " · no facturable"
                link = f"/clientes/{slug}/contactos" if slug else None
            elif kind == "notification":
                title, detail, state, icon = (
                    f"Aviso al dueño: {obj.kind}",
                    obj.text,
                    obj.status,
                    "🔔",
                )
            elif kind == "alert":
                title, detail, state, icon = (
                    "Alerta",
                    f"{obj.text} · enviada {obj.sent_count} veces",
                    "resolved" if obj.resolved_at else "open",
                    "🚨",
                )
            else:
                title, detail, state, icon = obj.summary, f"{obj.action} · {obj.actor}", None, "⚙️"
            item = ActivityItem(
                id=str(obj.pk),
                at=at,
                kind=kind,
                tenant=slug,
                channel=channel,
                icon=icon,
                title=title,
                detail=detail,
                status=state,
                link=link,
            )
            rows.append((at, rank, obj.pk, item))
    if (not selected or "job" in selected) and (not status or status == "failed"):
        clauses = ["e.type = 'failed'"]
        params: list[Any] = []
        if tenant_id:
            clauses.append("j.args->>'tenant_id' = %s")
            params.append(str(tenant_id))
        if position:
            at, cr, cid = position
            if cr < 5:
                clauses.append("(e.at < %s OR e.at = %s)")
                params.extend([at, at])
            elif cr == 5:
                clauses.append("(e.at < %s OR (e.at = %s AND e.id < %s))")
                params.extend([at, at, int(cid)])
        params.append(limit + 1)
        with connections["owner"].cursor() as db:
            db.execute(
                "SELECT e.id, e.at, j.task_name, j.attempts, j.args->>'tenant_id' "
                "FROM procrastinate_events e JOIN procrastinate_jobs j ON j.id = e.job_id WHERE "
                + " AND ".join(clauses)
                + " ORDER BY e.at DESC, e.id DESC LIMIT %s",
                params,
            )
            for id, at, task, attempts, job_tenant in db.fetchall():
                try:
                    slug = slugs.get(UUID(job_tenant)) if job_tenant else None
                except ValueError, TypeError:
                    slug = None
                item = ActivityItem(
                    id=str(id),
                    at=at,
                    kind="job",
                    tenant=slug,
                    channel=None,
                    icon="💥",
                    title=f"Trabajo {task} falló",
                    detail=f"Intento {attempts}",
                    status="failed",
                    link="/incidencias",
                )
                rows.append((at, 5, id, item))
    # Stable sorts preserve each source's native ID ordering, including numeric job IDs.
    rows.sort(key=lambda row: row[1])
    rows.sort(key=lambda row: row[0], reverse=True)
    page = rows[:limit]
    next_cursor = (
        encode_cursor(page[-1][0], page[-1][1], str(page[-1][2])) if len(rows) > limit else None
    )
    return ActivityPage(items=[row[3] for row in page], next_cursor=next_cursor)
