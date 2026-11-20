# Variables de entorno

Toda variable de `.env.example`, usada por `compose.yaml`/`compose.local.yaml`/`compose.prod.yaml`
o leída directamente por Django. "Obligatoria" es en producción; en local casi todas
tienen un valor por defecto en `settings.py` o se generan con `ensure-env.sh`.

| Variable | Qué hace | Obligatoria | Valor local | Quién la genera |
|---|---|---|---|---|
| `COMPOSE_FILE` | Lista de ficheros de compose que usa `docker compose` | sí | `deploy/compose/compose.yaml:deploy/compose/compose.local.yaml` | fija en `.env.example`; `ensure-env.sh` la fuerza en el servidor |
| `COMPOSE_PROJECT_NAME` | Nombre del proyecto Compose (nombres de contenedor y volumen) | sí | `autobot` | fija en `.env.example`; `ensure-env.sh` la fuerza en el servidor |
| `PUBLIC_HOST` | Dominio público que atiende Caddy | sí (prod) | vacío | la persona |
| `SHA` | SHA completo de la imagen a desplegar | sí (prod) | vacío | `make deploy`/CI |
| `AUTOBOT_IMAGE` | Imagen de `web`/`worker-inbound`/`worker-outbound`, sin tag (p.ej. `ghcr.io/<owner>/autobot`) | sí (prod) | vacío | la persona |
| `AUTOBOT_PANEL_IMAGE` | Imagen del panel, sin tag | sí (prod) | vacío | la persona |
| `DEPLOY_UID` | `id -u deploy` en la VPS; dueño de los ficheros montados en modo 0600 | sí (prod) | vacío | `ensure-env.sh` en el servidor (`id -u`; se recalcula siempre, incluso tras restaurar un `.env` de otro servidor) |
| `ENVIRONMENT` | `local` o `prod`; cambia los valores por defecto exigidos | sí | `local` | fija en `.env.example` |
| `DJANGO_SECRET_KEY` | Clave de firma de Django | sí (prod) | `change-me` | `ensure-env.sh` en el servidor (en prod, `settings.py` y `ensure-env.sh` rechazan el valor de ejemplo `change-me`) |
| `DJANGO_ALLOWED_HOSTS` | Hosts permitidos; debe incluir `127.0.0.1` y `localhost` para el túnel del panel | sí | `localhost,127.0.0.1` | la persona |
| `LOG_LEVEL` | Nivel de log de la app | no | `INFO` | fija en `.env.example` |
| `POSTGRES_PASSWORD` | Contraseña del superusuario de PostgreSQL | sí (prod) | `postgres` | `ensure-env.sh` en el servidor |
| `FP_OWNER_PASSWORD` | Contraseña del rol `fp_owner` | sí (prod) | `fp_owner` | `ensure-env.sh` en el servidor |
| `FP_APP_PASSWORD` | Contraseña del rol `fp_app` | sí (prod) | `fp_app` | `ensure-env.sh` en el servidor |
| `FP_READONLY_PASSWORD` | Contraseña del rol `fp_readonly` (consola SQL del panel) | sí (prod) | `fp_readonly` | `ensure-env.sh` en el servidor |
| `DB_APP_URL` | URL de conexión del alias `default` (`fp_app`) | sí | `postgres://fp_app:fp_app@localhost:5433/autobot` | `ensure-env.sh` en el servidor (en prod, se rechaza si contiene `localhost`) |
| `DB_OWNER_URL` | URL de conexión del alias `owner` (`fp_owner`) | sí | `postgres://fp_owner:fp_owner@localhost:5433/autobot` | `ensure-env.sh` en el servidor (en prod, se rechaza si contiene `localhost`) |
| `DB_READONLY_URL` | URL de conexión del alias `readonly` (`fp_readonly`) | sí | `postgres://fp_readonly:fp_readonly@localhost:5433/autobot` | `ensure-env.sh` en el servidor (en prod, se rechaza si contiene `localhost`) |
| `DB_CONN_MAX_AGE` | Segundos que Django reutiliza una conexión a la BD (`default` y `owner`; `readonly` siempre 0) | no | `0` en `web` (`compose.local.yaml`: `runserver` abre un hilo por petición y las conexiones persistentes se acumularían hasta agotar PostgreSQL) | por defecto `60` |
| `SECRETS_ENCRYPTION_KEY` | Claves Fernet (separadas por comas) para cifrar secretos de canal; la primera cifra, todas descifran | sí | clave de ejemplo en `.env.example` | `ensure-env.sh` en el servidor (en prod, `settings.py` y `ensure-env.sh` rechazan la clave de ejemplo) |
| `WHATSAPP_GRAPH_VERSION` | Versión de la Graph API de Meta usada por los adaptadores | no | `v23.0` | fija en `.env.example` |
| `DEMO_TELEGRAM_TOKEN` | Token del bot de Telegram de la puerta de demo | no (apaga la puerta) | vacío | la persona (@BotFather) |
| `DEMO_TELEGRAM_WEBHOOK_SECRET` | Secreto del webhook de la puerta de demo (Telegram) | no (local no lo necesita) | vacío | `ensure-env.sh` en el servidor |
| `DEMO_TELEGRAM_USERS` | Ids de Telegram con acceso a la puerta de demo (lista cerrada) | no | vacío | la persona |
| `DEMO_TELEGRAM_BOT_USERNAME` | `@usuario` del bot de demo, sin el `@` (informativo: solo para el enlace de invitación del panel, D5) | no | vacío | la persona (@BotFather) |
| `DEMO_WHATSAPP_PHONE_NUMBER_ID` | Id del número de WhatsApp de demo | no (las 5 juntas encienden la puerta) | vacío | la persona (Meta) |
| `DEMO_WHATSAPP_WABA_ID` | Id de la cuenta de WhatsApp Business de demo | no | vacío | la persona (Meta) |
| `DEMO_WHATSAPP_DISPLAY_PHONE` | Teléfono visible del número de demo (informativo) | no | vacío | la persona |
| `DEMO_WHATSAPP_APP_SECRET` | Secreto de la app de Meta de demo (firma del webhook) | no | vacío | la persona (Meta) |
| `DEMO_WHATSAPP_ACCESS_TOKEN` | Token de acceso de la app de demo | no | vacío | la persona (Meta) |
| `DEMO_WHATSAPP_VERIFY_TOKEN` | Token de verificación de la suscripción del webhook de demo | no | vacío | la persona |
| `DEMO_WHATSAPP_USERS` | Teléfonos o BSUID con acceso a la puerta de demo (WhatsApp) | no | vacío | la persona |
| `DEMO_WHATSAPP_MONTHLY_ALERT_THRESHOLD` | Umbral de aviso de coste mensual de la puerta de demo | no | `300` | fija en `.env.example` |
| `PUBLIC_URL` | URL pública base de los webhooks; solo la usa `telegram_set_webhook` | no (local: dominio ngrok) | vacío | `ensure-env.sh` en el servidor (`https://$PUBLIC_HOST`, si no se fija a mano) |
| `DEMO_SALON_CALENDAR_ID` | Calendario de Google del `salon` de demo; sustituye el valor de la plantilla al crearla (`seed_demos`) | no (sin ella el demo no reserva de verdad) | vacío | la persona |
| `NGROK_DOMAIN` | Dominio reservado de ngrok para `make ngrok` (solo local) | no | vacío | la persona |
| `NOTIFY_BOT_TOKEN` | Token del bot de avisos / asistente del dueño | no | vacío | la persona (@BotFather) |
| `NOTIFY_BOT_WEBHOOK_SECRET` | Secreto del webhook del bot de avisos | no (local no lo necesita) | vacío | `ensure-env.sh` en el servidor |
| `OWNER_SUPPORT_EMAIL` | Email de soporte que ofrece el menú del dueño (opción "Contacto") | no | vacío | la persona |
| `OPS_TELEGRAM_CHAT_ID` | Chat de Telegram donde el bot de avisos manda alertas de operación | no | vacío | la persona |
| `SENTRY_DSN` | DSN del proyecto de Sentry; vacío desactiva la integración | no | vacío | la persona |
| `HEALTHCHECKS_PING_URL` | URL de latido del check "worker" de healthchecks.io | no | vacío | la persona |
| `RELEASE_SHA` | SHA desplegado, expuesto a la app para los logs | sí (prod) | vacío | `deploy/scripts/deploy.sh` (= `SHA`) |
| `SERVICE_NAME` | Nombre del servicio en los logs estructurados (`web`/`worker-inbound`/`worker-outbound`) | no | `web` | fija por cada servicio en el compose |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | Ruta de la clave de la cuenta de servicio de Google Calendar; vacío monta `/dev/null` | no | vacío | la persona |
| `RETENTION_CLEANUP_ENABLED` | Permiso explícito para el borrado nocturno de retención RGPD | sí (para activarlo) | `false` | la persona (aprobación humana) |

