"""Read-only SQL console: a single SELECT through fp_readonly, always
rolled back. CONN_MAX_AGE=0 on the `readonly` alias closes the connection after every
request, so nothing from a query (a GUC, a lingering transaction) can survive it."""

import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg
from django.db import DatabaseError, connections, transaction

from autobot.ops.audit import record
from autobot.panel.errors import ApiError

MAX_SQL_LENGTH = 20_000
MAX_ROWS = 1_000
STATEMENT = re.compile(r"^\s*(WITH\b.*?\bSELECT\b|SELECT\b|VALUES\b)", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class Column:
    name: str
    type: str


@dataclass(frozen=True)
class QueryResult:
    columns: list[Column]
    rows: list[list[Any]]
    truncated: bool
    duration_ms: int


def _clean(sql: str) -> str:
    sql = sql.strip()
    if sql.endswith(";"):
        sql = sql[:-1].rstrip()
    if not sql:
        raise ApiError("bad_request", "La consulta está vacía.", 400)
    if len(sql) > MAX_SQL_LENGTH:
        raise ApiError("bad_request", "La consulta supera los 20 000 caracteres.", 400)
    if ";" in sql:
        raise ApiError("bad_request", "Solo se admite una sentencia.", 400)
    if not STATEMENT.match(sql):
        raise ApiError("bad_request", "Solo se admiten SELECT, WITH … SELECT o VALUES.", 400)
    return sql


def _column(description: Any, type_registry: Any) -> Column:
    info = type_registry.get(description.type_code)
    return Column(description.name, info.name if info else str(description.type_code))


def _cell(value: Any) -> Any:
    if isinstance(value, memoryview | bytes):
        return f"<{len(value)} bytes>"
    if isinstance(value, Decimal | UUID | datetime | date):
        return str(value)
    return value


def run(sql: str, *, tenant_id: UUID | None, actor: str) -> QueryResult:
    sql = _clean(sql)
    started = time.monotonic()
    connection = connections["readonly"]
    try:
        with transaction.atomic(using="readonly"):
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute("SET LOCAL statement_timeout = '10s'")
                cursor.execute("SET LOCAL idle_in_transaction_session_timeout = '15s'")
                if tenant_id is not None:
                    cursor.execute("SELECT set_config('app.tenant_id', %s, true)", [str(tenant_id)])
                else:
                    cursor.execute("SELECT set_config('app.readonly_all', 'on', true)")
            type_registry = connection.connection.adapters.types
            with connection.connection.cursor(name="panel_query") as server_cursor:
                server_cursor.execute(sql)
                columns = [_column(c, type_registry) for c in server_cursor.description or []]
                fetched = server_cursor.fetchmany(MAX_ROWS + 1)
            transaction.set_rollback(True, using="readonly")
    except (DatabaseError, psycopg.Error) as exc:
        raise ApiError("bad_request", str(exc).strip()[:500], 400) from None
    truncated = len(fetched) > MAX_ROWS
    rows = [[_cell(v) for v in row] for row in fetched[:MAX_ROWS]]
    duration_ms = int((time.monotonic() - started) * 1000)
    record(
        actor=actor,
        action="data.query",
        summary="Consulta SQL ejecutada.",
        details={"sql": sql},
    )
    return QueryResult(columns, rows, truncated, duration_ms)
