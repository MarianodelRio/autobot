# ADR-027 — Alta y configuración de un negocio en el panel

**Estado:** aceptada (2026-11-24). Reúne los antiguos ADR-014 (pasos del alta) y ADR-016
(acciones de alta de WhatsApp), que vivían en una pestaña «Alta» propia que ya no existe.

## Contexto

Dar de alta un negocio implica varios pasos repartidos entre servicios: documento válido,
canal, secretos, salud del canal, plantillas, privacidad, un mensaje real de un tester,
dueño, calendario (`salon`) y horarios (`bus`). Hacía falta un sitio que dijera, paso a
paso, qué falta y por qué, y que permitiera comprobarlo contra el proveedor real.

En WhatsApp, además, lo que hace que un número reciba mensajes se hacía a mano con la
Graph API: configurar el webhook de la app, registrar el número en la Cloud API (con el PIN
de verificación en dos pasos) y suscribir la app a la cuenta de WhatsApp (WABA). Son tres
llamadas repetitivas, y equivocarse en una deja un número que no recibe nada sin que nadie
lo vea.

La ficha de un cliente tenía dos pestañas para lo mismo: «Alta», con los pasos
de activación y sus «Comprobar», y «Configuración», con el formulario del documento.
Las dos tocaban canal, dueño, calendario, privacidad y horarios: el QR estaba en Alta y
las credenciales en Configuración, el email de la cuenta de servicio en Configuración y
su comprobación en Alta. Dar de alta un negocio obligaba a ir y venir entre ellas.
Además, Configuración mostraba todo el documento abierto a la vez, sin decir qué parte
faltaba, y al abrirla sin tocar nada ya marcaba «Cambios sin guardar» (y el navegador
pedía confirmación al cambiar de pestaña o salir): el formulario (rjsf) rellena los
valores por defecto del esquema para los campos que el documento guardado no tiene, y
la comparación se hacía contra el documento sin esos valores.

## Decisión

### Los pasos del alta

- **Un paso es una estructura común,** `SetupStep` (clave, etiqueta, por qué importa,
  estado `ok`/`pending`/`error`, si bloquea la activación, detalle, valores con copiar y si
  tiene «Comprobar»). Vive en `autobot.panel.services.setup`, no en `core`, porque los
  pasos de canal citan conceptos de Telegram y WhatsApp.
- **Los pasos se montan reutilizando los servicios existentes**, no con un hook por pack o
  adaptador: `tenant_setup(slug)` llama a `activation.checklist`, al email de la cuenta de
  servicio y al estado de los horarios de `bus`. Un pack o canal nuevo con un paso
  distinto se añade como una rama más en `tenant_setup`, sin tocar los contratos de `Pack`
  ni de `ChannelAdapter`.
- **Leer nunca llama a un proveedor.** `GET /tenants/{slug}/setup` solo usa lo que está en
  caché; `POST /tenants/{slug}/setup/check/{step}` hace la comprobación real de un paso,
  fuera de cualquier transacción, y la audita.
- **La prueba de escritura del calendario** (`CalendarClient.check_write_access()`)
  inserta un evento con id aleatorio en el año 2000, marcado `private.fp_probe=1` (nunca
  `fp_key` ni `fp_contact`, para que ni el barrido ni el resumen lo tomen por una cita),
  comprueba que existe y lo borra. Antes borra cualquier resto de una prueba anterior, así
  que es idempotente ante una llamada ambigua.
- **El paso de horarios de `bus`** no tiene «Comprobar»: solo lee el estado del dataset. Se
  busca por `document.pack`, no por `tenant.pack`, que es `None` justo en un negocio
  degradado por falta de ese dataset.
- **Los pasos no bloqueantes** (el dueño, por ejemplo) se muestran igual, sin impedir
  «Activar».

### Acciones de alta de WhatsApp

- **Tres pasos solo para WhatsApp**, cada uno con su «Comprobar» y una acción de escritura
  (`POST /tenants/{slug}/setup/action/{step}`, fuera de transacción, auditada como
  `tenant.setup_action` con el resultado y nunca con el PIN):
  - **Webhook de la app:** `POST /{app_id}/subscriptions` con la URL del webhook del
    negocio y su `verify_token`. Meta verifica la URL en ese momento, así que solo se
    ofrece con los ids y los secretos completos.
  - **Número registrado:** primero `GET /{phone_number_id}`; si ya está en la Cloud API, no
    hace nada (Meta limita los intentos). Si no, `POST /{phone_number_id}/register` con el
    PIN de 6 dígitos.
  - **App suscrita a la cuenta:** `POST /{waba_id}/subscribed_apps`. Pide confirmación
    explícita, porque es la que hace que el número real empiece a entregar mensajes.
