# Cola y workers

La plataforma reparte su trabajo asíncrono con Procrastinate, una cola que vive en la misma base de datos PostgreSQL. Esta página explica las colas, qué worker escucha cuál, cómo se garantiza el orden por contacto, qué se reintenta y qué no, y cómo vigila la plataforma que nada se quede atascado. Léela para entender cómo se procesan los mensajes en segundo plano o para diagnosticar una cola acumulada (el procedimiento paso a paso está en [cola y latido](../incidencias/cola-y-latido.md)).

## Por qué una cola en PostgreSQL

El webhook debe contestar rápido y no puede llamar a Meta, Google ni Telegram. Por eso solo guarda y encola; el resto lo hace un worker. Procrastinate guarda los trabajos en `procrastinate_jobs`, así que **un trabajo puede insertarse en la misma transacción que la fila que procesa**: aparece con el commit y desaparece con un rollback. No hay broker aparte que sincronizar. Ver la decisión en [ADR-001](adr/ADR-001-monolito-modular.md) y [ADR-004](adr/ADR-004-entrada-idempotente.md).

## Colas y trabajos

Los trabajos se declaran todos en `apps/backend/src/autobot/runtime/jobs.py` (Procrastinate descubre ese módulo con `PROCRASTINATE_AUTODISCOVER_MODULE_NAME = "runtime.jobs"`). Hay cuatro colas, para ver de un vistazo qué se atasca:

| Cola | Trabajos | Candado |
|---|---|---|
| `inbound` | `process_event`, `apply_status`, `route_demo_event`, `handle_owner_event` | `conv:<h>`, ninguno, `demo:<h>`, `ownerchat:<h>` |
| `outbound` | `send_message`, `send_notification` | `out:<h>`, `owner:<id del negocio>` |
| `periodic` | `dispatch_periodic`, `run_periodic`, `retry_stalled_jobs`, `retention_cleanup`, `jobs_cleanup`, `dispatch_owner_summaries`, `send_owner_summary` | `queueing_lock` en la mayoría (ver abajo) |
| `ops` | `ops_check` | `ops_check` |

Quién los encola y con qué argumentos:

- `process_event` / `apply_status`: `runtime/inbound.py`, al guardar un evento entrante.
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

Se despliegan dos workers (`deploy/compose/compose.yaml`), cada uno con `--concurrency 2`:

| Servicio | Colas | Para qué |
|---|---|---|
| `worker-inbound` | `inbound,periodic,ops` | Procesa webhooks (aquí corren los packs, que llaman a Google Calendar) y las tareas periódicas. |
| `worker-outbound` | `outbound,ops` | Solo envía. |

La separación hace que una caída de Google Calendar no pueda dejar sin enviar las respuestas: Google solo se llama desde `inbound` y `periodic`. `ops` la escuchan **los dos**: así, si uno se cae, el otro sigue ejecutando `ops_check` y avisa de esa caída.

Parada ordenada: ante `SIGTERM` el worker deja de tomar trabajos y deja terminar los que corren hasta 50 s (`--shutdown-graceful-timeout 50`), dentro de los 60 s de `stop_grace_period` antes de que Docker lo mate. Un trabajo cortado se reintenta porque todos son idempotentes. En local, `deploy/compose/compose.local.yaml` envuelve el mismo comando con un recargador (`deploy/compose/dev-worker.py`).

!!! note "Cada trabajo cierra sus conexiones"
    Los trabajos síncronos corren en hilos del worker. Cada uno llama a `close_old_connections()` al empezar y al acabar, para mantenerse dentro del presupuesto de conexiones.

## Candados: orden por contacto

Un candado de Procrastinate (`lock=`) garantiza que **no corren dos trabajos con el mismo candado a la vez, y que se ejecutan por orden de creación**. La plataforma lo usa para que los mensajes de una persona se procesen y se envíen uno a uno y en orden:

- `conv:<h>`: los mensajes entrantes de un contacto.
- `out:<h>`: los envíos a un contacto (el mismo `<h>`). Un `send_message` que se reintenta conserva su sitio: es el trabajo más antiguo con ese candado.
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
| `retry_stalled_jobs` | cada 5 min | Rescata trabajos cuyo worker murió. |
| `retention_cleanup` | 03:00 | Retención de datos de clientes (gobernada por `RETENTION_CLEANUP_ENABLED`). |
| `jobs_cleanup` | 03:30 | Purga los trabajos terminados de más de 30 días de `procrastinate_jobs`/`procrastinate_events`; no depende de `RETENTION_CLEANUP_ENABLED` porque solo guardan ids. |
| `dispatch_owner_summaries` | cada hora | Resumen mensual a los dueños; solo actúa en el día 1 de cada negocio pasado el mediodía local (`>=`, para recuperar un envío si el worker estaba caído). |

