# ADR-006 — Bot de demo con dos puertas y negocios de demostración

**Estado:** aceptada

## Contexto

Antes, cada negocio cliente tenía dos canales: su canal real y un bot de pruebas
interno (siempre por Telegram, con una lista de personas autorizadas por negocio y un
calendario de pruebas propio). Eso complicaba cada pack (`test_calendar_id`,
`testers.telegram`) y mezclaba dos cosas distintas: probar un negocio real antes de
abrirlo, y enseñar la plataforma a un posible cliente nuevo.

Un cliente real solo necesita su canal real (con `status: onboarding` y
`testers.main` para probarlo en ese mismo canal antes de activarlo). Enseñar Autobot
a alguien que aún no es cliente es un problema distinto: necesita un negocio de
mentira, accesible por los dos canales que ofrece la plataforma (WhatsApp y
Telegram), sin que cueste dinero por cada persona que lo prueba ni mezcle datos con un
negocio real.

## Decisión

- **Dos puertas de la plataforma**, no de ningún negocio: un bot de Telegram y un
  número de WhatsApp, cada uno con su propia lista cerrada de personas
  (`DEMO_TELEGRAM_USERS`, `DEMO_WHATSAPP_USERS`). Sin acceso, Telegram responde con un
  rechazo (limitado a 3 veces por hora y persona); WhatsApp no contesta nada, porque
  Meta cobra cada mensaje.
- La primera respuesta de cualquier puerta es un **selector**, en `channels/demo/`: una
  lista de los negocios de demo disponibles. Elegir uno abre una sesión
  (`DemoSession`, por puerta y persona) y, desde ahí, la conversación es la del pack
  real de ese negocio, como si hablara por su canal propio.
- **Los negocios de demo son negocios normales** en `tenants/`, marcados con
  `demo: {description}` en vez de `channel`: sin canal propio, sin `testers`, con
  `status` solo `active` o `paused`. Cada pack nuevo trae el suyo
  (`tenants/demo-<pack>/`) y su escenario de conversación.
- El calendario de un negocio de demo es uno solo (`config.calendar_id`), usado por
  cualquiera de las dos puertas; no hay "calendario de pruebas" aparte.
- Se retira el bot de pruebas por cliente: `test_calendar_id`, `testers.telegram`,
  canal `test` y sus tablas (`TestBotEvent`, `TestSession`) desaparecen. Lo sustituyen
  `DemoEvent`/`DemoSession`, sin RLS (la plataforma no conoce el negocio hasta que el
  selector lo decide) y sin datos personales en sus índices.

## Alternativas consideradas

- **Un pack "demo" que importa los demás**: rompe la regla de que un pack solo
  importa `core`, nunca otro pack; convertiría la demo en un caso especial dentro de la
  capa de negocio en vez de en la plataforma.
- **Un número de WhatsApp y un bot de Telegram por negocio de demo**: multiplica
  credenciales y coste (cada número de WhatsApp de Meta tiene un coste de
  mantenimiento) sin ganar nada; el selector ya resuelve "qué negocio" sin necesitar
  una puerta por negocio.
- **Mantener el canal de pruebas por cliente**: seguiría mezclando dos problemas
  (probar un negocio real vs. enseñar la plataforma) y cada pack seguiría cargando con
  un calendario y una lista de testers que solo existen por eso.

## Consecuencias

- Un cliente real nunca aparece en el selector de demo ni acepta campos de prueba en
  su `tenant.yaml`; la validación del esquema los rechaza.
- Cada pack nuevo necesita su propio negocio de demo y su escenario de conversación
  antes de poder enseñarse (regla añadida a `CLAUDE.md`).
- Encender o apagar una puerta es solo una variable de entorno; encender o apagar un
  negocio de demo es su `status`, igual que cualquier otro negocio.
- La puerta de WhatsApp solo puede probarse en el servidor (un número de Meta tiene una
  única URL de webhook); en local solo se prueba la puerta de Telegram, con un bot de
  desarrollo propio.

## Cuándo revisarla

- Si se necesitara enseñar la plataforma a muchas personas a la vez sin lista cerrada,
  esta decisión (acceso siempre cerrado) habría que revisarla junto con el coste de
  WhatsApp.
