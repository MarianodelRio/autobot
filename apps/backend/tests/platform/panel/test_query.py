"""Read-only SQL console: the `readonly_all` policy itself, and the
guards and behaviour of `panel.services.query.run`."""

import threading
import time
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest
from django.db import OperationalError, connections, transaction

from autobot.ops.models import AuditEvent
from autobot.panel.errors import ApiError
from autobot.panel.services import query
from autobot.runtime.models import Contact
from autobot.tenancy.models import Tenant
from autobot.tenancy.tx import tenant_tx
from tests.helpers.integration import tg_tenant
from tests.platform.panel.conftest import post

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner", "readonly"])


def _seed_two_tenants(tenants: Any) -> tuple[Tenant, Tenant]:
    doc_a, doc_b = tg_tenant("querya"), tg_tenant("queryb")
    tenants(doc_a, doc_b)
    tenant_a = Tenant.objects.using("owner").get(pk=doc_a["id"])
    tenant_b = Tenant.objects.using("owner").get(pk=doc_b["id"])
    with tenant_tx(tenant_a.id):
        Contact.objects.create(tenant_id=tenant_a.id, channel="main", external_id="a1")
    with tenant_tx(tenant_b.id):
        Contact.objects.create(tenant_id=tenant_b.id, channel="main", external_id="b1")
    return tenant_a, tenant_b


def test_readonly_all_policy_needs_the_setting(tenants: Any) -> None:
    tenant_a, _ = _seed_two_tenants(tenants)
    with transaction.atomic(using="readonly"):
        with connections["readonly"].cursor() as cursor:
            cursor.execute("SELECT count(*) FROM contact")
            assert cursor.fetchone() == (0,)
            cursor.execute("SELECT set_config('app.readonly_all', 'on', true)")
            cursor.execute("SELECT count(*) FROM contact")
            assert cursor.fetchone() == (2,)
        transaction.set_rollback(True, using="readonly")
    with transaction.atomic(using="readonly"):
        with connections["readonly"].cursor() as cursor:
            cursor.execute("SELECT set_config('app.tenant_id', %s, true)", [str(tenant_a.id)])
            cursor.execute("SELECT count(*) FROM contact")
            assert cursor.fetchone() == (1,)
        transaction.set_rollback(True, using="readonly")


def test_run_without_tenant_sees_every_client(tenants: Any) -> None:
    _seed_two_tenants(tenants)
    result = query.run("SELECT count(*) FROM contact", tenant_id=None, actor="operator")
    assert result.rows == [[2]]


def test_run_with_tenant_sees_only_its_rows(tenants: Any) -> None:
    tenant_a, _ = _seed_two_tenants(tenants)
    result = query.run("SELECT count(*) FROM contact", tenant_id=tenant_a.id, actor="operator")
    assert result.rows == [[1]]


def test_like_wildcard_is_not_interpreted_as_a_parameter(tenants: Any) -> None:
    _seed_two_tenants(tenants)
    result = query.run(
        "SELECT count(*) FROM contact WHERE external_id LIKE '%1'",
        tenant_id=None,
        actor="operator",
    )
    assert result.rows == [[2]]


def test_columns_report_their_pg_type() -> None:
    result = query.run("SELECT 1 AS n", tenant_id=None, actor="operator")
    assert result.columns[0].name == "n"
    assert result.columns[0].type == "int4"
    assert result.rows == [[1]]


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO contact (id) VALUES ('00000000-0000-0000-0000-000000000000')",
        "UPDATE contact SET channel = 'x'",
        "DELETE FROM contact",
        "CREATE TABLE query_test_reject (id integer)",
        "SELECT 1; SELECT 2",
        "EXPLAIN SELECT 1",
        "",
        "x" * 20_001,
    ],
)
def test_rejects_anything_but_one_select(sql: str) -> None:
    with pytest.raises(ApiError) as excinfo:
        query.run(sql, tenant_id=None, actor="operator")
    assert excinfo.value.status == 400


def test_sensitive_table_is_permission_denied() -> None:
    with pytest.raises(ApiError) as excinfo:
        query.run("SELECT * FROM tenant_secret", tenant_id=None, actor="operator")
    assert excinfo.value.status == 400
    assert "permission denied" in excinfo.value.message


def test_statement_timeout_cuts_a_slow_query() -> None:
    with pytest.raises(ApiError):
        query.run("SELECT pg_sleep(11)", tenant_id=None, actor="operator")


