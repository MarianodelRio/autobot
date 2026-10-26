# Preparar la VPS de FlowPilot

**Síntoma:** no hay servidor listo, el despliegue SSH falla, o un segundo bootstrap cambia
la configuración. **Diagnóstico:** comprueba DNS, SSH, puertos, Docker y timer por separado.
Este procedimiento lo ejecuta la persona operadora en una VPS nueva, tras M-7.1. El
agente no lo ejecuta. Antes de empezar, guarda en tu gestor de contraseñas la clave
privada de operación y la clave de CI, y confirma que puedes abrir una sesión `root`
con tu clave en la VPS recién creada.

1. Copia `deploy/bootstrap-server.sh` a la VPS nueva. Prepara dos ficheros de
   **claves públicas** distintas: `operator.pub` y `ci.pub`. Además, crea en GitHub
   una deploy key **solo lectura** para el repositorio y copia su clave privada a
   `github-read-key` en la VPS (modo 0600). Prepara `github-known-hosts` con la
   huella SSH de GitHub verificada por un canal independiente. Las claves privadas
   del operador y de CI permanecen fuera de la VPS.
2. Como `root`, ejecuta
   `bash deploy/bootstrap-server.sh operator.pub ci.pub github-read-key github-known-hosts`. El
   script exige Ubuntu 24.04, instala Docker Engine/Compose desde el repositorio oficial,
   `ufw`, `fail2ban`, actualizaciones automáticas y restic; crea `deploy`, clona el
   repositorio en `/srv/flowpilot`, instala el timer de backup y deshabilita SSH de
   root y contraseña. La clave de CI lleva un comando forzado: solo acepta
   `deploy/deploy.sh <sha completo de main>`. La clave de operación permite
   mantenimiento y el túnel Admin. La clave de lectura del repositorio permite
   `git fetch` del código que corresponde al SHA de despliegue.
3. Abre **otra sesión** con la clave de operación: `ssh deploy@<host>`. Comprueba
   `docker compose version` y
   `systemctl is-enabled flowpilot-backup.timer`. Si la sesión falla, conserva la
   consola del proveedor para corregir `authorized_keys` antes de cerrarla.
4. Ejecuta el mismo bootstrap de nuevo desde la consola del proveedor; verifica que
   no añade usuarios, claves, reglas de firewall ni unidades duplicadas. Comprueba
   `sshd -T | grep -E 'permitrootlogin|passwordauthentication'` y
   `ufw status numbered`. Desde otra máquina, escanea los puertos públicos; solo deben
   aparecer 22, 80 y 443. El puerto 8000 escucha únicamente en 127.0.0.1.
5. En `/srv/flowpilot/.env`, usa `.env.example` como guía y fija `DEPLOY_UID` con
   `id -u deploy`. Crea `secrets.yaml`, `google_sa.json`, `backup.env` y
   `restic-password` como propietario `deploy`, modo 0600. El usuario no root de
   `web` y `worker` usa ese UID para leer los dos secretos montados. La cuenta de
   servicio y los tokens reales dependen de M-5.1, M-6.1 y M-7.3.
6. Desde la consola del proveedor como root, inicia el timer con
   `systemctl start flowpilot-backup.timer` solo después de
   configurar `backup.env`, `restic-password` y el destino remoto de M-7.2.
   Antes del primer despliegue, comprueba que el paquete GHCR es público o configura
   autenticación de lectura para `deploy` en Docker. En GitHub, crea el entorno
   `production` con revisión requerida, si tu plan de GitHub lo permite, y añade
   `DEPLOY_HOST`, `DEPLOY_SSH_KEY` y `DEPLOY_KNOWN_HOSTS`. Fija `known_hosts` desde
   una huella verificada fuera de la conexión inicial.

**Verificación:** la sesión de operación funciona, la clave de CI rechaza comandos
distintos del despliegue, `docker compose version` responde, el timer está activo,
`ufw` solo abre 22/80/443 y un segundo bootstrap deja los mismos ficheros de
configuración. El primer despliegue y el escaneo externo pertenecen a M-7.6;
este runbook no los da por hechos.

Para entrar al Admin tras el despliegue, en tu máquina ejecuta
`make admin-tunnel HOST=<host>` con la clave de operación. Abre
`http://127.0.0.1:18000/admin/` y usa TOTP. El puerto 8000 del servidor no se
expone públicamente. Para un backup manual, `make backup-now HOST=<host>` usa esa
misma clave de operación; la clave de CI no puede ejecutarlo.
