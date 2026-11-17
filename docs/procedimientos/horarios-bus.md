# Actualizar horarios de `bus`

**Síntoma:** la empresa comunica cambios o el bot muestra un horario antiguo.
**Diagnóstico:** identificar línea, temporada, fecha de entrada en vigor y fuente
aprobada; consultar `docs/referencia/packs/bus.md` para el formato del dataset.

**ADR-013:** los horarios se suben por terminal a una biblioteca de conjuntos de
datos, independiente de cualquier cliente. Cada cliente usa una entrada con nombre
propio (p. ej. `linea-cordoba`); varios clientes pueden usar la misma. El alta de un
`bus` nuevo elige la entrada en el propio asistente; para un cliente ya existente, se
elige la nueva versión y se aplica desde su ficha.

1. `make bus-bajar NOMBRE=<nombre>` descarga la versión vigente de esa entrada a
   `var/datos/<nombre>/timetable/` (y a `.publicado/timetable/`, la base que usa
   `bus-revision` para el diff). Con `PROD=1`, la baja del servidor por SSH. Si la
   entrada no existe todavía (un conjunto nuevo), partir de una copia conocida y
   saltar este paso.
2. Editar solo `var/datos/<nombre>/timetable/`. No se versiona ni se copia a la
   imagen.
3. `make bus-formatear NOMBRE=<nombre>` y `make bus-validar NOMBRE=<nombre>`.
4. `make bus-revision NOMBRE=<nombre>` genera `var/revision/<nombre>/horarios.html` y
   `.pdf`, con el diff respecto a `.publicado/timetable`. `ARGS="--solo-html"` omite
   el PDF; `ARGS="--base /ruta/export-anterior"` elige otra copia de comparación.
5. Entregar el PDF a la empresa (o a quien aprueba la línea) y conservar su
   confirmación real. Hasta entonces los cambios permanecen locales. No se simula esa
   aprobación.
6. `make bus-subir NOMBRE=<nombre> COMMENT="Motivo aprobado"` valida, prueba la
   subida sin escribir y sube una versión nueva a la biblioteca, rechazando si otra
   persona subió una entre medias (`--base-sha`, resuelto automáticamente). Añadir
   `PROD=1` para subir al servidor. Con el mismo contenido no crea versión nueva.
   **Esto no cambia los horarios de ningún cliente.**
7. Por cada cliente que use esa entrada: en su ficha → Configuración → Horarios,
   pulsar «Aplicar» cuando el panel avise de la versión nueva. Crea una versión
   auditada del dataset de ese cliente y la recarga del registro la aplica en como
   máximo dos segundos, sin commit ni despliegue.
8. Comprobar los horarios con las consultas de prueba del negocio.

Si la entrada en vigor es futura, preparar y revisar las copias locales, pero esperar
hasta esa fecha para subir y aplicar: el dataset se aplica solo al aplicarlo desde la
ficha. Los cambios de código o de la plantilla inicial sí llevan commit, con sus
tests, por separado.

**Verificación:** validador sin errores, confirmación de la empresa, versión
auditada en la biblioteca y en cada cliente que la aplicó, y conversación de prueba
con el horario nuevo. La comprobación real con cada empresa sigue pendiente de sus
credenciales y de la persona operadora.
