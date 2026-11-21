# Autobot

Plataforma de automatización para pequeños negocios: atiende a sus clientes por WhatsApp o Telegram, gestiona reservas sobre la agenda que ya usan (peluquerías) o responde consultas de horarios (autobuses), y avisa al dueño por Telegram. Una sola plataforma para 5-15 negocios, en una VPS con Docker Compose. Visión de conjunto en [docs/arquitectura/vision-general.md](docs/arquitectura/vision-general.md).

**Estado:** probada en local contra servicios reales (demo por Telegram y WhatsApp, bot de avisos, panel, Google Calendar); nada está desplegado todavía en producción. Pasos para ponerla en marcha en [docs/procedimientos/servidor.md](docs/procedimientos/servidor.md).

## Requisitos

- [uv](https://docs.astral.sh/uv/) (instala Python 3.14 por su cuenta).
- Docker con `compose` v2 y `curl`.
- Node 24 y pnpm (`corepack enable`), solo para trabajar en el panel.

## Arranque rápido

```bash
cd apps/backend && uv sync && cd -
make local     # entorno local completo: db, migraciones, demos, web y workers
make check     # ruff, mypy, import-linter y tests (necesita la BD local)
make docs      # documentación como sitio, en http://localhost:8100
make help      # todos los objetivos
```

## Mapa del repo

```
apps/backend/   Backend Django (src/, tests/, pyproject.toml, Dockerfile)
apps/panel/     Panel interno (React, TypeScript, Vite)
deploy/         Compose por entorno, scripts, systemd, Caddy, PostgreSQL
docs/           Documentación (docs/README.md); sitio con mkdocs.yml
var/            Ficheros de ejecución, ignorados por git
CLAUDE.md       Reglas para trabajar en el repo
```

## Documentación

Índice por intención en [docs/README.md](docs/README.md). Se publica como sitio con `make docs` (o `make docs-check` para validar enlaces) y, desplegado, el panel la sirve en `/docs/`. Reglas de trabajo: [CLAUDE.md](CLAUDE.md).
