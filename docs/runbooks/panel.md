# Panel interno

El Django Admin se eliminó (ADR-008); el panel que lo sustituye es una API propia
(`/api/panel/`, django-ninja) más una SPA que llega en tareas posteriores
(`docs/panel/IMPLEMENTATION.md`, T23a en adelante). Hasta entonces, la API ya existe
y permite consultar y operar mediante sus endpoints; los comandos de
`manage.py` (`docs/comandos.md`) también permiten resolver incidencias:

- **Envíos ambiguos o fallidos** (runbook 05): `outbound_resolve <id> (--mark-sent|--resend)
  --confirm`.
- **Trabajos fallidos** (runbook 03): `job_retry <id>`.

Ambos comandos llaman a `autobot.ops.actions`, que comprueba la elegibilidad bajo
bloqueo y audita el cambio (`audit_event`) en la misma transacción.

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

- La API vive en `/api/panel/`, solo alcanzable por el túnel SSH de operación
  (`make panel-tunnel`, ADR-008): nunca por el Caddy público. `PanelGateMiddleware`
  responde 404 a cualquier petición que llegue con la cabecera `X-Autobot-Edge`
  (la añade el Caddy público) y 503 si el proceso no tiene el alias `owner`
  (`DB_OWNER_URL` sin configurar).
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


## Catálogo y consultas guardadas

La API ofrece `GET /api/panel/data/tables` y el detalle de cada tabla catalogada.
El detalle muestra hasta 20 filas y oculta contraseñas, sesiones, claves TOTP,
secretos cifrados, huellas de invitación y valores de caché. Las tablas desconocidas
se identifican en el listado, pero no se pueden abrir desde el detalle. El acceso a
estas lecturas usa el rol del panel (`fp_owner`).

En `/api/panel/data/saved-queries` se pueden listar, crear, modificar y borrar
consultas guardadas; los cambios quedan auditados. La migración añade cuatro ejemplos.
El ejemplo de costes usa tarifas aproximadas fijadas en su SQL: si cambian las tarifas
debe revisarse la consulta guardada. El ejemplo de contactos más activos los ordena
por la cantidad de mensajes salientes asociados. La ejecución de SQL se implementa en T22.
El rol `fp_app` no tiene permisos sobre `saved_query`; `apply_grants` los reaplica.
