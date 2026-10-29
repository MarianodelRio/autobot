# Pack `bus`

Responde consultas de horarios por origen, destino y día; ofrece contacto y
pueblos por línea. El cálculo usa únicamente el dataset versionado del tenant.
No hay avisos proactivos ni trabajos periódicos del pack. El menú enseña como
máximo ocho pueblos frecuentes de `config.start_menu_towns`; el resto se busca
por nombre o alias. Un dato sin horario se muestra como «horario no disponible»,
no como «sin servicio».

`config` en `tenants/<slug>/tenant.yaml` contiene `business_name`,
`contact_phone`, `office_hours` (lista de `days` y `ranges`), `links` (`web`,
`compra_online`, `bonos`, `pdf_horarios`), `start_menu_towns` (1–8 nombres
presentes en el dataset) y `next_day_search_days` (45 por defecto). Los días
de oficina se declaran una vez, con franjas `HH:MM-HH:MM` sin solapes.

El dataset vive en `tenants/<slug>/datasets/timetable/`:

| Archivo | Campos y formato |
|---|---|
| `paradas.yaml` | `localidades: {id: {nombre, alias?}}`; `paradas: {COD: {nombre, localidad}}`, con código de tres mayúsculas; `no_vendibles` son pares de ids sin billete en ambos sentidos; `pendientes` registra códigos `Pnn`. Una localidad pendiente lleva `pendiente`, `ver`, `minutos` y, opcionalmente, `aviso`. |
| `observaciones.yaml` | Mapa `id: {letra, tipo, ambitos, texto}`. `tipo` es `condicion` o `aviso`; `ambitos` usa `parada`, `viaje` o `linea`. Una condición nueva necesita lógica explícita en el motor. |
| `calendario.yaml` | `vigencia: DD/MM/AAAA - DD/MM/AAAA`; `festivos` es fecha → nombre y `festivos_locales` es localidad → (fecha → nombre); `curso` declara `inicio_clases`, `fin_clases`, `vacaciones` (`DD/MM/AAAA - DD/MM/AAAA`) y `no_lectivos`; `sin_servicio_todas_las_lineas` usa `DD/MM`; `pendientes` es opcional. |
| `lineas/<id>.yaml` | Una línea por fichero con id `a-z0-9-`: `nombre`, `nombre_corto?` (≤24), `telefono_demanda?`, `avisos?`, `no_circula?`, `temporadas`, `dias`, `horarios` y `pendientes?`. |

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

Para publicar: edita el dataset, ejecuta `make bus-formatear TENANT=<slug>` y
`make bus-validar TENANT=<slug>`, luego `make bus-revision TENANT=<slug>`.
La revisión genera HTML/PDF con el diff respecto al último tag `datos/<slug>/*`.
La empresa confirma el PDF antes del commit y despliegue. Después ejecuta
`make bus-publicar TENANT=<slug>`; la herramienta crea el tag local, que la
persona operadora publica. Los cambios futuros se publican en su fecha de
vigencia. El runbook 10 contiene las comprobaciones de operación.

### Resumen mensual al dueño

El pack declara un único gancho `summary` para el resumen periódico al dueño
(ADR-007), que lee esta métrica de plataforma
(`RecordMetric`, aún emitida por `conversation.py`):

| Métrica | Unidad | Se emite cuando |
|---|---|---|
| Consultas de horario | recuento | la conversación encuentra un itinerario (`con_salidas`); un menú, un error o "sin horarios" no cuentan |

`bus` no vende nada, así que no declara ninguna métrica en euros: es el
comportamiento esperado, no una limitación. Para activar el resumen mensual del
negocio, añade en su `tenant.yaml`:

```yaml
owner:
  summary_monthly: true
```

Requiere que el dueño ya esté vinculado al bot de avisos (`manage.py owner_invite
<slug>`: ver `docs/runbooks/alta-baja-negocio.md`). Llega por el mismo bot el día 1 de
cada mes, con los datos del mes anterior ya cerrado, y también se puede consultar en
cualquier momento escribiéndole al bot ("Cómo va el mes").
