#!/usr/bin/env bash
# Database roles (design.md §12.2): fp_owner owns the tables and bypasses RLS (migrations,
# Admin, cross-tenant operation commands); fp_app is what web and worker use, with only
# SELECT/INSERT/UPDATE/DELETE and no DDL.
#
# Runs as the PostgreSQL superuser. The postgres image runs it on the first start of an
# empty volume (/docker-entrypoint-initdb.d); it is idempotent, so it can also be run by
# hand or in CI with PGHOST/PGPASSWORD set. POSTGRES_TEST_DB (local and CI only) creates
# the test database with the same setup. Needs psql 15+ (\getenv); the postgres:18 image
# and the ubuntu-24.04 CI runner have it.
set -euo pipefail

: "${FP_OWNER_PASSWORD:?FP_OWNER_PASSWORD is required}"
: "${FP_APP_PASSWORD:?FP_APP_PASSWORD is required}"
db="${POSTGRES_DB:-flowpilot}"

psql_su() {
  psql -v ON_ERROR_STOP=1 --no-psqlrc --quiet --username "${POSTGRES_USER:-postgres}" "$@"
}

# Passwords are read from the environment inside psql (\getenv), so they never appear in
# the process list. Do not enable log_statement for DDL: it would log them.
export FP_OWNER_PASSWORD FP_APP_PASSWORD
psql_su --dbname postgres <<'SQL'
\getenv owner_pw FP_OWNER_PASSWORD
\getenv app_pw FP_APP_PASSWORD
SELECT 'CREATE ROLE fp_owner' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'fp_owner')\gexec
SELECT 'CREATE ROLE fp_app' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'fp_app')\gexec
ALTER ROLE fp_owner WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION BYPASSRLS
  PASSWORD :'owner_pw';
ALTER ROLE fp_app WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
  PASSWORD :'app_pw';
-- The application roles only reach their own databases.
REVOKE CONNECT, TEMPORARY ON DATABASE postgres, template1 FROM PUBLIC;
SQL

for name in "$db" ${POSTGRES_TEST_DB:+"$POSTGRES_TEST_DB"}; do
  psql_su --dbname postgres -v name="$name" <<'SQL'
SELECT format('CREATE DATABASE %I OWNER fp_owner', :'name')
  WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'name')\gexec
SELECT format('ALTER DATABASE %I OWNER TO fp_owner', :'name')\gexec
-- No CONNECT or TEMP for everyone else; fp_app only connects.
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', :'name')\gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO fp_app', :'name')\gexec
SQL
  psql_su --dbname "$name" <<'SQL'
ALTER SCHEMA public OWNER TO fp_owner;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO fp_app;
-- Tables and sequences that fp_owner creates (Django's and Procrastinate's migrations).
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO fp_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO fp_app;
ALTER DEFAULT PRIVILEGES FOR ROLE fp_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO fp_app;
ALTER DEFAULT PRIVILEGES FOR ROLE fp_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO fp_app;
SQL
done
