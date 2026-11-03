# Comandos

Referencia única de los comandos `make` y `manage.py` del proyecto. Cada tarea que añade
o cambia un comando amplía esta tabla en el mismo commit.

## `make` (desarrollo local)

| Comando | Qué hace |
|---|---|
| `make up` | Levanta los contenedores (`docker compose up -d --build`) |
| `make down` | Para los contenedores |
| `make status` | `docker compose ps` |
| `make db-roles` | Ejecuta `init-roles.sh` dentro del contenedor `db`: crea `fp_owner`, `fp_app` y `fp_readonly`, o actualiza sus contraseñas, sin recrear el contenedor |
| `make logs SERVICE=<servicio>` | Sigue los logs de un servicio (`docker compose logs --tail=100 --follow`) |
| `make shell` | Abre una shell de Django dentro de `web` |
| `make test` | `uv run pytest` |
| `make check` | Puerta de calidad del backend: `ruff check`, `ruff format --check`, `mypy`, `import-linter`, `pytest` |
| `make telegram-poll SLUG=<slug>` | *Long polling* del bot de Telegram de un tenant (o `notify`), para desarrollo local sin webhook |
| `make bus-validar TENANT=<slug>` | Valida el dataset de horarios del tenant |
| `make bus-formatear TENANT=<slug>` | Realinea las columnas de las tablas de horarios sin tocar el YAML |
| `make bus-revision TENANT=<slug> [ARGS="..."]` | Genera `revision/<slug>/horarios.{html,pdf}` con los cambios desde la última publicación |
| `make bus-publicar TENANT=<slug>` | Tras el commit y el despliegue: marca como publicada la versión actual del dataset (tag `datos/<slug>/<fecha>`) |
| `make tenant-health SLUG=<slug>` | `tenant_health`: comprueba y persiste la salud del pack y del canal |
| `make qr FILE=<document.yaml> [ARGS="..."]` | Genera el QR a partir de un documento exportado, en la máquina del desarrollador, sin secretos |
| `make check-prod-config` | Ejecuta `tools/check_prod_config.py`: prueba el allowlist de Caddy contra un *upstream* local |
| `make deploy [SHA=]` | Lanza el workflow de despliegue en GitHub Actions |
| `make backup-now` | Ejecuta `deploy/backup.sh` en el servidor por SSH |
| `make restore-test` | `bash deploy/restore-test.sh`: simulacro de restauración |
| `make prod-manage HOST=<servidor> CMD="..." [TTY=1]` | Ejecuta el comando con la imagen desplegada mediante SSH; `TTY=1` para comandos interactivos, sin TTY para streams binarios |
| `make tenant-push HOST=<servidor> SLUG=<slug> [SECRETS=<yaml>]` | Exporta la BD local y la importa por SSH. El YAML privado aporta solo la entrada del slug; el temporal se borra al salir |

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
| `tenant_status <slug> pause\|resume\|offboard` | Cambia el estado y crea una versión auditada; la baja exige escribir exactamente el slug |
