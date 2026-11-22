# Subencargados y transferencias internacionales

Lista de proveedores que intervienen en los tratamientos de la plataforma, con su ubicación y garantías, y estado de las transferencias fuera del Espacio Económico Europeo. Léela al contratar o cambiar un proveedor y para preparar el Anexo III del [contrato de encargado](contrato-de-encargado.md). Cualquier cambio exige avisar a los negocios con 30 días de preaviso.

!!! warning "No es asesoramiento jurídico"
    Documento de trabajo; los datos de proveedores por decidir están como marcadores. Las garantías de transferencia y su vigencia deben **revisarse con abogado** antes de firmar con el primer cliente.

## Lista

| Proveedor | Papel | Qué trata | Ubicación | Garantía | Estado |
|---|---|---|---|---|---|
| `[PROVEEDOR VPS]` (por decidir, en la UE) | Subencargado | Todo: base de datos, aplicación, logs | `[PAÍS UE]` | DPA del proveedor; ubicación UE | Pendiente de elegir |
| `[ALMACENAMIENTO DE BACKUPS]` (por decidir, otro proveedor, en la UE) | Subencargado | Copias cifradas con restic (ver [restaurar](../procedimientos/restaurar.md)) | `[PAÍS UE]` | DPA; datos cifrados por la plataforma antes de salir | Pendiente de elegir |
| Meta Platforms Ireland / WhatsApp, WhatsApp Cloud API | Encargado (según [términos de tratamiento](https://www.facebook.com/legal/terms/dataprocessing)) de quien sea titular de la cuenta WABA; responsable independiente de lo que trata para sí | Mensajes, teléfonos, estados de entrega | UE y EE. UU. | Términos de tratamiento de datos de Meta; SCC y DPF `[VERIFICAR VIGENTES]` | Ver decisión 1 en [roles](roles-y-tratamientos.md) |
| Google (Google Calendar API) | Encargado solo con Workspace; con cuenta gratuita, términos de consumidor | Nombre y teléfono en el evento | Global | [DPA de Workspace](https://workspace.google.com/terms/dpa_terms.html) si aplica | Riesgo a comunicar al negocio |
| Telegram | **Tercero, no subencargado**: responsable independiente | Mensajes del bot y datos de perfil | Dubái (EAU) y Virgin Islands Británicas (BVI) según su [política](https://telegram.org/privacy) | Ninguna decisión de adecuación para esos países; ver sección de transferencias | Riesgo a comunicar |
| Sentry (opcional) | Subencargado | Errores **sin** datos personales (identificadores, pilas, mensaje redactado) | EE. UU. | [DPA de Sentry](https://sentry.io/legal/dpa/): DPF y cláusulas contractuales tipo | Opcional (`SENTRY_DSN`) |
| Healthchecks.io | Subencargado de baja sensibilidad | Un ping; sin datos personales | `[CONFIRMAR]` (ver su [política](https://healthchecks.io/privacy/)) | Sin datos personales | En uso previsto |
| GitHub / GHCR | Proveedor de desarrollo | Código fuente e imágenes; **nunca datos de clientes** (`var/` ignorado; guard `forbidden-terms` en CI) | EE. UU. | No aplica por no haber datos personales de clientes finales; la cuenta de desarrollador es otro tratamiento | Ya en uso |

!!! note "Sentry: prohibido enviar categorías especiales"
    Aunque `before_send` ya descarta peticiones, variables locales y texto de excepciones, queda **prohibido** enviar a Sentry (o a cualquier proveedor de telemetría) texto de usuarios, categorías especiales o identificadores personales. Cualquier cambio que amplíe lo que se envía requiere revisar esta página y el [registro](registro-de-actividades.md).

## Transferencias internacionales

Mecanismo de transferencia por proveedor (art. 44 y siguientes RGPD):

| Destino | Mecanismo | Notas |
|---|---|---|
| EE. UU. (Meta, Google, Sentry, GitHub) | Marco de Privacidad de Datos UE-EE. UU. (**DPF**) si el importador está certificado; si no, cláusulas contractuales tipo (SCC) | Comprobar la certificación en la [lista oficial del DPF](https://www.dataprivacyframework.gov/) y que el DPA lo recoge |
| EAU y BVI (entidades de Telegram) | No hay decisión de adecuación; Telegram actúa como responsable independiente bajo su política | La plataforma **no transfiere** datos a Telegram: es la propia persona usuaria quien usa Telegram. Aun así el negocio debe informar de ello ([información al interesado](informacion-al-interesado.md)) |

### Plan B ante la caída del DPF

El DPF se apoya en la decisión de adecuación de la Comisión de 2023. El Tribunal General la confirmó en septiembre de 2025 (asunto T-553/23), pero hay **recurso de casación pendiente ante el Tribunal de Justicia (C-703/25 P)**. Si el Tribunal anulara la decisión:

1. Confirmar que cada proveedor de EE. UU. ofrece **cláusulas contractuales tipo** en su DPA (Meta, Google y Sentry las ofrecen en sus términos; verificar la versión).
2. Documentar una evaluación de impacto de la transferencia (TIA) por proveedor, con medidas complementarias (cifrado, minimización: Sentry ya no recibe datos personales).
3. Avisar a los negocios con el preaviso del contrato si cambia la lista o las garantías.
4. Si algún proveedor no puede ofrecer garantías, sustituirlo o desactivarlo (Sentry es opcional).

Estado: `[PENDIENTE DE REVISAR CON ABOGADO ANTES DEL PRIMER CLIENTE]`. Seguir las [notas del EDPB](https://www.edpb.europa.eu) y de la Comisión sobre el DPF.

## Cómo añadir o cambiar un proveedor

1. Evalúa si recibirá datos personales; si no, anótalo (como GitHub) y no es subencargado.
2. Pide su DPA, ubicación y mecanismo de transferencia; añádelo a esta tabla, al Anexo III del contrato y al [registro](registro-de-actividades.md).
3. Comunica a los negocios con 30 días de preaviso (cláusula 7.7 del contrato).
4. Si es un proveedor de infraestructura, es un cambio en la infraestructura del servidor: requiere aprobación humana (`CLAUDE.md`).

## Relacionado

[Contrato de encargado](contrato-de-encargado.md), [Roles y tratamientos](roles-y-tratamientos.md), [Observabilidad](../arquitectura/observabilidad.md), [Servidor](../procedimientos/servidor.md).
