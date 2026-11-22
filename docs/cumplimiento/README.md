# Cumplimiento y protección de datos

Documentación legal y de cumplimiento de Autobot: quién es responsable de qué dato, qué se guarda y cuánto tiempo, qué contrato firma el negocio, qué terceros intervienen, qué se dice a las personas atendidas, cómo se atienden sus derechos y qué se hace ante una brecha. Léela antes de dar de alta al primer cliente real y cada vez que cambie un tratamiento (un dato nuevo, un proveedor nuevo, un pack nuevo).

!!! warning "No es asesoramiento jurídico"
    Todo lo de esta sección es documentación técnica y modelos de trabajo redactados a partir del código y de fuentes oficiales. **No constituye asesoramiento jurídico.** Los textos legales (contrato de encargo, políticas de privacidad, avisos) son plantillas **pendientes de revisión por abogado** antes de usarse con terceros. Cada página indica qué partes necesitan esa revisión. Los datos de identificación del titular de la plataforma están como marcadores (`[TITULAR]`, `[NIF]`, `[DOMICILIO]`, `[EMAIL DE PRIVACIDAD]`, `[PROVEEDOR VPS]`…) y no se inventan.

## Páginas

| Página | Para qué sirve |
|---|---|
| [Roles y tratamientos](roles-y-tratamientos.md) | Quién es responsable y quién encargado en cada tratamiento; terceros; decisiones pendientes. |
| [Registro de actividades](registro-de-actividades.md) | RAT del art. 30 RGPD, como responsable y como encargado, con plazos reales del código. |
| [Contrato de encargado](contrato-de-encargado.md) | Plantilla de contrato art. 28.3 RGPD con anexos (medidas, subencargados). |
| [Subencargados](subencargados.md) | Proveedores, ubicación, garantías y transferencias internacionales. |
| [Información al interesado](informacion-al-interesado.md) | Textos por capas para el bot, política modelo del negocio, política de la plataforma y @BotFather. |
| [Derechos de los interesados](derechos-de-los-interesados.md) | Procedimiento operativo y plantillas de respuesta. |
| [Brechas de seguridad](brechas-de-seguridad.md) | Detección, contención, avisos (48 h al negocio, 72 h a la AEPD) y registro. |
| [Evaluación de riesgos](evaluacion-de-riesgos.md) | Riesgos, conclusión sobre EIPD y DPD, categorías especiales en texto libre. |
| [Otras normas](otras-normas.md) | LSSI, atención a la clientela, IA, políticas de Meta/Telegram/Google, Reglamento de Datos, facturación… |
| [Checklist de lanzamiento](checklist-lanzamiento.md) | Bloqueantes antes del primer cliente real. |

## Relación con el resto de la documentación

- Los comandos y plazos técnicos de retención y borrado están en [Retención y RGPD](../procedimientos/retencion-rgpd.md); esta sección los cita y no los duplica.
- Las medidas de seguridad están en [Seguridad y secretos](../arquitectura/seguridad-y-secretos.md); los avisos de incidente en [Incidente de seguridad](../incidencias/incidente-seguridad.md).
- Los backups y su restauración, en [Restaurar](../procedimientos/restaurar.md).

## Fuentes oficiales principales

Enlaces comprobados el 2026-11-22; la normativa y las políticas de los proveedores cambian, así que verifica la versión vigente antes de citarlas a un cliente.

- [RGPD, Reglamento (UE) 2016/679](https://eur-lex.europa.eu/eli/reg/2016/679/oj) (EUR-Lex).
- [Decisión de Ejecución (UE) 2021/915, cláusulas tipo responsable-encargado](https://eur-lex.europa.eu/eli/dec_impl/2021/915/oj) (EUR-Lex).
- [LOPDGDD, Ley Orgánica 3/2018](https://www.boe.es/buscar/act.php?id=BOE-A-2018-16673) (BOE).
- [LSSI, Ley 34/2002](https://www.boe.es/buscar/act.php?id=BOE-A-2002-13758) (BOE).
- [AEPD](https://www.aepd.es), [EDPB](https://www.edpb.europa.eu).
