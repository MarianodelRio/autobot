"""Documented database inventory and safe previews for the operator panel."""

from dataclasses import dataclass, field
from typing import Any

import psycopg
from django.db import DatabaseError, connections, transaction
from django.http import Http404
from ninja import Schema

from autobot.db.grants import SENSITIVE_TABLES
from autobot.ops.audit import record
from autobot.panel.errors import ApiError
from autobot.tenancy.models import Tenant


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


@dataclass(frozen=True)
class TableDoc:
    group: str
    description: str
    written_by: str
    retention: str
    rls: bool
    columns: dict[str, str] = field(default_factory=dict)


CONFIG = "Negocios y config"
MESSAGES = "Conversaciones y mensajes"
METRICS = "Avisos y métricas"
DEMO = "Demo y dueños"
QUEUE = "Cola de trabajos"
PANEL = "Operación del panel"
DJANGO = "Django interno"

CATALOG: dict[str, TableDoc] = {
    "tenant": TableDoc(
        CONFIG,
        "Identidad y estado de los negocios.",
        "Configuración del panel",
        "Hasta la purga del negocio",
        False,
    ),
    "tenant_document_version": TableDoc(
        CONFIG,
        "Versiones de la configuración de cada negocio.",
        "Panel y comandos",
        "Hasta la purga del negocio",
        False,
    ),
    "tenant_dataset_version": TableDoc(
        CONFIG,
        "Versiones de los datos publicados de cada negocio.",
        "Panel y comandos",
        "Hasta la purga del negocio",
        False,
    ),
    "dataset_library_version": TableDoc(
        CONFIG,
        "Biblioteca de conjuntos de datos (ADR-013), independiente de cualquier"
        " negocio; se copian a tenant_dataset_version al elegirlos o aplicarlos.",
        "Comando dataset_library",
        "Permanente",
        False,
    ),
    "tenant_secret": TableDoc(
        CONFIG,
        "Credenciales cifradas de los canales.",
        "Panel y comandos",
        "Hasta la purga del negocio",
        False,
        {"ciphertext": "Credenciales cifradas, ocultas."},
    ),
    "config_revision": TableDoc(
        CONFIG,
        "Revisión global para recargar la configuración.",
        "Panel y comandos",
        "Permanente",
        False,
    ),
    "contact": TableDoc(
        MESSAGES,
        "Personas que han contactado con un negocio.",
        "Procesador de mensajes",
        "12 meses desde la última actividad",
        True,
    ),
    "conversation": TableDoc(
        MESSAGES,
        "Estado de conversación de cada contacto.",
        "Procesador de mensajes",
        "Según la política de retención del negocio",
        True,
    ),
    "inbound_event": TableDoc(
        MESSAGES,
        "Eventos recibidos del canal.",
        "Webhooks y procesador",
        "Contenido 30 días; evento 90 días",
        True,
        {"effect_state": "Efectos ya realizados para evitar duplicados."},
    ),
    "outbound_message": TableDoc(
        MESSAGES,
        "Mensajes de respuesta y proactivos enviados.",
        "Procesador y worker",
        "Contenido 30 días; registro 12 meses",
        True,
        {
            "idem_key": "Clave de idempotencia del envío.",
            "unknown_at": "Inicio del estado de entrega ambigua.",
            "expires_at": "Límite para entregarlo; pasado, queda caducado y no se envía.",
        },
    ),
    "notification": TableDoc(
        METRICS,
        "Avisos enviados al dueño del negocio.",
        "Worker",
        "Según la política de retención del negocio",
        True,
    ),
    "metric_event": TableDoc(
        METRICS,
        "Eventos agregables del negocio.",
        "Procesador y worker",
        "Según la política de retención del negocio",
        True,
    ),
    "demo_event": TableDoc(
        DEMO,
        "Eventos de las puertas de demostración.",
        "Webhooks de demo",
        "7 días",
        False,
    ),
    "demo_session": TableDoc(
        DEMO,
        "Selección de negocio para una sesión de demostración.",
        "Selector de demo",
        "30 días",
        False,
    ),
    "demo_invite": TableDoc(
        DEMO,
        "Código de invitación a una puerta de demo.",
        "Panel",
        "30 días tras caducar, agotarse o revocarse",
        False,
        {"code": "Código de invitación, oculto."},
    ),
    "demo_access_grant": TableDoc(
        DEMO,
        "Identidad que canjeó un código de invitación a una puerta de demo.",
        "Selector de demo",
        "Según la caducidad de su invitación",
        False,
    ),
    "owner_event": TableDoc(
        DEMO,
        "Eventos recibidos por el bot del dueño.",
        "Webhook del bot de dueños",
        "7 días",
        False,
    ),
    "owner_link": TableDoc(
        DEMO,
        "Vinculación del dueño con Telegram.",
        "Bot del dueño y comandos",
        "Hasta la purga del negocio",
        False,
        {"invite_hash": "Huella de invitación, oculta."},
    ),
    "procrastinate_jobs": TableDoc(
        QUEUE,
        "Trabajos y estado de la cola.",
        "Procrastinate",
        "Según limpieza de trabajos",
        False,
        {"args": "Argumentos del trabajo: identificadores."},
    ),
    "procrastinate_events": TableDoc(
        QUEUE,
        "Eventos del ciclo de vida de los trabajos.",
        "Procrastinate",
        "Según limpieza de trabajos",
        False,
    ),
    "procrastinate_workers": TableDoc(
        QUEUE, "Workers y últimos latidos.", "Procrastinate", "Gestionada por Procrastinate", False
    ),
    "procrastinate_periodic_defers": TableDoc(
        QUEUE,
        "Ejecuciones programadas para evitar duplicados.",
        "Procrastinate",
        "Gestionada por Procrastinate",
        False,
    ),
    "audit_event": TableDoc(
        PANEL, "Auditoría de acciones del operador.", "Panel y comandos", "12 meses", False
    ),
    "privacy_suppression": TableDoc(
        PANEL,
        "Libro de supresiones: olvidos y purgas (ids y HMAC, sin datos personales).",
        "Comandos de olvido y purga",
        "Indefinida (prueba de supresión, ADR-019)",
        False,
        {"identity_hashes": "HMAC de la identidad olvidada, oculto."},
    ),
    "ops_alert": TableDoc(
        PANEL,
        "Alertas operativas persistidas.",
        "Worker y panel",
        "12 meses desde su resolución",
        False,
    ),
    "system_sample": TableDoc(
        PANEL, "Muestras periódicas del sistema.", "Worker", "62 días", False
    ),
    "platform_cache": TableDoc(
        PANEL,
        "Caché de plataforma y señales operativas.",
        "Web y worker",
        "Hasta caducidad o borrado",
        False,
        {"value": "Contenido de caché, oculto."},
    ),
    "auth_user": TableDoc(
        DJANGO,
        "Usuarios de acceso al panel.",
        "Django y comandos",
        "Hasta su eliminación",
        False,
        {"password": "Huella de contraseña, oculta."},
    ),
    "auth_group": TableDoc(
        DJANGO, "Grupos de permisos de Django.", "Django", "Hasta su eliminación", False
    ),
    "auth_permission": TableDoc(
        DJANGO, "Permisos de Django.", "Migraciones de Django", "Hasta su eliminación", False
    ),
    "auth_group_permissions": TableDoc(
        DJANGO, "Asignación de permisos a grupos.", "Django", "Hasta su eliminación", False
    ),
    "auth_user_groups": TableDoc(
        DJANGO, "Asignación de usuarios a grupos.", "Django", "Hasta su eliminación", False
    ),
    "auth_user_user_permissions": TableDoc(
        DJANGO, "Permisos individuales de usuarios.", "Django", "Hasta su eliminación", False
    ),
    "django_content_type": TableDoc(
        DJANGO, "Tipos de modelos registrados por Django.", "Django", "Hasta su eliminación", False
    ),
    "django_migrations": TableDoc(
        DJANGO, "Historial de migraciones aplicadas.", "Django", "Permanente", False
    ),
    "django_session": TableDoc(
        DJANGO,
        "Sesiones del panel.",
        "Django",
        "Hasta caducidad y limpieza",
        False,
        {
            "session_data": "Contenido de sesión, oculto.",
            "session_key": "Clave de sesión, oculta (permitiría secuestrar la sesión).",
        },
    ),
    "otp_totp_totpdevice": TableDoc(
        DJANGO,
        "Dispositivos de segundo factor.",
        "Django OTP y comandos",
        "Hasta su eliminación",
        False,
        {"key": "Clave de segundo factor, oculta."},
    ),
}

