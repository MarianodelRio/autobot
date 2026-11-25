# Comandos

Referencia única de los comandos `make` y `manage.py` del proyecto. Cada tarea que añade
o cambia un comando amplía esta tabla en el mismo commit.

## `make`

Las secciones siguen las del `Makefile` (`make help`). Las de desarrollo, calidad y documentación se
ejecutan en tu máquina; localprod ensaya la producción en local; las dos últimas operan
sobre el servidor de producción (instalación dentro de la VM, el resto por SSH o GitHub).

### Ayuda

| Comando | Qué hace |
|---|---|
| `make help` | Lista los objetivos por sección (Ayuda, Desarrollo, Calidad, Documentación, Panel, Negocios, Bus, Entorno local completo, Instalación y traslado, Producción); objetivo por defecto |

### Desarrollo

| Comando | Qué hace |
|---|---|
| `make up` | Construye y levanta los contenedores de desarrollo (`docker compose up -d --build`) |
| `make local` | Un solo comando para dejar todo el entorno local funcionando, desde cero o desde un estado previo y sin borrar datos (`deploy/scripts/install-local.sh`, ADR-017): comprueba requisitos, crea `.env` desde `.env.example` si falta, levanta db, roles, build, migra, `apply_grants`, `seed_demos`, crea el usuario del panel (si hay terminal) y levanta web/workers comprobando su salud; opciones `--check` y `--skip-panel-user`, que se pasan con `ARGS` (`make local ARGS="--check"`) |
| `make dev-bootstrap` | Alias de `make local` |
| `make dev-reset` | Exige escribir `RESET`, elimina el volumen local y repite `make local` |
| `make tenant-import DIR=<dir> [SECRETS=<yaml>]` | Importa un directorio contra la BD local desde el host; acepta rutas con espacios |
| `make dev-activity` | `manage.py seed_dev_activity`: actividad falsa y realista (mensajes, respuestas, avisos, alertas abiertas y resueltas, un `unknown`, un trabajo fallido y muestras de sistema) para ver el panel con datos; se niega fuera de `local` |
| `make ngrok` | Abre el túnel al puerto 8000 con tu dominio reservado de ngrok |
| `make down` | Para los contenedores |
| `make status` | `docker compose ps` |
| `make db-roles` | Ejecuta `init-roles.sh` dentro del contenedor `db`: crea `fp_owner`, `fp_app` y `fp_readonly`, o actualiza sus contraseñas, timeouts y `CONNECT`, sin recrear el contenedor; los permisos de tablas los aplica solo `manage.py apply_grants` (ejecútalo después) |
| `make logs SERVICE=<servicio>` | Sigue los logs de un servicio (`docker compose logs --tail=100 --follow`) |
| `make shell` | Abre una shell de Django dentro de `web` |
| `make telegram-poll SLUG=<slug>` | *Long polling* del bot de Telegram de un tenant (o `notify`), para desarrollo local sin webhook |
| `make chat PACK=salon\|bus [CHANNEL=telegram]` | Chat de prueba por terminal con la plantilla de demo de un pack; sin canal real, BD ni contenedores |

### Calidad

| Comando | Qué hace |
|---|---|
| `make test` | `uv run pytest` |
| `make test-fast` | `pytest -m "not db"`, sin base de datos levantada |
| `make check-prod-config` | Ejecuta `apps/backend/src/tools/ops/check_prod_config.py`: prueba el allowlist de Caddy contra un *upstream* local y el endurecimiento del compose de producción (credenciales por servicio, capacidades, redes) |
| `make check` | Puerta de calidad del backend: `ruff check`, `ruff format --check`, `mypy`, `import-linter`, `pytest` |
| `make fix` | `ruff check --fix` y `ruff format` en el backend, `biome check --write` en `apps/panel/`, y `make api` |
| `make api` | Regenera `apps/panel/openapi.json` (esquema de la API del panel) y `apps/panel/src/api/schema.d.ts` (tipos TypeScript) |

### Documentación

| Comando | Qué hace |
|---|---|
| `make docs` | Sirve este sitio en local con Zensical (`mkdocs.yml`), con recarga al editar |
| `make docs-check` | Construye el sitio en modo estricto: un enlace roto o una página que falta falla. Se ejecuta en CI |

### Panel

| Comando | Qué hace |
|---|---|
| `make panel-dev` | `pnpm -C apps/panel dev`: Vite en modo desarrollo, con proxy `/api` hacia el backend local |
| `make panel-check` | Puerta de calidad del frontend: `biome check`, `tsc -b --noEmit`, `vitest run` y el build de producción |
| `make panel-tunnel [HOST=<servidor>]` | Túnel SSH al puerto del contenedor `panel` en producción (8080→18000 local); nunca a `web` directamente |

### Negocios

| Comando | Qué hace |
|---|---|
| `make tenant-health SLUG=<slug>` | `tenant_health`: comprueba y persiste la salud del pack y del canal |
| `make qr FILE=<document.yaml> [ARGS="..."]` | Genera el QR a partir de un documento exportado, en la máquina del desarrollador, sin secretos |
| `make tenant-push SLUG=<slug> [SECRETS=<yaml>]` | Exporta la BD local y la importa por SSH. El YAML privado aporta solo la entrada del slug; el temporal se borra al salir |

