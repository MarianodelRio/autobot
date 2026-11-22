# Evaluación de riesgos, EIPD y DPD

Evaluación documentada de los riesgos para las personas que atiende Autobot (art. 24 y 32 RGPD), conclusión razonada sobre si hace falta una evaluación de impacto (EIPD, art. 35) y un delegado de protección de datos (DPD, art. 37), y cómo se mitiga la posible entrada de categorías especiales en texto libre. Léela al cambiar el producto (un pack, un proveedor, IA) y al menos una vez al año.

!!! warning "No es asesoramiento jurídico"
    Conclusiones de trabajo del equipo, **pendientes de revisión por abogado**. Se basan en el estado del código a 2026-11-22. Si cambian los hechos (escala, IA, datos de salud), la conclusión debe rehacerse.

## Descripción del tratamiento evaluado

Bots de WhatsApp y Telegram que atienden a los clientes de pequeños negocios: guardan identificador de contacto, nombre, mensajes y reservas; los mensajes se vacían a los 30 días y los contactos caducan a los 12 meses de inactividad. No hay perfiles, ni decisiones automatizadas con efectos jurídicos, ni IA generativa: las respuestas salen de una máquina de estados y de datos del negocio. Ver [registro](registro-de-actividades.md).

## Riesgos identificados

Escala: probabilidad y gravedad Baja/Media/Alta. Riesgo residual tras las medidas existentes.

| # | Riesgo | Prob. | Grav. | Medidas existentes | Residual | Acción pendiente |
|---|---|---|---|---|---|---|
| R1 | Acceso de un negocio a datos de otro | Baja | Alta | RLS forzada, `tenant_tx`, tests de aislamiento, roles separados ([Tenants y RLS](../arquitectura/tenants-y-rls.md)) | Bajo | |
| R2 | Compromiso del panel o de la clave de operación | Baja | Alta | Solo túnel SSH, contraseña y TOTP, límite de intentos, auditoría | Medio | Plan de brechas ([brechas](brechas-de-seguridad.md)); revisión periódica de accesos |
| R3 | Fuga de secretos de canal (toma de control del bot) | Baja | Alta | Cifrado Fernet, nunca en logs, rotación sin parada ([rotar secretos](../procedimientos/rotar-secretos.md)) | Bajo | |
| R4 | Conservación excesiva por no estar activa la limpieza | **Alta hoy** | Media | `RETENTION_CLEANUP_ENABLED=false` por defecto | **Alto hasta activarla** | **Activarla antes del primer cliente** ([checklist](checklist-lanzamiento.md)) |
| R5 | Datos en backups tras un borrado | Media | Baja | Retención 7/4/6; copias cifradas | Medio | Reaplicar supresiones tras restaurar; informar a la persona |
| R6 | Categorías especiales en texto libre (p. ej. salud en una peluquería) | Media | Media | Payload vaciado a 30 días; Sentry y logs sin texto; no se pide | Medio | Ver sección siguiente |
| R7 | Cuenta gratuita de Google del negocio (sin DPA) | Alta si aplica | Media | Acceso limitado al calendario concreto | Medio | Comunicar y documentar ([roles](roles-y-tratamientos.md)) |
| R8 | Transferencia a EE. UU. si cae el DPF | Baja | Media | DPF y SCC; Sentry opcional y sin PII | Bajo | Plan B ([subencargados](subencargados.md)) |
| R9 | Mensaje enviado a la persona equivocada o repetido | Baja | Media | Idempotencia; no reintento ciego de `unknown` | Bajo | |
| R10 | Suplantación en la demo o uso por no invitados | Media | Baja | Lista cerrada, códigos de invitación, vaciado de payload de extraños | Bajo | |
| R11 | Mensajes proactivos sin base o sin baja | Media | Media | `baja` inmediata, recordatorios solo de servicio | Medio | Opt-in documentado ([otras normas](otras-normas.md)) |
| R12 | Pérdida de disponibilidad o de datos | Baja | Media | Backups diarios, simulacro de restauración, latido externo | Bajo | Elegir proveedor de backups |

## ¿Hace falta una EIPD?

