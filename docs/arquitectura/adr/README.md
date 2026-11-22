# Decisiones de arquitectura (ADR)

Un ADR se escribe cuando se toma una decisión que no es trivial de deshacer (arquitectura, aislamiento de datos, despliegue) o cuando una decisión existente cambia. Documenta el contexto, la decisión, las alternativas descartadas y cuándo revisarla; no describe el código, de eso se ocupan las páginas de [Conceptos](../vision-general.md). Plantilla: [plantilla.md](plantilla.md).

La fecha es la del alta del ADR en git. Si una decisión cambia, el ADR afectado lo indica en su línea «Estado:» y en esta tabla.

| ADR | Título | Estado | Fecha | Modificado o sustituido por |
|---|---|---|---|---|
| [001](ADR-001-monolito-modular.md) | Monolito modular Django + Procrastinate | vigente | 2026-10-06 | |
| [002](ADR-002-multitenancy-rls.md) | Multitenancy con Row-Level Security | vigente | 2026-10-06 | |
| [003](ADR-003-packs.md) | Packs con máquina de estados propia | vigente | 2026-10-21 | |
| [004](ADR-004-entrada-idempotente.md) | Entrada idempotente y «al menos una vez» | vigente | 2026-10-06 | |
| [005](ADR-005-vps-docker-compose.md) | Una VPS con Docker Compose | vigente | 2026-10-21 | Ampliado por ADR-020 |
| [006](ADR-006-bot-de-demo.md) | Bot de demo con dos puertas y negocios de demostración | vigente | 2026-10-26 | |
| [007](ADR-007-bot-de-duenos.md) | El bot de avisos se convierte en el asistente del dueño | vigente | 2026-10-29 | |
| [008](ADR-008-panel.md) | Panel interno: arquitectura, acceso y observabilidad | vigente | 2026-11-03 | Actualizado por ADR-020 |
| [009](ADR-009-config-en-bd.md) | Config y datasets de los negocios en PostgreSQL, versionados | vigente; datasets modificados | 2026-11-03 | ADR-013 (datasets) |
| [010](ADR-010-estructura-del-repo.md) | Estructura del repositorio: apps autocontenidas, compose por entorno y `var/` | vigente | 2026-11-04 | |
| [011](ADR-011-borrado-total-de-un-cliente.md) | Borrado total de un cliente | vigente | 2026-11-09 | |
| [012](ADR-012-instalacion-y-traslado.md) | Instalación y traslado del servidor | parcialmente sustituido | 2026-11-15 | ADR-017 (instalación desde el portátil) |
| [013](ADR-013-biblioteca-de-conjuntos-de-datos.md) | Biblioteca de conjuntos de datos | vigente | 2026-11-17 | Modifica el ADR-009 |
| [014](ADR-014-pestana-de-alta.md) | Pestaña «Alta» guiada por pasos | vigente | 2026-11-17 | |
| [015](ADR-015-varios-peluqueros.md) | Varios peluqueros en `salon` | aceptado, pendiente de implementar | 2026-11-17 | |
| [016](ADR-016-acciones-de-alta-whatsapp.md) | Acciones de alta de WhatsApp desde la pestaña «Alta» | vigente | 2026-11-20 | |
| [017](ADR-017-instalador-de-la-vm-y-entorno-local.md) | Instalador de la VM desde dentro y un solo comando para local | vigente | 2026-11-20 | Sustituye parte del ADR-012 |
| [018](ADR-018-documentacion-en-el-panel.md) | Documentación como sitio servido por el panel | vigente | 2026-11-21 | |
| [019](ADR-019-libro-de-supresiones.md) | Libro de supresiones para no resucitar datos olvidados | vigente | 2026-11-22 | Complementa el ADR-011 |
| [020](ADR-020-api-del-panel-aparte.md) | La API del panel en un servicio propio, redes separadas y contenedores endurecidos | vigente | 2026-11-22 | Actualiza ADR-005 y ADR-008 |
| [021](ADR-021-backups-resistentes.md) | Backups resistentes a un servidor comprometido y clave de cifrado aparte | vigente | 2026-11-22 | Complementa ADR-011 y ADR-019 |
