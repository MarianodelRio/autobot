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

- **Envíos ambiguos o fallidos** (ver [envíos sin confirmar](../incidencias/envios-unknown.md)): `outbound_resolve <id> (--mark-sent|--resend)
  --confirm`.
- **Trabajos fallidos** (ver [cola y latido](../incidencias/cola-y-latido.md)): `job_retry <id>`.

Ambos comandos llaman a `autobot.ops.actions`, que comprueba la elegibilidad bajo
bloqueo y audita el cambio (`audit_event`) en la misma transacción.

## Resumen

La pantalla inicial muestra el estado global, los indicadores y mensajes del mes,
las métricas por pack, los clientes, el sistema y las últimas alertas. Se actualiza
cada 30 segundos.

## Clientes

La lista se puede filtrar por pack y estado o buscar por nombre y slug. La ficha
tiene seis pestañas: Resumen, Alta, Configuración, Actividad, Contactos y Avisos (ver
[Avisos](#avisos-del-cliente)).
Resumen muestra los indicadores del mes, la salud del canal con «Comprobar
ahora» y las alertas abiertas; el resumen del dueño se carga a petición, pues
puede consultar Calendar. Alta (ADR-014) reúne en un solo sitio, paso a paso, lo que
falta para activar el negocio: documento, canal (en WhatsApp, también la URL del
webhook a pegar en el panel de Meta), secretos, plantillas (WhatsApp: el texto de
cada una del pack y, al «Comprobar», su estado real en Meta), salud, un mensaje real
de un tester, el dueño, el webhook de Telegram, el calendario de `salon` (D1-D4) y
los horarios de `bus`; los pasos marcados «Comprobar» hacen una llamada real al
proveedor (nunca al cargar la pestaña, ni al volver a ella: leer solo consulta la caché
de salud, y una salud sin comprobar cuenta como pendiente) y quedan auditados. «Salud
del canal» también se comprueba así; «Activar» fuerza siempre la comprobación. Lo que
bloquea la activación lo decide el backend (`activation.checklist`): el webhook de
Telegram no bloquea por sí mismo, pero un webhook sin registrar hace fallar «Salud
del canal», que sí bloquea. «Añadir» un tester solo acepta a quien de verdad escribió. El paso del tester lista
los últimos que escribieron sin estarlo, con «Añadir» para sumarlos a
`testers.main` sin pasar por Configuración. Al final de la pestaña, el QR del canal
(con tamaño y margen correctos, descarga en SVG/PNG y vista para imprimir) y, mientras
el negocio está en `onboarding`, «Activar» (exige completar los pasos bloqueantes y
escribir el slug); pausar o reactivar un negocio ya activo sigue en la cabecera de la
ficha.
Configuración edita con formulario o YAML, con diff legible (campo por campo, no un
volcado de la librería de diferencias) y comentario opcional, e incluye el canal
(enlace, webhook y «Cambiar credenciales», con «Generar» para los campos que lo
admiten — el QR está en Alta) y el dueño («Invitar al dueño», con el enlace mostrado una sola vez, su
caducidad y el aviso de que sustituirá al chat ya conectado). En `salon`, el horario
de apertura tiene un editor por día (abierto/cerrado y tramos con hora) y los
servicios una tabla con id automático; la zona horaria se elige de una lista,
no se escribe a mano. En Telegram, el estado del webhook («Registrado», «Sin
registrar» o «Sin comprobar») se consulta a Telegram (`getWebhookInfo`) y se
refresca al registrarlo; «Sin comprobar» significa que no se pudo saberlo.
«Historial» (junto a «Editar YAML») lista las versiones guardadas con autor y
comentario, con «Ver cambios» (el mismo diff legible contra el documento actual) y
«Volver a esta versión», que crea una versión nueva con ese contenido tras pedir
confirmación. Actividad usa la misma lista que Logs → Conversaciones, limitada a
este cliente. Cada consulta de una conversación desde Contactos queda auditada, y
desde ahí también se puede «Exportar datos» (descarga un JSON) u «Olvidar contacto»
(borrado irreversible, con confirmación) de ese contacto; «Exportar datos del
negocio» (`POST`, pues audita), en el menú «⋯» de la ficha, hace lo mismo a nivel de
negocio, con un tope de 50 000 filas (más allá, el comando `tenant_data_export`) (ver
`docs/procedimientos/retencion-rgpd.md`). El panel pide confirmación para pausar o
reactivar.

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
5. **Revisión:** resumen y YAML final; «Crear cliente» lo crea y abre su pestaña Alta con
   lo que falta para activarlo ([alta-baja-negocio.md](alta-baja-negocio.md)).

El asistente guarda su progreso en `sessionStorage` del navegador, nunca en el servidor.

### Avisos del cliente

La pestaña Avisos (`features/tenants/notifications-tab.tsx`, `GET /tenants/{slug}/notifications`,
`autobot/panel/services/tenants.py`) lista los últimos 50 mensajes que la plataforma envió al
**dueño** del negocio (resumen mensual, avisos de citas...), con su texto, su estado de
envío y cuándo se crearon. Sirve para comprobar que el dueño recibe lo que debe; no incluye
los mensajes a clientes finales (eso está en Actividad).

### Cuenta de servicio de Google Calendar

En Configuración de un cliente `salon`, la tarjeta «Calendario de Google»
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

Reúne lo que requiere intervención: alertas abiertas («Resolver» solo si no se
resuelven solas), envíos `unknown`/`failed` sin confirmar («Marcar enviado» y
«Reenviar», con confirmación del riesgo de duplicado de [envíos sin confirmar](../incidencias/envios-unknown.md)) y trabajos
fallidos («Reintentar» solo si son idempotentes); debajo, el historial de alertas
resueltas, plegado. Si no hay nada abierto, una tarjeta única «Todo en orden». Cada
fila lleva «Ver logs», que abre Logs filtrado por cliente y acotado de 15 minutos
antes a 5 después del último suceso. El contador de la barra lateral cuenta alertas
abiertas, envíos estancados y trabajos fallidos.

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
cualquier dato rechazado por PostgreSQL (p. ej. un NUL) responde 400.

## Sistema

Arriba, dos tarjetas: Flujo de mensajes (estado `ok`/`idle`/`critical` según haya
tráfico, trabajos de entrada retrasados más de 2 min o fallos en la última hora;
recibidos, respondidos y fallos de esa hora) y Estado (los servicios `worker`, `db`
y VictoriaLogs, y las integraciones: bot de avisos, demo Telegram,
demo WhatsApp —apagada si no hay puerta configurada— y Calendar —«N de M
accesibles», solo cuenta clientes con `calendar_sweep`—). `web` ya no está en esta
tarjeta: lo cubre la de Contenedores.

Debajo, la tarjeta Contenedores: una fila por contenedor de producción (`caddy`,
`web`, `worker-inbound`, `worker-outbound`, `panel`, `db`, `victorialogs`), con su
estado, salud, reinicios, desde cuándo está en marcha y la etiqueta de su imagen
(en ámbar si no coincide con el SHA desplegado). «Sin datos de contenedores» significa
que `autobot-containers.timer` no ha escrito nunca la instantánea; «Datos
desactualizados», que lleva más de 3 minutos sin actualizarse (revisa el timer,
`docs/incidencias/contenedor-caido.md`). Durante un despliegue, la tarjeta muestra un
aviso de «Despliegue en curso» y no genera alertas nuevas; igual con una
restauración a medias.

Debajo, CPU, RAM, disco y carga actuales con la gráfica del mes, tamaño de la base
de datos y sus tablas más grandes, y trabajos pendientes por cola. El backup se
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

## Dónde está el código

`apps/panel/src/` (`features/`, `components/nav-sections.ts`), `apps/backend/src/autobot/panel/`
(`routers/`, `services/`), `apps/backend/src/autobot/management/commands/panel_user.py`.
