# Pack `bus`

Responde consultas de horarios por origen, destino y día; ofrece contacto y
pueblos por línea. El cálculo usa únicamente el dataset versionado del tenant.
No hay avisos proactivos ni trabajos periódicos del pack. El menú enseña como
máximo ocho pueblos frecuentes de `config.start_menu_towns`; el resto se busca
por nombre o alias. Un dato sin horario se muestra como «horario no disponible»,
no como «sin servicio».

`config` del documento versionado contiene `business_name`,
`contact_phone`, `office_hours` (lista de `days` y `ranges`), `links` (`web`,
`compra_online`, `bonos`, `pdf_horarios`), `start_menu_towns` (1–8 nombres
presentes en el dataset) y `next_day_search_days` (45 por defecto). Los días
de oficina se declaran una vez, con franjas `HH:MM-HH:MM` sin solapes.

`config` rechaza claves desconocidas (un error tipográfico falla al importar, no se ignora) y
`contact_phone` admite hasta 30 caracteres.

### Comportamiento de la conversación

- **Fecha escrita** (`día/mes[/año]`, separador `/`, `-`, `.` o espacio): `10 30` no es una
  fecha. Si no se entiende o ya pasó, el mensaje lleva siempre dos botones, «📅 Ver lista de
  días» y «↩️ Menú»; las palabras `menu`, `inicio`, `hola`, `salir`, `cancelar`, `volver` y
  `atrás` vuelven al menú desde cualquier paso.
- **Año nunca en silencio**: una fecha sin año se resuelve al año actual. Si cae en otro año y
  no es evidente (p. ej. `23/08` en septiembre, o `29/02` que saltaría a 2028) se pregunta
  «¿Te refieres al 23/08/2027?» [Sí] [No]; solo se acepta sin preguntar el año siguiente
  cuando queda más cerca por delante que por detrás (`5/1` a finales de diciembre). Todo
  resultado de un año distinto del actual muestra el año en la cabecera.
- **Botones viejos**: un `loc:` de una pregunta anterior se elige si existe, y cualquier otro
  id que no es del paso se ignora y se repite el paso; solo el texto escrito se busca como
  pueblo. Un `dia:` de un día ya pasado (lista mostrada antes de medianoche) vuelve a la lista
  de días con «Esa fecha ya ha pasado».
- **Logs**: al no reconocer un texto solo se registra el paso y su longitud
  (`[NO_RECONOCIDO] paso=origen longitud=12`); nunca el texto.
- `alta`/`baja` siguen siendo comandos globales en todos los pasos (un pueblo no se llama así;
  el opt-out debe poder pedirse siempre).

### Limitaciones conocidas

- **Viajes que cruzan la medianoche** no se pueden representar: en las tablas las horas nunca
  retroceden y cada viaje pertenece al día de su salida. Un servicio nocturno hay que partirlo
  en dos viajes (hasta las 23:59 y desde las 00:00) o dejarlo fuera del dataset.
- **Resultados muy largos**: si el resultado supera los 4.096 caracteres se recorta por la
  última salida completa, se añade «…y N salidas más. Para verlas todas, llama al …» y solo se
  explican las notas (⚠️) de las salidas que se muestran.

El dataset está versionado en la BD, en una biblioteca independiente de cualquier
cliente (ADR-013); el cliente se queda con una copia de la entrada elegida.
`manage.py dataset_library pull bus timetable <nombre> <dir>` saca una entrada a un
directorio con esta estructura:

| Archivo | Campos y formato |
|---|---|
| `paradas.yaml` | `localidades: {id: {nombre, alias?}}`; `paradas: {COD: {nombre, localidad}}`, con código de tres mayúsculas; `no_vendibles` son pares de ids sin billete en ambos sentidos; `pendientes` registra códigos `Pnn`. Una localidad pendiente lleva `pendiente`, `ver`, `minutos` y, opcionalmente, `aviso`. |
| `observaciones.yaml` | Mapa `id: {letra, tipo, ambitos, texto}`. `tipo` es `condicion` o `aviso`; `ambitos` usa `parada`, `viaje` o `linea`. Las condiciones que el motor sabe aplicar son `a_demanda`, `solo_viernes_lectivo` y `solo_si_viajeros`; cualquier otro id con `tipo: condicion` es un error de validación (un dataset antiguo con un id distinto se corrige renombrándolo a uno de estos). Una condición nueva necesita lógica explícita en el motor. |
| `calendario.yaml` | `vigencia: DD/MM/AAAA - DD/MM/AAAA`; `festivos` es fecha → nombre y `festivos_locales` es localidad → (fecha → nombre); `curso` declara `inicio_clases`, `fin_clases`, `vacaciones` (`DD/MM/AAAA - DD/MM/AAAA`) y `no_lectivos`; `sin_servicio_todas_las_lineas` usa `DD/MM`; `pendientes` es opcional. |
| `lineas/<id>.yaml` | Una línea por fichero con id `a-z0-9-`: `nombre`, `nombre_corto?` (≤24), `telefono_demanda?`, `avisos?`, `no_circula?`, `temporadas`, `dias`, `horarios` y `pendientes?`. |