- **El código vive en `autobot.channels.whatsapp.registration`**, el equivalente de
  `channels.telegram.registration`.
- **El PIN nunca se guarda**: ni en la base de datos, ni en la auditoría, ni en los logs.
- **No son bloqueantes:** el paso «Mensaje de un tester» ya demuestra que los tres
  funcionan.
- **Una escritura ambigua no se reintenta nunca:** si la conexión se cae después de enviar,
  el resultado es `unknown` y la interfaz pide «Comprobar» antes de repetir.
- **Nunca se devuelve lo que responde Meta** (cuerpos de error, tokens, teléfonos): solo
  mensajes cortos en español.
- **Queda fuera** añadir y verificar el número por SMS y crear las plantillas: se hacen en
  WhatsApp Manager.

### Una sola pestaña «Configuración»

- **Una sola pestaña «Configuración».** Las pestañas de la ficha quedan Resumen ·
  Configuración · Actividad · Contactos · Avisos. `?tab=alta` en la URL abre
  Configuración.
- **Banner de alta arriba,** solo mientras el negocio está en `onboarding`: «Alta: N de M
  pasos obligatorios listos», la lista de pasos bloqueantes que faltan (cada uno abre su
  sección y se desplaza a ella) y «Activar» (el mismo diálogo: escribir el slug;
  deshabilitado mientras quede un paso bloqueante sin `ok`). Con el negocio activo o
  pausado no hay banner. Los pasos cuya sección no existe se muestran en esa zona.
- **Secciones plegables** (acordeón; se pueden abrir varias). La cabecera cerrada muestra
  un punto de estado calculado con los pasos de alta de esa sección (crítico si un paso
  bloqueante no está `ok`, aviso si un paso dio error, `ok` si todos lo están), la
  etiqueta, un resumen de una línea con los valores clave y las marcas «modificado» (hay
  cambios sin guardar ahí) o «con errores» (el último guardado devolvió errores de
  validación ahí). Abierta: una explicación breve, sus campos, «Comprobaciones del alta»
  (sus pasos, con «Comprobar» y acciones) y sus extras (enlace, QR, webhook y credenciales
  en Canal; invitar y desconectar al dueño en Dueño y testers; email de la cuenta de
  servicio en Calendario; horarios en uso y «Aplicar» en los datasets).
- **Comprobar y las acciones actúan contra lo guardado:** se ejecutan al momento y se
  deshabilitan («Guarda antes de comprobar») mientras su sección tiene cambios sin
  guardar.
- **Al cargar se abren solas** las secciones con un paso bloqueante pendiente (en
  `onboarding`) y la indicada en `?section=` (p. ej. `?section=canal`).
- **Las secciones se declaran en el backend,** en `autobot/panel/services/forms.py`:
  `Section` (clave, etiqueta, descripción, campos y resumen como rutas con puntos),
  `PLATFORM_SECTIONS` (Negocio, Canal, Dueño y testers, Privacidad y atención, para todos
  los packs) y `PACK_SECTIONS` (`salon`: Servicios y horario, Reservas y recordatorios,
  Calendario de Google, Evento especial, Textos del bot; `bus`: Oficina y enlaces,
  Horarios y búsqueda). Una ruta que el pack no tiene se ignora. Todo campo de `config`
  que ninguna sección nombra aparece en una sección final «Otros ajustes»; la última es
  siempre «Avanzado» (historial de versiones y vuelta atrás, editar como YAML, ids
  técnicos). `ui_schema` devuelve `groups` y `show_if` (campos condicionales, `SHOW_IF`:
  `config.reminder_window_hours` solo con `config.reminders_enabled`,
  `config.manual_confirmations_since` solo con `config.manual_confirmations_enabled`); la
  clave `collapsed` desaparece.
- **Cada paso dice a qué sección pertenece** (`SetupStepOut.section`): documento → Negocio;
  canal, secretos, pasos de WhatsApp/Meta, plantillas y salud → Canal;
  privacidad → Privacidad y atención; tester y dueño → Dueño y testers; calendario →
  Calendario; `dataset:*` → la sección de datasets del pack. Los endpoints de alta
  (`GET/POST tenants/{slug}/setup...`) no cambian.
