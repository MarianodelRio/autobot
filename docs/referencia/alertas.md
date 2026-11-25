# Alertas de operación

Catálogo de las claves (`kind`) de las alertas que abre la plataforma: qué significan, cuándo
saltan, si se resuelven solas y qué runbook seguir. Léelo cuando llegue un aviso al chat de
operación o veas una alerta abierta en el panel (Incidencias). El índice por síntoma está en
[incidencias](../incidencias/README.md); el concepto, en
[observabilidad](../arquitectura/observabilidad.md).

## Cómo funcionan

`ops_check` (`apps/backend/src/autobot/ops/check.py`) corre cada cinco minutos en el worker.
Cada comprobación produce `Finding(kind, tenant_id, texto)`. `sync_alerts` hace tres cosas:

- Por cada hallazgo, `send_ops_alert` crea o actualiza una alerta abierta por
  `(kind, tenant_id)` y la manda por el bot de avisos al chat `OPS_TELEGRAM_CHAT_ID`. Tras
  enviarla, **no repite el aviso en 30 minutos** (enfriamiento), aunque siga abierta.
- La **severidad** sale del emoji inicial del texto: 🔴 `critical`, 🟠 `warning`, 🟡 `notice`,
  🟢 `info`.
- Las alertas abiertas que se resuelven solas (`auto_resolves`) y ya no aparecen en los
  hallazgos se cierran (`resolved_by = auto`). Si eran críticas, además se avisa al chat con
  «Resuelta». Al cerrarse se borra el enfriamiento, así que un problema que vuelve avisa de
  inmediato.

Las alertas de un negocio llevan su `tenant_id` y el texto empieza por el slug
(`<slug>: ...`). Las de plataforma no llevan tenant. Una alerta manual solo la cierra una
persona desde el panel (acción `alert.resolve`, ver [auditoría](auditoria.md)).

Además, `ops_check` toma una muestra del sistema (CPU, memoria, disco, tamaño de la BD) y, si
existe `HEALTHCHECKS_PING_URL`, hace el latido a healthchecks.io **solo si todo lo anterior
terminó sin error** (un fallo de BD no manda un latido falso). Si hay una alerta crítica abierta cuyo envío a Telegram falló (o no hay destino) desde hace más de 15 minutos, el canal de avisos está roto (token revocado, `OPS_TELEGRAM_CHAT_ID` erróneo): en vez del latido se llama a `<HEALTHCHECKS_PING_URL>/fail`, para que healthchecks.io avise por su propio canal.

## Cola y tareas

