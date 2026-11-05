# Autobot

Plataforma de automatización para pequeños negocios: atiende a sus clientes por
WhatsApp o Telegram, gestiona reservas sobre la agenda que ya usan (peluquerías) o
responde consultas de horarios (autobuses), y avisa al dueño por Telegram con un
resumen mensual. Una sola plataforma para 5–15 negocios, en una VPS con Docker Compose.

**Estado:** la plataforma está probada en local contra servicios reales (demo por
Telegram y WhatsApp, bot de avisos, panel, Google Calendar); nada está desplegado
todavía en producción. Pasos pendientes en [docs/puesta-en-marcha.md](docs/puesta-en-marcha.md).

## Arranque rápido

Requisito: [uv](https://docs.astral.sh/uv/) (instala Python 3.14 por su cuenta).

```bash
make dev-bootstrap   # db, roles, migraciones, permisos, demos, web y worker
make check           # ruff, mypy, import-linter y tests contra la BD local
make help             # todos los objetivos, por sección
```

Detalle en [docs/desarrollo/entorno-local.md](docs/desarrollo/entorno-local.md).

## Mapa del repo

```
apps/backend/   Backend Django (autocontenido: src/, tests/, pyproject.toml, Dockerfile)
apps/panel/     Panel interno (React, TypeScript, Vite)
deploy/         Compose por entorno, scripts de operación, systemd, Caddy, PostgreSQL
docs/           Documentación (ver docs/README.md)
var/            Ficheros de ejecución, ignorados por git (local y servidor)
CLAUDE.md       Reglas para trabajar en el repo
Makefile        Todos los comandos de desarrollo y operación (`make help`)
```

## Documentación

Índice completo por intención en [docs/README.md](docs/README.md). Reglas para
trabajar en el repo (idioma, forma de trabajo, arquitectura, reglas obligatorias):
[CLAUDE.md](CLAUDE.md).
