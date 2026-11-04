# 3. Cola acumulada o latido ausente

**Síntoma:** healthchecks.io avisa del worker o la cola tarda más de 30 s.
**Diagnóstico:** mira `docker compose -p autobot -f compose.prod.yaml ps worker`
y `logs --tail=100 worker` desde `/srv/autobot`; en el panel, Incidencias →
Trabajos fallidos, o Sistema → Colas, comprueba trabajos pendientes, fallidos y el
último latido. Distingue un worker parado de errores de BD o de un proveedor
externo.

**Pasos:** si el contenedor terminó, reinícialo con `docker compose -p autobot
-f compose.prod.yaml up -d worker`. Si hay trabajos fallidos, inspecciona el tipo y
la causa en el panel (Incidencias → Trabajos fallidos) antes de reintentarlos con
«Reintentar»; si el panel no es accesible, usa
`docker compose exec web python manage.py job_retry <id>` (rechaza trabajos de
envío, que no se reintentan a ciegas). Nunca reintentes a ciegas un envío de
estado `unknown`; usa el runbook 5. Si el problema es capacidad sostenida, registra
métricas antes de cambiar concurrencia o número de workers.

**Verificación:** llega un nuevo latido, el check vuelve a verde y los pendientes
disminuyen sin duplicados.

**Alertas persistidas:** cada cinco minutos `ops.check.collect()` evalúa la cola, los
tenants y los bots sin enviar nada; `sync_alerts()` guarda cada hallazgo en `ops_alert`
(con reintentos, severidad y enfriamiento de 30 min) y resuelve sola
(`resolved_by="auto"`) cualquier alerta abierta que ya no aparezca entre los hallazgos,
salvo `deploy_aborted` y `deploy_rollback`, que solo se resuelven a mano desde el panel.
El historial resuelto se purga junto con `audit_event` a los 12 meses, con
`purge_platform_history` (función `SECURITY DEFINER`, ya que `fp_app` no tiene `DELETE`
sobre ninguna de las dos tablas).