| Clave | Significado y umbral | Se resuelve sola | Runbook |
|---|---|---|---|
| `inbound_delay` | 🔴 Hay un trabajo `inbound` o `inbound_ext` listo (`todo`) que debería haber empezado hace más de 2 minutos. Se calcula con la misma consulta de edades que `queue_lag:<cola>`; se mantiene aparte porque es el único retraso que un cliente final nota (no le contestamos) y por eso es 🔴. | Sí | [Cola y latido](../incidencias/cola-y-latido.md) |
| `queue_lag_unknown` | 🟠 Plataforma: la consulta de atraso de las colas falló o superó el tiempo máximo (backlog enorme). `ops_check` sigue y da su latido; mira el backlog a mano. | Sí, cuando la consulta vuelve a responder | [Cola y latido](../incidencias/cola-y-latido.md) |
| `queue_lag:<cola>` | 🟠 Plataforma: una cola va retrasada. Dos condiciones por cola: el trabajo listo más antiguo lleva esperando más del límite (`outbound` 5 min, `ops` 10 min, `periodic` 20 min) o un trabajo lleva «en curso» más de 15 minutos (1 hora en `periodic`, donde viven las barridas y la limpieza). La espera se mide desde `scheduled_at`, no desde la creación: los `run_periodic` se programan a propósito repartidos en una ventana de 15 minutos y no cuentan como retraso hasta que les toca. `inbound` e `inbound_ext` no tienen límite de espera aquí: los cubre `inbound_delay` (🔴, 2 minutos); solo se vigila su «en curso». | Sí | [Cola y latido](../incidencias/cola-y-latido.md) |
| `failed_jobs` | 🟠 Algún trabajo falló en los últimos 10 minutos y sigue en estado `failed`. | Sí, a los 10 minutos si no hay fallos nuevos | [Cola y latido](../incidencias/cola-y-latido.md) |
| `check_failed` | 🟠 Por negocio: la comprobación de ese negocio lanzó una excepción (el resto se comprueba igual y el latido se envía). Sus demás alertas abiertas no se resuelven solas mientras dure. Detalle en los logs del worker (solo el id del tenant). | Sí, cuando una comprobación completa del negocio vuelve a terminar | [Cola y latido](../incidencias/cola-y-latido.md) |
| `inbound_stuck` | 🔴 Por negocio: eventos entrantes `pending` sin trabajo vivo desde hace más de 5 minutos. El barrido los reencola si tienen menos de 1 hora. | Sí | [Cola y latido](../incidencias/cola-y-latido.md) |
| `outbound_stuck` | 🟠 Por negocio: envíos `pending` o `sending` sin trabajo vivo desde hace más de 10 minutos. Un `sending` pasa a `unknown`; un `pending` de menos de 24 h se reencola. | Sí | [Envíos unknown](../incidencias/envios-unknown.md) |
| `outbound_failed` | 🟠 Por negocio: envíos `failed` creados en las últimas 24 h, o `unknown` desde hace más de 20 minutos, es decir, que la conciliación automática no resolvió (y menos de 24 h). Un envío `expired` no cuenta: es un envío que caducó, no un fallo. | Sí, al salir de la ventana de 24 h o resolverse el envío | [Envíos unknown](../incidencias/envios-unknown.md) |
| `provider_outage` | 🟠 Plataforma: el cortacircuitos de WhatsApp o Telegram del worker de salida está abierto (5 fallos de transporte seguidos de al menos 2 negocios distintos). Una sola alerta con los proveedores afectados, en lugar de una por mensaje. Los envíos esperan y se reintentan solos; los que caducan quedan `expired` (las respuestas, con una disculpa). Si la señal no se refresca en 10 minutos, se da por cerrada. Mientras dura, y 20 minutos después, no se crean las alertas `health:whatsapp_unavailable` o `health:telegram_unavailable` de cada negocio (las que ya estaban abiertas se resuelven sin mensaje): una caída de Meta con 300 negocios llegó a abrir 97. | Sí, al cerrarse el cortacircuitos (una sonda correcta) | [Envíos unknown](../incidencias/envios-unknown.md#caida-de-un-proveedor) |
| `calendar_outage` | 🔴 Plataforma: Google Calendar falla a la vez en al menos 5 negocios con calendario y en el 30 % o más de ellos (`calendar:<canal>` o `health:<canal>:calendar_unavailable` en la misma pasada). Una sola alerta con el recuento. Mientras dura, y 20 minutos después, **no se crean** las alertas por negocio que la misma caída provoca (`calendar:<canal>`, `health:<canal>:calendar_unavailable`, `errors:<canal>`), y las que ya estaban abiertas se resuelven sin mensaje. Con pocos negocios afectados (un calendario sin compartir) cada uno alerta por separado. | Sí, cuando deja de cumplirse (solo ella avisa de la recuperación) | [Calendar](../incidencias/calendar.md#caida-general-de-google) |
| `owner_unlinked` | 🟡 Por negocio real y activo (no de demo): hay avisos al dueño `held` o `expired` en las últimas 24 h y el negocio no tiene chat de avisos conectado (`reconcile.expire_held` pasa los `held` a `expired` a las 2 h; contarlos evita que la alerta se cierre sola sin arreglar nada). Salen solos al conectarlo (los de menos de 2 h). | Sí, al conectar el chat o caducar los avisos | [Envíos unknown](../incidencias/envios-unknown.md#avisos-retenidos) |
| `notification_failed` | 🟠 Por negocio: avisos al dueño `failed`, ambiguos o `expired` (más de 2 h sin entregarse) en las últimas 24 h, con el chat del dueño y el bot de avisos configurados. | Sí, al salir de la ventana de 24 h | [Envíos unknown](../incidencias/envios-unknown.md) |

Detalles de los barridos de trabajo atascado en `apps/backend/src/autobot/runtime/sweeps.py`.

## Negocios y canales

`<canal>` es el canal con el que corre el negocio: `main`, `demo_tg` o `demo_wa`.

| Clave | Significado y umbral | Se resuelve sola | Runbook |
|---|---|---|---|
| `config_stale` | 🟠 Plataforma: un proceso vivo (`web`, `web-panel` o un worker) tiene una revisión de la configuración **distinta** de la de la base de datos (atrasado, o por delante si la base se restauró) más de 1 minuto contado desde que **ese proceso** se vio así por primera vez, o lleva más de 1 minuto con las comprobaciones o recargas de la configuración fallando. Lo normal es que se ponga al día en unos 2 s. El texto nombra los servicios. No cubre un servicio sin ningún proceso vivo en la tabla (lo cubren las alertas de contenedores). | Sí, cuando todos los procesos vivos están al día y sin error (o el proceso deja de latir) | [Un negocio o canal no responde](../incidencias/negocio-o-canal.md#proceso-con-configuracion-desactualizada) |
| `registry` | 🔴 Hay configuraciones de negocio o secretos ilegibles al cargar el registro. | Sí, al corregirse | [Un negocio o canal no responde](../incidencias/negocio-o-canal.md) |
| `tenant_unavailable` | 🔴 Por negocio: degradado, o (si no es demo) con el canal principal sin secretos o sin configuración completa. | Sí | [Un negocio o canal no responde](../incidencias/negocio-o-canal.md) |
| `errors:<canal>` | 🔴 Por negocio y canal: tres errores seguidos al procesar mensajes o ejecutar periodics. Un éxito pone el contador a cero. | Sí, al primer éxito | [Un negocio o canal no responde](../incidencias/negocio-o-canal.md) |
| `auth` | 🔴 Por negocio: un envío del canal principal fue rechazado por autenticación (`last_error` empieza por `auth:` en las últimas 24 h). | Sí, a las 24 h del último rechazo o en cuanto sale bien un envío posterior de ese canal (la credencial vuelve a funcionar) | [Un negocio o canal no responde](../incidencias/negocio-o-canal.md) y [rotar secretos](../procedimientos/rotar-secretos.md) |
| `auth:<canal>` | 🔴 Plataforma: la puerta de demo (`demo_tg` o `demo_wa`) fue rechazada por autenticación. | Sí | [Un negocio o canal no responde](../incidencias/negocio-o-canal.md) y [rotar secretos](../procedimientos/rotar-secretos.md) |
| `tenant_silent` | 🟠 Por negocio activo (no demo) con canal principal habilitado: sin mensajes de clientes desde hace más de `max(48 h, 3 × la mediana del hueco entre mensajes de los últimos 14 días)`. No avisa si ha visto menos de 5 mensajes (negocio nuevo) ni si no queda historial (retención de 90 días). No modela el horario comercial: las 48 h mínimas cubren el fin de semana. | Sí, al llegar un mensaje | [Negocio en silencio](../incidencias/negocio-o-canal.md#negocio-en-silencio) |
| `webhook_unsubscribed` | 🔴 Por negocio, una vez al día: la app de Meta ya no figura en `GET /{waba}/subscribed_apps` (o, en Telegram, `getWebhookInfo` no apunta a nuestra URL). Dejan de llegar mensajes. | Sí | [Webhook sin suscripción](../incidencias/negocio-o-canal.md#webhook-sin-suscripcion) |
| `webhook_errors` | 🔴 Telegram registra errores de entrega del webhook en el último día; 🟠 si tiene más de 100 actualizaciones pendientes. | Sí | [Webhook sin suscripción](../incidencias/negocio-o-canal.md#webhook-sin-suscripcion) |
| `number_quality` | 🟠 Calidad `YELLOW` del número de WhatsApp; 🔴 calidad `RED` o estado `RESTRICTED`, `FLAGGED`, `BANNED`, `DISCONNECTED`, `OFFLINE`. El texto incluye el nivel de límite de mensajes. | Sí | [Calidad del número](../incidencias/negocio-o-canal.md#calidad-del-numero) |
| `billing` | 🟡 Por negocio de WhatsApp: mensajes facturables del canal principal en el mes superan `monthly_alert_threshold` (por defecto 2000). | Sí, al empezar el mes o subir el umbral | Sin runbook: avisa del coste, ver [alta y baja de un negocio](../procedimientos/alta-baja-negocio.md) |
| `billing:demo_wa` | 🟡 Plataforma: mensajes facturables de la puerta WhatsApp de demo en el mes superan `DEMO_WHATSAPP_MONTHLY_ALERT_THRESHOLD` (por defecto 300). | Sí | Sin runbook: ver [variables de entorno](variables-entorno.md) |

## Google Calendar y barrido (`salon`)

| Clave | Significado y umbral | Se resuelve sola | Runbook |
|---|---|---|---|
| `calendar:<canal>` | 🔴 Por negocio y canal: Calendar denegó el acceso, o hubo tres errores seguidos. Un acceso correcto lo limpia. | Sí | [Calendar](../incidencias/calendar.md) |
| `sweep:<canal>` | 🟠 Por negocio y canal, solo si el pack declara `calendar_sweep`: el barrido no se ha completado en más de 1 hora. | Sí, al completarse un barrido | [Calendar](../incidencias/calendar.md) |

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

| Clave | Significado | Se resuelve sola | Runbook |
|---|---|---|---|
| `bot:notify:auth` | 🔴 El bot de avisos fue rechazado por autenticación al enviar un aviso. | Sí | [rotar secretos](../procedimientos/rotar-secretos.md) |

## Servidor y despliegue

| Clave | Significado y umbral | Se resuelve sola | Runbook |
|---|---|---|---|
| `disk` | 🟠 Disco por encima del 80 %. Se mide el mayor uso entre `/` del contenedor (el sistema de ficheros de Docker: imágenes, volumen de PostgreSQL y temporales del backup) y `/run/ops` (`/srv/autobot/var/state/ops` del host). | Sí | [Disco lleno](../procedimientos/mantenimiento.md#disco-lleno) |
| `disk_critical` | 🔴 Disco por encima del 95 %. | Sí | [Disco lleno](../procedimientos/mantenimiento.md#disco-lleno) |
| `inodes` | 🟠 Inodos del disco por encima del 80 % (mismos sistemas de ficheros que `disk`). Sin inodos libres no se pueden crear ficheros aunque queden bytes. No aplica a sistemas de ficheros sin tabla fija de inodos. | Sí | [Inodos agotados](../incidencias/recursos-copias-y-certificado.md#inodos-agotados) |
| `inodes_critical` | 🔴 Inodos del disco por encima del 95 %. | Sí | [Inodos agotados](../incidencias/recursos-copias-y-certificado.md#inodos-agotados) |
| `memory_high` | 🟠 Memoria usada por encima del 90 % de forma sostenida: la lectura de esta pasada **y** la muestra anterior (de hace menos de 15 minutos) la superan. | Sí | [Memoria, swap o carga altas](../incidencias/recursos-copias-y-certificado.md#memoria-swap-o-carga-altas) |
| `load_high` | 🟠 Carga del sistema (`load1`) por encima de 2 por CPU de forma sostenida (esta lectura y la muestra anterior). | Sí | [Memoria, swap o carga altas](../incidencias/recursos-copias-y-certificado.md#memoria-swap-o-carga-altas) |
| `swap_high` | 🟠 Swap en uso por encima del 50 % (`/proc/meminfo` del host). Usar swap ya es una condición sostenida, así que basta una lectura. | Sí | [Memoria, swap o carga altas](../incidencias/recursos-copias-y-certificado.md#memoria-swap-o-carga-altas) |
| `backup_stale` | 🟠 Plataforma: el último backup terminó con error (`ok: false` en `var/state/ops/backup.json`) o hace más de 3 horas que no termina ninguno (el timer es horario). Solo fuera de local y con ese fichero. | Sí, al terminar un backup bien | [Backup atrasado o fallido](../incidencias/recursos-copias-y-certificado.md#backup-atrasado-o-fallido) |
| `tls_expiring` | 🟠 El certificado público (host de `PUBLIC_URL`, puerto 443) caduca en menos de 14 días: Caddy debería haberlo renovado. Se comprueba una vez al día (cada 15 minutos mientras falla). Solo fuera de local. | Sí, al renovarse | [Certificado a punto de caducar](../incidencias/recursos-copias-y-certificado.md#certificado-a-punto-de-caducar) |
| `tls_expiring_critical` | 🔴 El certificado caduca en menos de 3 días. | Sí | [Certificado a punto de caducar](../incidencias/recursos-copias-y-certificado.md#certificado-a-punto-de-caducar) |
| `tls_invalid` | 🔴 El certificado que sirve el proxy no valida (caducado, cadena o nombre incorrectos). Los webhooks de Meta y Telegram fallan. | Sí | [Certificado a punto de caducar](../incidencias/recursos-copias-y-certificado.md#certificado-a-punto-de-caducar) |
| `backup_prune_overdue` | 🟡 Plataforma: hace más de 10 días que el operador no purga las copias (testigo `autobot-prune`; si nunca purgó, desde el snapshot más antiguo). Lo lee `backup.sh` en `var/state/ops/backup-prune.json` (ADR-025). Solo fuera de local y con ese fichero. | Sí, al purgar y pasar el siguiente backup | [Caducar snapshots](../procedimientos/backups.md#caducar-snapshots) |
| `containers_stale` | 🟠 Sin estado de contenedores, o sin actualizar desde hace más de 3 minutos. Solo fuera de local. | Sí | [Contenedor caído](../incidencias/contenedor-caido.md) |
| `containers_restore` | 🟠 Restauración a medias: existe `var/.restore-incomplete`. | Sí, al terminar la restauración | [Restaurar](../procedimientos/restaurar.md) |
| `container_down:<servicio>` | 🔴 (🟠 si es `victorialogs`) El contenedor no existe, está parado o se reinicia en bucle. | Sí | [Contenedor caído](../incidencias/contenedor-caido.md) |
| `container_unhealthy:<servicio>` | 🔴 El contenedor está en marcha pero su healthcheck falla. | Sí | [Contenedor caído](../incidencias/contenedor-caido.md) |
| `container_restarted:<servicio>` | 🟠 El contenedor se ha reiniciado en los últimos 30 minutos. | Sí, al pasar la ventana | [Contenedor caído](../incidencias/contenedor-caido.md) |
| `container_image:<servicio>` | 🟠 La imagen de `web`, `web-panel`, de cualquiera de los cuatro workers o de `panel` no es la del SHA desplegado. | Sí | [Contenedor caído](../incidencias/contenedor-caido.md) |
| `container_unexpected:<servicio>` | 🟠 Hay un contenedor que no debería existir (¿huérfano de un despliegue?). | Sí | [Contenedor caído](../incidencias/contenedor-caido.md) |
| `deploy_aborted` | 🔴 El despliegue se abortó antes de cambiar la imagen. Lo emite `deploy/scripts/deploy.sh`. | **No**: se cierra a mano en el panel | [Volver atrás un despliegue](../incidencias/volver-atras.md) |
| `deploy_rollback` | 🔴 El despliegue falló y se revirtió automáticamente. Lo emite `deploy/scripts/deploy.sh`. | **No**: se cierra a mano en el panel | [Volver atrás un despliegue](../incidencias/volver-atras.md) |
| `deploy_ok`, `deploy_caddy_reload`, `deploy_https_check` | Avisos informativos de `deploy.sh` (desplegado, recarga de Caddy fallida, HTTPS sin respuesta). Se guardan ya resueltas y sin enfriamiento. | No aplica | [Volver atrás un despliegue](../incidencias/volver-atras.md) |

Mientras hay un despliegue en curso (`maintenance = deploy`) no se generan alertas de
contenedores. Los servicios esperados son `caddy`, `web`, `web-panel`, `worker-inbound`,
`worker-calendar`, `worker-periodic`, `worker-outbound`, `panel`, `db` y `victorialogs`. La evaluación está en
`apps/backend/src/autobot/ops/containers.py`.

## Dónde está el código

- `apps/backend/src/autobot/ops/check.py` (`collect`, `sync_alerts`, `run`): la lista de
  claves del chequeo.
- `apps/backend/src/autobot/ops/health.py` (`Issue`, `daily`) y
  `apps/backend/src/autobot/ops/containers.py` (`assess`): códigos de salud y de contenedores.
- `apps/backend/src/autobot/runtime/notifications.py` (`send_ops_alert`, `resolve_alert`,
  `MANUAL_KINDS`): enfriamiento, severidad y resolución.
- `deploy/scripts/deploy.sh` (`alert_ops`): alertas de despliegue.
- Prueba de coherencia: `apps/backend/tests/repo/test_docs.py` exige que cada clave esté aquí.

## Relacionado

[Incidencias](../incidencias/README.md), [estados de negocio](estados-de-negocio.md),
[observabilidad](../arquitectura/observabilidad.md).
