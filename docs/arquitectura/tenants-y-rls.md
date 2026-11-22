# Tenants y RLS

Cómo se aíslan los datos de cada negocio (tenant) en una única base de datos PostgreSQL compartida ([ADR-002](adr/ADR-002-multitenancy-rls.md)). Léelo antes de tocar modelos, migraciones o cualquier código que lea o escriba datos de cliente. La checklist práctica para añadir tablas está en [migraciones y RLS](../desarrollo/migraciones-y-rls.md).

## Idea

Toda tabla con datos de cliente lleva `tenant_id` y tiene Row-Level Security (RLS) forzada. La política compara `tenant_id` con la variable de sesión `app.tenant_id`; sin ella, no se ve ninguna fila. Así, un error de código no puede mostrar datos de un negocio a otro: la base de datos lo impide. La tabla `tenant` aplica la misma política sobre su propio `id`.

Las tablas con RLS son `tenant`, `contact`, `conversation`, `inbound_event`, `outbound_message`, `notification` y `metric_event` (lista `RLS_TABLES` en `apps/backend/src/autobot/migrations/0001_squashed_0026_dataset_library.py`). Sus hijos apuntan al padre con una clave foránea compuesta `(tenant_id, x_id)`, de modo que una fila no puede referirse a otro tenant.

## `tenant_tx`

`tenant_tx(tenant_id)` (`apps/backend/src/autobot/tenancy/tx.py`) es la **única** forma de fijar el tenant. Abre una transacción corta en la conexión `default` y ejecuta `set_config('app.tenant_id', ..., true)`, que solo vale dentro de la transacción. Dentro del bloque solo existen las filas de ese tenant; al salir sin error se limpia.

Reglas de uso:

- No se anida: es un bloque `durable`, una transacción, un tenant.
- Es corta. Nunca se hacen llamadas a Meta, Google o Telegram dentro.
- Nunca se salta RLS desde código de aplicación.

Ejemplo real, el diario de efectos (`apps/backend/src/autobot/runtime/effects.py`):

```python
def get(self, key: str) -> dict[str, Any] | None:
    with tenant_tx(self.tenant_id):
        value = self._event().effect_state.get(f"{self.scope}:{key}")
        return copy.deepcopy(value) if isinstance(value, dict) else None
```

La consulta a `InboundEvent` no filtra por tenant: no hace falta, la política ya lo hace.

## Conexiones y roles

`apps/backend/src/config/settings.py` define hasta tres conexiones, con roles distintos creados por `deploy/postgres/init-roles.sh`:

| Alias | Rol | Uso |
|---|---|---|
| `default` | `fp_app` | La aplicación y los workers. Sujeto a RLS. No lee ni escribe config, auth ni auditoría salvo lo permitido (ver abajo). |
| `owner` | `fp_owner` | `BYPASSRLS`. Migraciones, comandos de operación, `tenancy.store` y los servicios del panel. |
| `readonly` | `fp_readonly` | La consola SQL del panel. Solo lectura. |

`owner` solo existe si `DB_OWNER_URL` está definida: el worker la deja vacía y no puede usarlo. `readonly` depende igual de `DB_READONLY_URL`.

Solo pueden llamar a `.using("owner")` las migraciones, los comandos de `manage.py`, `autobot/tenancy/store/`, los servicios del panel (`autobot/panel/services/`) y el código de operación explícito (por ejemplo, `autobot/ops/audit.py` o los exports y borrados de `autobot/runtime/privacy.py`). Siempre con el `.using("owner")` explícito, nunca como conexión por defecto. El router `AuthDatabaseRouter` (`apps/backend/src/autobot/db/router.py`) envía a `owner` los modelos de `auth`, `contenttypes`, `sessions`, `otp_totp` y `django_otp`; el resto va a `default`.

## Políticas

Cada tabla con RLS lleva dos políticas:

- `tenant_isolation`: `USING` y `WITH CHECK` con `tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid`. Es la que aísla.
- `readonly_all`: `FOR SELECT TO fp_readonly`, que deja ver todas las filas solo si `app.readonly_all = 'on'`. La consola SQL (`autobot/panel/services/query.py`) fija `app.tenant_id` si el operador elige un tenant, o `app.readonly_all` si quiere ver todos, siempre en una transacción de solo lectura con límite de tiempo. Elegir tenant es una comodidad, no una barrera: el SQL puede activar `app.readonly_all` con `set_config`. Lo que protege es el rol `fp_readonly`, `SENSITIVE_TABLES` y el túnel con TOTP (ver [Panel](panel.md)).

## Permisos: `db/grants.py`

Los permisos de base de datos se declaran en `apps/backend/src/autobot/db/grants.py`, nunca solo en una migración. `statements()` devuelve SQL idempotente y `apply(connection)` lo ejecuta en una transacción. Se reaplica con el comando `apply_grants` tras cada despliegue y cada restauración (`pg_restore --no-acl` borra los permisos). Define:

- `SENSITIVE_TABLES`: tablas que `fp_readonly` no puede leer (`auth_user`, `django_session`, `tenant_secret`, `owner_link`, `demo_event`, `owner_event`, `demo_session`, `demo_invite`, `audit_event` por el SQL con literales que guarda, `tenant_document_version` por los teléfonos de los testers, etc.). Toda tabla nueva sensible se añade aquí.
- `CONFIG_TABLES`: `fp_app` solo lee; escribe `fp_owner`.
- `AUTH_TABLES`: `fp_app` no tiene ningún acceso.
- Revocaciones concretas: `fp_app` no puede escribir `tenant`, ni tocar `audit_event`, ni borrar `ops_alert`.

## Tablas de plataforma sin RLS

Llevan `tenant_id` pero no RLS por diseño, porque son configuración u operación de la plataforma, no datos de cliente ([ADR-009](adr/ADR-009-config-en-bd.md), [ADR-006](adr/ADR-006-bot-de-demo.md), [ADR-007](adr/ADR-007-bot-de-duenos.md)):

- `tenant_document_version`, `tenant_dataset_version`, `tenant_secret` (`autobot/tenancy/models.py`): config versionada y secretos. `fp_app` no puede escribirlas.
- `audit_event`, `ops_alert` (`autobot/ops/models.py`): operación y auditoría.
- `demo_session`, `owner_link` (`autobot/runtime/models.py`): se consultan antes de saber el tenant (el selector de demo y el bot de avisos buscan el tenant *desde* el chat).

También sin RLS y sin `tenant_id` propio: `config_revision` y `dataset_library_version` (`tenancy/models.py`) y las tablas de demo y de dueños (`demo_event`, `owner_event`, `demo_invite`, `demo_access_grant`, `platform_cache`). El test `apps/backend/tests/isolation/test_isolation.py` comprueba que ningún modelo con `tenant_id` queda fuera de RLS salvo los de esta lista.

## Dónde está el código

- `apps/backend/src/autobot/tenancy/tx.py` (`tenant_tx`).
- `apps/backend/src/autobot/db/router.py`, `apps/backend/src/autobot/db/grants.py`.
- `apps/backend/src/autobot/migrations/0001_squashed_0026_dataset_library.py` (función `rls`).
- `apps/backend/tests/isolation/test_isolation.py`.

## Relacionado

- [Migraciones y RLS](../desarrollo/migraciones-y-rls.md), [config y registro](config-y-registro.md), [seguridad y secretos](seguridad-y-secretos.md).
