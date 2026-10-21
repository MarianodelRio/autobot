# ADR-002 — Multitenancy con Row-Level Security

**Estado:** aceptada (revisada el 2026-10-21) · **Relacionado:** `design.md` §0, §7, §13.1, §13.2

## Contexto

Varios negocios comparten la plataforma. Un error de código que muestre datos de un negocio a otro es inaceptable, y operar una base de datos por cliente no es sostenible para una persona.

## Decisión

- **Una base de datos PostgreSQL 18 compartida**; toda tabla con datos de cliente lleva `tenant_id`.
- **RLS forzada** (`ENABLE` + `FORCE`) con la política `tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid`.
- El tenant se fija **solo** con `tenant_tx(tenant_id)`: transacción corta + `SET LOCAL app.tenant_id`, nunca anidada. Sin tenant fijado no se ve ninguna fila.
- Roles: `fp_owner` (migraciones), `fp_app` (`web` y `worker`, sin `BYPASSRLS`), `fp_admin` (solo el servicio `admin`, con `BYPASSRLS`, no expuesto a internet).
- Claves foráneas compuestas `(tenant_id, x_id)`.
- El enrutado de webhooks y la lista de tenants salen del registro en memoria (`tenants/*.yaml`), así que **no hacen falta funciones `SECURITY DEFINER`**.
- Test genérico de aislamiento que recorre todas las tablas con `tenant_id` y bloquea el merge.

## Alternativas consideradas

- **Base de datos o esquema por cliente**: aislamiento fuerte, pero migraciones, conexiones y backups multiplicados.
- **Filtrar solo en el ORM**: más simple, pero un olvido en una consulta expone datos y la BD no lo impediría. Con RLS el coste extra es pequeño (`tenant_tx` y una política por tabla).

## Consecuencias

- El aislamiento no depende de que el código acierte siempre: falla de forma segura.
- Toda tabla nueva debe crear su política (lo vigila el test); las migraciones que tocan RLS o roles requieren aprobación humana.
- Las tablas de Procrastinate no tienen RLS: los trabajos solo llevan ids y los candados no llevan datos personales.

## Cuándo revisarla

- Un cliente exige, por obligación legal o contractual, una base de datos propia.
