# Autobot

Plataforma de automatización para pequeños negocios: atiende a sus clientes por WhatsApp o Telegram, gestiona reservas sobre la agenda que ya usan (peluquerías) o responde consultas de horarios (autobuses) y avisa al dueño por Telegram.

Cada dueño tiene además un asistente en ese mismo bot de Telegram. Le manda los avisos y un resumen mensual (citas, ingresos estimados, clientes atendidos, mensajes y coste aproximado de WhatsApp), y con un menú puede pedir cómo va el mes o el contacto de soporte. El dueño se conecta con un enlace de un solo uso (`manage.py owner_invite <slug>`); ver [ADR-007](docs/adr/ADR-007-bot-de-duenos.md).

Una sola plataforma para 5–15 negocios, en una VPS con Docker Compose.

Cada negocio usa un **pack** con su lógica: `salon` (pedir, ver, mover y cancelar citas sobre Google Calendar, recordatorios y avisos al dueño) o `bus` (consulta de horarios origen → destino → día). Un bot de demo, por Telegram y por WhatsApp, enseña cada pack con negocios de demostración propios, sin tocar el canal real de ningún cliente.

**Estado:** la plataforma y los dos packs están implementados y probados con simulaciones; aún no se ha probado nada contra servicios reales. Los pasos pendientes están en [docs/puesta-en-marcha.md](docs/puesta-en-marcha.md).

## Documentación

- Reglas para trabajar en el repo: [CLAUDE.md](CLAUDE.md).
- Decisiones de arquitectura: [docs/adr/](docs/adr/).
- Configuración de cada pack: [docs/packs/](docs/packs/).
- Operación (alta y baja de negocios, servidor, incidencias, retención): [docs/runbooks/](docs/runbooks/).

## Desarrollo local

Requisitos: [uv](https://docs.astral.sh/uv/) (instala Python 3.14 por su cuenta).

```bash
uv sync
make dev-bootstrap     # db, roles, migraciones, permisos, demos, web y worker
make check             # ruff, mypy, import-linter y tests contra la BD local
```

`web` escucha en `http://127.0.0.1:8000`. `make up` reconstruye y levanta los servicios
ya preparados; `make down` los para y `make shell` abre Django en `web`.
`make dev-bootstrap` se puede repetir: conserva las versiones existentes y los cambios
de los demos. `make dev-reset` exige escribir `RESET`, borra el volumen local y repite
el bootstrap, incluida la creación de la base de pruebas.

La imagen local instala las dependencias de desarrollo (`INSTALL_DEV=true`); la de
producción mantiene `--no-dev`. El worker usa `watchfiles` y reinicia su proceso al
cambiar Python en `src/`, respetando el cierre del worker antes de sustituirlo.
En local, `.env` es opcional. Si se necesita Calendar, `GOOGLE_SERVICE_ACCOUNT_FILE`
apunta al fichero local de la cuenta de servicio; vacío monta `/dev/null` y no crea
ninguna credencial. Los secretos de los canales se importan cifrados a la BD.

Para importar un negocio: `make tenant-import DIR=<directorio> SECRETS=<yaml-privado>`
(`SECRETS` es opcional). `HOST` usa por defecto el alias SSH `autobot` de
`~/.ssh/config`; se puede cambiar con `HOST=<servidor>`.

`make status` muestra los servicios locales y `make logs SERVICE=worker` sigue sus logs
(sin `SERVICE`, los de todos los servicios). `make tenant-health SLUG=<slug>` comprueba
el negocio desde `web`; este último necesita las credenciales de los servicios que usa.

Para generar el QR público del negocio sin contenedores, credenciales ni acceso de red:

```bash
uv run python manage.py tenant_config export <slug> datos/<slug>
make qr FILE=datos/<slug>/document.yaml
make qr FILE=datos/<slug>/document.yaml ARGS="--output /ruta/qr.svg"
# Equivalente: PYTHONPATH=src uv run python -m tools.qr datos/<slug>/document.yaml
```

El canal debe declarar `display_phone` internacional (WhatsApp) o `bot_username`
(Telegram). El QR apunta al canal del negocio y se guarda como SVG con fondo blanco,
apto para imprimir. Los archivos de `qr/` son generados y no se suben a git.

### Bot de demo en local

Con un bot de Telegram de desarrollo propio, distinto del de producción, y un túnel
de [ngrok](https://ngrok.com) hacia `web` (mismo mecanismo que producción: webhook,
no polling). Ver el detalle en [docs/runbooks/demo.md](docs/runbooks/demo.md).

```bash
make ngrok                                                  # dominio reservado
# en .env: PUBLIC_URL=<esa URL>, DEMO_TELEGRAM_TOKEN, DEMO_TELEGRAM_USERS,
# DEMO_TELEGRAM_WEBHOOK_SECRET (p. ej. `openssl rand -hex 32`)
make up && docker compose restart web worker
docker compose exec web python manage.py telegram_set_webhook demo
```

En Telegram, escribe `/start` al bot: muestra los negocios de demo disponibles
(`demo-autobuses`, siempre; `demo-peluqueria` solo si está `active`).

Para un bot sin webhook (p. ej. grabar fixtures de un negocio real antes de darlo de
alta), `make telegram-poll SLUG=<slug>` sigue disponible; un bot con webhook no
admite polling a la vez (`docker compose exec web python manage.py
telegram_set_webhook demo --delete` se lo quita, nunca a un bot que use el servidor).

El registro de web y worker ya se carga desde las versiones de PostgreSQL. Consulta
`config_revision` como máximo cada dos segundos y recarga cuando cambia; cada petición
y trabajo conserva el mismo registro durante su ejecución. Un fallo al comprobar la
revisión mantiene el último registro válido; `/health` responde 503 si no puede hacer
la primera carga.

La configuración y los secretos de negocio ya no se copian del repositorio ni se
montan desde un YAML. `tenant_config import/export/validate`, `tenant_dataset`,
`seed_demos` y `tenant_status` gestionan las versiones en PostgreSQL; ver
[comandos](docs/comandos.md). La publicación no requiere commits ni reinicios.

Para el QR, exporta primero `document.yaml` y ejecuta `make qr FILE=<ruta/document.yaml>`.
Las acciones de producción se ejecutan con `make prod-manage HOST=<servidor> CMD="..."`;
`TTY=1` permite confirmaciones interactivas. `make tenant-push HOST=<servidor> SLUG=<slug>`
transfiere el documento y los datasets de la BD local por SSH; `SECRETS=<yaml-privado>`
añade solo los secretos del slug seleccionado al tar temporal. Los exports ordinarios
no incluyen secretos. Nunca se versionan `tenants/` ni `datos/`.
