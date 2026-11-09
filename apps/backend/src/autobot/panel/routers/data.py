"""Database catalogue."""

from typing import Any

from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router, Schema
from pydantic import Field

from autobot.panel.services import catalog, query
from autobot.tenancy.models import Tenant

router = Router(tags=["data"])


class QueryIn(Schema):
    sql: str = Field(min_length=1, max_length=20_000)
    tenant: str = ""


class ColumnOut(Schema):
    name: str
    type: str


class QueryOut(Schema):
    columns: list[ColumnOut]
    rows: list[list[Any]]
    truncated: bool
    duration_ms: int


class RelationOut(Schema):
    name: str
    source: str
    target: str
    columns: list[str]
    target_columns: list[str]


class TenantCountOut(Schema):
    tenant_id: str | None
    tenant: str | None
    count: int


class TableColumnOut(Schema):
    name: str
    type: str
    nullable: bool
    primary_key: bool
    description: str
    hidden: bool


class TableSummaryOut(Schema):
    name: str
    group: str
    description: str
    written_by: str
    retention: str
    rls: bool
    row_count: int
    approx: bool
    bytes: int
    columns: list[TableColumnOut]
    rows_by_tenant: list[TenantCountOut]
    incoming: list[RelationOut]
    outgoing: list[RelationOut]


class TableDetailOut(TableSummaryOut):
    rows: list[list[Any]]


@router.get("/data/tables", response=list[TableSummaryOut])
def tables(request: HttpRequest) -> list[dict[str, Any]]:
    return catalog.table_list()


@router.get("/data/tables/{name}", response=TableDetailOut)
def table(request: HttpRequest, name: str) -> dict[str, Any]:
    return catalog.table_detail(name)


@router.post("/data/query", response=QueryOut)
def run_query(request: HttpRequest, payload: QueryIn) -> query.QueryResult:
    tenant_id = None
    if payload.tenant:
        tenant = get_object_or_404(Tenant.objects.using("owner"), slug=payload.tenant)
        tenant_id = tenant.id
    return query.run(payload.sql, tenant_id=tenant_id, actor=request.user.username)