**De los packs.** Cada `Periodic` de un pack (ver [packs](packs.md)) se registra como una tarea `dispatch_periodic` con `periodic_id = <pack>:<nombre>`; `cron_for` convierte su `every_min` a cron (divisor de 60 minutos, divisor de 24 horas, o una vez al día). Al dispararse, `dispatch` (`apps/backend/src/autobot/runtime/periodic.py`) encola un `run_periodic(tenant_id, name, scheduled_at)` por cada negocio activo del pack, con un `queueing_lock` por negocio y nombre y un desfase estable por negocio dentro del periodo (para que no llamen todos a Calendar en el mismo instante). `run_periodic` construye un contexto sin contacto, ejecuta el manejador **sin transacción** y aplica sus acciones en una. Una ejecución con más retraso que `max_delay_min` se descarta y se registra. Solo corre en canales elegibles: un negocio en alta, pausado o degradado no recibe trabajo periódico en su canal principal.

## Reintentos

Los trabajos reintentan solo lo que probablemente se arregla solo (`RETRYABLE` en `jobs.py`):

- `TransientError`: un proveedor que puede contestar después.
- Errores de base de datos de conexión o concurrencia: `OperationalError` e `InterfaceError`, de Django o de psycopg (conexión perdida, `lock_not_available`, deadlock, fallo de serialización).

**Nunca** `DataError`, `IntegrityError` ni `ProgrammingError`: son fallos de programación y un reintento fallaría igual.

