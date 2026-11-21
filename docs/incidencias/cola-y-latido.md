# Cola acumulada o latido ausente

**Síntoma:** healthchecks.io avisa del worker o la cola tarda más de 30 s.
**Diagnóstico:** mira `docker compose ps worker-inbound worker-outbound`
y `docker compose logs --tail=100 worker-inbound worker-outbound` desde `/srv/autobot`
(`worker-inbound` procesa webhooks y las barridas periódicas; `worker-outbound` envía); en
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

**Trabajo atascado (barridas de `ops_check`):** los trabajos se encolan dentro de la
misma transacción que la fila que procesan (`autobot/runtime/queue.py`; nunca por el
pool propio del worker de Procrastinate, que quedaría fuera de la transacción y podía
arrancar un envío antes del commit de su mensaje), así que un mensaje o evento sin
trabajo no debería existir. Como red de seguridad, cada cinco minutos
`autobot/runtime/sweeps.py`: pasa a `unknown` un envío `sending` sin trabajo vivo (se
cortó mientras hablaba con el proveedor; nunca se reenvía solo); reencola `send_message`
para un envío `pending` de más de 10 minutos sin trabajo vivo (idempotente por estado,
solo si tiene menos de 24 h); y avisa (`inbound_stuck`, 🔴) de un evento entrante
`pending` de más de 5 minutos sin trabajo vivo, reencolándolo si tiene menos de 1 hora
(`process_event` y `apply_status` son idempotentes por el estado del evento; el límite
evita un bucle con un evento que fallara siempre). Pasado ese límite decide una persona.
Si `send_message`/`send_notification` no encuentran su fila lo registran con `log.error`
(ids, nunca datos personales). `ops_check` cuenta además los avisos al dueño en
`failed` de las últimas 24 h (`notification_failed`: un aviso ambiguo no se reenvía a
ciegas) y avisa del disco al 85 % (🟠) y al 95 % (🔴, `disk_critical`).

**Reintentos:** los trabajos reintentan los errores de proveedor transitorios
(`TransientError`) y los errores de BD de conexión o concurrencia (`OperationalError`,
`InterfaceError`: conexión perdida, `lock_not_available`, deadlock, fallo de
serialización); nunca `DataError`, `IntegrityError` ni `ProgrammingError`. Si
persistir la respuesta falla de forma determinista (p. ej. `LimitError`), el contacto
recibe el texto de recuperación y el evento queda `failed`.

**Conexiones del worker:** el pool propio de `procrastinate worker` está acotado con
`WORKER_DB_POOL_MIN`/`WORKER_DB_POOL_MAX` (1 y 6 por defecto; ver
[variables de entorno](../referencia/variables-entorno.md)). Los trabajos terminados de
más de 30 días de `procrastinate_jobs`/`procrastinate_events` los purga el periódico
`jobs_cleanup` (03:30 UTC), independiente de `RETENTION_CLEANUP_ENABLED`.

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
