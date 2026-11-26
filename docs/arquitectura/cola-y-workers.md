# Cola y workers

La plataforma reparte su trabajo asíncrono con Procrastinate, una cola que vive en la misma base de datos PostgreSQL. Esta página explica las colas, qué worker escucha cuál, cómo se garantiza el orden por contacto, qué se reintenta y qué no, y cómo vigila la plataforma que nada se quede atascado. Léela para entender cómo se procesan los mensajes en segundo plano o para diagnosticar una cola acumulada (el procedimiento paso a paso está en [cola y latido](../incidencias/cola-y-latido.md)).

## Por qué una cola en PostgreSQL

El webhook debe contestar rápido y no puede llamar a Meta, Google ni Telegram. Por eso solo guarda y encola; el resto lo hace un worker. Procrastinate guarda los trabajos en `procrastinate_jobs`, así que **un trabajo puede insertarse en la misma transacción que la fila que procesa**: aparece con el commit y desaparece con un rollback. No hay broker aparte que sincronizar. Ver la decisión en [ADR-001](adr/ADR-001-monolito-modular.md) y [ADR-004](adr/ADR-004-entrada-idempotente.md).

## Colas y trabajos

Los trabajos se declaran todos en `apps/backend/src/autobot/runtime/jobs.py` (Procrastinate descubre ese módulo con `PROCRASTINATE_AUTODISCOVER_MODULE_NAME = "runtime.jobs"`). Hay cinco colas, para ver de un vistazo qué se atasca:

| Cola | Trabajos | Candado |
|---|---|---|
| `inbound` | `process_event` (packs sin llamadas externas), `apply_status`, `route_demo_event`, `handle_owner_event` | `conv:<h>`, ninguno, `demo:<h>`, `ownerchat:<h>` |
| `inbound_ext` | `process_event` de los packs que llaman a Google Calendar (`needs_calendar`, como `salon`) | `conv:<h>` |
| `outbound` | `send_message`, `send_notification` | `out:<h>` (respuestas), `outp:<h>` (proactivos), `owner:<id del negocio>` |
| `periodic` | `dispatch_periodic`, `run_periodic`, `retry_stalled_jobs`, `retention_cleanup`, `jobs_cleanup`, `reconcile_unknown`, `dispatch_owner_summaries`, `send_owner_summary`, `ops_daily_summary` | `queueing_lock` en la mayoría (ver abajo) |
| `ops` | `ops_check` | `ops_check` |

Quién los encola y con qué argumentos:

