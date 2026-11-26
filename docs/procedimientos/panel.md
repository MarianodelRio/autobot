# Panel interno

Guía de uso del panel interno: qué hay en cada pantalla, cómo se da de alta a un operador
y cómo se accede. Léela cuando vayas a operar clientes, incidencias o la demo desde el
panel. El diseño (API, capas, seguridad) está en [../arquitectura/panel.md](../arquitectura/panel.md).

El panel es una API propia (`/api/panel/`, django-ninja) y una SPA (React, `apps/panel/`)
servidas por el contenedor `panel` (su propia Caddy: sirve `/` y hace de proxy de `/api/*`
hacia `web:8000`). Solo se alcanza por túnel SSH: `make panel-tunnel` en el portátil y
luego `http://127.0.0.1:18000`.

Las secciones de la barra lateral son Resumen, Clientes, Incidencias, Demo, Logs, Datos y
Sistema. Si algo falla, Incidencias; para investigar, Logs. La documentación también está
en el panel, en Docs (barra lateral). Los comandos de `manage.py`
([../referencia/comandos.md](../referencia/comandos.md)) permiten resolver incidencias sin
pasar por la API, con `make prod-manage CMD="..."` desde el portátil:

- **Envíos ambiguos** (ver [envíos sin confirmar](../incidencias/envios-unknown.md)): `outbound_resolve <id> (--mark-sent|--resend|--discard)
  --confirm`.
- **Trabajos fallidos** (ver [cola y latido](../incidencias/cola-y-latido.md)): `job_retry <id>`.

Ambos comandos llaman a `autobot.ops.actions`, que comprueba la elegibilidad bajo
bloqueo y audita el cambio (`audit_event`) en la misma transacción.

## Resumen

La pantalla inicial muestra el estado global, los indicadores y mensajes del mes,
las métricas por pack, los clientes, el sistema y las últimas incidencias. El estado
global sale de las incidencias abiertas y la salud de los negocios: una incidencia revisada
o un envío fallido antiguo ya no lo suben. Se actualiza
cada 30 segundos.

## Clientes

