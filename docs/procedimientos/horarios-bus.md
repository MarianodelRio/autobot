# Actualizar horarios de `bus`

Cómo cambiar los horarios de un cliente `bus`: se editan en tu portátil, se validan, se
suben a una biblioteca independiente de cualquier cliente (ADR-013) y cada cliente aplica la
versión nueva desde el panel. Léelo cuando la empresa comunique cambios o el bot muestre un
horario antiguo. El formato del dataset está en [../referencia/packs/bus.md](../referencia/packs/bus.md).

!!! warning "Aprobaciones"
    Subir a producción (`PROD=1`) y aplicar a un cliente es actuar sobre datos de
    producción: requiere aprobación humana explícita. Además, la confirmación de la empresa
    es real; no se simula.

## Objetivo, cuándo y requisitos

- **Objetivo:** que el bot de un cliente use el horario vigente y aprobado.
- **Cuándo:** cambio de línea, temporada o fecha de entrada en vigor; o un horario antiguo
  en el bot. Identifica antes línea, temporada, fecha y fuente aprobada.
- **Requisitos:** en el portátil, `uv` y la clave SSH de operación (alias `autobot`, o
  `HOST=<alias>`); el panel por túnel (`make panel-tunnel`).

Cada cliente usa una entrada con nombre propio de la biblioteca (por ejemplo
`linea-cordoba`); varios clientes pueden usar la misma. Subir una versión **no cambia los
horarios de ningún cliente**; cada uno la aplica por separado. Los datasets viven en
`var/datos/<nombre>/`, ignorado por git.

## Pasos

Todos los `make` se ejecutan en el portátil, en la raíz del repo. Con `PROD=1` operan sobre
el servidor por SSH (como `deploy`); sin él, sobre tu BD local.

1. **Bajar la versión vigente:** `make bus-bajar NOMBRE=<nombre> [PROD=1] [VERSION=<n>]`
   descarga la entrada a `var/datos/<nombre>/timetable/` (y a `.publicado/timetable/`, la
   base del diff). Si la entrada no existe todavía, parte de una copia conocida y salta este
   paso.
2. **Editar** solo `var/datos/<nombre>/timetable/`. No se versiona ni entra en la imagen.
3. `make bus-formatear NOMBRE=<nombre>` y `make bus-validar NOMBRE=<nombre>`.
4. `make bus-revision NOMBRE=<nombre> [ARGS="--solo-html"]` genera
   `var/revision/<nombre>/horarios.html` y `.pdf` con el diff respecto a `.publicado`;
   `--solo-html` omite el PDF y `--base <ruta>` elige otra copia de comparación.
5. **Aprobación:** entrega el PDF a la empresa (o a quien aprueba la línea) y conserva su
   confirmación. Hasta entonces los cambios quedan en local.
6. **Subir:** `make bus-subir NOMBRE=<nombre> DIR=<dir> COMMENT="Motivo aprobado" [PROD=1]`
   valida, prueba la subida sin escribir y sube una versión nueva a la biblioteca; rechaza
   si otra persona subió una entre medias (`--base-sha`, resuelto solo). Con el mismo
   contenido no crea versión.
7. **Aplicar a cada cliente** que use la entrada: panel, ficha, Configuración, Horarios,
   «Aplicar» cuando avise de la versión nueva. Crea una versión auditada del dataset de ese
   cliente; los procesos la aplican en unos dos segundos (sondeo del registro, ADR-030), sin commit
   ni despliegue.
8. Comprueba el resultado con las consultas de prueba del negocio.

Si la entrada en vigor es futura, prepara y revisa las copias locales, pero espera a esa
fecha para subir y aplicar. Los cambios de código o de la plantilla inicial sí llevan
commit, con sus tests, por separado.

## Verificación

- Validador sin errores y confirmación de la empresa conservada.
- Versión nueva en la biblioteca y versión auditada en cada cliente que la aplicó (panel,
  Configuración, Horarios).
- Una conversación de prueba con el horario nuevo responde lo esperado.

## Dónde está el código

`apps/backend/src/tools/bus/` (`library`, `validar`, `formatear`, `revision`),
`apps/backend/src/autobot/management/commands/dataset_library.py`, objetivos `bus-*` del
`Makefile`.