- `process_event` / `apply_status`: `runtime/inbound.py`, al guardar un evento entrante, y `runtime/sweeps.py` al reencolar. La cola de `process_event` la decide un único helper, `process_event_queue` (`jobs.py`): `inbound_ext` si el pack del negocio necesita Calendar, `inbound` si no. Un contacto es de un solo negocio, así que sus mensajes caen siempre en la misma cola y el candado `conv:<h>` conserva el orden.
- `send_message`: `runtime/outbound.py` (`defer_sends`), `runtime/sweeps.py` y `ops/actions.py` (`resend`).
- `send_notification`: `runtime/process.py` (acción `NotifyOwner`) y `runtime/summary.py`.
- `dispatch_periodic` / `run_periodic`: ver [Tareas periódicas](#tareas-periodicas).

### Los trabajos reciben solo ids

Regla de `CLAUDE.md`: **argumentos, candados y logs llevan ids, nunca teléfonos, ids de usuario ni datos personales**. La tabla de trabajos no tiene RLS y la lee quien pueda leer esa tabla, así que un trabajo lleva `tenant_id` y `event_id` / `outbound_id` / `notification_id`; el worker recarga lo que necesita de la base con `tenant_tx`. Los argumentos de `process_event` son solo `(tenant_id, event_id)`; los de `send_message`, `(tenant_id, outbound_id)`.

## Encolar dentro de la transacción

`procrastinate worker` sustituye el conector global por un pool propio. Si un trabajo encolase otro con ese pool, el nuevo trabajo se insertaría **fuera** de la `tenant_tx` en curso: podría arrancar antes de que se confirmase la fila que necesita (un `send_message` que «no encuentra el mensaje») y sobreviviría a un rollback.

Por eso todo el código síncrono encola con `enqueue` (`apps/backend/src/autobot/runtime/queue.py`), que usa una `App` de Procrastinate aparte, ligada a un `DjangoConnector`: inserta por la conexión de Django del hilo, la misma de la transacción abierta. El `NOTIFY` de Procrastinate se entrega al confirmar, como siempre. Las tareas se referencian por **nombre** (constantes en `jobs.py`), para que quien encola no importe el módulo de trabajos.

`enqueue` admite `lock`, `queueing_lock` y `schedule_in`. Si `queueing_lock` ya está tomado lanza `AlreadyEnqueued`; el intento corre en un savepoint para no abortar la transacción de quien llama.

## Qué worker escucha qué

Se despliegan cuatro workers (`deploy/compose/compose.yaml`), cada uno con su concurrencia ([ADR-023](adr/ADR-023-colas-aisladas-y-degradacion.md)):

| Servicio | Colas | Concurrencia | Para qué |
|---|---|---|---|
| `worker-inbound` | `inbound` | 4 | Conversaciones de los packs sin llamadas externas (`bus`), selector del bot de demo, chat de dueños y estados de entrega. |
| `worker-calendar` | `inbound_ext` | 8 | Conversaciones de los packs que llaman a Google Calendar (`salon`). |
| `worker-periodic` | `periodic`, `ops` | 2 | Tareas periódicas de plataforma y de los packs (también las que llaman a Calendar, como la barrida del calendario), `retry_stalled_jobs`, resúmenes. |
| `worker-outbound` | `outbound` | 8 | Solo envía. |

Cada grupo de huecos es un proceso aparte, así que **un servicio externo lento solo retiene sus propios huecos**: una caída de Google Calendar no frena los envíos, ni las conversaciones de `bus`, ni las tareas periódicas que no dependen de ella. `ops` solo la escucha `worker-periodic`: las comprobaciones de salud de `ops_check` llaman a Meta, Telegram y Google una tras otra y no deben ocupar nunca un hueco que envía o responde (con 700 negocios, la primera ejecución en frío tardó 581 s sobre un hueco de `worker-outbound`). Si `worker-periodic` se cae, `ops_check` no avisa de ello: lo detecta el latido externo (Healthchecks) al dejar de recibirlo. Con Google lento, el límite de un mensaje es de unos 8 s de hueco (ver [Calendar lento o caído](#calendar-lento-o-caido)), no del minuto que llegaba a retener antes.

Parada ordenada: ante `SIGTERM` el worker deja de tomar trabajos y deja terminar los que corren hasta 50 s (`--shutdown-graceful-timeout 50`), dentro de los 60 s de `stop_grace_period` antes de que Docker lo mate. Un trabajo cortado se reintenta porque todos son idempotentes. En local, `deploy/compose/compose.local.yaml` envuelve el mismo comando con un recargador (`deploy/compose/dev-worker.py`).

Los trabajos síncronos corren en el pool de hilos por defecto de asyncio, que con `min(32, CPU + 4)` hilos limitaría a 6 los huecos de un worker de concurrencia 8 en una VPS de 2 vCPU. Por eso `compose.prod.yaml` fija `PYTHON_CPU_COUNT` en cada worker.

!!! note "Cada trabajo cierra sus conexiones"
    Los trabajos síncronos corren en hilos del worker. Cada uno llama a `close_old_connections()` al empezar y al acabar, para mantenerse dentro del presupuesto de conexiones.

## Candados: orden por contacto

Un candado de Procrastinate (`lock=`) garantiza que **no corren dos trabajos con el mismo candado a la vez, y que se ejecutan por orden de creación**. La plataforma lo usa para que los mensajes de una persona se procesen y se envíen uno a uno y en orden:

- `conv:<h>`: los mensajes entrantes de un contacto.
- `out:<h>`: las respuestas a un contacto (el mismo `<h>`). Un `send_message` que se reintenta conserva su sitio: es el trabajo más antiguo con ese candado.
- `outp:<h>`: los envíos proactivos a ese contacto (recordatorios y confirmaciones). Separado de `out:<h>` para que un recordatorio atascado no bloquee una respuesta; a cambio, entre una respuesta y un recordatorio no hay orden garantizado ([ADR-024](adr/ADR-024-envio-saliente-por-caducidad.md)).
- `owner:<tenant_id>`: los avisos al dueño de un negocio.
- `demo:<h>` y `ownerchat:<h>`: las personas del bot de demo y los chats del bot de dueños (ver [bot de demo](bot-de-demo.md), [bot de dueños](bot-de-duenos.md)).
- `ops_check`: una sola ejecución a la vez.

### Nunca con datos personales

La tabla de trabajos no tiene RLS, y un teléfono o un id de Telegram tiene poca entropía: un sha256 simple se rompería con un diccionario. `apps/backend/src/autobot/runtime/locks.py` construye cada candado con un **HMAC-SHA256** y una clave de la plataforma derivada de `SECRET_KEY` (`_hash`, 16 primeros caracteres hexadecimales) sobre negocio, canal e id. Es estable entre procesos (web y workers) mientras `SECRET_KEY` no cambie. Si se rota, solo cambian los candados de los trabajos encolados después: durante un rato, los trabajos viejos y nuevos de un mismo contacto podrían no excluirse.

Hay otro tipo de candado que no es de la cola: `ctx.lock(key)` de los packs, un candado consultivo de sesión de PostgreSQL (ver [vida de un mensaje](vida-de-un-mensaje.md#4-el-contexto-del-pack)). Protege recursos externos (por ejemplo un día del calendario), no el orden de la cola.

### Candados de espera (`queueing_lock`)

Distinto del anterior: un `queueing_lock` impide que haya **dos trabajos pendientes** con esa clave. Lo usan las tareas periódicas (`periodic:<negocio>:<nombre>`, `summary:<negocio>`, `ops_check`, `retention_cleanup`, `jobs_cleanup`, `dispatch_owner_summaries`, `retry_stalled_jobs`): si la anterior sigue sin ejecutarse, la nueva no se apila.

## Tareas periódicas

Procrastinate dispara sus tareas periódicas por cron (UTC) y cada instante programado se encola una sola vez.

**Plataforma** (declaradas en `jobs.py` con `@app.periodic`):

| Tarea | Cron | Qué hace |
|---|---|---|
| `ops_check` | cada 5 min | Barridas, alertas, muestra del sistema y latido (ver abajo). Cola `ops`. |
| `retry_stalled_jobs` | cada minuto | Rescata trabajos cuyo worker murió. |
| `retention_cleanup` | 03:00 | Retención de datos de clientes (gobernada por `RETENTION_CLEANUP_ENABLED`). |
| `reconcile_unknown` | cada 5 min | Reenvía una vez los `unknown` de más de 10 minutos sin evidencia cuya clase admite duplicados, caduca los que pasaron `expires_at` y los avisos `held` viejos ([ADR-026](adr/ADR-026-conciliacion-de-envios-ambiguos.md)). |
| `jobs_cleanup` | 03:30 | Purga los trabajos terminados de más de 30 días de `procrastinate_jobs`/`procrastinate_events`; no depende de `RETENTION_CLEANUP_ENABLED` porque solo guardan ids. |
| `dispatch_owner_summaries` | cada hora | Resumen mensual a los dueños; solo actúa en el día 1 de cada negocio pasado el mediodía local (`>=`, para recuperar un envío si el worker estaba caído). |
| `ops_daily_summary` | cada hora, minuto 5 | Resumen diario al chat de operación; solo envía una vez al día, en la primera pasada desde las 09:00 de Madrid ([ADR-029](adr/ADR-029-menu-de-operador.md)). |

**De los packs.** Cada `Periodic` de un pack (ver [packs](packs.md)) se registra como una tarea `dispatch_periodic` con `periodic_id = <pack>:<nombre>`; `cron_for` convierte su `every_min` a cron (divisor de 60 minutos, divisor de 24 horas, o una vez al día). Al dispararse, `dispatch` (`apps/backend/src/autobot/runtime/periodic.py`) encola un `run_periodic(tenant_id, name, scheduled_at)` por cada negocio activo del pack, con un `queueing_lock` por negocio y nombre y un desfase estable por negocio dentro del periodo (para que no llamen todos a Calendar en el mismo instante). `run_periodic` construye un contexto sin contacto, ejecuta el manejador **sin transacción** y aplica sus acciones en una. Una ejecución con más retraso que `max_delay_min` se descarta y se registra. Solo corre en canales elegibles: un negocio en alta, pausado o degradado no recibe trabajo periódico en su canal principal.

## Reintentos

Los trabajos reintentan solo lo que probablemente se arregla solo (`RETRYABLE` en `jobs.py`):

- `TransientError`: un proveedor que puede contestar después.
- Errores de base de datos de conexión o concurrencia: `OperationalError` e `InterfaceError`, de Django o de psycopg (conexión perdida, `lock_not_available`, deadlock, fallo de serialización).

**Nunca** `DataError`, `IntegrityError` ni `ProgrammingError`: son fallos de programación y un reintento fallaría igual.

| Trabajo | Estrategia |
|---|---|
| `process_event` en `inbound`, `apply_status`, `route_demo_event`, `handle_owner_event` | 3 reintentos, espera exponencial (2, 4 y 8 s). `is_last_attempt` avisa a `process_event` del último intento, que contesta en lugar de reintentar. |
| `process_event` en `inbound_ext` | 1 reintento (2 s): el cliente de Calendar ya intenta dos veces y un hueco retenido durante más rondas es lo que dejaba sin servicio a los demás. Su último intento contesta con el texto de servicio degradado (ver abajo). Los errores de base de datos (`OperationalError`, `InterfaceError`) tienen su propio retroceso más largo, 3 reintentos tras 5, 15 y 40 s (`INBOUND_EXT_DB_WAITS_S`, cerca de un minuto), para que un corte breve de la base no agote el reintento y deje el mensaje esperando a la barrida (más de 5 minutos); mientras esperan, el trabajo está en `todo` y no ocupa hueco. |
| `send_message` | `SendRetryStrategy`: un `SendRetry` (el proveedor dijo «luego», o no hubo conexión) se reintenta siempre, sin tope de intentos, con el `retry_after` del proveedor o un retroceso exponencial con jitter de hasta 300 s; el mensaje caduca por su `expires_at` (30 min una respuesta, hasta 24 h un recordatorio). Los errores de base de datos, 5 reintentos. Ver [efectos e idempotencia](efectos-e-idempotencia.md#reintentos-que-si-son-seguros). |
| `send_notification` | `NotificationRetryStrategy`: `SendRetry` sin tope de intentos (el aviso caduca a las 2 h, `NOTICE_TTL`; espera del limitador, `retry_after` del proveedor o retroceso con jitter hasta 300 s) y errores de base de datos con 5 intentos. Antes del envío, un limitador en memoria (25 mensajes/s del bot y 1/s por chat del dueño, `runtime/ratelimit.py`) aplaza el aviso sin llamar a Telegram. |
| `run_periodic` | 2 intentos, con un minuto de espera, para sobrevivir a una caída breve de Calendar. |
| `send_owner_summary` | 3 intentos, 5 minutos de espera. |

Si persistir la respuesta falla de forma determinista (por ejemplo `LimitError`), no se reintenta: el contacto recibe el texto de recuperación y el evento queda `failed`.

### Calendar lento o caído

Las medidas del [ADR-023](adr/ADR-023-colas-aisladas-y-degradacion.md) acotan lo que un Google degradado cuesta (`apps/backend/src/integrations/google_calendar/`, sin importar Django):

- **Cliente**: timeout de 2,5 s y 2 intentos con pausa corta y jitter. Los errores de cuota (`quotaExceeded`, `rateLimitExceeded`, 429) no se reintentan dentro del cliente.
- **Presupuesto por mensaje**: `runtime/process.py` abre `time_budget(8 s)` alrededor del pack; el cliente no empieza un intento sin tiempo y recorta su timeout a lo que queda.
- **Cortacircuitos por proceso** (`breaker.py`): se abre tras 5 fallos seguidos, o con al menos la mitad de las llamadas de 30 s fallidas o más lentas de 1,5 s (mínimo 10 llamadas). Abierto, falla al instante con el mismo `TransientError`; cada 8 s deja pasar una llamada de prueba.
- **Respuesta degradada**: en el último intento, un `TransientError` del pack responde con `DEGRADED_TEXT` (`core/conversation.py`) y **conserva el estado de la conversación**, en lugar de reiniciarla con el texto de recuperación. El evento queda `failed` y las señales de error de Calendar (`ops/state.py`) cuentan igual.

### Trabajos fallidos

Un trabajo que agota sus reintentos queda `failed` en `procrastinate_jobs`. `ops_check` abre por cada tarea un evento `failed_job:<tarea>` con los trabajos fallidos posteriores a su marca de revisión como casos ([ADR-031](adr/ADR-031-incidencias-como-bandeja.md)); en el panel se ven en Incidencias y se cierran con «Lo he revisado». Reintentarlo es una decisión humana: `retry_job` en `apps/backend/src/autobot/ops/actions.py` (que usan el panel y el comando `job_retry`) solo acepta trabajos `failed` cuya tarea siga existiendo y **rechaza `send_message` y `send_notification`**: un envío no se reencola a ciegas, se resuelve con [envíos unknown](../incidencias/envios-unknown.md). La acción deja registro de auditoría. El comando es `python manage.py job_retry <id>`; cómo ejecutarlo en el servidor está en [cola y latido](../incidencias/cola-y-latido.md).

### Trabajos de un worker que murió

Un trabajo `doing` cuyo worker murió conserva su candado y bloquearía al contacto para siempre; Procrastinate no lo reintenta solo. `retry_stalled_jobs` (cada minuto, en `worker-periodic`) recoge los que llevan 30 s sin latido y los devuelve a `todo`. Es seguro: todo trabajo es idempotente, y un `send_message` cortado en `sending` termina `unknown` (nunca se reenvía). Con tope: un trabajo que ya se ha reintentado `STALLED_MAX_ATTEMPTS` (3) veces no se reencola otra vez (un mensaje que mata al worker, por ejemplo por falta de memoria, entraría en bucle cada minuto): se marca `failed`, se registra un error con solo el id y el nombre de la tarea y, si era un `process_event`, su evento pasa a `failed` con el texto de recuperación para el contacto (`process.abandon_event`, el mismo tx2 que un fallo determinista; si no puede crearse, al menos queda `failed`), de modo que ni queda `pending` ni la barrida lo reencola. `retry_stalled_jobs` y `ops_check` se encolan con prioridad alta (`HOUSEKEEPING_PRIORITY`, 100) para no esperar detrás de `run_periodic` en los dos huecos de `worker-periodic` (el deferidor periódico usa `task.configure`, que respeta la prioridad de la tarea). Si el trabajo rescatado choca con otro ya encolado bajo el mismo `queueing_lock` (por ejemplo el siguiente `ops_check`), no se puede reencolar: se termina como `aborted` para liberar el candado. No es `failed` a propósito: el trabajo de la cola hace lo mismo, así que no es un fallo y no debe abrir `failed_job:<tarea>`. El choque se reconoce por el índice único del `queueing_lock` (`procrastinate_jobs_queueing_lock_idx_v1`) en el error; cualquier otro motivo para no reencolarlo sí lo marca `failed`.

## Conexiones del worker

El `procrastinate worker` crea un pool psycopg propio, fuera del control de `CONN_MAX_AGE` de Django. `apps/backend/src/autobot/runtime/worker_pool.py` (`configure`, enganchado con `PROCRASTINATE_ON_APP_READY`) lo acota con `WORKER_DB_POOL_MIN` y `WORKER_DB_POOL_MAX` (1 y 6 por defecto: la conexión de `LISTEN`, la de recoger trabajos, el latido y el cierre de los trabajos), de modo que se sabe cuántas conexiones consume cada worker. `compose.prod.yaml` lo fija por servicio (8, 10, 6 y 10 para `worker-inbound`, `worker-calendar`, `worker-periodic` y `worker-outbound`), y cada hilo de trabajo abre además una conexión de Django: con eso el peor caso ronda las 90 conexiones y `max_connections` de PostgreSQL es 200 (el desglose está comentado en `compose.prod.yaml`). Ver [variables de entorno](../referencia/variables-entorno.md).

## Cortacircuitos del proveedor

`worker-outbound` lleva en memoria un cortacircuitos por proveedor, WhatsApp y Telegram (`apps/backend/src/autobot/runtime/breaker.py`, instancia `BREAKER` en `runtime/outbound.py`). Se abre tras 5 fallos de transporte seguidos (5xx, red, tiempo agotado; no 4xx ni autenticación) de **al menos 2 negocios distintos**. Abierto, `send_message` no llama al proveedor: aplaza el mensaje, y como mucho una vez cada 60 s uno de ellos ejecuta una sonda de solo lectura (`adapter.probe()`: `GET` del nodo del número en WhatsApp, `getMe` en Telegram); si responde, se cierra. Al abrirse y cerrarse escribe una señal en la caché de base de datos (`ops/state.py`), de la que `ops_check` deriva **una** alerta `provider_outage` ([alertas](../referencia/alertas.md)). Un reinicio del worker lo deja cerrado. Al recuperarse el proveedor los mensajes en espera no salen todos juntos: cada uno espera hasta la siguiente sonda más un azar (respuestas 0-30 s, recordatorios y demás 15-90 s) y los `send_message` se encolan con prioridad de Procrastinate (respuestas 10, recordatorios 0), de modo que una respuesta nunca espera detrás de un recordatorio y un atasco de WhatsApp retrasa lo mínimo a Telegram. Decisión en [ADR-024](adr/ADR-024-envio-saliente-por-caducidad.md).

## Barridas de `ops_check`

Aunque encolar en la transacción hace que no deba existir una fila sin trabajo, `ops_check` mira cada cinco minutos si algo se ha quedado atascado (`apps/backend/src/autobot/runtime/sweeps.py`). Solo cuenta lo que no tiene trabajo vivo (`todo` o `doing`) y procesa como máximo 200 filas por negocio y pasada:

| Qué | Umbral | Acción |
|---|---|---|
| Envío `sending` | más de 10 min | Pasa a `unknown`; nunca se reenvía solo. |
| Envío `pending` | más de 10 min, menos de 24 h | Se reencola `send_message` (con su candado `out:` u `outp:`). Si ya caducó, ese run lo deja `expired`. |
| Envío `pending` | más de 24 h | Se cuenta como atascado; decide una persona. |
| Evento entrante `pending` | más de 5 min | Alerta `inbound_stuck` (🔴); se reencola si tiene menos de 1 hora (el límite evita un bucle con un evento que fallara siempre). |

Si `send_message` o `send_notification` no encuentran su fila, lo registran con `log.error` (solo ids). Además, `ops_check` cuenta los avisos al dueño en `failed` o `expired` posteriores a la marca de revisión (`notification_failed`, un evento: un aviso ambiguo no se reenvía), avisa del disco al 80 % (🟠) y al 95 % (🔴, `disk_critical`) y, si está configurado, envía el latido a `HEALTHCHECKS_PING_URL`. Si una comprobación global falla, **no** se envía latido: una ausencia de latido es la señal de que algo va mal.

### Incidencias persistidas

`ops_check` evalúa la cola, los negocios, los bots y, en producción, los contenedores (`apps/backend/src/autobot/ops/containers.py`), sin enviar nada por sí mismo (`collect()`). Luego `sync_alerts()` (`apps/backend/src/autobot/ops/check.py`):

- Guarda cada hallazgo en `ops_alert`, con contador de repeticiones, severidad y casos (`send_ops_alert`, `apps/backend/src/autobot/runtime/notifications.py`). Solo una 🔴 o 🟠 que se abre avisa por Telegram; no se repite mientras siga abierta.
- **Cierra sola** (`resolved_by="auto"`) cualquier **condición** abierta que ya no aparezca entre los hallazgos. Los **eventos** (`failed_job:<tarea>`, `outbound_rejected:<clase>`, `deploy_rollback`…) siguen abiertos hasta que una persona los revisa desde el panel.
- Cuando se cierra sola una condición crítica, el bot de avisos manda un «Resuelta: …» al chat de operación; las que no son críticas, o los eventos revisados, no mandan ese segundo mensaje.
- Reintenta, como mucho una vez por hora, los avisos que no llegaron a Telegram.

El historial resuelto se purga junto con `audit_event` a los 12 meses mediante `purge_platform_history`, una función `SECURITY DEFINER` (el rol `fp_app` no tiene `DELETE` sobre esas tablas). Qué significa cada alerta: [alertas](../referencia/alertas.md). Cómo se ve todo en el panel: [observabilidad](observabilidad.md).

## Dónde está el código

- `apps/backend/src/autobot/runtime/jobs.py`: colas, trabajos, reintentos, periódicas de plataforma.
- `apps/backend/src/autobot/runtime/queue.py` (`enqueue`), `locks.py`, `worker_pool.py`.
- `apps/backend/src/autobot/runtime/periodic.py`: tareas periódicas de los packs.
- `apps/backend/src/autobot/runtime/sweeps.py`, `apps/backend/src/autobot/ops/check.py`, `notifications.py`.
- `apps/backend/src/autobot/ops/actions.py` (`retry_job`), `apps/backend/src/autobot/management/commands/job_retry.py`.
- `apps/backend/src/integrations/google_calendar/` (cliente y `breaker.py`).
- `deploy/compose/compose.yaml` (los cuatro workers) y `compose.prod.yaml` (reparto de conexiones).

## Relacionado

[Vida de un mensaje](vida-de-un-mensaje.md) · [Efectos e idempotencia](efectos-e-idempotencia.md) · [Tenants y RLS](tenants-y-rls.md) · [Observabilidad](observabilidad.md) · [Cola y latido (incidencia)](../incidencias/cola-y-latido.md)