La lista se puede filtrar por pack y estado o buscar por nombre y slug. La ficha
tiene cinco pestañas: Resumen, Configuración, Actividad, Contactos y Avisos (ver
[Avisos](#avisos-del-cliente)). Pausar o reactivar un negocio ya activo está en la
cabecera de la ficha; el panel pide confirmación.

Resumen muestra los indicadores del mes, la salud del canal con «Comprobar
ahora» y las alertas abiertas; el resumen del dueño se carga a petición, pues
puede consultar Calendar.

Actividad usa la misma lista que Logs → Conversaciones, limitada a
este cliente. Cada consulta de una conversación desde Contactos queda auditada, y
desde ahí también se puede «Exportar datos» (descarga un JSON) u «Olvidar contacto»
(borrado irreversible, con confirmación) de ese contacto; «Exportar datos del
negocio» (`POST`, pues audita), en el menú «⋯» de la ficha, hace lo mismo a nivel de
negocio, con un tope de 50 000 filas y de 25 MB de JSON (más allá responde 413 y hay que usar el comando `tenant_data_export`, que escribe un fichero privado) (ver
`docs/procedimientos/retencion-rgpd.md`).

### Configuración del cliente

Reúne el alta y la edición del documento en una sola pestaña (ADR-014, ADR-027);
`?tab=alta` en la URL también la abre.

**Banner de alta.** Mientras el negocio está en `onboarding`, arriba aparece «Alta: N de M
pasos obligatorios listos», con los pasos bloqueantes que faltan (cada uno abre su
sección y se desplaza a ella) y «Activar»: exige completar los pasos bloqueantes y
escribir el slug, y fuerza siempre la comprobación de salud. Con el negocio activo o
pausado no hay banner. Lo que bloquea la activación lo decide el backend
(`activation.checklist`): el webhook de Telegram no es un paso aparte, pero un webhook
sin registrar hace fallar «Salud del canal», que sí bloquea; el dueño no bloquea. Un paso
que no pertenece a ninguna sección se muestra también arriba.

**Secciones.** Debajo, secciones plegables (se pueden abrir varias). Cerrada, cada una
muestra un punto de estado según sus pasos de alta (rojo si una comprobación dio error,
ámbar si falta un paso obligatorio, verde si todos están bien), su nombre, un resumen de una
línea con los valores clave y, si procede, «modificado» (cambios sin guardar) o «con
errores» (el último guardado falló en algún campo suyo). Abierta: una explicación breve
con «Más información» (abre en otra pestaña la página de esta documentación que lo
explica a fondo), sus campos (cada parámetro con una línea de ayuda debajo), «Comprobaciones del alta» (sus pasos, cada uno con su estado, por qué importa,
qué hacer y valores con copiar) y sus extras. Al cargar se abren solas las secciones con un
paso bloqueante pendiente (en `onboarding`) y la de `?section=` (p. ej. `?section=canal`).

Los pasos marcados «Comprobar» y las acciones hacen una llamada real al proveedor (nunca
al cargar la pestaña, ni al volver a ella: leer solo consulta la caché de salud, y una
salud sin comprobar cuenta como pendiente) y quedan auditados. Comprueban lo **guardado**:
mientras su sección tiene cambios sin guardar se deshabilitan con «Guarda antes de
comprobar».

Secciones de todos los packs:

- **Negocio:** nombre, zona horaria (se elige de una lista, no se escribe a mano),
  `business_name`, `contact_phone` y `demo`. Paso: documento válido.
- **Canal:** ids del canal, el enlace público, el QR (con tamaño y margen correctos,
  descarga en SVG/PNG y vista para imprimir) y «Cambiar credenciales», con «Generar» para
  los campos que lo admiten. Pasos: canal, secretos, salud del canal y, en WhatsApp, la URL
  del webhook a pegar en Meta, las plantillas (el texto de cada una del pack y, al
  «Comprobar», su estado real en Meta) y las acciones de Meta (ADR-016): «Configurar
  webhook», «Registrar número» (pide un PIN de verificación en dos pasos de 6 dígitos que
  no se guarda) y «Suscribir app» (con confirmación). Una acción con «Resultado
  desconocido» no se repite sola: «Comprobar» antes de volver a lanzarla. En Telegram, el
  estado del webhook («Registrado», «Sin registrar» o «Sin comprobar») se consulta a
  Telegram (`getWebhookInfo`) cada vez que se abre la sección y se refresca al registrarlo
  con «Registrar webhook»; «Sin comprobar» significa que no se pudo saberlo. Es el único
  sitio donde sale el webhook de Telegram: no hay un paso del alta que lo repita.
- **Dueño y testers:** `owner` y `testers`, más «Invitar al dueño» (enlace mostrado una
  sola vez, su caducidad y el aviso de que sustituirá al chat ya conectado) y
  desconectarlo. El paso del tester exige un mensaje real de un tester por el canal
  principal y lista los últimos que escribieron sin estarlo, con «Añadir» para sumarlos a
  `testers.main` (solo acepta a quien de verdad escribió).
- **Privacidad:** `privacy` (`privacy.policy_url` es obligatorio para activar).

`salon` añade Servicios y horario (tabla de servicios con id automático y editor de
apertura por día, abierto/cerrado y tramos con hora), Reservas y recordatorios
(`reminder_window_hours` solo aparece con los recordatorios activados y
`manual_confirmations_since` solo con las confirmaciones manuales), Calendario de Google
(ver [abajo](#cuenta-de-servicio-de-google-calendar), con la prueba de escritura D1-D4),
Evento especial y Textos del bot. `bus` añade Oficina y enlaces y Horarios y búsqueda
(los horarios en uso, con «Aplicar» para cambiar a otra entrada de la biblioteca). Un
campo de `config` que ninguna sección nombra sale en «Otros ajustes».

La última sección es siempre **Avanzado**: «Historial» lista las versiones guardadas con
autor y comentario, con «Ver cambios» (diff legible campo por campo contra el documento
actual) y «Volver a esta versión», que crea una versión nueva con ese contenido tras pedir
confirmación; «Editar como YAML»; y los ids técnicos (slug, pack, id).

**Guardar.** Una sola barra fija abajo, visible solo si algo cambió, guarda todo el
documento como una versión nueva, con diff legible y comentario opcional. Solo se envía
lo que se cambió: los valores por defecto del pack que nadie tocó no se escriben en el
documento, así que un cambio futuro de ese valor por defecto sigue llegando al negocio.

### Asistente de alta de un cliente

`Clientes → Nuevo cliente` (`/clientes/nuevo`, `apps/panel/src/features/onboarding/`) crea
un negocio en estado `onboarding` en cinco pasos:

1. **Pack:** elige uno de los packs instalados (`salon`, `bus`...).
2. **Datos básicos:** nombre, slug (derivado del nombre, editable; se valida el formato y
   que esté libre), zona horaria y canal.
3. **Configuración:** formulario (o YAML, con diff) precargado con la plantilla del pack.
4. **Datasets:** solo para packs que los necesitan (`bus`): se elige una entrada de la
   biblioteca ([horarios-bus.md](horarios-bus.md)); si no hay ninguna, avisa de que hay que
   subirla antes con `make bus-subir`.
5. **Revisión:** resumen y YAML final; «Crear cliente» lo crea y abre su pestaña Configuración, con
   el banner de lo que falta para activarlo ([alta-baja-negocio.md](alta-baja-negocio.md)).

El asistente guarda su progreso en `sessionStorage` del navegador, nunca en el servidor.

### Avisos del cliente

La pestaña Avisos (`features/tenants/notifications-tab.tsx`, `GET /tenants/{slug}/notifications`,
`autobot/panel/services/tenants.py`) lista, de más reciente a más antigua y de 50 en 50 («Cargar más»), los mensajes que la plataforma envió al
**dueño** del negocio (resumen mensual, avisos de citas...), con su texto, su estado de
envío y cuándo se crearon. Sirve para comprobar que el dueño recibe lo que debe; no incluye
los mensajes a clientes finales (eso está en Actividad).

### Cuenta de servicio de Google Calendar

En Configuración de un cliente `salon`, la sección «Calendario de Google»
(`routers/calendar.py`, `GET /calendar/service-account`) muestra el email de la **cuenta de
servicio de la plataforma** con botón de copiar (nunca su clave privada). Es el email con el
que el negocio debe compartir su calendario («Hacer cambios y ver todos los detalles de
eventos»). Avisa si el servidor no tiene cuenta configurada o si el `calendar_id` parece un
Gmail personal.

## Demo

La pantalla Demo (`features/demo-invites`) gestiona las invitaciones al bot de demo: «Crear
invitación» (nota de para quién es, usos y caducidad o «No caduca») y la lista de códigos
con su estado (Activa, Agotada, Caducada, Revocada), usos y «Revocar». Cada código tiene su
enlace `t.me/<bot>?start=<código>` y su QR si `DEMO_TELEGRAM_BOT_USERNAME` está
configurada. Detalle y límites en [demo.md](demo.md).

## Incidencias

Una bandeja de **incidencias abiertas** ([ADR-031](../arquitectura/adr/ADR-031-incidencias-como-bandeja.md)),
de la más grave y reciente a la menos. Cada una tiene su título y consejo en español, su
runbook y sus **casos** (envíos, trabajos o avisos afectados), con las acciones de cada uno:
«Marcar enviado», «Reenviar» (con confirmación del riesgo de duplicado) y «Descartar» en un
envío sin confirmar ([envíos sin confirmar](../incidencias/envios-unknown.md)), y
«Reintentar» en un trabajo fallido idempotente. Una **condición** se cierra sola al
corregirse la causa; un **evento** se cierra con «Lo he revisado», y un caso posterior lo
reabre con «N nuevos desde tu revisión». Debajo, el historial de las cerradas y cómo se
cerró cada una (sola, por una caída, revisada, informativa). Si no hay nada abierto,
«Todo en orden». El contador de la barra lateral y el nivel del Resumen cuentan las mismas
incidencias abiertas. Claves y cierres: [alertas](../referencia/alertas.md).

## Logs

Tres pestañas, seleccionadas por `?tab=` en la URL (`technical` por defecto,
`conversations`, `operator`); cambiar de pestaña conserva el filtro de cliente y
limpia los demás.

- **Técnicos:** trazas de la aplicación (VictoriaLogs) por rango rápido o fechas,
  servicio, nivel, cliente y texto; el rango máximo son los últimos 31 días, la
  retención real. Cada fila abre un panel lateral con cabecera, mensaje, excepción,
  resto de campos en JSON plegado y «Copiar event_id». Avisa si el rango se recortó
  o si el servicio de logs no está disponible (503).
- **Conversaciones:** mensajes recibidos, respuestas y avisos al dueño, sin texto ni
  nombre de contacto en la lista; desplegar una fila pide el detalle a un endpoint
  que lo audita (`activity.view`), sin el texto en la auditoría. Filtros de cliente,
  tipo (chips) y estado. Mientras no se ha pedido ninguna página más, la primera se
  refresca cada 15 s.
- **Operador:** todas las acciones (`audit_event`), filtrables por cliente y acción
  (desplegable alimentado por los valores existentes), con el detalle completo en
  JSON. Se purga a los 12 meses junto con el historial de alertas resueltas
  (`purge_platform_history`).

## Datos

Una sola pantalla con la consola SQL y el catálogo de tablas uno junto al otro
(`GET /api/panel/data/tables`, rol `fp_owner`). El catálogo está agrupado y se
puede buscar por nombre o descripción; pinchar una tabla abre un recuadro con su
descripción, columnas e insignias (escrita por, retención, RLS), con dos acciones:
«Insertar SELECT» (rellena el editor sin ejecutar) y «Ver detalle» (solo para
tablas documentadas). El detalle de una tabla (`/datos/$tabla`) añade filas por
cliente, relaciones (Apunta a / La usan) y las últimas 20 filas, ocultando
contraseñas, sesiones, claves TOTP, secretos cifrados, huellas de invitación y
valores de caché. Las tablas sin documentar aparecen en «Sin catalogar» pero no
tienen detalle.

**Consola SQL:** editor de solo lectura (`fp_readonly`, solo
`SELECT`/`WITH`/`VALUES`, `POST /api/panel/data/query`) con autocompletado del
catálogo, ⌘↵ para ejecutar, «Copiar» (TSV) y «Descargar CSV», y selector de
cliente o «Todos»; recuerda la última consulta en el navegador. El selector es un
filtro de comodidad, no una frontera de seguridad (una consulta puede cambiarlo con
`set_config`). Límites: 2 consultas a la vez por proceso (la tercera recibe 429
«consola ocupada»), 10 000 caracteres por celda y 5 MB por resultado (se marca como
truncado), una sola sentencia (un `;` final o dentro de un literal/comentario vale) y
cualquier dato rechazado por PostgreSQL (p. ej. un NUL) o una consulta que excede el
tiempo responde 400. Si falla la propia base de datos (conexión perdida o rechazada) la
respuesta es 503 con un mensaje genérico, sin el texto del driver.

## Sistema

Arriba, dos tarjetas: Flujo de mensajes (estado `ok`/`idle`/`critical` según haya
tráfico, trabajos de entrada retrasados más de 2 min o fallos en la última hora;
recibidos, respondidos y fallos de esa hora) y Estado (los servicios `worker`, `db`
y VictoriaLogs, y las integraciones: bot de avisos, demo Telegram,
demo WhatsApp —apagada si no hay puerta configurada— y Calendar —«N de M
accesibles», solo cuenta clientes con `calendar_sweep`—). `worker` está en verde solo
si laten al menos 4 workers (procrastinate registra una fila por proceso, sin nombre, así
que no se pueden atribuir a un servicio) **y** el estado de contenedores, si está
fresco, muestra los cuatro `worker-*` en `running`: así un worker caído no queda tapado
por la fila vieja de otro reiniciado. `web` ya no está en esta
tarjeta: lo cubre la de Contenedores.

Debajo, la tarjeta Contenedores: una fila por contenedor de producción (`caddy`,
`web`, `web-panel`, `worker-inbound`, `worker-calendar`, `worker-periodic`, `worker-outbound`, `panel`, `db`, `victorialogs`), con su
estado, salud, reinicios, desde cuándo está en marcha y la etiqueta de su imagen
(en ámbar si no coincide con el SHA desplegado). «Sin datos de contenedores» significa
que `autobot-containers.timer` no ha escrito nunca la instantánea; «Datos
desactualizados», que lleva más de 3 minutos sin actualizarse (revisa el timer,
`docs/incidencias/contenedor-caido.md`). Durante un despliegue, la tarjeta muestra un
aviso de «Despliegue en curso» y no genera alertas nuevas; igual con una
restauración a medias.

Debajo, el bloque «Configuración cargada»: la revisión de la configuración en la base de
datos, cuándo cambió por última vez y una fila por proceso vivo (`web`, `web-panel` y los
cuatro workers) con la revisión que ha cargado y cuándo latió por última vez. Un proceso que
va por detrás de la base de datos se marca en ámbar; en condiciones normales todos están
al día en unos 2 s tras un cambio. Si uno se queda atrás más de un minuto salta la alerta
`config_stale` ([runbook](../incidencias/negocio-o-canal.md#proceso-con-configuracion-desactualizada)).
«Vivo» significa que su fila se renovó en los últimos 35 s.

Debajo, CPU, RAM, disco y carga actuales con la gráfica del mes, tamaño de la base
de datos y sus tablas más grandes, y por cola los trabajos pendientes, cuánto espera el
más antiguo y los que están en curso (si una cola se retrasa, salta `queue_lag:<cola>`,
ver [alertas](../referencia/alertas.md)). El backup se
marca en rojo si `ok=false` o lleva más de 8 h; el TLS, en ámbar con menos de 20
días y en rojo con menos de 7. Abajo, la versión desplegada y el historial de
despliegues, con el SHA enlazado al commit en GitHub.

## Alta del operador

Un solo rol: usuario de Django (`is_staff=True`) con un dispositivo TOTP confirmado. No hay
registro propio ni recuperación por email; la única forma de arreglarlo es por SSH. Todos
los comandos se lanzan desde el portátil, con la clave de operación y el alias `autobot`
(o `HOST=<alias>`), y se ejecutan en la VPS como `deploy` (`manage.sh`):

- **Alta inicial:** `make prod-manage TTY=1 CMD="panel_user create <usuario>"`. Pide la
  contraseña dos veces (con los validadores de Django) y muestra **una sola vez** la URI
  `otpauth://` y su QR en ASCII: escanéalo con una app de autenticación antes de cerrar la
  sesión SSH.
- **Recuperar el TOTP** (móvil perdido, app reinstalada):
  `make prod-manage TTY=1 CMD="panel_user reset-totp <usuario>"`. Borra el dispositivo
  anterior y muestra uno nuevo, también una sola vez.
- **Cambiar la contraseña:** `make prod-manage TTY=1 CMD="panel_user set-password <usuario>"`.
- `panel_user exists <usuario>` sale con código 0 si existe y 1 si no; lo usa `make local`
  en local para no pedir el alta en cada arranque.

## Datos al día

- El botón **Recargar** de la barra superior (siempre visible) vuelve a pedir los datos de la pantalla; el icono gira solo mientras esperas ese refresco manual, no en los refrescos automáticos. Los resultados de «Comprobar» se conservan (ver abajo) y los cambios sin guardar de la configuración no se pierden.
- Cada 30 s, solo con la pestaña visible, se refrescan solos: la lista de clientes, el detalle y el resumen de un cliente, el historial de versiones, los secretos, la lista de avisos y contactos, la checklist de activación y las invitaciones de demo (Resumen, Incidencias y Sistema ya lo hacían). Las listas con «Cargar más» (contactos, avisos, historial, invitaciones) solo se refrescan solas mientras muestras la primera página: si cargas más, dejan de hacerlo para no releer todo; usa «Recargar».
- No se refrescan solos los pasos del alta, el estado del webhook de Telegram (cada lectura llama a Telegram; se actualiza al abrir, al volver a la ventana y tras un cambio del canal: credenciales, webhook, configuración, restauración o estado), ni los logs, ni los resultados de la consola de datos o de la búsqueda de auditoría, ni las vistas previas de versiones ni los QR.
- Si un refresco falla estando ya los datos en pantalla (la red, un reinicio), la pantalla no se sustituye por un error: se queda con los últimos datos, conserva lo que estés escribiendo (borrador de configuración, valores de «Cambiar credenciales») y muestra el aviso «No se pudo actualizar; se muestran los últimos datos» con «Reintentar». El error a pantalla completa solo sale si nunca hubo datos.
- Los resultados de «Comprobar» y de las acciones del alta (los que llaman a Meta, Telegram o Google) los devuelve el servidor solo en el momento, así que el panel los guarda aparte y los superpone a los pasos mientras la configuración del cliente siga en la misma versión. Sobreviven a un refresco automático, a «Recargar», a cambiar de pestaña y a otras escrituras que no tocan la configuración (invitar al dueño, olvidar un contacto…). Desaparecen al guardar un cambio de configuración (cambia la versión: el resultado ya no vale), al restaurar una versión o al recargar la página del navegador.
- Al guardar o cambiar algo de un cliente (configuración, restaurar versión, aplicar horarios, credenciales, webhook, dueño, estado), se refresca todo lo suyo sin recargar el navegador: ficha, canal, enlace y QR, pasos del alta, checklist, historial, resumen, la lista de clientes y Resumen. Si el guardado choca con una versión más reciente, también se refresca.

## Confirmación de que un cambio está aplicado

Al guardar un cambio de un cliente (configuración, restaurar versión, aplicar horarios, credenciales, webhook, dueño, estado) sale un aviso en la esquina que se actualiza solo: «Aplicando el cambio…» mientras los procesos van cargando la configuración nueva (hasta 30 s en total; si pasan 10 s sin que ninguno avance, se da por detenido) y después «Aplicado en N procesos» (verde) o, si alguno no ha llegado, «Aplicado en X de N; siguen con la versión anterior: <servicio>» (ámbar; «(con error)» si ese proceso informa de un fallo). Un proceso con una revisión distinta de la de la base de datos, anterior o posterior (por ejemplo tras restaurar una versión antigua), cuenta como no aplicado. Al terminar, el panel vuelve a refrescar los datos del cliente. El cambio ya está guardado en cualquiera de los casos: el aviso solo dice cuántos procesos lo han cargado. Solo aparece al guardar la configuración, restaurar una versión, aplicar horarios, cambiar credenciales, añadir un tester y cambiar el estado (pausar, reactivar, activar). No aparece al exportar, ni en «Comprobar» y las acciones de Meta, ni al registrar el webhook, invitar o desconectar al dueño, olvidar un contacto o eliminar el cliente. Si un servicio no se pone al día, mira Sistema y la alerta `config_stale`.

## Sesión y acceso

- La SPA y la API viven en el contenedor `panel` (puerto 8080, solo en
  `127.0.0.1`), alcanzable únicamente por el túnel SSH de operación
  (`make panel-tunnel`, ADR-008): nunca por el Caddy público, que no conoce ese
  puerto. La Caddy del panel quita cualquier `X-Autobot-Edge` antes de reenviar a
  `web:8000`; aun así, `PanelGateMiddleware` responde 404 si esa cabecera llegara por
  algún otro camino, y 503 si el proceso no tiene el alias `owner` (`DB_OWNER_URL`
  sin configurar).
- Sesión de 12 horas como máximo y 30 minutos de inactividad: pasado ese tiempo sin
  peticiones hay que volver a entrar. Las acciones sensibles (borrar o dar de baja un
  negocio, exportar datos, olvidar un contacto, secretos, restaurar una versión,
  activar el canal real) piden además un código TOTP nuevo, válido 5 minutos; no sirve
  el código con el que acabas de entrar, hay que esperar al siguiente (30 s). Cookies `autobot_panel_session` y `autobot_panel_csrftoken`
  (nombres propios para no chocar con otra app en `127.0.0.1`). Toda escritura exige
  la cabecera `X-CSRFToken`.
- 5 fallos de login en 15 minutos bloquean ese usuario 15 minutos; además hay un tope de
  20 intentos fallidos en 15 minutos por dirección (por el túnel, la del contenedor
  `panel`, así que en la práctica es un tope global contra el rocío de usuarios). El
  contador es atómico (`cache.add` por intento, reservado antes de comprobar) y cada
  bloqueo queda en la auditoría como `auth.login_blocked`. Los errores de login son siempre genéricos;
  el motivo real (usuario, contraseña, OTP) solo queda en la auditoría
  (`auth.login_failed`), nunca en la respuesta.
- `fp_app` (el rol de `web` y `worker`) no tiene ningún acceso a las tablas de Django
  (`auth_user`, `django_session`, `otp_totp_totpdevice`...): están enrutadas a
  `fp_owner` por `AuthDatabaseRouter`. Un webhook nunca las consulta.

## Escritura de negocios

La API del panel permite crear negocios, publicar y recuperar versiones de configuración,
pausar o reactivar negocios, sustituir sus secretos de canal y eliminarlos por completo
(menú «⋯» de la ficha, deshabilitado si el negocio está activo: lo da de baja y lo
borra en la misma operación; ver `retencion-rgpd.md`). Cada cambio queda auditado con
el usuario del panel.

## Listas largas

Ninguna lista del panel lee la tabla entera: contactos, actividad, auditoría, avisos del
cliente, invitaciones de demo e incidencias se piden por **cursor** (`next_cursor`, opaco; un
cursor manipulado devuelve 400), con páginas de 50 y un máximo de 100 filas, y el panel
carga más con «Cargar más». El cursor (marca de tiempo e id de la última fila) evita
repetir o saltarse filas aunque entren otras nuevas y cuesta lo mismo en la página 1 que
en la 100. Cada orden tiene su índice (`contact_panel_list_idx`, `inbound_feed_idx`,
`outbound_feed_idx`, `notification_feed_idx`, `outbound_sent_feed_idx`, y los de
`tenant, created_at` ya existentes). Las listas de negocios (decenas) y las tablas del
catálogo no se paginan: el registro de negocios vive en memoria y el número de consultas
no depende de cuántos haya (los últimos mensajes, el mes en curso y el estado de salud
se leen en bloque; hay tests que lo comprueban con 2 y 14 negocios). Los logs se piden a
VictoriaLogs siempre con rango de tiempo (por defecto 1 hora, máximo 31 días) y como mucho
1.000 líneas.

## Dónde está el código

`apps/panel/src/` (`features/`, `components/nav-sections.ts`), `apps/backend/src/autobot/panel/`
(`routers/`, `services/`), `apps/backend/src/autobot/management/commands/panel_user.py`.
