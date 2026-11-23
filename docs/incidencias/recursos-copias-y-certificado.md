# Recursos del servidor, backup atrasado o certificado a punto de caducar

## Síntoma

El panel (o el chat de avisos) muestra una de estas alertas de plataforma: `inodes` / `inodes_critical`, `memory_high`, `swap_high`, `load_high`, `backup_stale`, `tls_expiring` / `tls_expiring_critical` o `tls_invalid`. El catálogo con umbrales está en [alertas](../referencia/alertas.md).

## Diagnóstico

En la VPS, como `deploy`, en `/srv/autobot`.

### Inodos agotados

1. `df -i / /srv/autobot` y, para ver dónde se concentran los ficheros, `sudo du --inodes -x -d 2 /var/lib/docker | sort -n | tail`.
2. Suelen ser capas de imágenes viejas o logs de contenedores en exceso.

### Memoria, swap o carga altas

1. `free -m`, `uptime` y `docker stats --no-stream`: qué contenedor consume.
2. Panel, Sistema: la gráfica de memoria y carga de las últimas horas indica si es un pico tras un despliegue o una tendencia.
3. `swap_high` con memoria libre suele ser memoria vieja enviada al swap; con memoria alta, falta RAM.

### Backup atrasado o fallido

1. `cat var/state/ops/backup.json`: `ok` y `finished_at` del último intento (también los fallidos escriben el fichero).
2. `systemctl status autobot-backup.timer autobot-backup.service` y `journalctl -u autobot-backup -n 100`: la causa (repositorio bloqueado, disco, credenciales de restic, dump inválido).
3. Si `finished_at` es antiguo y el timer no está activo, el timer se paró.

### Certificado a punto de caducar

1. Qué ve el exterior: `echo | openssl s_client -connect <dominio>:443 -servername <dominio> 2>/dev/null | openssl x509 -noout -dates`.
2. Logs de Caddy: `deploy/scripts/compose.sh logs --tail=200 caddy | grep -i -E 'tls|acme|certificate'`. Causas habituales: el puerto 80/443 bloqueado, el DNS del dominio ya no apunta a la VPS, límite de emisión de la CA.
3. `ops_check` conecta al dominio de `PUBLIC_URL` desde el contenedor; si la VPS no alcanza su propia IP pública (hairpin), la comprobación se omite en silencio: compruébalo desde fuera.

## Arreglo

1. **Inodos:** `deploy/scripts/prune.sh` (imágenes viejas) y los pasos de [Disco lleno](../procedimientos/mantenimiento.md#disco-lleno). Si el sistema de ficheros es pequeño, ampliarlo es acción de infraestructura: aprobación humana explícita.
2. **Memoria o carga:** reinicia solo el contenedor culpable (`deploy/scripts/compose.sh restart <servicio>`). Si es crónico, sube de plan en el proveedor (aprobación humana explícita).
3. **Backup:** arregla la causa y lanza uno a mano con `make backup-now`; ver [Backups](../procedimientos/backups.md). Mientras tanto no hay copia reciente: evita cambios arriesgados.
4. **Certificado:** arregla lo que impide la renovación (DNS, puertos) y reinicia Caddy (`deploy/scripts/compose.sh restart caddy`) para que reintente. Con `tls_invalid` o menos de 3 días, es urgente: los webhooks de Meta y Telegram fallan al caducar.

## Verificación

La alerta se resuelve sola en el siguiente `ops_check` (cinco minutos; la del certificado, en cuanto se repite su comprobación, 15 minutos mientras falla). El backup: `ok: true` y `finished_at` reciente en `var/state/ops/backup.json`.

## Relacionado

- [Alertas](../referencia/alertas.md), [Disco lleno](../procedimientos/mantenimiento.md#disco-lleno), [Backups](../procedimientos/backups.md), [Contenedor caído](contenedor-caido.md) y [Observabilidad](../arquitectura/observabilidad.md).
