# ADR-030 — Registro de negocios siempre al día

**Estado:** aceptada; modifica el comportamiento de la caché descrito en el [ADR-009](ADR-009-config-en-bd.md)

## Contexto

Cada proceso (`web`, `worker-inbound`, `worker-outbound`, ...) guarda en memoria un registro con los documentos, datasets y secretos descifrados de todos los negocios ([config y registro](../config-y-registro.md)). La caché era *stale-while-revalidate*: pasados dos segundos desde la última comprobación, el **primer** llamante seguía recibiendo la instantánea vieja y solo despertaba al hilo refrescador.

Un proceso que lleva horas sin actividad sirve entonces su primera petición o trabajo tras un cambio de configuración con datos de hace horas. Se vio en producción el 2026-11-25: se creó un negocio con `tenant_config import` y, en tres procesos distintos, el primer evento falló. `web` respondió 404 a la verificación del webhook de Meta, `worker-inbound` registró «process_event of an unknown tenant: event left pending» y `worker-outbound` registró «send_message of an unknown tenant: message left as it is». Solo las barridas periódicas lo arreglaron, entre 5 y 15 minutos después. El panel no lo sufría porque sus servicios usan `get_registry(force=True)`.

La documentación prometía además que un cambio era visible «a lo sumo dos segundos» después, lo que era falso para un proceso inactivo.

## Decisión

Dos medidas complementarias, ambas en `tenancy/registry.py`:

- **Sondeo propio (*refresh-ahead*).** El hilo refrescador existente, una vez activado el sondeo, comprueba la revisión cada `POLL_SECONDS = 2.0` por su cuenta, haya o no llamantes. Mantiene las garantías de antes: una sola comprobación o reconstrucción a la vez, nunca se publica un registro a medias y, si la recarga falla, se conserva la instantánea anterior. Conserva **una** conexión abierta entre comprobaciones (los workers usan `DB_CONN_MAX_AGE=0`: sin esto reconectaría cada 2 s) y solo la cierra tras una comprobación fallida o si no es utilizable; entre comprobaciones no deja ninguna transacción abierta. El sondeo se activa solo en el arranque real de un proceso: `config/wsgi.py` y `runtime/worker_pool.py` llaman a `warm_up_in_background(poll=True)` (precarga y después `start_polling()`, idempotente). Los tests, los comandos de `manage.py` y el chat de desarrollo siguen siendo perezosos. `stop_polling()` detiene y espera al hilo.
- **Búsquedas que no se rinden ante una instantánea vieja.** `tenant_by_id`, `tenant_by_slug` y `tenant_by_public_id` buscan en la instantánea y, si fallan, hacen **una** comprobación síncrona (`get_registry(force=True)`) y buscan de nuevo, con un límite de una por segundo y proceso (candado; los fallos concurrentes dentro de la ventana devuelven `None` sin consultar). Así el coste de un chorro de identificadores públicos inventados desde internet queda acotado a una consulta de revisión por segundo y proceso. Dentro de un `registry_scope` la recarga forzada sustituye la instantánea fijada, que solo gana lo que faltaba. Cuando un fallo se resuelve así se registra en INFO el id del negocio (nunca datos personales). Se usan en todos los caminos de ejecución que antes trataban un fallo como definitivo: verificación y recepción de webhooks, `process_event`, `apply_status`, `abandon_event`, `send_message`, avisos, resumen diario, barridas, enlaces de dueño, acciones de operación, selector de demo y sondeo de Telegram.

## Alternativas consideradas

- **Mantener *stale-while-revalidate* tal cual.** Es lo que falló: el primer llamante tras un periodo inactivo siempre ve datos viejos.
- **Forzar la comprobación en cada petición o trabajo.** Daría datos siempre actuales, pero añade una consulta a la ruta caliente de todos los mensajes y hace que cada proceso espere a cualquier reconstrucción (3,8 s con 300 negocios).
- **`LISTEN/NOTIFY`.** Avisaría al instante sin sondear, pero cada proceso necesitaría una conexión de escucha, tolerar reconexiones y pérdidas de avisos (y seguir sondeando como respaldo). Se plantea como una fase posterior, junto con una confirmación visible de «aplicado en todos los procesos» en el panel.
- **Recarga incremental con un diario de cambios** (recargar solo los negocios modificados). Reduciría el coste de reconstruir el registro entero, pero es un cambio mayor que solo compensa a escala (miles de negocios). Posterior.

## Consecuencias

- Un negocio recién creado o importado se encuentra al instante en cualquier proceso; un cambio en uno que ya estaba llega a los procesos arrancados en unos 2 s más la reconstrucción. La documentación lo dice así.
- Cada proceso arrancado hace una consulta de revisión cada 2 s (un `SELECT` de una fila) con una conexión propia más: hay que contarla en el presupuesto de conexiones de cada servicio.
- Un fallo de búsqueda cuesta una consulta de revisión como mucho por segundo y proceso; es la única vía por la que tráfico no autenticado puede provocar consultas, y está acotada.
- Dos fallos distintos dentro del mismo segundo: el segundo no fuerza. Los trabajos reintentan, y lo normal es que la primera recarga ya haya traído también el segundo negocio.
- Más superficie de hilos en pruebas: la fixture de la caché llama a `stop_polling()` al terminar para no dejar hilos ni conexiones.

## Cuándo revisarla

- Si hace falta que un cambio (p. ej. pausar un negocio) sea efectivo antes de 2 s o se quiera una confirmación de «aplicado en todos los procesos»: pasar a `LISTEN/NOTIFY`.
- Si la reconstrucción completa tarda más que el intervalo (del orden de miles de negocios) o el coste de CPU del sondeo con reconstrucciones frecuentes molesta: recarga incremental con diario de cambios.
- Si el presupuesto de conexiones de la base se queda corto por la conexión fija de cada hilo refrescador.
