# Registro de actividades de tratamiento

Registro del art. 30 RGPD de Autobot en sus dos papeles: como **responsable** (apartado 1 del art. 30) y como **encargado** (apartado 2). Está construido a partir del código real (`apps/backend/src/autobot/runtime/models.py` y `apps/backend/src/autobot/runtime/retention.py`). Léelo para saber qué se guarda, por qué y cuánto, y actualízalo cuando se añada un dato o un tratamiento.

!!! warning "No es asesoramiento jurídico"
    Documento de trabajo. Las bases jurídicas y los plazos son la propuesta técnica del equipo; **revisar con abogado** las bases jurídicas de la demo, de los dueños y de la facturación, y el plazo de 12 meses. Los datos del titular quedan como marcadores.

!!! note "La limpieza automática está activada en producción"
    Los plazos de esta página **solo se cumplen con la limpieza nocturna activa**. En producción `compose.prod.yaml` la activa por defecto (`RETENTION_CLEANUP_ENABLED=true`, aprobado el 2026-11-23; `check_prod_config.py` lo comprueba); en local vale `false` y nada caduca salvo los trabajos de la cola (`jobs_cleanup`, 30 días), los logs (31 días) y los backups (restic). Un servidor con `RETENTION_CLEANUP_ENABLED=false` en su `.env` incumpliría este registro y los avisos legales. Ver [Retención y RGPD](../procedimientos/retencion-rgpd.md#limpieza-automatica).

## Datos identificativos

| Campo | Valor |
|---|---|
| Titular / responsable de la plataforma | `[TITULAR]` |
| NIF | `[NIF]` |
| Domicilio | `[DOMICILIO]` |
| Contacto de privacidad | `[EMAIL DE PRIVACIDAD]` |
| Delegado de protección de datos | No designado (ver [evaluación de riesgos](evaluacion-de-riesgos.md)) |
| Última revisión | 2026-11-22 |

## 1. Registro como responsable

| Tratamiento | Finalidad | Base jurídica | Interesados y datos | Destinatarios | Transferencias | Plazo | Medidas |
|---|---|---|---|---|---|---|---|
| **Demo: selector, acceso y sesiones** (`demo_event`, `demo_session`, `demo_access_grant`, `demo_invite`) | Enseñar la plataforma a posibles clientes; controlar quién entra | Medidas precontractuales a petición del interesado / interés legítimo (6.1.b/f) `[abogado]` | Personas invitadas: id de Telegram o WhatsApp (BSUID o teléfono), mensajes de la persona, elección de negocio; invitaciones: nota, creador | Meta o Telegram (canal); proveedor VPS | Según proveedor; ver [subencargados](subencargados.md) | `demo_event` 7 días (el `payload` de quien no tiene acceso se vacía al guardarlo, y en WhatsApp ni se guarda); `demo_session` 30 días desde la última elección; concesiones al caducar; invitaciones revocadas o caducadas, 30 días después | Lista cerrada de personas o códigos de 12 caracteres, límite de intentos, RLS no aplica (tablas de plataforma, ADR-006), tablas sensibles fuera de la consola SQL |
| **Demo: negocios de demostración** (contactos, conversación, avisos de un negocio `demo`) | Conversación de prueba con la lógica real de un pack | Igual que el anterior | Id, nombre de perfil y texto que la persona escribe | Igual; Google Calendar (calendario de demo) | Igual | 30 días (`DEMO_RETENTION_DAYS`) | RLS por `tenant_id`, `tenant_tx` |
| **Dueños: vínculo** (`owner_link`, `owner_event`) | Enviar avisos y atender al dueño por el bot de avisos | Ejecución del contrato con el negocio (6.1.b) | Dueños: `chat_id` de Telegram, fecha de vínculo; invitación (solo sha256, caduca a 7 días) | Telegram | Telegram: ver [subencargados](subencargados.md) | Mientras dure el vínculo; se desvincula con `owner_unlink` o con el borrado del negocio; `owner_event` 7 días | Código de un solo uso, hash, candado por chat con hash, nada de ids en logs |
| **Operadores del panel** (`auth_user`, TOTP, `audit_event`) | Acceso seguro y trazabilidad de operaciones | Interés legítimo y seguridad (6.1.f, art. 32) | Personas operadoras: usuario, hash de contraseña, dispositivo TOTP, IP en límite de intentos, acciones auditadas | Nadie (uso interno); proveedor VPS | No | `audit_event` y `ops_alert`: 1 año (la purga `purge_platform_history` forma parte de la limpieza nocturna); cuentas mientras sean operadores | Túnel SSH, contraseña + TOTP, límite de intentos, CSRF, `FORBIDDEN_KEYS` ([auditoría](../referencia/auditoria.md)) |
| **Facturación y relación comercial** | Contratar, facturar, atender al negocio | Contrato (6.1.b), obligación legal (6.1.c) | Representante y contacto del negocio: nombre, email, teléfono, NIF/domicilio del negocio | Gestoría `[POR DECIDIR]`, Hacienda | No `[CONFIRMAR]` | Los plazos fiscales y mercantiles legales `[CONFIRMAR CON GESTOR]` | Fuera de la plataforma (hoy sin sistema propio) |
| **Logs técnicos** (VictoriaLogs) | Operar y diagnosticar | Interés legítimo (6.1.f) | Ids opacos; teléfonos solo con los 4 últimos dígitos; sin cuerpos de mensaje | Nadie; proveedor VPS | No | **31 días** | `PrivacyFilter`, `redact`, sin puerto publicado |
| **Monitorización de errores** (Sentry, opcional) | Detectar fallos | Interés legítimo (6.1.f) | Identificadores, pilas, mensaje redactado; **sin PII** (`before_send` descarta peticiones, variables locales y texto de excepciones) | Sentry | EE. UU.: DPF y SCC ([subencargados](subencargados.md)) | Según plan de Sentry `[CONFIRMAR]` | `before_send`; prohibido enviar categorías especiales |
| **Latido** (Healthchecks.io) | Avisar si la plataforma deja de funcionar | Interés legítimo (6.1.f) | Ninguno personal (solo el ping) | Healthchecks.io | `[CONFIRMAR UBICACIÓN]` | Según el servicio | Solo se envía una petición sin datos |

## 2. Registro como encargado (por cuenta de cada negocio)

Responsable: **cada negocio cliente**. Categoría de tratamiento: atención automatizada a los clientes del negocio por WhatsApp o Telegram, y reservas en su Google Calendar (pack `salon`) o consulta de horarios (pack `bus`). Los plazos son los de la plataforma por defecto; el negocio puede instruir otros.

| Tratamiento (tabla) | Finalidad | Base jurídica (la fija el responsable) | Interesados y datos | Destinatarios | Transferencias | Plazo | Medidas |
|---|---|---|---|---|---|---|---|
| **Contactos** (`contact`) | Identificar al cliente, recordar su baja (`opt_out`) y a quién enviar avisos | Contrato (reserva) o interés legítimo / consentimiento según el caso | Clientes finales: identificador (teléfono, BSUID o id de Telegram), nombre de perfil, nombre dado en la reserva, `opt_out`, `unreachable`, última actividad | Meta o Telegram (canal) | Ver [subencargados](subencargados.md) | **12 meses de inactividad** (para contactos sin actividad, desde la creación); un contacto con `opt_out` se conserva como supresión mínima (identificador y marca, nombre vaciado) hasta `contact_forget` | RLS (`tenant_isolation`, `readonly_all`), `tenant_tx`, secretos cifrados |
| **Eventos de entrada** (`inbound_event`) | Procesar cada mensaje una sola vez; diagnosticar | Igual | Payload completo del proveedor: teléfono o id, nombre de perfil, texto libre del cliente | Nadie más | No | `payload` y `effect_state` **vaciados a los 30 días; fila borrada a los 90** | RLS; payload fuera de logs y de Sentry |
| **Mensajes salientes** (`outbound_message`) | Enviar y no duplicar respuestas | Igual | Contenido de la respuesta (incluye nombre y datos de la cita), ids de proveedor | Meta o Telegram | Ver [subencargados](subencargados.md) | `payload` vaciado a los **30 días; fila a los 12 meses** (desde la creación) | RLS; idempotencia; sin reintentos ciegos |
| **Conversación** (`conversation`) | Estado del flujo del pack | Igual | Estado del pack (paso, selecciones, nombre en curso) | Nadie | No | Se vacía al superar el tiempo de conversación del pack; se borra con el contacto (12 meses) | RLS |
| **Avisos** (`notification`) | Avisos al dueño y recordatorios | Igual (recordatorios: ver [LSSI](otras-normas.md)) | Texto del aviso (puede nombrar al cliente), destinatario, estado | Telegram (dueño) o canal del cliente | Telegram: ver [subencargados](subencargados.md) | **12 meses** | RLS; el trabajo lleva solo el id |
| **Métricas** (`metric_event`) | Resumen mensual para el dueño | Interés legítimo del negocio | Tipo y valor; **sin teléfono, id de usuario ni texto libre** | Dueño | No | 12 meses | RLS |
| **Google Calendar del negocio** (pack `salon`) | Reservar, mover y cancelar citas | Contrato (reserva) | Nombre y teléfono en la descripción del evento; servicio y hora | Google (calendario del negocio) | Google: ver [subencargados](subencargados.md) | Lo decide el negocio: **la plataforma no borra el calendario** | Cuenta de servicio con acceso al calendario concreto; ver riesgo de cuenta gratuita en [roles](roles-y-tratamientos.md) |
| **Config y datasets del negocio** (`tenant_document_version`, `tenant_dataset_version`) | Servir el bot con su configuración | Contrato | Datos del negocio (no de clientes finales); `bus`: horarios | Nadie | No | Mientras el negocio sea cliente; se borra en la baja (≤ 30 días) | Versionado, sin RLS por diseño (ADR-009) |
| **Secretos de canal** (`tenant_secret`) | Operar el canal del negocio | Contrato | Tokens y secretos (no son datos personales de clientes) | Nadie | No | Hasta la baja | Cifrado Fernet, nunca en claro |
| **Cola de trabajos** (`procrastinate_*`) | Procesar mensajes y envíos | Igual | Solo ids y nombres de tarea | Nadie | No | 30 días (`jobs_cleanup`, no depende de la limpieza) | Argumentos solo con ids |
| **Backups** (restic) | Recuperarse de un desastre | Interés legítimo / obligación de seguridad (art. 32) | Copia cifrada de la base y de ficheros de `.env` y `google_sa.json` | Proveedor de almacenamiento `[POR DECIDIR]` | `[POR DECIDIR, UE]` | **Diario 7, semanal 4, mensual 6** (≈ 6 meses); `pre-migrate.dump` (sin cifrar en disco) máximo 7 días | restic cifrado, almacenamiento de otro proveedor, simulacro de restauración |
| **Logs técnicos** | Operar | Interés legítimo | Ids opacos, teléfonos redactados | Nadie | No | 31 días | `PrivacyFilter` |

!!! note "Qué no sale en esta tabla"
    Todo dato de cliente lleva `tenant_id` y RLS, salvo las tablas de configuración y operación listadas en `CLAUDE.md` (`tenant_document_version`, `tenant_dataset_version`, `tenant_secret`, `audit_event`, `ops_alert`, `demo_session`, `owner_link`). Un borrado de contacto o de negocio **no alcanza** a los backups ni al Calendar del negocio ([derechos](derechos-de-los-interesados.md#que-no-cubre)).

## Mantenimiento del registro

- Revísalo al añadir una tabla con datos personales, un pack, un proveedor o un canal, y al menos cada 12 meses.
- Cada fila nueva debe coincidir con `runtime/retention.py`: si cambia un plazo en el código, cambia aquí y en [Retención y RGPD](../procedimientos/retencion-rgpd.md).
- Cada negocio debe poder pedir su parte del registro (apartado 2) para incorporarla al suyo.

## Dónde está el código

`apps/backend/src/autobot/runtime/models.py` (modelos), `apps/backend/src/autobot/runtime/retention.py` (plazos), `deploy/scripts/backup.sh` (`--keep-daily 7 --keep-weekly 4 --keep-monthly 6`), `deploy/scripts/prune.sh` (`pre-migrate.dump`).

## Relacionado

[Roles y tratamientos](roles-y-tratamientos.md), [Subencargados](subencargados.md), [Retención y RGPD](../procedimientos/retencion-rgpd.md), [Restaurar](../procedimientos/restaurar.md), [Observabilidad](../arquitectura/observabilidad.md).
