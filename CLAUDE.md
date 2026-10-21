# CLAUDE.md — FlowPilot

Plataforma multi-negocio que atiende por WhatsApp a los clientes de pequeños negocios. Packs iniciales: `salon` (peluquería, reservas sobre Google Calendar) y `bus` (horarios de autobús). El diseño completo está en [`design.md`](design.md); este fichero resume las reglas para trabajar en el repo.

**Estado:** en diseño. Todavía no hay código de la aplicación.

## Idioma

- Responde siempre en español: resúmenes, preguntas, planes, revisiones y descripciones de PR.
- Documentos (`README`, `docs/`, `design.md`, descripciones de PR) en español. Código, identificadores, comandos y mensajes de commit en inglés.

## Forma de trabajo

- Un solo agente; sin framework de agentes ni tareas.
- Todo cambio en una rama (`feat/…`, `fix/…`, `data/<slug>-…`) → PR → CI en verde → revisión humana → merge. Nunca commits directos a `main`.
- Commit o push solo cuando la persona lo pida.
- Si un cambio contradice `design.md`, se actualiza `design.md` en el mismo PR (o se pregunta antes).

## Arquitectura (resumen de `design.md`)

- Monolito modular Django 5.2 + PostgreSQL 18 + Procrastinate, en una VPS con Docker Compose (`web`, `worker`, `admin`, `db`, `caddy`).
- `core/` e `integrations/` no importan Django; `packs/*` solo importan `core` (nunca Django, `integrations` ni otro pack). Lo comprueba `import-linter`.
- Lógica de cada negocio en `packs/<nombre>/`; la plataforma no sabe qué es una cita ni un autobús. A `core/` solo sube lo que usan los dos packs.
- Config y datasets de cada negocio en `tenants/<slug>/` (YAML validado en CI). Nunca secretos ni datos personales en ese directorio.

## Reglas obligatorias

- Todo dato de cliente lleva `tenant_id` y RLS; el tenant se fija solo con `tenant_tx`. Nunca se salta RLS en código de aplicación (solo el servicio `admin` usa el rol con `BYPASSRLS`).
- Todo efecto externo es idempotente; no se reintenta a ciegas un envío ambiguo (`unknown`).
- Ninguna transacción abierta durante llamadas a Meta, Google o Telegram.
- Los trabajos de la cola reciben solo ids; nunca teléfonos ni datos personales en argumentos, candados o logs.
- Credenciales: nunca en claro, nunca en git, nunca en logs.
- El bot nunca adivina en silencio: o hay una respuesta única, o pregunta.
- Toda respuesta respeta los límites de WhatsApp (botones ≤ 3, listas ≤ 10 filas, textos ≤ 4.096); los escenarios lo comprueban.
- Los escenarios de conversación son obligatorios para cada pack y cada cambio de su flujo.
- Requieren aprobación humana explícita: migraciones que tocan RLS, roles o borrados; cambios en cifrado, secretos o firma de webhooks; cambios en la infraestructura del servidor; cualquier acción sobre datos de producción; activar el canal real de un negocio.
- Ningún agente despliega a producción ni ejecuta comandos contra el servidor de producción.

## Referencias

- Bots de origen (solo lectura, para portar código y requisitos): `~/Desktop/Peluqueria` y `~/Desktop/buscaBus`.
- Decisiones: `docs/adr/`. Glosario: `docs/glosario.md`.
