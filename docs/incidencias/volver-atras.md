# Volver atrás un despliegue

**Síntoma:** un SHA nuevo rompe `/health` o el flujo tras desplegar. **Diagnóstico:**
consulta `var/.deployed-sha`, logs de `web`/`worker-inbound`/`worker-outbound` y el
resultado de `deploy.yml`. El script revierte automáticamente si `/health` no queda
sano en 60 s o si alguno de los dos workers se para o se reinicia en sus primeros ~10 s. Si falla antes de cambiar la
imagen (pull, migración o la validación de configuración), mantiene la imagen anterior, devuelve el
repositorio al SHA anterior y avisa con `deploy_aborted`. Comprueba si el aviso a
ops llegó.

**Pasos:** si la reversión automática falló, un operador autorizado ejecuta
`make rollback`: lee del servidor el `previous` del último despliegue correcto
(`var/state/ops/deploys.jsonl`), pide confirmación y lo vuelve a desplegar con
`make deploy SHA=<previous>`. Se niega a encadenar un segundo `make rollback` sobre
ese mismo despliegue (volvería al SHA roto que el primero acaba de abandonar); para
ir más atrás en la historia usa un SHA concreto. Para un SHA concreto en vez del
anterior automático, `make deploy SHA=<sha-completo>` (comprueba antes que su CI
está en verde) y aprueba el job en el entorno `production`. No reviertas migraciones:
deben ser compatibles hacia atrás (regla de expandir y contraer: una migración que
añade schema puede ir en el mismo despliegue que deja de usar lo viejo; una que lo
quita o renombra espera a un despliegue posterior, cuando ya no hace falta poder
volver atrás a código que todavía lo lee). `abort` y la reversión automática
restauran la imagen anterior, nunca el esquema: si una migración ya aplicada hizo
falta deshacerla a mano, `deploy.sh` deja un volcado previo en
`var/backups/pre-migrate.dump` (se sobrescribe en cada despliegue con migraciones
pendientes). Si la causa fue una configuración de tenant, publica una versión anterior
con `POST /tenants/{slug}/rollback` o con `tenant_config import`; no hace falta un
SHA nuevo. El panel ya no muestra el historial en pantalla, pero esos endpoints se
conservan. No cambies webhooks de canales reales sin autorización.

**Sin GitHub (SSH directo):** si GitHub o `gh` no están disponibles, con la clave de operador:
`ssh deploy@<host> 'tail -n 50 /srv/autobot/var/state/ops/deploys.jsonl'` (el `previous` del último
`deployed`), y
`ssh admin@<host>` → `sudo -u deploy bash -lc 'cd /srv/autobot && git fetch origin main &&
git merge-base --is-ancestor <sha> origin/main && git checkout --detach <sha> &&
deploy/scripts/deploy.sh <sha>'`. Lo mismo que hace `ssh-deploy.sh` (el CI) pero sin su candado
previo, así que primero comprueba que no hay otro despliegue en curso. La imagen de ese SHA tiene
que seguir en GHCR (o en disco, si `prune.sh` aún no la quitó).

**Verificación:** `var/.deployed-sha` coincide con el SHA sano, `/health` devuelve
200, la cola continúa y una consulta por el bot de demo funciona.

La configuración de negocios no vuelve atrás al desplegar otra imagen: está versionada
en PostgreSQL. Para recuperarla se publica una versión anterior con
`POST /tenants/{slug}/rollback` o se importa un documento exportado con
`tenant_config import <dir> --comment "Recuperación"`, conservando identidad y estado.
