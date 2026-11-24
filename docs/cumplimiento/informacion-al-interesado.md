# Información al interesado

Textos modelo para cumplir el deber de información de los arts. 13 y 14 RGPD **por capas**, como recomienda la [AEPD](https://www.aepd.es) y el art. 11 de la LOPDGDD: una primera capa breve dentro del bot, una segunda capa completa (política de privacidad) y la política de la propia plataforma. Léela para redactar lo que ve cada persona y para dar de alta a un negocio.

!!! warning "No es asesoramiento jurídico: textos pendientes de revisión por abogado"
    Los textos son modelos. Antes de publicarlos, un abogado debe revisar las bases jurídicas, los plazos y las menciones a transferencias. Los marcadores `[...]` los rellena el negocio o el titular; no se inventan datos.

!!! note "Estado técnico"
    El bot muestra la primera capa como una sola línea en cursiva debajo del menú, cada vez que lo muestra, y debajo del primer mensaje de cada contacto (y otra vez tras un olvido): asistente automático, negocio y enlace a la segunda capa (`privacy.policy_url`; sin él, el responsable `privacy.controller_name` solo si no es el propio negocio). No hay comandos `PERSONA` ni `BAJA` ([ADR-028](../arquitectura/adr/ADR-028-aviso-en-una-linea-sin-persona-ni-baja.md)): la atención humana es el teléfono de «ℹ️ Información» y la baja de recordatorios está por decidir. La activación del canal real exige `privacy.policy_url`. Texto exacto y diseño: [Packs](../arquitectura/packs.md#aviso-inicial). Los textos de abajo son los modelos completos para el abogado, más largos que lo que hoy muestra el bot.

## Quién informa a quién

| Persona | Quién le informa | Con qué |
|---|---|---|
| Cliente final de un negocio | El negocio (responsable); la plataforma pone los medios | Primera capa en el bot + política de privacidad del negocio |
| Persona en la demo | La plataforma (responsable) | Primera capa de la demo + política de la plataforma |
| Dueño o autorizado del negocio | La plataforma | Política de la plataforma |
| Quien visita la web de la plataforma | La plataforma | Política de la plataforma y aviso legal ([LSSI](otras-normas.md)) |

## 1. Primera capa en el bot

Textos breves (caben en un mensaje y en el límite de 4.096 caracteres de los dos canales). Se mostrarían en el primer contacto y al escribir `privacidad` (comportamiento aún no implementado, ver el aviso de estado). Los `[...]` salen de la ficha del negocio.

### Pack `salon`

```text
Hola, soy el asistente de [NEGOCIO]. Para gestionar tu cita guardo tu
teléfono (o tu identificador de Telegram), tu nombre y tus mensajes.
Responsable: [NEGOCIO] ([EMAIL DE PRIVACIDAD DEL NEGOCIO]).
Uso: gestionar tus citas y enviarte recordatorios de ellas.
Conservación: hasta 12 meses sin actividad.
[CÓMO DEJAR DE RECIBIR RECORDATORIOS: por decidir]. Más información y tus
derechos: [URL DE LA POLÍTICA]. Por favor, no escribas datos de salud.
```

### Pack `bus`

```text
Hola, soy el asistente de horarios de [NEGOCIO]. Para responderte guardo
tu identificador (teléfono o Telegram) y tus mensajes, hasta 12 meses
sin actividad. Responsable: [NEGOCIO] ([EMAIL DE PRIVACIDAD DEL NEGOCIO]).
Los horarios son orientativos: confírmalos en [FUENTE OFICIAL].
Más información y tus derechos: [URL DE LA POLÍTICA].
```

### Demo

```text
Esta es una demo de Autobot, de [TITULAR] (NIF [NIF], [DOMICILIO]).
Para enseñártela guardo tu identificador de [Telegram/WhatsApp] y tus
mensajes de prueba: eventos 7 días, sesión 30 días, conversación de
demo 30 días. No escribas datos reales de terceros ni de salud.
Contacto y derechos: [EMAIL DE PRIVACIDAD]. Política: [URL DE LA POLÍTICA].
```

### Dónde mostrarla

- **WhatsApp:** en el primer mensaje de la conversación y en el perfil del número (descripción y web); el enlace va como texto, sin botón (respeta el límite de tres botones).
- **Telegram:** en la descripción del bot, en el mensaje de `/start` y en @BotFather (sección siguiente).
- **Opt-in:** para recordatorios y cualquier mensaje proactivo, ver [otras normas](otras-normas.md).

## 2. Segunda capa: política de privacidad del negocio (modelo)

La publica el negocio en su web o, si no tiene, la plataforma la aloja por negocio `[POR DECIDIR]`. Rellena los `[...]`.

```text
POLÍTICA DE PRIVACIDAD DEL ASISTENTE DE MENSAJERÍA DE [NEGOCIO]

1. Responsable. [NEGOCIO], NIF [NIF DEL NEGOCIO], [DOMICILIO DEL NEGOCIO].
   Contacto de privacidad: [EMAIL DEL NEGOCIO].

2. Qué datos tratamos. Tu identificador en el canal que uses (tu número
   de teléfono en WhatsApp, o tu identificador de Telegram), el nombre de
   tu perfil, el nombre que nos des para una reserva, los mensajes que nos
   envíes y los datos de tus citas (servicio, fecha y hora). [Si no se
   facilitan, no podemos gestionar tu cita.] No necesitamos datos de salud
   ni otras categorías especiales: te pedimos que no los escribas.

3. Para qué y con qué base jurídica.
   - Gestionar tus reservas y consultas: ejecución del contrato o de las
     medidas que nos pides (art. 6.1.b RGPD).
   - Enviarte recordatorios de tus citas: es parte del servicio contratado
     (art. 6.1.b). Puedes pedir que dejemos de enviarlos [CÓMO: por decidir].
   - [Promociones: solo con tu consentimiento previo (art. 6.1.a)].
   - Seguridad y evitar abusos: interés legítimo (art. 6.1.f).

4. Cuánto tiempo. Conservamos tus datos hasta 12 meses sin actividad.
   El contenido de los mensajes se elimina antes (a los 30 días el texto
   original y a los 12 meses el registro). Si pides la baja de
   recordatorios, guardamos solo tu identificador para no volver a
   escribirte. Las citas del calendario las conservamos [PLAZO DEL NEGOCIO].

5. Quién recibe tus datos (encargados).
   - Autobot ([TITULAR]), plataforma que ejecuta el asistente, como
     encargada de tratamiento por nuestra cuenta.
   - Meta Platforms Ireland (WhatsApp) o Telegram, según el canal.
   - Google, para el calendario de citas (solo salón).
   - Proveedores técnicos de la plataforma, que están en la UE [o con
     garantías]. No vendemos tus datos ni los usamos para entrenar IA.

6. Transferencias internacionales. WhatsApp y Google pueden tratar datos
   en EE. UU. con las garantías del Marco de Privacidad de Datos UE-EE. UU.
   o cláusulas tipo. Si usas Telegram, esa empresa trata tus datos bajo su
   propia política (https://telegram.org/privacy), con entidades fuera de
   la UE (EAU y Islas Vírgenes Británicas), y es responsable independiente.

7. Tus derechos. Acceso, rectificación, supresión, oposición, limitación
   y portabilidad, escribiendo a [EMAIL DEL NEGOCIO]. Respondemos en un mes. Puedes
   reclamar ante la Agencia Española de Protección de Datos
   (www.aepd.es).

8. Decisiones automatizadas. El asistente automatiza respuestas pero no
   toma decisiones con efectos jurídicos sobre ti; [puedes hablar con una
   persona en [CONTACTO HUMANO]].

9. Cambios. Si cambia esta política te avisaremos por este mismo medio.
   Última actualización: [FECHA].
```

Para `bus`, quita el apartado de calendario, los recordatorios y la base de cita, y sustituye la finalidad por «responder a tus consultas de horarios» (base: interés legítimo o ejecución del servicio solicitado, art. 6.1.b/f `[abogado]`).

## 3. Política de privacidad de la plataforma (web, demo, dueños)

La publica la plataforma en su web (`[URL]`) y se enlaza desde la demo y desde el bot de avisos. Cubre los tratamientos en que la plataforma es **responsable** ([roles](roles-y-tratamientos.md)).

```text
POLÍTICA DE PRIVACIDAD DE AUTOBOT

1. Responsable. [TITULAR], NIF [NIF], [DOMICILIO]. [EMAIL DE PRIVACIDAD].

2. Tratamientos.
   a) Demo. Datos: identificador de Telegram o WhatsApp, mensajes de
      prueba y negocio elegido. Finalidad: enseñarte la plataforma.
      Base: tus medidas precontractuales o interés legítimo (6.1.b/f).
      Plazos: eventos 7 días, sesión de demo 30 días, conversación 30 días.
   b) Dueños y autorizados de un negocio cliente. Datos: identificador
      de chat de Telegram y fecha de vínculo. Finalidad: enviarte los
      avisos y resúmenes del negocio. Base: ejecución del contrato (6.1.b).
      Conservación: mientras el vínculo esté activo.
   c) Contacto comercial y facturación. Datos: nombre, email, teléfono y
      datos fiscales del negocio. Base: contrato y obligaciones legales
      (6.1.b/c). Conservación: los plazos legales.
   d) Operación y seguridad. Registros técnicos 31 días; auditoría 1 año.
      Base: interés legítimo en la seguridad (6.1.f).

3. Destinatarios. Proveedor de alojamiento [PROVEEDOR VPS], proveedor de
   copias de seguridad [ALMACENAMIENTO DE BACKUPS], Meta y Telegram (canal),
   Google (calendario), Sentry (errores sin datos personales) y
   Healthchecks (latido, sin datos personales). Lista actualizada: [URL].

4. Transferencias. Ver «Subencargados»: DPF o cláusulas tipo para EE. UU.;
   Telegram, responsable independiente con entidades en EAU y BVI.

5. Derechos y reclamación. [EMAIL DE PRIVACIDAD]; plazo de un mes;
   reclamación ante la AEPD (www.aepd.es).

6. Datos de clientes de los negocios. Cuando eres cliente de un negocio
   que usa Autobot, el responsable es ese negocio; Autobot actúa como su
   encargada. Dirígete al negocio.
```

## 4. Telegram: política en @BotFather

Los [Términos para desarrolladores de bots de Telegram](https://telegram.org/tos/bot-developers) (sección «Privacy») exigen que **todo bot** esté sujeto a una política de privacidad fácilmente accesible, que detalle qué datos guarda, cómo los recoge y para qué. Telegram ofrece una *política estándar* que se aplica por defecto a bots que no tienen propia, pero **si esa política estándar no describe bien el tratamiento, se debe configurar una política propia en @BotFather** y enlazarla. Prohíben también usar los datos para crear grandes conjuntos de datos, modelos de aprendizaje automático o productos de IA.

Para cada bot (cada negocio con canal Telegram, el bot de demo y el bot de avisos):

1. Escribe a @BotFather, `/mybots`, elige el bot y abre **Edit Bot** (o el menú de ajustes del bot que muestre la política de privacidad; el nombre exacto de la opción puede variar: verifica en la interfaz de @BotFather).
2. Configura la **política de privacidad** con la URL de la política del negocio (segunda capa) o de la plataforma (demo y avisos). No uses `/setprivacy`, que es el modo de privacidad en grupos y no tiene que ver.
3. Pon la primera capa en la descripción del bot (`/setdescription`) y en el texto «about» (`/setabouttext`) con el enlace.
4. Anótalo en la ficha del alta del negocio. Es un paso manual: no se simula.

Estado: **pendiente** para el bot de demo, el de avisos y cada bot de cliente.

## Dónde está el código

Textos del bot: `apps/backend/src/packs/salon/messages.py`, `apps/backend/src/packs/bus/messages.py`; `info_text` del pack `salon` ([referencia](../referencia/packs/salon.md)); selector de demo: `apps/backend/src/autobot/channels/demo/selector.py`.

## Relacionado

[Roles y tratamientos](roles-y-tratamientos.md), [Registro de actividades](registro-de-actividades.md), [Derechos](derechos-de-los-interesados.md), [Otras normas](otras-normas.md), [Bot de demo](../arquitectura/bot-de-demo.md).
