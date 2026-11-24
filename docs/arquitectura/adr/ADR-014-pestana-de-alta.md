# ADR-014 — Pestaña «Alta» guiada por pasos

**Estado:** vigente salvo la pestaña propia: desde el [ADR-027](ADR-027-alta-y-configuracion-en-una-pestana.md) los pasos del alta están dentro de la pestaña «Configuración», cada uno en su sección

## Contexto

El alta de un cliente ya funcionaba, pero está repartida entre la pestaña
«Configuración» (canal, dueño, calendario, horarios) y el diálogo «Activar», sin un
sitio único que diga, paso a paso, qué falta y por qué. Se pide una
pestaña «Alta» con esa vista: cada paso con su estado, por qué importa, qué hacer, un
botón «Comprobar» cuando aplica, y valores con copiar. Ya estaba construida
casi toda la información que esa pestaña necesita mostrar (la lista de
`autobot.tenancy.activation.checklist`, el estado del webhook de Telegram, los
secretos, el email de la cuenta de servicio, el estado de los horarios); falta
reunirla en un solo sitio con una forma común.

## Decisión

- **Un paso es una estructura común,** `SetupStep` (clave, etiqueta, por qué importa,
  estado `ok`/`pending`/`error`, si bloquea la activación, detalle, valores con
  etiqueta/valor/si se puede copiar, y si tiene una acción «Comprobar»). Vive en
  `autobot.panel.services.setup` (no en `core`, porque los pasos de canal citan
  conceptos de Telegram/WhatsApp que `core` no puede importar).
- **Los pasos se montan reutilizando los servicios ya existentes**, no un hook nuevo
  por pack o por adaptador: `tenant_setup(slug)` llama a
  `activation.checklist` (documento, canal, secretos, salud, plantillas, tester,
  dueño), al estado del webhook de Telegram, al email de la cuenta de servicio y al
  estado de los horarios de `bus`, y construye un `SetupStep` por cada uno. Es la
  opción deliberadamente más simple: un pack o canal nuevo que necesite un paso
  genuinamente distinto se añade como una rama más en `tenant_setup`, sin tocar el
  contrato de `Pack` ni el de `ChannelAdapter`. Se reconsidera (ver «Cuándo
  revisarla») si eso deja de ser manejable.
- **`GET /tenants/{slug}/setup`** devuelve la lista completa, solo con lo que ya está
  en caché (nunca llama a un proveedor externo en una petición de lectura).
  **`POST /tenants/{slug}/setup/check/{step}`** ejecuta la comprobación real de ese
  paso concreto (salud del canal, registro del webhook, o la prueba de escritura del
  calendario) fuera de cualquier transacción, audita el resultado y devuelve el
  paso actualizado.
- **La prueba de escritura del calendario** se construye como un paso más de
  `salon`: `CalendarClient.check_write_access()` inserta un evento con id aleatorio,
  en el año 2000, con `private.fp_probe=1` (nunca `fp_key` ni `fp_contact`, para que
  ni el barrido ni el resumen lo confundan con una cita), comprueba que se insertó y
  lo borra. Antes de insertar, borra cualquier resto de una prueba anterior en esa
  ventana (idempotente ante una llamada ambigua). Verificado en real contra el
  calendario de demo de `salon` en local (inserta, confirma y borra; no deja ningún
  evento).
- **El paso de horarios de `bus`** (uno por dataset del pack, vía la plantilla) no
  tiene «Comprobar»: solo lee `tenant_dataset_status`, nunca llama a un proveedor.
  Se busca por `document.pack`, no por `tenant.pack` (que es `None` en un tenant
  degradado por falta justo de ese dataset — el caso donde este paso importa más).
- **La pestaña reemplaza el componente muerto `missing-checklist.tsx`**: se
  borra, porque la pestaña «Alta» cubre lo mismo y más.
- **Los pasos no bloqueantes** (dueño, por ejemplo) se muestran igual, sin impedir
  «Activar».

## Alternativas consideradas

- **Un hook `Pack.setup`/método `ChannelAdapter.setup_steps` desde el principio**
  (la idea original): más generalizable, pero cambia el contrato de `core`
  y de los dos adaptadores para un solo pack con calendario y un solo canal con
  webhook; con dos packs y dos canales, la rama-por-caso de `tenant_setup` es más
  simple de auditar y no obliga a ningún pack futuro a implementar un hook que no
  necesita.
- **Guardar el estado de cada paso en una tabla:** innecesario; cada paso ya se
  puede calcular al vuelo a partir de lo que otras tablas guardan (documento,
  secretos, caché de salud); solo las llamadas lentas a un proveedor se cachean,
  igual que ya hace `ops.health.daily`.

## Consecuencias

- La pestaña «Alta» y la antigua lista de «Configuración» muestran en parte la
  misma información (p. ej. el estado del webhook); es intencionado — la primera es
  la vista guiada, la segunda sigue para editar.
- Un pack o canal nuevo con pasos propios obliga a tocar `tenant_setup` (una función
  de servicio), no un contrato nuevo; aceptable mientras sean pocos.
- La prueba de escritura escribe de verdad en el calendario del cliente durante «Comprobar», aunque sea
  un evento de prueba borrado al momento; debe documentarse así para quien dé de
  alta a un cliente real.

## Cuándo revisarla

- Si un tercer pack con necesidades de alta muy distintas hace que `tenant_setup`
  crezca en ramas difíciles de seguir, pasar al hook por pack que se descartó aquí.
