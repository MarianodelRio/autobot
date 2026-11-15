# Restauración y simulacro trimestral

**Síntoma:** pérdida de datos/servidor o fecha de simulacro. **Diagnóstico:** comprueba
en restic el último snapshot con tag `autobot`, su fecha y el ping del backup.
Revisa que dispones de la contraseña y las credenciales S3 fuera del repositorio.
No restaures sobre una instalación con volumen de BD existente.

**Dependencia con GHCR (A14):** `restore.sh` necesita descargar la imagen del SHA del
snapshot (`${AUTOBOT_IMAGE}:${SHA}`); si la política de retención de paquetes de GHCR
ya la borró, falla al levantar `web`/`worker-*`, aunque el volcado de la BD sea
correcto. La política de retención de GHCR debe cubrir, como mínimo, el snapshot más
antiguo que `backup.sh` conserva (`--keep-daily 7 --keep-weekly 4 --keep-monthly 6`:
hasta 6 meses); configúrala al crear el repositorio (`docs/procedimientos/servidor.md`).

**Pasos:** prepara una VPS temporal (con el bootstrap ya hecho: `restore.sh` se niega
sin `/var/lib/autobot/bootstrap-complete`) o un proyecto local aislado, instala Docker
y restic, clona el repositorio y crea `var/backup.env` y `var/restic-password` como
`deploy` con modo 0600. Ejecuta `deploy/scripts/restore.sh --confirm-empty-target`.
El script hace checkout del SHA del snapshot, restaura `.env`, `google_sa.json`, el
`Caddyfile` y, si estaban en el snapshot, el estado de Caddy (certificados/cuenta
ACME) y `deploys.jsonl` (T2; ninguno es obligatorio). Reaplica los roles de
PostgreSQL (`init-roles.sh`) y los permisos (`manage.py apply_grants`) después de
restaurar el volcado, porque `pg_restore --no-acl` los pierde. Levanta
`web`, `panel`, `victorialogs` y `caddy`, pero no los workers: con los tokens reales,
enviarían mensajes antes de verificar los datos o cambiar el DNS (T1). Arráncalos
aparte con `AUTOBOT_RESTORE_START_WORKERS=true deploy/scripts/restore.sh
--confirm-empty-target` solo cuando ya has verificado y, si aplica, cambiado el DNS.
Si falla tras crear el volumen, conserva `var/.restore-incomplete` y vuelve a
ejecutar el mismo comando tras arreglar la causa; el script solo admite ese reintento
controlado. Si el snapshot era inválido y aún no se creó volumen, corrige la fuente
antes de repetir. No apuntes DNS hasta verificar. Para prueba puramente local ejecuta
`make restore-test` con Docker y restic; crea dos proyectos temporales y compara
conteos por tenant (usa `AUTOBOT_RESTORE_DB_ONLY=true`, así que no arranca ningún
servicio de aplicación).

**Verificación:** `/health` responde 200, compara por tenant los conteos de `contact`,
`inbound_event` y `outbound_message` con el origen o informe previo; comprueba un
flujo por el bot de demo. Anota SHA, snapshot, hora de inicio/fin y duración; la
meta es menos de dos horas. Borra la VPS temporal tras el simulacro autorizado.
