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
| `make tenant-sync` | `sync_tenants` y reinicio de `web`/`worker`, tras editar `tenants/<slug>/tenant.yaml` a mano |
| `make tenant-health SLUG=<slug>` | `tenant_health`: comprueba y persiste la salud del pack y del canal |
| `make qr SLUG=<slug> [ARGS="..."]` | Genera el QR del enlace público del canal, en la máquina del desarrollador, sin secretos |
| `make check-prod-config` | Ejecuta `tools/check_prod_config.py`: prueba el allowlist de Caddy contra un *upstream* local |
| `make deploy [SHA=]` | Lanza el workflow de despliegue en GitHub Actions |
| `make backup-now` | Ejecuta `deploy/backup.sh` en el servidor por SSH |
| `make restore-test` | `bash deploy/restore-test.sh`: simulacro de restauración |

## `manage.py`

| Comando | Qué hace |
|---|---|
| `migrate` | El `migrate` de Django, pero corre por defecto sobre el alias `owner` (`fp_app` no puede hacer DDL) |
| `apply_grants` | Reaplica los permisos deseados de PostgreSQL (`db_grants.py`); se ejecuta tras `migrate`, en cada despliegue y tras cada restauración |
| `new_tenant <slug> --pack <pack> --channel whatsapp\|telegram` | Crea `tenants/<slug>/tenant.yaml`: id UUIDv7, `public_id` aleatorio, `status: onboarding` y los campos del pack (sin valor por defecto quedan `null`) |
| `sync_tenants [--strict]` | Vuelca la parte común del registro en memoria a la tabla `tenant` |
| `tenant_health <slug>` | Comprueba la salud del pack y del canal de un negocio, forzando la comprobación |
| `telegram_set_webhook <target> [--delete]` | Fija o borra el webhook de Telegram de un tenant, del bot de demo (`demo`) o del bot de avisos (`notify`) |
| `telegram_poll [<slug>]` | *Long polling* de un bot de Telegram (desarrollo local) |
| `owner_invite <slug>` | Genera un enlace de un solo uso para que el dueño del negocio enlace su Telegram |
| `owner_unlink <slug>` | Desconecta el Telegram del dueño del negocio |
| `export_contact <slug> <external_id> [--channel main\|demo_tg\|demo_wa] --output <fichero>` | Exporta los datos de un contacto a un fichero privado (derechos RGPD) |
| `export_tenant <slug> --output <fichero>` | Exporta todos los datos de un negocio a un fichero privado (derechos RGPD) |
| `forget_contact <slug> <external_id> [--channel ...]` | Borra los datos de un contacto |
| `purge_tenant <slug>` | Borra los datos de un negocio, con confirmación escribiendo el slug |
| `outbound_resolve <uuid> (--mark-sent\|--resend) --confirm` | Resuelve un envío ambiguo a mano; sin `--confirm` explica el riesgo y no hace nada |
| `job_retry <id>` | Reintenta un trabajo fallido idempotente a mano; rechaza los de envío (`send_message`, `send_notification`) |
