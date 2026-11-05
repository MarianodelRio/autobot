# Decisiones de arquitectura (ADR)

Índice de las decisiones registradas. Cada ADR documenta un contexto y una decisión que
no es trivial de deshacer; se mantiene actualizada con el estado real del sistema.
Plantilla: [`plantilla.md`](plantilla.md).

| ADR | Título | Estado |
|---|---|---|
| [001](ADR-001-monolito-modular.md) | Monolito modular Django + Procrastinate | aceptada |
| [002](ADR-002-multitenancy-rls.md) | Multitenancy con Row-Level Security | aceptada |
| [003](ADR-003-packs.md) | Packs con máquina de estados propia | aceptada |
| [004](ADR-004-entrada-idempotente.md) | Entrada idempotente y "al menos una vez" | aceptada |
| [005](ADR-005-vps-docker-compose.md) | Una VPS con Docker Compose | aceptada |
| [006](ADR-006-bot-de-demo.md) | Bot de demo con dos puertas y negocios de demostración | aceptada |
| [007](ADR-007-bot-de-duenos.md) | El bot de avisos se convierte en el asistente del dueño | aceptada |
| [008](ADR-008-panel.md) | Panel interno: arquitectura, acceso y observabilidad | aceptada |
| [009](ADR-009-config-en-bd.md) | Config y datasets de los negocios en PostgreSQL, versionados | aceptada |
| [010](ADR-010-estructura-del-repo.md) | Estructura del repositorio: apps autocontenidas, compose por entorno y `var/` | aceptada |
