# CLAUDE.md — Autobot

Plataforma multi-negocio que atiende a los clientes de pequeños negocios por un canal por negocio (WhatsApp o Telegram), con un bot de demo, por WhatsApp y Telegram, para enseñar los packs. Packs iniciales: `salon` (peluquería, reservas sobre Google Calendar) y `bus` (horarios de autobús). Este fichero resume las reglas para trabajar en el repo.

**Estado:** la plataforma está probada en local contra servicios reales (demo por Telegram y WhatsApp, bot de avisos, panel, Google Calendar); nada está desplegado todavía en producción. Los pasos para ponerla en marcha están en [`docs/procedimientos/servidor.md`](docs/procedimientos/servidor.md).

## Idioma

- Responde siempre en español: resúmenes, preguntas, planes y revisiones.
- Documentos (`README`, `docs/`) en español. Código, identificadores, comandos y mensajes de commit en inglés.
- Excepción (decidida por la persona, 2026-10-22): el código heredado de `packs/bus/` conserva sus identificadores en español (`Localidad`, `Viaje`, `SEL_ORIGEN`…); lo nuevo de ese pack va en inglés.

## Forma de trabajo

- Cada cambio va en un commit con su código, sus tests y la documentación afectada (`README`, `docs/`).
- Si algo espera una acción manual, se deja anotado y se sigue con otra cosa independiente. Nunca se inventan credenciales ni ids, ni se simulan aprobaciones o verificaciones reales.
- Se trabaja directamente sobre `main`; sin ramas ni PR salvo que la persona lo pida. CI debe quedar en verde.
- Commit o push solo cuando la persona lo pida.
- La documentación es un sitio Zensical (`mkdocs.yml`): `make docs` lo sirve en local y `make docs-check` lo construye en modo estricto (lo ejecuta CI). Una página nueva se añade al `nav` de `mkdocs.yml`; nada de enlaces Markdown a ficheros fuera de `docs/` (los ficheros de código se citan en backticks).
- Una decisión de arquitectura nueva o que cambie una existente se registra como ADR en `docs/arquitectura/adr/` (o se pregunta antes).

## Arquitectura

Visión completa en [`docs/arquitectura/vision-general.md`](docs/arquitectura/vision-general.md); aquí solo las reglas.

- Monolito modular Django 5.2 + PostgreSQL 18 + Procrastinate, en una VPS con Docker Compose (`caddy`, `web`, `web-panel`, `worker-inbound`, `worker-calendar`, `worker-periodic`, `worker-outbound`, `db`, `panel`, `victorialogs`). Dos apps autocontenidas en `apps/` (`backend/`, `panel/`); el despliegue vive en `deploy/` (ADR-010). Los ficheros de ejecución, locales y del servidor, van en `var/` (ignorado por git). Mapa del código: [`docs/arquitectura/mapa-del-codigo.md`](docs/arquitectura/mapa-del-codigo.md).
- `core/` e `integrations/` no importan Django; `packs/*` solo importan `core` (nunca Django, `integrations` ni otro pack). Lo comprueba `import-linter`.
- Lógica de cada negocio en `packs/<nombre>/`; la plataforma no sabe qué es una cita ni un autobús, y los packs no saben qué canal se usa. Las diferencias entre WhatsApp y Telegram viven solo en sus adaptadores, y el selector del bot de demo solo en `channels/demo/`. A `core/` solo sube lo que usan los dos packs y las utilidades genéricas sin lógica de negocio.
- Config y datasets de cada negocio en PostgreSQL, versionados (ADR-009); nada en git ni en la imagen. Los datasets de un pack se suben por terminal a una biblioteca independiente de cualquier cliente y el cliente se queda con una copia, nunca una referencia viva (ADR-013); `var/tenants/` y `var/datos/` están ignorados. Secretos de canal cifrados en la base de datos; secretos de la plataforma en `.env` del servidor. Nunca en git.
- Cada pack nuevo incluye su plantilla en `apps/backend/src/packs/<pack>/template/` (de ahí sale su negocio de demo) y su escenario de conversación en `apps/backend/tests/packs/<pack>/`. Guía: [`docs/desarrollo/anadir-un-pack.md`](docs/desarrollo/anadir-un-pack.md).
- El panel (`apps/panel/`, TypeScript, Biome y Vitest) solo es accesible por túnel SSH (ADR-008); el frontend nunca es la única barrera de validación ni de permisos.

## Reglas obligatorias

- Todo dato de cliente lleva `tenant_id` y RLS; el tenant se fija solo con `tenant_tx`. Nunca se salta RLS en código de aplicación (el rol `fp_owner`, con `BYPASSRLS`, solo lo usan migraciones, comandos de operación, `tenancy.store` y los servicios del panel, siempre con `.using("owner")` explícito).
- Toda tabla nueva con RLS lleva las dos políticas: `tenant_isolation` y `readonly_all` (para la consola SQL del panel, rol `fp_readonly`). Toda tabla nueva sensible se añade a `SENSITIVE_TABLES` en `autobot/db/grants.py`. Los permisos de base de datos se declaran en `autobot/db/grants.py`, nunca solo en una migración; `apply_grants` los reaplica tras cada despliegue y restauración.
- `tenant_document_version`, `tenant_dataset_version`, `tenant_secret`, `audit_event`, `ops_alert`, `demo_session` y `owner_link` llevan `tenant_id` sin RLS por diseño (ADR-009, ADR-006, ADR-007): son configuración u operación de la plataforma, no datos de cliente.
- Todo efecto externo es idempotente. Un envío ambiguo (`unknown`) no se reintenta a ciegas: primero se concilia con el estado del proveedor y, si pasado el plazo no hay evidencia, solo se reenvía una vez y solo si su clase declara que un duplicado es inocuo; si no, queda para un humano (ADR-026).
- Ninguna transacción abierta durante llamadas a Meta, Google o Telegram.
- Los trabajos de la cola reciben solo ids; nunca teléfonos, ids de usuario ni datos personales en argumentos, candados o logs.
- Credenciales: nunca en claro, nunca en git, nunca en logs.
- El bot nunca adivina en silencio: o hay una respuesta única, o pregunta.
- Toda respuesta respeta los límites comunes de los dos canales (botones ≤ 3, listas ≤ 10 filas, textos ≤ 4.096, ids ≤ 64 bytes); los escenarios lo comprueban.
- Los escenarios de conversación son obligatorios para cada pack y cada cambio de su flujo.
- Requieren aprobación humana explícita: migraciones que tocan RLS, roles o borrados; cambios en cifrado, secretos o firma de webhooks; cambios en la infraestructura del servidor; cualquier acción sobre datos de producción; activar el canal real de un negocio.
- Ningún agente despliega a producción ni ejecuta comandos contra el servidor de producción.

## Referencias

Índice del sitio: [`docs/README.md`](docs/README.md).

- Decisiones: `docs/arquitectura/adr/` (índice en `README.md`). Conceptos: `docs/arquitectura/`.
- Desarrollo: `docs/desarrollo/` (entorno local, tests, añadir un pack, migraciones y RLS, documentación).
- Operación: `docs/procedimientos/`; incidencias por síntoma: `docs/incidencias/`.
- Cumplimiento y RGPD: `docs/cumplimiento/` (roles, registro de actividades, contrato de encargado, brechas, checklist de lanzamiento).
- Referencia: `docs/referencia/` (comandos, variables de entorno, packs, alertas, glosario).
