# ADR-028 — Aviso inicial en una línea, sin PERSONA ni BAJA

**Estado:** aceptada

## Contexto

El primer mensaje de cada contacto empezaba con un párrafo de la plataforma («Soy el asistente automático de…, no una persona. Uso tus datos solo para… Responsable: … Más información y tus derechos: … Escribe *PERSONA* para hablar con alguien o *BAJA* para dejar de recibir avisos.»). Iba **delante** de la respuesta del pack, así que el menú quedaba debajo de cinco frases legales: el aviso tapaba la respuesta.

Además, la plataforma atendía antes que el pack tres órdenes globales:

- `persona`/`humano`/`hablar con…` respondía con `support.human_contact` y mandaba siempre al dueño un aviso `human_requested`.
- `baja`/`stop`/`parar` y `alta` marcaban `Contact.opt_out`.
- Si el pack esperaba texto libre (`Pack.expects_free_text`, el nombre en `salon`), preguntaba «¿Quieres darte de baja o es tu nombre?».

En la práctica:

- **La atención humana** ya la cubre el propio bot: los dos packs enseñan el teléfono del negocio (`bus` en «ℹ️ Información», `salon` en el menú). Una palabra mágica que nadie conoce no añade nada, y el aviso al dueño era ruido.
- **BAJA** solo tiene sentido con mensajes proactivos. `bus` no tiene ninguno, y en `salon` quien no quiera recordatorios puede decírselo al negocio por teléfono.
- **Las órdenes globales** quitaban palabras a los packs (un pueblo o un nombre «Baja») y obligaban a preguntar «¿orden o nombre?».

## Decisión

- **El aviso inicial es una sola línea discreta, al final.** `core.conversation.first_contact_notice` devuelve «_🤖 Asistente automático de {negocio} · Privacidad:_ {policy_url}» o, sin enlace, «_🤖 Asistente automático de {negocio}_». En la demo, `channels/demo/notice.py` da «_🤖 Demo de Autobot · Privacidad:_ {PLATFORM_PRIVACY_URL}» o, sin enlace, «_🤖 Demo de Autobot_». `with_notice` lo añade como última línea de la última respuesta, separado por una línea en blanco; si no cabe en esa respuesta (1.024 en un interactivo, 4.096 en un texto), va como texto aparte después. Sale **cada vez que se muestra el menú principal** del pack (el pack lo marca con `PackResult.menu = True`) y, además, debajo de la primera respuesta que recibe un contacto aunque no sea el menú (`Contact.notice_sent_at`). No sale en el resto de pasos (listas, horarios, reservas), para no ensuciarlos.
- **Cursiva, no pie.** El pie gris de WhatsApp tiene 60 caracteres (no cabe con el enlace), ya lo usan los packs y Telegram lo descarta. La cursiva (`_…_`) se ve en los dos canales: el adaptador de Telegram la convierte en `<i>`. El enlace va fuera de la cursiva, para que no se le pegue el `_`.
- **Sin órdenes PERSONA ni BAJA.** Se retiran de la plataforma las órdenes `persona`/`humano`/`hablar con…`, `baja`/`stop`/`parar` y `alta`, sus textos, el aviso `human_requested`, la pregunta «¿orden o nombre?» (`fp_cmd:`/`fp_name:`), `Pack.expects_free_text` y el campo `opt_out` de la acción `UpdateContact`. Solo queda `menu` (`menu`, `menú`, `inicio`, `/start`): `core.conversation.is_menu_command`. Esas palabras llegan al pack como cualquier otro texto.
- **Sin `support.human_contact`.** Desaparece del documento del negocio, del panel y de la lista de activación, que solo exige `privacy.policy_url`. Las versiones ya guardadas son inmutables y pueden traer `support`, así que `TenantDocument` lo descarta al cargar en vez de rechazarlo; la siguiente versión guardada ya no lo lleva.
- **Sin `privacy.controller_name`.** El responsable es siempre el propio negocio, así que el aviso no lo repite. `Privacy` lo descarta al cargar versiones antiguas, igual que `support`.
- **Sin `Contact.opt_out`.** Sin orden BAJA nada lo marcaba: la migración 0034 borra `opt_out`/`opt_out_at`, y con ellos el filtro de proactivos, la regla de retención que conservaba el identificador y la columna del panel. Quien no quiere más mensajes lo pide al negocio y el operador lo olvida desde el panel («Olvidar contacto»). Es una migración que contrae el esquema, permitida a mano en el linter porque ninguna versión publicada leía esas columnas (nada estaba en producción).
- **«Contacto» pasa a «Información»** en el menú de los dos packs (mismo id, `menu_info`). En `bus`, la cabecera del menú es solo «🚌 {negocio}» y el cuerpo, «¿Qué necesitas?».

## Alternativas consideradas

- **Que cada pack declare qué órdenes de atención usa** (`salon` con BAJA, `bus` sin nada). Descartada: ninguno de los dos las necesita hoy, y mantener la maquinaria para un caso futuro sin diseño cuesta más que volver a añadirla.
- **Dejar el aviso delante, pero más corto.** Descartada: la primera línea que se lee debe ser la respuesta, no la letra pequeña.
- **Llevar el aviso al pie (`footer`).** Descartada: 60 caracteres, ocupado por el pie del pack, e invisible en Telegram.
- **Conservar las columnas `opt_out` para una baja futura.** Descartada: nada las marca, y olvidar al contacto ya cubre la petición.

## Consecuencias

- El menú lleva siempre una línea de privacidad debajo (y el primer mensaje de un contacto, aunque no sea el menú): quién responde (un asistente automático), de qué negocio y dónde leer la política.
- Nadie puede darse de baja de los recordatorios desde el bot: se pide al negocio y se olvida al contacto. Una cita manual posterior con el mismo teléfono vuelve a crearlo.
- La atención humana depende de que el bot muestre un contacto real: en `bus`, `contact_phone` (obligatorio) en «ℹ️ Información»; en `salon`, `contact_phone` en el propio menú y, si lo hay, `info_text` en «ℹ️ Información».
- Un pack nuevo ya no tiene que reservar palabras ni declarar `expects_free_text`.

## Cuándo revisarla

- Si los recordatorios u otros mensajes proactivos generan peticiones de baja frecuentes: entonces compensa una baja dentro del bot (orden o botón en la plantilla).