HIDDEN_COLUMNS = frozenset(
    {
        ("tenant_secret", "ciphertext"),
        ("auth_user", "password"),
        ("django_session", "session_data"),
        ("django_session", "session_key"),
        ("otp_totp_totpdevice", "key"),
        ("owner_link", "invite_hash"),
        ("platform_cache", "value"),
        ("demo_invite", "code"),
        # Payloads and free text: message bodies, phones and names of end customers.
        ("inbound_event", "payload"),
        ("inbound_event", "error"),
        ("outbound_message", "payload"),
        ("outbound_message", "last_error"),
        ("conversation", "state"),
        ("notification", "text"),
        ("demo_event", "payload"),
        ("owner_event", "payload"),
        ("audit_event", "details"),
    }
)
UNKNOWN = TableDoc("Sin catalogar", "Tabla sin documentar.", "Desconocido", "Desconocida", False)


def _identifier(value: str) -> str:
    """Quote a PostgreSQL identifier, including quotes in uncatalogued names."""
    return '"' + value.replace('"', '""') + '"'


def _catalog_metadata() -> dict[str, dict[str, Any]]:
    with connections["owner"].cursor() as cursor:
        cursor.execute("""
            SELECT c.relname, c.reltuples, pg_total_relation_size(c.oid), c.relrowsecurity
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
        """)
        return {
            name: {"estimate": estimate, "bytes": size, "rls": rls}
            for name, estimate, size, rls in cursor.fetchall()
        }


