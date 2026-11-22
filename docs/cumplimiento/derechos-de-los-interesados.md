# Derechos de los interesados

Procedimiento operativo para atender los derechos de las personas (acceso, rectificación, supresión, oposición, limitación, portabilidad). Léelo cuando un cliente final, un dueño o un negocio pida algo sobre sus datos. Los comandos y el detalle técnico están en [Retención y RGPD](../procedimientos/retencion-rgpd.md); aquí está quién hace qué, los plazos y las plantillas.

!!! warning "No es asesoramiento jurídico"
    Procedimiento de trabajo y plantillas **pendientes de revisión por abogado**, en especial las excepciones a los derechos y las respuestas denegatorias. Cualquier acción sobre datos de producción requiere aprobación humana explícita y la ejecuta una persona (`CLAUDE.md`).

## Quién responde

| Situación | Responsable de contestar | Papel de la plataforma |
|---|---|---|
| Un cliente final de un negocio ejerce un derecho | **El negocio** (responsable) | Encargada: asiste, exporta o borra cuando el negocio lo ordena |
| La petición llega a la plataforma por error | El negocio | Reenvía al negocio en **5 días hábiles** y avisa a la persona de que lo ha hecho ([plantilla C](#c-redireccion-al-negocio)) |
| Persona de la demo, dueño, operador, contacto comercial | **La plataforma** | Responde directamente |
| Un negocio pide los datos de todo su negocio o su baja | Es el responsable: pide, la plataforma ejecuta | Exportación y borrado total |

## Plazos

- **Un mes** desde la recepción de la solicitud (art. 12.3 RGPD), prorrogable dos meses más en casos complejos informando dentro del primer mes. El plazo es del **negocio**: la plataforma debe ejecutar en un máximo de `[10]` días hábiles tras la orden del negocio para dejar margen (compromiso del contrato, cláusula 7.8).
- La baja de recordatorios (`baja`) es inmediata: la hace el propio bot.
- La baja de un negocio: borrado en un máximo de 30 días desde la baja efectiva ([Alta y baja](../procedimientos/alta-baja-negocio.md#baja)).

## Verificación de identidad

Sin pedir más datos de los necesarios (la AEPD advierte de no exigir documentación excesiva):

1. Contestar **por el mismo canal** y al mismo identificador desde el que se escribió (el teléfono o el chat), nunca a un correo no verificado.
2. Si la petición llega por otra vía (correo), pedir que la reiteren desde el canal del bot o que indiquen un dato que solo el titular conozca (por ejemplo, el nombre y la fecha de una cita pasada) antes de entregar nada.
3. Para la exportación o supresión, comprobar que el identificador coincide con el contacto que se va a tratar (`--channel` explícito si hay coincidencia entre canales).
4. Si hay duda razonable, pedir información adicional proporcionada y documentarlo.
5. Un tercero o representante debe acreditar su representación.

## Procedimiento paso a paso

1. **Registrar.** Fecha de recepción, quién pide, qué derecho, canal, negocio (contador de un mes). En un fichero fuera de logs públicos.
2. **Identificar el negocio y el contacto.** Panel, pestaña «Contactos»: busca por identificador. Anota solo el id interno en el registro.
3. **Aprobación humana.** Exportar y olvidar son acciones sobre datos de producción: la persona responsable las aprueba y ejecuta.
4. **Ejecutar** según el derecho:

| Derecho | Qué se hace | Cómo |
|---|---|---|
| Acceso y portabilidad | Exportación JSON del contacto (conversación, mensajes, eventos, avisos) | Panel: «Exportar datos» en la conversación del contacto; o `contact_export` en local. Evento `contact.export` |
| Rectificación | Corregir el nombre u otro dato | Panel (ficha del contacto) o instrucción al negocio; si el dato está en un evento de Calendar, lo corrige el negocio |
| Supresión | Borra el contacto y sus mensajes, conversación, avisos y eventos asociados | Panel: «Olvidar contacto»; o `contact_forget <slug> <id> --channel main`. Evento `contact.forget`. Irreversible; borra también la marca `opt_out` (avisar a quien lo pide) |
| Oposición / limitación | Parar los envíos | Marca `opt_out` (la persona escribe `baja`); limitación: marcar y no tratar, o borrar si procede `[criterio del negocio]` |
| Todos los datos de un negocio | Exportación completa | Panel: «Exportar datos del negocio»; `tenant_data_export` |

5. **Entregar** la exportación con medidas de seguridad: por el canal verificado o en enlace temporal; custodiar y retirar el fichero según el procedimiento. Nunca por correo sin cifrar.
6. **Responder** con la plantilla correspondiente y cerrar el registro.
7. **Comprobar** el evento de auditoría (panel, Logs, pestaña Operador).

En producción las exportaciones se hacen **desde el panel** (el contenedor efímero no conserva ficheros); los comandos de exportación son para local. Ver la advertencia en [Retención y RGPD](../procedimientos/retencion-rgpd.md).

## Qué no cubre

Un borrado de contacto o de negocio **no alcanza** a:

- **Google Calendar del negocio.** La plataforma escribe nombre y teléfono en el evento y no los borra: lo hace el negocio en su cuenta. Hay que decírselo siempre.
- **Logs técnicos** (VictoriaLogs): caducan a los 31 días y llevan teléfonos redactados.
- **Backups** (restic): hasta unos 6 meses; los datos borrados siguen en copias antiguas. Si se restaura un backup, hay que **volver a aplicar las supresiones** atendidas desde su fecha (anota cada supresión con fecha en el registro de derechos para poder reaplicarlas; ver [Restaurar](../procedimientos/restaurar.md)).
- **Meta y Telegram**: tienen sus propias copias de los mensajes; la persona debe dirigirse a ellos.
- **La marca `opt_out`**: el borrado la elimina; si la persona vuelve a escribir sin darse de baja, recibirá recordatorios.
- **Datos del dueño en Telegram**: se desvinculan con `owner_unlink`.

## Plantillas de respuesta

### A. Acceso (entrega de datos)

```text
Asunto: Respuesta a tu solicitud de acceso

Hola [NOMBRE]:
En respuesta a tu solicitud del [FECHA], te adjuntamos los datos que
[NEGOCIO] conserva sobre ti a través de su asistente: identificador de
contacto, nombre, mensajes y avisos de los últimos [PLAZO] meses.
Los tratamos para [FINALIDAD], con base en [BASE], y los conservamos
hasta [PLAZO]. Los reciben nuestros proveedores técnicos (Autobot, Meta o
Telegram, Google). Puedes pedirnos su rectificación, supresión,
oposición, limitación o portabilidad, y reclamar ante la AEPD (www.aepd.es).
Atentamente, [NEGOCIO] ([EMAIL DEL NEGOCIO])
```

### B. Supresión (ejecutada)

```text
Hola [NOMBRE]:
Hemos eliminado tus datos del asistente de [NEGOCIO] el [FECHA]. Ten en
cuenta que: (1) las copias de seguridad cifradas se eliminan por completo
en un máximo de [6] meses; (2) [las citas pasadas de nuestro calendario las
borraremos nosotros / conservamos X por obligación legal]; (3) Meta/Telegram
conservan sus propias copias según sus políticas. Si vuelves a escribirnos,
se creará un contacto nuevo. Atentamente, [NEGOCIO]
```

### C. Redirección al negocio

```text
Hola [NOMBRE]: tu solicitud afecta a datos que gestiona [NEGOCIO], que es
el responsable. Se la hemos trasladado el [FECHA] y te responderá en el
plazo legal de un mes. Contacto: [EMAIL DEL NEGOCIO]. Autobot ([TITULAR])
actúa solo como su proveedor técnico.
```

### D. Denegación o prórroga

```text
Hola [NOMBRE]: no podemos atender totalmente tu solicitud del [FECHA]
porque [MOTIVO: no hemos podido verificar tu identidad / existe una
obligación legal de conservación / solicitud manifiestamente infundada o
excesiva]. [Prórroga: por la complejidad necesitamos dos meses más;
te lo comunicamos dentro del primer mes.] Puedes reclamar ante la AEPD
(www.aepd.es) o acudir a los tribunales. Atentamente, [RESPONSABLE]
```

### E. Petición del negocio (borrado total)

Confirma por escrito la fecha efectiva de baja, ofrece la exportación (`tenant_data_export` desde el panel), ejecuta `tenant_status <slug> offboard` y `tenant_purge` (con aprobación humana) en **un máximo de 30 días**, y envía un certificado de borrado sin datos del negocio (la entrada de auditoría `tenant.purge`).

## Registro de solicitudes

Anota cada solicitud (sin copiar el identificador personal en ningún ticket público):

| Fecha | Negocio | Derecho | Identificador (id interno) | Verificación | Respuesta | Cierre |
|---|---|---|---|---|---|---|
| | | | | | | |

## Dónde está el código

`apps/backend/src/autobot/management/commands/` (`contact_export`, `contact_forget`, `tenant_data_export`, `tenant_purge`, `owner_unlink`), servicios y routers del panel en `apps/backend/src/autobot/panel/`.

## Relacionado

[Retención y RGPD](../procedimientos/retencion-rgpd.md), [Auditoría](../referencia/auditoria.md), [Registro de actividades](registro-de-actividades.md), [Contrato de encargado](contrato-de-encargado.md).
