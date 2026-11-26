# Entorno local

Cómo montar y usar el entorno de desarrollo: qué hay que tener instalado, qué hace `make local`, cuándo usar `make check` o `make test-fast` y cómo reproducir producción en el portátil. Léelo la primera vez que clones el repo. La lista completa de objetivos y comandos está en [Comandos](../referencia/comandos.md); aquí solo se explica cuándo usar cada uno.

## Requisitos

| Herramienta | Para qué | Versión |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | Backend, tests y herramientas | Instala Python 3.14 por su cuenta |
| Docker (con el plugin `compose` v2) y `curl` | `make local` levanta `db`, `web`, workers y logs | Un daemon accesible para tu usuario |
| Node 24 | Solo para el panel (`apps/panel/`) | La del `Dockerfile` del panel (`node:24-alpine`) |
| pnpm | Solo para el panel | Fijada en `packageManager` de `apps/panel/package.json`; se activa con `corepack enable` |

`install-local.sh` comprueba Docker, `docker compose` y `curl`, y se detiene si falta alguno. No comprueba Node ni pnpm: solo se necesitan si trabajas en el panel o ejecutas `make fix`, `make api` o `make panel-*`.

## Arranque

```bash
cd apps/backend && uv sync && cd -
make local
```

`make local` (alias `make dev-bootstrap`) ejecuta `deploy/scripts/install-local.sh` ([ADR-017](../arquitectura/adr/ADR-017-instalador-de-la-vm-y-entorno-local.md)). En orden:

1. Comprueba los requisitos y crea `.env` desde `.env.example` si falta, solo con valores locales y sin credenciales de terceros.
2. Levanta `db`, reaplica los roles de PostgreSQL y construye la imagen de `web`.
3. Aplica las migraciones como `fp_owner`, ejecuta `apply_grants` y siembra los negocios de demo (`seed_demos`).
4. Si no existe el usuario `panel`, pide crearlo (`panel_user create`). Sin terminal interactivo, lo deja anotado.
5. Levanta `web`, los cuatro workers (`worker-inbound`, `worker-calendar`, `worker-periodic` y `worker-outbound`) y `victorialogs`, y espera hasta 60 s a que `/health/internal` responda bien y los workers estén en marcha.

Se puede repetir sin miedo: conserva las versiones de configuración existentes y los cambios hechos en los demos. Cuando termina, `web` escucha en `http://127.0.0.1:8000`.

Las opciones del script se pasan con `ARGS=`:

```bash
make local ARGS=--check              # solo comprueba si web responde sana; no cambia nada
make local ARGS=--skip-panel-user    # no pregunta por el usuario del panel
```

`make dev-reset` pide escribir `RESET`, borra el volumen local de PostgreSQL y repite `make local`. Es lo único que destruye datos locales.

## Día a día

- `make up` reconstruye y levanta los servicios ya preparados; `make down` los para; `make status` los lista.
- `make logs SERVICE=worker-inbound` sigue los logs de un servicio (sin `SERVICE`, de todos). `make shell` abre una shell de Django en `web`.
- `make chat PACK=salon` o `PACK=bus` abre un chat por terminal con la plantilla de demo de un pack, sin canal real, sin BD y sin contenedores (`CHANNEL=telegram` aplica los límites de ese canal).
- `make tenant-health SLUG=<slug>` comprueba el pack y el canal de un negocio desde `web`; necesita las credenciales de los servicios que use.
- `make tenant-import DIR=<directorio> [SECRETS=<yaml>]` importa un negocio exportado contra la BD local.

La imagen local instala las dependencias de desarrollo (`INSTALL_DEV=true`); la de producción usa `--no-dev`. En local, `web` corre con gunicorn y `--reload`, con hilos acotados como en producción. Cada worker corre bajo `deploy/compose/dev-worker.py`: reinicia su proceso cuando cambia Python en `apps/backend/src/`, esperando a que termine lo que está haciendo, y si muere solo Docker lo relanza.

`.env` es opcional en local. Para usar Google Calendar, `GOOGLE_SERVICE_ACCOUNT_FILE` apunta al fichero de la cuenta de servicio, con ruta relativa a `deploy/compose/` (por convención `../../var/google_sa.json`). Vacío, monta `/dev/null` y no crea ninguna credencial. Las variables están en [Variables de entorno](../referencia/variables-entorno.md).

### Actividad falsa para el panel

