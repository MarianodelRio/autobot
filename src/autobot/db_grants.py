"""Desired PostgreSQL permissions (ADR-009), declared as idempotent SQL and reapplied
on every migration that creates tables or changes permissions, on every deploy, and
after every restore (pg_restore --no-acl drops them). A single source of truth instead
of relying on a migration staying in the restored dump."""

from typing import Any

SENSITIVE_TABLES: tuple[str, ...] = (
    "auth_user",
    "django_session",
    "otp_totp_totpdevice",
    "tenant_secret",
)
# Config tables (ADR-009): fp_app keeps SELECT, but only fp_owner (the panel, the
# commands) writes.
CONFIG_TABLES: tuple[str, ...] = (
    "tenant_document_version",
    "tenant_dataset_version",
    "tenant_secret",
    "config_revision",
)


def _revoke_if_exists(table: str, role: str, privileges: str = "ALL") -> str:
    # The table may not exist yet: either a third-party app's migration (auth, sessions,
    # django_otp) hasn't run, or — since this whole function is reapplied by every
    # migration from here on — a later migration of ours creates it.
    return (
        "DO $$ BEGIN "
        f"IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = '{table}') "
        f"THEN EXECUTE 'REVOKE {privileges} ON {table} FROM {role}'; "
        "END IF; END $$"
    )


def statements() -> list[str]:
    return [
        "REVOKE INSERT, UPDATE, DELETE ON tenant FROM fp_app",
        _revoke_if_exists("audit_event", "fp_app"),
        *(_revoke_if_exists(table, "fp_app", "INSERT, UPDATE, DELETE") for table in CONFIG_TABLES),
        "GRANT SELECT ON ALL TABLES IN SCHEMA public TO fp_readonly",
        "ALTER DEFAULT PRIVILEGES FOR ROLE fp_owner IN SCHEMA public "
        "GRANT SELECT ON TABLES TO fp_readonly",
        *(_revoke_if_exists(table, "fp_readonly") for table in SENSITIVE_TABLES),
    ]


def apply(connection: Any) -> None:
    with connection.cursor() as cursor:
        for statement in statements():
            cursor.execute(statement)
