# Variables de entorno

Toda variable de `.env.example`, usada por `compose.yaml`/`compose.local.yaml`/`compose.prod.yaml`
o leída directamente por Django. "Obligatoria" es en producción; en local casi todas
tienen un valor por defecto en `settings.py` o se generan con `ensure-env.sh`.

| Variable | Qué hace | Obligatoria | Valor local | Quién la genera |
|---|---|---|---|---|
| `COMPOSE_FILE` | Lista de ficheros de compose que usa `docker compose` | sí | `deploy/compose/compose.yaml:deploy/compose/compose.local.yaml` | fija en `.env.example`; `ensure-env.sh` la fuerza en el servidor |
| `COMPOSE_PROJECT_NAME` | Nombre del proyecto Compose (nombres de contenedor y volumen) | sí | `autobot` | fija en `.env.example`; `ensure-env.sh` la fuerza en el servidor |
| `PUBLIC_HOST` | Dominio público que atiende Caddy | sí (prod) | vacío | el operador |
| `SHA` | SHA completo de la imagen a desplegar | sí (prod) | vacío | `make deploy`/CI |
| `AUTOBOT_IMAGE` | Imagen de `web`/`web-panel` y los workers, sin tag (p.ej. `ghcr.io/<owner>/autobot`) | sí (prod) | vacío | el operador |
| `AUTOBOT_PANEL_IMAGE` | Imagen del panel, sin tag | sí (prod) | vacío | el operador |
| `DEPLOY_UID` | `id -u deploy` en la VPS; dueño de los ficheros montados en modo 0600 | sí (prod) | vacío | `ensure-env.sh` en el servidor (`id -u`; se recalcula siempre, incluso tras restaurar un `.env` de otro servidor) |
| `ENVIRONMENT` | `local` o `prod`; cambia los valores por defecto exigidos. Si falta, `settings.py` asume `prod` (falla cerrado: sin DEBUG ni claves de ejemplo). Las herramientas locales (pytest, mypy, `make`) usan `config.settings_dev`, que fija `local`; los contenedores de `compose.local.yaml` deben declararla | sí | `prod` si falta | fija en `.env.example` (`local`) y en `compose.prod.yaml` (`prod`) |
| `DJANGO_SECRET_KEY` | Clave de firma de Django | sí (prod) | `change-me` | `ensure-env.sh` en el servidor (en prod, `settings.py` y `ensure-env.sh` rechazan el valor de ejemplo `change-me`) |
| `DJANGO_ALLOWED_HOSTS` | Hosts permitidos; debe incluir `127.0.0.1` y `localhost` para el túnel del panel | sí | `localhost,127.0.0.1` | el operador |
| `LOG_LEVEL` | Nivel de log de la app | no | `INFO` | fija en `.env.example` |
| `POSTGRES_PASSWORD` | Contraseña del superusuario de PostgreSQL | sí (prod) | `postgres` | `ensure-env.sh` en el servidor |
| `FP_OWNER_PASSWORD` | Contraseña del rol `fp_owner` | sí (prod) | `fp_owner` | `ensure-env.sh` en el servidor |
| `FP_APP_PASSWORD` | Contraseña del rol `fp_app` | sí (prod) | `fp_app` | `ensure-env.sh` en el servidor |
| `FP_READONLY_PASSWORD` | Contraseña del rol `fp_readonly` (consola SQL del panel) | sí (prod) | `fp_readonly` | `ensure-env.sh` en el servidor |
| `DB_APP_URL` | URL de conexión del alias `default` (`fp_app`) | sí | `postgres://fp_app:fp_app@localhost:5433/autobot` | `ensure-env.sh` en el servidor (en prod, se rechaza si contiene `localhost`) |
| `DB_OWNER_URL` | URL de conexión del alias `owner` (`fp_owner`) | sí | `postgres://fp_owner:fp_owner@localhost:5433/autobot` | `ensure-env.sh` en el servidor (en prod, se rechaza si contiene `localhost`) |
| `DB_READONLY_URL` | URL de conexión del alias `readonly` (`fp_readonly`) | sí | `postgres://fp_readonly:fp_readonly@localhost:5433/autobot` | `ensure-env.sh` en el servidor (en prod, se rechaza si contiene `localhost`) |
| `DB_CONN_MAX_AGE` | Segundos que Django reutiliza una conexión a la BD (`default` y `owner`; `readonly` siempre 0) | no | `0` en los cuatro workers (local y prod); `web` usa el valor por defecto (gunicorn acota los hilos, así que las conexiones persistentes también están acotadas) | por defecto `60` |
| `DB_CONNECT_TIMEOUT` | Segundos máximos para abrir una conexión a la BD (`connect_timeout` de libpq, en todos los alias y en el pool del worker). Además se activan siempre los keepalives TCP (30 s de inactividad, sondeo cada 10 s, 3 fallos) para que una red medio muerta no cuelgue las consultas hasta el timeout de gunicorn | no | sin definir | por defecto `5` |
| `WORKER_DB_POOL_MIN` / `WORKER_DB_POOL_MAX` | Tamaño mínimo y máximo del pool psycopg propio de `procrastinate worker` (LISTEN, búsqueda, latido y cierre de los trabajos de `--concurrency`) | no | el compose fija `WORKER_DB_POOL_MAX` por worker: 8 (`worker-inbound`), 10 (`worker-calendar`), 6 (`worker-periodic`) y 10 (`worker-outbound`) | por defecto `1` y `6` |
| `PYTHON_CPU_COUNT` | De Python, no de Autobot: fija cuántas CPU cree tener el proceso; el compose de producción lo pone en los workers para que el pool de hilos por defecto de asyncio (`min(32, CPU + 4)`), que ejecuta los trabajos síncronos, no limite su concurrencia (ADR-023) | no | sin definir | `compose.prod.yaml`: 4, 6, 4 y 6 |
| `SECRETS_ENCRYPTION_KEY` | Claves Fernet (separadas por comas) para cifrar secretos de canal; la primera cifra, todas descifran | sí | clave de ejemplo en `.env.example` | `ensure-env.sh --first-install`, solo en la primera instalación; después, si falta, el despliegue aborta (ADR-022). En prod, `settings.py` y `ensure-env.sh` rechazan la clave de ejemplo |
| `WHATSAPP_GRAPH_VERSION` | Versión de la Graph API de Meta usada por los adaptadores | no | `v23.0` | fija en `.env.example` |
| `DEMO_TELEGRAM_TOKEN` | Token del bot de Telegram de la puerta de demo | no (apaga la puerta) | vacío | el operador (@BotFather) |
| `DEMO_TELEGRAM_WEBHOOK_SECRET` | Secreto del webhook de la puerta de demo (Telegram) | no (local no lo necesita) | vacío | `ensure-env.sh` en el servidor |
| `DEMO_TELEGRAM_USERS` | Ids de Telegram con acceso a la puerta de demo (lista cerrada) | no | vacío | el operador |
| `DEMO_TELEGRAM_BOT_USERNAME` | `@usuario` del bot de demo, sin el `@` (informativo: solo para el enlace de invitación del panel, D5) | no | vacío | el operador (@BotFather) |
| `DEMO_WHATSAPP_PHONE_NUMBER_ID` | Id del número de WhatsApp de demo | no (las 5 juntas encienden la puerta) | vacío | el operador (Meta) |
| `DEMO_WHATSAPP_WABA_ID` | Id de la cuenta de WhatsApp Business de demo | no | vacío | el operador (Meta) |
| `DEMO_WHATSAPP_DISPLAY_PHONE` | Teléfono visible del número de demo (informativo) | no | vacío | el operador |
| `DEMO_WHATSAPP_APP_SECRET` | Secreto de la app de Meta de demo (firma del webhook) | no | vacío | el operador (Meta) |
| `DEMO_WHATSAPP_ACCESS_TOKEN` | Token de acceso de la app de demo | no | vacío | el operador (Meta) |
| `DEMO_WHATSAPP_VERIFY_TOKEN` | Token de verificación de la suscripción del webhook de demo | no | vacío | el operador |
| `DEMO_WHATSAPP_USERS` | Teléfonos o BSUID con acceso a la puerta de demo (WhatsApp) | no | vacío | el operador |
| `DEMO_WHATSAPP_MONTHLY_ALERT_THRESHOLD` | Umbral de aviso de coste mensual de la puerta de demo | no | `300` | fija en `.env.example` |
| `PUBLIC_URL` | URL pública base de los webhooks; solo la usa `telegram_set_webhook` | no (local: dominio ngrok) | vacío | `ensure-env.sh` en el servidor (`https://$PUBLIC_HOST`, si no se fija a mano) |
| `DEMO_SALON_CALENDAR_ID` | Calendario de Google del `salon` de demo; sustituye el valor de la plantilla al crearla (`seed_demos`) | no (sin ella el demo no reserva de verdad) | vacío | el operador |
| `NGROK_DOMAIN` | Dominio reservado de ngrok para `make ngrok` (solo local) | no | vacío | el operador |
| `NOTIFY_BOT_TOKEN` | Token del bot de avisos / asistente del dueño | no | vacío | el operador (@BotFather) |
| `NOTIFY_BOT_WEBHOOK_SECRET` | Secreto del webhook del bot de avisos | no (local no lo necesita) | vacío | `ensure-env.sh` en el servidor |
| `OWNER_SUPPORT_EMAIL` | Email de soporte que ofrece el menú del dueño (opción "Contacto") | no | vacío | el operador |
| `PLATFORM_PRIVACY_URL` | Política de privacidad de la plataforma (`https://…`); la cita la línea de privacidad del bot de demo. Sin ella, la línea omite el enlace | no | vacío | el operador |
| `OPS_TELEGRAM_CHAT_ID` | Chat de Telegram donde el bot de avisos manda las alertas de operación y el resumen diario; solo en él responde el menú de operador ([ADR-029](../arquitectura/adr/ADR-029-menu-de-operador.md)) | no | vacío | el operador |
| `SENTRY_DSN` | DSN del proyecto de Sentry; vacío desactiva la integración | no | vacío | el operador |
| `HEALTHCHECKS_PING_URL` | URL de latido del check "worker" de healthchecks.io | no | vacío | el operador |
| `RELEASE_SHA` | SHA desplegado, expuesto a la app para los logs | sí (prod) | vacío | lo fija el compose de producción (= `SHA`); no va en `.env` |
| `SERVICE_NAME` | Nombre del servicio en los logs estructurados (`web`/`web-panel`/`worker-inbound`/`worker-calendar`/`worker-periodic`/`worker-outbound`) | no | `web` | lo fija el compose por cada servicio; no va en `.env` |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | Ruta de la clave de la cuenta de servicio de Google Calendar; vacío monta `/dev/null` | no | vacío | el operador |
| `RETENTION_CLEANUP_ENABLED` | Limpieza nocturna de datos antiguos | no | `true` en producción (`compose.prod.yaml`); `false` en local y en `settings.py` | el operador: `false` en el `.env` del servidor lo apaga; `check_prod_config.py` exige `true` en el compose |
| `OPS_STATE_DIR` | Directorio con el estado de operación que el panel y `ops_check` leen (`backup.json`, `backup-prune.json`, `deploys.jsonl`, instantánea de contenedores) | no | `/tmp/ops` en `compose.local.yaml` | por defecto `<app>/state/ops`; `/run/ops` en `compose.prod.yaml` (montaje de solo lectura de `var/state/ops`) |
| `VICTORIALOGS_URL` | URL de VictoriaLogs: destino de los logs estructurados y de la consulta de logs del panel; vacío los deja solo en stdout | no | `http://victorialogs:9428` | fija en `compose.yaml` (para `web` y los workers) y en `compose.prod.yaml` para `web-panel`, que solo existe allí |
| `AUTOBOT_BINARY_STDOUT` | Interna: `manage.py` la fija en `1` cuando un comando escribe binario por stdout (`tenant_config export -`, `dataset_library pull -`) para que el log vaya a stderr | no | no se define a mano | `manage.py` |
| `AUTOBOT_CADDY_HTTP_PORT` / `AUTOBOT_CADDY_HTTPS_PORT` | Puertos del host a los que publica Caddy el 80 y el 443; solo se cambian en `localprod` para convivir con el stack de desarrollo | no | no aplica | por defecto `80` / `443`; `localprod.sh` fija `8081` / `8443` |
| `AUTOBOT_WEB_HOST_PORT` | Puerto de `127.0.0.1` en el que se publica `web` en producción (`/health/internal` para `deploy.sh` y túnel del panel) | no | no aplica | por defecto `8000`; `localprod.sh` fija `18000` |
| `AUTOBOT_PANEL_HOST_PORT` | Puerto de `127.0.0.1` en el que se publica el panel en producción (túnel SSH) | no | no aplica | por defecto `8080`; `localprod.sh` fija `18080` |

