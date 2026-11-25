"""Desired PostgreSQL permissions (ADR-009), declared as idempotent SQL and reapplied
on every migration that creates tables or changes permissions, on every deploy, and
after every restore (pg_restore --no-acl drops them). A single source of truth instead
of relying on a migration staying in the restored dump."""

from typing import Any

from django.db import transaction

SENSITIVE_TABLES: tuple[str, ...] = (
    "auth_user",
    "django_session",
    "otp_totp_totpdevice",
    "tenant_secret",
    "owner_link",
    "platform_cache",
    "demo_invite",
    # Raw inbound payloads and external ids (phones, BSUIDs, Telegram ids) of demo and
    # owner chats: personal data of people who are not tenants' staff. The SQL console
    # (fp_readonly) must not read them; the operator checks them with the panel's own
    # views or by terminal.
    "demo_event",
    "owner_event",
    "demo_session",
    "demo_access_grant",
    # `details` and `summary` carry the SQL console's literals (phones, names typed into
    # a WHERE) and contact ids: the audit log is read through the panel's own view
    # (owner connection), never through the console.
    "audit_event",
    # The full tenant document: it lists the testers' phone numbers and ids. The panel
    # reads it through `tenancy.store` / its own services (owner), not through fp_readonly.
    "tenant_document_version",
    # The suppression ledger (ADR-019): ids and keyed hashes only, but a record of whose
    # data was erased; not for the SQL console.
    "privacy_suppression",
)
# Config tables (ADR-009): fp_app keeps SELECT, but only fp_owner (the panel, the
# commands) writes.
CONFIG_TABLES: tuple[str, ...] = (
    "tenant_document_version",
    "tenant_dataset_version",
    "tenant_secret",
    "config_revision",
)
# `config_follower` (ADR-030) is deliberately NOT in CONFIG_TABLES: every booted process
# writes its own row as fp_app (the base grant above gives SELECT, INSERT, UPDATE and DELETE;
# DELETE also lets `ops_check` purge stale rows). fp_readonly reads it through the default
# SELECT grant: it holds hostnames and pids, nothing sensitive.
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
        # The base: init-roles.sh no longer grants table permissions (it only manages
        # roles, CONNECT and schema USAGE), so this is the single place fp_app gets
        # them, including Procrastinate's tables and sequences. The REVOKEs below narrow it.
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO fp_app",
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO fp_app",
        "REVOKE INSERT, UPDATE, DELETE ON tenant FROM fp_app",
        _revoke_if_exists("audit_event", "fp_app"),
        # Only the operator commands (fp_owner) write or read the suppression ledger.
        _revoke_if_exists("privacy_suppression", "fp_app"),
        _revoke_if_exists("ops_alert", "fp_app", "DELETE"),
        # ADR-013: the registry never reads this table (only `tenancy.store`, as
        # `fp_owner`, copies from it into `tenant_dataset_version`), unlike the
        # CONFIG_TABLES below that `fp_app` reloads at startup.
        _revoke_if_exists("dataset_library_version", "fp_app"),
        *(_revoke_if_exists(table, "fp_app", "INSERT, UPDATE, DELETE") for table in CONFIG_TABLES),
        *(_revoke_if_exists(table, "fp_app") for table in AUTH_TABLES),
        "GRANT SELECT ON ALL TABLES IN SCHEMA public TO fp_readonly",
        "ALTER DEFAULT PRIVILEGES FOR ROLE fp_owner IN SCHEMA public "
        "GRANT SELECT ON TABLES TO fp_readonly",
        *(_revoke_if_exists(table, "fp_readonly") for table in SENSITIVE_TABLES),
        *(_function_grants(name, signature) for name, signature in FUNCTIONS),
    ]


def apply(connection: Any) -> None:
    # One transaction, so the broad base grant never shows without the REVOKEs after it.
    with transaction.atomic(using=connection.alias), connection.cursor() as cursor:
        for statement in statements():
            cursor.execute(statement)
