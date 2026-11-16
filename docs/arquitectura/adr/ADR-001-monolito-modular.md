# ADR-001 — Monolito modular Django + Procrastinate

**Estado:** aceptada

## Contexto

Una sola persona construye y opera la plataforma para 5–15 negocios. Hay que atender webhooks rápido, procesar trabajo en segundo plano (conversaciones, envíos, barridos) y añadir negocios sin reescribir nada. La carga es pequeña (picos de unos pocos mensajes por segundo en total).

## Decisión

- **Un solo proyecto Python 3.14 + Django 5.2 LTS**, dividido en `core/` e `integrations/` (sin Django), `packs/` (solo dependen de `core`) y `autobot/` (Django), con la regla de dependencias comprobada por `import-linter`.
- **Una imagen, tres procesos**: `web` (webhooks de WhatsApp y Telegram: verifica, guarda y encola) y `worker-inbound`/`worker-outbound` (Procrastinate).
- **Cola en el propio PostgreSQL con Procrastinate 3.x**: 4 colas (`inbound`, `outbound`, `periodic`, `ops`); `worker-inbound` atiende `inbound`, `periodic` y `ops`, `worker-outbound` atiende `outbound` y `ops` (dos workers desde X14, 2026-11-11, para que una caída de Google Calendar no frene también los envíos; `ops` la escuchan los dos desde 2026-11-16, para que la caída de uno no silencie también su propia alerta); candados por contacto; tareas periódicas integradas.

## Alternativas consideradas

- **Microservicios**: más despliegues y fallos parciales; sin beneficio a esta escala.
- **Celery + Redis**: una pieza más que operar; Postgres ya da transacciones compartidas con los datos (el trabajo solo existe si hay COMMIT).
- **FastAPI**: habría que montar a mano admin, migraciones y ORM, que Django trae.

## Consecuencias

- Un solo despliegue, un solo sitio donde mirar; los tests de `core` y de los packs corren sin BD.
- La cola comparte recursos con los datos: una saturación de la BD afecta a ambas (irrelevante a esta escala).

## Cuándo revisarla

- Postgres como cola llega a su límite (miles de trabajos/s).
- Django 6.2 LTS (abril de 2027): planificar la migración antes del fin de soporte de 5.2 (abril de 2028).
