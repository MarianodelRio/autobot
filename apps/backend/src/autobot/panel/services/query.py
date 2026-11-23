"""Read-only SQL console: a single SELECT through fp_readonly, always
rolled back. CONN_MAX_AGE=0 on the `readonly` alias closes the connection after every
request, so nothing from a query (a GUC, a lingering transaction) can survive it.

Security model, honestly: the per-tenant scope (`app.tenant_id`) is a convenience, NOT a
barrier. The query runs as `fp_readonly` and can call `set_config(...)` (directly or via
`query_to_xml` and friends, which run SQL dynamically) to flip `app.readonly_all` or
`statement_timeout`. `FORBIDDEN_FUNCTIONS` rejects the obvious spellings on a best-effort
basis, but it is a filter, not a proof. The real barriers are: the `fp_readonly` role
(SELECT only, NOBYPASSRLS, no access to `SENSITIVE_TABLES`), the read-only transaction that
is always rolled back, and the panel being reachable only through the SSH tunnel with
password + TOTP. Whoever can type here is already a fully trusted operator. The timeout is
likewise enforced twice: `statement_timeout` (a GUC the SQL could reset) and a Python
watchdog that cancels the query from outside."""

import contextlib
import json
import math
import re
import threading
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import psycopg
from django.db import DatabaseError, InterfaceError, OperationalError, connections, transaction

from autobot.ops.audit import record
from autobot.panel.errors import ApiError

MAX_SQL_LENGTH = 20_000
MAX_ROWS = 1_000
MAX_CELL_CHARS = 10_000
MAX_RESULT_BYTES = 5_000_000
MAX_CONCURRENT = 2
WATCHDOG_S = 10.5  # a little over statement_timeout, so the server's own error wins normally
FORBIDDEN_FUNCTIONS = re.compile(
    r"\b(set_config|\w*_to_xml\w*|\w*xmlschema\w*|pg_\w*advisory\w*|dblink\w*|lo_\w+"
    r"|pg_read\w*|pg_ls_\w*)\b"
)
STATEMENT = re.compile(r"^\s*(WITH\b.*?\bSELECT\b|SELECT\b|VALUES\b)", re.IGNORECASE | re.DOTALL)
DOLLAR_TAG = re.compile(r"\$(?:[A-Za-z_\x80-\uffff][\w\x80-\uffff]*)?\$")

# Each query holds two connections (owner for the audit row, readonly for the query):
# without a cap, a burst of slow queries exhausts PostgreSQL's connections.
_slots = threading.BoundedSemaphore(MAX_CONCURRENT)


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


def _top_level_semicolons(sql: str) -> list[int]:
    """Positions of `;` outside string literals, quoted identifiers, dollar quotes and
    comments, so `select ';'` or a `-- ;` comment are not mistaken for a second
    statement."""
    found: list[int] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch == ";":
            found.append(i)
        elif ch == "-" and sql.startswith("--", i):
            end = sql.find("\n", i)
            i = n if end < 0 else end
            continue
        elif ch == "/" and sql.startswith("/*", i):
            depth = 1
            i += 2
            while i < n and depth:
                if sql.startswith("/*", i):
                    depth += 1
                    i += 2
                elif sql.startswith("*/", i):
                    depth -= 1
                    i += 2
                else:
                    i += 1
            continue
        elif ch in "'\"":
            escapes = ch == "'" and i > 0 and sql[i - 1] in "eE"
            i += 1
            while i < n:
                if escapes and sql[i] == "\\":
                    i += 2
                    continue
                if sql[i] == ch:
                    if sql.startswith(ch, i + 1):
                        i += 2
                        continue
                    break
                i += 1
        elif ch == "$":
            tag = DOLLAR_TAG.match(sql, i)
            if tag is not None:
                end = sql.find(tag.group(), tag.end())
                i = n if end < 0 else end + len(tag.group())
                continue
        i += 1
    return found


