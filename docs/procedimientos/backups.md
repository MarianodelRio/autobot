# Backups: configuración, credenciales y caducidad

Cómo está montada la copia de seguridad y qué custodia cada pieza. Léelo al configurar el
bucket por primera vez, al rotar credenciales o al caducar snapshots. Para restaurar, ve a
[restaurar.md](restaurar.md); la decisión y sus motivos están en
[ADR-021](../arquitectura/adr/ADR-021-backups-resistentes.md).

!!! warning "Aprobaciones"
    Crear o cambiar credenciales del almacenamiento, purgar snapshots y tocar la clave de
    cifrado son acciones sobre datos de producción: las hace una persona, no un agente.

## Qué hace cada parte

| Pieza | Dónde vive | Qué puede |
|---|---|---|
| `autobot-backup.timer` → `deploy/scripts/backup.sh` | El servidor, cada hora, como `deploy` | **Subir** snapshots (la base y el libro de supresiones, etiquetas `autobot` y `autobot-ledger`) y leer el repositorio (`restic check`, fecha de la última purga). No puede borrar |
| `deploy/scripts/backup-prune.sh` (`make backup-prune`) | **Tu máquina**, a mano | Caducar snapshots (`forget --prune`) con otra credencial y dejar el testigo `autobot-prune` |
| Contraseña de restic | `var/restic-password` en el servidor y copia en tu gestor | Cifra y descifra el repositorio |
| Clave de cifrado de secretos (`SECRETS_ENCRYPTION_KEY`) | `.env` del servidor y copia en tu gestor | Descifra `tenant_secret`. **No viaja en el snapshot** |

## Las dos credenciales del bucket

1. **Credencial de subida** (la del servidor, en `var/backup.env`: `AWS_ACCESS_KEY_ID` y
   `AWS_SECRET_ACCESS_KEY`). Permisos mínimos sobre el bucket del backup: listar, leer y
   escribir objetos (`s3:ListBucket`, `s3:GetObject`, `s3:PutObject`), `s3:DeleteObject`
   **solo** sobre el prefijo `locks/` del repositorio y **ningún otro borrado** (ni
   `s3:DeleteObjectVersion`). `restic backup` siempre crea un fichero de bloqueo y lo borra
   al terminar (no admite `--no-lock`): sin ese permiso los bloqueos se acumularían y la
   purga se pararía. Un bloqueo no contiene datos; borrarlo no toca el historial.
2. **Credencial de purga** (la tuya, en `~/.config/autobot/backup-prune.env`, modo 0600,
   **nunca en el servidor ni en git**): la misma `RESTIC_REPOSITORY`, la contraseña de restic
   (`RESTIC_PASSWORD_FILE` o `RESTIC_PASSWORD_COMMAND`) y un par `AWS_*` distinto, con
   `s3:DeleteObject` sobre ese bucket. Plantilla de las variables en
   `deploy/env/backup.env.example`.

El bucket debe tener **versionado** activado, con una regla de ciclo de vida que conserve las
versiones no vigentes unos 30 días: es lo que permite recuperar el historial si alguien
borra objetos con una credencial que no debía. **Object Lock** en modo cumplimiento añade
protección, pero bloquea también la purga legítima hasta que expire la retención (el espacio
se libera con retraso): úsalo solo si la retención es menor que la ventana diaria de restic.

## El libro de supresiones viaja en el backup

Cada backup horario exporta el libro de supresiones (ADR-019: ids y HMAC, sin datos
personales) y lo sube como snapshot propio con la etiqueta `autobot-ledger` (ADR-025).
`restore.sh` toma siempre el **último** y lo reaplica antes de arrancar nada
([restaurar.md](restaurar.md)). Ya no hace falta exportarlo a mano tras cada olvido; si
quieres una copia fuera de restic, `privacy_ledger_export` sigue disponible. Si la
exportación falla, el backup termina en error (panel en rojo, sin latido) aunque la base sí
se haya subido.

## Caducar snapshots

La política (7 diarios, 4 semanales, 6 mensuales, etiqueta `autobot`; el libro, 7 diarios y
4 semanales) vive en `deploy/scripts/backup-prune.sh`. Ejecútalo desde tu portátil, más o
menos una vez por semana (si no lo haces, el repositorio solo crece y `ops_check` abre
`backup_prune_overdue` 🟡 a los 10 días):

```bash
make backup-prune ARGS="--dry-run"   # qué borraría
make backup-prune
```

- Se niega a ejecutarse en el servidor (marcador `/var/lib/autobot/bootstrap-complete`).
- Se niega fuera de los minutos `:15`–`:50` de cada hora (salvo `--dry-run`). El bloqueo
  exclusivo de restic impide que la purga y el backup horario corran a la vez, pero el que
  llega segundo falla: un backup que encuentra el repositorio bloqueado falla esa hora (y
  avisa). Si has parado el temporizador, `AUTOBOT_PRUNE_ANYTIME=true` lo permite.
- Si se queja de un bloqueo viejo (un backup que murió a medias), mira
  `var/state/ops/backup.json` en el servidor y quítalo desde tu máquina con `restic unlock`,
  usando la misma configuración de purga.
- Al terminar sube un snapshot diminuto con la etiqueta `autobot-prune` (el testigo, en
  `--dry-run` no) y caduca los anteriores, dejando los tres últimos. El siguiente backup del
  servidor lee su fecha (solo lectura) y la escribe en `var/state/ops/backup-prune.json`; la
  alerta `backup_prune_overdue` se resuelve sola en cuanto el servidor la ve (hasta una hora).
  En un repositorio sin testigo (anterior al ADR-025) la alerta salta una vez, hasta la
  primera purga.
- Tras purgar, comprueba que el siguiente backup termina bien (`var/state/ops/backup.json`,
  ping de Healthchecks).

## La clave de cifrado de secretos

El snapshot lleva el `.env` **sin** `SECRETS_ENCRYPTION_KEY` (`var/backups/autobot.env`), para
que la clave no viaje con los datos que descifra. Custódiala en tu gestor de contraseñas,
junto a la contraseña de restic pero como entrada aparte, y actualiza esa copia cada vez que
la rotes ([rotar-secretos.md](rotar-secretos.md)). Al restaurar hay que indicarla
explícitamente ([restaurar.md](restaurar.md)). Sin ella la base se restaura, pero los
secretos de canal no se pueden leer y hay que volver a introducirlos.

Los snapshots anteriores al ADR-021 siguen llevando el `.env` completo hasta que caduquen
(hasta 6 meses); si quieres cerrar esa puerta antes, rota la clave.

`var/google_sa.json` sí va en el snapshot: solo da acceso a los calendarios compartidos con
esa cuenta de servicio y se puede revocar y reemitir desde Google.

## Configurar un servidor nuevo

1. Crea el bucket (con versionado) y las dos credenciales anteriores.
2. En el servidor, como `deploy`: `var/backup.env` con la credencial de subida y
   `var/restic-password` (0600); `restic init` a mano (nunca es automático) y un primer
   `deploy/scripts/backup.sh`. Después, como `admin`, `sudo systemctl start autobot-backup.timer`.
3. En tu máquina: `~/.config/autobot/backup-prune.env` con la credencial de purga.
4. Guarda en tu gestor la contraseña de restic **y** la clave de cifrado.

## Dónde está el código

`deploy/scripts/backup.sh`, `deploy/scripts/backup-prune.sh`, `autobot/ops/check.py` (`PRUNE_OVERDUE`), `deploy/env/backup.env.example`,
`deploy/systemd/autobot-backup.*`; pruebas en `apps/backend/tests/tools/test_backup.py` y
`make restore-test`.
