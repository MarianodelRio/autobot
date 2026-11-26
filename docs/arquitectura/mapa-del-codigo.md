# Mapa del código

Una línea por carpeta o módulo relevante, para saber dónde buscar. Las capas y sus reglas de import están en la [visión general](vision-general.md); aquí solo se localiza el código. Las rutas son desde la raíz del repo.

## Backend: `apps/backend/`

Contiene `pyproject.toml`, `uv.lock`, `Dockerfile`, `manage.py`, el código en `src/` y los tests en `tests/`.

### `apps/backend/src/core/`

Contratos y utilidades sin Django ni lógica de negocio.

- `pack.py`: el contrato `Pack` que implementa cada pack.
- `messages.py`: lo que un pack recibe (`IncomingMessage`).
- `replies.py`: las respuestas comunes a todos los canales (`Text`, `Buttons`, `List`).
- `ui.py`: constructores de respuestas que respetan los límites comunes.
- `limits.py`: límites comunes de los dos canales y el plan de envío.
- `actions.py`, `proactive.py`: lo que un pack pide además de responder; mensajes proactivos.
- `effects.py`, `idem.py`: diario de autorizaciones de efectos externos y claves de idempotencia.
- `conversation.py`, `serialization.py`: reglas de conversación compartidas con el arnés de tests; (de)serialización de respuestas.
- `clock.py`, `dates.py`, `hours.py`, `phone.py`, `text.py`, `errors.py`: utilidades genéricas (reloj, fechas, horarios, teléfonos, texto, errores).
- `testing/`: arnés de conversación y fakes (`harness.py`, `clock.py`, `effects.py`) para los escenarios de los packs.

### `apps/backend/src/integrations/`

- `google_calendar/`: puerto hacia Google Calendar (`client.py`).

### `apps/backend/src/packs/`

- `registry.py`: único punto por el que `autobot` llama a los packs.
- `salon/`: pack de peluquería (`pack.py`, `conversation.py`, `booking.py`, `slots.py`, `sweep.py`, `config.py`, `template/`…).
- `bus/`: pack de horarios de autobús, con identificadores en español heredados (`pack.py`, `conversation.py`, `matcher.py`, `loader.py`, `formato/`, `template/`…).

### `apps/backend/src/config/`

- `settings.py`, `settings_dev.py`: settings de Django (conexiones `default`, `owner`, `readonly`, Procrastinate, sesión).
- `urls.py`: rutas de webhooks, `/health` y `/api/panel/`. `wsgi.py`: entrada WSGI.

### `apps/backend/src/tools/`

Scripts de operación: `bus/` (herramientas de horarios y biblioteca de datasets), `ops/` (`check_prod_config.py`, `qr.py`), `tenant/` (`tenant_push.sh`, `tenant_import.sh`).

### `apps/backend/src/autobot/`

El único paquete que importa Django.

- `tenancy/`: tenants, registro en memoria (`registry.py`), esquema del documento (`schema.py`), `tx.py` (`tenant_tx`), cifrado (`crypto.py`), `store/` (único servicio de escritura de config), biblioteca de datasets, activación y archivo.
- `runtime/`: el motor: modelos de datos de cliente, entrada (`inbound.py`), `process.py`, envío (`outbound.py`, con el cortacircuitos por proveedor en `breaker.py`), jobs de Procrastinate (`jobs.py`), candados, retención, barridas, resúmenes, avisos y privacidad.
- `channels/`: webhooks (`views.py`), contrato de adaptador (`base.py`, `adapters.py`), `whatsapp/`, `telegram/`, `demo/` (puertas y selector del bot de demo), límites de tasa y limpieza de payloads.
- `owner/`: bot de avisos y de dueños: vinculación, menú del dueño y del operador, textos, bandeja y webhook.
- `ops/`: observabilidad y operación: `/health`, logs, alertas, auditoría, el estado para el operador y su resumen diario, comprobaciones de workers, contenedores y estado del host.
- `db/`: `router.py` (enrutado a `owner` de las tablas de auth) y `grants.py` (permisos de BD).
- `panel/`: API del panel: `api.py`, `auth.py`, `routers/` (HTTP) y `services/` (lógica).
- `management/commands/`: comandos de `manage.py` (`tenant_config`, `apply_grants`, `owner_invite`, `telegram_set_webhook`, `dataset_library`…).
- `migrations/`: `0001_squashed_0026_dataset_library.py` (las 26 primeras fusionadas, con las políticas RLS y las claves compuestas) y las siguientes desde `0027`; las aplicadas en producción no se editan.

### `apps/backend/tests/`

- `core/`, `packs/{salon,bus}/`: tests de `core` y escenarios de conversación de cada pack.
- `platform/{channels,runtime,tenancy,ops,owner,panel}/`: tests de `autobot`.
- `contract/`: contratos de los adaptadores de canal y de Google Calendar, con fixtures.
- `isolation/`: aislamiento RLS entre tenants.
- `repo/`: coherencia del repo (docs, settings, tenants).
- `tools/`: tests de los scripts de `deploy/` y de `tools/`.
- `fixtures/`, `helpers/`, `conftest.py`: datos y utilidades comunes.

## Panel: `apps/panel/`

Contiene `Caddyfile`, `Dockerfile`, `openapi.json`, `package.json` y el código en `src/`.

- `src/routes/`: rutas (TanStack Router): `_app/` con las pantallas, `login.tsx`, `__root.tsx`.
- `src/features/`: una carpeta por pantalla (`overview`, `tenants`, `onboarding`, `activity`, `data`, `demo-invites`, `incidents`, `logs`, `system`, `auth`).
- `src/components/`: componentes compartidos; `ui/` con las primitivas.
- `src/api/`: cliente HTTP (`client.ts`) y tipos generados (`schema.d.ts`).
- `src/lib/`: utilidades (consultas, formato, errores, CSV).
- `src/hooks/`: hooks genéricos.

## Despliegue: `deploy/`

- `compose/`: `compose.yaml` (base), `compose.local.yaml`, `compose.prod.yaml`.
- `scripts/`: `compose.sh`, `manage.sh`, `deploy.sh`, `backup.sh`, `backup-prune.sh` (desde el portátil), `restore.sh`, `install-vm.sh`, `bootstrap-server.sh`…
- `caddy/`: `Caddyfile` de producción.
- `postgres/`: `init-roles.sh`, creación de roles.
- `systemd/`: temporizadores de copia, limpieza y vigilancia de contenedores, y el servicio que filtra los puertos publicados por Docker (`DOCKER-USER`).
- `env/`: ejemplos de `.env`. `ci/`: lista de términos prohibidos.

## Relacionado

- [Visión general](vision-general.md), [referencia de comandos](../referencia/comandos.md).