`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `RESTIC_REPOSITORY`, `RESTIC_PASSWORD_FILE`
y `HEALTHCHECKS_BACKUP_PING_URL` no van en `.env`: viven en `var/backup.env` en el
servidor (ver [`deploy/env/backup.env.example`](../../deploy/env/backup.env.example) y
[procedimientos/servidor.md](../procedimientos/servidor.md)).

## Variables de los scripts de `deploy/scripts/`

No las lee Django: solo cambian el comportamiento del script en sí (pruebas locales,
`restore-test.sh`, `server-migrate.sh`). No van en `.env`.

| Variable | Script | Qué hace | Valor por defecto |
|---|---|---|---|
| `AUTOBOT_PROJECT` | `lib.sh` (todos) | Nombre de proyecto de `docker compose --project-name` | `autobot` |
| `AUTOBOT_COMPOSE_BASE` / `AUTOBOT_COMPOSE_OVERRIDE` | `lib.sh` (todos) | Ruta a los ficheros de compose, para probar contra otros (localprod, `restore-test.sh`) | `deploy/compose/compose.yaml` / `compose.prod.yaml` |
| `AUTOBOT_BACKUP_CONFIG` | `backup.sh`, `restore.sh` | Ruta a `backup.env` | `/srv/autobot/var/backup.env` |
| `AUTOBOT_BOOTSTRAP_MARKER` | `restore.sh` | Ruta al marcador de bootstrap (T1) | `/var/lib/autobot/bootstrap-complete` |
| `RESTIC_BIN` | `backup.sh`, `restore.sh`, `restore-test.sh` | Binario de restic a usar | `restic` |
| `AUTOBOT_RESTORE_DB_ONLY` | `restore.sh` | Solo restaura la base de datos; no arranca ningún servicio ni marca el destino como desplegado (T4: ensayo de traslado) | `false` |
| `AUTOBOT_RESTORE_START_WORKERS` | `restore.sh` | Arranca también los workers en la misma ejecución (T1); para arrancarlos después de verificar, usa `compose.sh up -d worker-inbound worker-outbound` en vez de repetir `restore.sh` | `false` |
| `AUTOBOT_RESTORE_SNAPSHOT` | `restore.sh` | Id de snapshot concreto a restaurar en vez de `latest` (T4: el destino de un traslado restaura exactamente el snapshot del corte) | `latest` |
| `AUTOBOT_PRUNE_LOCK_WAIT` | `prune.sh` | Segundos que espera el candado compartido con `deploy.sh` antes de omitir el prune | `60` |
| `AUTOBOT_HTTPS_CHECK_TIMEOUT` / `AUTOBOT_HTTPS_CHECK_INTERVAL` | `deploy.sh` | Reintentos de la comprobación HTTPS tras desplegar (A9) | `60` / `5` (segundos) |

`var/.restic-repo-id` (no es variable de entorno, sino un fichero en el servidor) guarda
el id del repositorio de restic contra el que se hizo el primer backup; `backup.sh` se
niega si `restic cat config` devuelve un id distinto (A3). `var/.frozen` congela el
origen o el destino durante un traslado (T4): `deploy.sh` y `restore.sh` se niegan a
tocar un host con ese fichero presente.
