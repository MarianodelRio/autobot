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
Incidencias, Logs, Datos, Sistema y «Salir». En producción, el
contenedor `panel` (su propia Caddy, puerto 8080) solo es alcanzable por
`make panel-tunnel` (túnel SSH, ADR-008), nunca por el Caddy público.

## Convenciones del código del panel

- Las claves de react-query viven en `src/lib/queries.ts` (`qk.*`), junto con los
  helpers de invalidación (`tenantChanged`, `tenantLifecycleChanged`, `tenantRemoved`) y
  las `queryOptions` compartidas (`tenantsQueryOptions`, `packsQueryOptions`,
  `packSchemaQueryOptions`). No se escriben claves literales en los componentes.
- Las mutaciones con aviso (toast de éxito, toast de error con el detalle del backend e
  invalidación) usan `useApiMutation` (`src/lib/use-api-mutation.ts`).
- La correspondencia entre estados del backend y niveles de `StatusDot` está en
  `src/lib/status-levels.ts`; un nivel desconocido se muestra como `unknown`.
- Los componentes de `src/components/ui/` son los de shadcn tal cual: no se podan sus
  exports sin uso para poder actualizarlos con el CLI.
- Vitest usa `pool: "vmThreads"` (un jsdom por worker, no por fichero); los tests que
  renderizan una ruta con carga diferida precargan la página en un `beforeAll`.
