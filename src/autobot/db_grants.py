"""Desired PostgreSQL permissions (ADR-009), declared as idempotent SQL and reapplied
on every migration that creates tables or changes permissions, on every deploy, and
after every restore (pg_restore --no-acl drops them). A single source of truth instead
of relying on a migration staying in the restored dump."""

from typing import Any

SENSITIVE_TABLES: tuple[str, ...] = ("auth_user", "django_session", "otp_totp_totpdevice")


def _revoke_if_exists(table: str, role: str) -> str:
    # Third-party apps (auth, sessions, django_otp) create these tables with their own
    # migrations, which may not have run yet on a partially migrated database.
    return (
        "DO $$ BEGIN "
        f"IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = '{table}') "
        f"THEN EXECUTE 'REVOKE ALL ON {table} FROM {role}'; "
        "END IF; END $$"
    )


def statements() -> list[str]:
    return [
        "REVOKE INSERT, UPDATE, DELETE ON tenant FROM fp_app",
        "GRANT SELECT ON ALL TABLES IN SCHEMA public TO fp_readonly",
        "ALTER DEFAULT PRIVILEGES FOR ROLE fp_owner IN SCHEMA public "
        "GRANT SELECT ON TABLES TO fp_readonly",
        *(_revoke_if_exists(table, "fp_readonly") for table in SENSITIVE_TABLES),
    ]


def apply(connection: Any) -> None:
    with connection.cursor() as cursor:
        for statement in statements():
            cursor.execute(statement)
