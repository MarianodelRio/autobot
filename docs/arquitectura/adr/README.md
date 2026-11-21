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
| [011](ADR-011-borrado-total-de-un-cliente.md) | Borrado total de un cliente | aceptada |
| [012](ADR-012-instalacion-y-traslado.md) | Instalación y traslado del servidor desde la máquina del operador | aceptada (parcialmente sustituida por ADR-017) |
| [013](ADR-013-biblioteca-de-conjuntos-de-datos.md) | Biblioteca de conjuntos de datos (modifica el ADR-009) | aceptada |
| [014](ADR-014-pestana-de-alta.md) | Pestaña «Alta» guiada por pasos | aceptada |
| [015](ADR-015-varios-peluqueros.md) | Varios peluqueros en `salon` | aceptada |
| [016](ADR-016-acciones-de-alta-whatsapp.md) | Acciones de alta de WhatsApp desde la pestaña «Alta» | aceptada |
| [017](ADR-017-instalador-de-la-vm-y-entorno-local.md) | Instalador de la VM desde dentro y un solo comando para local (sustituye `server-init` del ADR-012) | aceptada |