El art. 35 exige EIPD cuando es probable un **alto riesgo**; la AEPD publica la [lista de tratamientos que la requieren (art. 35.4)](https://www.aepd.es/documento/listas-dpia-es-35-4.pdf), que concreta los criterios de las directrices del grupo del art. 29/EDPB: evaluación o puntuación, decisiones automatizadas con efectos jurídicos, observación sistemática, datos sensibles, gran escala, cruce de conjuntos de datos, personas vulnerables, uso innovador de tecnología, impedir el ejercicio de derechos o el acceso a un servicio.

| Criterio | ¿Aplica hoy? | Razón |
|---|---|---|
| Evaluación o perfiles | No | No se puntúa ni perfila a nadie |
| Decisiones automatizadas con efectos jurídicos | No | Reservar o consultar horarios no tiene efectos jurídicos significativos |
| Observación sistemática | No | |
| Datos sensibles o de naturaleza muy personal | **No intencionalmente**; posible incidental en texto libre | Ver mitigación; el bot no los pide |
| Gran escala | No | Pocos negocios pequeños, volumen reducido |
| Cruce de conjuntos de datos | No | Cada negocio aislado por RLS |
| Personas vulnerables | No específicamente | `bus` podría atender a personas mayores o menores; revisar |
| Tecnología innovadora | No | Mensajería y reglas; **si se añade IA, sí hay que reevaluar** |
| Impedir derechos o acceso a servicio | No | |

**Conclusión:** con el diseño actual **no se alcanza el umbral que obliga a una EIPD** (a lo sumo coincide un criterio débil, datos sensibles incidentales, y las directrices piden normalmente dos o más). Esta página queda como **evaluación documentada** (art. 24.1) y como razonamiento a presentar a la AEPD. Debe **rehacerse y, probablemente, hacerse una EIPD completa** si: se incorpora IA o procesamiento de lenguaje con terceros; se piden o guardan datos de salud; se segmenta o perfila a clientes; crece el volumen a escala; un cliente trata personas vulnerables (por ejemplo `bus` con colegios); o un cliente la exige. El abogado debe confirmar esta conclusión; cada negocio, como responsable, hace la suya y puede apoyarse en esta.

## ¿Hace falta un DPD?

El art. 37 RGPD y el art. 34 LOPDGDD obligan a designar DPD a autoridades públicas, a quienes hagan seguimiento regular y sistemático a gran escala, o traten a gran escala categorías especiales; y la LOPDGDD lista además ciertas entidades (centros sanitarios, entidades financieras, etc.).

**Conclusión:** **no es obligatorio hoy**: Autobot no hace seguimiento sistemático a gran escala ni trata categorías especiales a gran escala, y no es una de las entidades de la lista. Se recomienda **designar un punto de contacto de privacidad** (`[EMAIL DE PRIVACIDAD]`) y **revisar la decisión** si: crece el número de negocios o personas, hay IA, se tratan datos de salud, un cliente es una entidad del art. 34 LOPDGDD o una administración pública (`bus` municipal). El abogado debe confirmarlo, y si un cliente lo exige contractualmente, valorar un DPD externo.

## Categorías especiales en texto libre

El bot de peluquería pide un nombre y un servicio, pero una persona puede escribir «tengo dermatitis, ¿puedes cuidar la zona?». Eso es dato de salud (art. 9). La plataforma no puede impedirlo del todo, pero reduce el riesgo:

| Medida | Estado |
|---|---|
| El bot no pregunta por salud ni ofrece campos libres de notas médicas | Hecho (diseño actual; los pasos esperan nombre y elecciones de lista) |
| Contenido de mensajes vaciado a los 30 días (entrantes y salientes); fila a los 90 días / 12 meses | Hecho en código, **efectivo solo con la limpieza activa** |
| No se envía texto a logs ni a Sentry | Hecho |
| Aviso en la primera capa: «no escribas datos de salud» | Propuesto en los [textos modelo](informacion-al-interesado.md); pendiente de implementar |
| Cláusula del contrato: el Responsable no usa el bot para recoger categorías especiales; si entran, se tratan como mensaje, sin otro fin | Hecho en la [plantilla](contrato-de-encargado.md) (cláusula 7.2) |
| Al detectar un dato sensible, el operador puede borrar el contacto (`contact_forget`) si el negocio lo pide | Hecho (procedimiento de [derechos](derechos-de-los-interesados.md)) |
| Evitar el nombre en el evento de Calendar más allá de lo necesario | Pendiente de evaluar (cambio de producto) |
| Si un cliente necesita tratar salud (clínica, fisioterapia…), no usar este tratamiento sin nueva evaluación y EIPD | Regla de decisión: **no activar** esos negocios sin revisión |

## Revisión

| Fecha | Cambio | Resultado |
|---|---|---|
| 2026-11-22 | Primera evaluación | Sin EIPD ni DPD obligatorios; riesgo alto hasta activar la retención |

## Relacionado

[Registro de actividades](registro-de-actividades.md), [Seguridad y secretos](../arquitectura/seguridad-y-secretos.md), [Tenants y RLS](../arquitectura/tenants-y-rls.md), [Brechas](brechas-de-seguridad.md).
