# Alertas e incidencias de operación

Catálogo de las claves (`kind`) de las incidencias que abre la plataforma: qué significan,
cuándo se abren, cómo se cierran y qué runbook seguir. Léelo cuando llegue un aviso al chat de
operación o veas una incidencia abierta en el panel (Incidencias). El índice por síntoma está
en [incidencias](../incidencias/README.md); el concepto, en
[observabilidad](../arquitectura/observabilidad.md); la decisión, en el
[ADR-031](../arquitectura/adr/ADR-031-incidencias-como-bandeja.md).

## Cómo funcionan

Una **incidencia** es una fila de `ops_alert`: una por cada periodo abierto de una clave y un
negocio (`(kind, tenant_id)`; las de plataforma no llevan negocio y su texto no empieza por
un slug). Cada clave, exacta o por prefijo (`queue_lag:`), está declarada en el registro
`apps/backend/src/autobot/ops/incidents.py` con su **naturaleza**, su título y consejo en
español y sus casos:

- **Condición** («está mal ahora»: un contenedor caído, el disco, una cola atrasada, envíos
  ambiguos sin decidir…). `ops_check` la abre mientras dura la causa y la cierra sola
  (`resolved_by = auto`) en cuanto deja de encontrarla. Si era 🔴, avisa con «✅ Resuelta».
- **Evento** («pasó algo»: un envío rechazado, un trabajo fallido, un contenedor reiniciado,
  el umbral de coste superado, un despliegue abortado). Queda abierto hasta que una persona
  pulsa **«Lo he revisado»** en el panel (`POST /api/panel/incidents/{id}/review`, auditado
  como `incident.review`, ver [auditoría](auditoria.md)). La revisión guarda una **marca de
  revisión** (`review_watermark`): los casos hasta ella cuentan como revisados.

**Casos.** Los envíos, trabajos y avisos afectados son casos de su incidencia. Se calculan en
vivo desde sus tablas en cada pasada (`apps/backend/src/autobot/ops/cases.py`) y nunca se
copian a `ops_alert`, que no tiene RLS: solo se guardan su número (`case_count`) y la fecha del
más reciente (`last_case_at`). La hora de un caso es **cuándo se convirtió en fallo**
(`failed_at` de un envío rechazado o de un aviso perdido, `unknown_at` de un envío ambiguo, el
último evento `failed` de un trabajo), no cuándo se creó la fila: un reenvío de un envío
antiguo que luego falla es un caso nuevo. Las filas anteriores a `failed_at` usan su
`created_at`. En Incidencias el recuento de cada incidencia con casos se calcula en vivo al
abrir la pantalla; el texto (`text`) conserva las cifras de la última pasada. `details` guarda datos del tipo sin datos personales (el
recuento de reinicios visto, el mes de `billing`, la clase de error).

**Reapertura.** Un caso posterior a la marca de revisión abre una fila nueva de la misma clave
que **hereda la marca**: solo cuentan los casos nuevos, y el panel y el bot dicen «N nuevos
desde tu revisión». La marca es la fecha del caso más reciente que vio `ops_check` (no la hora
del clic), y nunca posterior al caso más reciente que mostraba el panel, así que un caso que
llega mientras se lee la pantalla vuelve a abrirla. El panel no devuelve esa hora, sino el
`seen_through` de la incidencia: una referencia opaca con la hora exacta, hasta el microsegundo,
que el backend generó y descifra. La API recorta las horas a milisegundos, y una marca hecha con
la hora recortada quedaba unas millonésimas antes del caso y lo reabría en cada pasada. Sin
`seen_through` (una pestaña abierta antes de este cambio) se usa la hora guardada del caso.
Nunca retrocede respecto a la marca anterior. Una revisión que llega mientras `ops_check` está
en mitad de una pasada no provoca una reapertura falsa: los eventos revisados desde que empezó
la pasada no se vuelven a abrir con sus cifras. Sin ninguna revisión previa de una clave, solo
cuentan los casos de las **últimas 24 h**: una primera pasada nunca saca meses de historia a la
vez.

