# Registro de auditoría

Catálogo de las acciones que se anotan en el registro de auditoría (`audit_event`): quién las
hace, qué se guarda y qué se rechaza. Léelo cuando revises el registro desde el panel
(Logs, pestaña Operador) o añadas una acción nueva. El diseño de seguridad está en
[seguridad y secretos](../arquitectura/seguridad-y-secretos.md).

## Qué se guarda

Cada escritura del panel y de los comandos de operación llama a
`apps/backend/src/autobot/ops/audit.py` (`record`, `record_tenant`). Un evento guarda:

| Campo | Contenido |
|---|---|
| `actor` | Quién: el usuario del panel, o `command:<nombre>` si lo hizo un comando de `manage.py`. |
| `action` | La clave de la acción (tabla siguiente). |
| `summary` | Frase corta en español. |
| `tenant_id` | Negocio afectado, si lo hay (sin RLS por diseño, ADR-009). |
| `target_type`, `target_id` | Qué objeto se tocó (`tenant`, `contact`, `outbound_message`, `job`, `ops_alert`, `dataset`, `demo_invite`, `bot`…). |
| `details` | Datos extra en JSON, sin secretos. |

La escritura se hace con el rol `owner` en su propia transacción. Dentro de la misma
transacción que la acción cuando esta puede borrar datos (`contact.forget`), para que nunca
haya un borrado sin rastro.

## Qué se rechaza

- **Claves con forma de secreto.** Si `details`, a cualquier nivel, contiene una de las
  claves `token`, `secret`, `password`, `access_token`, `app_secret`, `verify_token`,
  `bot_token`, `webhook_secret` u `otp`, `record` lanza `ValueError` y no escribe nada. Es
  una red de seguridad contra errores de programación: los valores de los secretos nunca
  deben llegar hasta aquí (en `tenant.secrets` solo se guardan los **nombres** de los campos).
- **Caracteres NUL**: se eliminan del texto, porque PostgreSQL los rechaza y una auditoría no
  debe fallar (ni deshacer la acción) por texto libre.

El registro lo puede borrar solo la retención nocturna o `tenant_purge`
([retención y borrado de datos](../procedimientos/retencion-rgpd.md)).

## Acciones

### Negocios (`tenant.*`)

| Acción | Cuándo | Detalles |
|---|---|---|
| `tenant.create` | Se crea un negocio. | `version`, `comment` |
| `tenant.publish` | Se publica la configuración (panel o `tenant_config import`). | `version`, `comment` |
| `tenant.rollback` | Se recupera una versión anterior de la configuración. | `version`, `comment` |
| `tenant.status` | Pausa, reanudación o baja. | `version`, `comment` |
| `tenant.secrets` | Se sustituyen los secretos de canal, o se recifran (`tenant_secrets_reencrypt`). | solo `fields` (nombres) o `reencrypted` |
| `tenant.export` | Exportación de todos los datos de un negocio (panel o `tenant_data_export`). | |
| `tenant.purge` | Borrado total tras la baja (`tenant_purge`). | `slug`; sin `tenant_id`, porque el negocio ya no existe |
| `tenant.notifications.view` | Se abren los avisos enviados al dueño (sus textos pueden contener nombres y citas). | |
| `tenant.owner_invite` | Se genera el enlace de invitación del dueño. | |
| `tenant.owner_unlink` | Se desconecta al dueño, o se cancela su invitación. | |
| `tenant.webhook_register`, `tenant.webhook_delete` | Se registra o borra el webhook de Telegram de un bot. Para los bots de plataforma (`demo`, `notify`) no hay `tenant_id` y el objeto es `bot`. | |
| `tenant.setup_add_tester` | Se añade un tester desde la pestaña Configuración (sección «Dueño y testers»). | |
| `tenant.setup_check` | Se comprueba un paso del alta (pestaña Configuración). | `step`, `state` |
| `tenant.setup_action` | Se ejecuta una acción del alta (pestaña Configuración). | `step`, `outcome` |

### Contactos (`contact.*`)

| Acción | Cuándo | Detalles |
|---|---|---|
| `contact.list` | Se lista (o se pagina) los contactos de un negocio en el panel. | `paged` |
| `contact.search` | Se busca entre los contactos de un negocio. El término **nunca** se guarda en claro. | `search_length` y `search_hmac` (16 hex de un HMAC con clave de plataforma: permite ver si dos búsquedas son la misma) |
| `contact.view` | Se abre la ficha de un contacto en el panel. | `contact_id` |
| `contact.export` | Exportación de los datos de un contacto (panel o `contact_export`). | `contact_id` |
| `contact.forget` | Borrado de un contacto (panel o `contact_forget`). | `contact_id` |
| `privacy.reapply` | Tras restaurar un backup: reaplicación de los olvidos y purgas del libro de supresiones (`privacy_reapply`). | contadores (`entries`, `contacts`, `tenants`, `other_rows`, `blocked`) |

