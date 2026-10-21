# ADR-005 — Una VPS con Docker Compose

**Estado:** aceptada (sustituye a "AWS ECS Fargate + CDK", el 2026-10-21) · **Relacionado:** `design.md` §0, §15, §16

## Contexto

La plataforma atiende a 5–10 negocios (15 como máximo previsto), con picos de pocos mensajes por segundo. La opera una persona. El diseño anterior en AWS (ECS Fargate, RDS, ALB, KMS, SSM, EventBridge, CloudWatch, CDK, dos cuentas) costaba ~100 €/mes en producción y añadía muchas piezas que operar. Los bots actuales corren en una VM pequeña sin problemas de capacidad.

## Decisión

- **Una VPS en la UE** (Hetzner Cloud, 2 vCPU / 4 GB) con Ubuntu 24.04 y **Docker Compose**: `caddy`, `web`, `worker`, `admin` y `db` (PostgreSQL 18). Misma imagen para los procesos de la aplicación.
- **Caddy** con HTTPS automático; solo expone `/webhooks/whatsapp/*` y `/health`. El Admin escucha en `127.0.0.1` y se usa por túnel SSH.
- **Backups**: `pg_dump` cada 6 h cifrado con restic a almacenamiento de **otro proveedor**; instantáneas diarias de la VM; simulacro de restauración trimestral. RPO ≤ 6 h, RTO ≤ 2 h.
- **Secretos**: `.env` en el servidor; credenciales de negocios cifradas con Fernet en la BD.
- **Despliegue**: imagen en GHCR desde GitHub Actions; despliegue manual por SSH con migraciones antes, comprobación de salud, smoke y vuelta atrás automática.
- **Vigilancia que no depende de la VPS**: latido a healthchecks.io y uptime externo.

## Alternativas consideradas

- **AWS ECS + RDS** (diseño anterior): gestionado y escalable, pero ~5–10× más caro y mucho más complejo para esta escala.
- **PaaS (Render, Fly, Railway)**: menos operación, pero coste por servicio (web, worker, BD) que supera el objetivo y menos control de la región.
- **Kubernetes**: sin sentido a esta escala.

## Consecuencias

- Coste de infraestructura ~10–20 €/mes.
- Sin alta disponibilidad: un fallo de la VPS supone una caída hasta restaurar (Meta reintenta los webhooks durante horas). Aceptado (`design.md` §1.3).
- Parches del sistema, cortafuegos y backups son responsabilidad nuestra: automatizados (`unattended-upgrades`, timer de backup) y vigilados.
- Nada depende del proveedor: cambiar de VPS es una restauración.

## Cuándo revisarla

- Más de 15–20 negocios, o un negocio que dependa del servicio en horas críticas → PostgreSQL gestionado + varias VPS de aplicación.
- Un cliente exige datos en España → proveedor con centro de datos en España.
