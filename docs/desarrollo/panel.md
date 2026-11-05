# Desarrollo del panel

Panel interno (`apps/panel/`: React, TypeScript, Vite, Biome, Vitest) que sustituye al
Django Admin ([ADR-008](../arquitectura/adr/ADR-008-panel.md)), resumido para quien
opera en [procedimientos/panel.md](../procedimientos/panel.md). Requiere Node 24 y
pnpm (`corepack enable`, que lee la versión fijada en `apps/panel/package.json`).

```bash
pnpm -C apps/panel install
make panel-dev           # Vite en modo desarrollo, proxy /api hacia el backend local
make panel-check         # Biome, tsc --noEmit, Vitest y el build de producción
```

`make api` regenera `apps/panel/openapi.json` (desde el backend) y
`apps/panel/src/api/schema.d.ts` (con `openapi-typescript`); `make fix` aplica
`ruff`/`biome --write` y deja ambos al día. En local, con `make up` y `make panel-dev`,
`http://localhost:5173` pide usuario, contraseña y código TOTP
(`manage.py panel_user create <usuario>`) y, tras entrar, ofrece Resumen, Clientes,
Actividad, Incidencias, Logs, Datos, Sistema, Auditoría y «Salir». En producción, el
contenedor `panel` (su propia Caddy, puerto 8080) solo es alcanzable por
`make panel-tunnel` (túnel SSH, ADR-008), nunca por el Caddy público.