def _normalize(sql: str) -> str:
    """Lowercased SQL without comments, string literals, dollar-quoted bodies or the
    quotes of identifiers, so `"Set_Config"`, `set_/**/config` and `pg_catalog."set_config"`
    all read `set_config`, while a literal like `'set_config'` is ignored."""
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if sql.startswith("--", i):
            end = sql.find("\n", i)
            i = n if end < 0 else end
            continue
        if sql.startswith("/*", i):
            depth, i = 1, i + 2
            while i < n and depth:
                if sql.startswith("/*", i):
                    depth, i = depth + 1, i + 2
                elif sql.startswith("*/", i):
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
            out.append(" ")
            continue
        if ch == "'":
            escapes = i > 0 and sql[i - 1] in "eE"
            i += 1
            while i < n:
                if escapes and sql[i] == "\\":
                    i += 2
                    continue
                if sql[i] == "'":
                    if sql.startswith("'", i + 1):
                        i += 2
                        continue
                    break
                i += 1
            i += 1
            out.append(" ")
            continue
        if ch == "$" and (tag := DOLLAR_TAG.match(sql, i)) is not None:
            end = sql.find(tag.group(), tag.end())
            i = n if end < 0 else end + len(tag.group())
            out.append(" ")
            continue
        if ch != '"':
            out.append(ch.lower())
        i += 1
    return "".join(out)


def _reject_forbidden(sql: str) -> None:
    found = FORBIDDEN_FUNCTIONS.search(_normalize(sql))
    if found:
        raise ApiError(
            "bad_request",
            f"La consola no admite la función «{found.group()}» "
            "(cambia la configuración o ejecuta SQL dinámico).",
            400,
        )


def _strip_trailing_comments(sql: str) -> str:
    return re.sub(r"(\s|--[^\n]*(\n|$)|/\*.*?\*/)+$", "", sql, flags=re.DOTALL)


def _clean(sql: str) -> str:
    sql = sql.strip()
    if "\x00" in sql:
        raise ApiError("bad_request", "La consulta no puede contener caracteres NUL.", 400)
    if len(sql) > MAX_SQL_LENGTH:
        raise ApiError("bad_request", "La consulta supera los 20 000 caracteres.", 400)
    semicolons = _top_level_semicolons(sql)
    if semicolons:
        # Only one final `;` (optionally followed by comments) is tolerated.
        if len(semicolons) > 1 or _strip_trailing_comments(sql[semicolons[0] + 1 :]):
            raise ApiError("bad_request", "Solo se admite una sentencia.", 400)
        sql = sql[: semicolons[0]].rstrip()
    if not sql:
        raise ApiError("bad_request", "La consulta está vacía.", 400)
    if not STATEMENT.match(sql):
        raise ApiError("bad_request", "Solo se admiten SELECT, WITH … SELECT o VALUES.", 400)
    _reject_forbidden(sql)
    return sql


def _column(description: Any, type_registry: Any) -> Column:
    info = type_registry.get(description.type_code)
    return Column(description.name, info.name if info else str(description.type_code))


def _cell(value: Any) -> tuple[Any, int, bool]:
    """The JSON-safe form of a cell, its approximate size and whether it was cut."""
    if value is None or isinstance(value, bool):
        return value, 1, False
    if isinstance(value, memoryview | bytes):
        text = f"<{len(value)} bytes>"
        return text, len(text), False
    if isinstance(value, int):
        return value, 8, False
    if isinstance(value, float):
        return (value if math.isfinite(value) else str(value)), 8, False
    if isinstance(value, list | dict | tuple):
        try:
            text = json.dumps(value, default=str, ensure_ascii=False)
        except ValueError, TypeError:
            text = str(value)
        if len(text) <= MAX_CELL_CHARS:
            return _jsonable(value), len(text), False
        return text[:MAX_CELL_CHARS] + "…", MAX_CELL_CHARS, True
    text = value if isinstance(value, str) else str(value)
    if len(text) > MAX_CELL_CHARS:
        return text[:MAX_CELL_CHARS] + "…", MAX_CELL_CHARS, True
    return text, len(text), False


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    return str(value)