El id de una localidad (`loc:<id>`) y el de una línea (`linea:<id>:<página>`) se
muestran como id de botón o de fila: la validación los rechaza si, con su
prefijo, superarían los 64 bytes del límite común de canal.

Una línea declara `temporadas` como `invierno: 01/09 - 22/06` o `anual: todo
el año`; entre todas cubren el año sin huecos ni solapes. En `dias`, cada
temporada asigna cada clase (lunes a domingo y festivos) a `horario`,
`sin_servicio` o `sin_datos`. Puede agrupar clases con `lunes-viernes`,
`lunes-jueves`, `martes-viernes`, `sabados-domingos`, `domingos-festivos` y
`sabados-domingos-festivos`, sin declarar una clase dos veces. `sin_datos`
señala una laguna conocida y no equivale a ausencia de servicio.

`horarios` es una lista de `{temporada, dias, tabla}`. Cada tabla de texto
empieza con al menos dos códigos de parada, en orden de recorrido, y cada fila
posterior representa un viaje con un valor por parada. `-` indica que no para;
`HH:MM` indica paso; `HH:MM>HH:MM` indica llegada y salida en una parada
intermedia; letras anexas (`09:55D`) remiten a `observaciones.yaml`. Tras una
barra vertical se pueden declarar ids de observaciones de ámbito `viaje`, códigos
pendientes `Pnn` y `bus:<id>` para el mismo vehículo compartido por líneas.
Las horas nunca retroceden y cada viaje tiene al menos dos pasos. `no_circula`
es una lista de nombres de mes (por ejemplo, `[agosto]`). `avisos` en la línea
aplican a todos sus viajes; `telefono_demanda` permite
explicar paradas a demanda. Los nombres con coma dentro de mapas YAML en línea
deben ir entre comillas.

Ejemplo mínimo de tabla:

```yaml
horarios:
  - temporada: anual
    dias: lunes-viernes
    tabla: |
      ADA    VFC    COR
      06:40  06:55  07:35
      08:50  09:00  09:40
```

Para subir una versión nueva, primero `make bus-bajar NOMBRE=<nombre>` descarga la
vigente a `var/datos/<nombre>/timetable/` y guarda la base en `.publicado/timetable`.
Tras editar, ejecuta `make bus-formatear`, `make bus-validar` y `make bus-revision`,
siempre con `NOMBRE=<nombre>`. La revisión HTML/PDF compara con esa copia de la
versión anterior; `ARGS="--base <dir>"` permite elegir otra base.

La empresa (o quien aprueba la línea) confirma el PDF antes de `make bus-subir
NOMBRE=<nombre> COMMENT="Motivo"`, que sube la versión nueva **a la biblioteca**, no
a ningún cliente. Sin `PROD`, se usa la BD local; con `PROD=1`, bajar y subir usan
SSH al servidor. Cada cliente que use esa entrada aplica la versión nueva desde su
propia ficha. El alta crea una versión de dataset y su auditoría; no hay tags de git
ni despliegue.
[`docs/procedimientos/horarios-bus.md`](../../procedimientos/horarios-bus.md) describe el flujo completo y las comprobaciones.

### Dónde está el código

- `apps/backend/src/packs/bus/formato/`: el único parser y validador del dataset (`validar()`), un módulo por
  fichero (`localidades`, `calendario`, `observaciones`, `linea` y `tabla`, `buses`) más `temporadas` y
  `normalizar`, que usa también el motor de consulta. El modelo (`Modelo`, `Linea`, `Viaje`…) está en `modelo.py`.
- `loader.py` calcula al cargar los índices (`localidad_viajes`, `lineas_pueblos`, `lineas_con_pueblos`) y
  `query.py` guarda por par origen-destino lo que no depende de la fecha, para que listar siete días o buscar
  el siguiente día con salidas no repita el trabajo.
- `apps/backend/src/tools/bus/`: las herramientas de terminal (`make bus-*`), incluida la comparación de versiones
  (`diff.py`) que usa `make bus-revision`.

### Resumen mensual al dueño

El pack declara un único gancho `summary` para el resumen periódico al dueño
(ADR-007), que lee esta métrica de plataforma
(`RecordMetric`, aún emitida por `conversation.py`):

| Métrica | Unidad | Se emite cuando |
|---|---|---|
| Consultas de horario | recuento | la conversación encuentra un itinerario (`con_salidas`); un menú, un error o "sin horarios" no cuentan |

`bus` no vende nada, así que no declara ninguna métrica en euros: es el
comportamiento esperado, no una limitación. Para activar el resumen mensual del
negocio, añade en su documento exportado:

```yaml
owner:
  summary_monthly: true
```

Requiere que el dueño ya esté vinculado al bot de avisos (`manage.py owner_invite
<slug>`: ver `docs/procedimientos/alta-baja-negocio.md`). Llega por el mismo bot el día 1 de
cada mes, con los datos del mes anterior ya cerrado, y también se puede consultar en
cualquier momento escribiéndole al bot ("Cómo va el mes").

La plantilla inicial del demo está en `apps/backend/src/packs/bus/template/document.yaml`; su dataset está en `apps/backend/src/packs/bus/template/datasets/timetable/`.
Todos sus datos son ficticios, por eso `template_blank=()`.