`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `RESTIC_REPOSITORY`, `RESTIC_PASSWORD_FILE`
y `HEALTHCHECKS_BACKUP_PING_URL` no van en `.env`: viven en `var/backup.env` en el
servidor (ver `deploy/env/backup.env.example` y
[procedimientos/servidor.md](../procedimientos/servidor.md)).

## Variables de los scripts de `deploy/scripts/`

No las lee Django: solo cambian el comportamiento del script en sí (pruebas locales,
`restore-test.sh`, `server-migrate.sh`). No van en `.env`.

| Variable | Script | Qué hace | Valor por defecto |
|---|---|---|---|
| `AUTOBOT_PROJECT` | `lib.sh` (todos) | Nombre de proyecto de `docker compose --project-name` | `autobot` |
| `AUTOBOT_COMPOSE_BASE` / `AUTOBOT_COMPOSE_OVERRIDE` | `lib.sh` (todos) | Ruta a los ficheros de compose, para probar contra otros (localprod, `restore-test.sh`) | `deploy/compose/compose.yaml` / `compose.prod.yaml` |
| `AUTOBOT_BACKUP_CONFIG` | `backup.sh`, `restore.sh` | Ruta a `backup.env` | `/srv/autobot/var/backup.env` |
| `AUTOBOT_BOOTSTRAP_MARKER` | `restore.sh` | Ruta al marcador de bootstrap, que escribe `install-vm.sh` | `/var/lib/autobot/bootstrap-complete` |
| `RESTIC_BIN` | `backup.sh`, `restore.sh`, `restore-test.sh` | Binario de restic a usar | `restic` |
| `AUTOBOT_RESTORE_DB_ONLY` | `restore.sh` | Solo restaura la base de datos; no arranca ningún servicio ni marca el destino como desplegado (ensayo de traslado) | `false` |
| `AUTOBOT_RESTORE_START_WORKERS` | `restore.sh` | Arranca también los workers en la misma ejecución; para arrancarlos después de verificar, usa `compose.sh up -d worker-inbound worker-calendar worker-periodic worker-outbound` en vez de repetir `restore.sh` | `false` |
| `AUTOBOT_RESTORE_SNAPSHOT` | `restore.sh` | Id de snapshot concreto a restaurar en vez de `latest` (el destino de un traslado restaura exactamente el snapshot del corte) | `latest` |
| `AUTOBOT_PRUNE_LOCK_WAIT` | `prune.sh` | Segundos que espera el candado compartido con `deploy.sh` antes de omitir el prune | `60` |
| `AUTOBOT_HTTPS_CHECK_TIMEOUT` / `AUTOBOT_HTTPS_CHECK_INTERVAL` | `deploy.sh` | Reintentos de la comprobación HTTPS tras desplegar | `60` / `5` (segundos) |
| `AUTOBOT_HTTPS_INSECURE` | `deploy.sh`, `localprod.sh` | Si es `true`, la comprobación HTTPS tras desplegar acepta un certificado no verificable (la CA interna de Caddy en `localprod`); nunca en producción | `false` |
| `AUTOBOT_SERVER_ENV` | `server-migrate.sh` | Ruta de `server.env` (plantilla en `deploy/env/server.env.example`; solo contiene `PUBLIC_HOST`) | `var/server.env` |
| `AUTOBOT_DEPLOY_LOCK_HELD` | `deploy.sh`, `ssh-deploy.sh` | Interna: `ssh-deploy.sh` la fija en `1` al tomar el candado de despliegue, para que `deploy.sh` no vuelva a pedirlo | sin definir |
| `AUTOBOT_DEPLOY_LOCK_TIMEOUT` | `deploy.sh`, `ssh-deploy.sh` | Segundos que espera el candado de despliegue (`var/.deploy.lock`) antes de decir que hay otro despliegue en marcha; los tests lo acortan | `10` |
| `AUTOBOT_RESTORE_TEST_SKIP_BUILD` | `restore-test.sh` | Si es `true`, no construye la imagen del backend: usa la `autobot:restore-test` ya construida (el CI la construye antes con caché compartida) | `false` |
| `AUTOBOT_INSTALL_LIB_ONLY` | `install-vm.sh` | Si es `1`, el script solo define sus funciones y se detiene antes de leer argumentos; lo usan los tests (`apps/backend/tests/tools/test_install_vm.py`) | sin definir |
| `AUTOBOT_LIB_FUNCTIONS_ONLY` | `lib.sh` | Si es `1`, `lib.sh` solo define sus funciones (`compose_in`, `ensure_state_dirs`), sin comprobar el usuario ni cambiar de directorio; lo usan `localprod.sh` y `restore-test.sh` | sin definir |
| `AUTOBOT_RESTORE_SKIP_BOOTSTRAP_CHECK` | `restore.sh` | Omite la comprobación del marcador de bootstrap; solo para ensayos en una máquina que no es una VM (`restore-test.sh`, `localprod.sh`) | `false` |
| `AUTOBOT_BACKUP_MIN_FREE_BYTES` | `backup.sh`, `deploy.sh` | Espacio libre mínimo exigido antes de volcar la base de datos (en `backup.sh`, si el último volcado ×2 es mayor, se usa eso; en `deploy.sh`, el tamaño de la base si es mayor) | `536870912` (512 MiB) |
| `AUTOBOT_BACKUP_DEPLOY_LOCK_WAIT` | `backup.sh` | Segundos que espera el candado de despliegue (compartido) antes de fallar visiblemente | `300` |
| `AUTOBOT_MIGRATE_LOCK_TIMEOUT` | `deploy.sh` | `lock_timeout` de PostgreSQL para `migrate` (`PGOPTIONS`) | `5s` |
| `AUTOBOT_WATCHDOG_DISK_PCT` | `watchdog.sh` | Porcentaje de disco usado a partir del cual avisa | `90` |
| `AUTOBOT_WATCHDOG_STALE_MIN` | `watchdog.sh` | Minutos sin actualizarse `containers.json` para avisar | `15` |
| `AUTOBOT_WATCHDOG_REPEAT_SECS` | `watchdog.sh` | Segundos mínimos entre dos avisos de la misma condición | `3600` |
| `AUTOBOT_RESTIC_CHECK_SUBSET` | `backup.sh` | Porción de datos que lee la verificación semanal de `restic check` | `5%` |

`var/.restic-repo-id` (no es variable de entorno, sino un fichero en el servidor) guarda
el id del repositorio de restic contra el que se hizo el primer backup; `backup.sh` se
niega si `restic cat config` devuelve un id distinto. `var/.frozen` congela el
origen o el destino durante un traslado: `deploy.sh` y `restore.sh` se niegan a
tocar un host con ese fichero presente.

## Secretos del entorno `production` de GitHub

No son variables de entorno de la app: son *secrets* del entorno `production` del repositorio
que lee el workflow de despliegue (`.github/workflows/deploy.yml`) para conectarse por SSH
a la VPS como `deploy`. Los sube `install-vm.sh` (paso `github`) y los actualiza
`server-migrate.sh` en un traslado; ver [servidor](../procedimientos/servidor.md).

| Secreto | Qué contiene |
|---|---|
| `DEPLOY_HOST` | Host o IP de la VPS |
| `DEPLOY_SSH_KEY` | Clave privada de CI, solo para ejecutar `deploy/scripts/deploy.sh` |
| `DEPLOY_KNOWN_HOSTS` | Clave de host de la VPS, para fijar su identidad (`StrictHostKeyChecking=yes`) |
