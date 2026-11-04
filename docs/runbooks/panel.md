# Panel interno

El Django Admin se eliminó (ADR-008); el panel que lo sustituye es una API propia
(`/api/panel/`, django-ninja) y una SPA (React, `apps/panel/`) servidas por el contenedor
`panel` (su propia Caddy, sirve `/` y hace de proxy de `/api/*` hacia `web:8000`). Las
secciones son Resumen, Clientes, Actividad, Incidencias, Logs, Datos, Sistema y
Auditoría. Los comandos de `manage.py` (`docs/comandos.md`) también permiten resolver
incidencias sin pasar por la API:

- **Envíos ambiguos o fallidos** (runbook 05): `outbound_resolve <id> (--mark-sent|--resend)
  --confirm`.
- **Trabajos fallidos** (runbook 03): `job_retry <id>`.

Ambos comandos llaman a `autobot.ops.actions`, que comprueba la elegibilidad bajo
bloqueo y audita el cambio (`audit_event`) en la misma transacción.

## Resumen

La pantalla inicial muestra el estado global, los indicadores y mensajes del mes,
las métricas por pack, los clientes, el sistema y las últimas alertas. Se actualiza
cada 30 segundos; el indicador de la barra superior usa el mismo estado. El buscador
incluye clientes y enlaces a sus fichas.

## Clientes

La lista se puede filtrar por pack y estado o buscar por nombre y slug. La ficha
muestra la salud, los indicadores, el canal y su QR público, la actividad, los
contactos y sus conversaciones, los avisos y los datasets. Cada consulta de una
conversación queda auditada. El resumen del dueño se carga a petición, pues puede
consultar Calendar. «Comprobar salud» fuerza la comprobación del canal. La configuración se edita con formulario o YAML, con diff y comentario obligatorio;
el historial permite recuperar versiones. El panel pide confirmación para pausar o
reactivar y exige comprobaciones y slug para activar. En Canal se sustituye el juego
completo de secretos sin mostrar los valores guardados.

El alta de un negocio nuevo (`/clientes/nuevo`) pasa por pack, datos básicos (nombre,
slug derivado y comprobado, zona horaria y canal), configuración precargada con la
plantilla del pack y revisión; crea el cliente en estado `onboarding` y abre su pestaña
Canal con la lista de lo que falta para activarlo. El asistente guarda su progreso en
`sessionStorage` del navegador, nunca en el servidor.

## Actividad

Lista cruzada de negocios (mensajes, respuestas, avisos, alertas y auditoría) con
filtros de cliente, tipo y estado en la URL; cada elemento se despliega con su detalle.
Mientras no se ha pedido ninguna página más, la primera se refresca cada 15 s.

## Incidencias

Reúne lo que requiere intervención: alertas abiertas («Resolver» solo si no se
resuelven solas), envíos `unknown`/`failed` sin confirmar («Marcar enviado» y
«Reenviar», con confirmación del riesgo de duplicado del runbook 5) y trabajos
fallidos («Reintentar» solo si son idempotentes); debajo, el historial de alertas
resueltas. El contador de la barra lateral cuenta alertas abiertas, envíos
estancados y trabajos fallidos.

## Logs

Consulta los logs técnicos del mes en curso (VictoriaLogs) por rango rápido o fechas,
servicio, nivel, cliente y texto. Cada fila se despliega con el JSON completo, la
excepción si la hay, y «Copiar event_id». Avisa si el rango se recortó al mes en
curso o si el servicio de logs no está disponible (503).

## Datos

**Catálogo:** todas las tablas de PostgreSQL, agrupadas y con su tamaño
(`GET /api/panel/data/tables`, rol `fp_owner`); abrir una muestra su descripción,
columnas, relaciones, filas por cliente y las últimas 20 filas, con «Consultar esta
tabla». El detalle oculta contraseñas, sesiones, claves TOTP, secretos cifrados,
huellas de invitación y valores de caché. Las tablas sin documentar aparecen en «Sin
catalogar» pero no se pueden abrir desde el detalle.

