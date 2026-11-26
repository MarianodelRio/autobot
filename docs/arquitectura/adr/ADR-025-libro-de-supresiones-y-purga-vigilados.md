# ADR-025 — Libro de supresiones y purga vigilados automáticamente

**Estado:** aceptada; la alerta `backup_prune_overdue` viene desactivada (`PRUNE_ALERT_ENABLED = False` en `autobot/ops/check.py`) para instalaciones que purgan sin calendario. El testigo y su lectura siguen funcionando, y el resumen diario sigue mostrando la fecha de la última purga, sin aviso. Para reactivarla basta con volver a poner `True`.

## Contexto

Dos pasos manuales de los ADR anteriores dependían de que alguien se acordara de hacerlos,
y los dos fallan en silencio:

- **ADR-019 (libro de supresiones).** Un olvido o una purga se anota en `privacy_suppression`,
  que vive en la misma base que se restaura. Para no resucitar un contacto olvidado tras una
  restauración había que ejecutar `privacy_ledger_export` y guardar la salida fuera del
  servidor **después de cada olvido o purga**, a mano. Si se olvidaba, una restauración
  devolvía datos que se habían borrado por derecho del interesado.
- **ADR-021 (backups resistentes).** El servidor solo sube snapshots; caducarlos
  (`backup-prune.sh`) se hace desde la máquina del operador con otra credencial. Si nadie lo
  ejecuta, el repositorio crece sin límite (coste) y se conservan copias más allá de los seis
  meses que prometen los avisos legales.

## Decisión

- **El libro viaja solo, en el mismo repositorio de restic.** `deploy/scripts/backup.sh`
  (cada hora) exporta el libro con `privacy_ledger_export`, en un contenedor efímero de
  `web-panel` de solo lectura (la exportación sale por stdout; solo se conservan las líneas
  marcadas `privacy.v1`) y lo sube como snapshot propio con la etiqueta `autobot-ledger`.
  Contiene solo ids y HMAC, ningún dato personal, y es diminuto y deduplicado. Si la
  exportación falla, el backup de la base se hace igualmente, pero la ejecución termina con
  error antes del latido (el panel muestra `ok: false` y Healthchecks avisa).
- **`restore.sh` usa el último libro, no el del snapshot restaurado.** Descarga el
  snapshot más reciente con etiqueta `autobot-ledger`, y tras restaurar la base y reaplicar
  permisos, **antes de arrancar `web` o los workers**, ejecuta `privacy_reapply --ledger -`
  (por stdin: el contenedor es de solo lectura). Si el repositorio no tiene ningún snapshot
  de libro (anterior a este ADR), avisa en voz alta y sigue con la tabla de la base
  restaurada. La exportación manual sigue existiendo, como copia opcional adicional.
- **La purga deja un testigo que el servidor puede leer.** `backup-prune.sh`, tras un
  `forget --prune` correcto (nunca en `--dry-run`), sube un snapshot minúsculo con etiqueta
  `autobot-prune` y caduca los testigos anteriores (se guardan los tres últimos). También
  caduca los snapshots del libro (7 diarios, 4 semanales). El servidor no necesita ningún
  permiso nuevo: `backup.sh` solo **lee** (`restic snapshots --no-lock`) la fecha del último
  testigo y la del snapshot más antiguo, y las escribe en `var/state/ops/backup-prune.json`
  (el directorio que los contenedores ven como `/run/ops`).
- **Alerta `backup_prune_overdue` (🟡).** `ops_check` la abre cuando la última purga (o, si
  nunca hubo, el snapshot más antiguo) tiene más de 10 días. Se resuelve sola tras purgar.
  Sin fichero de estado (local, servidor sin backup todavía) no alerta. Runbook:
  [Caducar snapshots](../../procedimientos/backups.md#caducar-snapshots).

## Alternativas consideradas

- **Que el servidor suba el libro a otro sitio con otra credencial.** Más piezas y otra
  credencial que custodiar para un fichero que ya cabe en el repositorio cifrado y
  versionado que existe. Descartada.
- **Incluir el libro en el snapshot principal.** Ataría el libro a la fecha del snapshot que
  se restaura: justo lo que hay que evitar (un olvido posterior no estaría). Descartada.
- **Dar a la credencial del servidor permiso de borrado para que purgue sola.** Rompe la
  garantía del ADR-021 (un servidor comprometido no puede borrar el historial). Descartada.
- **Que la alerta se base solo en la edad del snapshot más antiguo.** Tras la primera purga
  esa edad ya es de meses por diseño (política de 6 meses) y no distingue «purgado ayer» de
  «nunca purgado»; de ahí el testigo explícito.

## Consecuencias

- Una restauración reaplica automáticamente los olvidos hasta la última hora previa a la
  pérdida del servidor; el hueco que queda es de como mucho una hora de backup y se cubre con
  el aviso del ADR-019.
- `backup.sh` arranca un contenedor efímero cada hora (unos segundos) y depende de que
  `web-panel` pueda ejecutarse; un fallo se ve como backup en rojo.
- La purga sigue siendo manual, pero ya no puede olvidarse sin que salte una alerta.
- Los repositorios anteriores a este ADR no tienen testigo: la alerta saltará una vez, hasta
  la primera purga.

## Cuándo revisarla

- Si el libro crece hasta que su snapshot horario deje de ser despreciable.
- Si se automatiza la purga con una credencial de borrado acotada (por ejemplo, una
  función en el proveedor de almacenamiento) o se pasa a archivado continuo del WAL (PITR):
  el libro y su testigo tendrían que repensarse.