def test_a_database_outage_is_503_but_a_timeout_stays_400(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise OperationalError("connection to server at 10.0.0.5 refused")

    monkeypatch.setattr(query, "transaction", SimpleNamespace(atomic=refuse))
    with pytest.raises(ApiError) as excinfo:
        query.run("SELECT 1", tenant_id=None, actor="operator")
    assert excinfo.value.status == 503
    assert excinfo.value.code == "unavailable"
    assert "10.0.0.5" not in excinfo.value.message  # no driver text
    monkeypatch.undo()
    with pytest.raises(ApiError) as excinfo:
        query.run("SELECT pg_sleep(11)", tenant_id=None, actor="operator")
    assert excinfo.value.status == 400


def test_truncated_to_1000_rows() -> None:
    result = query.run(
        "SELECT i FROM generate_series(1, 1500) AS i", tenant_id=None, actor="operator"
    )
    assert result.truncated
    assert len(result.rows) == 1000


def test_audits_the_query() -> None:
    query.run("SELECT 1", tenant_id=None, actor="operator")
    event = AuditEvent.objects.using("owner").filter(action="data.query").latest("at")
    assert event.actor == "operator"
    assert event.details["sql"] == "SELECT 1"


def test_audits_a_query_even_when_it_fails() -> None:
    """A query that errors (a CAST that leaks a value through the driver's message,
    for instance) must still leave a trace: the audit is recorded before running it,
    not after it succeeds."""
    sql = "SELECT * FROM tenant_secret"
    with pytest.raises(ApiError):
        query.run(sql, tenant_id=None, actor="operator")
    event = AuditEvent.objects.using("owner").filter(action="data.query").latest("at")
    assert event.actor == "operator"
    assert event.details["sql"] == sql


def test_no_setting_or_transaction_remains_after_the_query() -> None:
    query.run("SELECT 1", tenant_id=None, actor="operator")
    assert not connections["readonly"].in_atomic_block
    with connections["readonly"].cursor() as cursor:
        cursor.execute("SELECT current_setting('app.readonly_all', true)")
        assert cursor.fetchone()[0] in (None, "")


def test_query_endpoint(authed_client: Any, tenants: Any) -> None:
    tenant_a, _ = _seed_two_tenants(tenants)
    scoped = post(
        authed_client,
        "data/query",
        {"sql": "SELECT count(*) FROM contact", "tenant": tenant_a.slug},
    )
    assert scoped.status_code == 200, scoped.content
    assert scoped.json()["rows"] == [[1]]

    every_client = post(authed_client, "data/query", {"sql": "SELECT count(*) FROM contact"})
    assert every_client.json()["rows"] == [[2]]

    assert (
        post(authed_client, "data/query", {"sql": "SELECT 1", "tenant": "nope"}).status_code == 404
    )
    assert post(authed_client, "data/query", {"sql": "DROP TABLE contact"}).status_code == 400


def test_semicolons_inside_literals_and_comments_are_allowed() -> None:
    assert query._clean("select ';' as a -- ; trailing\n") == "select ';' as a -- ; trailing"
    assert query._clean('select $$a;b$$, "x;y" from (select 1 as "x;y") t;') == (
        'select $$a;b$$, "x;y" from (select 1 as "x;y") t'
    )
    assert query._clean("select 1; -- done") == "select 1"
    assert query._clean("select E'a\\';b'") == "select E'a\\';b'"
    for bad in ("select 1; select 2", "select 1; drop table x", "select 1 /* ; */; select 2"):
        with pytest.raises(ApiError):
            query._clean(bad)


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("select 1", []),
        ("select 1;", [8]),
        ("select 1;select 2;", [8, 17]),
        # single-quoted strings, with a doubled quote inside
        ("select ';'", []),
        ("select 'it''s;';", [15]),
        ("select 'a'';'';b'", []),
        # E'' strings honour backslash escapes; plain strings do not
        ("select E'a\\';b'", []),
        ("select e'a\\\\';", [13]),
        ("select 'a\\';", [11]),
        # quoted identifiers, with a doubled quote inside
        ('select "a;b"', []),
        ('select "a"";b";', [14]),
        # dollar quoting: bare and tagged, nested tag text, unterminated
        ("select $$a;b$$;", [14]),
        ("select $tag$a;$$;b$tag$;", [23]),
        ("select $tag$a;$other$;b$tag$", []),
        ("select $$ never closed; ", []),
        ("select $1;", [9]),
        # line comments
        ("select 1 -- ; here\n;", [19]),
        ("select 1 -- ; to the end", []),
        # block comments, including nested ones
        ("select /* ; */ 1;", [16]),
        ("select /* a /* ; */ ; */ 1;", [26]),
        ("select /* never closed ;", []),
        # a quote opened inside a comment does not leak out of it
        ("select 1 -- it's\n;", [17]),
        ("select 1 /* it's */;", [19]),
        # a comment marker inside a string is not a comment
        ("select '--'; select 2", [11]),
        ("select '/*'; select '*/';", [11, 24]),
    ],
)
def test_top_level_semicolons(sql: str, expected: list[int]) -> None:
    assert query._top_level_semicolons(sql) == expected


def test_the_database_itself_refuses_a_second_statement(tenants: Any) -> None:
    # Defence in depth: even bypassing `_clean`, DECLARE CURSOR takes one statement.
    connection = connections["readonly"]
    with pytest.raises(psycopg.Error) as refused, transaction.atomic(using="readonly"):
        connection.cursor().close()
        with connection.connection.cursor(name="x") as cursor:
            cursor.execute("select 1; select 2")
    assert "syntax" in str(refused.value) or "multiple" in str(refused.value)