**Eventos vacíos.** Un evento con casos en tabla (`outbound_rejected:<clase>`,
`notification_failed`, `failed_job:<tarea>`) que se queda sin ningún caso vivo (se reintentó
bien el trabajo, un envío rechazado resultó entregado) **se cierra solo** como cierre de la
plataforma (`resolved_by = auto`): sin mensaje, sin tocar la marca y sin contar como revisión.
Un caso posterior abre un periodo nuevo. Del mismo modo, tras «Marcar enviado», «Reenviar»,
«Descartar» o «Descartar todos» se reevalúa en el acto `outbound_ambiguous` del negocio, y tras
«Reintentar» un trabajo, su `failed_job:<tarea>`: se cierran si no queda ningún caso.

**Severidad.** Sale del emoji inicial del texto: 🔴 `critical`, 🟠 `warning`, 🟡 `notice`,
🟢 `info`. Se actualiza en cada pasada (sube o baja dentro de la misma incidencia). El nivel de
un negocio, del Resumen y del bot sale de las incidencias abiertas: una 🟡 lo deja en
`notice`, nunca más alto; `info` nunca cuenta ([estados de negocio](estados-de-negocio.md)).

**Avisos por Telegram** (`send_ops_alert`, `apps/backend/src/autobot/runtime/notifications.py`),
al chat `OPS_TELEGRAM_CHAT_ID` por el bot de avisos:

- Solo 🔴 y 🟠 avisan, y solo **al abrirse**. Una incidencia que sigue abierta no se repite.
- 🟡 no avisa nunca (`last_delivery = panel`): queda en el panel y en el resumen diario.
- Cada **apertura**, sea condición o evento (una condición que va y viene, una reapertura tras
  una revisión), avisa como mucho una vez por hora por clave y negocio, contando desde el último
  aviso de esa clave (`last_delivery = throttled` si no toca). Si su apertura no avisó, su cierre
  tampoco manda «✅ Resuelta».
- Si la severidad **sube** dentro de una incidencia abierta, se actualiza y avisa: a 🔴
  **siempre** (una crítica nunca espera) y a 🟠 como mucho una vez por hora por clave.
- Excepción: `deploy_aborted` y `deploy_rollback` avisan **en cada caso nuevo** (cada despliegue
  fallido importa), sin límite horario.
- Una revisión no manda nada. Las informativas (`deploy_ok`…) nacen cerradas y avisan siempre.
- Un aviso que **no llegó** (`last_delivery` `failed` o `unconfigured`) se reintenta como mucho
  una vez por hora mientras la incidencia siga abierta, sin contar como aviso nuevo
  (`retry_undelivered`).

Además, `ops_check` toma una muestra del sistema (CPU, memoria, disco, tamaño de la BD) y, si
existe `HEALTHCHECKS_PING_URL`, hace el latido a healthchecks.io **solo si todo lo anterior
terminó sin error** (un fallo de BD no manda un latido falso). Si hay una incidencia crítica
abierta cuyo aviso a Telegram no llegó desde hace más de 15 minutos, el canal de avisos está
roto (token revocado, `OPS_TELEGRAM_CHAT_ID` erróneo): en vez del latido se llama a
`<HEALTHCHECKS_PING_URL>/fail`, para que healthchecks.io avise por su propio canal. En cuanto
Telegram vuelve a aceptar el reintento horario, el aviso pasa a `sent` y el latido vuelve solo.

En las tablas, «Cierre» dice la naturaleza y cuándo se cierra.

## Cola y tareas

