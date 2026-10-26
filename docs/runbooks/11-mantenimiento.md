# 11. Mantenimiento periódico

**Síntoma:** llega la revisión mensual/trimestral o salta una alerta de seguridad.
**Diagnóstico:** revisa fecha del último backup, uso de disco, CI, dependencias,
versión de Graph API, estado del número de WhatsApp y plantillas aprobadas.

**Pasos:** cada mes ejecuta la auditoría de dependencias de CI, actualiza la imagen
base por Dependabot y planifica un reinicio de VPS tras parches de kernel. Cada seis
meses verifica la versión soportada de Graph API antes de cambiarla. Cada trimestre
revisa calidad del número, plantillas, restaura un snapshot en entorno temporal con
el runbook 6 y registra RTO. Antes de desplegar cualquier actualización, ejecuta
`make check` y valida el SHA publicado en GHCR. Las pruebas reales o cambios de
canal requieren intervención humana.

**Verificación:** CI verde, backup/restauración reciente documentados, alertas
resueltas y `tenant_health` sin degradaciones tras el mantenimiento.
