# ADR-016 — Acciones de alta de WhatsApp desde la pestaña «Alta»

**Estado:** vigente; desde el [ADR-027](ADR-027-alta-y-configuracion-en-una-pestana.md) estas acciones están en la sección «Canal» de la pestaña «Configuración»

## Contexto

La pestaña «Alta» (ADR-014) solo **lee** de Meta para un negocio de WhatsApp: el
estado de las plantillas. Lo que falta para que un número reciba mensajes se hace a
mano, fuera del panel, con llamadas a la Graph API o desde la consola de Meta:
configurar el webhook de la app, registrar el número en la Cloud API (con el PIN de
verificación en dos pasos) y suscribir la app a la cuenta de WhatsApp (WABA,
`subscribed_apps`). Son tres llamadas sencillas y repetitivas en cada alta, y
equivocarse en una (otra URL, otro `verify_token`, la app sin suscribir) deja un
número que no recibe nada sin que nadie lo vea. Requiere aprobación humana
explícita, porque dos de ellas activan de verdad la recepción de mensajes de un
número real; la persona lo ha aprobado explícitamente.

## Decisión

- **Tres pasos nuevos en `tenant_setup`, solo para WhatsApp**, justo después de
  «Secretos»: `whatsapp_webhook` («Webhook de la app»), `whatsapp_number` («Número
  registrado») y `whatsapp_subscription` («App suscrita a la cuenta»). Siguen la
  regla del ADR-014: el `GET .../setup` nunca llama a Meta (salen `pending`), y
  «Comprobar» hace la consulta real.
- **Cada paso tiene, además, una acción de escritura** (`SetupStepOut.action`, con
  su etiqueta, si pide PIN y si pide confirmación), que se lanza con
  `POST /tenants/{slug}/setup/action/{step}` (cuerpo opcional `{pin}`), fuera de
  cualquier transacción, y se audita como `tenant.setup_action` con el paso y el
  resultado (`done`, `already`, `error`, `auth`, `unknown`), nunca con el PIN:
  - webhook: `POST /{app_id}/subscriptions` con `object=whatsapp_business_account`,
    la URL del webhook del negocio, su `verify_token` y el campo `messages`, con el
    token de app (`app_id|app_secret`). Meta verifica la URL en ese momento con un
    `GET` a nuestro webhook, que responde 404 mientras al negocio le falte alguno de
    sus tres ids o tres secretos; por eso la acción solo se ofrece con todo completo.
    Necesita `PUBLIC_URL`.
  - número: primero `GET /{phone_number_id}` y, si ya está en la Cloud API
    (`platform_type == CLOUD_API`), no hace nada (Meta limita los intentos de
    registro). Si no, `POST /{phone_number_id}/register` con el PIN de 6 dígitos,
    validado antes de llamar a Meta.
  - suscripción: `POST /{waba_id}/subscribed_apps` (idempotente en Meta). Pide
    confirmación explícita en la interfaz: es la que hace que el número real empiece
    a entregar mensajes a la plataforma.
- **El código vive en `autobot.channels.whatsapp.registration`**, el equivalente de
  `channels.telegram.registration`: funciones pequeñas de lectura y escritura sobre
  la Graph API, con el mismo token y la misma versión que `ops.health`.
- **El PIN nunca se guarda**: ni en la base de datos, ni en la auditoría, ni en los
  logs. El operador lo apunta y lo custodia él.
- **Los pasos no son bloqueantes.** El paso bloqueante «Mensaje de un tester» ya
  demuestra que los tres funcionan; `activation.checklist` no cambia.
- **Una escritura ambigua no se reintenta nunca.** Si la conexión se cae después de
  enviar la petición (p. ej. un *timeout* de lectura), el resultado es `unknown` y
  la interfaz pide pulsar «Comprobar» antes de repetir. Si no se llegó a conectar,
  no se envió nada y se dice así.
- **Nunca se devuelve lo que responde Meta**: ni cuerpos de error, ni tokens, ni el
  teléfono que informa Meta. Los errores son mensajes cortos en español; los de
  autenticación (401/403, código 190) dicen «token sin acceso».
- **Queda fuera** añadir el número y verificarlo con el código por SMS o llamada,
  y crear las plantillas: se siguen haciendo en WhatsApp Manager.

## Alternativas consideradas

- **Guardar el PIN como un secreto cifrado más del canal:** permitiría volver a
  registrar el número sin pedírselo al operador, pero cambia el esquema de los
  secretos (`WhatsAppSecrets`) y su cifrado, que requieren su propia aprobación,
  para algo que se hace una vez por número.
- **Un comando de terminal en vez de botones en el panel:** es lo que ya se puede
  hacer a mano con `curl`; el valor de estos pasos es precisamente que el alta guiada de la
  pestaña llegue hasta el final sin salir del panel.
- **Añadir y verificar el número con el código desde el panel:** exige pedir el
  código, esperar el SMS y gestionar sus propios límites de Meta; es raro (una vez
  por número) y WhatsApp Manager ya lo resuelve bien.
- **Hacer bloqueantes los tres pasos nuevos:** duplicaría la prueba real que ya
  hace el paso del tester y obligaría a «Comprobar» los tres antes de activar.

## Consecuencias

- El alta de un número de WhatsApp se completa desde la pestaña «Alta», salvo la
  verificación del número y las plantillas.
- El panel puede cambiar, a petición del operador, el webhook de la app y la
  suscripción a la WABA de un número real; por eso la suscripción pide confirmación
  y cada intento queda auditado.
- Un resultado `unknown` deja al operador la decisión de repetir, tras comprobar.

## Cuándo revisarla

- Si Meta cambia estos endpoints o deja de verificar el webhook de forma síncrona.
- Si aparece un caso real de tener que volver a registrar números con frecuencia
  (migraciones entre portfolios, por ejemplo), reconsiderar guardar el PIN.