def test_nul_and_data_errors_are_400(tenants: Any) -> None:
    with pytest.raises(ApiError) as nul:
        query.run("select 'a\x00b'", tenant_id=None, actor="operator")
    assert nul.value.status == 400
    with pytest.raises(ApiError) as out_of_range:
        query.run("select 1::smallint + 100000::int::smallint", tenant_id=None, actor="operator")
    assert out_of_range.value.status == 400


def test_cells_and_the_total_are_capped(tenants: Any) -> None:
    result = query.run("select repeat('x', 3000000)", tenant_id=None, actor="operator")
    assert len(result.rows[0][0]) == query.MAX_CELL_CHARS + 1 and result.truncated
    result = query.run(
        "select repeat('x', 9000) from generate_series(1, 900)", tenant_id=None, actor="operator"
    )
    assert result.truncated and 400 < len(result.rows) < 900


def test_jsonb_and_special_floats_are_json_safe(tenants: Any) -> None:
    result = query.run(
        "select '{\"a\": [1, 2]}'::jsonb, 'NaN'::float8, now()", tenant_id=None, actor="operator"
    )
    assert result.rows[0][:2] == ['{"a": [1, 2]}', "nan"]


def test_a_busy_console_answers_429(tenants: Any) -> None:
    held = [query._slots.acquire(blocking=False) for _ in range(query.MAX_CONCURRENT)]
    try:
        with pytest.raises(ApiError) as busy:
            query.run("select 1", tenant_id=None, actor="operator")
        assert busy.value.status == 429
    finally:
        for _ in held:
            query._slots.release()


def test_unknown_panel_routes_are_json_404(authed_client: Any) -> None:
    for path in ("/api/panel/nope/at/all", "/api/panel/"):
        response = authed_client.get(path, HTTP_HOST="127.0.0.1")
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT set_config('app.readonly_all', 'on', true)",
        "SELECT SET_CONFIG('statement_timeout', '0', true)",
        "SELECT \"set_config\"('x', 'y', true)",
        "SELECT pg_catalog.set_config('x', 'y', true)",
        "SELECT /* c */ set_config('x','y',true)",
        "WITH s AS MATERIALIZED (SELECT set_config('app.readonly_all','on',true) AS x)"
        " SELECT count(*) FROM s, contact",
        "SELECT query_to_xml('select 1', true, false, '')",
        "SELECT query_to_xml_and_xmlschema('select 1', true, false, '')",
        "SELECT table_to_xml('contact'::regclass, true, false, '')",
        "SELECT cursor_to_xml('c', 1, true, false, '')",
        "SELECT schema_to_xmlschema('public', true, false, '')",
        "SELECT pg_advisory_lock(1)",
        "SELECT pg_try_advisory_xact_lock(1)",
        "SELECT dblink('x', 'select 1')",
        "SELECT lo_import('/etc/passwd')",
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT pg_ls_dir('.')",
        "SELECT * FROM pg_ls_waldir()",
    ],
)
def test_rejects_functions_that_change_settings_or_run_dynamic_sql(sql: str) -> None:
    with pytest.raises(ApiError) as excinfo:
        query.run(sql, tenant_id=None, actor="operator")
    assert excinfo.value.status == 400
    assert "no admite la función" in excinfo.value.message


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 'set_config' AS word",
        "SELECT 1 -- set_config",
        "SELECT /* pg_read_file */ 2",
        "SELECT $$ query_to_xml $$",
        "SELECT 1 AS settings_config, 'lo_x' AS y",
    ],
)
def test_forbidden_names_in_literals_and_comments_are_fine(sql: str) -> None:
    assert query.run(sql, tenant_id=None, actor="operator").rows


def test_watchdog_cuts_a_query_that_resets_its_own_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The SQL can zero `statement_timeout` with set_config: the Python-side watchdog
    must still cut it. (The best-effort filter is bypassed here to prove the watchdog.)"""
    monkeypatch.setattr(query, "_reject_forbidden", lambda sql: None)
    monkeypatch.setattr(query, "WATCHDOG_S", 1.0)
    started = time.monotonic()
    with pytest.raises(ApiError) as excinfo:
        query.run(
            "SELECT set_config('statement_timeout', '0', true), pg_sleep(12)",
            tenant_id=None,
            actor="operator",
        )
    assert excinfo.value.status == 400
    assert time.monotonic() - started < 6


def test_watchdog_timer_is_always_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    timers: list[Any] = []
    real = threading.Timer

    def spy(*args: Any, **kwargs: Any) -> Any:
        timer = real(*args, **kwargs)
        timers.append(timer)
        return timer

    monkeypatch.setattr(threading, "Timer", spy)
    query.run("SELECT 1", tenant_id=None, actor="operator")
    with pytest.raises(ApiError):
        query.run("SELECT * FROM tenant_secret", tenant_id=None, actor="operator")
    assert len(timers) == 2
    assert all(timer.finished.is_set() for timer in timers)
