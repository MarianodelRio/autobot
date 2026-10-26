# FlowPilot

Plataforma de automatización para pequeños negocios: atiende a sus clientes por WhatsApp o Telegram, gestiona reservas sobre la agenda que ya usan (peluquerías) o responde consultas de horarios (autobuses) y avisa al dueño por Telegram.

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
uv sync          # dependencias, incluidas las de desarrollo
make check       # ruff, mypy, import-linter y pytest; los tests de BD necesitan `make up` (db en 127.0.0.1:5433)
```

Con Docker Compose (`db`, `web` y `worker`, con el código montado):

```bash
cp .env.example .env   # opcional en local: sin .env se usan los valores de desarrollo
make up                # construye la imagen y levanta los servicios; web en http://127.0.0.1:8000
make shell             # shell de Django dentro de web
make down
```

La primera vez que arranca, `db` crea los roles `fp_owner` y `fp_app` y la base de pruebas (`deploy/postgres/init-roles.sh`). Ese script solo se ejecuta con un volumen vacío; para empezar de cero: `docker compose down -v` (borra los datos locales). La base de pruebas se reutiliza entre ejecuciones y solo aplica migraciones nuevas: si editas una migración ya aplicada, reinicia el volumen igual.

`make status` muestra los servicios locales y `make logs SERVICE=worker` sigue sus logs
(sin `SERVICE`, los de todos los servicios). `make tenant-health SLUG=<slug>` comprueba
el negocio desde `web`; este último necesita las credenciales de los servicios que usa.

Para generar el QR público del negocio sin contenedores, credenciales ni acceso de red:

```bash
make qr SLUG=<slug>                         # qr/<slug>.svg
make qr SLUG=<slug> ARGS="--output /ruta/qr.svg"
# Equivalente: PYTHONPATH=src uv run python -m tools.qr <slug>
```

El canal debe declarar `display_phone` internacional (WhatsApp) o `bot_username`
(Telegram). El QR apunta al canal del negocio y se guarda como SVG con fondo blanco,
apto para imprimir. Los archivos de `qr/` son generados y no se suben a git.

### Bot de demo en local

Con un bot de Telegram de desarrollo propio, distinto del de producción (ver
[docs/puesta-en-marcha.md](docs/puesta-en-marcha.md)): pon su token en
`DEMO_TELEGRAM_TOKEN` y tu id de Telegram en `DEMO_TELEGRAM_USERS`, en `.env`, y después:

```bash
make up         # el worker procesa lo que llega; tras cambiar .env: docker compose up -d
make demo-up    # arranca también el poller de la puerta Telegram de demo (make demo-down la para)
```

En Telegram, escribe `/start` al bot: muestra los negocios de demo disponibles
(`demo-autobuses`, siempre; `demo-peluqueria` solo si está `active`). `make
telegram-poll SLUG=<slug>` hace lo mismo con el bot propio de un negocio (o sin
`SLUG`, con la puerta Telegram de demo, en primer plano). Un bot con webhook no
admite polling: `docker compose exec web python manage.py telegram_set_webhook
demo --delete` se lo quita (nunca a un bot que use el servidor).

La puerta WhatsApp de la demo solo funciona en el servidor: un número de Meta tiene una única URL de webhook, así que no hay equivalente local. Ver [docs/runbooks/demo.md](docs/runbooks/demo.md).