`make dev-activity` crea actividad realista (mensajes, respuestas, avisos, incidencias abiertas, reabiertas y cerradas, envíos `unknown` y rechazados, un trabajo fallido y muestras de sistema) para ver el panel con datos. Se niega a ejecutarse fuera de `local`. El objetivo no admite argumentos; para cambiar los días o limpiar lo creado, ejecuta el comando directamente:

```bash
docker compose exec web python manage.py seed_dev_activity --days 7 --reset
```

## Calidad: `make check` o `make test-fast`

| Objetivo | Qué ejecuta | Necesita |
|---|---|---|
| `make check` | `ruff check`, `ruff format --check`, `mypy`, `lint-imports` y toda la suite de pytest | La BD local levantada (`make local`) |
| `make test` | Solo la suite completa de pytest | La BD local levantada |
| `make test-fast` | `pytest -m "not db"`: solo los tests que no tocan PostgreSQL | Nada, ni siquiera Docker |
| `make fix` | `ruff --fix`, `ruff format`, `biome --write` y `make api` | Node y pnpm |

Usa `make test-fast` mientras iteras y `make check` antes de dar un cambio por terminado: es lo que exige CI. Cómo se organizan los tests, en [Tests](tests.md). El frontend tiene su propia puerta, `make panel-check` ([Panel](panel.md)).

## QR público de un negocio

Se genera sin contenedores, credenciales ni red, a partir de un documento exportado:

```bash
uv run --project apps/backend python apps/backend/manage.py tenant_config export <slug> var/datos/<slug>
make qr FILE=var/datos/<slug>/document.yaml
make qr FILE=var/datos/<slug>/document.yaml ARGS="--output /ruta/qr.svg"
```

El canal debe declarar `display_phone` internacional (WhatsApp) o `bot_username` (Telegram). El QR apunta al canal del negocio y se guarda como SVG con fondo blanco, apto para imprimir. Lo generado en `var/qr/` no se sube a git. `var/tenants/` y `var/datos/` tampoco.

## Reproducir producción en local (`localprod`)

`make up` y `make local` son para desarrollar: código montado, gunicorn con recarga, sin Caddy ni TLS. Para probar tal cual los scripts que corren en el servidor (`deploy.sh`, `backup.sh`, `restore.sh`, con Caddy y TLS, `read_only` y tu UID real) existen los objetivos `localprod-*`:

```bash
make localprod-up       # construye las imágenes, las sube a un registro Docker local y despliega con el deploy.sh real
make localprod-backup   # backup.sh real contra restic en var/localprod/restic
make localprod-restore  # restore.sh real; pide confirmación y sustituye el volumen
make localprod-down     # para y borra los contenedores y el registro
```

Proyecto (`autobot-localprod`), puertos (8443 y 8081 de Caddy, 18000 de `web`, 18080 del panel) y volúmenes son distintos de los de `make up`, así que pueden estar levantados a la vez. `var/localprod/` guarda la copia de este checkout que despliega, incluidos los cambios sin commitear. `https://localhost:8443` usa el certificado interno de Caddy (`curl -k`).

!!! warning "Un `down` sin `SHA` puede borrar tu BD de desarrollo"
    Un `docker compose down` contra `compose.prod.yaml` sin `SHA` no aborta: resuelve el proyecto por `COMPOSE_PROJECT_NAME` de `.env` e ignora `--project-name`, así que un `down -v` puede borrar el volumen de la BD de desarrollo. `localprod.sh` fija siempre un `SHA` real antes de cualquier `down`; haz lo mismo si lo lanzas a mano.

Docker crea `var/state/{caddy-data,caddy-config,ops}` como `root` si no existen en el primer `up`. `localprod.sh` los crea antes, igual que `bootstrap-server.sh`.

## Dónde está el código

- `Makefile`: objetivos de desarrollo, calidad y `localprod-*`.
- `deploy/scripts/install-local.sh`: lo que hace `make local`.
- `deploy/scripts/localprod.sh`: el ensayo de producción en local.
- `deploy/compose/compose.yaml` y `compose.local.yaml`: servicios locales; `dev-worker.py`, el reinicio de workers.
- `apps/backend/src/tools/ops/qr.py`: el generador de QR.

## Relacionado

- [Comandos](../referencia/comandos.md) y [Variables de entorno](../referencia/variables-entorno.md).
- [Registro y configuración](../arquitectura/config-y-registro.md): cómo `web` y los workers cargan la configuración de los negocios desde PostgreSQL.
- [Tests](tests.md), [Panel](panel.md) y [Bot de demo en local](demo-local.md).
- [Servidor](../procedimientos/servidor.md): la puesta en marcha en producción.
