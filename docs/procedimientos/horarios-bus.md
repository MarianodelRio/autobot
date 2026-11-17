# Actualizar horarios de `bus`

**Síntoma:** la empresa comunica cambios o el bot muestra un horario antiguo.
**Diagnóstico:** identificar línea, temporada, fecha de entrada en vigor y fuente
aprobada; consultar `docs/referencia/packs/bus.md` para el formato del dataset.

**ADR-013 (2026-11-17):** los horarios ya no se publican directamente sobre un
cliente. El camino correcto es subirlos a la biblioteca con
`make bus-subir NOMBRE=<nombre> DIR=var/datos/<nombre> COMMENT="…" [PROD=1]`
(valida, prueba sin escribir y sube con `--base-sha`) y, desde la ficha del cliente
→ pestaña Configuración → Horarios, pulsar «Aplicar» cuando haya una versión más
nueva que la que usa. El alta de un `bus` nuevo elige la entrada de la biblioteca
en el propio asistente. Los pasos 1–6 de abajo (`bus-bajar`/`bus-publicar` por
cliente) quedan pendientes de retirar (C24); mientras tanto siguen funcionando para
un cliente concreto, pero no pasan por la biblioteca ni dejan rastro en ella.

1. `make bus-bajar TENANT=<slug>` descarga el dataset vigente de la BD local a
   `var/datos/<slug>/timetable/` y a `var/datos/<slug>/.publicado/timetable/`. Con
   `PROD=1`, lo exporta del servidor por SSH mediante la imagen desplegada. Este paso
   sustituye las dos copias locales: guardar cualquier edición pendiente antes de
   volver a bajar.
2. Editar solo `var/datos/<slug>/timetable/`. No se versiona ni se copia a la imagen.
3. `make bus-formatear TENANT=<slug>` y `make bus-validar TENANT=<slug>`.
4. `make bus-revision TENANT=<slug>` genera `var/revision/<slug>/horarios.html` y `.pdf`,
   con el diff respecto a `.publicado/timetable`. `ARGS="--solo-html"` omite el PDF;
   `ARGS="--base /ruta/export-anterior"` elige otra copia de comparación.
5. Entregar el PDF a la empresa y conservar su confirmación real. Hasta entonces los
   cambios permanecen locales. No se simula esa aprobación.
6. `make bus-publicar TENANT=<slug> COMMENT="Motivo aprobado"` importa la instantánea
   validada en la BD local. Añadir `PROD=1` para publicar en el servidor. La operación
   crea una versión auditada y actualiza `.publicado` solo si la importación termina
   bien. Con el mismo hash no crea otra versión.
7. Comprobar los horarios con las consultas de prueba del negocio. La recarga del
   registro aplica el cambio en como máximo dos segundos, sin commit ni despliegue.

Si la entrada en vigor es futura, preparar y revisar las copias locales, pero esperar
hasta esa fecha para publicar: el dataset se aplica al importarlo. Los cambios de
código o de la plantilla inicial sí llevan commit, con sus tests, por separado.

**Verificación:** validador sin errores, confirmación de la empresa, versión auditada
en BD y conversación de prueba con el horario nuevo. La comprobación real con cada
empresa sigue pendiente de sus credenciales y de la persona operadora.
