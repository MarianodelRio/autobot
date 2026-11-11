# Preparar la VPS de Autobot

**Síntoma:** no hay servidor listo, el despliegue SSH falla, o un segundo bootstrap cambia
la configuración. **Diagnóstico:** comprueba DNS, SSH, puertos, Docker y timer por separado.
Este procedimiento lo ejecuta la persona operadora en una VPS nueva, con el dominio ya apuntando a ella. El
agente no lo ejecuta. Antes de empezar, guarda en tu gestor de contraseñas la clave
privada de operación y la clave de CI, y confirma que puedes abrir una sesión `root`
con tu clave en la VPS recién creada.

1. Copia `deploy/scripts/bootstrap-server.sh` a la VPS nueva. Prepara dos ficheros de
   **claves públicas** distintas: `operator.pub` y `ci.pub`. Además, crea en GitHub
   una deploy key **solo lectura** para el repositorio y copia su clave privada a
   `github-read-key` en la VPS (modo 0600). Prepara `github-known-hosts` con la
   huella SSH de GitHub verificada por un canal independiente. Las claves privadas
   del operador y de CI permanecen fuera de la VPS.
2. Como `root`, ejecuta
   `REPO_URL=git@github.com:<owner>/<repo>.git bash deploy/scripts/bootstrap-server.sh operator.pub ci.pub github-read-key github-known-hosts`. El
   script exige Ubuntu 24.04, instala Docker Engine/Compose desde el repositorio oficial,
   `ufw`, `fail2ban`, actualizaciones automáticas y restic; crea `deploy`, clona el
   repositorio en `/srv/autobot`, instala el timer de backup y deshabilita SSH de
   root y contraseña. La clave de CI lleva un comando forzado: solo acepta
   `deploy/scripts/deploy.sh <sha completo de main>`. La clave de operación permite
   mantenimiento y el túnel del panel. La clave de lectura del repositorio permite
   `git fetch` del código que corresponde al SHA de despliegue.
3. Abre **otra sesión** con la clave de operación: `ssh deploy@<host>`. Comprueba
   `docker compose version`,
   `systemctl is-enabled autobot-backup.timer` y
   `systemctl is-enabled autobot-containers.timer`. Si la sesión falla, conserva la
   consola del proveedor para corregir `authorized_keys` antes de cerrarla.
4. Ejecuta el mismo bootstrap de nuevo desde la consola del proveedor; verifica que
   no añade usuarios, claves, reglas de firewall ni unidades duplicadas. Comprueba
   `sshd -T | grep -E 'permitrootlogin|passwordauthentication'` y
   `ufw status numbered`. Desde otra máquina, escanea los puertos públicos; solo deben
   aparecer 22, 80 y 443. Los puertos 8000 (`web`) y 8080 (`panel`) escuchan
   únicamente en 127.0.0.1.
5. En `/srv/autobot/.env`, usa `.env.example` como guía y fija `DEPLOY_UID` con
   `id -u deploy`, y `AUTOBOT_IMAGE` y `AUTOBOT_PANEL_IMAGE` con las imágenes de tu
   repo sin tag (`ghcr.io/<owner>/autobot` y `ghcr.io/<owner>/autobot-panel`);
   `ensure-env.sh` se niega a seguir sin ellas. Crea `var/google_sa.json`, `var/backup.env` y
   `var/restic-password` como propietario `deploy`, modo 0600. El usuario no root de
   `web` y los `worker-*` usan ese UID para leer el fichero de cuenta de servicio montado. La cuenta de
   servicio y los tokens reales dependen de Google Cloud, del bot de avisos y de los secretos de GitHub. En
   `DJANGO_ALLOWED_HOSTS`, incluye `api.<dominio>`, `localhost` y `127.0.0.1`:
   el panel recibe el host local al entrar por el túnel SSH.
6. Desde la consola del proveedor como root, inicia el timer con
   `systemctl start autobot-backup.timer` solo después de
   configurar `var/backup.env`, `var/restic-password` y el destino remoto de los backups.
   Antes del primer despliegue, comprueba que los paquetes GHCR (`autobot` y
   `autobot-panel`) son públicos o configura autenticación de lectura para `deploy`
   en Docker. En GitHub, crea el entorno
   `production` con revisión requerida, si tu plan de GitHub lo permite, y añade
   `DEPLOY_HOST`, `DEPLOY_SSH_KEY` y `DEPLOY_KNOWN_HOSTS`. Fija `known_hosts` desde
   una huella verificada fuera de la conexión inicial.

**Verificación:** la sesión de operación funciona, la clave de CI rechaza comandos
distintos del despliegue, `docker compose version` responde, el timer está activo,
`ufw` solo abre 22/80/443 y un segundo bootstrap deja los mismos ficheros de
configuración. El primer despliegue y el escaneo externo son pasos del plan de lanzamiento
(`docs/plan-lanzamiento.md`); este procedimiento no los da por hechos.

El Django Admin se eliminó (ADR-008); el panel (`docs/procedimientos/panel.md`) solo se
alcanza por `make panel-tunnel` (túnel al puerto 8080 del contenedor `panel`), nunca
por el Caddy público. La operación tras el despliegue se hace por SSH con la clave
de operación y
`docker compose exec web python manage.py <comando>`
(`docs/referencia/comandos.md`), o con los comandos de resolución (`outbound_resolve`, `job_retry`).
El puerto 8000 del servidor no se expone públicamente. Para un backup manual,
`make backup-now HOST=<host>` usa esa misma clave de operación; la clave de CI no
puede ejecutarlo.

Los secretos de canal están cifrados en la BD; no hay YAML de secretos montado en
`web` ni en los `worker-*`. Configura `SECRETS_ENCRYPTION_KEY` en `.env` antes del primer
despliegue y conserva su copia con los backups. `deploy/scripts/manage.sh` usa el SHA de
`.deployed-sha` para los comandos de operación; desde local se invoca mediante
`make prod-manage HOST=<servidor> CMD="..."` (`TTY=1` si pide una confirmación).

**Sistema:** cada cinco minutos `ops.check.run()` guarda una muestra
(`system_sample`: CPU, memoria, carga, disco y tamaño de la base) y borra las de más de
62 días. `deploy/scripts/backup.sh` escribe `var/state/ops/backup.json` de forma atómica
(`{finished_at, ok, dump_bytes}`) y `deploy/scripts/deploy.sh` añade una línea a
`var/state/ops/deploys.jsonl` por cada intento (`deployed`, `already`, `aborted`,
`rolled_back` o `rollback_failed`). `web`, `worker-inbound` y `worker-outbound` montan
`var/state/ops` en solo lectura en `/run/ops`.

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

**Logs técnicos:** el servicio `victorialogs` (imagen fijada, sin
publicar puertos) recibe los logs de `web` y los `worker-*` por `VICTORIALOGS_URL`; los
guarda 31 días. `deploy/scripts/deploy.sh` lo actualiza en cada despliegue, pero su
caída nunca aborta ni hace retroceder uno: el `VictoriaLogsHandler` descarta en
silencio lo que no puede enviar. Para consultarlo, usa la pantalla Logs del panel
(ADR-008); no está expuesto fuera de la red interna.
