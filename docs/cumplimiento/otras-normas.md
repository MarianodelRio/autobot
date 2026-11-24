# Otras obligaciones legales y de plataforma

Lista de comprobación de normas y políticas distintas del RGPD que afectan a Autobot: comercio electrónico, atención a la clientela, inteligencia artificial, políticas de Meta, Telegram y Google, portabilidad de servicios en la nube, facturación y otras. Léela al preparar el lanzamiento y cuando cambie un pack o un proveedor. Cada punto lleva su estado.

!!! warning "No es asesoramiento jurídico"
    Resumen técnico de obligaciones, con enlaces a fuentes oficiales consultadas el 2026-11-22 (las normas y políticas cambian). Los puntos marcados **pendiente de abogado** no deben darse por cumplidos sin su revisión.

Estados: **hecho** (existe y se verifica en el repo), **pendiente** (por hacer, lo puede hacer el equipo), **pendiente de abogado** (requiere criterio jurídico).

## 1. Comercio electrónico y comunicaciones comerciales

[LSSI, Ley 34/2002](https://www.boe.es/buscar/act.php?id=BOE-A-2002-13758).

| Punto | Detalle | Estado |
|---|---|---|
| Aviso legal (art. 10) | La web de la plataforma debe mostrar titular, NIF, domicilio, contacto, registro mercantil si procede | Pendiente (`[TITULAR]`, `[NIF]`, `[DOMICILIO]`); no hay web aún |
| Recordatorios de servicio | Un recordatorio de una cita ya reservada es comunicación de servicio, no comercial; no requiere consentimiento adicional, pero debe poder pararse | Pendiente: `reminders_enabled` desactivado por defecto; la orden `baja` se retiró ([ADR-028](../arquitectura/adr/ADR-028-aviso-en-una-linea-sin-persona-ni-baja.md)) y hay que decidir cómo se para antes de activarlos |
| Comunicaciones comerciales (art. 21) | Prohibido enviar publicidad por medios electrónicos sin consentimiento previo y expreso (salvo cliente actual con productos similares y opción de oposición) | Pendiente: el bot no envía promociones; si un negocio las pide, exigir opt-in y registro del consentimiento |
| Identificar la publicidad (art. 20) | Si hay promociones, que se identifiquen como tales | Pendiente (solo si se ofrecen) |
| Cookies/rastreo | Si la web de la plataforma usa cookies no técnicas (art. 22.2) | Pendiente de comprobar al publicar la web |
| Contratación en línea (art. 27) | Información previa si se contrata por web | Pendiente de abogado |

## 2. Atención a la clientela

[Ley 10/2025, de 26 de diciembre, de servicios de atención a la clientela (BOE-A-2025-26698)](https://www.boe.es/buscar/act.php?id=BOE-A-2025-26698).

| Punto | Detalle | Estado |
|---|---|---|
| Plazo de adaptación | Hasta el **28 de diciembre de 2026** | Pendiente: dentro de plazo hoy |
| Atención humana | Las empresas obligadas deben ofrecer atención por una persona cuando se pida; un bot no puede ser el único canal | Pendiente de abogado: el bot no tiene orden `PERSONA` ([ADR-028](../arquitectura/adr/ADR-028-aviso-en-una-linea-sin-persona-ni-baja.md)); la salida a una persona es el teléfono del negocio (`contact_phone`: en `bus`, en «ℹ️ Información»; en `salon`, en el menú) |
| Alcance | Depende del tamaño y del sector del **negocio** (cliente), no de la plataforma | Pendiente de abogado |
| Pack `bus` | El transporte es servicio básico en el ámbito de la ley: **revisar con abogado a cada cliente de `bus`** antes del alta | Pendiente de abogado |

## 3. Inteligencia artificial

[Reglamento (UE) 2024/1689](https://eur-lex.europa.eu/eli/reg/2024/1689/oj), art. 50 (transparencia).

| Punto | Detalle | Estado |
|---|---|---|
| Sin IA hoy | Las respuestas salen de una máquina de estados; no hay modelo de lenguaje | Hecho (verificado en el diseño) |
| Si se añade IA que interactúe con personas | Informar de que interactúan con un sistema de IA (art. 50.1), etiquetar contenido generado; reevaluar [EIPD](evaluacion-de-riesgos.md) y DPD; cambiar la información al interesado | Pendiente (condicional); cualquier cambio de arquitectura necesita ADR |
| Uso de datos de Telegram y WhatsApp para IA | Prohibido sin las condiciones de cada plataforma (ver 4 y 5) | Hecho (no se usa) |

## 4. Políticas de WhatsApp Business

[Políticas de WhatsApp Business](https://business.whatsapp.com/policy) y términos de la solución de negocio de WhatsApp.

| Punto | Detalle | Estado |
|---|---|---|
| Opt-in | Para mensajes iniciados por la empresa (plantillas), la persona debe haber dado su consentimiento previo y claro | Pendiente: el recordatorio de una cita reservada necesita opt-in documentado en la reserva |
| Ventana de 24 horas | Fuera de la ventana desde el último mensaje del usuario solo se pueden enviar plantillas aprobadas | Hecho en el diseño del canal (ver [canales](../arquitectura/canales.md)); verificar al activar recordatorios |
| Plantillas | Aprobación previa; categoría adecuada (utilidad frente a marketing) | Pendiente al definir los recordatorios por WhatsApp |
| Chatbots de IA de propósito general | Prohibidos como servicio principal desde el 15-01-2026 | Hecho: los bots son de propósito concreto (citas, horarios) y sin IA |
| Mensaje de baja | Permitir dejar de recibir mensajes | Pendiente: la orden `baja` se retiró ([ADR-028](../arquitectura/adr/ADR-028-aviso-en-una-linea-sin-persona-ni-baja.md)); decidir antes de enviar plantillas |
| Cuenta y verificación | Cuenta WhatsApp Business, número, verificación del negocio | Pendiente por cliente (decisión 1 de [roles](roles-y-tratamientos.md)); ver [alta de WhatsApp](../procedimientos/alta-whatsapp-meta.md) |

## 5. Telegram

[Términos para desarrolladores de bots](https://telegram.org/tos/bot-developers).

| Punto | Detalle | Estado |
|---|---|---|
| Política de privacidad obligatoria | Todo bot debe estar sujeto a una política accesible; política propia en @BotFather si la estándar no basta | Pendiente ([información al interesado](informacion-al-interesado.md#4-telegram-politica-en-botfather)) |
| Datos y IA | Prohibido usar los datos para construir conjuntos de datos, modelos de ML o productos de IA | Hecho (no se hace) |
| Minimización | No recoger más de lo esencial | Hecho (diseño) |
| Brechas | Remediar de inmediato fugas y brechas | Hecho en el [procedimiento](brechas-de-seguridad.md) |

## 6. Google

| Punto | Detalle | Estado |
|---|---|---|
| [Política de datos de usuario de las API de Google](https://developers.google.com/terms/api-services-user-data-policy) | Uso limitado, transparencia, sin transferir ni vender los datos | Pendiente de revisar al ir a producción |
| Verificación OAuth | Solo si se usan alcances sensibles con OAuth de usuario. Hoy el acceso es por **cuenta de servicio** compartida por el negocio (`google_sa.json`), sin OAuth de usuario | Pendiente de comprobar si Google exige verificación en el modelo final |
| Cuenta gratuita sin DPA | Riesgo a comunicar al negocio | Pendiente ([roles](roles-y-tratamientos.md)) |

## 7. Reglamento de Datos y cambio de proveedor

[Reglamento (UE) 2023/2854](https://eur-lex.europa.eu/eli/reg/2023/2854/oj) (Reglamento de Datos), capítulo sobre cambio entre servicios de tratamiento de datos (incluido SaaS).

| Punto | Detalle | Estado |
|---|---|---|
| Derecho a cambiar de proveedor | Preaviso máximo de **2 meses**; el contrato debe prever exportación de los datos y activos digitales | Pendiente de abogado: reflejarlo en el contrato de servicio |
| Exportación | Datos exportables (`tenant_data_export` y biblioteca de datasets) | Hecho (técnicamente) |
| Tasas de cambio | Sin tarifas de cambio desde el **12-01-2027** | Pendiente: no cobrar exportación; reflejarlo en las condiciones |

## 8. Facturación

| Punto | Detalle | Estado |
|---|---|---|
| VeriFactu (RRSIF) | Obligatorio para sociedades desde el **1-01-2027** y para el resto desde el **1-07-2027** según el RDL 15/2025 | Pendiente: elegir software de facturación conforme; **la plataforma no factura** |
| Factura electrónica B2B (Ley 18/2022 «Crea y crece») | Entre empresas, con formato estructurado; plazos según reglamento | Pendiente de abogado/gestor |

## 9. Accesibilidad y seguridad de redes

| Punto | Detalle | Estado |
|---|---|---|
| Accesibilidad (Ley 11/2023, transposición de la Directiva 2019/882) | Servicios de comercio electrónico y comunicaciones: **microempresas de servicios exentas**; la plataforma sería microempresa | Pendiente de abogado (confirmar encaje) |
| NIS2 ([Directiva 2022/2555](https://eur-lex.europa.eu/eli/dir/2022/2555/oj)) | No aplica por tamaño mientras no se llegue a mediana empresa | Hecho (comprobado hoy); revisar si crece |

## 10. Pack `bus`

| Punto | Detalle | Estado |
|---|---|---|
| Aviso de horarios orientativos | El bot debe decir que los horarios son orientativos y remitir a la fuente oficial | Pendiente: añadir al texto del pack (cambio de código) |
| Licencias de los datos de horarios | Los datasets de horarios proceden del cliente o de fuentes públicas; comprobar su licencia (por ejemplo datos abiertos de transporte) antes de reutilizarlos | Pendiente |
| Ley 10/2025 | Ver sección 2 | Pendiente de abogado |
| Servicio público | Si el cliente es una administración, cambia el encargo | Pendiente de abogado |

## Dónde está el código

Canales y límites: `apps/backend/src/autobot/channels/`; supresión de proactivos con `opt_out`: `apps/backend/src/autobot/runtime/process.py`; retención: `apps/backend/src/autobot/runtime/retention.py`.

## Relacionado

[Roles y tratamientos](roles-y-tratamientos.md), [Información al interesado](informacion-al-interesado.md), [Checklist de lanzamiento](checklist-lanzamiento.md), [Canales](../arquitectura/canales.md), [Pack bus](../referencia/packs/bus.md).
