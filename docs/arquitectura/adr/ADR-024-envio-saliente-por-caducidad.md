# ADR-024 — Envío saliente por caducidad

**Estado:** aceptada

## Contexto

`send_message` reintentaba como mucho cinco veces (`MAX_SEND_ATTEMPTS`), con esperas de 5 s, 30 s, 2 min y 10 min. La espera de 30 min no llegaba a usarse (el trabajo se daba por fallido al llegar a 5), así que la ventana total era de unos 12,6 minutos. Una caída de Meta o de Telegram más larga convertía **todas** las respuestas y recordatorios en `failed`, sin recuperación: los recordatorios no se recreaban porque `create_proactive` ignora una clave `reminder:*` ya existente. Las caídas reales de Meta en 2026 duraron 5,5 h y 11,7 h.

Además, los recordatorios compartían el candado `out:<h>` con las respuestas: un recordatorio atascado bloqueaba las respuestas al mismo contacto. Y durante una caída cada mensaje seguía llamando al proveedor y agotando su timeout, ocupando un hueco del worker, y generaba una alerta propia.

Un prototipo con las medidas de este ADR convirtió caídas de 30 min a 12 h (antes, 100 % de mensajes perdidos) en 0 perdidos en silencio y 0 duplicados, y una tormenta de 429 (70 de 100 perdidos) en 100 de 100 entregados.

## Decisión

**Se reintenta por tiempo, no por número de intentos.** Cada mensaje saliente tiene `expires_at` (columna nueva, nullable; los anteriores no caducan):

| Mensaje | Caduca |
|---|---|
| Respuesta | 30 minutos desde que se crea |
| Recordatorio o aviso proactivo | el menor de 24 h y `SendProactive.not_after` |
| Disculpa (ver abajo) | 6 horas |

`not_after` lo pone el pack: `salon` lo fija 30 minutos antes del comienzo de la cita (calculado en UTC, para que las noches de cambio de hora no lo desplacen). Reglas:

- Un fallo transitorio del proveedor (`RetryLater`: límite de tasa, 5xx que Meta declara como «no salió», fallo de conexión) se reintenta **sin tope de intentos** hasta `expires_at`. La espera es el `Retry-After` del proveedor si lo da y, si no, un retroceso exponencial con jitter, de 5 s hasta un máximo de 300 s, y nunca más allá de la caducidad. `RetryLater` lleva un `kind` (`rate`, `server`, `network`).
- Lo ambiguo no cambia: sigue siendo `unknown` y no se reenvía a ciegas. Los errores de base de datos siguen teniendo un número acotado de reintentos (5).
- Pasado `expires_at`, el mensaje pasa a un estado nuevo, `expired`, y **no se envía**.
- La ventana de servicio de 24 h de WhatsApp queda cubierta: respuesta (30 min) y disculpa (6 h) terminan siempre dentro de ella (hay una comprobación en el código).
- Los avisos al dueño (`send_notification`) conservan su estrategia anterior de cinco intentos: se tratan aparte.

**Una disculpa en lugar de la respuesta tardía.** Una respuesta caducada no se entrega: sus botones pueden estar obsoletos. En su lugar se envía **una** disculpa corta (`APOLOGY_TEXT`, en `core/conversation.py`: «Perdona el retraso, hemos tenido un problema técnico. ¿Seguimos? Escribe *menú* para empezar.»), como mucho una por contacto cada 6 horas e idempotente (`apology:<id del mensaje caducado>`). Si la disculpa caduca también, no genera otra. Un recordatorio caducado simplemente queda `expired`, sin disculpa.

**Candados separados.** Las respuestas siguen con `out:<h>` (orden entre ellas). Los envíos proactivos van con `outp:<h>` (`runtime/locks.py`, `send_lock`). Un recordatorio atascado ya no bloquea las respuestas al mismo contacto. A cambio, **entre una respuesta y un recordatorio no hay orden garantizado**.

**Recordatorios recreables.** Si `create_proactive` encuentra una fila con esa clave en `expired` y la nueva ventana sigue abierta (`min(ahora + 24 h, not_after)` está en el futuro), la revive (`pending`, nuevo `expires_at`, intentos a cero) y se vuelve a encolar. El barrido de `salon` ofrece cada recordatorio periódicamente, así que tras una caída los recordatorios aún útiles salen solos. No se revive un `failed`: significa que el proveedor lo rechazó y volver a pedirlo solo lo repetiría; tampoco un `sent` ni un `unknown`.

**Cortacircuitos por proveedor.** Cada proceso del worker de salida tiene uno por proveedor (WhatsApp, Telegram; `runtime/breaker.py`), en memoria:

- Se abre tras 5 fallos de transporte seguidos (5xx, red, tiempo agotado; **no** 4xx ni rechazos de autenticación) que vengan de **al menos 2 negocios distintos**, para que un negocio mal configurado no lo abra para todos. Cualquier respuesta correcta del proveedor (incluida una 4xx de rechazo) reinicia la cuenta.
- Abierto, los envíos se aplazan (`RetryLater`) sin llamar al proveedor, y como mucho una vez cada 60 s uno de ellos ejecuta una sonda de solo lectura (`adapter.probe()`: `GET` del nodo del número en WhatsApp, `getMe` en Telegram). Si responde, se cierra.
- Al abrirse, cerrarse y tras cada sonda fallida, escribe una señal en la caché de base de datos (`ops/state.py`). `ops_check` levanta **una** alerta `provider_outage` (y la resuelve sola), en lugar de una por mensaje. Una señal sin refrescar durante 10 minutos (un worker que murió con el cortacircuitos abierto) cuenta como cerrada.