| Trabajo | Estrategia |
|---|---|
| `process_event`, `apply_status`, `route_demo_event`, `handle_owner_event` | 3 reintentos, espera exponencial (2, 4 y 8 s). `is_last_attempt` avisa a `process_event` del último intento, que contesta con el texto de recuperación en lugar de reintentar. |
| `send_message`, `send_notification` | `SendRetryStrategy`: solo `SendRetry` y errores de base de datos; esperas 5 s, 30 s, 2 min, 10 min, 30 min o el `retry_after` del proveedor; 5 intentos. Ver [efectos e idempotencia](efectos-e-idempotencia.md#reintentos-que-si-son-seguros). |
| `run_periodic` | 2 intentos, con un minuto de espera, para sobrevivir a una caída breve de Calendar. |
| `send_owner_summary` | 3 intentos, 5 minutos de espera. |

Si persistir la respuesta falla de forma determinista (por ejemplo `LimitError`), no se reintenta: el contacto recibe el texto de recuperación y el evento queda `failed`.

### Trabajos fallidos

Un trabajo que agota sus reintentos queda `failed` en `procrastinate_jobs`. En el panel, Incidencias → Trabajos fallidos lo lista. Reintentarlo es una decisión humana: `retry_job` en `apps/backend/src/autobot/ops/actions.py` (que usan el panel y el comando `job_retry`) solo acepta trabajos `failed` cuya tarea siga existiendo y **rechaza `send_message` y `send_notification`**: un envío no se reencola a ciegas, se resuelve con [envíos unknown](../incidencias/envios-unknown.md). La acción deja registro de auditoría. El comando es `python manage.py job_retry <id>`; cómo ejecutarlo en el servidor está en [cola y latido](../incidencias/cola-y-latido.md).

### Trabajos de un worker que murió

Un trabajo `doing` cuyo worker murió conserva su candado y bloquearía al contacto para siempre; Procrastinate no lo reintenta solo. `retry_stalled_jobs` (cada 5 min) recoge los que llevan 30 s sin latido y los devuelve a `todo`. Es seguro: todo trabajo es idempotente, y un `send_message` cortado en `sending` termina `unknown` (nunca se reenvía). Si el trabajo rescatado choca con otro ya encolado bajo el mismo `queueing_lock` (por ejemplo el siguiente `ops_check`), no se puede reencolar: se marca `failed` para liberar el candado.

## Conexiones del worker

El `procrastinate worker` crea un pool psycopg propio, fuera del control de `CONN_MAX_AGE` de Django. `apps/backend/src/autobot/runtime/worker_pool.py` (`configure`, enganchado con `PROCRASTINATE_ON_APP_READY`) lo acota con `WORKER_DB_POOL_MIN` y `WORKER_DB_POOL_MAX` (1 y 6 por defecto: la conexión de `LISTEN`, la de recoger trabajos, el latido y el cierre de los trabajos de `--concurrency 2`), de modo que se sabe cuántas conexiones consume cada worker. Ver [variables de entorno](../referencia/variables-entorno.md).

## Barridas de `ops_check`

Aunque encolar en la transacción hace que no deba existir una fila sin trabajo, `ops_check` mira cada cinco minutos si algo se ha quedado atascado (`apps/backend/src/autobot/runtime/sweeps.py`). Solo cuenta lo que no tiene trabajo vivo (`todo` o `doing`) y procesa como máximo 200 filas por negocio y pasada:

| Qué | Umbral | Acción |
|---|---|---|
| Envío `sending` | más de 10 min | Pasa a `unknown`; nunca se reenvía solo. |
| Envío `pending` | más de 10 min, menos de 24 h | Se reencola `send_message`. |
| Envío `pending` | más de 24 h | Se cuenta como atascado; decide una persona. |
| Evento entrante `pending` | más de 5 min | Alerta `inbound_stuck` (🔴); se reencola si tiene menos de 1 hora (el límite evita un bucle con un evento que fallara siempre). |

Si `send_message` o `send_notification` no encuentran su fila, lo registran con `log.error` (solo ids). Además, `ops_check` cuenta los avisos al dueño en `failed` de las últimas 24 h (`notification_failed`: un aviso ambiguo no se reenvía), avisa del disco al 85 % (🟠) y al 95 % (🔴, `disk_critical`) y, si está configurado, envía el latido a `HEALTHCHECKS_PING_URL`. Si una comprobación global falla, **no** se envía latido: una ausencia de latido es la señal de que algo va mal.

### Alertas persistidas

`ops_check` evalúa la cola, los negocios, los bots y, en producción, los contenedores (`apps/backend/src/autobot/ops/containers.py`), sin enviar nada por sí mismo (`collect()`). Luego `sync_alerts()` (`apps/backend/src/autobot/ops/check.py`):

- Guarda cada hallazgo en `ops_alert`, con contador de repeticiones, severidad y un **enfriamiento de 30 minutos** entre avisos (`send_ops_alert`, `apps/backend/src/autobot/runtime/notifications.py`).
- **Resuelve sola** (`resolved_by="auto"`) cualquier alerta abierta que ya no aparezca entre los hallazgos, salvo `deploy_aborted` y `deploy_rollback`, que solo resuelve una persona desde el panel.
- Cuando se resuelve sola una alerta crítica, el bot de avisos manda un «Resuelta: …» al chat de operación; las que no son críticas, o las que resuelve una persona, no mandan ese segundo mensaje.

El historial resuelto se purga junto con `audit_event` a los 12 meses mediante `purge_platform_history`, una función `SECURITY DEFINER` (el rol `fp_app` no tiene `DELETE` sobre esas tablas). Qué significa cada alerta: [alertas](../referencia/alertas.md). Cómo se ve todo en el panel: [observabilidad](observabilidad.md).

## Dónde está el código

- `apps/backend/src/autobot/runtime/jobs.py`: colas, trabajos, reintentos, periódicas de plataforma.
- `apps/backend/src/autobot/runtime/queue.py` (`enqueue`), `locks.py`, `worker_pool.py`.
- `apps/backend/src/autobot/runtime/periodic.py`: tareas periódicas de los packs.
- `apps/backend/src/autobot/runtime/sweeps.py`, `apps/backend/src/autobot/ops/check.py`, `notifications.py`.
- `apps/backend/src/autobot/ops/actions.py` (`retry_job`), `apps/backend/src/autobot/management/commands/job_retry.py`.
- `deploy/compose/compose.yaml` (servicios `worker-inbound` y `worker-outbound`).

## Relacionado

[Vida de un mensaje](vida-de-un-mensaje.md) · [Efectos e idempotencia](efectos-e-idempotencia.md) · [Tenants y RLS](tenants-y-rls.md) · [Observabilidad](observabilidad.md) · [Cola y latido (incidencia)](../incidencias/cola-y-latido.md)
