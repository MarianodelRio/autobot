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
# Django's own auth/session/OTP tables: routed to fp_owner by AuthDatabaseRouter.
# fp_app has no business with them at all, unlike CONFIG_TABLES (no SELECT either).
AUTH_TABLES: tuple[str, ...] = (
    "auth_user",
    "auth_group",
    "auth_permission",
    "auth_user_groups",
    "auth_user_user_permissions",
    "auth_group_permissions",
    "django_session",
    "otp_totp_totpdevice",
)
# Platform functions reapplied like the table grants: fp_app only gets EXECUTE, never
# PUBLIC (SECURITY DEFINER functions must not be callable by anyone who connects).
FUNCTIONS: tuple[tuple[str, str], ...] = (
    ("purge_platform_history", "purge_platform_history(timestamptz)"),
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


def _function_grants(name: str, signature: str) -> str:
    # Same reasoning as _revoke_if_exists: a migration before the one that creates the
    # function also reapplies these grants.
    return (
        "DO $$ BEGIN "
        f"IF EXISTS (SELECT FROM pg_proc WHERE proname = '{name}') THEN "
        f"EXECUTE 'REVOKE ALL ON FUNCTION {signature} FROM PUBLIC'; "
        f"EXECUTE 'GRANT EXECUTE ON FUNCTION {signature} TO fp_app'; "
        "END IF; END $$"
    )


def statements() -> list[str]:
    return [
        "REVOKE INSERT, UPDATE, DELETE ON tenant FROM fp_app",
        _revoke_if_exists("audit_event", "fp_app"),
        _revoke_if_exists("ops_alert", "fp_app", "DELETE"),
        *(_revoke_if_exists(table, "fp_app", "INSERT, UPDATE, DELETE") for table in CONFIG_TABLES),
        *(_revoke_if_exists(table, "fp_app") for table in AUTH_TABLES),
        "GRANT SELECT ON ALL TABLES IN SCHEMA public TO fp_readonly",
        "ALTER DEFAULT PRIVILEGES FOR ROLE fp_owner IN SCHEMA public "
        "GRANT SELECT ON TABLES TO fp_readonly",
        *(_revoke_if_exists(table, "fp_readonly") for table in SENSITIVE_TABLES),
        *(_function_grants(name, signature) for name, signature in FUNCTIONS),
    ]


def apply(connection: Any) -> None:
    with connection.cursor() as cursor:
        for statement in statements():
            cursor.execute(statement)
