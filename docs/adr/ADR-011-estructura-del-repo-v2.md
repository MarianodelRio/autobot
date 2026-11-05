# ADR-011 — Estructura del repositorio v2

**Estado:** aceptada · sustituye a [ADR-010](ADR-010-estructura-del-repo.md)

## Contexto

ADR-010 agrupó el código en `apps/` y el despliegue en `deploy/`, pero dejó varias cosas
a medias: `apps/backend/` no tenía su propio `pyproject.toml` ni `Dockerfile` (vivían en
la raíz y en `deploy/docker/`), por lo que no era autocontenido como `apps/panel/`;
`tests/` seguía en la raíz, repartido a la vez entre la raíz, `core/` y cada pack, sin
un criterio de carpetas por lo que prueban; `compose.yaml`/`compose.prod.yaml` se
quedaron deliberadamente en la raíz para que los runbooks los tecleasen cortos a mano; y
los ficheros de ejecución (`state/`, `backups/`, `qr/`, `revision/`, `datos/`,
`tenants/`, `.deployed-sha`...) estaban sueltos en la raíz, cada uno con su propia
entrada en `.gitignore`.

## Decisión

- **`apps/backend/` autocontenido, como `apps/panel/`:** `pyproject.toml`, `uv.lock`,
  `.python-version`, `manage.py`, `Dockerfile` y `.dockerignore` viven dentro de
  `apps/backend/`; el código de producción está en `apps/backend/src/` y los tests en
  `apps/backend/tests/`. Motivo: la raíz queda mínima (solo lo que de verdad es de todo
  el repo) y las dos apps desplegables se ven y se tratan igual.
- **Compose en `deploy/compose/`, con un fichero base y overrides:**
  `deploy/compose/compose.yaml` (lo común a local y producción: `db`, `victorialogs`, y
  los fragmentos compartidos de `web`/`worker`), `compose.local.yaml` (build local,
  montajes de código, passwords de desarrollo) y `compose.prod.yaml` (imágenes de GHCR,
  Caddy, políticas de reinicio). El `.env` fija `COMPOSE_FILE` con la lista de ficheros
  que corresponde a cada entorno y `COMPOSE_PROJECT_NAME=autobot`, así que
  `docker compose up` sigue siendo corto de teclear — la objeción de ADR-010 a mover
  estos ficheros («obliga a escribir una ruta más justo cuando menos conviene») ya no
  aplica con `COMPOSE_FILE` puesto, y todavía no hay ninguna VPS montada donde alguien
  tenga memorizados los comandos largos. Las rutas relativas de estos tres ficheros (los
  mounts, `../postgres`, `../caddy/Caddyfile`, `../../var/...`) se resuelven contra
  `deploy/compose/`, el directorio del primero que se pasa con `-f` — comprobado con
  Docker Compose 2.40, también para los overrides.
- **Tests en `apps/backend/tests/`, fuera de la imagen:** repartidos por lo que prueban
  (`core/`, `packs/<pack>/`, `platform/{channels,runtime,tenancy,owner,ops,panel}/`,
  `contract/`, `isolation/`, `tools/`, `repo/`, `fixtures/`), no por si son unitarios o
  de integración. `apps/backend/.dockerignore` excluye `tests/` explícitamente.
- **`var/` para los ficheros de ejecución, igual en local y en el servidor:**
  `var/state/`, `var/backups/`, `var/qr/`, `var/revision/`, `var/datos/<slug>/`,
  `var/tenants/` (solo local, de paso hacia `tenant_config import`),
  `var/google_sa.json`, `var/.deployed-sha` y el resto de ficheros de bloqueo/estado del
  despliegue. Una sola entrada `/var/` en `.gitignore` sustituye a las ocho o nueve
  sueltas que había antes.

## Alternativas consideradas

- **Compose base y overrides en la raíz (no en `deploy/compose/`):** evita el problema
  de resolución de rutas relativas, pero deja la raíz con tres ficheros de despliegue
  sueltos de nuevo, justo lo que esta ADR quiere evitar.
- **Tests junto a cada pack y cada app, sin una carpeta `tests/` común:** cada pieza
  dueña de sus propios tests, pero los tests de `platform/` cruzan varios módulos
  (`channels`, `runtime`, `tenancy`...) sin un dueño único, y separarlos de los de
  `packs/` habría obligado a duplicar fixtures compartidas (`tenants`, `salon_setup`) en
  vez de tener un único `conftest.py` común.

## Consecuencias

- Rutas del servidor: el checkout en `/srv/autobot` pasa a tener `deploy/scripts/`,
  `deploy/compose/`, `deploy/systemd/`, `deploy/env/` y `var/` en vez de los scripts y
  ficheros sueltos de antes. `deploy/scripts/bootstrap-server.sh` ya crea `var/` (y
  `var/state/{ops,caddy-data,caddy-config}`) con el dueño correcto, e instala los units
  desde `deploy/systemd/`. El comando forzado de la clave de CI pasa a
  `deploy/scripts/deploy.sh <sha>`.
- Los runbooks que citan rutas de servidor (`state/ops/...`, `deploy/backup.sh`,
  `google_sa.json`...) se actualizan a las rutas nuevas en la Fase 7 de la reorganización
  (`docs/`).
- No hay servidor de producción desplegado todavía, así que nada de esto afecta a un
  sistema real; se verificó con `docker compose config` en modo local y en modo
  producción (con variables de prueba), comparando los servicios resueltos antes y
  después, y con `make up`, `make dev-bootstrap` y `make check-prod-config` en local.