## Avisos al dueño

Los avisos del bot de avisos (`send_notification`) seguían con cinco intentos y, con 150 avisos simultáneos, entre el 67 % y el 97 % acababan `failed`: Telegram contesta 429 por encima de unos 30 mensajes/s por bot y 1/s por chat, y el tope de intentos se agotaba. Siguen el mismo modelo:

- **Limitador previo** (`runtime/ratelimit.py`, `SlotLimiter`, "próximo hueco libre"): 25 mensajes/s para el bot y 1/s por chat de dueño. Sin hueco no se llama a Telegram: el aviso queda `pending` y se lanza `SendRetry` con la espera hasta el hueco (más hasta 1 s de jitter); una espera de 1 s o menos se duerme en el hilo. **Es por proceso**: vale con un único `worker-outbound`; compartirlo entre procesos es trabajo futuro.
- **Caducidad de 2 h** (`NOTICE_TTL`, sobre `created_at`; sin columna nueva): un aviso más viejo ya no sirve y pasa a `expired` sin disculpa. La migración `0030_notification_expired` solo añade la opción al estado.
- **Reintento por tiempo**: el 429 respeta `retry_after` y no consume intentos; un fallo de red (ciertamente no enviado) espera `backoff_s` (jitter, tope 300 s) sin límite de intentos hasta caducar; un 5xx o un tiempo agotado siguen siendo ambiguos y el aviso queda `failed` (no se reenvía a ciegas).
- **Sin cortacircuitos**: el bot de avisos es uno solo de la plataforma, no un proveedor compartido por negocios; el `BREAKER` de `send_message` (que exige fallos de al menos 2 negocios) no aplica, y la caducidad ya acota el trabajo.
- **Alerta**: `notification_failed` cuenta también los `expired` (el bot estuvo horas sin poder entregar: un aviso perdido de verdad, y raro; un atasco por límite de ritmo se drena en segundos).

Las alertas de operación (`send_ops_alert`) siguen sin pasar por el limitador: son pocas y solo avisan al abrirse (ADR-031).

## Alternativas consideradas

- **Subir el número de intentos o alargar las esperas.** Sigue siendo una cuenta arbitraria: o se queda corta en la siguiente caída o deja respuestas de horas que ya no tienen sentido. El criterio útil es el tiempo durante el que el mensaje sigue valiendo.
- **Entregar la respuesta tardía.** Los botones pueden apuntar a un estado de la conversación que ya cambió, y el contacto recibiría de golpe varias respuestas viejas.
- **Tabla `provider_health` en PostgreSQL y un cubo de fichas global.** Coordinaría los workers, pero añade una tabla, escrituras en el camino de cada envío y una pieza más que puede fallar justo cuando el proveedor está caído. El cortacircuitos en memoria necesita unos pocos envíos fallidos para aprender y no coordina nada; basta con un worker de salida. Queda como trabajo futuro si hubiera varios.
- **Reconciliar los `unknown` contra el proveedor.** Mejoraría el estado ambiguo, pero es otro problema (la regla de no reenviar a ciegas no cambia aquí).
- **Revivir también los `failed`.** Se repetirían envíos rechazados por el proveedor en cada barrido.

## Consecuencias

- Una caída de horas ya no pierde mensajes en silencio: lo útil sale al recuperarse, lo obsoleto se descarta con una disculpa y todo queda registrado como `expired`.
- Aparece el estado `expired` en `outbound_message`, y la columna `expires_at` (migración `0029_outbound_expires_at`). `outbound_failed` no salta por un `expired`: la caída se ve en `provider_outage`. *Nota (ADR-031):* hoy son `outbound_rejected:<clase>` y `outbound_ambiguous`, y tampoco cuentan los `expired`.
- Durante una caída cada mensaje pendiente mantiene un trabajo `send_message` vivo que se reintenta como mucho cada 5 minutos (con el cortacircuitos abierto, sin llamar al proveedor), durante 30 minutos las respuestas y hasta 24 h los recordatorios.
- Un reintento de los errores de base de datos que llegue tras muchos reintentos del proveedor ya no se reintenta (el contador del trabajo es común); la barrida de `ops_check` reencola un `pending` sin trabajo vivo.
- Reiniciar un worker de salida reinicia su cortacircuitos (cerrado).
- Un `resend` manual da al mensaje un plazo nuevo (30 min o 24 h).

## Cuándo revisarla

- Si hay más de un worker de salida y las sondas o la apertura del cortacircuitos se descoordinan de forma que se note (sondas repetidas, o uno abierto y otro cerrado durante minutos).
- Si Meta o Telegram cambian las reglas de reintento o de ventana de servicio (hoy: 24 h).
- Si hay más de un proceso de salida: el limitador de avisos por proceso permitiría el doble de ritmo.
- Si se implementa la reconciliación de `unknown`: los `expired` podrían entrar también en ella.

Relacionado: [ADR-004](ADR-004-entrada-idempotente.md), [efectos e idempotencia](../efectos-e-idempotencia.md), [cola y workers](../cola-y-workers.md).
