# Panel interno

Guía de uso del panel interno: lo que cada pantalla no explica por sí misma, cómo se da de
alta a un operador y cómo se accede. El diseño (API, capas, seguridad) está en
[../arquitectura/panel.md](../arquitectura/panel.md).

Solo se alcanza por túnel SSH: `make panel-tunnel` en el portátil y luego
`http://127.0.0.1:18000`. La barra lateral tiene Resumen, Clientes, Incidencias, Demo, Logs,
Datos, Sistema y Docs (esta documentación). Si algo falla, Incidencias; para investigar,
Logs. Sin panel, los mismos arreglos se hacen con `manage.py` desde el portátil
(`make prod-manage CMD="..."`): `outbound_resolve <id> (--mark-sent|--resend|--discard)
--confirm` para los [envíos sin confirmar](../incidencias/envios-unknown.md) y
`job_retry <id>` para los [trabajos fallidos](../incidencias/cola-y-latido.md). Los dos
pasan por `autobot.ops.actions`, que comprueba bajo bloqueo y audita en la misma
transacción.

## Resumen

Estado global, indicadores y mensajes del mes, métricas por pack, clientes, sistema y
últimas incidencias; se actualiza cada 30 s. El estado global sale de las incidencias
abiertas y de la salud de los negocios: una incidencia revisada ya no lo sube.

## Clientes

La ficha de un cliente tiene cinco pestañas: Resumen, Configuración, Actividad, Contactos y
Avisos. Pausar o reactivar está en su cabecera; exportar los datos del negocio y eliminarlo,
en el menú «⋯» (ver [retencion-rgpd.md](retencion-rgpd.md)).

- **Resumen:** indicadores del mes, salud del canal con «Comprobar ahora» e incidencias
  abiertas. El resumen del dueño se carga a petición, porque puede consultar Calendar.
- **Actividad:** las conversaciones de este cliente. «Envíos con error» la reduce a lo
  rechazado, sin confirmar o descartado: ahí siguen los envíos ya revisados en Incidencias.
- **Contactos:** cada consulta queda auditada; desde aquí se exportan los datos de un
  contacto o se le olvida (borrado irreversible).

### Configuración del cliente

Reúne el alta y la edición del documento en una sola pestaña
([ADR-027](../arquitectura/adr/ADR-027-alta-y-configuracion-en-una-pestana.md)):

- **Banner de alta**, solo en `onboarding`: cuántos pasos obligatorios faltan, un enlace a
  cada uno y «Activar» (pide escribir el slug). Lo que bloquea lo decide el backend
  (`activation.checklist`).
- **Secciones plegables** con un punto de estado y un resumen en una línea. Dentro, los
  campos, «Más información» (la página de estas docs que lo explica) y las
  «Comprobaciones del alta».
- **«Comprobar» y las acciones** llaman de verdad al proveedor (nunca al cargar), quedan
  auditadas y actúan sobre lo **guardado**: con cambios sin guardar se desactivan.
- **Canal en WhatsApp:** «Configurar webhook», «Registrar número» (pide el PIN de
  verificación en dos pasos, que no se guarda) y «Suscribir app» (con confirmación). Un
  «Resultado desconocido» no se repite solo: «Comprobar» antes de volver a lanzarlo.
- **Canal en Telegram:** el estado del webhook se consulta a Telegram al abrir la sección,
  con «Registrar webhook».
- **Dueño y testers:** «Invitar al dueño» (enlace de un solo uso) y la lista de quien
  escribió sin ser tester, con «Añadir».
- **Avanzado**, siempre la última: historial de versiones con «Ver cambios» y «Volver a
  esta versión» (crea una versión nueva), «Editar como YAML» e ids técnicos.
- **Guardar:** una sola barra abajo; cada guardado es una versión nueva y solo envía lo que
  cambiaste, así que los valores por defecto del pack que nadie tocó siguen al día.

### Asistente de alta de un cliente

`Clientes → Nuevo cliente` crea un negocio en `onboarding` en cinco pasos: pack, datos
básicos (nombre, slug, zona horaria y canal), configuración precargada con la plantilla del
pack, datasets (solo `bus`, elegidos de la biblioteca: [horarios-bus.md](horarios-bus.md)) y
revisión. Al crear abre su Configuración con el banner de lo que falta
([alta-baja-negocio.md](alta-baja-negocio.md)). El progreso solo se guarda en el navegador.

### Avisos del cliente

Los mensajes que la plataforma envió al **dueño** (resumen mensual, avisos de citas…), con
su estado de envío. Sirve para comprobar que le llega lo que debe; los mensajes a clientes
finales están en Actividad.

### Cuenta de servicio de Google Calendar

En un cliente `salon`, la sección «Calendario de Google» muestra el email de la cuenta de
servicio de la plataforma (nunca su clave). El negocio debe compartir su calendario con ese
email con el permiso «Hacer cambios y ver todos los detalles de eventos». Avisa si el
`calendar_id` parece un Gmail personal.

## Demo

Invitaciones al bot de demo: crear (para quién, usos y caducidad), ver su estado y revocar.
Cada código tiene su enlace `t.me/<bot>?start=<código>` y su QR. Detalle en
[demo.md](demo.md).

