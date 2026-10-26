# ADR-005 — Una VPS con Docker Compose

**Estado:** aceptada

## Contexto

La plataforma atiende a 5–10 negocios (15 como máximo previsto), con picos de pocos mensajes por segundo, y la opera una persona. El objetivo de coste de infraestructura es de unos 20 €/mes, sin contar las APIs.

## Decisión

- **Una VPS en la UE** (Hetzner Cloud, 2 vCPU / 4 GB) con Ubuntu 24.04 y **Docker Compose**: `caddy`, `web`, `worker` y `db` (PostgreSQL 18). `web` y `worker` usan la misma imagen.
- **Caddy** con HTTPS automático; solo expone los webhooks de WhatsApp y Telegram (incluidos los de las dos puertas del bot de demo) y `/health`. El Admin lo sirve `web`, pero solo es accesible por túnel SSH.
- **Secretos**: `.env` (plataforma) y `secrets.yaml` (canal de cada negocio) en el servidor, montados de solo lectura; nunca en git ni en la imagen.
- **Backups**: `pg_dump` cada 6 h y los ficheros de secretos, cifrados con restic, a almacenamiento de **otro proveedor**; simulacro de restauración trimestral. RPO ≤ 6 h, RTO ≤ 2 h.
- **Despliegue**: imagen en GHCR desde GitHub Actions; despliegue manual por SSH con migraciones primero, comprobación de salud y vuelta atrás automática.
- **Vigilancia que no depende de la VPS**: latido a healthchecks.io y uptime externo.

## Alternativas consideradas

- **Nube gestionada (contenedores gestionados + base de datos gestionada + balanceador)**: escalable y con alta disponibilidad, pero varias veces más cara y con muchas más piezas que operar para esta escala.
- **PaaS (Render, Fly, Railway)**: menos operación, pero el coste por servicio (web, worker, BD) supera el objetivo.
- **Kubernetes**: sin sentido a esta escala.

## Consecuencias

- Coste de infraestructura de ~6–11 €/mes.
- Sin alta disponibilidad: un fallo de la VPS supone una caída hasta restaurar (los proveedores reintentan los webhooks). Aceptado.
- Parches del sistema, cortafuegos y backups son responsabilidad nuestra: automatizados y vigilados.
- Nada depende del proveedor: cambiar de VPS es una restauración.

## Cuándo revisarla

- Más de 15 negocios, o un negocio que dependa del servicio en horas críticas → PostgreSQL gestionado y varias VPS de aplicación.
