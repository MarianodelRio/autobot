# Roles y tratamientos

Reparto de roles del RGPD entre el negocio cliente, la plataforma y los terceros, tratamiento por tratamiento. Léela para saber con qué papel actúa Autobot en cada caso, porque de ahí salen el contrato, el registro de actividades y a quién se dirige cada persona. Antes de usarla con un cliente, revisa con abogado las conclusiones de roles (sección «Qué debe revisar un abogado»).

!!! warning "No es asesoramiento jurídico"
    Calificar a cada parte como responsable, encargado o corresponsable es una cuestión jurídica que depende de los hechos (quién decide los fines y los medios; [Directrices 07/2020 del EDPB](https://www.edpb.europa.eu/our-work-tools/our-documents/guidelines/guidelines-072020-concepts-controller-and-processor-gdpr_en)). Esta página recoge la hipótesis de trabajo y las decisiones pendientes. Pendiente de revisión por abogado.

## Resumen

| Tratamiento | Interesados | Responsable | Encargado | Base documental |
|---|---|---|---|---|
| Atención por bot a los clientes de un negocio (contactos, mensajes, reservas, avisos) | Clientes finales del negocio | El negocio | La plataforma (`[TITULAR]`) | Contrato de encargo ([plantilla](contrato-de-encargado.md)) |
| Bot de demo (selector, sesiones, invitaciones, mensajes de prueba) | Personas invitadas a la demo | La plataforma | Meta y Telegram según el caso | Información al interesado de la plataforma |
| Bot de avisos al dueño (vínculo chat-negocio, avisos) | Dueños y personas autorizadas del negocio | La plataforma, para el vínculo y el canal; el negocio, para el contenido de los avisos sobre sus clientes | Ver nota | Contrato + política de la plataforma |
| Operadores del panel (usuarios, TOTP, auditoría) | Personas operadoras | La plataforma | Proveedor VPS | Política interna |
| Facturación y relación comercial con el negocio | Contacto y representante del negocio | La plataforma | Asesoría/gestor, si lo hay `[POR DECIDIR]` | Política de la plataforma |
| Logs técnicos, backups, monitorización | Los de los tratamientos anteriores | Según el tratamiento de origen | Subencargados de la plataforma | [Subencargados](subencargados.md) |

La plataforma, en el tratamiento de los clientes finales, **solo actúa bajo instrucciones documentadas del negocio** (art. 28.3.a RGPD): conserva, responde y avisa según la configuración que publica el negocio en su ficha. Si decidiera por su cuenta fines propios (por ejemplo, analítica para producto con esos datos, o entrenar modelos), pasaría a ser responsable de ese uso: hoy no se hace y debe seguir así.

## El negocio: responsable de los datos de sus clientes

El negocio (peluquería, empresa de autobuses…) decide para qué quiere hablar con sus clientes y por qué canal, y es quien tiene la relación con ellos. Por tanto:

- Es el **responsable**: elige base jurídica, informa a sus clientes (art. 13), atiende los derechos (art. 15 a 22) y notifica las brechas a la AEPD ([brechas](brechas-de-seguridad.md)).
- Debe incluir el bot en **su propio registro de actividades** y en su política de privacidad ([modelo](informacion-al-interesado.md)).
- Es dueño del **calendario de Google** donde se guardan las citas y de su cuenta de Google.
- La plataforma le entrega el contrato de encargo antes del alta; **sin contrato firmado no se activa el canal real** (ver [checklist](checklist-lanzamiento.md)).

## La plataforma como encargada

Datos que trata por cuenta del negocio (detalle en el [registro](registro-de-actividades.md)): identificador de contacto (teléfono, BSUID o id de Telegram), nombre de perfil, nombre dado en una reserva, mensajes recibidos y enviados, estado de la conversación, avisos al dueño, métricas sin identificadores y el contenido que la plataforma escribe en el Google Calendar del negocio (nombre y teléfono en la descripción del evento).

Obligaciones que asume (resumidas; el contrato las detalla): tratar solo según instrucciones, confidencialidad, medidas de seguridad ([medidas](../arquitectura/seguridad-y-secretos.md)), subencargados con autorización, asistir en derechos y brechas, y devolver o suprimir los datos al terminar (máximo 30 días desde la baja, ver [Retención y RGPD](../procedimientos/retencion-rgpd.md)).

## La plataforma como responsable

La plataforma decide los fines y medios de:

- **Demo.** Personas invitadas (lista cerrada o código de invitación): identificador de Telegram o WhatsApp, sesión del selector, eventos de entrada (se vacía el contenido de quien no tiene acceso), invitaciones y concesiones. Base probable: medidas precontractuales a petición del interesado o interés legítimo (art. 6.1.b/f), pendiente de revisión. Plazos: eventos 7 días, sesiones 30 días, contactos de un negocio de demo 30 días.
- **Dueños.** El `chat_id` de Telegram vinculado a un negocio (`owner_link`), el hash de su invitación y los eventos del bot de avisos. Base: ejecución del contrato con el negocio (6.1.b) para el vínculo. Los avisos que mencionan a clientes finales (por ejemplo, «cita nueva de X») son contenido de los clientes del negocio: ahí la plataforma sigue siendo encargada.
- **Operadores.** Usuarios del panel, contraseña con hash, TOTP, y `audit_event` (actor, acción, objeto, un año). Base: interés legítimo en seguridad y trazabilidad (6.1.f) y obligación de seguridad (art. 32).
- **Facturación y comercial.** Datos de contacto del negocio y de su representante, contrato, facturas. Base: contrato (6.1.b) y obligaciones legales (6.1.c). Plazos: los legales fiscales y mercantiles `[CONFIRMAR CON GESTOR]`.

## Terceros

| Tercero | Papel | Qué recibe | Cómo se documenta |
|---|---|---|---|
| **Meta** (WhatsApp Cloud API) | **Encargado** del negocio (o de la plataforma, según de quién sea la cuenta; ver decisión 1) para el tratamiento de los mensajes de la Cloud API, según los términos de tratamiento de datos de Meta; responsable independiente de lo que trata para sus propios fines | Mensajes, teléfonos, estados de entrega | [Meta Data Processing Terms](https://www.facebook.com/legal/terms/dataprocessing) y [WhatsApp Business](https://business.whatsapp.com/policy) (aceptados en la cuenta de Meta) |
| **Telegram** | **Responsable independiente**: la persona usa Telegram con sus propios términos; el bot es una aplicación de terceros dentro de Telegram. No es subencargado de la plataforma | Mensajes y datos de perfil que la persona envía al bot | [Política de privacidad de Telegram](https://telegram.org/privacy) y [Términos de desarrolladores de bots](https://telegram.org/tos/bot-developers) |
| **Google Calendar** | Con **Google Workspace** del negocio: Google es encargado bajo el [Acuerdo de tratamiento de datos de Workspace](https://workspace.google.com/terms/dpa_terms.html). Con **cuenta gratuita** (Gmail): sin DPA de Workspace, Google actúa bajo sus términos de consumidor | Nombre y teléfono del cliente en la descripción del evento | Ver riesgo siguiente |
| Proveedor VPS, backups, Sentry, Healthchecks, GitHub | Subencargados de la plataforma (Telegram aparte) | Ver lista | [Subencargados](subencargados.md) |

!!! warning "Riesgo a comunicar al negocio: Google Calendar con cuenta gratuita"
    Si el calendario del negocio está en una cuenta gratuita de Google, **no existe un acuerdo de encargo de Google con el negocio** para esos datos. El negocio, como responsable, debe saberlo antes del alta y aceptarlo por escrito (o pasar a Workspace). El bot escribe nombre y teléfono en el evento; la plataforma no puede evitarlo sin cambiar el producto. La comunicación debe constar en el contrato o en la hoja de alta. Pendiente de revisión por abogado.

## Decisiones pendientes

| # | Decisión | Opciones | Efecto | Estado |
|---|---|---|---|---|
| 1 | De quién es la cuenta WhatsApp Business (WABA) de cada negocio | (a) del negocio, con la plataforma como proveedor tecnológico; (b) de la plataforma, que presta el número al negocio | En (a) el negocio acepta directamente los términos de Meta y Meta es su encargado; en (b) la plataforma es la clienta de Meta y asume más responsabilidad y coste. Condiciona el contrato y la facturación de Meta | Pendiente de decidir; ver [Alta de WhatsApp en Meta](../procedimientos/alta-whatsapp-meta.md) |
| 2 | Qué base jurídica y texto de información usa el negocio para recordatorios y avisos | Ejecución del contrato (cita reservada) vs. consentimiento (cualquier promoción) | Condiciona el opt-in y la LSSI art. 21 ([otras normas](otras-normas.md)) | Pendiente de abogado |
| 3 | Plazo de conservación por defecto para clientes finales | 12 meses de inactividad (actual) u otro que fije cada negocio | Es instrucción del responsable; el contrato debe fijarlo | Pendiente de confirmar con el primer cliente |
| 4 | Proveedor VPS y almacenamiento de backups | Proveedor en la UE con DPA | Lista de [subencargados](subencargados.md) y transferencias | Pendiente |
| 5 | ¿Los dueños son interesados con política propia o parte del negocio? | Política de la plataforma para el vínculo | [Información al interesado](informacion-al-interesado.md) | Propuesto |
| 6 | Alcance de `bus`: ¿el cliente es una empresa de transporte o un ayuntamiento/organismo? | Cambia el encargo (¿administración pública?) y la Ley 10/2025 | [Otras normas](otras-normas.md) | Pendiente de abogado |
| 7 | Facturación: asesoría o gestor como encargado | Sí/no | Lista de encargados | Pendiente |

## Qué debe revisar un abogado

- La calificación de Meta como encargado y de Telegram como responsable independiente, y su efecto en el aviso al interesado.
- La viabilidad de operar con calendarios de cuentas gratuitas de Google (decisión 1 y riesgo anterior).
- La base jurídica de la demo y de los dueños.
- Si el pack `bus` convierte al cliente en sujeto obligado por la normativa de atención a la clientela ([otras normas](otras-normas.md)).

## Dónde está el código

Tratamientos y plazos: `apps/backend/src/autobot/runtime/models.py`, `apps/backend/src/autobot/runtime/retention.py`. Secretos y cifrado: `apps/backend/src/autobot/tenancy/crypto.py`.

## Relacionado

[Registro de actividades](registro-de-actividades.md), [Contrato de encargado](contrato-de-encargado.md), [Subencargados](subencargados.md), [Bot de demo](../arquitectura/bot-de-demo.md), [Bot de dueños](../arquitectura/bot-de-duenos.md).
