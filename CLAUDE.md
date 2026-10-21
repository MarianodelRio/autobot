# CLAUDE.md — FlowPilot

Plataforma multi-negocio que atiende por WhatsApp (y Telegram, sobre todo para pruebas) a los clientes de pequeños negocios. Packs iniciales: `salon` (peluquería, reservas sobre Google Calendar) y `bus` (horarios de autobús). El diseño completo está en [`design.md`](design.md); este fichero resume las reglas para trabajar en el repo.

**Estado:** en diseño. Todavía no hay código de la aplicación.

## Idioma

- Responde siempre en español: resúmenes, preguntas, planes y revisiones.
- Documentos (`README`, `docs/`, `design.md`) en español. Código, identificadores, comandos y mensajes de commit en inglés.

## Forma de trabajo

- Un solo agente; sin framework de agentes ni tareas.
- Se trabaja directamente sobre `main`; sin ramas ni PR salvo que la persona lo pida. CI debe quedar en verde.
- Commit o push solo cuando la persona lo pida.
- Si un cambio contradice `design.md`, se actualiza `design.md` en el mismo commit (o se pregunta antes).

## Arquitectura (resumen de `design.md`)

- Monolito modular Django 5.2 + PostgreSQL 18 + Procrastinate, en una VPS con Docker Compose (`caddy`, `web`, `worker`, `db`).
- `core/` e `integrations/` no importan Django; `packs/*` solo importan `core` (nunca Django, `integrations` ni otro pack). Lo comprueba `import-linter`.
- Lógica de cada negocio en `packs/<nombre>/`; la plataforma no sabe qué es una cita ni un autobús, y los packs no saben qué canal se usa. Las diferencias entre WhatsApp y Telegram viven solo en sus adaptadores. A `core/` solo sube lo que usan los dos packs.
- Config y datasets de cada negocio en `tenants/<slug>/` (YAML validado en CI). Secretos en `.env` y `secrets.yaml` del servidor; nunca en git.

## Reglas obligatorias

- Todo dato de cliente lleva `tenant_id` y RLS; el tenant se fija solo con `tenant_tx`. Nunca se salta RLS en código de aplicación (el rol `fp_owner`, con `BYPASSRLS`, solo lo usan migraciones, el Admin y comandos de operación).
- Todo efecto externo es idempotente; no se reintenta a ciegas un envío ambiguo (`unknown`).
- Ninguna transacción abierta durante llamadas a Meta, Google o Telegram.
- Los trabajos de la cola reciben solo ids; nunca teléfonos, ids de usuario ni datos personales en argumentos, candados o logs.
- Credenciales: nunca en claro, nunca en git, nunca en logs.
- El bot nunca adivina en silencio: o hay una respuesta única, o pregunta.
- Toda respuesta respeta los límites comunes de los dos canales (botones ≤ 3, listas ≤ 10 filas, textos ≤ 4.096, ids ≤ 64 bytes); los escenarios lo comprueban.
- Los escenarios de conversación son obligatorios para cada pack y cada cambio de su flujo.
- Requieren aprobación humana explícita: migraciones que tocan RLS, roles o borrados; cambios en cifrado, secretos o firma de webhooks; cambios en la infraestructura del servidor; cualquier acción sobre datos de producción; activar el canal real de un negocio.
- Ningún agente despliega a producción ni ejecuta comandos contra el servidor de producción.

## Referencias

- Bots de origen (solo lectura, para portar código y requisitos): `~/Desktop/Peluqueria` y `~/Desktop/buscaBus`.
- Decisiones: `docs/adr/`. Glosario: `docs/glosario.md`.
