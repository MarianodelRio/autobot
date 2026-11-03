# CLAUDE.md — Autobot

Plataforma multi-negocio que atiende a los clientes de pequeños negocios por un canal por negocio (WhatsApp o Telegram), con un bot de demo, por WhatsApp y Telegram, para enseñar los packs. Packs iniciales: `salon` (peluquería, reservas sobre Google Calendar) y `bus` (horarios de autobús). Este fichero resume las reglas para trabajar en el repo.

**Estado:** plataforma y dos packs implementados y probados con simulaciones; nada probado aún contra servicios reales. Los pasos manuales pendientes están en [`docs/puesta-en-marcha.md`](docs/puesta-en-marcha.md).

## Idioma

- Responde siempre en español: resúmenes, preguntas, planes y revisiones.
- Documentos (`README`, `docs/`) en español. Código, identificadores, comandos y mensajes de commit en inglés.
- Excepción (decidida por la persona, 2026-10-22): el código heredado de `packs/bus/` conserva sus identificadores en español (`Localidad`, `Viaje`, `SEL_ORIGEN`…); lo nuevo de ese pack va en inglés.

## Forma de trabajo

- Cada cambio va en un commit con su código, sus tests y la documentación afectada (`README`, `docs/`).
- Si algo espera una acción manual, se deja anotado y se sigue con otra cosa independiente. Nunca se inventan credenciales ni ids, ni se simulan aprobaciones o verificaciones reales.
- Se trabaja directamente sobre `main`; sin ramas ni PR salvo que la persona lo pida. CI debe quedar en verde.
- Commit o push solo cuando la persona lo pida.
- Una decisión de arquitectura nueva o que cambie una existente se registra como ADR en `docs/adr/` (o se pregunta antes).

## Arquitectura

- Monolito modular Django 5.2 + PostgreSQL 18 + Procrastinate, en una VPS con Docker Compose (`caddy`, `web`, `worker`, `db`, `panel`, `victorialogs`).
- `core/` e `integrations/` no importan Django; `packs/*` solo importan `core` (nunca Django, `integrations` ni otro pack). Lo comprueba `import-linter`.
- Lógica de cada negocio en `packs/<nombre>/`; la plataforma no sabe qué es una cita ni un autobús, y los packs no saben qué canal se usa. Las diferencias entre WhatsApp y Telegram viven solo en sus adaptadores, y el selector del bot de demo solo en `channels/demo/`. A `core/` solo sube lo que usan los dos packs y las utilidades genéricas sin lógica de negocio.
- Config y datasets de cada negocio en PostgreSQL, versionados (ADR-009); nada en git ni en la imagen. Importación/exportación con `tenant_config` y `tenant_dataset`; `tenants/` y `datos/` están ignorados. Secretos de canal cifrados en la base de datos; secretos de la plataforma en `.env` del servidor. Nunca en git.
- Cada pack nuevo incluye su plantilla en `src/packs/<pack>/template/` (de ahí sale su negocio de demo) y su escenario de conversación.
- Panel interno (`panel/`) en TypeScript, Biome y Vitest; sustituye al Django Admin. Su API (`/api/panel/`) solo es accesible por túnel SSH (ADR-008); el frontend nunca es la única barrera de validación ni de permisos.

## Reglas obligatorias

- Todo dato de cliente lleva `tenant_id` y RLS; el tenant se fija solo con `tenant_tx`. Nunca se salta RLS en código de aplicación (el rol `fp_owner`, con `BYPASSRLS`, solo lo usan migraciones, comandos de operación, `tenancy.store` y los servicios del panel, siempre con `.using("owner")` explícito).
- Toda tabla nueva con RLS lleva las dos políticas: `tenant_isolation` y `readonly_all` (para la consola SQL del panel, rol `fp_readonly`). Toda tabla nueva sensible se añade a `SENSITIVE_TABLES` en `db_grants.py`. Los permisos de base de datos se declaran en `db_grants.py`, nunca solo en una migración; `apply_grants` los reaplica tras cada despliegue y restauración.
- `tenant_document_version`, `tenant_dataset_version`, `tenant_secret` y `audit_event` llevan `tenant_id` sin RLS por diseño (ADR-009): son configuración u operación de la plataforma, no datos de cliente.
- Todo efecto externo es idempotente; no se reintenta a ciegas un envío ambiguo (`unknown`).
- Ninguna transacción abierta durante llamadas a Meta, Google o Telegram.
- Los trabajos de la cola reciben solo ids; nunca teléfonos, ids de usuario ni datos personales en argumentos, candados o logs.
- Credenciales: nunca en claro, nunca en git, nunca en logs.
- El bot nunca adivina en silencio: o hay una respuesta única, o pregunta.
- Toda respuesta respeta los límites comunes de los dos canales (botones ≤ 3, listas ≤ 10 filas, textos ≤ 4.096, ids ≤ 64 bytes); los escenarios lo comprueban.
- Los escenarios de conversación son obligatorios para cada pack y cada cambio de su flujo.
- Requieren aprobación humana explícita: migraciones que tocan RLS, roles o borrados; cambios en cifrado, secretos o firma de webhooks; cambios en la infraestructura del servidor; cualquier acción sobre datos de producción; activar el canal real de un negocio.
- Ningún agente despliega a producción ni ejecuta comandos contra el servidor de producción.

## Referencias

- Decisiones: `docs/adr/`. Operación: `docs/runbooks/`. Configuración de cada pack: `docs/packs/`. Comandos: `docs/comandos.md`.
