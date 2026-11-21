# Cola acumulada o latido ausente

## Síntoma

healthchecks.io avisa del worker, la cola tarda más de 30 s o el panel muestra una de estas alertas: `inbound_delay` (trabajo inbound listo desde hace más de 2 minutos), `failed_jobs` (trabajos fallidos en 10 minutos) o `inbound_stuck` (evento entrante sin trabajo).

## Diagnóstico

`worker-inbound` procesa webhooks y las barridas periódicas; `worker-outbound` envía.

1. Estado de los workers. En la VPS, como `deploy`, en `/srv/autobot`:

    ```bash
    deploy/scripts/compose.sh ps worker-inbound worker-outbound
    ```

2. Logs. En la VPS, como `deploy`:

    ```bash
    deploy/scripts/compose.sh logs --tail=100 worker-inbound worker-outbound
    ```

3. Trabajos. En el panel, Incidencias → Trabajos fallidos, o Sistema → Colas: pendientes, fallidos y último latido.
4. Distingue un worker parado de errores de BD ([el bot no responde](bot-no-responde.md)) o de un proveedor externo.

## Arreglo

1. Si un contenedor terminó, reinícialo. En la VPS, como `deploy`:

    ```bash
    deploy/scripts/compose.sh up -d worker-inbound
    ```

    (o `worker-outbound`, según cuál).
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
