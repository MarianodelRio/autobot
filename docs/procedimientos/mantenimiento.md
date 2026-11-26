# Mantenimiento periódico

Revisiones recurrentes de la plataforma en producción, cómo liberar disco y cómo subir de
versión mayor PostgreSQL. Lo que ya comprueba el CI en cada commit (tests, auditoría de
dependencias, validez de compose y Caddy, simulacro de copia y restauración) no se repite
aquí: ver [despliegue.md](despliegue.md).

## Objetivo, cuándo y requisitos

- **Objetivo:** que backups, disco, dependencias y cuentas de canal sigan sanos sin que
  salte una alerta.
- **Cuándo:** mensual, semestral y trimestral según la tabla; y ante una alerta de disco.
- **Requisitos:** acceso SSH como `deploy` (clave de operación), panel por túnel
  (`make panel-tunnel`). Las pruebas reales o los cambios de canal requieren intervención
  humana.

## Calendario

| Cuándo | Qué |
|---|---|
| Mensual | Mirar en el panel (Sistema) la fecha del último backup, disco, TLS y despliegues. Comprobar `timedatectl` (reloj sincronizado) y que la limpieza de retención de las 03:00 UTC deja rastro (`retention_cleanup`). Subir dependencias a mano (no se usa Dependabot): ver [dependencias](#dependencias). Si hubo parches de kernel, planificar un reinicio de la VPS como `admin` |
| Cada seis meses | Verificar la versión soportada de Graph API antes de cambiar `WHATSAPP_GRAPH_VERSION` |
| Trimestral | Calidad del número y plantillas de WhatsApp en Meta; simulacro de restauración ([restaurar.md](restaurar.md)) anotando el RTO; revisar la retención de paquetes de GHCR; revisar las cuentas externas: segundo factor activo, códigos de recuperación en el gestor, quién tiene acceso en Meta y GitHub, claves SSH autorizadas en `admin` y `deploy` ([cuentas externas](../arquitectura/seguridad-y-secretos.md#cuentas-externas-y-acceso)) |

**Backups:** cada backup valida el volcado (`pg_restore --list`) antes de subirlo y
comprueba el espacio libre; el primero de cada semana ISO ejecuta `restic check
--read-data-subset=5%` y, si falla, el backup falla sin avisar a Healthchecks. Si salta,
haz un `restic check` completo antes de fiarte del repositorio.

**Verificación:** CI verde, alertas resueltas, backup reciente (`ok`) en el panel y
`make tenant-health SLUG=<slug>` sin degradaciones tras el mantenimiento.

## Dependencias

No hay Dependabot: las subidas se hacen a mano, en un commit con CI en verde. Las auditorías (`pip-audit`, `pnpm audit`, Trivy sobre la imagen) solo se ejecutan con cada push a `main`, así que un mes sin commits es un mes sin revisar vulnerabilidades nuevas.

- **Backend:** `uv lock --upgrade` en `apps/backend/` (o `--upgrade-package <nombre>`) y `make check`.
- **Panel:** `pnpm -C apps/panel outdated` y `pnpm -C apps/panel update`, con sus tests.
- **Imágenes base** (`FROM` de los Dockerfile, imágenes de `compose.prod.yaml`): cambia tag y digest a la vez, resolviendo el digest con `docker buildx imagetools inspect <imagen:tag>`.
- **Acciones de GitHub:** el SHA real del tag con `git ls-remote` y el comentario con la versión ([seguridad y secretos](../arquitectura/seguridad-y-secretos.md#cadena-de-suministro-y-analisis-en-ci)).
- Una versión mayor de Python, Node o PostgreSQL es un cambio aparte, nunca junto a otras subidas ([PostgreSQL](#subir-de-version-mayor-de-postgresql) tiene su procedimiento).

## Disco lleno

**Qué lo dispara.** `ops_check` (cada cinco minutos, `apps/backend/src/autobot/ops/check.py`)
mide el uso del sistema de ficheros donde viven Docker, el volumen de PostgreSQL y los temporales del backup (`/` del contenedor, que es el disco del host, y `/run/ops`, el directorio `var/state/ops` del host por si `/srv` es otro volumen; cuenta el más lleno) y abre:

- `disk` (aviso, 🟠) por encima del **80 %**.
- `disk_critical` (🔴) por encima del **95 %**.

También se ve en el panel, Sistema. Con un disco lleno, PostgreSQL deja de escribir, el
backup falla por falta de espacio (`backup.sh` exige el doble del último volcado, o 512 MiB)
y el despliegue no puede descargar imágenes.

**Pasos** (en la VPS, como `deploy`, en `/srv/autobot`; nada de esto toca datos de
clientes):

1. Mide qué ocupa: `df -h /`, `docker system df` y `du -sh var/* var/backups/* 2>/dev/null`.
2. **Imágenes Docker viejas:** `deploy/scripts/prune.sh` (lo mismo que el timer diario:
   `docker image prune --all --force --filter 'until=24h'`). Conserva las que usa algún
   contenedor y las de las últimas 24 h; un rollback más allá vuelve a descargar la
   imagen. Si espera por el candado, es que hay un despliegue en curso.
3. **Volcados locales:** `var/backups/pre-migrate.dump` (lo borra `prune.sh` a las 48 h,
   junto con cualquier `pre-migrate.dump.tmp`) y cualquier volcado manual que dejaras (`ls -la var/backups`). Contienen datos de
   clientes en claro: bórralos con `rm` en cuanto no hagan falta. `autobot.dump` es
   temporal y lo borra el propio `backup.sh`; si sobrevive, el último backup falló.
4. **Logs de VictoriaLogs:** guarda 31 días con tope de 5 GiB y descarta el día más antiguo
   al llegar. Si aun así pesa, baja el tope (`-retention.maxDiskSpaceUsageBytes` en
   `deploy/compose/compose.yaml`) con un commit y despliegue; no borres su volumen.
5. **Logs de contenedores:** están limitados a 5 ficheros de 20 MB por contenedor
   (`compose.prod.yaml`); no suelen ser la causa. Compruébalo con `docker system df -v`.
6. **Caché del repositorio restic local** y otros restos de `/var/cache` del usuario
   `deploy`: `du -sh ~/.cache 2>/dev/null`; `restic cache --cleanup` borra lo obsoleto.
7. Si no basta, amplía el disco en el proveedor (acción de infraestructura: aprobación
   humana explícita).

**Verificación:** `df -h / /srv/autobot` por debajo del 80 %, la alerta `disk` se resuelve sola en el
siguiente `ops_check` y el siguiente backup termina bien (`make backup-now`).

## Subir de versión mayor de PostgreSQL

`db` está fijada por dígest en `deploy/compose/compose.yaml` a una versión mayor concreta
(hoy 18). Una mayor **no es un cambio de imagen**: el formato de los datos no es
compatible entre mayores, y el volumen `autobot_pgdata` de la versión anterior no arranca
con el binario nuevo. Una menor (mismo número mayor, otro dígest) sí es solo un cambio de
imagen y la despliega `deploy.sh` como cualquier otra.

!!! warning "Qué NO hace `deploy.sh`"
    `deploy.sh` descarga imágenes, hace `up -d --wait db`, migra y arranca; **no
    restaura volcados**. Con un volumen de la versión anterior, `db` no arrancaría y el
    despliegue abortaría. `restore.sh` tampoco sirve para esto: se niega a actuar sobre
    una instalación con `var/.deployed-sha` o con volumen de base de datos. Y `backup.sh`
    solo deja el volcado en restic (borra su copia local al terminar). Es un cambio de
    infraestructura sobre datos de producción: requiere aprobación humana explícita, una
    ventana de mantenimiento y no está ensayado de punta a punta en producción.

**Requisitos:** aprobación; backup reciente comprobado en restic; el cambio de dígest ya
en `main` con CI verde (publica la imagen); espacio libre para dos copias de la base.

**Ensayo previo (portátil, sin servidor):** con el dígest nuevo en tu árbol de trabajo,
`make restore-test` (crea una base con la versión nueva, la respalda y la restaura) y, si
quieres el flujo de despliegue completo, `make localprod-up`.

**Pasos** (en la VPS, como `deploy`, en `/srv/autobot`):

1. `make backup-now` desde el portátil y confirma en restic que hay un snapshot nuevo.
2. Para el tráfico: `deploy/scripts/compose.sh stop caddy worker-inbound worker-calendar worker-periodic worker-outbound
   web web-panel panel`. Los webhooks que lleguen ahora fallarán y los canales los reintentarán.
3. Volcado lógico, con la `db` aún en marcha y comprobado:

    ```bash
    (umask 077 && deploy/scripts/compose.sh exec -T db \
      pg_dump -U postgres -d autobot -Fc > var/backups/major-upgrade.dump)
    deploy/scripts/compose.sh exec -T db pg_restore --list \
      < var/backups/major-upgrade.dump > /dev/null
    ```

4. `deploy/scripts/compose.sh down` (sin `-v`) y aparta el volumen antiguo: copia
   `autobot_pgdata` a `autobot_pgdata_old` con un contenedor temporal
   (`docker run --rm -v autobot_pgdata:/from:ro -v autobot_pgdata_old:/to <imagen> cp -a
   /from/. /to/`) y borra `autobot_pgdata` con `docker volume rm`. Si no hay espacio para la
   copia, no sigas: amplía el disco antes.
5. Despliega el SHA que lleva el dígest nuevo (`make deploy` desde el portátil). `deploy.sh`
   crea la `db` nueva y vacía (la imagen ejecuta `init-roles.sh`), migra el esquema y
   arranca la aplicación sobre una base sin datos de clientes.
6. Inmediatamente, vuelve a parar `caddy`, los workers, `web`, `web-panel` y `panel` (paso 2) y restaura
   el volcado, igual que hace `restore.sh`:

    ```bash
    deploy/scripts/compose.sh exec -T db sh -c \
      'PGPASSWORD="$FP_OWNER_PASSWORD" exec pg_restore -h 127.0.0.1 -U fp_owner -d autobot --clean --if-exists --no-owner --no-acl' \
      < var/backups/major-upgrade.dump
    deploy/scripts/compose.sh exec -T db bash /docker-entrypoint-initdb.d/init-roles.sh
    deploy/scripts/manage.sh apply_grants
    ```

7. Levanta `deploy/scripts/compose.sh up -d web web-panel panel caddy`, comprueba `/health` y los
   conteos por negocio contra los de antes de empezar (`contact` por tenant, como en
   [restaurar.md](restaurar.md)) y solo entonces
   `deploy/scripts/compose.sh up -d worker-inbound worker-calendar worker-periodic worker-outbound`.
8. Cuando todo esté verificado: borra `var/backups/major-upgrade.dump` (datos en claro;
   `prune.sh` no lo limpia) y, pasados unos días, `docker volume rm autobot_pgdata_old`.
   Actualiza el número de versión en este procedimiento y en
   [../arquitectura/adr/ADR-005-vps-docker-compose.md](../arquitectura/adr/ADR-005-vps-docker-compose.md)
   si lo citan.

**Si algo sale mal antes del paso 8:** vuelve a la versión anterior restaurando el volumen
guardado (`autobot_pgdata_old` a `autobot_pgdata`) y desplegando el SHA anterior
(`make deploy SHA=<anterior>`), o restaura el snapshot de restic con
[restaurar.md](restaurar.md).

**Verificación:** `/health` 200, conteos por negocio iguales, un flujo por el bot de demo,
el siguiente backup termina bien y `SELECT version()` en el panel (Datos) da la mayor
nueva.

## Dónde está el código

`deploy/scripts/prune.sh`, `deploy/scripts/backup.sh`, `deploy/compose/compose.yaml`,
`apps/backend/src/autobot/ops/check.py` (`DISK_WARNING_PCT`, `DISK_CRITICAL_PCT`).
