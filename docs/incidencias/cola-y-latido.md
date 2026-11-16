# Cola acumulada o latido ausente

**Síntoma:** healthchecks.io avisa del worker o la cola tarda más de 30 s.
**Diagnóstico:** mira `docker compose ps worker-inbound worker-outbound`
y `docker compose logs --tail=100 worker-inbound worker-outbound` desde `/srv/autobot`
(`inbound` procesa webhooks; `outbound` envía y hace las barridas periódicas, X14); en
el panel, Incidencias → Trabajos fallidos, o Sistema → Colas, comprueba trabajos
pendientes, fallidos y el último latido. Distingue un worker parado de errores de BD o
de un proveedor externo.

**Pasos:** si un contenedor terminó, reinícialo con `docker compose up -d worker-inbound`
o `worker-outbound`, según cuál. Si hay trabajos fallidos, inspecciona el tipo y
la causa en el panel (Incidencias → Trabajos fallidos) antes de reintentarlos con
«Reintentar»; si el panel no es accesible, usa
`docker compose exec web python manage.py job_retry <id>` (rechaza trabajos de
envío, que no se reintentan a ciegas). Nunca reintentes a ciegas un envío de
estado `unknown`; usa [envíos sin confirmar](envios-unknown.md). Si el problema es capacidad sostenida, registra
métricas antes de cambiar concurrencia o número de workers.

**Verificación:** llega un nuevo latido, el check vuelve a verde y los pendientes
disminuyen sin duplicados.

**Alertas persistidas:** cada cinco minutos `ops.check.collect()` evalúa la cola, los
tenants, los bots y, en producción, la instantánea de contenedores
(`autobot/ops/containers.py`, [contenedor caído](contenedor-caido.md)) sin enviar nada;
`sync_alerts()` guarda cada hallazgo en `ops_alert`
(con reintentos, severidad y enfriamiento de 30 min) y resuelve sola
(`resolved_by="auto"`) cualquier alerta abierta que ya no aparezca entre los hallazgos,
salvo `deploy_aborted` y `deploy_rollback`, que solo se resuelven a mano desde el panel.
Al resolverse sola una alerta crítica (🔴), el bot de avisos manda además un
«✅ Resuelta: …» al chat de ops, para cerrar el aviso original sin tener que mirar el
panel; las que no son críticas, o las que resuelve una persona desde el panel, no
mandan ese segundo mensaje. `ops_check` corre en su propia cola (`ops`), que escuchan
los dos workers (`worker-inbound` y `worker-outbound`): si uno de los dos se cae, el
otro sigue vigilando y avisa también de esa caída. El historial resuelto se purga
junto con `audit_event` a los 12 meses, con `purge_platform_history` (función
`SECURITY DEFINER`, ya que `fp_app` no tiene `DELETE` sobre ninguna de las dos
tablas).