- **El webhook de Telegram sale una sola vez**, en el bloque del Canal (estado consultado
  a Telegram al abrir la sección y «Registrar webhook»). El paso «Webhook de Telegram»
  desaparece: repetía lo mismo con su propio «Comprobar» y no bloqueaba nada, porque un
  webhook sin registrar ya hace fallar «Salud del canal», que es lo que bloquea.
- **Una sola barra de guardado** para todo el documento (cada guardado es una versión),
  fija abajo y visible solo si algo cambió.
- **«Modificado» se calcula contra el documento guardado con los valores por defecto del
  esquema aplicados,** y al guardar solo se envía lo que el operador cambió: los valores por
  defecto que no tocó no se escriben en el documento, así un cambio futuro del valor por
  defecto de un pack sigue llegando a ese negocio. Cambiar de pestaña tras aceptar la
  confirmación ya no la pide dos veces.

## Alternativas consideradas

- **Un hook `Pack.setup` o `ChannelAdapter.setup_steps`:** más general, pero cambia los
  contratos de `core` y de los dos adaptadores para un solo pack con calendario y un solo
  canal con webhook.
- **Guardar el estado de cada paso en una tabla:** innecesario; cada paso se calcula a
  partir de lo que otras tablas ya guardan.
- **Guardar el PIN como un secreto cifrado del canal:** permitiría volver a registrar el
  número sin pedírselo al operador, pero cambia el esquema y el cifrado de los secretos
  para algo que se hace una vez por número.
- **Un comando de terminal en vez de botones:** es lo que ya se podía hacer con `curl`; el
  valor está en que el alta llegue hasta el final sin salir del panel.
- **Hacer bloqueantes los tres pasos de WhatsApp:** duplicaría la prueba real del tester.
- **Mantener las dos pestañas y enlazarlas entre sí:** reduce el ir y venir, pero sigue
  habiendo dos sitios para el canal, el dueño y el calendario, y Configuración seguiría
  sin decir qué falta.
- **Un botón de guardar por sección:** más cómodo a primera vista, pero cada guardado es
  una versión del documento (ADR-009) y guardar por partes llena el historial de
  versiones a medias y complica el bloqueo optimista (una sección guardada cambia la
  versión base de las demás, que tendrían que rehacer su diff).
- **Un asistente paso a paso para el alta:** encaja con un alta lineal, pero el alta real
  no lo es (Meta tarda días en aprobar plantillas, el calendario depende del negocio) y
  después del alta la misma información se edita de forma libre; ya hay un asistente para
  crear el negocio (`Clientes → Nuevo cliente`).

## Consecuencias

- Un pack o canal nuevo con pasos propios obliga a tocar `tenant_setup`, no un contrato.
- La prueba de escritura escribe de verdad en el calendario del cliente durante
  «Comprobar», aunque sea un evento borrado al momento.
- El panel puede cambiar, a petición del operador, el webhook de la app y la suscripción a
  la WABA de un número real; por eso la suscripción pide confirmación y cada intento queda
  auditado.
- `forms.py`, que es de la plataforma, nombra campos de `salon` y `bus` en
  `PACK_SECTIONS`, igual que ya hacía `CUSTOM_FIELDS`. Se acepta: es presentación del
  panel, no lógica del pack, y los packs siguen sin importar nada del panel.
- Un pack nuevo funciona sin declarar secciones: sus campos de `config` salen en «Otros
  ajustes». Declararlas es una mejora, no un requisito.
- Un paso de alta nuevo debe indicar su `section`; si no la tiene o la sección no existe,
  se muestra arriba, junto al banner.
- Los documentos guardados ya no acumulan valores por defecto que nadie eligió; los que ya
  los tenían escritos los conservan.
- Tests: secciones y `show_if` en `tests/platform/panel/test_forms.py`, `section` de cada
  paso en `test_setup.py`, y en el panel los helpers puros de `lib/form-draft.ts` y el
  editor.

## Cuándo revisarla

- Si un tercer pack con necesidades de alta muy distintas llena `tenant_setup` de ramas
  difíciles de seguir: pasar al hook por pack.
- Si Meta cambia estos endpoints o deja de verificar el webhook de forma síncrona.
- Si hay que volver a registrar números con frecuencia: reconsiderar guardar el PIN.
- Si `PACK_SECTIONS` crece con un tercer pack hasta hacer de `forms.py` un catálogo de
  campos de packs, mover la declaración de secciones a cada pack (como metadato de su
  modelo de configuración).
- Si las versiones creadas por una sola barra de guardado resultan demasiado grandes para
  revisarse en el historial, reconsiderar el guardado por sección.
