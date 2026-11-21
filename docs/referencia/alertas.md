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
terminó sin error** (un fallo de BD no manda un latido falso).

## Cola y tareas

| Clave | Significado y umbral | Se resuelve sola | Runbook |
|---|---|---|---|
| `inbound_delay` | 🔴 Hay un trabajo `inbound` listo (`todo`) que debería haber empezado hace más de 2 minutos. | Sí | [Cola y latido](../incidencias/cola-y-latido.md) |
| `failed_jobs` | 🟠 Algún trabajo falló en los últimos 10 minutos y sigue en estado `failed`. | Sí, a los 10 minutos si no hay fallos nuevos | [Cola y latido](../incidencias/cola-y-latido.md) |
| `inbound_stuck` | 🔴 Por negocio: eventos entrantes `pending` sin trabajo vivo desde hace más de 5 minutos. El barrido los reencola si tienen menos de 1 hora. | Sí | [Cola y latido](../incidencias/cola-y-latido.md) |
| `outbound_stuck` | 🟠 Por negocio: envíos `pending` o `sending` sin trabajo vivo desde hace más de 10 minutos. Un `sending` pasa a `unknown`; un `pending` de menos de 24 h se reencola. | Sí | [Envíos unknown](../incidencias/envios-unknown.md) |
| `outbound_failed` | 🟠 Por negocio: envíos `failed` creados en las últimas 24 h, o `unknown` desde hace más de 10 minutos (y menos de 24 h). | Sí, al salir de la ventana de 24 h o resolverse el envío | [Envíos unknown](../incidencias/envios-unknown.md) |
| `notification_failed` | 🟠 Por negocio: avisos al dueño `failed` o ambiguos en las últimas 24 h, con el chat del dueño y el bot de avisos configurados. | Sí, al salir de la ventana de 24 h | [Envíos unknown](../incidencias/envios-unknown.md) |

Detalles de los barridos de trabajo atascado en `apps/backend/src/autobot/runtime/sweeps.py`.

## Negocios y canales

`<canal>` es el canal con el que corre el negocio: `main`, `demo_tg` o `demo_wa`.

| Clave | Significado y umbral | Se resuelve sola | Runbook |
|---|---|---|---|
| `registry` | 🔴 Hay configuraciones de negocio o secretos ilegibles al cargar el registro. | Sí, al corregirse | [Un negocio o canal no responde](../incidencias/negocio-o-canal.md) |
| `tenant_unavailable` | 🔴 Por negocio: degradado, o (si no es demo) con el canal principal sin secretos o sin configuración completa. | Sí | [Un negocio o canal no responde](../incidencias/negocio-o-canal.md) |
| `errors:<canal>` | 🔴 Por negocio y canal: tres errores seguidos al procesar mensajes o ejecutar periodics. Un éxito pone el contador a cero. | Sí, al primer éxito | [Un negocio o canal no responde](../incidencias/negocio-o-canal.md) |
| `auth` | 🔴 Por negocio: un envío del canal principal fue rechazado por autenticación (`last_error` empieza por `auth:` en las últimas 24 h). | Sí, al salir de la ventana o dejar de haber rechazos | [Un negocio o canal no responde](../incidencias/negocio-o-canal.md) y [rotar secretos](../procedimientos/rotar-secretos.md) |
| `auth:<canal>` | 🔴 Plataforma: la puerta de demo (`demo_tg` o `demo_wa`) fue rechazada por autenticación. | Sí | [Un negocio o canal no responde](../incidencias/negocio-o-canal.md) y [rotar secretos](../procedimientos/rotar-secretos.md) |
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

`health:<código>` es por negocio, con la severidad del propio problema. Códigos:

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
| `disk` | 🟠 Disco por encima del 85 %. | Sí | [Disco lleno](../procedimientos/mantenimiento.md#disco-lleno) |
| `disk_critical` | 🔴 Disco por encima del 95 %. | Sí | [Disco lleno](../procedimientos/mantenimiento.md#disco-lleno) |
| `containers_stale` | 🟠 Sin estado de contenedores, o sin actualizar desde hace más de 3 minutos. Solo fuera de local. | Sí | [Contenedor caído](../incidencias/contenedor-caido.md) |
| `containers_restore` | 🟠 Restauración a medias: existe `var/.restore-incomplete`. | Sí, al terminar la restauración | [Restaurar](../procedimientos/restaurar.md) |
| `container_down:<servicio>` | 🔴 (🟠 si es `victorialogs`) El contenedor no existe, está parado o se reinicia en bucle. | Sí | [Contenedor caído](../incidencias/contenedor-caido.md) |
| `container_unhealthy:<servicio>` | 🔴 El contenedor está en marcha pero su healthcheck falla. | Sí | [Contenedor caído](../incidencias/contenedor-caido.md) |
| `container_restarted:<servicio>` | 🟠 El contenedor se ha reiniciado en los últimos 30 minutos. | Sí, al pasar la ventana | [Contenedor caído](../incidencias/contenedor-caido.md) |
| `container_image:<servicio>` | 🟠 La imagen de `web`, `worker-inbound`, `worker-outbound` o `panel` no es la del SHA desplegado. | Sí | [Contenedor caído](../incidencias/contenedor-caido.md) |
| `container_unexpected:<servicio>` | 🟠 Hay un contenedor que no debería existir (¿huérfano de un despliegue?). | Sí | [Contenedor caído](../incidencias/contenedor-caido.md) |
| `deploy_aborted` | 🔴 El despliegue se abortó antes de cambiar la imagen. Lo emite `deploy/scripts/deploy.sh`. | **No**: se cierra a mano en el panel | [Volver atrás un despliegue](../incidencias/volver-atras.md) |
| `deploy_rollback` | 🔴 El despliegue falló y se revirtió automáticamente. Lo emite `deploy/scripts/deploy.sh`. | **No**: se cierra a mano en el panel | [Volver atrás un despliegue](../incidencias/volver-atras.md) |
| `deploy_ok`, `deploy_caddy_reload`, `deploy_https_check` | Avisos informativos de `deploy.sh` (desplegado, recarga de Caddy fallida, HTTPS sin respuesta). Se guardan ya resueltas y sin enfriamiento. | No aplica | [Volver atrás un despliegue](../incidencias/volver-atras.md) |

Mientras hay un despliegue en curso (`maintenance = deploy`) no se generan alertas de
contenedores. Los servicios esperados son `caddy`, `web`, `worker-inbound`,
`worker-outbound`, `panel`, `db` y `victorialogs`. La evaluación está en
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
