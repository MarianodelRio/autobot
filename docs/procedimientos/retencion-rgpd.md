# Retención y derechos de datos

Cómo se limpian los datos con el tiempo y cómo atender una petición de exportación u
olvido de un contacto, o la baja total de un negocio. Léelo cuando un cliente o un
contacto ejerza sus derechos, al dar de baja un negocio o antes de activar la limpieza
automática.

!!! warning "Aprobación humana explícita"
    Actuar sobre datos de producción (exportar, olvidar, purgar, activar la limpieza)
    requiere aprobación humana explícita y lo ejecuta una persona (`CLAUDE.md`). Ningún
    agente lo hace. `contact_forget` y `tenant_purge` son irreversibles.

## Objetivo, cuándo y requisitos

- **Objetivo:** cumplir los plazos de retención y atender derechos de acceso y supresión
  con auditoría, sin dejar datos personales de más.
- **Cuándo:** petición de un contacto o de un negocio; baja de un cliente (máximo 30 días
  desde la baja efectiva hasta el borrado); decisión de activar la limpieza nocturna.
- **Requisitos:** aprobación humana; SSH como `deploy` (clave de operación) o el panel por
  túnel (`make panel-tunnel`); un terminal privado.

## Cómo se ejecutan los comandos en producción

Los comandos de `manage.py` de esta página usan la conexión `owner` (`fp_owner`, con
`BYPASSRLS`), que solo tiene el contenedor `web`. Se ejecutan con `manage.sh`, que lanza
un contenedor `web` efímero con la imagen desplegada:

```bash
# desde el portátil (TTY=1 si el comando pide escribir el slug)
make prod-manage TTY=1 CMD="contact_forget <slug> <external_id> --channel main"
# o en la VPS, como deploy, en /srv/autobot
deploy/scripts/manage.sh contact_forget <slug> <external_id> --channel main
```

!!! note "Exportaciones: usa el panel"
    `contact_export` y `tenant_data_export` exigen `--output <fichero>`, y el contenedor
    efímero de producción es de solo lectura y se destruye al terminar: el fichero se
    perdería. En producción exporta desde el panel (descarga en tu navegador; ver más abajo);
    los comandos de exportación quedan para local.

## Limpieza automática

La limpieza nocturna se programa a las 03:00 UTC. En **producción está activada por
defecto** (`compose.prod.yaml` pasa `RETENTION_CLEANUP_ENABLED=true`; la persona lo aprobó el
2026-11-23 y `check_prod_config.py` lo exige en el compose renderizado); en local vale
`false`. Para pararla en un servidor, `RETENTION_CLEANUP_ENABLED=false` en su `.env` y
reiniciar `worker-periodic` (ejecuta la cola `periodic`): el permiso se comprueba al ejecutar
el trabajo, incluidos los trabajos ya encolados. Los plazos aplicados son exactamente los de
[Registro de actividades](../cumplimiento/registro-de-actividades.md) (`runtime/retention.py`,
revisado el 2026-11-23): `inbound_event` vaciado a los 30 días y borrado a los 90;
`outbound_message` con `payload` vaciado a los 30 días y fila a los 12 meses; `notification`,
`metric_event` y contactos a los 12 meses de inactividad; negocios de demo, 30 días;
`demo_event` y `owner_event`, 7 días; `demo_session`, 30; `audit_event` y `ops_alert`, 1 año.
Las excepciones: los eventos de entrada de un negocio de demo siguen los 90 días generales.

La limpieza usa lotes de hasta 1.000 filas padre y una transacción corta por lote y
negocio bajo RLS. Los borrados en cascada de un contacto pueden afectar a más filas
hijas. Aplica los plazos de retención también a negocios pausados y dados de
baja que sigan en el registro. Los doce meses se calculan por calendario; para contactos
sin actividad registrada se usa la fecha de creación. `test_session.selected_at`
registra la selección o el último mensaje remitido al negocio. Los estados se vacían
cuando superan el tiempo de conversación del pack o carecen de fecha de entrada.

Un contacto que ha pedido la baja (`opt_out`) **no se purga** al caducar: se conserva
como supresión mínima (el identificador o teléfono y la marca `opt_out`, con el nombre
vaciado). Así una cita manual posterior para el mismo teléfono no crea un contacto
nuevo al que enviar recordatorios (`_contact_by_phone` respeta el `opt_out`). Solo
`contact_forget` (o «Olvidar contacto» en el panel) lo borra del todo, y entonces se
pierde también esa supresión: el operador debe decirlo a quien lo pide.