def _error(exc: Exception) -> ApiError:
    return ApiError("bad_request", str(exc).strip()[:500] or "Consulta no válida.", 400)


def _unavailable(exc: Exception) -> bool:
    """A failure of the database itself (connection lost or refused, server shutting
    down), not of the query. A timeout or a cancel (`QueryCanceled`, also an
    OperationalError) is the query's fault and stays a 400."""
    cause = exc.__cause__ or exc
    if isinstance(cause, psycopg.errors.QueryCanceled):
        return False
    return isinstance(exc, (OperationalError, InterfaceError)) or isinstance(
        cause, (psycopg.OperationalError, psycopg.InterfaceError)
    )


def run(sql: str, *, tenant_id: UUID | None, actor: str) -> QueryResult:
    sql = _clean(sql)
    if not _slots.acquire(blocking=False):
        raise ApiError("busy", "Consola ocupada: espera a que termine otra consulta.", 429)
    try:
        return _run(sql, tenant_id=tenant_id, actor=actor)
    finally:
        _slots.release()


def _fetch(cursor: Any) -> tuple[list[list[Any]], bool]:
    """Fetches in growing batches, so one giant row cannot be pulled `batch` times over,
    stopping at MAX_ROWS or MAX_RESULT_BYTES; cells are cut as they arrive."""
    rows: list[list[Any]] = []
    total = 0
    truncated = False
    batch = 1
    while len(rows) < MAX_ROWS:
        fetched = cursor.fetchmany(min(batch, MAX_ROWS - len(rows)))
        if not fetched:
            return rows, truncated
        batch_size = 0
        for raw in fetched:
            cells = [_cell(v) for v in raw]
            size = sum(c[1] for c in cells)
            truncated = truncated or any(c[2] for c in cells)
            if total + size > MAX_RESULT_BYTES:
                return rows, True
            total += size
            batch_size += size
            rows.append([c[0] for c in cells])
        batch = min(batch * 2, 200) if batch_size < 50_000 else 1
    # Exactly MAX_ROWS read: is there more?
    return rows, truncated or bool(cursor.fetchmany(1))


def _cancel(raw: Any) -> None:
    with contextlib.suppress(psycopg.Error):
        raw.cancel()


def _run(sql: str, *, tenant_id: UUID | None, actor: str) -> QueryResult:
    # Recorded before running, not after: a failure (e.g. a CAST error that leaks a
    # value through the driver's message) must never leave a query without a trace.
    record(
        actor=actor,
        action="data.query",
        summary="Consulta SQL ejecutada.",
        details={"sql": sql},
    )
    started = time.monotonic()
    connection = connections["readonly"]
    # Out-of-band timeout: it does not depend on a GUC the SQL could reset.
    watchdog: threading.Timer | None = None
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
            raw = connection.connection
            watchdog = threading.Timer(WATCHDOG_S, _cancel, args=(raw,))
            watchdog.daemon = True
            watchdog.start()
            type_registry = raw.adapters.types
            with connection.connection.cursor(name="panel_query") as server_cursor:
                server_cursor.execute(sql)
                columns = [_column(c, type_registry) for c in server_cursor.description or []]
                rows, truncated = _fetch(server_cursor)
            transaction.set_rollback(True, using="readonly")
    except (DatabaseError, psycopg.Error, ValueError) as exc:
        # DataError, a NUL byte, an invalid cast...: always the caller's fault, never a 500.
        if _unavailable(exc):
            raise ApiError(
                "unavailable", "La base de datos no está disponible: inténtalo de nuevo.", 503
            ) from None
        raise _error(exc) from None
    finally:
        if watchdog is not None:
            watchdog.cancel()
    duration_ms = int((time.monotonic() - started) * 1000)
    return QueryResult(columns, rows, truncated, duration_ms)
