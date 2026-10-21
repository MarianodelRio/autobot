# ADR-001 — Monolito modular Django + Procrastinate

**Estado:** aceptada (revisada el 2026-10-21) · **Relacionado:** `design.md` §0, §5, §7.5

## Contexto

Una sola persona construye y opera la plataforma para 5–15 negocios. Hay que atender webhooks rápido, procesar trabajo en segundo plano (conversaciones, envíos, barridos) y añadir negocios sin reescribir nada. La carga es pequeña (picos de unos pocos mensajes por segundo en total).

## Decisión

- **Un solo proyecto Python 3.14 + Django 5.2 LTS**, dividido en `core/` e `integrations/` (sin Django), `packs/` (solo dependen de `core`) y `flowpilot/` (Django), con la regla de dependencias comprobada por `import-linter`.
- **Una imagen, varios procesos**: `web` (verifica, guarda y encola), `worker` (Procrastinate) y `admin` (Django Admin, solo por túnel SSH).
- **Cola en el propio PostgreSQL con Procrastinate 3.x**: 3 colas (`inbound`, `outbound`, `periodic`) atendidas por un solo worker; candados por contacto; tareas periódicas integradas.

## Alternativas consideradas

- **Microservicios**: más despliegues y fallos parciales; sin beneficio a esta escala.
- **Celery + Redis**: una pieza más que operar; Postgres ya da transacciones compartidas con los datos (el trabajo solo existe si hay COMMIT).
- **Seguir con FastAPI como los bots actuales**: habría que montar a mano admin, migraciones y ORM, que Django trae.

## Consecuencias

- Un solo despliegue, un solo sitio donde mirar; los tests de `core` y de los packs corren sin BD.
- La cola comparte recursos con los datos: una saturación de la BD afecta a ambas (irrelevante a esta escala).

## Cuándo revisarla

- Postgres como cola llega a su límite (miles de trabajos/s).
- Django 6.2 LTS (abril de 2027): planificar la migración antes del fin de soporte de 5.2 (abril de 2028).
