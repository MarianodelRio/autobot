# ADR-018 — Documentación como sitio dentro del panel

**Estado:** aceptada

## Contexto

La documentación vive en `docs/` como Markdown y solo se lee en GitHub o en el editor. Quien
opera el panel no la tiene a mano cuando salta una alerta, y el repo no se puede navegar
como un sitio (búsqueda, navegación por secciones, diagramas). Se quiere que se lea
entera, que cada pantalla del panel enlace a su procedimiento y que cada alerta apunte a su
runbook.

Restricciones que ya existen: el panel solo es accesible por túnel SSH y con sesión
([ADR-008](ADR-008-panel.md)); el Caddy público (`deploy/caddy/`) no sirve nada del panel;
la imagen del panel corre sin root y con el filesystem de solo lectura.

## Decisión

- **Generador: Zensical 0.1.3**, que lee `mkdocs.yml` (compatible con MkDocs, tema Material).
  Se fija en el grupo `docs` de `apps/backend/pyproject.toml` y `uv.lock`. `make docs` sirve
  el sitio en local y `make docs-check` lo construye en modo estricto (un enlace o un
  snippet roto falla). El job `docs` de CI hace lo mismo y `image` depende de él.
- **Dónde se sirve:** en el contenedor `panel`, bajo `/docs/`. El `Dockerfile` del panel
  tiene una etapa `docs` que construye el sitio y lo copia a `/srv/docs`. Sigue siendo
  accesible solo por el túnel del panel; no se añade ninguna ruta al Caddy público.
- **Sesión:** `handle /docs/*` usa `forward_auth` hacia `web:8000`, endpoint
  `/api/panel/auth/me` (el mismo `PanelAuth` que toda la API: sesión de personal con TOTP
  verificado). Con 401/403 redirige a `/login`; con otro error (p. ej. `web` caído) se
  devuelve ese error, sin servir nada. `/docs` redirige a `/docs/`.
- **CSP propia de `/docs/*`:** `default-src 'self'`, sin CDN (Mermaid y las fuentes van
  vendorizados en el sitio), `worker-src 'self' blob:` para la búsqueda y
  `frame-ancestors 'none'`. `script-src` lleva `'unsafe-inline'` solo en esa ruta: cada
  página trae unos tres `<script>` inline (tema, base de URLs, configuración) cuyo hash
  cambia con la profundidad de la página (59 páginas, 5 variantes hoy), así que una lista
  de hashes `sha256` se rompería con cada página nueva. El resto del panel mantiene su CSP
  sin `script-src` inline.
- **Contexto de build = raíz del repo:** el sitio necesita `docs/`, `mkdocs.yml` y el código
  que incrustan los snippets. La imagen se construye con
  `docker build -f apps/panel/Dockerfile .` (CI, `compose.local.yaml`, `localprod.sh`).
  `apps/panel/Dockerfile.dockerignore` (y un `.dockerignore` raíz equivalente, para el
  builder sin BuildKit) deja entrar solo `apps/panel/`, `docs/`, `mkdocs.yml`,
  `apps/backend/src/` y el `pyproject.toml`/`uv.lock` del backend. Nunca `.env`, `var/`,
  `.git`, `node_modules` ni `.venv`.
- **Entrada «Docs» en el panel:** enlace normal `<a href="/docs/">` en una pestaña nueva
  (no una ruta de TanStack). En desarrollo (`make panel-dev`), Vite hace proxy de `/docs`
  a `make docs` (`localhost:8100`), que también sirve bajo `/docs/`.
- **Ayuda contextual:** `HelpLink` («?») en la cabecera de cada pantalla (prop `help` de
  `PageHeader`) enlaza a la página de procedimiento de esa pantalla.
- **Runbooks:** `autobot/ops/runbooks.py` mapea cada clave de alerta (exacta o por prefijo)
  a una página de `docs/incidencias/` o `docs/procedimientos/`. La API de alertas devuelve
  `runbook` (URL `/docs/...`) y la fila de la incidencia muestra «Ver runbook». Un test
  recorre el código de `ops/check.py` y `ops/containers.py` y falla si una clave nueva no
  tiene runbook ni está marcada como sin él, o si el fichero destino no existe.

## Alternativas consideradas

- **MkDocs Material:** entra en mantenimiento desde noviembre de 2026; empezar ahí es
  heredar una herramienta congelada. Zensical es su continuación y lee el mismo
  `mkdocs.yml`, así que mudarse no cuesta nada.
- **Starlight (Astro):** buena opción, pero añade una segunda cadena de Node al sitio de
  docs y no lee `mkdocs.yml`. Es la alternativa si Zensical se estanca.
- **Iframe del sitio dentro del panel:** obliga a relajar `X-Frame-Options DENY` y
  `frame-ancestors 'none'` del panel, y duplica navegación y tema. Un enlace en pestaña
  nueva da lo mismo sin tocar esas cabeceras.
- **Renderizar el Markdown de forma nativa en React:** habría que reimplementar
  admonitions, tabs, snippets, búsqueda y Mermaid. Queda como posible fase futura si se
  quiere integrar el tema y la búsqueda con el panel.
- **Hashes `sha256` de los scripts inline:** descartados por inestables (ver CSP).
- **Servirlo desde el Caddy público o un contenedor aparte:** amplía la superficie pública
  o añade un servicio por una web estática; el contenedor del panel ya tiene sesión y
  túnel.

## Consecuencias

- La imagen del panel crece con el sitio y su build tarda más; la etapa `docs` va en caché
  de capas mientras no cambien `docs/`, `mkdocs.yml` o `apps/backend/src/`.
- Una página mal enlazada rompe CI, no solo el sitio.
- `/docs/` depende de que `web` responda: con `web` caído, la documentación tampoco se
  puede leer desde el panel (el Markdown sigue en el repo).
- Cada clave de alerta nueva obliga a decidir su runbook.
- `'unsafe-inline'` en `script-src` de `/docs/*` es una concesión acotada: el contenido
  del sitio sale del repo y de la imagen, no de datos de clientes.

## Cuándo revisarla

- Si Zensical deja de mantenerse o no soporta una extensión que necesitemos: pasar a
  Starlight.
- Si el sitio emite scripts inline estables (o con nonce): cambiar `'unsafe-inline'` por
  hashes o nonces.
- Si se quiere búsqueda o tema unificados con el panel: valorar el render nativo en React.
- Si el panel deja de ir solo por túnel SSH: replantear quién puede leer `/docs/`.
