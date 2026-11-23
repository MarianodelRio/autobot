# ADR-023 — Colas aisladas y degradación ante servicios externos

**Estado:** aceptada

## Contexto

Con los workers anteriores (`worker-inbound`: `inbound`, `periodic`, `ops`, concurrencia 2; `worker-outbound`: `outbound`, `ops`, concurrencia 2) las pruebas de carga dieron un techo de unos 150 negocios, y el límite eran los **huecos de worker**, no la CPU. Peor: con Google Calendar lento durante 10 minutos y 100 negocios, el p95 de respuesta fue de 387 s y 486 mensajes se quedaron sin respuesta, y los negocios de `bus`, que no usan Calendar, también sufrieron. La causa es que todos los `process_event` compartían los dos huecos de `worker-inbound`, y un solo evento podía retenerlo hasta ~62 s (5 s de timeout × 3 intentos del cliente × 4 ejecuciones del trabajo). Un servicio externo lento acababa bloqueando a quien no dependía de él.

Un prototipo con las medidas de este ADR bajó el p95 con Google degradado a 4,1 s con 100 negocios y 4,9 s con 300.

## Decisión

**Topología de workers.** Cuatro servicios, cada uno con sus colas y su concurrencia (`deploy/compose/compose.yaml`):

| Servicio | Colas | Concurrencia |
|---|---|---|
| `worker-inbound` | `inbound` | 4 |
| `worker-calendar` (nuevo) | `inbound_ext` | 8 |
| `worker-periodic` (nuevo) | `periodic`, `ops` | 2 |
| `worker-outbound` | `outbound` | 8 |

`ops` solo la escucha `worker-periodic` (enmienda tras la prueba de carga de 700 negocios: sus comprobaciones de salud son lentas y ocupaban un hueco de `worker-outbound`); si ese worker cae, lo detecta el latido externo. El pool de conexiones de cada worker se acota con `WORKER_DB_POOL_MAX` (8, 10, 6 y 10), y se fija `PYTHON_CPU_COUNT` para que el pool de hilos por defecto de asyncio, que ejecuta los trabajos síncronos, no limite la concurrencia (con 2 vCPU serían 6 hilos). `max_connections` de PostgreSQL sube de 100 a 200; el reparto está comentado en `compose.prod.yaml`.

**Cola `inbound_ext` (mamparo).** El `process_event` de los negocios cuyo pack llama a servicios externos (`Pack.needs_calendar`) va a `inbound_ext`; el resto, a `inbound`. Un único helper decide la cola (`process_event_queue` en `runtime/jobs.py`) y lo usan `runtime/inbound.py` y el reencolado de `runtime/sweeps.py`. Un contacto pertenece a un negocio y un negocio tiene un pack, así que sus mensajes caen siempre en la misma cola, y el candado `conv:<h>` sigue ordenándolos. `apply_status`, `route_demo_event` y `handle_owner_event` siguen en `inbound`. Las alertas y el panel miran las dos colas de entrada.

**Resiliencia del cliente de Google Calendar** (`integrations/google_calendar/`):

- Timeout de 2,5 s y 2 intentos con pausa corta y variación aleatoria (jitter).
- Un error de cuota (`rateLimitExceeded`, `userRateLimitExceeded`, `quotaExceeded`, `dailyLimitExceeded` o un 429) **no se reintenta dentro del cliente**: reintentar solo añade carga. Se registra como error transitorio.
- **Presupuesto por mensaje**: `runtime/process.py` abre un `time_budget` de 8 s alrededor de la ejecución del pack. El cliente comprueba el tiempo restante antes de cada intento y de cada pausa, y limita el timeout a lo que queda; agotado, lanza `CalendarTransientError` sin llamar a Google.
- **Cortacircuitos por proceso**: se abre tras 5 fallos seguidos, o cuando al menos la mitad de las llamadas de los últimos 30 s fallan o tardan más de 1,5 s (con al menos 10 llamadas). Abierto, falla al instante con el mismo `TransientError`; pasados 8 s deja pasar una llamada de prueba y se cierra si funciona. Es seguro entre hilos. Los rechazos que Google contesta (404, 403 de permisos) no cuentan como fallos suyos.
- El objeto de servicio de Google se construye una vez por hilo, no por contexto de pack.

**Reintentos y respuesta degradada.** `process_event` en `inbound_ext` se reintenta como máximo una vez (en `inbound`, tres, como antes). En el último intento, si el pack falla con `TransientError`, el contacto recibe un texto genérico de la plataforma (`DEGRADED_TEXT` en `core/conversation.py`: «Ahora mismo no puedo completar tu consulta. Prueba de nuevo en unos minutos.») y **la conversación conserva su estado**, en lugar del texto de recuperación que reinicia. La plataforma no sabe qué es una cita: el texto no menciona agenda. El evento queda `failed` con el error registrado y la señal de salud del negocio y las alertas de Calendar cuentan igual que antes.

**`retry_stalled_jobs` cada minuto** (antes cada 5): un worker que muere libera antes los candados de sus contactos. Vive en `periodic`, que ahora sirve `worker-periodic`.

## Alternativas consideradas

- **Subir solo la concurrencia de los workers existentes**: más huecos, pero el mismo reparto; una caída de Google seguiría agotándolos para todos.
- **Una cola por negocio o por pack**: aislamiento total, pero un worker por cola o una lista de colas dinámica; demasiada complejidad para dos packs. Una sola cola de «externo» cubre el caso real.
- **Solo cortacircuitos, sin cola aparte**: protege el tiempo, pero un fallo parcial (lento, no caído) seguiría ocupando huecos compartidos.
- **Mantener el texto de recuperación**: reinicia la conversación por un fallo que no es suyo; la persona perdería el paso en que iba.
- **PgBouncer**: no hace falta con 200 conexiones, y el modo transacción rompe `LISTEN/NOTIFY` y los candados consultivos.

## Consecuencias

- Una caída o lentitud de Google solo afecta a los negocios que usan Calendar, y cada hueco se retiene como mucho unos 8 s por mensaje, no un minuto.
- Dos contenedores más (384 MB cada uno) y más conexiones a PostgreSQL (hasta unas 90 en el peor caso, frente a 200 permitidas).
- Con Google caído, esas personas reciben un aviso en pocos segundos en vez de esperar o no recibir nada; si vuelven a escribir, continúan donde iban.
- Un tenant que cambiase de pack con mensajes en vuelo podría tener un instante dos colas para un mismo contacto; no es un caso soportado hoy (el pack de un negocio no cambia).
- Un despliegue o un rollback a un commit anterior sigue funcionando: `deploy.sh` toma la lista de servicios del compose que está desplegado.

## Cuándo revisarla

- Si un tercer servicio externo lento (otro calendario, un CRM) necesita su propio aislamiento, generalizar `inbound_ext` a una cola por dependencia.
- Si se supera de nuevo el techo de capacidad medido (ver [capacidad y crecimiento](../capacidad-y-crecimiento.md)), o si la VPS cambia de tamaño y habría que reajustar concurrencias y `max_connections`.
- Si el cortacircuitos se abre en falso con tráfico normal (alertas de Calendar sin caída real), revisar sus umbrales.
