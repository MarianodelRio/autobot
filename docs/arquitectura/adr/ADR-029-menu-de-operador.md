# ADR-029 — Menú de operador en el bot de avisos, solo consulta

**Estado:** aceptada; actualizada por [ADR-031](ADR-031-incidencias-como-bandeja.md) (el menú y el resumen diario listan incidencias, no alertas)

## Contexto

El operador se entera de los problemas por las alertas del bot de avisos (`OPS_TELEGRAM_CHAT_ID`, [Observabilidad](../observabilidad.md#avisos-al-operador)) y ve el estado completo en el panel, que solo se abre por túnel SSH ([ADR-008](ADR-008-panel.md)). Faltaban dos cosas:

- **Preguntar desde el móvil** cómo va todo sin abrir el túnel: el chat de operación solo enviaba y no leía lo que se le escribía.
- **Una confirmación periódica de que todo va bien.** Un chat que calla puede significar que todo va bien o que el propio aviso está roto. El latido de Healthchecks cubre lo segundo, pero el operador no veía nada.

El bot de avisos ya atiende a los dueños con un menú declarativo ([ADR-007](ADR-007-bot-de-duenos.md)), y los datos del estado ya existen: alertas (`ops_alert`), muestras del sistema (`system_sample`), contenedores y backups (ficheros de `OPS_STATE_DIR`), trabajos (`procrastinate_jobs`) y la salud de cada negocio (`ops.status`).

## Decisión

- **Un menú de operador en el mismo bot**, solo en el chat de `OPS_TELEGRAM_CHAT_ID` (`owner.operator.is_operator_chat`). Opciones de `OPERATOR_MENU` (ids `ops:<nombre>`):
    - 🩺 **Estado**: «Todo en orden», «Hay avisos» o «Hay problemas» (el peor nivel entre las incidencias abiertas y la salud de los negocios), los servicios, el disco, la memoria y el tamaño de la base de datos, el último backup, la última limpieza nocturna, las incidencias abiertas y qué negocios tienen problemas.
    - 🚨 **Incidencias** (antes «Alertas»; el botón conserva el id `ops:alerts`): las abiertas, las mismas que el panel (`ops.incidents.open_incidents`), de la más grave y reciente a la menos, con desde cuándo y, en un evento reabierto, «N nuevos desde tu revisión».
    - 📊 **Hoy**: mensajes recibidos y enviados, fallos y contactos nuevos desde las 00:00 de Madrid, en total y por negocio. Las demos van juntas en una línea.
    - 🏪 **Clientes**: cada negocio real con su estado y salud y cuándo fue su último mensaje, primero los que tienen problemas. Las demos van en una sola línea.
    - 💾 **Backups**: el último backup, cuándo se caducaron copias por última vez y la limpieza nocturna.
- **Un solo menú si el chat también es dueño** de algún negocio: primero las opciones de operador y después las del dueño (`owner.menu.options`). Un chat que no es el de operador nunca ve las de operador, aunque fuerce el payload.
- **Solo consulta.** Ninguna opción cambia nada. Las acciones (revisar incidencias, reintentar trabajos, pausar un negocio) siguen en el panel, que tiene túnel, contraseña y segundo factor. Las respuestas no llevan datos personales: solo cifras, estados y nombres de negocio.
- **Resumen diario** (`ops.daily`, trabajo `ops_daily_summary`, cada hora en el minuto 5): la primera pasada desde las 09:00 de Madrid manda al chat de operación el Estado y las cifras de ayer. Sale aunque no haya pasado nada, para que su ausencia se note. Una clave de caché por día (`ops:daily:<fecha>`) lo reclama antes de enviar, así que sale como mucho una vez. Solo se libera si el envío seguro que no salió (`RetryLater`), y entonces lo reintenta la hora siguiente. Un envío ambiguo no se repite.
- **Datos y texto separados.** `ops.report` lee el estado como datos (dataclasses, sin texto) y `ops.report_text` lo convierte en mensajes, con funciones puras. Cambiar una cifra o una frase no toca lo otro, y una opción nueva es una entrada más de `OPERATOR_MENU`.
- **Bajo RLS, como el resto de los workers.** El bot se atiende en `worker-inbound` y el resumen en `worker-periodic`, ambos como `fp_app`: las tablas de plataforma se leen directamente y las cifras de cada negocio dentro de su `tenant_tx`, de una en una. El panel, en cambio, agrupa por `tenant_id` con el rol `owner`.
- **Dentro de los límites comunes.** Las listas que crecen (incidencias, clientes) muestran como mucho 15 elementos y remiten al panel para el resto, así que un texto nunca pasa de 4.096 caracteres. Si una respuesta no cabe en el cuerpo de un interactivo (1.024), va como texto propio y el menú detrás («¿Algo más?»). Si el segundo envío falla, no se reintenta nada, para no repetir el primero.
- **El chat de operación no cuenta como desconocido** en el límite de eventos de chats sin negocio (`stranger_limiter`).

## Alternativas consideradas

- **Acciones desde Telegram (resolver, reintentar, pausar).** Descartada por ahora: quien entre en la cuenta de Telegram del operador podría tocar producción, sin el túnel ni el segundo factor del panel. Si se añade alguna, será inofensiva y con confirmación.
- **Un bot aparte para el operador.** Descartada: es otro token, otro webhook y otra configuración para lo mismo. El bot de avisos ya escribe a ese chat y ya tiene menú.
- **Leer las cifras con el rol `owner`, como el panel.** Descartada: los workers no tienen esa credencial a propósito (`check_prod_config.py` lo exige). Una consulta por negocio cuesta poco con los negocios que hay.
- **Enviar el resumen diario como una alerta `info`.** Descartada: las alertas son problemas que se abren y se cierran, y una diaria llenaría `ops_alert` y el historial del panel.

## Consecuencias

- El operador puede preguntar el estado desde Telegram y recibe cada mañana un resumen. Que no llegue es una señal más, junto al latido de Healthchecks.
- `OPS_TELEGRAM_CHAT_ID` pasa de destino de alertas a dar acceso a esta información: quien esté en ese chat (un grupo, si se cambia a uno) ve el estado de la plataforma.
- «Hoy» y «Clientes» hacen una o dos consultas por negocio, dentro de su RLS. Con cientos de negocios tardan algo más, pero no bloquean nada: es un trabajo de la cola `inbound`.
- El menú de un chat que es a la vez de operador y de dueño tiene hasta ocho opciones, en una lista.

## Cuándo revisarla

- Si el operador necesita actuar desde el móvil con frecuencia: valorar acciones concretas con confirmación, y si hace falta un segundo factor en el bot.
- Si con muchos negocios «Hoy» o «Clientes» tardan segundos: pasar a cifras precalculadas (por ejemplo, en `ops_check`) en vez de consultar negocio a negocio.
- Si el chat de operación pasa a ser un grupo con gente que no debe ver todo el estado.