Las tablas de la cola (`procrastinate_jobs`/`procrastinate_events`) solo guardan ids y
nombres de tarea, nunca datos personales. Un periódico propio (`jobs_cleanup`, 03:30
UTC) borra los trabajos terminados de más de 30 días y **no** depende de
`RETENTION_CLEANUP_ENABLED`, que solo gobierna los datos de clientes. Borra por lotes
(2000 trabajos por sentencia, como mucho 500 lotes por pasada) para no superar el
`statement_timeout` de `fp_app` y avanzar siempre, aunque haya mucha acumulación.

La purga nocturna aísla a cada negocio: si falla en uno (se registra con `log.exception`,
solo con su id), sigue con los demás y con las tablas de plataforma, y al final el trabajo
`retention_cleanup` termina con `RetentionError` (queda `failed` en la cola, con los ids de
los negocios afectados). Así un negocio con problemas no deja sin purgar a los siguientes,
y el fallo es visible en Incidencias → Trabajos fallidos; la purga de esa noche se reintenta
al día siguiente.

## Exportar, olvidar y purgar

Los comandos son síncronos, usan el alias `owner` y no encolan identificadores
personales. Sustituye los argumentos por el negocio y el contacto correspondientes:

```sh
manage.py contact_export SLUG EXTERNAL_ID --channel main --output /ruta/privada/contacto.json
manage.py contact_forget SLUG EXTERNAL_ID --channel main
manage.py tenant_data_export SLUG --output /ruta/privada/negocio.json
manage.py tenant_purge SLUG
```

(`manage.py` se invoca con `manage.sh` o `make prod-manage` como arriba; en local,
`cd apps/backend && uv run python manage.py ...`.)

Cada exportación y cada borrado deja un evento de auditoría (`actor` `command:<nombre>`, solo
ids internos, nunca el identificador del contacto), igual que sus equivalentes del panel.

`--channel` puede omitirse si el identificador corresponde a un único contacto; si
coincide entre `main` y una puerta de demo (`demo_tg`/`demo_wa`), el comando exige
elegir. Las exportaciones crean un archivo JSON nuevo con permisos 0600; rechazan
archivos existentes y enlaces simbólicos. El operador debe custodiar, entregar y
retirar ese archivo según el procedimiento del negocio. El contenido no se imprime en
el terminal ni en logs.

El panel ofrece el mismo export/olvido, sin necesidad de terminal: «Exportar
datos» y «Olvidar contacto» en la conversación del contacto (pestaña «Contactos») y
«Exportar datos del negocio» en el menú «⋯» de la ficha. El JSON se descarga en el
navegador del operador en vez de escribirse en el servidor; las mismas reglas de
asociación (demo, remitente, eventos del selector) y la misma auditoría
(`contact.export`, `contact.forget`, `tenant.export`, con solo el id, nunca el
contenido) aplican en los dos casos.

El borrado de contacto incluye su conversación, mensajes y eventos identificados por
remitente, relación con el mensaje saliente o referencia del proveedor. Los originales
del bot de demo se exportan/borran solo cuando su `provider_event_id` está vinculado a
un evento de la puerta (`demo_tg`/`demo_wa`) del negocio (`provider_event_id` o
`select:provider_event_id`), junto con la sesión (`DemoSession`) de esa puerta y
persona. Los eventos del selector sin negocio atribuido son datos de plataforma y
caducan a los siete días (treinta para las sesiones); no se borran por compartir
remitente con eventos de otro negocio. `tenant_purge` aplica la misma regla de
asociación y exige escribir literalmente el slug, sin espacios adicionales. Solo
admite negocios en `offboarded`. Borra todo lo que el sistema guarda del negocio:
contactos, conversaciones, mensajes, avisos, métricas, sesiones y eventos de demo,
el enlace del dueño, secretos cifrados, versiones de configuración y datasets, sus
alertas y su auditoría, y su propia fila `tenant`; el slug queda libre. Lo único
que permanece es una entrada de auditoría `tenant.purge` con `tenant_id` nulo
(prueba de que el borrado se hizo, sin datos del negocio), los logs técnicos
(caducan a los 31 días) y las copias de seguridad (retención de restic; ver el libro de supresiones más abajo). Conserva
los datos de otros negocios. Todo el borrado y su auditoría ocurren en la misma
transacción; si el canal es Telegram, el webhook se retira antes, fuera de esa
transacción. El panel ofrece el mismo borrado desde la ficha del cliente (menú
«⋯» → «Eliminar cliente»), con confirmación de slug.

### Qué cubre y qué no cubre el olvido

