# ADR-021 — Backups resistentes a un servidor comprometido y clave de cifrado aparte

**Estado:** aceptada

## Contexto

El temporizador de backup del servidor usaba una sola credencial S3 para subir snapshots y
para `restic forget --prune`. Quien controlase el servidor podía por tanto borrar todo el
historial de backups además de los datos vivos. Además, el snapshot incluía el `.env`
completo, con `SECRETS_ENCRYPTION_KEY`: la clave Fernet que descifra los secretos de canal
(`tenant_secret`) viajaba en el mismo snapshot que los datos que protege.

## Decisión

**Credencial de subida sin permiso de borrado.**

- El servidor solo sube. La credencial de `var/backup.env` sube y lee, y solo puede borrar
  bajo el prefijo `locks/` del repositorio: `restic backup` crea siempre un fichero de
  bloqueo y lo borra al terminar (ignora `--no-lock`; comprobado con restic 0.18.1). Un
  bloqueo no lleva datos, así que ese permiso no alcanza al historial, y mantiene el
  bloqueo de restic como protección real entre el backup y la purga. `restore.sh` restaura
  con `--no-lock` (ahí sí se respeta): un servidor nuevo puede tener una credencial de solo
  lectura.
- `backup.sh` ya no ejecuta `forget` ni `--prune`. El `restic check --read-data-subset`
  semanal sigue en el servidor (solo lee).
- La caducidad de snapshots (7 diarios, 4 semanales, 6 mensuales, como antes) es
  `deploy/scripts/backup-prune.sh`, que se ejecuta **desde la máquina de la persona
  operadora** con otra credencial (con permiso de borrado) guardada fuera del servidor y
  fuera de git, en `~/.config/autobot/backup-prune.env` (modo 0600). El script se niega a
  ejecutarse en el servidor (marcador de bootstrap) y fuera de la ventana `:15`–`:50` de
  cada hora: el bloqueo exclusivo de restic impide que coincidan, pero el backup horario
  que encontrase el repositorio bloqueado fallaría esa hora.
- El bucket debe tener **versionado** (con una regla de ciclo de vida que conserve las
  versiones no vigentes unos 30 días): así, aunque alguien borrase objetos con una
  credencial indebida, se podrían recuperar. **Object Lock en modo cumplimiento** protege
  más, pero impide que `prune` borre hasta que expire la retención; solo es compatible si
  la retención es menor que el periodo diario de retención de restic y se acepta que el
  espacio se libere con retraso.

**La clave Fernet fuera del snapshot.**

- `backup.sh` sube `var/backups/autobot.env`: el `.env` sin la línea `SECRETS_ENCRYPTION_KEY`
  (y falla si queda alguna mención). El fichero temporal se borra al terminar.
- `restore.sh` exige la clave por otra vía, indicada explícitamente:
  `AUTOBOT_SECRETS_KEY_FILE=<fichero con la clave en la primera línea>` o
  `SECRETS_ENCRYPTION_KEY=<clave>` en el entorno. Falla antes de tocar nada si falta, si el
  fichero no se puede leer o si no es una clave Fernet válida; y tras restaurar la base
  comprueba que la clave descifra todos los `tenant_secret` restaurados, para no descubrir
  una clave equivocada cuando se lea el primer token de canal. Instala la clave en el `.env`
  restaurado **antes** de `ensure-env.sh`, que si no generaría una clave nueva.
- Los snapshots anteriores a este ADR llevan el `.env` completo; `restore.sh` los acepta
  (avisando) y usa la clave que traen salvo que se indique otra.
- `server-migrate.sh` lee la clave en el destino de `/srv/autobot/var/secrets-key` (o de
  `AUTOBOT_MIGRATE_SECRETS_KEY_FILE`); la persona debe dejarla allí antes del ensayo.
- `restore-test.sh` (CI) comprueba que el snapshot no contiene la clave, que `restore.sh`
  falla sin ella y con una clave equivocada, y que la clave indicada descifra los secretos
  restaurados.
- `var/google_sa.json` **se queda** en el snapshot: no descifra datos de la plataforma, solo
  da acceso a los calendarios compartidos con esa cuenta de servicio, y se puede revocar y
  volver a emitir desde Google. Sacarlo añadiría una segunda pieza de custodia por poco
  beneficio.
- La clave se custodia en el gestor de contraseñas de la persona (ver
  [rotar secretos](../../procedimientos/rotar-secretos.md)), nunca en el repositorio de
  backups.

## Alternativas consideradas

- **Object Lock como única defensa:** bloquea también el `prune` legítimo y no está
  disponible en todos los proveedores; se recomienda como complemento, no como sustituto.
- **Un segundo repositorio restic para la purga:** duplica datos y coste.
- **Cifrar el `.env` del snapshot con otra clave (age, gpg):** mueve el problema de custodia a
  otra clave sin simplificarlo; excluir la única clave que importa es más simple y auditable.
- **Poner la clave en un gestor de secretos del servidor:** sigue en el servidor comprometido.

## Consecuencias

- Un servidor comprometido puede añadir snapshots basura y leer el repositorio (necesita la
  contraseña de restic para cifrar), pero no borrar el historial.
- Los snapshots hechos antes de este ADR siguen conteniendo la clave hasta que caduquen
  (hasta 6 meses). Quien quiera cerrar esa puerta antes debe rotar la clave
  (`rotar-secretos.md`) y esperar a que caduquen o purgarlos.
- Una restauración necesita ahora dos piezas que viven en sitios distintos: el repositorio
  restic con su contraseña y la clave Fernet. Perder la clave equivale a perder los secretos
  de canal (hay que volver a introducirlos); los datos del resto de tablas no se ven afectados.
- La purga deja de ser automática: si nadie ejecuta `backup-prune.sh`, el repositorio crece.
  Conviene ejecutarlo una vez por semana (la persona decide el recordatorio).
- Hay que crear dos credenciales S3 distintas al configurar el bucket (documentado en
  [backups](../../procedimientos/backups.md)).

## Cuándo revisarla

- Si el proveedor de almacenamiento ofrece políticas de solo añadir (append-only) nativas
  que hagan innecesaria la separación de credenciales.
- Si el backup deja de ser horario o se mueve a otro programa distinto de restic.
- Si se adopta un gestor de secretos externo donde custodiar la clave.
