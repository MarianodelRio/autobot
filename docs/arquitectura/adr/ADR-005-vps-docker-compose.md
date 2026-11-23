# ADR-005 — Una VPS con Docker Compose

**Estado:** vigente; ampliado por [ADR-020](ADR-020-api-del-panel-aparte.md) (contenedor `web-panel`, redes separadas y contenedores endurecidos) y por [ADR-023](ADR-023-colas-aisladas-y-degradacion.md) (cuatro workers: `worker-calendar` y `worker-periodic` aparte)

## Contexto

La plataforma atiende a 5–10 negocios (15 como máximo previsto), con picos de pocos mensajes por segundo, y la opera una persona. El objetivo de coste de infraestructura es de unos 20 €/mes, sin contar las APIs.

## Decisión

- **Una VPS en la UE** (Hetzner Cloud, 2 vCPU / 4 GB) con Ubuntu 24.04 y **Docker Compose**: `caddy`, `web`, `worker-inbound`, `worker-outbound` (desde 2026-11-11: una caída de Google Calendar frenaba también los envíos y las barridas periódicas; dos workers, uno por grupo de colas, lo evitan), `db` (PostgreSQL 18), `panel` y `victorialogs`. `web` y los `worker-*` usan la misma imagen; `panel` y `victorialogs` solo son accesibles por túnel SSH. Excepción a "un worker por grupo de colas": los dos workers escuchan también la cola `ops` (`ops_check`, 2026-11-16), para que la caída de uno de ellos no silencie también su propia alerta.
- **Caddy** con HTTPS automático; solo expone los webhooks de WhatsApp y Telegram (incluidos los de las dos puertas del bot de demo y el bot de avisos, `/webhooks/telegram-notify`) y `/health`.
- **Secretos**: `.env` (plataforma) en el servidor, montado de solo lectura; los secretos de canal de cada negocio viven cifrados en PostgreSQL (`SECRETS_ENCRYPTION_KEY` en `.env`). Nunca en git ni en la imagen.
- **Backups**: `pg_dump` cada 6 h, `.env`, `google_sa.json`, el `Caddyfile` y `.deployed-sha` (todos bajo `var/`), cifrados con restic, a almacenamiento de **otro proveedor**; simulacro de restauración trimestral. RPO ≤ 6 h, RTO ≤ 2 h.
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

## Proveedor y alternativas (contexto, 2026-11)

- **Dimensionado:** 2 vCPU, 4 GB de RAM y 2 GB de swap se estiman suficientes para 5-15
  negocios; no se ha medido bajo carga (pendiente medir la memoria con los dos workers).
  Coste total estimado: menos de 10 EUR/mes con dominio y planes gratuitos de Sentry,
  healthchecks.io y backups.
- **Proveedor aún sin fijar.** Precios sin IVA del 2026-11-09: OVHcloud VPS-1 (2 vCore,
  4 GB, 40 GB) desde 3,81 EUR/mes, a confirmar permanencia y centro de datos en la UE (es
  la opción propuesta); Hetzner CX23 a 5,99 EUR/mes, sin stock ese día; netcup VPS 500
  G12.5 a 8,26 EUR/mes con 12 meses. Como nada depende del proveedor, cambiarlo es una
  restauración (ADR-012).
- **Terraform descartado:** un script por SSH sirve en cualquier proveedor sin añadir otra
  herramienta que mantener.

## Cuándo revisarla

- Más de 15 negocios, o un negocio que dependa del servicio en horas críticas → PostgreSQL gestionado y varias VPS de aplicación.

Cómo se instala y se traslada el servidor (cuentas de acceso, `bootstrap-server.sh`,
`install-vm.sh` (ADR-017), `server-migrate.sh`) queda en [ADR-012](ADR-012-instalacion-y-traslado.md).
