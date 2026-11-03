# Comandos

Referencia única de los comandos `make` y `manage.py` del proyecto. Cada tarea que añade
o cambia un comando amplía esta tabla en el mismo commit.

## `make` (desarrollo local)

| Comando | Qué hace |
|---|---|
| `make up` | Tras el bootstrap, levanta los contenedores (`docker compose up -d --build`) |
| `make dev-bootstrap` | Prepara db y roles, construye la imagen local con herramientas dev, migra, reaplica permisos, siembra demos y levanta web/worker; se puede repetir |
| `make dev-reset` | Exige escribir `RESET`, elimina el volumen local y repite el bootstrap |
| `make tenant-import DIR=<dir> [SECRETS=<yaml>]` | Importa un directorio contra la BD local desde el host; acepta rutas con espacios |
| `make dev-activity` | `manage.py seed_dev_activity`: actividad falsa y realista (mensajes, respuestas, avisos, alertas abiertas y resueltas, un `unknown`, un trabajo fallido y muestras de sistema) para ver el panel con datos; se niega fuera de `local` |
| `make ngrok [NGROK_DOMAIN=<dominio>]` | Abre el túnel al puerto 8000 usando el dominio reservado configurado |
| `make down` | Para los contenedores |
| `make status` | `docker compose ps` |
| `make db-roles` | Ejecuta `init-roles.sh` dentro del contenedor `db`: crea `fp_owner`, `fp_app` y `fp_readonly`, o actualiza sus contraseñas, sin recrear el contenedor |
| `make logs SERVICE=<servicio>` | Sigue los logs de un servicio (`docker compose logs --tail=100 --follow`) |
| `make shell` | Abre una shell de Django dentro de `web` |
| `make test` | `uv run pytest` |
| `make check` | Puerta de calidad del backend: `ruff check`, `ruff format --check`, `mypy`, `import-linter`, `pytest` |
| `make telegram-poll SLUG=<slug>` | *Long polling* del bot de Telegram de un tenant (o `notify`), para desarrollo local sin webhook |
| `make bus-bajar TENANT=<slug> [PROD=1]` | Exporta el dataset vigente a `datos/<slug>/timetable` y `.publicado/timetable`; sustituye ambas copias locales |
| `make bus-validar TENANT=<slug>` | Valida `datos/<slug>/timetable` |
| `make bus-formatear TENANT=<slug>` | Realinea las columnas de las tablas de horarios sobre `datos/<slug>/timetable`, sin cambiar los datos |
| `make bus-revision TENANT=<slug> [ARGS="..."]` | Genera HTML/PDF comparando con `.publicado/timetable`; `ARGS="--base <dir>"` elige otra base |
| `make bus-publicar TENANT=<slug> COMMENT="..." [PROD=1]` | Publica la copia local validada en BD y actualiza `.publicado` tras el éxito; sin `PROD`, usa la BD local |
| `make tenant-health SLUG=<slug>` | `tenant_health`: comprueba y persiste la salud del pack y del canal |
| `make qr FILE=<document.yaml> [ARGS="..."]` | Genera el QR a partir de un documento exportado, en la máquina del desarrollador, sin secretos |
| `make check-prod-config` | Ejecuta `tools/check_prod_config.py`: prueba el allowlist de Caddy contra un *upstream* local |
| `make api` | Regenera `panel/openapi.json` a partir del esquema vigente de la API del panel |
| `make deploy [SHA=]` | Lanza el workflow de despliegue en GitHub Actions |
| `make backup-now` | Ejecuta `deploy/backup.sh` en el servidor por SSH |
| `make restore-test` | `bash deploy/restore-test.sh`: simulacro de restauración |
| `make prod-manage CMD="..." [TTY=1]` | Ejecuta el comando con la imagen desplegada mediante SSH; `TTY=1` para comandos interactivos, sin TTY para streams binarios |
| `make tenant-push SLUG=<slug> [SECRETS=<yaml>]` | Exporta la BD local y la importa por SSH. El YAML privado aporta solo la entrada del slug; el temporal se borra al salir |

`HOST ?= autobot` usa el alias de `~/.ssh/config`; se puede sobrescribir en cada
comando. `NGROK_DOMAIN` usa el dominio reservado de desarrollo documentado en el
`Makefile`.

