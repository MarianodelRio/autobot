# Cola acumulada o latido ausente

## Síntoma

healthchecks.io avisa del worker, la cola tarda más de 30 s o el panel muestra una de estas alertas: `inbound_delay` (trabajo inbound listo desde hace más de 2 minutos), `failed_jobs` (trabajos fallidos en 10 minutos), `inbound_stuck` (evento entrante sin trabajo) o `queue_lag:<cola>` (una cola va retrasada: su trabajo listo más antiguo espera más de lo normal, o un trabajo lleva demasiado «en curso»).

## Diagnóstico

`worker-inbound` procesa los mensajes de los packs sin Calendar, el bot de demo y los estados de entrega; `worker-calendar` procesa los de los packs con Calendar (cola `inbound_ext`); `worker-periodic` ejecuta las tareas periódicas, las barridas y el rescate de trabajos; `worker-outbound` envía.

1. Estado de los workers. En la VPS, como `deploy`, en `/srv/autobot`:

    ```bash
    deploy/scripts/compose.sh ps worker-inbound worker-calendar worker-periodic worker-outbound
    ```

2. Logs. En la VPS, como `deploy`:

    ```bash
    deploy/scripts/compose.sh logs --tail=100 worker-inbound worker-calendar worker-periodic worker-outbound
    ```

3. Trabajos. En el panel, Incidencias → Trabajos fallidos, o Sistema → Colas: por cola, los pendientes, cuánto espera el más antiguo y cuántos hay en curso (y desde cuándo). Un `queue_lag:<cola>` con pendientes que crecen y ningún trabajo en curso indica un worker parado; con un trabajo en curso muy antiguo, un trabajo atascado en una llamada externa (el rescate `retry_stalled_jobs` solo libera los de un worker que dejó de latir).
4. Distingue un worker parado de errores de BD ([el bot no responde](bot-no-responde.md)) o de un proveedor externo.

## Arreglo

1. Si un contenedor terminó, reinícialo. En la VPS, como `deploy`:

    ```bash
    deploy/scripts/compose.sh up -d worker-inbound
    ```

    (o `worker-calendar`, `worker-periodic` o `worker-outbound`, según cuál).
2. Si hay trabajos fallidos, inspecciona tipo y causa en el panel y reintenta con «Reintentar». Si el panel no es accesible, en la VPS como `deploy`:

    ```bash
    deploy/scripts/manage.sh job_retry <id>
    ```

    Rechaza los trabajos de envío: no se reintentan a ciegas.
3. Nunca reintentes un envío `unknown`; usa [envíos sin confirmar](envios-unknown.md).
4. Si el problema es capacidad sostenida, registra métricas antes de cambiar concurrencia o número de workers.

## Verificación

Llega un nuevo latido, el check vuelve a verde y los pendientes disminuyen sin duplicados. La alerta se resuelve sola en el siguiente `ops_check` (cada 5 minutos).

## Relacionado

- Cómo funcionan la cola, las barridas, los reintentos, el pool de conexiones y las alertas persistidas: [cola y workers](../arquitectura/cola-y-workers.md).
- [Envíos `unknown`](envios-unknown.md), [contenedor caído](contenedor-caido.md), [alertas](../referencia/alertas.md).
