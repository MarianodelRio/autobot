# Preparar la VPS de Autobot

**Síntoma:** no hay servidor listo, el despliegue SSH falla, o hay que repetir/reparar la
instalación. **Diagnóstico:** `sudo deploy/scripts/install-vm.sh --check` dice qué pasos
están hechos y cuáles pendientes. El agente no lo ejecuta contra un servidor real.
Decisiones y motivos: ADR-012 y ADR-017.

## Instalación: un comando, dentro de la VM

Antes de empezar: una VM Ubuntu 24.04 con acceso `root` o `sudo` por clave SSH, el
registro DNS de `api.<dominio>` apuntando a ella (o se hace después), la cuenta de
servicio de Google y, si ya los tienes, los tokens externos. Los paquetes GHCR
(`autobot`, `autobot-panel`) deben ser públicos y el CI del commit en verde (el instalador
comprueba que la imagen existe).

```bash
git clone https://github.com/<owner>/<repo>.git && cd <repo>
sudo deploy/scripts/install-vm.sh --public-host api.<dominio> --google-sa ~/google_sa.json \
  [--env-file ~/install.env]
```

`--env-file` es un `CLAVE=valor` (modo 0600, fuera del repo) con credenciales externas
opcionales: `DEMO_TELEGRAM_TOKEN`, `NOTIFY_BOT_TOKEN`, `OPS_TELEGRAM_CHAT_ID`,
`SENTRY_DSN`, `HEALTHCHECKS_PING_URL`, los `DEMO_*`, y los de backup (`RESTIC_REPOSITORY`,
`AWS_*`, `HEALTHCHECKS_BACKUP_PING_URL`, que van a `var/backup.env`). Sin
`--operator-key`, usa la única clave de `~/.ssh/authorized_keys` del usuario que ejecuta
`sudo`; con varias, pasa `--operator-key <fichero.pub>`. Sin Google todavía:
`--no-google-sa` (Calendar no funcionará hasta subir el real).

Pasos, en este orden (cada uno comprueba antes si ya está hecho; se puede repetir el
comando entero, o `--only paso` / `--skip paso`):

1. `ci-key`: genera dentro de la VM la clave ed25519 de CI (la privada queda en
   `/root/autobot-ci-deploy-key`, solo root).
2. `base`: `bootstrap-server.sh --base` (paquetes, Docker, swap, cuentas `deploy` y
   `admin` con la **misma** clave del operador, clon en `/srv/autobot`, timers). La clave
   de CI se instala en `deploy` con `restrict,command="…/ssh-deploy.sh"`, que solo deja
   pasar `deploy/scripts/deploy.sh <sha de main>`.
3. `env`: `.env` (valores explícitos y `ensure-env.sh`, que genera los secretos internos y
   nunca inventa los externos), `var/google_sa.json`.
4. `deploy`: primer despliegue del commit del clon (o `--sha`) por el mismo
   `ssh-deploy.sh` que usa el CI.
5. `health`: web, panel, workers, HTTPS y timers.
6. `harden-ssh`: cierra root y contraseña, solo `admin`/`deploy`, `ufw` 22/80/443 y
   `fail2ban`. **Pide confirmar** que has abierto otra sesión como `admin@` y `deploy@`;
   rechaza seguir si sshd no escucha solo en el 22 o la clave no está en ambas cuentas.
   Sin terminal y sin `--yes` se omite y queda pendiente. La consola del proveedor sigue
   siendo la salida de emergencia.
7. `marker`: escribe `/var/lib/autobot/bootstrap-complete` (lo exige `restore.sh`), solo
   si el SSH está endurecido.
8. `github` (opcional): si `gh` está instalado y autenticado en la VM y confirmas, crea el
   entorno `production` si falta y sube `DEPLOY_HOST`, `DEPLOY_SSH_KEY` y
   `DEPLOY_KNOWN_HOSTS` (la clave de host se lee en la VM, sin fiarse de la red), y borra
   la clave privada con `shred`.

Al final imprime un **resumen de pasos manuales pendientes**. Lo habitual:

- **DNS** del `PUBLIC_HOST` a la IP de la VM.
- **Secretos de GitHub** si no se subieron con `gh`, desde el portátil:
  `ssh admin@<host> 'sudo cat /root/autobot-ci-deploy-key' | gh secret set DEPLOY_SSH_KEY --env production`,
  luego `ssh admin@<host> 'sudo shred -u /root/autobot-ci-deploy-key'`, y `DEPLOY_HOST`,
  `DEPLOY_KNOWN_HOSTS`.
- **Entorno `production` de GitHub**: restringirlo a la rama `main` y con revisores
  obligatorios (Settings → Environments); sin eso cualquier rama con acceso al workflow
  puede usar la clave de despliegue.