### Envíos y trabajos

| Acción | Cuándo | Detalles |
|---|---|---|
| `outbound.mark_sent` | El operador marca como enviado un envío `unknown`. | |
| `outbound.resend` | El operador autoriza reenviar con riesgo de duplicado. | |
| `outbound.discard` | El operador descarta un envío `unknown`: pasa al estado final `discarded` y no se reenvía (ADR-031). | |
| `outbound.resend_bulk_start` | Histórica (reenvío en bloque, retirado por el ADR-031): se escribía al iniciar un reenvío en bloque. | Solo el número de mensajes seleccionados. |
| `outbound.resend_bulk` | Histórica (reenvío en bloque, retirado por el ADR-031): reenvío en bloque de mensajes fallidos, sin confirmar o caducados. | Solo cifras: seleccionados, reenviados y omitidos; ni ids ni datos personales. |
| `job.retry` | El operador reintenta un trabajo fallido idempotente. | |

Ver [envíos unknown](../incidencias/envios-unknown.md).

### Incidencias y actividad

| Acción | Cuándo |
|---|---|
| `incident.review` | Una persona pulsa «Lo he revisado» en una incidencia de tipo evento: se cierra y guarda su marca de revisión (ADR-031, ver [alertas](alertas.md)). Detalles: la clave (`kind`) y el número de casos (`cases`). |
| `alert.resolve` | Histórica (retirada por el ADR-031, la sustituye `incident.review`): una persona resolvía una alerta manual. |
| `activity.view` | Se abre el contenido de un mensaje o evento en Actividad. |

### Datos y consola SQL (`data.*`)

| Acción | Cuándo | Detalles |
|---|---|---|
| `data.query` | Se ejecuta una consulta en la consola SQL. Se anota **antes** de ejecutarla. | `sql` |
| `data.table` | Se consulta una tabla del catálogo de datos. Se anota antes de leer. Las tablas de `SENSITIVE_TABLES` no muestran filas y las columnas con payloads o textos libres salen como `<oculto>`. | `table` |

`audit_event` está en `SENSITIVE_TABLES`: contiene el SQL de la consola (con sus literales), así que se lee solo desde la pantalla Logs, nunca desde la consola SQL.

### Conjuntos de datos

| Acción | Cuándo | Detalles |
|---|---|---|
| `dataset.import` | Se importa un dataset a un negocio (copia de una entrada de la biblioteca). | `name`, `version`, `comment` |
| `dataset_library.push` | Se sube una versión a la biblioteca (`dataset_library push`). Sin `tenant_id`. | `version`, `comment` |

Ver [horarios de bus](../procedimientos/horarios-bus.md).

### Demo y acceso al panel

| Acción | Cuándo |
|---|---|
| `demo_invite.create`, `demo_invite.revoke` | Se crea o se revoca una invitación de demo. |
| `auth.login` | Inicio de sesión correcto en el panel. |
| `auth.login_failed` | Contraseña o código TOTP incorrectos. |
| `auth.step_up` | Reautenticación con un código TOTP nuevo antes de una acción destructiva (borrar, olvidar, exportar, secretos, activar, rollback); vale 5 minutos. |
| `auth.step_up_failed` | Código TOTP incorrecto o reutilizado en la reautenticación. |
| `auth.step_up_blocked` | Reautenticación bloqueada por demasiados fallos (comparte el límite del login). |
| `auth.login_blocked` | Intento bloqueado por demasiados fallos (`scope`: `ip` o `user`). Como mucho una fila por ventana de bloqueo (15 min) y usuario (o dirección, en el ámbito `ip`). El actor es `login:<usuario>`, con el usuario recortado a 64 caracteres, para que un nombre escrito en el formulario no pueda hacerse pasar por un actor real. |
| `panel_user.create`, `panel_user.set_password`, `panel_user.reset_totp` | Alta de usuario, cambio de contraseña o reinicio del TOTP con `panel_user` (actor `command:panel_user`). Los dos últimos cierran las sesiones activas del usuario y anotan cuántas (`sessions_revoked`). |

## Dónde está el código

- `apps/backend/src/autobot/ops/audit.py` (`FORBIDDEN_KEYS`, `record`, `record_tenant`).
- `apps/backend/src/autobot/tenancy/store/` (acciones de configuración y secretos),
  `autobot/ops/actions.py` y `autobot/ops/tenant_actions.py` (operador),
  `autobot/panel/` (servicios y routers), `autobot/management/commands/`.
- Prueba de coherencia: `apps/backend/tests/repo/test_docs.py` exige que cada acción usada en
  el código esté en esta página.
