# Contrato de encargado del tratamiento (plantilla)

Plantilla del contrato que la plataforma firma con cada negocio cliente para cumplir el art. 28.3 RGPD. Se inspira en la estructura de las [cláusulas tipo de la Decisión de Ejecución (UE) 2021/915](https://eur-lex.europa.eu/eli/dec_impl/2021/915/oj) de la Comisión y rellena sus anexos con los hechos reales de Autobot. Léela al preparar el alta de un cliente; los marcadores `[...]` se rellenan por persona, nunca se inventan.

!!! danger "Plantilla pendiente de revisión por abogado"
    Este texto **no está revisado por un abogado** y no debe firmarse ni enviarse a un cliente sin esa revisión. Además: las cláusulas de la Decisión 2021/915 solo ofrecen la presunción de conformidad si se incorporan **sin modificar su texto**; aquí se redactan de forma propia siguiendo su estructura y contenido, así que el abogado debe decidir si se adopta el texto oficial íntegro como cuerpo del contrato (y estos anexos se usan tal cual) o se mantiene una redacción propia. No es asesoramiento jurídico.

## Cómo usar la plantilla

1. Rellena las partes, la fecha y las instrucciones del negocio (plazo de conservación, canal, pack).
2. Adjunta los anexos I a IV; el Anexo III se genera de [Subencargados](subencargados.md) con la lista vigente al firmar.
3. Antes de activar el canal real del negocio, el contrato debe estar firmado (ver [checklist de lanzamiento](checklist-lanzamiento.md)).
4. Conserva el contrato firmado junto con la ficha del negocio. Cada cambio de subencargado se comunica con el preaviso de la cláusula 7.7.

---

## CONTRATO DE ENCARGO DEL TRATAMIENTO DE DATOS PERSONALES

En `[LUGAR]`, a `[FECHA]`.

**De una parte (el «Responsable»):** `[NEGOCIO]`, NIF `[NIF DEL NEGOCIO]`, domicilio `[DOMICILIO DEL NEGOCIO]`, representado por `[REPRESENTANTE]`, contacto de privacidad `[EMAIL DEL NEGOCIO]`.

**De otra parte (el «Encargado»):** `[TITULAR]`, NIF `[NIF]`, domicilio `[DOMICILIO]`, contacto de privacidad `[EMAIL DE PRIVACIDAD]`.

Ambos acuerdan lo siguiente, en el marco del Reglamento (UE) 2016/679 (RGPD) y de la Ley Orgánica 3/2018.

### Sección I. Disposiciones generales

**1. Objeto.** Este contrato regula el tratamiento de datos personales que el Encargado realiza por cuenta del Responsable al prestarle el servicio de atención a sus clientes mediante un bot de mensajería (WhatsApp o Telegram) y, en su caso, la gestión de reservas en el calendario de Google del Responsable o la consulta de horarios (el «Servicio»), descrito en el Anexo I.

**2. Invariabilidad e interpretación.** Los anexos forman parte del contrato. En caso de contradicción entre este contrato y otro acuerdo entre las partes, prevalece este contrato en lo relativo a protección de datos. Se interpretará conforme al RGPD y a la LOPDGDD.

**3. Duración.** El contrato dura lo que dure el Servicio y se extingue con él, sin perjuicio de las obligaciones de la cláusula 7.9 (devolución y supresión).

### Sección II. Obligaciones de las partes

**4. Instrucciones del Responsable.** El Encargado trata los datos **únicamente según las instrucciones documentadas** del Responsable (Anexo I y la configuración que el Responsable publica en su ficha), salvo obligación legal, que comunicará al Responsable salvo prohibición. Si considera que una instrucción infringe el RGPD, se lo comunicará de inmediato. El Responsable es quien determina los plazos de conservación; a falta de otra instrucción se aplican los del Anexo I.

**5. Limitación de la finalidad.** El Encargado trata los datos solo para prestar el Servicio. No los usará para fines propios (analítica comercial, perfiles, entrenamiento de modelos de inteligencia artificial, publicidad) ni los cederá a terceros salvo los subencargados autorizados.

**6. Confidencialidad.** El personal autorizado del Encargado se compromete a la confidencialidad y solo accede a los datos en la medida necesaria. En el momento de la firma, el acceso a producción está limitado a `[N]` persona(s) operadora(s) identificadas, con acceso por túnel SSH, contraseña y segundo factor.

**7. Obligaciones del Encargado.**

**7.1. Seguridad.** El Encargado aplica al menos las medidas técnicas y organizativas del Anexo II y las mantiene actualizadas al estado de la técnica.

**7.2. Categorías especiales y condenas.** El Servicio no está diseñado para tratar datos de categorías especiales (art. 9 RGPD) ni de condenas e infracciones. El Responsable se compromete a configurar el bot de modo que no los solicite. Si un cliente final los introduce en un texto libre, el Encargado los tratará únicamente como parte del mensaje, con los mismos plazos y medidas, y no los usará para ningún otro fin.

**7.3. Documentación y cumplimiento.** El Encargado puede demostrar su cumplimiento y responde sin demora a las consultas del Responsable sobre el tratamiento.

**7.4. Auditorías.** El Encargado pone a disposición del Responsable la información necesaria para demostrar el cumplimiento y permite auditorías, incluida la inspección, por el Responsable o por un auditor que este designe y que esté sujeto a confidencialidad, con preaviso razonable de `[15]` días, como máximo una vez al año salvo brecha o requerimiento de una autoridad, sin comprometer la seguridad de los demás clientes del Encargado. La plataforma aloja a varios negocios en la misma infraestructura con aislamiento por Row-Level Security: la auditoría no dará acceso a datos de otros responsables.

**7.5. Registro y exportación.** El Encargado facilita la parte del [registro de actividades](registro-de-actividades.md) que corresponde al Responsable y mantiene el suyo como encargado (art. 30.2 RGPD).

**7.6. Transferencias internacionales.** El Encargado solo transfiere datos fuera del Espacio Económico Europeo conforme al capítulo V del RGPD (decisión de adecuación, cláusulas contractuales tipo u otra garantía), según el Anexo III. El Responsable es consciente de que el canal elegido implica a Meta (WhatsApp) o Telegram, que actúan según sus propios términos (Anexo III).

**7.7. Subencargados.** Autorización general. El Responsable autoriza a los subencargados del Anexo III. El Encargado informará por escrito (correo al contacto del Responsable) de cualquier incorporación o sustitución con **al menos 30 días naturales de preaviso**; el Responsable puede **oponerse** por motivos razonables de protección de datos dentro de ese plazo. Si el Encargado mantiene el cambio pese a la oposición, el Responsable puede resolver el contrato sin penalización con la devolución de los datos conforme a la cláusula 7.9. El Encargado impone a cada subencargado, por contrato, obligaciones equivalentes y responde frente al Responsable de su cumplimiento.

**7.8. Asistencia al Responsable.** El Encargado asiste al Responsable, teniendo en cuenta la naturaleza del tratamiento:

- **Derechos de los interesados.** Si un interesado se dirige al Encargado, este se lo comunica al Responsable **en un plazo máximo de 5 días hábiles** y no responde por sí mismo salvo instrucción. El Encargado facilita la exportación y supresión de los datos de un contacto y del negocio ([procedimiento](derechos-de-los-interesados.md)), con la mayor diligencia y, en todo caso, a tiempo para que el Responsable cumpla el plazo de un mes del art. 12.3 RGPD.
- **Seguridad, evaluaciones de impacto y consulta previa.** Facilita la información que el Responsable necesite para los arts. 32 a 36 RGPD.
- **Registro de actividades y obligaciones de transparencia**, facilitando las descripciones del Anexo I.

**7.9. Devolución y supresión al terminar.** Al extinguirse el Servicio, el Encargado, a elección del Responsable, devuelve los datos (exportación en JSON) y los suprime **como máximo en 30 días desde la fecha efectiva de baja**, y lo acredita por escrito. Quedan fuera de esa supresión inmediata, y se eliminarán en su ciclo de rotación, las **copias de seguridad cifradas** (hasta `[6 meses]`, ver Anexo I) y los **registros técnicos** (31 días); durante ese tiempo no se restauran salvo recuperación de desastre y, si se restauran, se reaplican las supresiones. Se conservará una anotación de auditoría del borrado, sin datos del negocio. El calendario de Google es del Responsable y no lo borra el Encargado.

### Sección III. Brechas de seguridad

**8. Notificación de brechas.** En caso de violación de la seguridad de los datos personales que afecte a datos tratados por cuenta del Responsable, el Encargado la notifica al Responsable **sin dilación indebida y, como máximo, en 48 horas** desde que tenga conocimiento de ella, al contacto designado en el Anexo I, con la información de que disponga: naturaleza de la violación (categorías y número aproximado de interesados y registros), consecuencias probables y medidas adoptadas o propuestas, y punto de contacto. Si no toda la información está disponible, la facilitará por fases sin más dilación. La notificación a la AEPD (en 72 horas desde que el Responsable tenga conocimiento) y a los interesados corresponde al Responsable; el Encargado coopera. Procedimiento interno: [brechas](brechas-de-seguridad.md).

### Sección IV. Disposiciones finales

**9. Incumplimiento y resolución.** Si el Encargado incumple este contrato, el Responsable puede ordenar la suspensión del tratamiento hasta que se subsane o resolver el contrato. El Encargado puede resolverlo si, informado de que una instrucción infringe la ley, el Responsable insiste en ella.

**10. Responsabilidad.** Cada parte responde conforme al art. 82 RGPD. `[Los límites contractuales de responsabilidad, si los hay, los decide el abogado.]`

**11. Ley aplicable y jurisdicción.** Derecho español; tribunales de `[CIUDAD]`.

Firmas: `[REPRESENTANTE DEL RESPONSABLE]` y `[TITULAR]`.

---

## Anexo I. Descripción del tratamiento

| Concepto | Contenido |
|---|---|
| Responsable | `[NEGOCIO]` |
| Encargado | `[TITULAR]` |
| Contacto del Responsable para brechas | `[NOMBRE, EMAIL Y TELÉFONO DE GUARDIA]` |
| Contacto del Encargado | `[EMAIL DE PRIVACIDAD]` |
| Interesados | Clientes finales del Responsable que escriben al bot; en su caso, el dueño y las personas autorizadas del Responsable (avisos) |
| Categorías de datos | Identificador de contacto (teléfono, BSUID de WhatsApp o id de Telegram), nombre de perfil, nombre dado en la reserva, mensajes y texto libre, estado de la conversación, reservas (servicio, fecha y hora; nombre y teléfono en el evento de Calendar), avisos al dueño, métricas sin identificadores |
| Categorías especiales | No previstas (ver cláusula 7.2) |
| Naturaleza y finalidad | Recepción y respuesta automatizada de mensajes; gestión de citas; recordatorios de servicio y avisos al dueño; atención de bajas (`baja`); operación y seguridad del Servicio |
| Duración | La del Servicio |
| Plazos de conservación por defecto | Contactos: 12 meses de inactividad (con `opt_out`, solo el identificador como supresión mínima); mensajes entrantes: contenido vaciado a 30 días y fila a 90; mensajes salientes: contenido a 30 días y fila a 12 meses; avisos y métricas: 12 meses; logs: 31 días; cola: 30 días; copias de seguridad: diaria 7, semanal 4, mensual 6. Instrucción del Responsable distinta: `[ ]` |
| Limpieza | Automática nocturna; el Encargado confirma que está activa antes de tratar datos reales |
| Lugar del tratamiento | `[PROVEEDOR VPS, PAÍS UE]`; transferencias del Anexo III |

## Anexo II. Medidas técnicas y organizativas

Resumen de [Seguridad y secretos](../arquitectura/seguridad-y-secretos.md), a fecha `[FECHA]`. Cada medida existe en el código; no se prometen otras.

**Aislamiento de los datos entre clientes**

- Todo dato de cliente lleva `tenant_id` y Row-Level Security forzada; el negocio se fija solo con `tenant_tx`. Los roles de base de datos son tres: `fp_app` (sujeta a RLS), `fp_owner` (solo migraciones, comandos de operación y panel) y `fp_readonly` (solo lectura, sin tablas sensibles).
- Los permisos de base de datos se declaran en `autobot/db/grants.py` y se reaplican en cada despliegue y restauración.

**Cifrado y secretos**

- Secretos de canal del Responsable (tokens, secretos de app, de webhook) cifrados con Fernet en la base de datos; nunca en claro, nunca en git, nunca en logs. Rotación sin parada con claves múltiples.
- Secretos de la plataforma en el `.env` del servidor, fuera de git y de la imagen. La plataforma rechaza arrancar en producción con valores de ejemplo.
- Copias de seguridad cifradas con restic y en un almacenamiento de otro proveedor.

**Autenticidad de las comunicaciones**

- Cada webhook verifica su firma antes de leer el cuerpo (`X-Hub-Signature-256` de WhatsApp, `secret_token` de Telegram), con comparación en tiempo constante y límite de tamaño y de fallos por IP.
- HTTPS automático (Caddy); solo se exponen los webhooks y `/health`.

**Control de acceso y trazabilidad**

- El panel de operación solo es accesible por túnel SSH, con contraseña y TOTP, límite de intentos y protección CSRF.
- Toda escritura de operación se anota en un registro de auditoría que rechaza claves con forma de secreto; las exportaciones y borrados de datos de contactos dejan evento.

**Minimización**

- Los trabajos de la cola reciben solo ids; los candados usan hashes; los logs redactan teléfonos (solo los 4 últimos dígitos) y secretos; Sentry no recibe peticiones, variables locales ni texto de excepciones.
- Retención con vaciado y borrado automáticos (Anexo I).

**Resiliencia y continuidad**

- Mensajes entrantes guardados antes de contestar al proveedor; efectos externos idempotentes; no se reintenta a ciegas un envío ambiguo.
- Copias de seguridad periódicas con simulacro de restauración y vigilancia externa de que la plataforma está viva.

**Organizativas**

- Cambios en cifrado, secretos, firma de webhooks, infraestructura, datos de producción y activación del canal real requieren aprobación humana expresa.
- Procedimientos escritos de [derechos](derechos-de-los-interesados.md) y de [brechas](brechas-de-seguridad.md).
- Control en CI de que ningún fichero versionado contiene datos de clientes reales.

## Anexo III. Subencargados autorizados

Lista vigente en [Subencargados](subencargados.md) (se copia aquí al firmar):

| Subencargado | Servicio | Ubicación | Garantía |
|---|---|---|---|
| `[PROVEEDOR VPS]` | Servidor y base de datos | `[UE]` | DPA con el proveedor |
| `[ALMACENAMIENTO DE BACKUPS]` | Copias cifradas | `[UE]` | DPA con el proveedor; copias cifradas |
| Meta Platforms Ireland / WhatsApp (solo canal WhatsApp) | WhatsApp Cloud API | UE/EE. UU. | Términos de tratamiento de datos de Meta |
| Google (solo pack `salon`) | Calendar | `[según cuenta del Responsable]` | Workspace con DPA; **cuenta gratuita sin DPA** (riesgo aceptado por el Responsable) |
| Sentry (opcional) | Errores sin datos personales | EE. UU. | DPF y cláusulas tipo |
| Healthchecks.io | Latido | `[CONFIRMAR]` | Sin datos personales |

Telegram **no** es subencargado: es responsable independiente de su propia plataforma de mensajería. GitHub y GHCR alojan código e imágenes, nunca datos de clientes.

## Anexo IV. Instrucciones específicas del Responsable

`[Plazos distintos, texto de las respuestas del bot, activación de recordatorios (reminders_enabled), canal, pack, calendario]`.

## Dónde está el código

Medidas: `apps/backend/src/autobot/tenancy/crypto.py`, `autobot/db/grants.py`, `autobot/channels/`, `autobot/ops/logging.py`, `autobot/ops/audit.py`; retención: `autobot/runtime/retention.py`.

## Relacionado

[Roles y tratamientos](roles-y-tratamientos.md), [Subencargados](subencargados.md), [Registro de actividades](registro-de-actividades.md), [Brechas](brechas-de-seguridad.md).
