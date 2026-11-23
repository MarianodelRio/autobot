# ADR-026 — Conciliación de envíos ambiguos y recuperación en bloque

**Estado:** aceptada

## Contexto

Un envío cuyo resultado se desconoce (un 5xx de Meta sin cuerpo, cualquier 5xx de Telegram, un tiempo agotado tras conectar, un worker muerto a mitad) queda `unknown`. Hasta ahora **solo una persona** lo resolvía desde el panel: si no llegaba un estado de entrega de Meta, el mensaje se quedaba así para siempre. Telegram **no tiene estado de entrega**, así que en ese canal todo `unknown` es permanente salvo intervención.

Pasa con lo que más importa al cliente: la respuesta que confirma una reserva y el recordatorio de la cita. Perderlos en silencio cuesta más que recibir dos veces el mismo texto.

Además, tras una incidencia no hay recuperación en bloque (los `failed`, `unknown` y `expired` se reenvían uno a uno) y un aviso al dueño cuyo chat no está conectado acaba `failed` sin que nadie lo vea, aunque el dueño pueda conectarlo minutos después.

## Decisión

**Conciliar antes de reenviar.** La regla pasa de «no se reintenta a ciegas un envío ambiguo» a: un `unknown` no se reenvía a ciegas; primero se concilia con el estado del proveedor (el webhook de estado de Meta lo pasa a `sent`) y, si pasado el plazo no hay evidencia, solo se reenvía **una vez** y **solo si su clase declara que un duplicado es inocuo**; si no, queda para una persona.

- **Tarea periódica `reconcile_unknown`** (cola `periodic`, cada 5 minutos, `runtime/reconcile.py`): por negocio, en lotes de 100, con la consulta que cubre el índice parcial `outbound_unknown_idx` (`tenant`, `unknown_at` donde `status = 'unknown'`).
- **Plazo** `RECONCILE_WAIT` = 10 minutos desde `unknown_at`: más que el retraso habitual de un estado de Meta. Es el mismo plazo que ya exigía el panel para «Marcar enviado» y «Reenviar».
- **Sin evidencia** significa que el mensaje sigue `unknown` y no tiene `provider_message_id`. Un estado de entrega ya lo habría pasado a `sent`.
- **Reenvío único**: columna nueva `ambiguous_resends` (smallint, 0 por defecto, máximo 1). El reenvío pasa por la vía normal (`send_message`: candados `out:`/`outp:`, cortacircuitos, `expires_at`). Si vuelve a ser ambiguo, queda `unknown` para una persona. Un reenvío manual (uno a uno o en bloque) también fija el contador a 1: la plataforma nunca suma su reenvío a la decisión de una persona.
- **Caducidad**: un `unknown` pasado su `expires_at` no se reenvía; pasa a `expired` (sin disculpa: puede que sí llegara).
- **Política de duplicados** (`DUP_POLICY` en `runtime/outbound.py`): se deriva de la clase del mensaje (`kind`). Respuestas, menús, disculpas y recordatorios son `safe`: repiten una frase que el contacto esperaba o ya vio. Cualquier clase no declarada es `unsafe` y la reenvía solo una persona. Añadir una clase nueva de mensaje obliga a decidirlo.
- **Avisos al dueño** (`Notification`): no siguen esta política. Se reclaman como `failed` antes de llamar a Telegram y no tienen estado `unknown`, y caducan a las 2 horas, así que el beneficio sería pequeño y exigiría un estado nuevo. Se documenta y se deja como estaba.

**Recuperación en bloque desde el panel.** `POST outbound/resend-bulk` (y su `…/preview`) reenvía los mensajes elegidos o filtrados (negocio, estados `failed`/`unknown`/`expired`, rango de fechas), con un tope de 500 por acción (los más antiguos primero; se repite para el resto), confirmación del riesgo de duplicado y **verificación TOTP reciente** (el mismo `require_recent_reauth` de las acciones destructivas). Cada mensaje recupera un `expires_at` nuevo, usa la misma lógica que el reenvío individual (`ops/actions.py`) y se omiten los que no cumplen (un `unknown` reciente, un contacto inalcanzable, un negocio de baja o sin canal). Deja **un** registro de auditoría con solo cifras.

**Avisos retenidos.** Un aviso al dueño de un negocio sin chat conectado pasa a `held` en lugar de `failed`. Al conectar el chat (`owner/links.py`), los `held` de menos de `NOTICE_TTL` (2 h) se encolan y los más viejos caducan; `reconcile_unknown` caduca también los que nadie reclama. `ops_check` no cuenta los `held` como fallo (`notification_failed`); un negocio real activo con avisos retenidos recibe una alerta 🟡 `owner_unlinked`, y el panel muestra cuántos hay.

## Alternativas consideradas

- **Dejarlo como estaba** (solo una persona): con Telegram, y con cualquier estado de Meta que no llegue, se pierden confirmaciones y recordatorios sin que nadie lo sepa; la persona no tiene cómo enterarse a tiempo.
- **Reenviar siempre tras el plazo, sin tope ni clase**: puede repetir un mensaje que no sea inocuo y, en una caída larga, multiplicarlo. El tope de un reenvío acota el duplicado a uno por mensaje.
- **Marcar como `sent` tras el plazo**: ocultaría pérdidas reales.
- **Reconciliar con una consulta al proveedor**: ni Telegram ni la API de mensajes de Meta ofrecen consultar un envío por su clave de idempotencia.
- **Poner la política en cada `Reply` o `ProactiveMessage`**: obliga a cambiar la serialización de todos los packs para una distinción que hoy no existe (todo es `safe`). La clase del mensaje basta y el valor por defecto es el seguro.

## Consecuencias

- Como mucho **un duplicado por mensaje** (acotado y medido por `ambiguous_resends`), a cambio de no perder en silencio respuestas ni recordatorios. Se acepta de forma explícita; es un cambio de la regla de `CLAUDE.md`.
- Los `unknown` que quedan tras la conciliación son los que de verdad requieren a una persona; la alerta `outbound_failed` espera ahora 20 minutos (plazo más una vuelta de la tarea) en lugar de 10.
- Una migración (0031) sin cambios de RLS ni de roles: columna `ambiguous_resends` y la opción `held` de `Notification.status`.
- La vía manual (marcar enviado, reenviar) sigue disponible y tiene prioridad sobre la automática.

## Cuándo revisarla

- Si aparece una clase de mensaje cuyo duplicado no sea inocuo (un cobro, un código de un solo uso): debe declararse `unsafe`.
- Si Telegram o Meta ofrecen consulta del estado de un envío: conciliar con el proveedor sustituiría al reenvío.
- Si el número de `ambiguous_resends` = 1 con duplicado confirmado crece de forma apreciable.