## `manage.py`

| Comando | Qué hace |
|---|---|
| `migrate` | El `migrate` de Django, pero corre por defecto sobre el alias `owner` (`fp_app` no puede hacer DDL) |
| `apply_grants` | Reaplica los permisos deseados de PostgreSQL (`db_grants.py`); se ejecuta tras `migrate`, en cada despliegue y tras cada restauración |
| `tenant_health <slug>` | Comprueba la salud del pack y del canal de un negocio, forzando la comprobación |
| `telegram_set_webhook <target> [--delete]` | Fija o borra el webhook de Telegram de un tenant, del bot de demo (`demo`) o del bot de avisos (`notify`) |
| `telegram_poll [<slug>]` | *Long polling* de un bot de Telegram (desarrollo local) |
| `owner_invite <slug>` | Genera un enlace de un solo uso para que el dueño del negocio enlace su Telegram |
| `owner_unlink <slug>` | Desconecta el Telegram del dueño del negocio |
| `export_contact <slug> <external_id> [--channel main\|demo_tg\|demo_wa] --output <fichero>` | Exporta los datos de un contacto a un fichero privado (derechos RGPD) |
| `export_tenant <slug> --output <fichero>` | Exporta todos los datos de un negocio a un fichero privado (derechos RGPD) |
| `forget_contact <slug> <external_id> [--channel ...]` | Borra los datos de un contacto |
| `purge_tenant <slug>` | Solo tras la baja: borra datos, secretos, métricas e historiales; conserva una versión depurada y exige escribir el slug |
| `outbound_resolve <uuid> (--mark-sent\|--resend) --confirm` | Resuelve un envío ambiguo a mano; sin `--confirm` explica el riesgo y no hace nada |
| `job_retry <id>` | Reintenta un trabajo fallido idempotente a mano; rechaza los de envío (`send_message`, `send_notification`) |
| `tenant_secrets_reencrypt` | Recifra todos los secretos de canal con la primera clave de `SECRETS_ENCRYPTION_KEY`, atómicamente y con auditoría; ver [rotación](runbooks/09-rotar-secretos.md) |
| `tenant_config export <slug> <dir\|->` | Exporta documento y datasets vigentes, sin secretos; el directorio debe estar vacío o ser nuevo. Con `-`, tar.gz por stdout y diagnósticos por stderr |
| `tenant_config import <dir\|-> [--secrets <yaml>] [--comment "..."]` | Crea o publica desde un directorio o tar.gz por stdin. Valida documento, datasets y secretos juntos en una transacción. Admite `secrets.yaml` en la raíz del tar |
| `tenant_config validate --all` | Valida todos los documentos vigentes; sale con error si alguno es ilegible, inválido, degradado o ambiguo |
| `tenant_dataset export <slug> <name> <dir\|->` | Exporta el dataset vigente a un directorio vacío o tar.gz, sin secretos |
| `tenant_dataset import <slug> <name> <dir\|-> --comment "..."` | Publica un dataset de texto UTF-8; con el mismo hash imprime «sin cambios» |
| `seed_demos` | Crea los demos de las plantillas solo si no tienen versiones; conserva los cambios posteriores |
| `seed_dev_activity [--days N] [--reset]` | Crea actividad falsa en local (mensajes, avisos, alertas, un trabajo fallido, muestras de sistema); sin `--days`, los transcurridos del mes en curso. Con `--reset`, borra antes lo que creó. Se niega fuera de `local` |
| `tenant_status <slug> pause\|resume\|offboard` | Cambia el estado y crea una versión auditada; la baja exige escribir exactamente el slug |
| `panel_user create <usuario>` | Crea el usuario único del panel: contraseña (dos veces, con los validadores de Django) y un TOTP confirmado; muestra la URI `otpauth://` y su QR en ASCII una sola vez |
| `panel_user reset-totp <usuario>` | Sustituye el dispositivo TOTP; lo muestra una sola vez |
| `panel_user set-password <usuario>` | Cambia la contraseña del usuario del panel |
| `panel_user exists <usuario>` | Sale con código 0 si existe, 1 si no; lo usa `make dev-bootstrap` |
| `export_openapi <ruta>` | Escribe el esquema OpenAPI de la API del panel; lo usa `make api` |