**Consulta:** editor SQL de solo lectura (`fp_readonly`, solo
`SELECT`/`WITH`/`VALUES`, `POST /api/panel/data/query`) con autocompletado del
catálogo, ⌘↵ para ejecutar, «Copiar» (TSV) y «Descargar CSV», selector de cliente o
«Todos», y un panel de consultas guardadas (`/api/panel/data/saved-queries`: listar,
crear, modificar y borrar, todo auditado); recuerda la última consulta en el
navegador. La migración siembra cuatro consultas de ejemplo: la de costes usa tarifas
aproximadas fijadas en su SQL (revisarla si cambian las tarifas de Meta) y la de
contactos más activos los ordena por mensajes salientes. `fp_app` no tiene permisos
sobre `saved_query`; `apply_grants` los reaplica.

## Sistema

CPU, RAM, disco y carga actuales, con la gráfica del mes; estado de los servicios
(`web`, `worker`, `db`, VictoriaLogs), tamaño de la base de datos y sus tablas más
grandes, y trabajos pendientes por cola. El backup se marca en rojo si `ok=false` o
lleva más de 8 h; el TLS, en ámbar con menos de 20 días y en rojo con menos de 7.
Abajo, la versión desplegada y el historial de despliegues, con el SHA enlazado al
commit en GitHub.

## Auditoría

Todas las acciones del operador (`audit_event`), filtrables por cliente y acción, con
el detalle completo en JSON. Se purga a los 12 meses junto con el historial de
alertas resueltas (`purge_platform_history`).

## Alta del operador

Un solo rol: usuario de Django (`is_staff=True`) con un dispositivo TOTP confirmado.
No hay registro propio ni recuperación por email; la única forma de arreglarlo es por
SSH.

- **Alta inicial:** `make prod-manage TTY=1 CMD="panel_user create <usuario>"`. Pide la
  contraseña dos veces (con los validadores de Django) y muestra **una sola vez** la
  URI `otpauth://` y su QR en ASCII: escanéalo con una app de autenticación
  (Google Authenticator, Authy...) antes de cerrar la sesión SSH. Si se pierde, no hay
  forma de recuperarlo: usa `reset-totp`.
- **Recuperar el TOTP** (móvil perdido, app reinstalada):
  `make prod-manage TTY=1 CMD="panel_user reset-totp <usuario>"`. Borra el dispositivo
  anterior y muestra uno nuevo, también una sola vez.
- **Cambiar la contraseña:** `make prod-manage TTY=1 CMD="panel_user set-password <usuario>"`.
- `panel_user exists <usuario>` sale con código 0 si existe y 1 si no; lo usa
  `make dev-bootstrap` en local para no pedir el alta en cada arranque.

## Sesión y acceso

- La SPA y la API viven en el contenedor `panel` (puerto 8080, solo en
  `127.0.0.1`), alcanzable únicamente por el túnel SSH de operación
  (`make panel-tunnel`, ADR-008): nunca por el Caddy público, que no conoce ese
  puerto. La Caddy del panel quita cualquier `X-Autobot-Edge` antes de reenviar a
  `web:8000`; aun así, `PanelGateMiddleware` responde 404 si esa cabecera llegara por
  algún otro camino, y 503 si el proceso no tiene el alias `owner` (`DB_OWNER_URL`
  sin configurar).
- Sesión de 12 horas, cookies `autobot_panel_session` y `autobot_panel_csrftoken`
  (nombres propios para no chocar con otra app en `127.0.0.1`). Toda escritura exige
  la cabecera `X-CSRFToken`.
- 5 fallos de login en 15 minutos bloquean ese usuario 15 minutos (no la IP, que
  siempre es la del contenedor `panel`). Los errores de login son siempre genéricos;
  el motivo real (usuario, contraseña, OTP) solo queda en la auditoría
  (`auth.login_failed`), nunca en la respuesta.
- `fp_app` (el rol de `web` y `worker`) no tiene ningún acceso a las tablas de Django
  (`auth_user`, `django_session`, `otp_totp_totpdevice`...): están enrutadas a
  `fp_owner` por `AuthDatabaseRouter`. Un webhook nunca las consulta.

## Escritura de negocios

La API del panel permite crear negocios, publicar y recuperar versiones de configuración,
pausar o reactivar negocios y sustituir los secretos completos del canal. Cada cambio
queda auditado con el usuario del panel. La baja se realiza únicamente por comando.