`contact_forget` borra, en una transacción: el contacto, su conversación, sus mensajes
salientes, **sus avisos al dueño** (`notification`, que llevan su nombre en el texto), los
eventos entrantes en los que aparece como remitente, y, en las puertas de demo, su sesión
y sus **accesos por invitación** (`demo_access_grant`, por identificador y teléfono) y los
eventos de demo vinculados. El remitente se busca en todo tipo de actualización de
Telegram (`message`, `edited_message`, `callback_query`, `channel_post`, `my_chat_member`,
`chat_member`, `inline_query`, `pre_checkout_query`, `message_reaction`, etc.) y de
WhatsApp (`messages[].from`, `contacts[].wa_id`, `statuses[].recipient_id`). El contador
`uses` de la invitación no guarda identidad y no se toca; olvidar un contacto `main` no
toca sus accesos de demo (es otra identidad en otra puerta: olvida también el contacto de
demo). `tenant_purge` no puede borrar accesos de demo porque no pertenecen a un negocio.

**No lo cubre:**

- **Google Calendar:** las citas son del calendario del negocio; el olvido no las borra.
  El negocio debe borrarlas o anonimizarlas allí.
- **Meta y Telegram:** su copia de los mensajes (en el móvil del contacto, en WhatsApp
  Business, en los servidores de Telegram) está fuera de la plataforma.
- **Logs técnicos** (VictoriaLogs): caducan a los 31 días y no se editan; no llevan
  datos personales por diseño.
- **Backups** (restic, hasta 6 meses): no se reescriben. Siguen conteniendo lo olvidado
  hasta que caduca el snapshot; por eso existe el libro de supresiones (abajo).
- **Datos de otros negocios** o eventos del selector sin negocio (caducan solos).

### Libro de supresiones y restauraciones

Cada `contact_forget`/`tenant_purge` (también desde el panel) escribe en la misma
transacción una fila de `privacy_suppression` (ADR-019): ids internos y HMAC de la
identidad, nunca el dato en claro. Como esa tabla vive en la base que se restaura, hay
que sacarlo del servidor: lo hace solo el backup. Copia manual opcional:

```bash
make prod-manage CMD="privacy_ledger_export" > libro-supresiones.jsonl   # acumulativo
```

Desde el ADR-025 no hace falta exportarlo a mano: `backup.sh` lo sube cada hora a restic
(etiqueta `autobot-ledger`) y `restore.sh` reaplica el último con `privacy_reapply --ledger -`
**antes de arrancar los workers** ([restaurar.md](restaurar.md)). El comando es idempotente
y no necesita aprobación adicional más allá de la de la propia restauración. La exportación
manual (`privacy_ledger_export`) queda como copia opcional adicional.

Para dar de baja un negocio, el operador registra la fecha real de baja y una
fecha límite de borrado de como máximo 30 días en el registro operativo de la baja.
Ejecuta `tenant_status <slug> offboard` (con `manage.sh`, como arriba) confirmando el slug y realiza la exportación acordada y ejecuta `tenant_purge` dentro de
ese plazo; comprueba que el negocio ya no aparece (`GET /tenants/<slug>` o la lista
del panel da 404) y que no quedan secretos ni datasets antes de retirar las copias
locales y los accesos externos. No se retira la entrada del registro antes del borrado: `worker-inbound`
recorre ese registro. `synced_at` se actualiza al publicar configuración y nunca demuestra
la fecha de baja. La gestión de calendarios pertenece al negocio y la retención de
backups corresponde a restic (`deploy/scripts/backup.sh`); estos comandos no modifican ninguno de ellos.

Fuentes útiles (AEPD, consultadas el 2026-11-09): [contratos de encargo](https://www.aepd.es/es/node/813)
y [pymes y Facilita](https://www.aepd.es/derechos-y-deberes/cumple-tus-deberes/directrices-de-aplicacion/pymes).

## Verificación

- El evento de auditoría existe (panel, Logs, pestaña Operador: `contact.export`,
  `contact.forget`, `tenant.export` o `tenant.purge`).
- Tras `tenant_purge`, el negocio no aparece en la lista del panel y no quedan secretos ni
  datasets.
- El libro de supresiones llega al repositorio de backups con el siguiente backup horario
  (snapshot `autobot-ledger`; `restic snapshots --tag autobot-ledger`).
- La limpieza nocturna está activa en producción (`RETENTION_CLEANUP_ENABLED=true`).

## Dónde está el código

`apps/backend/src/autobot/management/commands/` (`contact_export`, `contact_forget`,
`tenant_data_export`, `tenant_purge`, `tenant_status`, `privacy_ledger_export`,
`privacy_reapply`), `autobot/runtime/privacy.py`, `autobot/runtime/suppressions.py`,
`deploy/scripts/manage.sh`.
