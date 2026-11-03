# ADR-002 — Multitenancy con Row-Level Security

**Estado:** aceptada

## Contexto

Varios negocios comparten la plataforma. Un error de código que muestre datos de un negocio a otro es inaceptable, y operar una base de datos por cliente no es sostenible para una persona.

## Decisión

- **Una base de datos PostgreSQL 18 compartida**; toda tabla con datos de cliente lleva `tenant_id`.
- **RLS forzada** (`ENABLE` + `FORCE`) con la política `tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid`.
- El tenant se fija **solo** con `tenant_tx(tenant_id)`: transacción corta + `SET LOCAL app.tenant_id`, nunca anidada. Sin tenant fijado no se ve ninguna fila.
- Dos roles: `fp_app` (`web` y `worker`, sin `BYPASSRLS`) y `fp_owner` (dueño de las tablas, con `BYPASSRLS`: migraciones, Django Admin y comandos de operación entre tenants). El Admin no está expuesto a internet (túnel SSH).
- Claves foráneas compuestas `(tenant_id, x_id)`.
- El enrutado de webhooks y la lista de tenants salen del registro en memoria (`tenants/*.yaml`), así que **no hacen falta funciones `SECURITY DEFINER`**.
- Test genérico de aislamiento que recorre todas las tablas con `tenant_id` y deja CI en rojo si alguna tabla no tiene política.

Modificada por [ADR-008](ADR-008-panel.md) y [ADR-009](ADR-009-config-en-bd.md): el Django Admin desaparece, sustituido por el panel, que accede a `fp_owner` de forma explícita (`.using("owner")`); aparece un tercer rol, `fp_readonly` (`NOBYPASSRLS`, solo `SELECT`), para la consola SQL del panel, con una política `readonly_all` adicional en toda tabla con RLS; y la config y los datasets de los negocios pasan a vivir en cuatro tablas con `tenant_id` pero sin RLS (excepción explícita del test de aislamiento), porque cada proceso necesita leerlas enteras.

## Alternativas consideradas

- **Base de datos o esquema por cliente**: aislamiento fuerte, pero migraciones, conexiones y backups multiplicados.
- **Filtrar solo en el ORM**: más simple, pero un olvido en una consulta expone datos y la BD no lo impediría. Con RLS el coste extra es pequeño (`tenant_tx`, una política por tabla y dos roles).
- **Un tercer rol solo para el Admin en un contenedor aparte**: más estricto, pero una pieza más que operar sin beneficio real a esta escala.

## Consecuencias

- El aislamiento no depende de que el código acierte siempre: falla de forma segura.
- Toda tabla nueva debe crear su política (lo vigila el test); las migraciones que tocan RLS o roles requieren aprobación humana.
- Las tablas de Procrastinate no tienen RLS: los trabajos solo llevan ids y los candados no llevan datos personales.

## Cuándo revisarla

- Un cliente exige, por obligación legal o contractual, una base de datos propia.