def _relations() -> list[dict[str, Any]]:
    with connections["owner"].cursor() as cursor:
        cursor.execute("""
            SELECT con.conname, src.relname, dst.relname,
                   ARRAY(SELECT a.attname FROM unnest(con.conkey) WITH ORDINALITY AS k(num, ord)
                         JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.num
                         ORDER BY k.ord),
                   ARRAY(SELECT a.attname FROM unnest(con.confkey) WITH ORDINALITY AS k(num, ord)
                         JOIN pg_attribute a ON a.attrelid = con.confrelid AND a.attnum = k.num
                         ORDER BY k.ord)
            FROM pg_constraint con JOIN pg_class src ON src.oid = con.conrelid
            JOIN pg_namespace ns ON ns.oid = src.relnamespace
            JOIN pg_class dst ON dst.oid = con.confrelid
            JOIN pg_namespace nd ON nd.oid = dst.relnamespace
            WHERE con.contype = 'f' AND ns.nspname = 'public' AND nd.nspname = 'public'
            ORDER BY src.relname, con.conname
        """)
        return [
            dict(
                name=name,
                source=source,
                target=target,
                columns=columns,
                target_columns=target_columns,
            )
            for name, source, target, columns, target_columns in cursor.fetchall()
        ]


def _columns(table: str) -> list[dict[str, Any]]:
    with connections["owner"].cursor() as cursor:
        cursor.execute(
            """
            SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull,
                   EXISTS (SELECT 1 FROM pg_index i WHERE i.indrelid = c.oid
                           AND i.indisprimary AND a.attnum = ANY(i.indkey))
            FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relname = %s AND a.attnum > 0 AND NOT a.attisdropped
            ORDER BY a.attnum
        """,
            [table],
        )
        descriptions = CATALOG.get(table, UNKNOWN).columns
        return [
            dict(
                name=name,
                type=kind,
                nullable=not required,
                primary_key=primary,
                description=descriptions.get(name, ""),
                hidden=(table, name) in HIDDEN_COLUMNS,
            )
            for name, kind, required, primary in cursor.fetchall()
        ]


def _tenant_slugs() -> dict[str, str]:
    return {str(id): slug for id, slug in Tenant.objects.using("owner").values_list("id", "slug")}


STATS_TIMEOUT = "2s"
DETAIL_TIMEOUT = "5s"


def _stats(
    name: str, metadata: dict[str, Any], columns: list[dict[str, Any]], slugs: dict[str, str]
) -> dict[str, Any]:
    """Exact counts only where they are cheap: from `reltuples` up, the row count is the
    planner's estimate and the per-client breakdown is skipped (a full GROUP BY over a
    big table is what made this screen slow). Each query has its own
    `statement_timeout`; a timeout degrades to the estimate instead of failing."""
    quote = _identifier
    estimated = metadata["estimate"]
    approx = estimated >= 100_000
    count = int(max(estimated, 0))
    counts: list[dict[str, Any]] = []
    try:
        with transaction.atomic(using="owner"), connections["owner"].cursor() as cursor:
            cursor.execute(f"SET LOCAL statement_timeout = '{STATS_TIMEOUT}'")
            if not approx:
                cursor.execute(f"SELECT count(*) FROM public.{quote(name)}")
                count = cursor.fetchone()[0]
    except DatabaseError:
        approx = True
    if not approx and any(column["name"] == "tenant_id" for column in columns):
        try:
            with transaction.atomic(using="owner"), connections["owner"].cursor() as cursor:
                cursor.execute(f"SET LOCAL statement_timeout = '{STATS_TIMEOUT}'")
                cursor.execute(
                    f"SELECT tenant_id, count(*) FROM public.{quote(name)} "
                    "GROUP BY tenant_id ORDER BY tenant_id"
                )
                counts = [
                    dict(
                        tenant_id=str(id) if id is not None else None,
                        tenant=slugs.get(str(id)) if id is not None else None,
                        count=value,
                    )
                    for id, value in cursor.fetchall()
                ]
        except DatabaseError:
            counts = []
    return dict(row_count=count, approx=approx, bytes=metadata["bytes"], rows_by_tenant=counts)