| Clave | Significado y umbral | Cierre | Runbook |
|---|---|---|---|
| `inbound_delay` | 🔴 Hay un trabajo `inbound` o `inbound_ext` listo (`todo`) que debería haber empezado hace más de 2 minutos. Se calcula con la misma consulta de edades que `queue_lag:<cola>`; se mantiene aparte porque es el único retraso que un cliente final nota (no le contestamos) y por eso es 🔴. | Condición: se cierra sola | [Cola y latido](../incidencias/cola-y-latido.md) |
| `queue_lag_unknown` | 🟠 Plataforma: la consulta de atraso de las colas falló o superó el tiempo máximo (backlog enorme). `ops_check` sigue y da su latido; mira el backlog a mano. | Condición: se cierra sola cuando la consulta vuelve a responder | [Cola y latido](../incidencias/cola-y-latido.md) |
| `queue_lag:<cola>` | 🟠 Plataforma: una cola va retrasada. Dos condiciones por cola: el trabajo listo más antiguo lleva esperando más del límite (`outbound` 5 min, `ops` 10 min, `periodic` 20 min) o un trabajo lleva «en curso» más de 15 minutos (1 hora en `periodic`, donde viven las barridas y la limpieza). La espera se mide desde `scheduled_at`, no desde la creación: los `run_periodic` se programan a propósito repartidos en una ventana de 15 minutos y no cuentan como retraso hasta que les toca. `inbound` e `inbound_ext` no tienen límite de espera aquí: los cubre `inbound_delay` (🔴, 2 minutos); solo se vigila su «en curso». | Condición: se cierra sola | [Cola y latido](../incidencias/cola-y-latido.md) |
| `failed_job:<tarea>` | 🟠 Plataforma, una por tarea (con su nombre en español): trabajos en estado `failed` cuyo último evento `failed` es posterior a la marca de revisión. Casos: esos trabajos, con «Reintentar» si la tarea es idempotente (`send_message` y `send_notification` no se reintentan a ciegas). Un trabajo parado que `retry_stalled_jobs` no pudo reencolar porque otro igual ya estaba en cola (mismo `queueing_lock`, p. ej. el siguiente `ops_check`) se cierra como `aborted`, no `failed`: no es un fallo y no abre incidencia. | Evento: «Lo he revisado» | [Trabajos fallidos](../incidencias/cola-y-latido.md#trabajos-fallidos) |
| `check_failed` | 🟠 Por negocio: la comprobación de ese negocio lanzó una excepción (el resto se comprueba igual y el latido se envía). Sus demás alertas abiertas no se resuelven solas mientras dure. Detalle en los logs del worker (solo el id del tenant). | Condición: se cierra sola cuando una comprobación completa del negocio vuelve a terminar | [Cola y latido](../incidencias/cola-y-latido.md) |
| `inbound_stuck` | 🔴 Por negocio: eventos entrantes `pending` sin trabajo vivo desde hace más de 5 minutos. El barrido los reencola si tienen menos de 1 hora. | Condición: se cierra sola | [Cola y latido](../incidencias/cola-y-latido.md) |
| `outbound_stuck` | 🟠 Por negocio: envíos `pending` sin trabajo vivo y demasiado antiguos (más de 24 h) para reencolarlos. Los `pending` más recientes se reencolan solos; un `sending` sin trabajo pasa a `unknown` y lo cubre `outbound_ambiguous`. | Condición: se cierra sola | [Envíos unknown](../incidencias/envios-unknown.md) |
| `outbound_ambiguous` | 🟠 Por negocio: envíos `unknown` desde hace más de 20 minutos (la espera de un estado y la conciliación automática del ADR-026 no lo resolvieron), sin límite de antigüedad. Casos: esos envíos, con «Marcar enviado», «Reenviar» y «Descartar». | Condición: se cierra sola cuando no queda ninguno sin decidir | [Envíos unknown](../incidencias/envios-unknown.md) |
| `outbound_rejected:<clase>` | 🟠 Por negocio y clase de error (🟡 si la causa es del destinatario: `blocked`, `undeliverable`, `marketing_declined`): envíos que pasaron a `failed` después de la marca de revisión. La clase la da el adaptador del canal (`outside_window`, `undeliverable`, `blocked`, `rate`, `marketing_declined`, `spam_limit`, `other`) o la plataforma (`expired_payload`, `channel_disabled`); el título y el consejo, `apps/backend/src/autobot/ops/send_errors.py`. `auth` no abre esta incidencia: es la condición `auth`. Un envío `expired` o `discarded` no cuenta. Casos: esos envíos, con su motivo. | Evento: «Lo he revisado»; un rechazo nuevo la reabre | [Envíos rechazados](../incidencias/envios-unknown.md#envios-rechazados) |
| `provider_outage` | 🟠 Plataforma: el cortacircuitos de WhatsApp o Telegram del worker de salida está abierto (5 fallos de transporte seguidos de al menos 2 negocios distintos). Una sola alerta con los proveedores afectados, en lugar de una por mensaje. Los envíos esperan y se reintentan solos; los que caducan quedan `expired` (las respuestas, con una disculpa). Si la señal no se refresca en 10 minutos, se da por cerrada. Mientras dura, y 20 minutos después, no se crean las alertas `health:whatsapp_unavailable` o `health:telegram_unavailable` de cada negocio (las que ya estaban abiertas se resuelven sin mensaje): una caída de Meta con 300 negocios llegó a abrir 97. | Condición: se cierra sola al cerrarse el cortacircuitos (una sonda correcta) | [Envíos unknown](../incidencias/envios-unknown.md#caida-de-un-proveedor) |
| `calendar_outage` | 🔴 Plataforma: Google Calendar falla a la vez en al menos 5 negocios con calendario y en el 30 % o más de ellos (`calendar:<canal>` o `health:<canal>:calendar_unavailable` en la misma pasada). Una sola alerta con el recuento. Mientras dura, y 20 minutos después, **no se crean** las alertas por negocio que la misma caída provoca (`calendar:<canal>`, `health:<canal>:calendar_unavailable`, `errors:<canal>`), y las que ya estaban abiertas se resuelven sin mensaje. Con pocos negocios afectados (un calendario sin compartir) cada uno alerta por separado. | Condición: se cierra sola cuando deja de cumplirse (solo ella avisa de la recuperación) | [Calendar](../incidencias/calendar.md#caida-general-de-google) |
| `owner_unlinked` | 🟡 Por negocio real y activo (no de demo): el negocio no tiene chat de avisos conectado y hay avisos al dueño `held`, o `expired` en las últimas 24 h (`reconcile.expire_held` pasa los `held` a `expired` a las 2 h; contarlos evita que se cierre sola sin arreglar nada). Casos: esos avisos (sin su texto). Salen solos al conectarlo (los de menos de 2 h). | Condición: se cierra sola al conectar el chat o caducar los avisos | [Envíos unknown](../incidencias/envios-unknown.md#avisos-retenidos) |
| `notification_failed` | 🟠 Por negocio, con el chat del dueño y el bot de avisos configurados: avisos al dueño `failed` (rechazados o ambiguos, nunca se reenvían a ciegas) o `expired` (más de 2 h sin entregarse) que pasaron a ese estado después de la marca de revisión. Casos: esos avisos. | Evento: «Lo he revisado» | [Envíos unknown](../incidencias/envios-unknown.md) |

Detalles de los barridos de trabajo atascado en `apps/backend/src/autobot/runtime/sweeps.py`.

## Negocios y canales

`<canal>` es el canal con el que corre el negocio: `main`, `demo_tg` o `demo_wa`.

| Clave | Significado y umbral | Cierre | Runbook |
|---|---|---|---|
| `config_stale` | 🟠 Plataforma: un proceso vivo (`web`, `web-panel` o un worker) tiene una revisión de la configuración **distinta** de la de la base de datos (atrasado, o por delante si la base se restauró) más de 1 minuto contado desde que **ese proceso** se vio así por primera vez, o lleva más de 1 minuto con las comprobaciones o recargas de la configuración fallando. Lo normal es que se ponga al día en unos 2 s. El texto nombra los servicios. No cubre un servicio sin ningún proceso vivo en la tabla (lo cubren las alertas de contenedores). | Condición: se cierra sola cuando todos los procesos vivos están al día y sin error (o el proceso deja de latir) | [Un negocio o canal no responde](../incidencias/negocio-o-canal.md#proceso-con-configuracion-desactualizada) |
| `registry` | 🔴 Hay configuraciones de negocio o secretos ilegibles al cargar el registro. | Condición: se cierra sola al corregirse | [Un negocio o canal no responde](../incidencias/negocio-o-canal.md) |
| `tenant_unavailable` | 🔴 Por negocio: degradado, o (si no es demo) con el canal principal sin secretos o sin configuración completa. | Condición: se cierra sola | [Un negocio o canal no responde](../incidencias/negocio-o-canal.md) |
| `errors:<canal>` | 🔴 Por negocio y canal: tres errores seguidos al procesar mensajes o ejecutar periodics. Un éxito pone el contador a cero. | Condición: se cierra sola al primer éxito | [Un negocio o canal no responde](../incidencias/negocio-o-canal.md) |
| `auth` | 🔴 Por negocio: un envío del canal principal fue rechazado por autenticación (`last_error` empieza por `auth:` en las últimas 24 h). | Condición: se cierra sola a las 24 h del último rechazo o en cuanto sale bien un envío posterior de ese canal (la credencial vuelve a funcionar) | [Un negocio o canal no responde](../incidencias/negocio-o-canal.md) y [rotar secretos](../procedimientos/rotar-secretos.md) |
| `auth:<canal>` | 🔴 Plataforma: la puerta de demo (`demo_tg` o `demo_wa`) fue rechazada por autenticación. | Condición: se cierra sola | [Un negocio o canal no responde](../incidencias/negocio-o-canal.md) y [rotar secretos](../procedimientos/rotar-secretos.md) |
| `tenant_silent` | 🟠 Por negocio activo (no demo) con canal principal habilitado: sin mensajes de clientes desde hace más de `max(48 h, 3 × la mediana del hueco entre mensajes de los últimos 14 días)`. No avisa si ha visto menos de 5 mensajes (negocio nuevo) ni si no queda historial (retención de 90 días). No modela el horario comercial: las 48 h mínimas cubren el fin de semana. | Condición: se cierra sola al llegar un mensaje | [Negocio en silencio](../incidencias/negocio-o-canal.md#negocio-en-silencio) |
| `webhook_unsubscribed` | 🔴 Por negocio, una vez al día: la app de Meta ya no figura en `GET /{waba}/subscribed_apps` (o, en Telegram, `getWebhookInfo` no apunta a nuestra URL). Dejan de llegar mensajes. | Condición: se cierra sola | [Webhook sin suscripción](../incidencias/negocio-o-canal.md#webhook-sin-suscripcion) |
| `webhook_errors` | 🔴 Telegram registra errores de entrega del webhook en el último día; 🟠 si tiene más de 100 actualizaciones pendientes. | Condición: se cierra sola | [Webhook sin suscripción](../incidencias/negocio-o-canal.md#webhook-sin-suscripcion) |
| `number_quality` | 🟠 Calidad `YELLOW` del número de WhatsApp; 🔴 calidad `RED` o estado `RESTRICTED`, `FLAGGED`, `BANNED`, `DISCONNECTED`, `OFFLINE`. El texto incluye el nivel de límite de mensajes. | Condición: se cierra sola | [Calidad del número](../incidencias/negocio-o-canal.md#calidad-del-numero) |
| `billing` | 🟡 Por negocio de WhatsApp: los mensajes facturables del canal principal en el mes (zona del negocio) superan `monthly_alert_threshold` (por defecto 2000). Una vez por mes natural: revisada en un mes, no vuelve hasta el siguiente (`details.month`). | Evento: «Lo he revisado» | Sin runbook: avisa del coste, ver [alta y baja de un negocio](../procedimientos/alta-baja-negocio.md) |
| `billing:demo_wa` | 🟡 Plataforma: mensajes facturables de la puerta WhatsApp de demo en el mes superan `DEMO_WHATSAPP_MONTHLY_ALERT_THRESHOLD` (por defecto 300). Una vez por mes natural. | Evento: «Lo he revisado» | Sin runbook: ver [variables de entorno](variables-entorno.md) |

## Google Calendar y barrido (`salon`)

| Clave | Significado y umbral | Cierre | Runbook |
|---|---|---|---|
| `calendar:<canal>` | 🔴 Por negocio y canal: Calendar denegó el acceso, o hubo tres errores seguidos. Un acceso correcto lo limpia. | Condición: se cierra sola | [Calendar](../incidencias/calendar.md) |
| `sweep:<canal>` | 🟠 Por negocio y canal, solo si el pack declara `calendar_sweep`: el barrido no se ha completado en más de 1 hora. | Condición: se cierra sola al completarse un barrido | [Calendar](../incidencias/calendar.md) |

## Salud diaria (`health:*` y `bot:*`)

La salud se comprueba con una caché: un resultado correcto vale 24 horas; uno con problemas se
vuelve a comprobar a los 15 minutos (`apps/backend/src/autobot/ops/health.py`, `daily`). El
mismo resultado alimenta el [estado de negocio](estados-de-negocio.md). Todas se resuelven
solas cuando la siguiente comprobación sale limpia.

`health:<código>` es por negocio, con la severidad del propio problema. Los códigos
`webhook_unsubscribed`, `number_quality` y los de webhook de Telegram de un negocio
(`telegram_webhook_unregistered`, `telegram_webhook`, `telegram_webhook_backlog`) se publican
con clave propia (`webhook_unsubscribed`, `number_quality`, `webhook_errors`; ver arriba).
Códigos:

| Código | Significado | Severidad | Runbook |
|---|---|---|---|
| `degraded` | El negocio está degradado (config inválida). | 🔴 | [Un negocio o canal no responde](../incidencias/negocio-o-canal.md) |
| `channel_disabled` | El canal principal no tiene configuración completa. | 🔴 | [Un negocio o canal no responde](../incidencias/negocio-o-canal.md) |
| `<canal>:calendar_unavailable` | El pack no puede acceder al calendario. | 🔴 | [Calendar](../incidencias/calendar.md) |
| `<canal>:pack_health` | Falló la propia comprobación de salud del pack. | 🔴 | [Calendar](../incidencias/calendar.md) |
| `auth` | Telegram o Meta rechazan el token del negocio. | 🔴 | [rotar secretos](../procedimientos/rotar-secretos.md) |
| `telegram_unavailable` | No se puede consultar a Telegram (error distinto de 401 o 403). | 🔴 | [Un negocio o canal no responde](../incidencias/negocio-o-canal.md) |
| `telegram_response` | Respuesta de Telegram inválida. | 🔴 | [Un negocio o canal no responde](../incidencias/negocio-o-canal.md) |
| `telegram_webhook_unregistered` | El webhook de Telegram no apunta a la URL esperada. | 🔴 | [Un negocio o canal no responde](../incidencias/negocio-o-canal.md) |
| `telegram_webhook` | Telegram registra errores del webhook en el último día. | 🔴 | [Un negocio o canal no responde](../incidencias/negocio-o-canal.md) |
| `whatsapp_unavailable` | No se puede consultar a Meta. | 🔴 | [Alta de WhatsApp en Meta](../procedimientos/alta-whatsapp-meta.md) |
| `whatsapp_response` | Respuesta de Meta inválida (paginación de plantillas). | 🔴 | [Alta de WhatsApp en Meta](../procedimientos/alta-whatsapp-meta.md) |
| `templates` | Faltan plantillas de WhatsApp aprobadas del pack. | 🟠 | [Alta de WhatsApp en Meta](../procedimientos/alta-whatsapp-meta.md) |

`bot:<bot>:<código>` es lo mismo para los bots de la plataforma, sin negocio (`bot:demo_tg:<código>`,
`bot:notify:<código>` y `bot:demo_wa:<código>`). `<bot>` es
`demo_tg` (bot de demo de Telegram), `notify` (bot de avisos) o `demo_wa` (puerta WhatsApp de
demo). Los códigos son los de la tabla anterior que aplican a Telegram (`auth`,
`telegram_unavailable`, `telegram_response`, `telegram_webhook_unregistered`,
`telegram_webhook`) y a WhatsApp (`auth`, `whatsapp_unavailable`, `whatsapp_response`,
`templates`). Solo se comprueban los bots con token o credenciales configurados. Además:

| Clave | Significado | Cierre | Runbook |
|---|---|---|---|
| `bot:notify:auth` | 🔴 El bot de avisos fue rechazado por autenticación al enviar un aviso. | Condición: se cierra sola | [rotar secretos](../procedimientos/rotar-secretos.md) |

## Servidor y despliegue

| Clave | Significado y umbral | Cierre | Runbook |
|---|---|---|---|
| `disk` | 🟠 Disco por encima del 80 %. Se mide el mayor uso entre `/` del contenedor (el sistema de ficheros de Docker: imágenes, volumen de PostgreSQL y temporales del backup) y `/run/ops` (`/srv/autobot/var/state/ops` del host). | Condición: se cierra sola | [Disco lleno](../procedimientos/mantenimiento.md#disco-lleno) |
| `disk_critical` | 🔴 Disco por encima del 95 %. | Condición: se cierra sola | [Disco lleno](../procedimientos/mantenimiento.md#disco-lleno) |
| `inodes` | 🟠 Inodos del disco por encima del 80 % (mismos sistemas de ficheros que `disk`). Sin inodos libres no se pueden crear ficheros aunque queden bytes. No aplica a sistemas de ficheros sin tabla fija de inodos. | Condición: se cierra sola | [Inodos agotados](../incidencias/recursos-copias-y-certificado.md#inodos-agotados) |
| `inodes_critical` | 🔴 Inodos del disco por encima del 95 %. | Condición: se cierra sola | [Inodos agotados](../incidencias/recursos-copias-y-certificado.md#inodos-agotados) |
| `memory_high` | 🟠 Memoria usada por encima del 90 % de forma sostenida: la lectura de esta pasada **y** la muestra anterior (de hace menos de 15 minutos) la superan. | Condición: se cierra sola | [Memoria, swap o carga altas](../incidencias/recursos-copias-y-certificado.md#memoria-swap-o-carga-altas) |
| `load_high` | 🟠 Carga del sistema (`load1`) por encima de 2 por CPU de forma sostenida (esta lectura y la muestra anterior). | Condición: se cierra sola | [Memoria, swap o carga altas](../incidencias/recursos-copias-y-certificado.md#memoria-swap-o-carga-altas) |
| `swap_high` | 🟠 Swap en uso por encima del 50 % (`/proc/meminfo` del host). Usar swap ya es una condición sostenida, así que basta una lectura. | Condición: se cierra sola | [Memoria, swap o carga altas](../incidencias/recursos-copias-y-certificado.md#memoria-swap-o-carga-altas) |
| `backup_stale` | 🟠 Plataforma: el último backup terminó con error (`ok: false` en `var/state/ops/backup.json`) o hace más de 3 horas que no termina ninguno (el timer es horario). Solo fuera de local y con ese fichero. | Condición: se cierra sola al terminar un backup bien | [Backup atrasado o fallido](../incidencias/recursos-copias-y-certificado.md#backup-atrasado-o-fallido) |
| `tls_expiring` | 🟠 El certificado público (host de `PUBLIC_URL`, puerto 443) caduca en menos de 14 días: Caddy debería haberlo renovado. Se comprueba una vez al día (cada 15 minutos mientras falla). Solo fuera de local. | Condición: se cierra sola al renovarse | [Certificado a punto de caducar](../incidencias/recursos-copias-y-certificado.md#certificado-a-punto-de-caducar) |
| `tls_expiring_critical` | 🔴 El certificado caduca en menos de 3 días. | Condición: se cierra sola | [Certificado a punto de caducar](../incidencias/recursos-copias-y-certificado.md#certificado-a-punto-de-caducar) |
| `tls_invalid` | 🔴 El certificado que sirve el proxy no valida (caducado, cadena o nombre incorrectos). Los webhooks de Meta y Telegram fallan. | Condición: se cierra sola | [Certificado a punto de caducar](../incidencias/recursos-copias-y-certificado.md#certificado-a-punto-de-caducar) |
| `backup_prune_overdue` | 🟡 Plataforma: hace más de 10 días que el operador no purga las copias (testigo `autobot-prune`; si nunca purgó, desde el snapshot más antiguo). Lo lee `backup.sh` en `var/state/ops/backup-prune.json` (ADR-025). Solo fuera de local y con ese fichero. | Condición: se cierra sola al purgar y pasar el siguiente backup | [Caducar snapshots](../procedimientos/backups.md#caducar-snapshots) |
| `containers_stale` | 🟠 Sin estado de contenedores, o sin actualizar desde hace más de 3 minutos. Solo fuera de local. | Condición: se cierra sola | [Contenedor caído](../incidencias/contenedor-caido.md) |
| `containers_restore` | 🟠 Restauración a medias: existe `var/.restore-incomplete`. | Condición: se cierra sola al terminar la restauración | [Restaurar](../procedimientos/restaurar.md) |
| `container_down:<servicio>` | 🔴 (🟠 si es `victorialogs`) El contenedor no existe, está parado o se reinicia en bucle. | Condición: se cierra sola | [Contenedor caído](../incidencias/contenedor-caido.md) |
| `container_unhealthy:<servicio>` | 🔴 El contenedor está en marcha pero su healthcheck falla. | Condición: se cierra sola | [Contenedor caído](../incidencias/contenedor-caido.md) |
| `container_restarted:<servicio>` | 🟠 El número de reinicios del contenedor creció respecto al que guardó su última incidencia (`details.restart_count`); sin incidencia previa, un reinicio en los últimos 30 minutos. Un contenedor recreado (recuento a 0) solo baja el número guardado; si su incidencia sigue abierta, conserva los reinicios ya contados. | Evento: «Lo he revisado»; un reinicio nuevo la reabre | [Contenedor caído](../incidencias/contenedor-caido.md) |
| `container_image:<servicio>` | 🟠 La imagen de `web`, `web-panel`, de cualquiera de los cuatro workers o de `panel` no es la del SHA desplegado. | Condición: se cierra sola | [Contenedor caído](../incidencias/contenedor-caido.md) |
| `container_unexpected:<servicio>` | 🟠 Hay un contenedor que no debería existir (¿huérfano de un despliegue?). | Condición: se cierra sola | [Contenedor caído](../incidencias/contenedor-caido.md) |
| `deploy_aborted` | 🔴 El despliegue se abortó antes de cambiar la imagen. Lo emite `deploy/scripts/deploy.sh`; cada llamada es un caso más y avisa por Telegram. | Evento: «Lo he revisado» | [Volver atrás un despliegue](../incidencias/volver-atras.md) |
| `deploy_rollback` | 🔴 El despliegue falló y se revirtió automáticamente. Lo emite `deploy/scripts/deploy.sh`; cada llamada es un caso más y avisa por Telegram. | Evento: «Lo he revisado» | [Volver atrás un despliegue](../incidencias/volver-atras.md) |
| `deploy_ok`, `deploy_caddy_reload`, `deploy_https_check` | Avisos informativos de `deploy.sh` (desplegado, recarga de Caddy fallida, HTTPS sin respuesta). Nacen cerradas (`resolved_by = info`) y siempre avisan. | Informativa | [Volver atrás un despliegue](../incidencias/volver-atras.md) |

Mientras hay un despliegue en curso (`maintenance = deploy`) no se generan incidencias de
contenedores. Los servicios esperados son `caddy`, `web`, `web-panel`, `worker-inbound`,
`worker-calendar`, `worker-periodic`, `worker-outbound`, `panel`, `db` y `victorialogs`. La evaluación está en
`apps/backend/src/autobot/ops/containers.py`.

## Dónde está el código

- `apps/backend/src/autobot/ops/check.py` (`collect`, `sync_alerts`, `run`): la lista de
  claves del chequeo.
- `apps/backend/src/autobot/ops/health.py` (`Issue`, `daily`) y
  `apps/backend/src/autobot/ops/containers.py` (`assess`): códigos de salud y de contenedores.
- `apps/backend/src/autobot/ops/incidents.py`: el registro de claves (naturaleza, título,
  consejo, casos), las incidencias abiertas, las marcas de revisión y «Lo he revisado».
- `apps/backend/src/autobot/ops/cases.py`: los casos de cada incidencia.
- `apps/backend/src/autobot/runtime/notifications.py` (`send_ops_alert`, `retry_undelivered`,
  `resolve_alert`): apertura, avisos, severidad y cierre.
- `deploy/scripts/deploy.sh` (`alert_ops`): alertas de despliegue.
- Prueba de coherencia: `apps/backend/tests/repo/test_docs_coherence.py` exige que cada clave
  (de `check.py`, `containers.py`, `deploy.sh` y el registro) esté aquí.

## Relacionado

[Incidencias](../incidencias/README.md), [estados de negocio](estados-de-negocio.md),
[observabilidad](../arquitectura/observabilidad.md).