### Bus

| Comando | Qué hace |
|---|---|
| `make bus-bajar NOMBRE=<nombre> [DIR=<dir>] [VERSION=<n>] [PROD=1]` | ADR-013: descarga esa entrada de la biblioteca a `var/datos/<nombre>/timetable` y `.publicado/timetable`; sin `VERSION`, la vigente |
| `make bus-validar NOMBRE=<nombre>` | Valida `var/datos/<nombre>/timetable` |
| `make bus-formatear NOMBRE=<nombre>` | Realinea las columnas de las tablas de horarios sobre `var/datos/<nombre>/timetable`, sin cambiar los datos |
| `make bus-revision NOMBRE=<nombre> [ARGS="..."]` | Genera HTML/PDF comparando con `.publicado/timetable`; `ARGS="--base <dir>"` elige otra base |
| `make bus-subir NOMBRE=<nombre> [DIR=<dir>] COMMENT="..." [PROD=1]` | ADR-013: valida, prueba sin escribir y sube `var/datos/<nombre>/timetable` (o `DIR`) a la biblioteca, rechazando si otra persona subió antes (`--base-sha`, resuelto solo); nunca toca a ningún cliente |

### Entorno local completo (localprod)

| Comando | Qué hace |
|---|---|
| `make localprod-up` | Reproduce producción en local (Caddy con TLS, `deploy.sh` real, registro Docker local), proyecto `autobot-localprod` aparte de `make up` |
| `make localprod-backup` | `backup.sh` real contra un repositorio restic en `var/localprod/restic` |
| `make localprod-restore` | `restore.sh` real; reemplaza el volumen de BD de `localprod` |
| `make localprod-down` | Para y borra los contenedores y el registro local de `localprod` |

### Instalación y traslado

| Comando | Qué hace |
|---|---|
| `make install-vm [ARGS="..."]` | Se ejecuta **dentro de la VM**: `sudo deploy/scripts/install-vm.sh` (ADR-017). Instala/repara de forma idempotente: clave de CI, paquetes y Docker, cuentas, `.env`, primer despliegue, salud, endurecimiento de SSH y marcador `bootstrap-complete`; `--only`/`--skip PASO`, `--check`, `--restore-target`, `--public-host`, `--google-sa`, `--env-file`, `--rotate-ci-key`, `--yes` |
| `make server-migrate FROM= TO= [ONLY=paso]` | Traslada el despliegue de `FROM` a `TO` (ADR-012); `TO` ya debe tener `install-vm.sh --restore-target` ejecutado; exige `FROM` ≠ `TO` y un destino sin despliegue |

### Producción

| Comando | Qué hace |
|---|---|
| `make deploy [SHA=]` | Sin `SHA`, usa `origin/main`; comprueba con `gh` que su CI está en verde y lanza el workflow de despliegue |
| `make rollback` | Lee del servidor el `previous` del último despliegue correcto y, con confirmación, ejecuta `make deploy SHA=<previous>`; se niega a encadenar un segundo rollback sobre el SHA roto |
| `make backup-now` | Ejecuta `deploy/scripts/backup.sh` en el servidor por SSH |
| `make backup-prune [ARGS="--dry-run"]` | Ejecuta `deploy/scripts/backup-prune.sh` **en tu máquina** (nunca en el servidor): caduca los snapshots viejos con una credencial con permiso de borrado que no vive en el servidor (ADR-021; ver [backups](../procedimientos/backups.md)) |
| `make restore-test` | `bash deploy/scripts/restore-test.sh`: simulacro de restauración |
| `make prod-manage CMD="..." [TTY=1]` | Ejecuta el comando con la imagen desplegada mediante SSH; `TTY=1` para comandos interactivos, sin TTY para streams binarios |
| `make prod-compose ARGS="..." [TTY=1]` | Ejecuta un comando de `docker compose` (p. ej. `exec`, `logs`) contra el servidor por SSH, con `SHA` y `--env-file` ya puestos |

Los objetivos con opciones libres (`make local`, `make install-vm`, `make qr`, `make bus-revision`, `make prod-compose`) las reciben en `ARGS="..."`; `make` no pasa `--flags` sueltos. `HOST ?= autobot` usa el alias de `~/.ssh/config`; se puede sobrescribir en cada
comando. `NGROK_DOMAIN` no tiene valor por defecto: `make ngrok` lo lee de `.env` y
también se puede pasar en la línea de comandos.

## `manage.py`