## Incidencias

Una **bandeja** pensada para llegar a cero
([ADR-031](../arquitectura/adr/ADR-031-incidencias-como-bandeja.md)): una tarjeta por
incidencia abierta, de la más grave a la menos, con su consejo, «Ver logs» y «Ver runbook».

- Una **condición** («está mal ahora»: un contenedor caído, el disco, una cola atrasada,
  envíos sin decidir) se cierra sola cuando se arregla.
- Un **evento** («pasó algo»: un envío rechazado, un trabajo fallido) se cierra con
  **«Lo he revisado»**. Si después ocurre otro caso, vuelve con «N nuevos desde tu revisión».
- **Casos de envío sin confirmar:** «Marcar enviado», «Reenviar» (con riesgo de duplicado)
  o «Descartar»; «Descartar todos» los descarta de una vez. Detalle en
  [envíos sin confirmar](../incidencias/envios-unknown.md).
- **Casos de trabajo fallido:** «Reintentar» solo si es seguro repetirlo
  ([cola y latido](../incidencias/cola-y-latido.md)).
- **Historial**, plegado: las cerradas y cómo se cerraron.

Las claves de cada incidencia están en [alertas](../referencia/alertas.md).

## Logs

Tres pestañas:

- **Técnicos:** las trazas de la aplicación (VictoriaLogs, últimos 31 días), filtrables por
  servicio, nivel, cliente y texto.
- **Conversaciones:** mensajes recibidos, respuestas y avisos al dueño, sin texto en la
  lista; abrir una fila muestra el detalle y queda auditado.
- **Operador:** todas las acciones auditadas (`audit_event`), que se purgan a los 12 meses.

## Datos

El catálogo de tablas (descripción, columnas, RLS, retención y las últimas filas, ocultando
lo sensible) junto a la **consola SQL**: solo lectura (`fp_readonly`), una sentencia, con
límite de tiempo y de tamaño, y un selector de cliente o «Todos». El selector es una
comodidad, no una barrera de seguridad: lo que protege es el rol y `SENSITIVE_TABLES`
([panel](../arquitectura/panel.md)).

## Sistema

- **Flujo de mensajes y Estado:** tráfico de la última hora y salud de workers, base de
  datos, VictoriaLogs, bots y Calendar.
- **Contenedores:** estado, reinicios e imagen de cada uno (en ámbar si no es la del SHA
  desplegado). «Datos desactualizados» significa que el timer de contenedores no escribe
  ([contenedor caído](../incidencias/contenedor-caido.md)).
- **Configuración cargada:** la revisión de cada proceso vivo frente a la de la base de
  datos; si uno se queda atrás más de un minuto salta `config_stale`
  ([runbook](../incidencias/negocio-o-canal.md#proceso-con-configuracion-desactualizada)).
- **Recursos y colas:** CPU, RAM, disco, tamaño de la base, espera de cada cola, backup,
  certificado TLS, versión desplegada e historial de despliegues.

## Alta del operador

Un solo rol: usuario de Django (`is_staff`) con un TOTP confirmado. No hay registro ni
recuperación por email; todo se hace desde el portátil, por SSH:

- **Alta:** `make prod-manage TTY=1 CMD="panel_user create <usuario>"`. Muestra **una sola
  vez** el QR del TOTP: escanéalo antes de cerrar.
- **Recuperar el TOTP:** `make prod-manage TTY=1 CMD="panel_user reset-totp <usuario>"`.
- **Cambiar la contraseña:** `make prod-manage TTY=1 CMD="panel_user set-password <usuario>"`.

## Datos al día

- **Recargar** (barra superior) vuelve a pedir los datos sin perder lo que estés
  escribiendo. Además, la mayoría de pantallas se refrescan solas cada 30 s con la pestaña
  visible.
- Si un refresco falla, se quedan los últimos datos con el aviso «No se pudo actualizar».
- Los resultados de «Comprobar» se conservan mientras la configuración siga en la misma
  versión; desaparecen al guardar un cambio.
- Al guardar un cambio de un cliente, un aviso dice si ya lo han cargado todos los procesos
  («Aplicado en N procesos») o cuál va atrasado. El cambio ya está guardado en cualquier
  caso. Cómo funciona: [config y registro](../arquitectura/config-y-registro.md).

## Sesión y acceso

- Sesión de 12 horas como máximo y 30 minutos de inactividad.
- Las acciones sensibles (borrar o dar de baja, exportar, olvidar un contacto, secretos,
  restaurar una versión, activar el canal real) piden un código TOTP **nuevo**: el de
  entrada no vale, hay que esperar al siguiente (30 s).
- 5 fallos de login en 15 minutos bloquean al usuario 15 minutos. Los errores de login son
  siempre genéricos; el motivo real solo queda en la auditoría.

El detalle de estas barreras está en [panel](../arquitectura/panel.md).

## Dónde está el código

`apps/panel/src/` (`features/`, `components/nav-sections.ts`), `apps/backend/src/autobot/panel/`
(`routers/`, `services/`), `apps/backend/src/autobot/management/commands/panel_user.py`.
