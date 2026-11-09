# ADR-011 — Borrado total de un cliente

**Estado:** aceptada

## Contexto

`tenant_purge` borraba los datos de cliente de un negocio dado de baja, pero
conservaba su fila `tenant` y una última versión de su documento (sin testers ni
dueño), para que un webhook tardío de su canal siguiera teniendo un negocio al
que responder. La persona aprobó el 2026-11-08 extender el panel para ofrecer un
borrado completo desde la ficha del cliente, lo que exige decidir qué pasa con
esa fila y esa versión, y qué queda como prueba del borrado.

## Decisión

- **El borrado es total.** Además de lo que `tenant_purge` ya borraba (contactos,
  conversaciones, mensajes, avisos, métricas, secretos y versiones de datasets),
  ahora también borra las sesiones y eventos de demo, el enlace del dueño, todas
  las versiones del documento (ninguna se conserva), sus alertas (`ops_alert`) y
  su auditoría (`audit_event`), los trabajos de la cola con ese `tenant_id` que no
  estén en curso, y la propia fila `tenant`. El slug queda libre para un negocio
  nuevo.
- **Solo permanece una entrada de auditoría**, `tenant.purge`, con `tenant_id`
  nulo y solo el id, el slug y quién lo borró: la prueba de que el borrado se
  hizo, sin datos del negocio. Fuera de la base de datos, los logs técnicos
  caducan solos a los 31 días y las copias de seguridad según la retención de
  restic (`deploy/scripts/backup.sh`); ninguno de los dos se toca.
- **Un webhook tardío de ese canal recibe 404**, igual que cualquier identificador
  desconocido: ya no hay fila `tenant` a la que asociarlo.
- **Las claves de caché del cliente se borran** (`health:<id>`, `runtime:<id>:<canal>`
  por cada canal y los enfriamientos de alerta por cada `kind` que tuviera), al
  confirmarse la transacción.
- **Solo un negocio dado de baja (`offboarded`) se puede borrar**, y nunca un
  demo. Desde el panel, un negocio activo debe pausarse primero; el botón queda
  deshabilitado con esa explicación. Si el canal es Telegram, el panel
  resuelve el bot y sus secretos **antes** (después ya no existen), ejecuta el
  borrado y, **solo si ha confirmado**, retira el webhook **fuera** de la transacción
  (nunca una transacción abierta durante una llamada a Telegram); si esa llamada
  falla, el borrado ya está hecho y se comunica. Dentro de la transacción se
  bloquean (`FOR UPDATE`) los trabajos `todo` y `doing` de ese cliente; como
  `procrastinate_fetch_job` usa `SKIP LOCKED`, ningún worker puede arrancar los
  pendientes mientras dura. Si alguno está en curso (`doing`), el borrado se
  rechaza sin borrar nada, sin tocar el webhook, y se puede reintentar en unos segundos.
- **El panel ofrece el mismo borrado** que `tenant_purge` (ficha del cliente, menú
  «⋯» → «Eliminar cliente», con confirmación de slug), no un camino aparte: ambos
  llaman a la misma función (`autobot.runtime.privacy.purge`).
- **Lo que queda fuera de la plataforma no se toca.** La app en Meta, el bot de
  Telegram y el calendario de Google son del negocio; el borrado no los retira ni
  los desvincula, y la interfaz lo recuerda.

## Alternativas consideradas

- **Mantener el comportamiento anterior** (fila y última versión conservadas): se
  descartó porque la persona quiere poder reutilizar un slug y no necesita que un
  webhook tardío encuentre un negocio al que asociar el evento; 404 es una
  respuesta igual de válida y más simple de razonar.
- **Anonimizar en vez de borrar** (conservar filas con los campos personales
  vacíos): se descartó porque multiplica el código de borrado por tabla sin
  aportar nada que el requisito no pida, y porque las claves de caché y la cola
  ya no tendrían a qué fila apuntar.

## Consecuencias

- `tenant_purge` y el borrado del panel comparten una sola implementación: un
  cambio en qué se borra se hace una vez.
- El test que recorre `information_schema` para encontrar toda columna
  `tenant_id` hace improbable que una tabla nueva quede fuera del borrado por
  omisión.
- Ya no existe un registro al que asociar un webhook tardío del cliente borrado;
  los paneles de monitorización externos deben esperar 404, no 200.
- Un slug borrado puede reutilizarse de inmediato para un negocio nuevo sin
  relación con el anterior.

## Cuándo revisarla

Si se necesitara demostrar ante una auditoría externa qué datos tenía un cliente
en el momento del borrado (más allá de que se borró), haría falta un export
previo obligatorio, no solo recomendado. Si se añadiera una tabla de datos de
cliente que no lleve `tenant_id` como columna propia, el barrido genérico no la
detectaría y el borrado tendría que declararla a mano.
