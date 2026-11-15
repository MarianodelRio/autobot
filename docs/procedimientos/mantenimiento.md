# Mantenimiento periódico

**Síntoma:** llega la revisión mensual/trimestral o salta una alerta de seguridad.
**Diagnóstico:** revisa fecha del último backup, uso de disco, CI, dependencias,
versión de Graph API, estado del número de WhatsApp y plantillas aprobadas.

**Pasos:** cada mes ejecuta la auditoría de dependencias de CI, actualiza la imagen
base por Dependabot y planifica un reinicio de VPS tras parches de kernel. Cada seis
meses verifica la versión soportada de Graph API antes de cambiarla. Cada trimestre
revisa calidad del número, plantillas, restaura un snapshot en entorno temporal con
[el procedimiento de restauración](restaurar.md) y registra RTO. Antes de desplegar cualquier actualización, ejecuta
`make check` y valida el SHA publicado en GHCR. Las pruebas reales o cambios de
canal requieren intervención humana.

**Verificación:** CI verde, backup/restauración reciente documentados, alertas
resueltas y `tenant_health` sin degradaciones tras el mantenimiento.

## Subir de versión mayor de PostgreSQL

`db` está fijada por dígest (`deploy/compose/compose.yaml`) a una versión mayor
concreta (actualmente 18). A diferencia de una actualización menor (mismo dígest de
mayor, solo cambia el parche), una mayor **no es un simple cambio de imagen**: el
formato de los ficheros de datos de PostgreSQL no es compatible entre versiones
mayores, así que `pgdata` del volumen antiguo no arranca con el binario nuevo.

**Pasos:** esto no lo hace `deploy.sh`; es un simulacro de restauración (`T1`–`T3`,
`docs/procedimientos/restaurar.md`) sobre un proyecto Compose vacío con el `db` ya
actualizado:

1. Backup reciente comprobado (`make backup-now` o esperar al timer) y simulacro de
   restauración aparte, con la versión **actual**, para tener una referencia de
   conteos por tenant antes de tocar nada.
2. En una rama o checkout aparte, sube el dígest de `db` en `compose.yaml` a la
   versión mayor deseada.
3. Simulacro de restauración con ese checkout contra un proyecto Compose nuevo (vacío):
   `deploy/scripts/restore.sh --confirm-empty-target` crea el volumen con la versión
   nueva y `pg_restore` reconstruye el esquema y los datos desde el volcado lógico
   (`pg_dump`/`pg_restore`, no son los ficheros binarios del volumen antiguo, así que
   el salto de versión mayor no es un problema para ellos). Compara los conteos por
   tenant con el paso 1.
4. Si coincide, repite el corte real: backup final, parar `web`/`worker-*`/`caddy`
   en producción, desplegar el checkout con el dígest nuevo (que recrea `db` desde
   cero y restaura desde el volcado más reciente, no desde el volumen antiguo) y
   verificar `/health` y los conteos antes de levantar `worker-*`.
5. Actualiza el dígest fijado también en `docs/arquitectura/adr/ADR-005-vps-docker-compose.md`
   si el ADR lo menciona, y en este procedimiento si cambia el número de versión mayor
   citado arriba.

**Verificación:** igual que un simulacro de restauración normal (`restaurar.md`):
`/health` 200, conteos por tenant iguales y un flujo por el bot de demo. Conserva el
volumen antiguo sin borrar hasta confirmar el corte real.
