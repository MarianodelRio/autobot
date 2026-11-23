# Contenedor caído, reiniciándose o con una imagen distinta

## Síntoma

Llega una alerta `container_down:<servicio>`, `container_unhealthy:<servicio>`, `container_restarted:<servicio>`, `container_image:<servicio>`, `container_unexpected:<servicio>` o `containers_stale`, o la tarjeta Contenedores de Sistema en el panel muestra un servicio en rojo o ámbar. Los servicios esperados son `caddy`, `web`, `web-panel`, `worker-inbound`, `worker-calendar`, `worker-periodic`, `worker-outbound`, `panel`, `db` y `victorialogs`.

## Diagnóstico

Todo en la VPS, como `deploy`, en `/srv/autobot`.

1. Estado de todos los contenedores:

    ```bash
    deploy/scripts/compose.sh ps
    ```

2. Logs del que falla:

    ```bash
    deploy/scripts/compose.sh logs --tail=100 <servicio>
    ```

3. Si el texto de la alerta dice «sin memoria», el OOM killer lo mató. Como `admin` (necesita `sudo`) o con permiso de lectura:

    ```bash
    dmesg | tail -50
    ```

4. `containers_stale` no es un contenedor caído: `var/state/ops/containers.json` lleva más de 3 minutos sin actualizarse. Revisa el timer antes de mirar contenedores:

    ```bash
    systemctl status autobot-containers.timer
    journalctl -u autobot-containers.service --since -10min
    ```

5. `container_unexpected:<servicio>` señala un contenedor huérfano de un despliegue anterior (p. ej. el `worker` único previo a la separación en workers), no uno de los diez servicios actuales.
6. Durante un despliegue (`maintenance: "deploy"` en la instantánea) la tarjeta sigue mostrando la verdad pero no genera alertas nuevas de contenedores; espera a que termine. Con una restauración a medias (`var/.restore-incomplete`) solo salta `containers_restore`: ve a [restauración](../procedimientos/restaurar.md).

## Arreglo

1. Contenedor parado o reiniciándose en bucle:

    ```bash
    deploy/scripts/compose.sh up -d <servicio>
    ```

    Sigue los logs; si vuelve a caer, es un fallo de arranque (migración pendiente, secreto mal configurado) y no un problema transitorio.
2. Healthcheck fallando (`web`, `web-panel`, `panel`, `db`) sin que el contenedor esté parado: comprueba a mano antes de reiniciar. Los puertos solo escuchan en `127.0.0.1` de la VPS:

    ```bash
    curl -s http://127.0.0.1:8000/health     # web
    curl -s http://127.0.0.1:8080/healthz    # panel
    deploy/scripts/compose.sh ps web-panel   # web-panel no publica puerto: mira la columna de salud
    deploy/scripts/compose.sh exec -T db pg_isready
    ```

3. Huérfano (`container_unexpected`): retíralo si ya no está en `deploy/compose/compose.prod.yaml`:

    ```bash
    deploy/scripts/compose.sh up -d --remove-orphans
    ```

    Si debería estar, revisa por qué el despliegue no lo levantó.
4. Imagen distinta de la desplegada (`container_image`): normalmente un despliegue a medias o revertido. Compara `var/.deployed-sha` con la etiqueta de la alerta; si no coinciden, sigue [volver atrás un despliegue](volver-atras.md).

## Verificación

`deploy/scripts/compose.sh ps` muestra el servicio `running` y sin reinicios recientes, la alerta se resuelve sola en el panel y la tarjeta Contenedores vuelve a verde en el siguiente minuto.

## Relacionado

- [Cola y workers](../arquitectura/cola-y-workers.md) (cómo se resuelven solas las alertas), [observabilidad](../arquitectura/observabilidad.md), [alertas](../referencia/alertas.md).
- [Volver atrás un despliegue](volver-atras.md), [el bot no responde](bot-no-responde.md).
