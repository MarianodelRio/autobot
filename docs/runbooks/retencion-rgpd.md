# Retención y derechos de datos

La limpieza nocturna se programa a las 03:00 UTC y permanece inerte con
`RETENTION_CLEANUP_ENABLED=false` (valor predeterminado). Solo el operador, tras la
aprobación humana explícita de T-6.3, puede establecer `true` y reiniciar el worker.
El permiso se comprueba al ejecutar el trabajo, incluidos los trabajos ya encolados.
No se ha autorizado ni activado esa limpieza en producción.

La limpieza usa lotes de hasta 1.000 filas padre y una transacción corta por lote y
negocio bajo RLS. Los borrados en cascada de un contacto pueden afectar a más filas
hijas. Aplica los plazos de §12.3 del diseño también a negocios pausados y dados de
baja que sigan en el registro. Los doce meses se calculan por calendario; para contactos
sin actividad registrada se usa la fecha de creación. `test_session.selected_at`
registra la selección o el último mensaje remitido al negocio. Los estados se vacían
cuando superan el tiempo de conversación del pack o carecen de fecha de entrada.

Los comandos siguientes son síncronos, requieren el alias de operación `owner` y no
encolan identificadores personales. Deben ejecutarse en un terminal privado por un
operador autorizado. Sustituya los argumentos por el negocio y contacto correspondientes:

```sh
uv run python manage.py export_contact SLUG EXTERNAL_ID --channel main --output /ruta/privada/contacto.json
uv run python manage.py forget_contact SLUG EXTERNAL_ID --channel main
uv run python manage.py export_tenant SLUG --output /ruta/privada/negocio.json
uv run python manage.py purge_tenant SLUG
```

`--channel` puede omitirse si el identificador corresponde a un único contacto; si
coincide entre `main` y `test`, el comando exige elegir. Las exportaciones crean un
archivo JSON nuevo con permisos 0600; rechazan archivos existentes y enlaces simbólicos.
El operador debe custodiar, entregar y retirar ese archivo según el procedimiento del
negocio. El contenido no se imprime en el terminal ni en logs.

El borrado de contacto incluye su conversación, mensajes y eventos identificados por
remitente, relación con el mensaje saliente o referencia del proveedor. Los originales
del bot de pruebas se exportan/borran solo cuando su `update_id` está vinculado a un
evento `test` del negocio (`update_id` o `select:update_id`). Los eventos del selector
sin negocio atribuido son datos de plataforma y caducan a los siete días; no se borran
por compartir remitente con eventos de otro negocio. `purge_tenant` aplica la misma
regla de asociación y exige escribir literalmente el slug, sin espacios adicionales.
Conserva el reflejo `tenant`, YAML, secretos, calendarios y datos de otros negocios.

Para dar de baja un negocio (§16.2), el operador registra la fecha real de baja y una
fecha límite de borrado de como máximo 30 días en el registro operativo de la baja.
Marca `offboarded`, realiza la exportación acordada y ejecuta `purge_tenant` dentro de
ese plazo; comprueba el resultado antes de retirar secretos, acceso al canal y carpeta
`tenants/<slug>/`. No se retira la entrada del registro antes del borrado: el worker
recorre ese registro. `synced_at` se actualiza en cada sincronización y nunca demuestra
la fecha de baja. La gestión de calendarios pertenece al negocio y la retención de
backups corresponde a F7/restic; estos comandos no modifican ninguno de ellos.