| Comando | Qué hace |
|---|---|
| `chat <pack> [--channel whatsapp\|telegram]` | Chat de prueba por terminal con la plantilla de demo de un pack, sin canal real ni BD; lo usa `make chat` |
| `migrate` | El `migrate` de Django, pero corre por defecto sobre el alias `owner` (`fp_app` no puede hacer DDL) |
| `apply_grants` | Reaplica los permisos deseados de PostgreSQL (`autobot/db/grants.py`); se ejecuta tras `migrate`, en cada despliegue y tras cada restauración |
| `tenant_health <slug>` | Comprueba la salud del pack y del canal de un negocio, forzando la comprobación |
| `telegram_set_webhook <target> [--delete]` | Fija o borra el webhook de Telegram de un tenant, del bot de demo (`demo`) o del bot de avisos (`notify`) |
| `telegram_poll [<slug>]` | *Long polling* de un bot de Telegram (desarrollo local) |
| `owner_invite <slug>` | Genera un enlace de un solo uso para que el dueño del negocio enlace su Telegram |
| `owner_unlink <slug>` | Desconecta el Telegram del dueño del negocio |
| `contact_export <slug> <external_id> [--channel main\|demo_tg\|demo_wa] --output <fichero>` | Exporta los datos de un contacto a un fichero privado (si pide sus datos) |
| `tenant_data_export <slug> --output <fichero>` | Exporta todos los datos de un negocio a un fichero privado (al darlo de baja) |
| `contact_forget <slug> <external_id> [--channel ...]` | Borra los datos de un contacto |
| `tenant_purge <slug>` | Solo tras la baja: borra todo lo que el sistema guarda del negocio, incluida su fila y su slug (que queda libre); exige escribir el slug |
| `privacy_ledger_export` | Imprime el libro de supresiones (JSON lines, sin datos personales). `backup.sh` ya lo sube cada hora a restic (ADR-025); la exportación manual es una copia opcional |
| `privacy_reapply [--ledger FICHERO]` | Tras restaurar: vuelve a aplicar los olvidos y purgas del libro (tabla + fichero, o `--ledger -` por stdin); idempotente |
| `outbound_resolve <uuid> (--mark-sent\|--resend\|--discard) --confirm` | Resuelve un envío ambiguo a mano (marcarlo enviado, reenviarlo o descartarlo, que es definitivo); sin `--confirm` explica el riesgo y no hace nada |
| `job_retry <id>` | Reintenta un trabajo fallido idempotente a mano; rechaza los de envío (`send_message`, `send_notification`) |
| `tenant_secrets_reencrypt` | Recifra todos los secretos de canal con la primera clave de `SECRETS_ENCRYPTION_KEY`, atómicamente y con auditoría; ver [rotación](../procedimientos/rotar-secretos.md) |
| `tenant_config export <slug> <dir\|->` | Exporta documento y datasets vigentes, sin secretos; el directorio debe estar vacío o ser nuevo. Con `-`, tar.gz por stdout y diagnósticos por stderr |
| `tenant_config import <dir\|-> [--secrets <yaml>] [--comment "..."]` | Crea o publica desde un directorio o tar.gz por stdin. Valida documento, datasets y secretos juntos en una transacción. Admite `secrets.yaml` en la raíz del tar |
| `tenant_config validate --all` | Valida todos los documentos vigentes; sale con error si alguno es ilegible, inválido, degradado o ambiguo |
| `dataset_library push <pack> <dataset> <nombre> <dir\|-> --comment "..." [--base-sha <sha>] [--dry-run]` | ADR-013: valida con el pack (`Pack.dataset_summary`) y sube una versión a la biblioteca, independiente de cualquier cliente; `--dry-run` no escribe |
| `dataset_library pull <pack> <dataset> <nombre> <dir\|-> [--version <n>]` | Descarga esa entrada (vigente, o `--version`) a un directorio vacío o tar.gz, sin secretos |
| `dataset_library list <pack> <dataset>` | Lista, en JSON, la última versión de cada entrada de la biblioteca (nombre, versión, resumen, autor), nunca su contenido |
| `dataset_library current-sha <pack> <dataset> <nombre>` | Imprime el `sha256` vigente de esa entrada, o nada si no existe; para construir `--base-sha` |
| `seed_demos` | Crea los demos de las plantillas solo si no tienen versiones; conserva los cambios posteriores |
| `seed_dev_activity [--days N] [--reset]` | Crea actividad falsa en local (mensajes, avisos, alertas, un trabajo fallido, muestras de sistema); sin `--days`, los transcurridos del mes en curso. Con `--reset`, borra antes lo que creó. Se niega fuera de `local` |
| `tenant_status <slug> pause\|resume\|offboard` | Cambia el estado y crea una versión auditada; la baja exige escribir exactamente el slug |
| `panel_user create <usuario>` | Crea el usuario único del panel: contraseña (dos veces, con los validadores de Django) y un TOTP confirmado; muestra la URI `otpauth://` y su QR en ASCII una sola vez |
| `panel_user reset-totp <usuario>` | Sustituye el dispositivo TOTP; lo muestra una sola vez |
| `panel_user set-password <usuario>` | Cambia la contraseña del usuario del panel |
| `panel_user exists <usuario>` | Sale con código 0 si existe, 1 si no; lo usa `make local` |
| `export_openapi <ruta>` | Escribe el esquema OpenAPI de la API del panel; lo usa `make api` |
