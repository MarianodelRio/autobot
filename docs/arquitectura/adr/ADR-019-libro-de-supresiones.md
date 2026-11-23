# ADR-019 — Libro de supresiones para no resucitar datos olvidados

**Estado:** aceptada

**Actualización (ADR-025):** la exportación del libro fuera del servidor ya no es un paso manual: `backup.sh` la sube cada hora como snapshot propio y `restore.sh` reaplica el último. La exportación manual queda como copia opcional.

## Contexto

`contact_forget` y `tenant_purge` borran datos de la base de datos viva, pero los backups
(restic, hasta 6 meses) los conservan. Al restaurar un snapshot anterior a un olvido, el
dato olvidado reaparece, y con él el incumplimiento del derecho de supresión. Hace falta
poder volver a aplicar los olvidos posteriores al snapshot sin guardar datos personales
del olvidado.

## Decisión

- Tabla de plataforma `privacy_suppression` (modelo `PrivacySuppression`, sin RLS, como
  `audit_event`): `tenant_id`, `contact_id` (uuid interno), `channel`, `kind`
  (`forget` o `purge`), fecha y `identity_hashes`. Estos son HMAC-SHA256 de
  `(channel, identificador)` con una clave derivada de `SECRET_KEY` (mismo esquema que
  `runtime/locks.py`, propósito propio). Ningún dato personal en claro.
- Se escribe en la misma transacción que el olvido o la purga
  (`privacy.forget`, `privacy.purge`): si el borrado falla, no queda apunte, y viceversa.
  Al purgar un negocio se borran sus filas `forget` (las subsume la fila `purge`, que se
  conserva como prueba). `fp_app` no tiene acceso y
  está en `SENSITIVE_TABLES` (`autobot/db/grants.py`).
- `manage.py privacy_ledger_export` imprime el libro como JSON lines por stdout. Es un paso
  obligatorio guardarlo **fuera del servidor** tras cada olvido o purga (la tabla vive en
  la misma base que se restaura, así que el snapshot no contiene los olvidos posteriores
  a él). Funciona con `make prod-manage`, que no puede escribir ficheros (contenedor de
  solo lectura).
- `manage.py privacy_reapply [--ledger fichero]` une la tabla restaurada con el fichero y
  repite cada entrada de forma idempotente: olvido por `contact_id` (si el contacto
  existe) o, si no, por los HMAC (eventos por remitente, sesión y accesos de demo);
  purga del negocio aunque la fila restaurada no esté `offboarded`. Reinserta en la tabla
  las entradas que faltaban y deja un evento de auditoría `privacy.reapply` con solo
  contadores. Se ejecuta antes de arrancar los workers.

## Alternativas consideradas

- **Fichero append-only en `OPS_STATE_DIR`:** en producción ese directorio se monta de
  solo lectura en `web` (`/run/ops`) y el contenedor de `manage.sh` es efímero; la
  aplicación no puede escribirlo y habría que tocar la infraestructura.
- **Solo la tabla, sin exportar:** inútil tras una restauración: el volcado restaurado no
  contiene los olvidos posteriores al snapshot.
- **Guardar el identificador en claro o con sha256 simple:** reintroduce el dato personal
  que se quiere borrar; un teléfono o un id de Telegram caen por diccionario.
- **Reescribir los backups al olvidar:** restic no lo permite de forma práctica.

## Consecuencias

- La supresión sobrevive a una restauración si el operador conserva el libro exportado;
  sin él, solo se reaplican los olvidos incluidos en el snapshot elegido.
- Los HMAC dependen de `SECRET_KEY`: sin ella (ya imprescindible para restaurar, está en
  `.env`) solo funciona la baja por `contact_id`.
- Un nuevo paso manual en el procedimiento de olvido y en el de restauración.

## Cuándo revisarla

Si el backup pasa a poder excluir o reescribir filas, si `OPS_STATE_DIR` pasa a ser
escribible por la aplicación (permitiría automatizar la copia), o si se rota `SECRET_KEY`
de forma rutinaria.
