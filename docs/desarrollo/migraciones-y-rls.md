# Migraciones y RLS

Lista de comprobación práctica para crear una tabla nueva con datos de cliente sin romper el aislamiento entre negocios. Léela antes de tocar un modelo o escribir una migración. El concepto (qué es RLS, qué roles hay y por qué) se explica en [Tenants y RLS](../arquitectura/tenants-y-rls.md); aquí solo está el procedimiento.

!!! warning "Requiere aprobación humana"
    Las migraciones que tocan RLS, roles o borrados necesitan aprobación humana explícita (`CLAUDE.md`). Una tabla nueva con políticas RLS es una de ellas: prepara el cambio, anota que espera aprobación y no lo des por cerrado sin ella.

## Estado actual de las migraciones

Hay una sola migración, `apps/backend/src/autobot/migrations/0001_squashed_0026_dataset_library.py`, que sustituye a las 26 de los primeros meses (aún no hay BD de producción). Lo que un modelo no puede expresar vive ahí, en SQL:

- Las claves foráneas compuestas `(tenant_id, x_id)` (`composite_fk`, lista `COMPOSITE_FKS`).
- Las políticas RLS de cada tabla (`rls(table, column)`, lista `RLS_TABLES`).
- La función `purge_platform_history`, la fila de `config_revision` y, al final, `db_grants.apply`.

Una tabla nueva va en una migración **nueva** (`0002_...`) que sigue el mismo patrón. Las funciones de ayuda de `0001` no se pueden importar (el nombre empieza por un dígito): copia su SQL a la migración nueva.

## Checklist: tabla nueva con datos de cliente

### 1. El modelo lleva `tenant_id`

Hereda de `TenantScoped` (`apps/backend/src/autobot/runtime/models.py`), que aporta `id` (UUIDv7) y la clave foránea `tenant`. Ponle:

- `Meta.db_table` explícito.
- Una restricción única que empiece por `tenant` (`UniqueConstraint(fields=["tenant", ...])`). Sirve de índice y evita cruces.
- Si otra tabla del cliente apunta a ella, una restricción `UniqueConstraint(fields=["tenant", "id"])` como `contact_tenant_id_uniq`: es el destino de la clave compuesta.
- Un índice `(tenant, fecha)` si la tabla entra en retención.

Exporta el modelo en `apps/backend/src/autobot/models.py`. Los datos personales no van a logs ni a `__str__`.

### 2. Referencias a otras filas del cliente

Si tiene una clave foránea a otra tabla con `tenant_id`, usa `ForeignKey(..., db_constraint=False)` en el modelo y crea la restricción compuesta en SQL, para que una fila no pueda apuntar a otra de otro negocio:

```python
migrations.RunSQL(
    sql="ALTER TABLE mi_tabla ADD CONSTRAINT mi_tabla_contact_fk"
        " FOREIGN KEY (tenant_id, contact_id) REFERENCES contact (tenant_id, id) ON DELETE CASCADE",
    reverse_sql="ALTER TABLE mi_tabla DROP CONSTRAINT mi_tabla_contact_fk",
)
```

### 3. La migración activa RLS con las dos políticas

Genera el esquema con `uv run python manage.py makemigrations autobot` (desde `apps/backend`, con `DJANGO_SETTINGS_MODULE=config.settings_dev`) y añade a mano, tras la creación de la tabla, el SQL de `rls()` de `0001`:

```python
TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

migrations.RunSQL(
    sql=[
        "ALTER TABLE mi_tabla ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE mi_tabla FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY tenant_isolation ON mi_tabla USING (tenant_id = {TENANT}) WITH CHECK (tenant_id = {TENANT})",
        "CREATE POLICY readonly_all ON mi_tabla FOR SELECT TO fp_readonly"
        " USING (current_setting('app.readonly_all', true) = 'on')",
    ],
    reverse_sql=[
        "DROP POLICY readonly_all ON mi_tabla",
        "DROP POLICY tenant_isolation ON mi_tabla",
        "ALTER TABLE mi_tabla NO FORCE ROW LEVEL SECURITY",
        "ALTER TABLE mi_tabla DISABLE ROW LEVEL SECURITY",
    ],
)
```

- `FORCE` hace que RLS valga también para el propietario de la tabla.
- Las dos políticas son obligatorias: `tenant_isolation` (todas las operaciones) y `readonly_all` (solo `SELECT` para `fp_readonly`, que la consola SQL del panel activa con `app.readonly_all`). Ninguna política más.
- La condición exacta importa: el test compara el texto de cada política.
- Termina con `migrations.RunPython(apply_grants, migrations.RunPython.noop)`, donde `apply_grants` llama a `autobot.db.grants.apply(schema_editor.connection)`, como `0001`.

### 4. Permisos en `autobot/db/grants.py`

