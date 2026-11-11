# Retención y derechos de datos

La limpieza nocturna se programa a las 03:00 UTC y permanece inerte con
`RETENTION_CLEANUP_ENABLED=false` (valor predeterminado). Solo el operador, tras la
aprobación humana explícita, puede establecer `true` y reiniciar `worker-inbound` (ejecuta la cola `periodic`).
El permiso se comprueba al ejecutar el trabajo, incluidos los trabajos ya encolados.
No se ha autorizado ni activado esa limpieza en producción.

La limpieza usa lotes de hasta 1.000 filas padre y una transacción corta por lote y
negocio bajo RLS. Los borrados en cascada de un contacto pueden afectar a más filas
hijas. Aplica los plazos de retención también a negocios pausados y dados de
baja que sigan en el registro. Los doce meses se calculan por calendario; para contactos
sin actividad registrada se usa la fecha de creación. `test_session.selected_at`
registra la selección o el último mensaje remitido al negocio. Los estados se vacían
cuando superan el tiempo de conversación del pack o carecen de fecha de entrada.

Los comandos siguientes son síncronos, requieren el alias de operación `owner` y no
encolan identificadores personales. Deben ejecutarse en un terminal privado por un
operador autorizado. Sustituya los argumentos por el negocio y contacto correspondientes:

```sh
uv run python manage.py contact_export SLUG EXTERNAL_ID --channel main --output /ruta/privada/contacto.json
uv run python manage.py contact_forget SLUG EXTERNAL_ID --channel main
uv run python manage.py tenant_data_export SLUG --output /ruta/privada/negocio.json
uv run python manage.py tenant_purge SLUG
```

`--channel` puede omitirse si el identificador corresponde a un único contacto; si
coincide entre `main` y una puerta de demo (`demo_tg`/`demo_wa`), el comando exige
elegir. Las exportaciones crean un archivo JSON nuevo con permisos 0600; rechazan
archivos existentes y enlaces simbólicos. El operador debe custodiar, entregar y
retirar ese archivo según el procedimiento del negocio. El contenido no se imprime en
el terminal ni en logs.

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
(caducan a los 31 días) y las copias de seguridad (retención de restic). Conserva
los datos de otros negocios. Todo el borrado y su auditoría ocurren en la misma
transacción; si el canal es Telegram, el webhook se retira antes, fuera de esa
transacción. El panel ofrece el mismo borrado desde la ficha del cliente (menú
«⋯» → «Eliminar cliente»), con confirmación de slug.

Para dar de baja un negocio, el operador registra la fecha real de baja y una
fecha límite de borrado de como máximo 30 días en el registro operativo de la baja.
Ejecuta `tenant_status <slug> offboard` confirmando el slug y realiza la exportación acordada y ejecuta `tenant_purge` dentro de
ese plazo; comprueba que el negocio ya no aparece (`GET /tenants/<slug>` o la lista
del panel da 404) y que no quedan secretos ni datasets antes de retirar las copias
locales y los accesos externos. No se retira la entrada del registro antes del borrado: `worker-inbound`
recorre ese registro. `synced_at` se actualiza al publicar configuración y nunca demuestra
la fecha de baja. La gestión de calendarios pertenece al negocio y la retención de
backups corresponde a restic (`deploy/scripts/backup.sh`); estos comandos no modifican ninguno de ellos.