- **Backups**: `var/backup.env`, `var/restic-password` (cópiala a tu gestor de
  contraseñas), `restic init` **a mano** (nunca automático), un `backup.sh`, y
  `sudo systemctl start autobot-backup.timer`. Fija también la retención de GHCR para
  cubrir los 6 meses de `--keep-monthly 6` (`restaurar.md`).
- **Healthchecks.io** (`HEALTHCHECKS_PING_URL`, `HEALTHCHECKS_BACKUP_PING_URL`), Sentry,
  chat de avisos y tokens de Telegram en `.env` (como `deploy`), y relanzar el despliegue.
- **Google**: la cuenta de servicio real si se instaló el marcador vacío.
- **Panel**: `ssh -t deploy@<host> deploy/scripts/manage.sh panel_user create panel` y
  los webhooks (`telegram_set_webhook`).

Para rotar la clave de CI: `sudo deploy/scripts/install-vm.sh --only ci-key --rotate-ci-key`
y repetir la entrega. Para preparar una VM solo para restaurar o recibir un traslado:
`--restore-target` (sin `.env` ni despliegue; ver `restaurar.md`).

**Verificación:** `install-vm.sh --check` sin pendientes, sesiones de `deploy` y `admin`
funcionando, la clave de CI rechaza comandos distintos del despliegue, los timers activos,
`ufw` solo abre 22/80/443 (`ufw status numbered`) y repetir `install-vm.sh` no cambia
nada. Los puertos 8000 (`web`) y 8080 (`panel`) escuchan solo en 127.0.0.1. Comprueba
además desde otra máquina, con un escaneo de puertos contra la IP pública, que solo
responden 22, 80 y 443.

El panel (`docs/procedimientos/panel.md`) solo se
alcanza por `make panel-tunnel` (túnel al puerto 8080 del contenedor `panel`), nunca
por el Caddy público. La operación tras el despliegue se hace por SSH con la clave
de operación como `deploy` y `deploy/scripts/manage.sh python manage.py <comando>`
(`docs/referencia/comandos.md`), o con los comandos de resolución (`outbound_resolve`, `job_retry`);
una tarea que necesite `sudo` (actualizar paquetes, reiniciar `sshd`, repetir el
bootstrap) se hace como `admin`. Un `docker compose exec web ...` a mano en el
servidor falla sin exportar `SHA` y sin `--env-file`; usa `deploy/scripts/compose.sh
<comando>` en su lugar, que (como `manage.sh`) toma ambos de `deploy/scripts/lib.sh`.
El puerto 8000 del servidor no se expone públicamente. Para un backup manual,
`make backup-now HOST=<host>` usa esa misma clave de operación; la clave de CI no
puede ejecutarlo.

Los secretos de canal están cifrados en la BD; no hay YAML de secretos montado en
`web` ni en los `worker-*`. Configura `SECRETS_ENCRYPTION_KEY` en `.env` antes del primer
despliegue y conserva su copia con los backups. `deploy/scripts/manage.sh` y
`deploy/scripts/compose.sh` usan el SHA de `.deployed-sha` para los comandos de
operación; desde local se invocan mediante `make prod-manage HOST=<servidor> CMD="..."`
y `make prod-compose HOST=<servidor> ARGS="..."` (`TTY=1` si piden una confirmación).

**Sistema:** cada cinco minutos `ops.check.run()` guarda una muestra
(`system_sample`: CPU, memoria, carga, disco y tamaño de la base) y borra las de más de
62 días. `deploy/scripts/backup.sh` escribe `var/state/ops/backup.json` de forma atómica
(`{finished_at, ok, dump_bytes}`) y `deploy/scripts/deploy.sh` añade una línea a
`var/state/ops/deploys.jsonl` por cada intento (`deployed`, `already`, `aborted`,
`rolled_back` o `rollback_failed`), con `via: rollback` cuando deshace exactamente el
despliegue anterior (`make rollback` se niega a encadenar un segundo). `web`,
`worker-inbound` y `worker-outbound` montan `var/state/ops` en solo lectura en
`/run/ops`. Tras cada despliegue o reversión, `deploy.sh` recarga Caddy si su
fichero cambió (`up` no lo reinicia solo porque cambie el contenido de un fichero
montado) y comprueba `https://$PUBLIC_HOST/health`; si falla, solo avisa, nunca
aborta (el DNS o el certificado pueden tardar en el primer despliegue).