def table_list() -> list[dict[str, Any]]:
    metadata = _catalog_metadata()
    relations = _relations()
    slugs = _tenant_slugs()
    result = []
    for name, info in sorted(metadata.items()):
        doc = CATALOG.get(name, UNKNOWN)
        columns = _columns(name)
        result.append(
            dict(
                name=name,
                group=doc.group,
                description=doc.description,
                written_by=doc.written_by,
                retention=doc.retention,
                rls=info["rls"],
                columns=columns,
                **_stats(name, info, columns, slugs),
                incoming=[r for r in relations if r["target"] == name],
                outgoing=[r for r in relations if r["source"] == name],
            )
        )
    return result


ORDER_COLUMNS = ("at", "created_at", "received_at", "taken_at", "updated_at")
DETAIL_LIMIT = 20


def _pick_order(columns: list[dict[str, Any]]) -> str | None:
    """The column a preview is sorted by, newest first: the first date column of
    `ORDER_COLUMNS`, else the primary key, else none."""
    dates = {col["name"] for col in columns if col["type"].startswith(("timestamp", "date"))}
    return next(
        (column for column in ORDER_COLUMNS if column in dates),
        next((col["name"] for col in columns if col["primary_key"]), None),
    )


def _build_select(name: str, columns: list[dict[str, Any]], order: str | None) -> str:
    quote = _identifier
    expressions = ["'<oculto>'" if col["hidden"] else quote(col["name"]) for col in columns]
    query = f"SELECT {', '.join(expressions)} FROM public.{quote(name)}"
    if order:
        query += f" ORDER BY {quote(order)} DESC NULLS LAST"
    return f"{query} LIMIT {DETAIL_LIMIT}"


def _run_sample(query: str) -> list[list[Any]]:
    try:
        with transaction.atomic(using="owner"), connections["owner"].cursor() as cursor:
            cursor.execute(f"SET LOCAL statement_timeout = '{DETAIL_TIMEOUT}'")
            cursor.execute(query)
            return [
                [
                    f"<{len(value)} bytes>"
                    if isinstance(value, (bytes, bytearray, memoryview))
                    else value
                    for value in row
                ]
                for row in cursor.fetchall()
            ]
    except (DatabaseError, psycopg.Error) as exc:
        raise ApiError("bad_request", str(exc).strip()[:500], 400) from None


def table_detail(name: str, *, actor: str) -> TableDetailOut:
    metadata = _catalog_metadata()
    if name not in CATALOG or name not in metadata:
        raise Http404
    doc = CATALOG[name]
    columns = _columns(name)
    query = _build_select(name, columns, _pick_order(columns))
    # Recorded before running, not after: a failure (e.g. a CAST error that leaks a
    # value through the driver's message) must never leave a view without a trace.
    record(
        actor=actor,
        action="data.table",
        summary="Vista de tabla consultada.",
        details={"table": name},
    )
    # Sensitive tables are not previewed at all (same rule as fp_readonly in the SQL
    # console); the owner connection here would otherwise bypass it.
    rows = [] if name in SENSITIVE_TABLES else _run_sample(query)
    relations = _relations()
    return TableDetailOut.model_validate(
        dict(
            name=name,
            group=doc.group,
            description=doc.description,
            written_by=doc.written_by,
            retention=doc.retention,
            rls=metadata[name]["rls"],
            columns=columns,
            rows=rows,
            **_stats(name, metadata[name], columns, _tenant_slugs()),
            incoming=[r for r in relations if r["target"] == name],
            outgoing=[r for r in relations if r["source"] == name],
        )
    )
