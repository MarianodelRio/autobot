# Preparar la VPS de Autobot

**Síntoma:** no hay servidor listo, el despliegue SSH falla, o un segundo bootstrap cambia
la configuración. **Diagnóstico:** comprueba DNS, SSH, puertos, Docker y timer por separado.
`make server-init` (A15) automatiza los pasos de este procedimiento; lo que sigue es su
desglose, para entender qué hace cada paso y para el ensayo manual (A16) o si algo falla
a mitad. El agente no lo ejecuta contra un servidor real. Antes de empezar, guarda en tu
gestor de contraseñas la clave privada de operación y confirma que puedes abrir una
sesión `root` (o con `sudo`, según el proveedor) con tu clave en la VPS recién creada.

1. Copia `deploy/scripts/bootstrap-server.sh` a la VPS nueva. Prepara dos ficheros de
   **claves públicas**: `operator.pub` (la tuya; se instala tanto en `admin` como en
   `deploy`) y `ci.pub` (solo en `deploy`, con comando forzado). El repositorio es
   público, así que no hace falta ninguna deploy key: el clon es por HTTPS.
2. Ejecuta, como `root` o con `sudo` (el script se reinvoca con `sudo` solo si no es
   ya root):
   `REPO_URL=https://github.com/<owner>/<repo>.git bash deploy/scripts/bootstrap-server.sh --base operator.pub ci.pub`.
   Esta fase instala Docker Engine/Compose desde el repositorio oficial, `ufw`
   (sin activar todavía), `fail2ban`, actualizaciones automáticas, restic y 2 GB de
   swap; crea dos cuentas con la **misma** clave de operación, `deploy` (sin `sudo`,
   en el grupo `docker`; además acepta la clave de CI, restringida a
   `deploy/scripts/deploy.sh <sha completo de main>`) y `admin` (con `sudo` sin
   contraseña: no hay contraseñas en ningún sitio, la entrada ya está controlada por
   la clave); clona el repositorio en `/srv/autobot` e instala los timers. **No
   toca SSH todavía**, así que es seguro repetirla desde la misma sesión.
3. Abre **dos sesiones nuevas**: `ssh deploy@<host>` y `ssh admin@<host>`, ambas con
   tu clave de operación. En la de `deploy`, comprueba `docker compose version` y
   `systemctl is-enabled autobot-backup.timer/autobot-containers.timer/autobot-prune.timer`.
   En la de `admin`, comprueba `sudo true`. Si cualquiera falla, conserva la consola
   del proveedor para corregir `authorized_keys` antes de cerrarla: todavía hay
   acceso de emergencia porque SSH no está endurecido.
4. Solo tras verificar el paso 3, ejecuta
   `sudo bash deploy/scripts/bootstrap-server.sh --harden-ssh` (como `admin`). Cierra
   el acceso de `root` y por contraseña, limita las sesiones a `deploy`/`admin` y
   activa `ufw` (22, 80, 443) y la cárcel de `fail2ban` para SSH. Repítela; verifica
   que no cambia nada (`sshd -T | grep -E 'permitrootlogin|passwordauthentication'`,
   `ufw status numbered`). Desde otra máquina, escanea los puertos públicos; solo
   deben aparecer 22, 80 y 443. Los puertos 8000 (`web`) y 8080 (`panel`) escuchan
   únicamente en 127.0.0.1.
5. En `/srv/autobot/.env`, usa `.env.example` como guía y fija `AUTOBOT_IMAGE` y
   `AUTOBOT_PANEL_IMAGE` con las imágenes de tu repo sin tag (`ghcr.io/<owner>/autobot`
   y `ghcr.io/<owner>/autobot-panel`); `ensure-env.sh` se niega a seguir sin ellas y,
   como `DEPLOY_UID`, lo recalcula siempre con `id -u` (nunca a mano). Crea
   `var/google_sa.json`, `var/backup.env` y `var/restic-password` como `deploy`, modo
   0600. El usuario no root de `web` y los `worker-*` usan ese UID para leer el
   fichero de cuenta de servicio montado. La cuenta de servicio y los tokens reales
   dependen de Google Cloud, del bot de avisos y de los secretos de GitHub. En
   `DJANGO_ALLOWED_HOSTS`, incluye `api.<dominio>`, `localhost` y `127.0.0.1`:
   el panel recibe el host local al entrar por el túnel SSH.
6. Inicializa restic a mano (`restic init` nunca es automático, A3) y anota el
   destino y la contraseña en `var/backup.env`/`var/restic-password`; solo entonces,
   como `deploy` (o `admin` con `sudo systemctl`), arranca el timer con
   `systemctl start autobot-backup.timer`. Antes del primer despliegue, comprueba
   que los paquetes GHCR (`autobot` y `autobot-panel`) son públicos o configura
   autenticación de lectura para `deploy` en Docker. Fija también su política de
   retención (GitHub → paquete → *Package settings*) para que cubra al menos los 6
   meses que `backup.sh` conserva (`--keep-monthly 6`): si GHCR borra la imagen de un
   SHA antes de eso, restaurar ese snapshot falla al no poder descargarla (A14,
   `docs/procedimientos/restaurar.md`). En GitHub, crea el entorno `production` con
   revisión requerida, si tu plan de GitHub lo permite, y añade `DEPLOY_HOST`,
   `DEPLOY_SSH_KEY` y `DEPLOY_KNOWN_HOSTS`. Fija `known_hosts` desde una huella
   verificada fuera de la conexión inicial.

**Verificación:** las sesiones de `deploy` y `admin` funcionan, la clave de CI rechaza
comandos distintos del despliegue, `docker compose version` responde, los timers están
activos, `ufw` solo abre 22/80/443 y repetir `--base` y `--harden-ssh` no cambia nada. El
primer despliegue y el escaneo externo son pasos del plan de lanzamiento
(`docs/plan-lanzamiento.md`); este procedimiento no los da por hechos.

El Django Admin se eliminó (ADR-008); el panel (`docs/procedimientos/panel.md`) solo se
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
