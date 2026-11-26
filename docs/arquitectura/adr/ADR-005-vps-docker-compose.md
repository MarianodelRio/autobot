# ADR-005 — Una VPS con Docker Compose

**Estado:** vigente; ampliado por [ADR-020](ADR-020-api-del-panel-aparte.md) (contenedor `web-panel`, redes separadas y contenedores endurecidos), por [ADR-021](ADR-021-backups-resistentes.md) (backups horarios) y por [ADR-023](ADR-023-colas-aisladas-y-degradacion.md) (cuatro workers: `worker-calendar` y `worker-periodic` aparte). Proveedor fijado y en producción desde 2026-11-24 (ver «Proveedor y tamaño»)

## Contexto

La plataforma atiende a 5–10 negocios (15 como máximo previsto), con picos de pocos mensajes por segundo, y la opera una persona. El objetivo de coste de infraestructura es de unos 20 €/mes, sin contar las APIs.

## Decisión

- **Una VPS en la UE** (Hetzner Cloud) con Ubuntu 24.04 y **Docker Compose**: `caddy`, `web`, `web-panel`, los cuatro workers (`worker-inbound`, `worker-calendar`, `worker-periodic`, `worker-outbound`), `db` (PostgreSQL 18), `panel` y `victorialogs`; la lista de referencia está en [visión general](../vision-general.md#contenedores). `web`, `web-panel` y los `worker-*` usan la misma imagen; `panel` y `victorialogs` solo son accesibles por túnel SSH. (Historia: el 2026-11-11 se pasó de un worker a dos por grupos de colas, y el ADR-023 los llevó a cuatro.)
- **Caddy** con HTTPS automático; solo expone los webhooks de WhatsApp y Telegram (incluidos los de las dos puertas del bot de demo y el bot de avisos, `/webhooks/telegram-notify`) y `/health`.
- **Secretos**: `.env` (plataforma) en el servidor, montado de solo lectura; los secretos de canal de cada negocio viven cifrados en PostgreSQL (`SECRETS_ENCRYPTION_KEY` en `.env`). Nunca en git ni en la imagen.
- **Backups**: `pg_dump` cada hora (ADR-021), `.env` sin la clave de cifrado, `google_sa.json`, el `Caddyfile` y `.deployed-sha` (todos bajo `var/`), cifrados con restic, a almacenamiento de **otro proveedor** en la UE; simulacro de restauración trimestral. RPO 1 h; objetivo de RTO ≤ 2 h, pendiente de medir en el simulacro ([backups](../../procedimientos/backups.md#rpo-y-rto)).
- **Despliegue**: imagen en GHCR desde GitHub Actions; despliegue manual por SSH con migraciones primero, comprobación de salud y vuelta atrás automática.
- **Vigilancia que no depende de la VPS**: latido a healthchecks.io y uptime externo.
- **Vigilancia de contenedores**: un timer del host escribe cada minuto una instantánea en lista blanca (`var/state/ops/containers.json`) que leen `ops_check` y el panel; ningún contenedor accede al socket de Docker.

## Alternativas consideradas

- **Nube gestionada (contenedores gestionados + base de datos gestionada + balanceador)**: escalable y con alta disponibilidad, pero varias veces más cara y con muchas más piezas que operar para esta escala.
- **PaaS (Render, Fly, Railway)**: menos operación, pero el coste por servicio (web, worker, BD) supera el objetivo.
- **Kubernetes**: sin sentido a esta escala.

## Consecuencias

- Coste de infraestructura de ~6–11 €/mes.
- Sin alta disponibilidad: un fallo de la VPS supone una caída hasta restaurar (los proveedores reintentan los webhooks). Aceptado.
- Parches del sistema, cortafuegos y backups son responsabilidad nuestra: automatizados y vigilados.
- Nada depende del proveedor: cambiar de VPS es una restauración.

## Proveedor y tamaño (2026-11)

- **Proveedor:** Hetzner Cloud, centro de datos en la UE. Los backups van a un bucket S3 de
  otro proveedor, también en la UE (ADR-021). El 2026-11-09 se compararon OVHcloud VPS-1
  (3,81 EUR/mes), Hetzner CX23 (5,99 EUR/mes) y netcup VPS 500 (8,26 EUR/mes con 12 meses);
  como nada depende del proveedor, cambiarlo es una restauración (ADR-012).
- **Tamaño de arranque: 2 vCPU y 4 GB, con 2 GB de swap** (2026-11-24). Las máquinas
  mayores no tenían stock o habían subido mucho de precio. La prueba de carga en
  `localprod` dio un pico de ~1,15 GiB entre todos los contenedores con 5 negocios y 1.500
  mensajes, así que basta para los negocios de demo y un negocio en pruebas. Los
  `mem_limit` de `compose.prod.yaml` suman 5,76 GB: son topes, no reservas, y en esta
  máquina no se pueden alcanzar todos a la vez.
- **Antes del primer cliente real se amplía a 4 vCPU y 8 GB** (Rescale del proveedor, sin
  reinstalar), el tamaño para el que están calculados los `mem_limit` y el ajuste de
  PostgreSQL ([capacidad y crecimiento](../capacidad-y-crecimiento.md#servidor-y-proveedor)).
  También si antes salta `memory_high` (memoria por encima del 90 % de forma sostenida) o
  el swap se usa de forma habitual.
- **Terraform descartado:** un script por SSH sirve en cualquier proveedor sin añadir otra
  herramienta que mantener.

## Cuándo revisarla

- Más de 15 negocios, o un negocio que dependa del servicio en horas críticas → PostgreSQL gestionado y varias VPS de aplicación.

Cómo se instala y se traslada el servidor (cuentas de acceso, `bootstrap-server.sh`,
`install-vm.sh` (ADR-017), `server-migrate.sh`) queda en [ADR-012](ADR-012-instalacion-y-traslado.md).