Los permisos se declaran en `apps/backend/src/autobot/db/grants.py`, **nunca solo en una migración**: `apply_grants` los reaplica tras cada despliegue y cada restauración (`pg_restore --no-acl` los pierde).

- La base ya da a `fp_app` `SELECT, INSERT, UPDATE, DELETE` sobre todas las tablas, y a `fp_readonly` solo `SELECT`. Una tabla de datos de cliente normal no necesita nada más.
- Si la tabla guarda datos personales en bruto (teléfonos, ids de usuario, payloads), añádela a **`SENSITIVE_TABLES`**: así `fp_readonly` no puede leerla ni con `readonly_all`. En caso de duda, añádela.
- Si solo debe escribirla el panel o un comando, y la web solo leerla, mira `CONFIG_TABLES` (revoca escritura a `fp_app`). Si `fp_app` no debe tocarla nada, `AUTH_TABLES`. Elige de forma explícita; un revoke se añade al listado, no a la migración.

### 5. Tablas sin RLS por diseño

Solo hay unas pocas y están documentadas: `tenant_document_version`, `tenant_dataset_version`, `tenant_secret`, `audit_event`, `ops_alert`, `demo_session` y `owner_link` llevan `tenant_id` sin RLS (ADR-009, ADR-006, ADR-007), porque son configuración u operación de la plataforma. Una tabla nueva **no** entra en esa lista por comodidad. Si crees que debe, es una decisión de arquitectura: ADR nuevo o pregunta antes. Los datos de cliente siempre llevan RLS.

### 6. El código accede con `tenant_tx`

El código de aplicación lee y escribe esa tabla dentro de `tenant_tx(tenant_id)` (`apps/backend/src/autobot/tenancy/tx.py`), que abre una transacción corta con `app.tenant_id` fijado. No se puede anidar y no se mantiene abierta durante llamadas a Meta, Google o Telegram. Nunca se salta RLS con `fp_owner` en código de aplicación: ese rol solo lo usan las migraciones, los comandos de operación, `tenancy.store` y los servicios del panel, con `.using("owner")` explícito.

### 7. Tests

Todos estos se ejecutan en `make check` y necesitan la BD local:

- **`tests/isolation/test_isolation.py`:** añade una fábrica del modelo (`_mi_tabla`) al diccionario `FACTORIES`. El test genérico recorre todos los modelos con `tenant` y falla si falta la fábrica o la política (`test_every_tenant_model_has_a_factory_or_is_a_platform_table`, `test_every_tenant_model_has_its_policy`). `test_every_table_with_tenant_id_has_its_policy` mira además las tablas de la BD, aunque ningún modelo las declare. Con tu fábrica se prueba solo, para dos negocios A y B, que A no lee, modifica, borra ni inserta filas de B, que no puede apuntar a ellas y que sin negocio no se ve nada.
- **`tests/platform/ops/test_db_roles.py`:** recorre `SENSITIVE_TABLES` y comprueba que `fp_readonly` no puede leerlas.
- **Migraciones:** CI ejecuta `makemigrations --check --dry-run` (el modelo y la migración coinciden) y `lintmigrations` (`django-migration-linter`, rechaza operaciones peligrosas).
- **Tus propios tests** de la lógica, con `tenant_tx` y marca `django_db(transaction=True, databases=["default", "owner"])`.

## Lista rápida

- [ ] Modelo con `TenantScoped`, `db_table`, restricción única con `tenant`.
- [ ] Clave compuesta si apunta a otra tabla del cliente.
- [ ] Migración con `ENABLE` y `FORCE`, `tenant_isolation`, `readonly_all` y `apply_grants`.
- [ ] `SENSITIVE_TABLES` si guarda datos personales; resto de permisos en `grants.py`.
- [ ] Fábrica en `tests/isolation/test_isolation.py`.
- [ ] Acceso desde código solo con `tenant_tx`.
- [ ] Aprobación humana anotada.

## Dónde está el código

- `apps/backend/src/autobot/migrations/0001_squashed_0026_dataset_library.py`: `rls`, `composite_fk`, `RLS_TABLES`.
- `apps/backend/src/autobot/db/grants.py`: `SENSITIVE_TABLES`, `CONFIG_TABLES`, `AUTH_TABLES`, `apply`.
- `apps/backend/src/autobot/runtime/models.py`: `TenantScoped` y los modelos de datos de cliente.
- `apps/backend/src/autobot/tenancy/tx.py`: `tenant_tx`.
- `apps/backend/tests/isolation/test_isolation.py` y `tests/platform/ops/test_db_roles.py`.
- `deploy/postgres/init-roles.sh`: creación de los roles.

## Relacionado

- [Tenants y RLS](../arquitectura/tenants-y-rls.md) y [ADR-002](../arquitectura/adr/ADR-002-multitenancy-rls.md).
- [Seguridad y secretos](../arquitectura/seguridad-y-secretos.md).
- [Tests](tests.md) y [Panel](panel.md).
