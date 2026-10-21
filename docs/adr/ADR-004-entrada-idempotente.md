# ADR-004 — Entrada idempotente y "al menos una vez"

**Estado:** aceptada (revisada el 2026-10-21) · **Relacionado:** `design.md` §5.3, §7, §9.5

## Contexto

Meta reintenta los webhooks si no recibe 200 a tiempo, y a veces los repite igualmente. Los procesos se reinician a mitad de un trabajo (por ejemplo, en cada despliegue). No se puede perder un mensaje ni duplicar una cita o un envío.

## Decisión

- **Guardar primero, contestar 200, procesar después**: el webhook verifica la firma, inserta `inbound_event` con `UNIQUE(tenant_id, provider_event_id)` y encola en la misma transacción.
- Procesamiento **"al menos una vez"** + **idempotencia** en todo efecto externo:
  - Mensajes salientes: `outbound_message` con `UNIQUE(tenant_id, idem_key)`, guardado antes de enviar; estados explícitos; un envío ambiguo pasa a `unknown` y **no se reintenta a ciegas**.
  - Barridos (recordatorios, confirmaciones): clave estable por entidad en la misma tabla.
  - Citas: **id de evento de Calendar determinista** derivado de la clave idempotente + advisory lock por calendario y día. No hace falta una tabla de efectos.
- **Transacciones cortas**: nunca una transacción abierta durante llamadas externas.
- Candado por contacto (hash sin teléfono) + `conversation.version` para que dos mensajes del mismo contacto nunca se procesen a la vez.

## Alternativas consideradas

- **Procesar dentro del webhook** (como los bots actuales con `BackgroundTasks` y estado en memoria): se pierde trabajo si el proceso cae.
- **Tabla genérica `side_effect`** (diseño anterior): innecesaria con ids deterministas en Calendar y claves únicas en los envíos.

## Consecuencias

- Todo sistema externo que escribe debe ser idempotente o consultable.
- Hay estados `unknown` que revisar en el Admin.

## Cuándo revisarla

- Se añade un sistema externo sin forma de escritura idempotente → tabla de efectos para ese caso.
