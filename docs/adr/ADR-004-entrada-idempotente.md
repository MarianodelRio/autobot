# ADR-004 — Entrada idempotente y "al menos una vez"

**Estado:** aceptada · **Relacionado:** `design.md` §4.3, §7, §9.5

## Contexto

Meta y Telegram reintentan los webhooks si no reciben 200 a tiempo, y a veces los repiten igualmente. Los procesos se reinician a mitad de un trabajo (por ejemplo, en cada despliegue). No se puede perder un mensaje ni duplicar una cita o un envío.

## Decisión

- **Guardar primero, contestar 200, procesar después**: el webhook verifica la firma, inserta `inbound_event` con `UNIQUE(tenant_id, channel, provider_event_id)` y encola en la misma transacción.
- Procesamiento **"al menos una vez"** + **idempotencia** en todo efecto externo:
  - Mensajes salientes: `outbound_message` con `UNIQUE(tenant_id, idem_key)`, guardado antes de enviar; estados explícitos; un envío ambiguo pasa a `unknown` y **no se reintenta a ciegas**.
  - Barridos (recordatorios, confirmaciones): clave estable por entidad en la misma tabla.
  - Citas: **id de evento de Calendar determinista** derivado de la clave idempotente + advisory lock por calendario y día. No hace falta una tabla de efectos.
- **Transacciones cortas**: nunca una transacción abierta durante llamadas externas.
- Candado por conversación de Procrastinate (hash sin identificadores en claro): los mensajes de un contacto se procesan de uno en uno y en orden; como solo ese trabajo escribe la conversación, no hace falta control de versiones.

## Alternativas consideradas

- **Procesar dentro del webhook** con estado en memoria: se pierde trabajo si el proceso cae.
- **Tabla genérica de efectos externos**: innecesaria con ids deterministas en Calendar y claves únicas en los envíos.

## Consecuencias

- Todo sistema externo que escribe debe ser idempotente o consultable.
- Hay estados `unknown` que revisar en el Admin.

## Cuándo revisarla

- Se añade un sistema externo sin forma de escritura idempotente → tabla de efectos para ese caso.
