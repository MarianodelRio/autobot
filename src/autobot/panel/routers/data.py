"""Database catalogue and saved-query CRUD."""

from datetime import datetime
from typing import Any

from django.db import transaction
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router, Schema
from ninja.responses import Status
from pydantic import Field

from autobot.ops.audit import record
from autobot.ops.models import SavedQuery
from autobot.panel.services import catalog

router = Router(tags=["data"])


class SavedQueryIn(Schema):
    name: str = Field(min_length=1)
    sql: str = Field(min_length=1, max_length=20_000)


class SavedQueryOut(Schema):
    id: int
    name: str
    sql: str
    created_at: datetime
    updated_at: datetime


@router.get("/data/tables", response=list[dict[str, Any]])
def tables(request: HttpRequest) -> list[dict[str, Any]]:
    return catalog.table_list()


@router.get("/data/tables/{name}", response=dict[str, Any])
def table(request: HttpRequest, name: str) -> dict[str, Any]:
    return catalog.table_detail(name)


@router.get("/data/saved-queries", response=list[SavedQueryOut])
def saved_queries(request: HttpRequest) -> Any:
    return SavedQuery.objects.using("owner").order_by("name", "id")


@router.post("/data/saved-queries", response=SavedQueryOut)
def create_query(request: HttpRequest, payload: SavedQueryIn) -> SavedQuery:
    with transaction.atomic(using="owner"):
        query = SavedQuery.objects.using("owner").create(**payload.model_dump())
        record(
            actor=request.user.username,
            action="saved_query.create",
            summary="Consulta guardada creada.",
            target_type="saved_query",
            target_id=str(query.pk),
        )
    return query


@router.put("/data/saved-queries/{id}", response=SavedQueryOut)
def update_query(request: HttpRequest, id: int, payload: SavedQueryIn) -> SavedQuery:
    with transaction.atomic(using="owner"):
        query = get_object_or_404(SavedQuery.objects.using("owner").select_for_update(), pk=id)
        query.name = payload.name
        query.sql = payload.sql
        query.save(using="owner", update_fields=["name", "sql", "updated_at"])
        record(
            actor=request.user.username,
            action="saved_query.update",
            summary="Consulta guardada modificada.",
            target_type="saved_query",
            target_id=str(query.pk),
        )
    return query


@router.delete("/data/saved-queries/{id}", response={204: None})
def delete_query(request: HttpRequest, id: int) -> Status[None]:
    with transaction.atomic(using="owner"):
        query = get_object_or_404(SavedQuery.objects.using("owner").select_for_update(), pk=id)
        query.delete(using="owner")
        record(
            actor=request.user.username,
            action="saved_query.delete",
            summary="Consulta guardada eliminada.",
            target_type="saved_query",
            target_id=str(id),
        )
    return Status(204, None)
