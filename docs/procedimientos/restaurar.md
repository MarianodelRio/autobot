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

**Pasos:** prepara una VPS temporal con `sudo deploy/scripts/install-vm.sh --restore-target`
(`docs/procedimientos/servidor.md`): `restore.sh` se niega sin
`/var/lib/autobot/bootstrap-complete`, que escribe ese instalador al terminar la base y el
endurecimiento de SSH (nada más lo crea). Crea `var/backup.env` y `var/restic-password`
como `deploy` con modo 0600 (el repositorio ya queda clonado en `/srv/autobot`). Ejecuta `deploy/scripts/restore.sh --confirm-empty-target`.
El script hace checkout del SHA del snapshot, restaura `.env`, `google_sa.json`, el
`Caddyfile` y, si estaban en el snapshot, el estado de Caddy (certificados/cuenta
ACME) y `deploys.jsonl` (T2; ninguno es obligatorio). Reaplica los roles de
PostgreSQL (`init-roles.sh`) y los permisos (`manage.py apply_grants`) después de
restaurar el volcado, porque `pg_restore --no-acl` los pierde. Levanta
`web`, `panel`, `victorialogs` y `caddy`, pero no los workers: con los tokens reales,
enviarían mensajes antes de verificar los datos o cambiar el DNS (T1). Una vez
restaurado, `var/.deployed-sha` ya existe, así que un segundo
`restore.sh --confirm-empty-target` se niega («Existing deployment»); para arrancar
los workers después de verificar, usa en su lugar
`deploy/scripts/compose.sh up -d worker-inbound worker-outbound` (toma el `SHA` y el
`.env` ya restaurados de `lib.sh`, igual que `manage.sh`). `AUTOBOT_RESTORE_START_WORKERS=true`
solo sirve dentro de la misma ejecución de `restore.sh`, cuando no hace falta
verificar antes de arrancarlos (por ejemplo, en `make restore-test`).
Si falla tras crear el volumen, conserva `var/.restore-incomplete` y vuelve a
ejecutar el mismo comando tras arreglar la causa; el script solo admite ese reintento
controlado. Si el snapshot era inválido y aún no se creó volumen, corrige la fuente
antes de repetir. No apuntes DNS hasta verificar. Para prueba puramente local ejecuta
`make restore-test` con Docker y restic; crea dos proyectos temporales, compara
conteos por tenant (restaura con `AUTOBOT_RESTORE_DB_ONLY=true`), y después arranca solo
`web` sobre la copia restaurada para comprobar que `/health/internal` responde sin
negocios ilegibles y que la `SECRETS_ENCRYPTION_KEY` restaurada descifra `tenant_secret`.
En una máquina que no es VM salta la comprobación del marcador con
`AUTOBOT_RESTORE_SKIP_BOOTSTRAP_CHECK=true` (avisándolo), no la falsifica.

**Verificación:** `/health` responde 200, compara por tenant los conteos de `contact`,
`inbound_event` y `outbound_message` con el origen o informe previo; comprueba un
flujo por el bot de demo. Anota SHA, snapshot, hora de inicio/fin y duración; la
meta es menos de dos horas. Borra la VPS temporal tras el simulacro autorizado.
