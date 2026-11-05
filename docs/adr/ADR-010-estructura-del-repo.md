# ADR-010 — Estructura del repositorio: `apps/` y `deploy/`

**Estado:** sustituida por [ADR-011](ADR-011-estructura-del-repo-v2.md)

## Contexto

Tras añadir el panel, la raíz del repositorio mezclaba dos apps desplegables (`src/` del
backend, `panel/` del frontend) con ficheros de despliegue sueltos (`Dockerfile`,
`Caddyfile`, `compose.yaml`, `compose.prod.yaml`) y una carpeta `deploy/` que solo tenía
parte de ese despliegue (scripts, `postgres/`, systemd). No había un criterio claro de
qué vivía en la raíz y qué en `deploy/`. Este ADR fija la organización del repo, sin
tocar los límites internos de `core/`/`integrations/`/`packs/` que ya vigila
`import-linter`.

## Decisión

- **Dos apps desplegables en `apps/`:** `apps/backend/` (todo lo que antes era `src/`:
  `autobot/`, `config/`, `core/`, `integrations/`, `packs/`, `tools/`) y `apps/panel/`
  (antes `panel/`, sin cambios internos). `manage.py` y `conftest.py` se quedan en la
  raíz como lanzadores finos; `PYTHONPATH`/`mypy_path`/`pytest.ini_options` apuntan a
  `apps/backend`.
- **`deploy/` reúne todo lo de despliegue que no se teclea a mano:** el `Dockerfile` del
  backend (`deploy/docker/backend.Dockerfile`) y el `Caddyfile` del borde público
  (`deploy/caddy/Caddyfile`), además de lo que ya tenía (`postgres/`, los scripts de
  `backup`/`restore`/`deploy`/`ensure-env`/`manage`/`bootstrap-server`/`ssh-deploy`, y los
  units de systemd). Dentro de un contenedor, las rutas internas (`/app/src`,
  `/etc/caddy/Caddyfile`) no cambian: solo cambia de dónde los copia el `Dockerfile` en
  el host.
- **`compose.yaml` y `compose.prod.yaml` se quedan en la raíz.** A diferencia del
  `Dockerfile` y el `Caddyfile`, los runbooks los usan tecleados a mano por SSH
  (`docker compose -p autobot -f compose.prod.yaml ...`) durante incidencias; moverlos
  obligaría a escribir una ruta más justo cuando menos conviene. Es la única excepción a
  "nada de despliegue suelto en la raíz".
- **`tests/` no se mueve.** Sigue en la raíz, cubre la plataforma entera (incluida
  `tests/integration/panel/`), y no se ha encontrado beneficio en anidarla bajo
  `apps/backend/`.

## Alternativas consideradas

- **Dejar `src/` y `panel/` como estaban, solo limpiar la raíz de infra suelta:** menor
  riesgo (no toca `pyproject.toml`, `manage.py`, Dockerfiles, CI, Makefile), pero no
  resuelve la falta de un agrupador visible de "esto es una app desplegable".
- **Mover también `compose.yaml`/`compose.prod.yaml` a `deploy/`:** más coherente con
  "todo el despliegue en un sitio", pero obliga a tocar más de diez runbooks que los
  invocan tecleados a mano; el coste de operación supera el beneficio estético.
- **Anidar `tests/` bajo `apps/backend/tests/`:** más "cada app es dueña de sus tests",
  pero `tests/` ya cubre piezas de más de una app (p. ej. `tests/integration/panel/`
  contra la API del backend) y no aporta claridad real.

## Consecuencias

- Cualquier ruta que antes empezaba por `src/` o `panel/` cambia a `apps/backend/` o
  `apps/panel/` (código, tests, `Makefile`, CI, docs). Verificado con `ruff`, `mypy`,
  `import-linter`, la suite completa de `pytest`, `pnpm check/typecheck/build` del panel,
  `manage.py check`/`makemigrations --check`/`lintmigrations`/`export_openapi`, y
  reconstruyendo ambas imágenes Docker y `make check-prod-config` contra `compose.prod.yaml`
  real.
- No hay servidor de producción desplegado todavía (`docs/puesta-en-marcha.md`), así que
  este cambio no afecta a ningún sistema real; la próxima vez que se prepare una VPS,
  `deploy/bootstrap-server.sh` y los runbooks ya reflejan la estructura nueva.
- `make restore-test` no se ha podido ejecutar en esta máquina (no tiene `restic`
  instalado); los scripts de `backup`/`restore`/`restore-test` se revisaron a mano y
  quedan con las rutas del `Caddyfile` actualizadas, pero conviene que la persona los
  ejecute una vez tenga `restic` a mano.

## Cuándo revisarla

- Si se añade una tercera app desplegable, confirmar que sigue encajando en `apps/`.
- Si se bootstrapea un servidor real y algo de `deploy/` no cuadra con lo que espera
  `bootstrap-server.sh`, corregir ahí antes que revertir esta estructura.
