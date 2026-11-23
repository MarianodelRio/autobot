# Autobot

Autobot es una plataforma multi-negocio que atiende a los clientes de pequeños negocios por un canal por negocio (WhatsApp o Telegram). Cada tipo de negocio es un pack: `salon` (peluquería, reservas sobre Google Calendar) y `bus` (horarios de autobús). Hay además un bot de demo, por WhatsApp y Telegram, para enseñar los packs.

**Estado:** probada en local contra servicios reales (demo por Telegram y WhatsApp, bot de avisos, panel, Google Calendar). Nada está desplegado todavía en producción; los pasos para ponerla en marcha están en [Servidor](procedimientos/servidor.md).

## Ruta de lectura para quien llega nuevo

Unas tres horas en total. Lee en este orden; cada página enlaza a la siguiente.

| # | Página | Tiempo | Para qué sirve |
|---|---|---|---|
| 1 | [Visión general](arquitectura/vision-general.md) | 10 min | Qué piezas hay, qué procesos corren y cómo encajan. |
| 2 | [Mapa del código](arquitectura/mapa-del-codigo.md) | 10 min | Qué hay en cada carpeta y qué capas pueden importar a cuáles. |
| 3 | [Vida de un mensaje](arquitectura/vida-de-un-mensaje.md) | 15 min | El recorrido completo, del webhook a la respuesta. |
| 4 | [Efectos e idempotencia](arquitectura/efectos-e-idempotencia.md) | 15 min | Cómo se evitan envíos duplicados o perdidos. |
| 5 | [Tenants y RLS](arquitectura/tenants-y-rls.md) | 15 min | Cómo se aíslan los datos de cada negocio. |
| 6 | [Packs](arquitectura/packs.md) | 15 min | El contrato de un pack y cómo se conecta a la plataforma. |
| 7 | [Entorno local](desarrollo/entorno-local.md) | 20 min | Arrancar todo en tu máquina y probar un chat. |
| 8 | [Tests](desarrollo/tests.md) | 15 min | Cómo se prueba, qué comprueba `make check` y los escenarios de conversación. |
| 9 | [Despliegue](procedimientos/despliegue.md) | 15 min | Cómo llega un cambio a producción y cómo se vuelve atrás. |
| 10 | [Panel](arquitectura/panel.md) | 15 min | La herramienta con la que se opera la plataforma. |

Después, según lo que vayas a hacer: [Añadir un pack](desarrollo/anadir-un-pack.md), [Migraciones y RLS](desarrollo/migraciones-y-rls.md) o [Decisiones (ADR)](arquitectura/adr/README.md).

## Quiero…

| Quiero… | Página |
|---|---|
| Entender la arquitectura | [Visión general](arquitectura/vision-general.md), [Decisiones (ADR)](arquitectura/adr/README.md) |
| Ver qué hay en cada carpeta | [Mapa del código](arquitectura/mapa-del-codigo.md) |
| Arrancar en local | [Entorno local](desarrollo/entorno-local.md) |
| Enseñar la demo (Telegram o WhatsApp) | [Demo local](desarrollo/demo-local.md), [Demo](procedimientos/demo.md) |
| Trabajar en el panel | [Panel (desarrollo)](desarrollo/panel.md) |
| Correr o escribir tests | [Tests](desarrollo/tests.md) |
| Añadir un pack | [Añadir un pack](desarrollo/anadir-un-pack.md) |
| Cambiar la base de datos | [Migraciones y RLS](desarrollo/migraciones-y-rls.md) |
| Dar de alta o baja un negocio | [Alta y baja de un negocio](procedimientos/alta-baja-negocio.md) |
| Dar de alta el canal WhatsApp de un negocio | [Alta de WhatsApp en Meta](procedimientos/alta-whatsapp-meta.md) |
| Desplegar un cambio | [Despliegue](procedimientos/despliegue.md) |
| Preparar el servidor | [Servidor](procedimientos/servidor.md), [Traslado](procedimientos/traslado.md) |
| Dimensionar el servidor o planear el crecimiento | [Capacidad y crecimiento](arquitectura/capacidad-y-crecimiento.md) |
| Restaurar un backup | [Restaurar](procedimientos/restaurar.md) |
| Rotar un secreto de canal | [Rotar secretos](procedimientos/rotar-secretos.md) |
| Actualizar horarios de `bus` | [Horarios de bus](procedimientos/horarios-bus.md) |
| Atender un derecho de datos (RGPD) | [Derechos de los interesados](cumplimiento/derechos-de-los-interesados.md), [Retención y RGPD](procedimientos/retencion-rgpd.md) |
| Cumplimiento legal y protección de datos (contrato, roles, brechas) | [Cumplimiento](cumplimiento/README.md), [Checklist de lanzamiento](cumplimiento/checklist-lanzamiento.md) |
| Hacer el mantenimiento periódico | [Mantenimiento](procedimientos/mantenimiento.md) |
| Resolver algo que falla en producción | [Incidencias](incidencias/README.md) (por síntoma) |
| Buscar un comando | [Comandos](referencia/comandos.md) |
| Buscar una variable de entorno | [Variables de entorno](referencia/variables-entorno.md) |
| Configurar un pack concreto | [Pack salon](referencia/packs/salon.md), [Pack bus](referencia/packs/bus.md) |
| Entender una alerta o un estado | [Alertas](referencia/alertas.md), [Estados de negocio](referencia/estados-de-negocio.md) |
| Buscar un término | [Glosario](referencia/glosario.md) |

## Tareas habituales

| Quiero… | Cómo |
|---|---|
| Añadir un cliente | Panel → Nuevo cliente → pestaña Alta ([Alta y baja](procedimientos/alta-baja-negocio.md)) |
| Cambiar horarios, servicios, textos | Ficha del cliente en el panel, sin desplegar |
| Subir horarios de `bus` | `make bus-subir NOMBRE=x DIR=var/datos/x COMMENT=… PROD=1` ([Horarios de bus](procedimientos/horarios-bus.md)) |
| Cambiar los horarios de un cliente | Ficha del cliente → Horarios → Aplicar |
| Desplegar un cambio | Commit en `main`, CI en verde, `make deploy` ([Despliegue](procedimientos/despliegue.md)) |
| Volver atrás | `make rollback` ([Volver atrás](incidencias/volver-atras.md)) |
| Probar el despliegue en local | `make localprod-up` ([Entorno local](desarrollo/entorno-local.md)) |
| Ampliar la máquina o cambiar de proveedor | Ampliarla en el proveedor, o `make server-migrate FROM= TO=` ([Traslado](procedimientos/traslado.md)) |

## Ver la documentación como sitio

Desde la raíz del repo, `make docs` sirve el sitio en local; `make docs-check` lo construye en modo estricto (un enlace roto falla) y es lo que ejecuta CI. En el panel, la sección Docs sirve el mismo sitio ([ADR-018](arquitectura/adr/ADR-018-documentacion-en-el-panel.md)). Cómo se escribe y se mantiene: [Documentación](desarrollo/documentacion.md).

Las reglas para trabajar en el repo (idioma, forma de trabajo, reglas obligatorias) están en `CLAUDE.md`, en la raíz.
