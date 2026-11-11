# Contenedor caído, reiniciándose o con una imagen distinta

**Síntoma:** llega una alerta `container_down:<servicio>`, `container_unhealthy:<servicio>`,
`container_restarted:<servicio>`, `container_image:<servicio>`, `container_unexpected:<servicio>`
o `containers_stale`, o la tarjeta Contenedores de Sistema en el panel muestra un
servicio en rojo o ámbar.

**Diagnóstico:** desde `/srv/autobot`, `docker compose ps` para ver el estado de todos
los contenedores y `docker compose logs --tail=100 <servicio>` para el que falla. Si el
texto de la alerta dice «sin memoria», revisa `dmesg | tail -50` por si el OOM killer lo
mató. `containers_stale` no es un contenedor caído: significa que
`var/state/ops/containers.json` lleva más de 3 minutos sin actualizarse; comprueba el
timer (`systemctl status autobot-containers.timer`,
`journalctl -u autobot-containers.service --since -10min`) antes de mirar los
contenedores. `container_unexpected:<servicio>` señala un contenedor huérfano de un
despliegue anterior (p. ej. el `worker` único de antes de X14), no uno de los siete
servicios actuales.

**Pasos:**

- Contenedor parado o reiniciándose en bucle: `docker compose up -d <servicio>` y
  sigue los logs; si vuelve a caer, es un fallo de arranque (migración pendiente,
  secreto mal configurado) y no un problema transitorio.
- Healthcheck fallando (`web`, `panel`, `db`) sin que el contenedor esté parado: revisa
  si responde `/health` o `/healthz` manualmente dentro del contenedor
  (`docker compose exec <servicio> ...`) antes de reiniciarlo.
- Huérfano (`container_unexpected`): `docker compose up -d --remove-orphans` lo retira
  si ya no está en `compose.prod.yaml`; si debería estar, revisa por qué el despliegue no
  lo levantó.
- Imagen distinta de la desplegada (`container_image`): normalmente un despliegue a
  medias o revertido; compara `var/.deployed-sha` con la etiqueta de la alerta y, si no
  coinciden, sigue [volver atrás un despliegue](volver-atras.md).
- Durante un despliegue (`maintenance: "deploy"` en la instantánea) o una restauración
  a medias (`var/.restore-incomplete`), la tarjeta sigue mostrando la verdad pero no
  genera alertas nuevas de contenedores: espera a que termine antes de diagnosticar.

**Verificación:** `docker compose ps` muestra el servicio `running` y sin reinicios
recientes, la alerta correspondiente se resuelve sola en el panel
(`sync_alerts`, `docs/incidencias/cola-y-latido.md`) y la tarjeta Contenedores vuelve a
verde en el siguiente minuto.
