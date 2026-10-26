# 3. Cola acumulada o latido ausente

**Síntoma:** healthchecks.io avisa del worker o la cola tarda más de 30 s.
**Diagnóstico:** mira `docker compose -p flowpilot -f compose.prod.yaml ps worker`
y `logs --tail=100 worker` desde `/srv/flowpilot`; en Admin → Estado comprueba
trabajos pendientes, fallidos y el último latido. Distingue un worker parado de
errores de BD o de un proveedor externo.

**Pasos:** si el contenedor terminó, reinícialo con `docker compose -p flowpilot
-f compose.prod.yaml up -d worker`. Si hay trabajos fallidos, inspecciona el tipo y
la causa en Admin antes de reintentarlos. Nunca reintentes a ciegas un envío de
estado `unknown`; usa el runbook 5. Si el problema es capacidad sostenida, registra
métricas antes de cambiar concurrencia o número de workers.

**Verificación:** llega un nuevo latido, el check vuelve a verde y los pendientes
disminuyen sin duplicados.