**Vigilancia de contenedores:** el timer `autobot-containers.timer` (instalado y
arrancado por `bootstrap-server.sh`, de solo lectura) ejecuta cada minuto
`deploy/scripts/containers.sh`, que hace `docker inspect` de los contenedores del
proyecto compose y escribe una instantánea en lista blanca en
`var/state/ops/containers.json`; ningún contenedor accede a `docker.sock`.
`ops_check` la evalúa y el panel la muestra en la tarjeta Contenedores de Sistema
(`docs/procedimientos/panel.md`). Para comprobar que funciona:
`systemctl is-enabled autobot-containers.timer` y que
`var/state/ops/containers.json` se actualiza cada minuto
(`stat -c %Y var/state/ops/containers.json` cambia entre comprobaciones, o
`journalctl -u autobot-containers.service --since -2min`). Si deja de actualizarse,
ver `docs/incidencias/contenedor-caido.md`.

**Disco:** el timer `autobot-prune.timer` (instalado y arrancado por
`bootstrap-server.sh`) ejecuta a diario `deploy/scripts/prune.sh`
(`docker image prune --all --force --filter 'until=24h'`): cada despliegue deja la
imagen anterior en disco (útil para un `rollback` instantáneo) y capas sueltas de
`pull`s fallidos, que en 40 GB se notan. Solo borra lo que ningún contenedor usa y
tiene más de un día; un `rollback` más allá de eso vuelve a descargar la imagen,
igual que cualquier `pull` normal. Comprobar: `systemctl is-enabled autobot-prune.timer`.

**Logs técnicos:** el servicio `victorialogs` (imagen fijada, sin
publicar puertos) recibe los logs de `web` y los `worker-*` por `VICTORIALOGS_URL`; los
guarda 31 días, con un límite adicional de 5 GiB en disco
(`-retention.maxDiskSpaceUsageBytes`) que descarta el día más antiguo si se alcanza
antes. `deploy/scripts/deploy.sh` lo actualiza en cada despliegue, pero su
caída nunca aborta ni hace retroceder uno: el `VictoriaLogsHandler` descarta en
silencio lo que no puede enviar. Para consultarlo, usa la pantalla Logs del panel
(ADR-008); no está expuesto fuera de la red interna.

## Traslado a otro servidor

Para cambiar de proveedor o ampliar la máquina cuando el proveedor no permite hacerlo
sobre la misma. Si lo permite, basta un reinicio y no hace falta nada de esto. Con el
mismo dominio no hay que tocar los webhooks. Si en cambio se ha perdido la máquina
original, ver `docs/incidencias/perdida-total.md`.

**Qué viaja en el backup:** base de datos, `.env` (incluye la clave de cifrado),
`google_sa.json`, `.deployed-sha`, certificados y estado de Caddy (`var/state/caddy-*`)
y `deploys.jsonl`. **Guárdalos en el gestor de contraseñas, fuera del backup:** la
contraseña de restic, las claves S3 y las claves SSH.

`make server-migrate FROM=<a> TO=<b>` (`deploy/scripts/server-migrate.sh`; pasos
`rehearse`, `freeze`, `cutover`, `start-destination`, `finish`, repetibles con
`ONLY=<paso>`; pide confirmación antes de cada paso destructivo o visible desde fuera):

1. 24 horas antes, baja el TTL del DNS a 60-300 s.
2. En el destino, `install-vm.sh --restore-target`: deja la VM lista sin `.env` ni despliegue (ver `restaurar.md`).
3. Ensayo en el destino (`AUTOBOT_RESTORE_DB_ONLY=true`) y comparación de conteos por
   negocio; `down -v` antes del corte real.
4. Corte en el origen: crea `var/.frozen` (que `deploy.sh` y `restore.sh` respetan),
   desactiva el workflow de despliegue, para `worker-inbound`, `worker-outbound`, `web`,
   `panel`, `caddy` y el timer de backup, y hace un backup final; anota el id del snapshot.
5. En el destino, restaura **ese snapshot concreto** (`AUTOBOT_RESTORE_SNAPSHOT=<id>`,
   nunca `latest`), con `DEPLOY_UID`, roles, permisos y certificados.
6. Arranca todo menos los workers y verifica con `curl --resolve`. Comprueba que el origen
   no tiene ningún contenedor de aplicación en marcha y arranca los workers del destino
   con `deploy/scripts/compose.sh up -d worker-inbound worker-outbound`.
7. Cambia el DNS a mano.
8. Actualiza `DEPLOY_HOST` y `DEPLOY_KNOWN_HOSTS` en GitHub, reactiva el workflow y el
   timer del destino, y conserva el origen parado (con `var/.frozen`) 7 días.

Corte estimado (no medido todavía): 15-30 minutos más el TTL del DNS, sin pérdida de datos
salvo logs técnicos. En una pérdida de la máquina, se pierde como mucho la última hora
(el backup es horario) y la recuperación tarda 1-2 horas.
