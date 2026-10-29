# Mejora 01 · Bot de demo

**Estado:** implementada (2026-10-26, pasos 1-5 de §9); quedan las acciones manuales
de §8 por parte de la persona.
**Objetivo de este documento:** que un agente lo implemente de principio a fin sin
tener que decidir nada. Si algo no está aquí o contradice el código, se pregunta.

## 1. Introducción

Hasta ahora cada negocio cliente tenía dos formas de hablar con él: su canal real
(`main`) y el **bot de pruebas** de la plataforma (canal interno `test`, siempre por
Telegram), con un calendario de pruebas propio (`test_calendar_id`) y una lista de
personas autorizadas (`testers.telegram`).

Eso cambia:

1. **Cada cliente tiene solo su bot real**, el canal que elija (WhatsApp o Telegram).
   No hay bot de pruebas, calendario de pruebas ni `testers.telegram` para clientes.
   Para probar un cliente antes de abrirlo sigue existiendo `status: onboarding` con
   `testers.main` (solo contesta a esos ids, en su canal real).
2. **La plataforma tiene un bot de demo** para enseñar Autobot a posibles clientes,
   con **dos puertas**: un bot de Telegram y un número de WhatsApp. Las dos hacen lo
   mismo: la primera respuesta pide elegir negocio y, desde ahí, la conversación es la
   del pack real de ese negocio.
3. **Los negocios de demo son negocios normales** en `tenants/`, marcados como demo y
   sin canal propio: `demo-peluqueria` (pack `salon`, sobre un calendario de la
   persona) y `demo-autobuses` (pack `bus`, con tres líneas inventadas entre Posadas y
   Córdoba). **Cada pack nuevo trae su negocio de demo.**
4. **Solo una lista cerrada de personas** puede usar cada puerta. El resto no recibe
   servicio (en WhatsApp ni siquiera respuesta, porque Meta cobra cada mensaje).
5. La demo corre en la VM de producción como un cliente más, se enciende y apaga por
   puerta (credenciales) y por negocio (`status`), y también se puede lanzar en local.

Es una evolución del bot de pruebas actual (`autobot/channels/test_bot/`): su
selector ya hace casi todo; se generaliza a dos transportes y se restringe a negocios
de demo.

## 2. Decisiones cerradas

| Tema | Decisión |
|---|---|
| Cómo se elige negocio | Selector de la plataforma (no un pack: un pack no puede importar otros) |
| Acceso | Lista cerrada en las dos puertas: `DEMO_TELEGRAM_USERS` y `DEMO_WHATSAPP_USERS` en `.env` |
| Sin acceso | Telegram: "No tienes acceso a esta demo." como mucho 3 veces por hora y usuario. WhatsApp: ninguna respuesta |
| Avisos al dueño de la demo | Como un cliente real: el chat de Telegram de la persona, vinculado con `manage.py owner_invite`. Avisos por WhatsApp: fuera de alcance |
| Calendario de la demo | Uno solo, el de la persona: `calendar_id` del negocio de demo |
| Limpieza automática del calendario de demo | No, de momento |
| Contenido | Lo inventa el agente (§5.10) |
| Migración que borra tablas y filas del canal `test` | **Aprobada por la persona (2026-10-26)** |
| Documento | `docs/mejoras/01-bot-de-demo.md` (este) |

Cambios que siguen necesitando revisión humana explícita al implementarse (regla de
`CLAUDE.md`): las rutas públicas nuevas en `Caddyfile` y el webhook de WhatsApp de la
demo (verificación de firma). Se implementan y se dejan señalados en el commit para
que la persona los apruebe antes del push.

## 3. Modelo resultante

```
Cliente real            tenants/<slug>/      channel: whatsapp|telegram   canal interno "main"
Negocio de demo         tenants/demo-<pack>/ demo: {...}, sin channel     canales "demo_tg" y "demo_wa"

Puerta Telegram  ─┐                     ┌─ demo-peluqueria (salon, calendar_id de la persona)
                  ├─ selector de demo ──┤
Puerta WhatsApp  ─┘   (lista cerrada)   └─ demo-autobuses (bus, 3 líneas)
```

- Canales internos (`autobot.runtime.models.Channel`): `main`, `demo_tg`, `demo_wa`.
  El valor `test` desaparece. Los nombres caben en las columnas actuales
  (`max_length=8`).
- Un contacto de demo existe por negocio y por puerta: la misma persona por Telegram y
  por WhatsApp son dos contactos distintos del mismo negocio de demo (igual que hoy
  `main`/`test`). Cada mensaje sale por la puerta por la que entró su contacto.
- La sesión de demo (qué negocio eligió cada persona) es por puerta y usuario.

## 4. Configuración y ajustes

### 4.1 `tenant.yaml` (`autobot/tenancy/schema.py`)

- Nuevo campo opcional `demo: DemoInfo | None = None`, con
  `class DemoInfo(Strict): description: str = Field(min_length=1, max_length=72)`.
  Es el texto que el selector muestra bajo el nombre del negocio (72 es el límite de
  descripción de fila de WhatsApp). Un negocio es de demo si y solo si `demo` no es
  `None`.
- `channel` pasa a `Channel | None = None`.
- `Testers` pierde `telegram`; queda solo `main`. Un `tenant.yaml` con
  `testers.telegram` debe fallar la validación (el modelo es `extra="forbid"`).
- Validador de modelo nuevo (sustituye y amplía `main_testers_match_the_channel`):
  - Si `demo` está: `channel` debe ser `None`, `testers.main` vacío y `status` debe ser
    `active` o `paused` (`onboarding` y `offboarded` no tienen sentido en una demo).
  - Si `demo` no está: `channel` es obligatorio y se aplica la comprobación actual de
    `testers.main` según el tipo de canal.

### 4.2 Registro (`autobot/tenancy/registry.py`)

- `_with_secrets`: si `tenant.file.channel is None` (demo), no busca secretos,
  `secrets=None` y `main_disabled=["demo tenant: no main channel"]`. `load_registry` no
  registra el aviso "main channel disabled" para negocios de demo.
- `_mark_duplicates` y `_index`: las claves `public_id` y `phone_number_id` solo
  existen si hay `channel`. Se elimina `by_tester` y su indexado.
- `visible_to` se sustituye por `demo_tenants() -> list[LoadedTenant]`: negocios con
  `demo`, no ambiguos. La disponibilidad (estado, degradado) la decide el selector.
- `LoadedTenant` gana la propiedad `is_demo` (`self.file.demo is not None`).

### 4.3 Pack `salon` (`packs/salon/config.py`)

- Se elimina `test_calendar_id` (campo, `nonempty` y la regla "must differ"), y se
  quita de todos los YAML y fixtures. `SalonConfig` ignora hoy los campos extra (no
  tiene `extra="forbid"`); ese comportamiento no se cambia en esta mejora.
- Sin más cambios en el pack: no sabe si habla con una demo.

### 4.4 Calendario ligado (`autobot/runtime/context.py`)

`bound_calendar_id(tenant, channel)`:

- Pack sin `needs_calendar` → `None`.
- `channel == MAIN` y negocio no demo → `config.calendar_id`.
- `channel in (DEMO_TG, DEMO_WA)` y negocio demo → `config.calendar_id`.
- Cualquier otra combinación → `CalendarUnavailable` (un negocio real nunca se usa por
  una puerta de demo ni una demo por `main`).

Se actualiza el docstring del módulo. `can_contact_by_phone` es
`channel == MAIN and tenant.file.channel is not None and tenant.file.channel.type ==
"whatsapp"`: en la demo nunca se escribe a teléfonos sacados del calendario.

### 4.5 Ajustes (`config/settings.py`, `.env.example`, `compose.prod.yaml`)

Se eliminan `TEST_BOT_TOKEN`, `TEST_BOT_WEBHOOK_SECRET` y `TEST_BOT_OPERATORS`. Nuevos:

| Variable | Uso |
|---|---|
| `DEMO_TELEGRAM_TOKEN` | Token del bot de demo. Vacío → puerta Telegram apagada |
| `DEMO_TELEGRAM_WEBHOOK_SECRET` | ≥ 32 caracteres (misma validación que el actual). Vacío → webhook apagado (en local se usa polling) |
| `DEMO_TELEGRAM_USERS` | Ids de Telegram separados por comas (mismo parser `_ids` que hoy) |
| `DEMO_WHATSAPP_PHONE_NUMBER_ID`, `DEMO_WHATSAPP_WABA_ID` | Ids de Meta del número de demo (dígitos) |
| `DEMO_WHATSAPP_DISPLAY_PHONE` | Opcional, solo informativo |
| `DEMO_WHATSAPP_APP_SECRET`, `DEMO_WHATSAPP_ACCESS_TOKEN`, `DEMO_WHATSAPP_VERIFY_TOKEN` | Secretos de la app de Meta del número de demo |
| `DEMO_WHATSAPP_USERS` | Teléfonos (solo dígitos, con prefijo de país) o BSUID, separados por comas. Nuevo parser `_strings` que recorta espacios y descarta vacíos |
| `DEMO_WHATSAPP_MONTHLY_ALERT_THRESHOLD` | Entero, 300 por defecto: mensajes facturables al mes de la puerta WhatsApp antes de avisar |

La puerta WhatsApp está encendida solo si `PHONE_NUMBER_ID`, `WABA_ID`, `APP_SECRET`,
`ACCESS_TOKEN` y `VERIFY_TOKEN` tienen valor. `autobot/ops/logging.py` (filtro de
privacidad) incluye los nuevos secretos en la lista que hoy contiene `TEST_BOT_TOKEN`
y `TEST_BOT_WEBHOOK_SECRET`. `compose.prod.yaml` pasa las variables nuevas en
`x-app-env` y quita las viejas. `.env.example` las documenta en un bloque "Bot de demo".

## 5. Cambios en el código

### 5.1 Modelos y migración (`autobot/runtime/models.py`)

- `Channel`: `MAIN = "main"`, `DEMO_TG = "demo_tg"`, `DEMO_WA = "demo_wa"`. Propiedad o
  constante `DEMO_CHANNELS = (Channel.DEMO_TG, Channel.DEMO_WA)` en el mismo módulo.
- `Notification.Audience`: se elimina `OPS` (solo la usaba el canal `test`); queda
  `OWNER`. Se conserva la columna.
- Se eliminan `TestBotEvent` y `TestSession`. Se añaden, en la sección de tablas de
  plataforma (sin `tenant_id` en la primera, sin RLS en las dos):

```python
class DemoEvent(models.Model):
    """A message received by a demo door, before the selector knows its tenant."""
    class Status(models.TextChoices):
        PENDING = "pending"; DONE = "done"; FAILED = "failed"
    id = UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    channel = CharField(max_length=8, choices=Channel)          # demo_tg | demo_wa
    provider_event_id = CharField(max_length=200)                # update_id o wamid
    payload = JSONField()                                        # el item, como inbound_event
    status = CharField(max_length=8, choices=Status, default=PENDING, db_default=PENDING)
    received_at = DateTimeField()
    # db_table "demo_event"; UniqueConstraint(channel, provider_event_id)
    # Index(received_at, name="demo_event_retention_idx"); __str__ sin ids de usuario

class DemoSession(models.Model):
    """The demo business a person picked, per door."""
    id = UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    channel = CharField(max_length=8, choices=Channel)
    external_id = CharField(max_length=160)                      # id de Telegram, BSUID o teléfono
    tenant = ForeignKey(Tenant, on_delete=CASCADE, related_name="+")
    selected_at = DateTimeField()
    # db_table "demo_session"; UniqueConstraint(channel, external_id)
    # Index(selected_at, name="demo_session_retention_idx"); __str__ sin external_id
```

- `autobot/models.py` exporta los modelos nuevos y deja de exportar los viejos.
- Migración `0008_demo_channels.py` (⚠️ aprobada), en este orden:
  1. `RunSQL` que borra los datos del canal `test`: `DELETE FROM outbound_message
     WHERE channel='test'`, `DELETE FROM conversation WHERE contact_id IN (SELECT id
     FROM contact WHERE channel='test')`, `DELETE FROM contact WHERE channel='test'`,
     `DELETE FROM inbound_event WHERE channel='test'` y `DELETE FROM notification WHERE
     audience='ops'`. Las migraciones corren como `fp_owner` (sin RLS). Sin
     `reverse_sql` (`migrations.RunSQL.noop` al revertir).
  2. `DeleteModel` de `TestBotEvent` y `TestSession`.
  3. `CreateModel` de `DemoEvent` y `DemoSession` con sus restricciones e índices.
  4. `AlterField` de las `choices` de `channel` (contact, inbound_event,
     outbound_message) y de `audience` (solo estado, sin SQL).
  - Los permisos de `fp_app` sobre las tablas nuevas llegan por los `DEFAULT
    PRIVILEGES` de `deploy/postgres/init-roles.sh`; no hace falta `GRANT`.
  - Pasar `makemigrations --check` y `lintmigrations` (si el linter marca el borrado,
    se añade la excepción con un comentario que cite esta aprobación).

### 5.2 Puertas y selector (`autobot/channels/demo/`, sustituye a `test_bot/`)

Se mueve `autobot/channels/test_bot/` a `autobot/channels/demo/` (`selector.py`,
`views.py`, `doors.py`) y se borra el antiguo.

`doors.py` describe cada puerta:

```python
@dataclass(frozen=True)
class Door:
    channel: Channel                  # DEMO_TG o DEMO_WA
    adapter: ChannelAdapter[Any, Any] # TELEGRAM o WHATSAPP
    description: Any                  # None (Telegram) o WhatsAppChannel sintético
    secrets: Any                      # TelegramSecrets o WhatsAppSecrets
    users: frozenset[str]             # lista cerrada

def door(channel: Channel) -> Door | None   # None si esa puerta está apagada
def allowed(door: Door, item: InboundItem) -> bool
```

- Telegram: `TelegramSecrets(bot_token=DEMO_TELEGRAM_TOKEN, webhook_secret=…)` con la
  misma lógica que `test_bot_secrets()` (secreto aleatorio si no hay webhook).
- WhatsApp: `WhatsAppChannel(type="whatsapp", public_id="demowhatsapp",
  app_id=None, waba_id=DEMO_WHATSAPP_WABA_ID, phone_number_id=…,
  display_phone=…)` y `WhatsAppSecrets(app_secret, access_token, verify_token)`.
- `users`: los ids de `DEMO_TELEGRAM_USERS` (enteros de `_ids`) convertidos a texto,
  o los valores de `DEMO_WHATSAPP_USERS`.
- `allowed`: Telegram → `item.external_id in users`. WhatsApp → `item.external_id in
  users` o el teléfono sin `+` (`item.phone`) está en `users` (como `testers.main`).
- `door()` se cachea como hoy `test_bot_secrets()` (`functools.cache`); los tests
  limpian la caché.

`channels/adapters.endpoint(tenant, channel)`:

- `MAIN` → como hoy (afirma que `tenant.file.channel` no es `None`).
- `DEMO_TG`/`DEMO_WA` → `Endpoint(door.adapter, door.description, door.secrets)`; si
  la puerta está apagada, `Endpoint(adapter, description, None)` para que el envío
  falle como hoy cuando falta el token. Se elimina `test_bot_secrets`.

`selector.py` (mismo flujo que hoy, generalizado):

1. `store_event(door, item) -> bool`: guarda el `InboundItem` en `demo_event`
   (`INSERT … ON CONFLICT (channel, provider_event_id) DO NOTHING RETURNING id`, en una
   transacción en `default`, sin RLS) y encola `route_demo_event(event_id)` en la cola
   `INBOUND` con el candado `demo_user_lock(channel, external_id)`. `payload` es
   `item.payload`. Sustituye a `store_update`.
2. `route_demo_event(event_id)`: relee el evento `pending`, lo parsea con
   `door.adapter.parse(payload, door.description)` y:
   - Sin acceso (`not allowed`): Telegram → texto de rechazo con el limitador actual
     (3 por hora); WhatsApp → sin respuesta. En los dos casos se marca `done` y se
     registra "demo message from a user without access" sin ids.
   - `fp_page:<n>` → lista de negocios, página n.
   - `fp_select:<slug>` → si está disponible, `_pick`; si no, "no disponible" + lista.
   - Comando de selector (primera palabra, sin `@bot`, en minúsculas: `/start`,
     `/negocio` o `negocio`) → lista.
   - Cualquier otra cosa: con sesión válida → `store(tenant, [item], door.channel)`,
     actualiza `selected_at` y marca `done`; sin sesión → lista; sesión a un negocio
     no disponible → borra la sesión, "no disponible" + lista.
   - Los botones del selector (`fp_select:`/`fp_page:`) se confirman con
     `door.adapter.acknowledge` (en WhatsApp no hace nada).
3. Disponible = negocio de demo, `status == "active"`, no degradado y no ambiguo.
4. `business_list`: como hoy, una fila por negocio con título `file.name` y
   descripción `file.demo.description`, ordenadas por nombre, 8 por página.
5. `_pick`: envía `PICKED_TEXT`, guarda la sesión (`update_or_create` por `channel` y
   `external_id`) y crea el `menu` sintético con `provider_event_id =
   "select:<provider_event_id>"`, que se guarda con `store` en el canal de la puerta.
   - Telegram: el `_synthetic_menu` actual.
   - WhatsApp: copia profunda del `payload` guardado (un cuerpo de webhook con un solo
     mensaje); en `messages[0]` conserva `from`, `from_user_id`/`user_id` si están,
     `id` y `timestamp`, quita el resto de claves y pone `"type": "text", "text":
     {"body": "menu"}`. Se comprueba que `WHATSAPP.parse(cuerpo, door.description)`
     devuelve un `InboundItem`.
6. Mensajes propios del selector (no son de ningún negocio): se envían directamente
   con `door.adapter.send(door.adapter.render(reply, door.description),
   item.external_id, door.description, door.secrets, uuid7())`, tras `plan_sends` y
   después de marcar el evento `done` (como mucho una vez). Un `Rejected(kind="auth")`
   marca `cache "bot:<channel>:auth"`; un `Sent` lo borra.
7. Textos:

| Constante | Texto |
|---|---|
| `PICK_TEXT` | `👋 Demo de Autobot. Elige el negocio que quieres probar:` |
| `PICKED_TEXT` | `Demo · {name}. Escribe /negocio para cambiar.` |
| `NOT_AVAILABLE_TEXT` | `Ese negocio no está disponible ahora mismo.` |
| `NONE_AVAILABLE_TEXT` | `No hay ninguna demo disponible ahora mismo.` |
| `NO_ACCESS_TEXT` | `No tienes acceso a esta demo.` |

`autobot/runtime/locks.py`: `telegram_user_lock` → `demo_user_lock(channel,
external_id)` = `demo:<16 hex de sha256(channel \x00 external_id)>`.
`autobot/jobs.py`: `ROUTE_TEST_UPDATE` → `ROUTE_DEMO_EVENT = "route_demo_event"`.

### 5.3 Webhooks de las puertas (`autobot/channels/demo/views.py`, `config/urls.py`)

- `POST /webhooks/telegram-demo` (sustituye a `/webhooks/telegram-test`): mismas
  comprobaciones que hoy (limitador por IP, tamaño, `X-Telegram-Bot-Api-Secret-Token`
  antes de parsear, JSON). 404 si la puerta está apagada o no hay
  `DEMO_TELEGRAM_WEBHOOK_SECRET`. Parsea con `TELEGRAM.parse(body, None)` y llama a
  `store_event` con cada `InboundItem`.
- `GET|POST /webhooks/whatsapp-demo` (⚠️ revisión humana): 404 si la puerta está
  apagada.
  - `GET`: `WHATSAPP.verify_subscription(request.GET.dict(), door.secrets)`; como el
    webhook de un negocio (403 y cuenta para el limitador si falla).
  - `POST`: mismo orden que `channels/views._receive` (limitador, tamaño,
    `WHATSAPP.verify` con la firma antes de parsear, JSON). Cada `InboundItem` →
    `store_event`. Cada `StatusItem` → `route_demo_status(item)`.
- `route_demo_status(item)` (en `selector.py`): para cada negocio de demo, en su
  `tenant_tx`, busca `OutboundMessage` del canal `demo_wa` por `id = outbound_ref` (si
  es un UUID válido) o por `provider_message_id`. Al encontrarlo, `store(tenant,
  [item], Channel.DEMO_WA)` y termina. Si no aparece en ninguno, se descarta y se
  registra sin ids. Solo base de datos, sin llamadas externas.
- Errores de base de datos o de la cola → 503, como hoy. Respuesta normal → 200.

### 5.4 Polling y comandos

- `channels/telegram/polling.py`: `source(None)` es la puerta Telegram de demo (nombre
  `"demo bot"`, `accept` = parsear y `store_event` cada item). Mensaje si falta el
  token: `DEMO_TELEGRAM_TOKEN is not set`.
- `management/commands/telegram_poll.py` y `telegram_set_webhook.py`: el objetivo
  `test` pasa a llamarse `demo` (`telegram_set_webhook demo` registra
  `https://<PUBLIC_URL>/webhooks/telegram-demo` con `DEMO_TELEGRAM_WEBHOOK_SECRET`).
- `new_tenant`: nuevo `--demo "<descripción>"`, excluyente con `--channel` (uno de los
  dos es obligatorio). Con `--demo` escribe `demo: {description: …}`, `status:
  paused`, sin `channel` ni `testers`. Sin `--demo`, `testers` queda `{main: []}`.
- `tools/qr.py`: un negocio de demo termina con error "Un negocio de demo no tiene
  canal propio." `tools/migrate_salon_events.py`: rechaza negocios de demo con el
  mismo mensaje que hoy para canales que no son WhatsApp.
- `export_contact` y `forget_contact`: `--channel` admite `main`, `demo_tg` y `demo_wa`.

### 5.5 Runtime

- `runtime/inbound.py`: `store(..., channel)`; en canales de demo el evento va siempre
  `pending` (el selector ya comprobó el acceso). Docstrings sin "test bot".
- `runtime/process.py`:
  - `_proactive_target`: en un canal de demo el contacto debe ser de ese canal y su
    persona seguir en la lista cerrada de la puerta (`allowed` con su `external_id` y
    su `phone_e164`); si no, no se envía (`log.info`, sin ids). Un contacto de la otra
    puerta se descarta con `log.info`, no `warning` (es lo normal en el barrido de un
    calendario compartido por las dos puertas). La comprobación de teléfono enlazado
    (`phone_group`) sigue solo para `main` de WhatsApp, protegida con
    `tenant.file.channel is not None`.
  - `_contact_by_phone`: igual que hoy (solo `main` de WhatsApp).
  - `_notify_owner`: sin distinción de canal; siempre `Audience.OWNER` y el texto tal
    cual. Un negocio de demo avisa a su `owner` igual que un cliente.
- `runtime/notifications.py`: se elimina la rama `Audience.OPS`.
- `runtime/periodic.py` (`channels_for`):
  - Negocio de demo con `status == "active"` y no degradado → las puertas encendidas
    (`DEMO_TG` si `door(DEMO_TG)`, `DEMO_WA` si `door(DEMO_WA)`).
  - Negocio real → `[MAIN]` si `is_active` (como hoy). Ya no hay canal `test`.
  - Se quita el prefijo `test:` de las claves de idempotencia: un mismo recordatorio
    se crea en la puerta del contacto, y en la otra puerta se descarta sin consumir la
    clave (`create_proactive` no se llama si `_proactive_target` devuelve `None`).
- `runtime/context.py`: §4.4.
- `runtime/retention.py`: `DemoEvent` a los 7 días y `DemoSession` a los 30, como hoy
  las tablas del bot de pruebas.
- `runtime/privacy.py`:
  - `test_bot_events` → `demo_events(tenant_id, event_ids=None)`: `DemoEvent` cuyo
    `(channel, provider_event_id)` coincide con eventos de demo del negocio, quitando
    el prefijo `select:`.
  - `export_data` y `forget`: contactos de canales de demo incluyen y borran sus
    `DemoSession` (`channel`, `external_id`) y sus `DemoEvent`. `purge` borra los
    `DemoEvent` y `DemoSession` del negocio. `MODELS` cambia `TestSession` por
    `DemoSession`.

### 5.6 Operación (`ops/health.py`, `ops/check.py`, `admin.py`, `ops/views.py`)

- `whatsapp_health` se separa en una función que recibe `(channel, secrets, templates)`
  y se usa para negocios reales (como hoy) y para la puerta WhatsApp de demo (con las
  plantillas de los packs de los negocios de demo activos).
- `tenant_health`: en un negocio de demo no se emite `channel_disabled` ni se comprueba
  canal propio; la salud del pack se comprueba por cada puerta encendida.
- `ops_check`:
  - `tenant_unavailable` no se emite para negocios de demo salvo si están degradados.
  - Alertas de autenticación: `bot:demo_tg:auth` y `bot:demo_wa:auth` (de la caché del
    selector) y `last_error` con `auth:` en mensajes de canales de demo → "🔴 Bot de
    demo (Telegram|WhatsApp): envío rechazado por autenticación."
  - Salud diaria del bot de Telegram de demo (como hoy la del bot de pruebas) y de la
    puerta WhatsApp de demo.
  - Facturación: mensajes `billable` del canal `demo_wa` este mes, sumando los negocios
    de demo, por encima de `DEMO_WHATSAPP_MONTHLY_ALERT_THRESHOLD` → 🟡
    `billing:demo_wa`.
- `admin.py`: la vista de estado muestra `main` en negocios reales y `demo_tg`/`demo_wa`
  en los de demo. Reenviar un `unknown` de demo es elegible si su puerta está encendida.
- `/health` no cambia.

### 5.7 Infraestructura y local

- `Caddyfile` (⚠️ revisión humana): rutas públicas `/webhooks/whatsapp/*
  /webhooks/telegram/* /webhooks/telegram-demo /webhooks/whatsapp-demo /health`.
  `tools/check_prod_config.py` comprueba las rutas nuevas (y que la vieja da 404).
- `compose.yaml`: servicio `demo-poller` con `profiles: [demo]`, mismo `x-app`,
  `command: python manage.py telegram_poll`, `restart: unless-stopped`, dependiente de
  `db`. Así la demo por Telegram queda siempre encendida en local sin depender de una
  terminal.
- `Makefile`: `demo-up` (`docker compose --profile demo up -d`), `demo-down`
  (`docker compose --profile demo stop demo-poller`) y `telegram-poll` sigue igual
  (polling en primer plano del bot de demo o de `SLUG`).
- En local se usa **otro bot de Telegram** distinto del de producción: un bot con
  webhook no admite polling. WhatsApp de demo solo en la VM (un número solo tiene una
  URL de webhook).

### 5.8 Encender y apagar

| Qué | Cómo |
|---|---|
| Una puerta | Sus variables en `.env` (vacías = apagada) y reiniciar `web`/`worker` |
| Un negocio de demo | `status: active` o `paused` en su `tenant.yaml` y desplegar |
| Quién entra | `DEMO_TELEGRAM_USERS` / `DEMO_WHATSAPP_USERS` y reiniciar |
| Demo local | `make demo-up` / `make demo-down` |

### 5.9 Lo que se borra o renombra (resumen para buscar)

`TEST_BOT_TOKEN`, `TEST_BOT_WEBHOOK_SECRET`, `TEST_BOT_OPERATORS`, `Channel.TEST`,
`"test"` como canal, `testers.telegram`, `by_tester`, `visible_to`,
`test_calendar_id`, `test_bot_secrets`, `TestBotEvent`, `TestSession`,
`test_bot_event`, `test_session`, `telegram_user_lock`, `ROUTE_TEST_UPDATE`,
`route_test_update`, `store_update`, `Audience.OPS`, `/webhooks/telegram-test`,
`channels/test_bot/`, "bot de pruebas" en textos y docs (pasa a "bot de demo"). Al
terminar, `git grep -nE "TEST_BOT|Channel\.TEST|test_calendar|testers\.telegram|test_bot|TestSession|TestBotEvent|telegram-test|bot de pruebas"`
solo puede devolver este documento.

### 5.10 Negocios de demo

Se crean con `manage.py new_tenant … --demo` (ids generados por el comando, nunca a
mano) y después se completan.

**`tenants/demo-peluqueria/tenant.yaml`** · `name: Peluquería de Prueba` · `pack:
salon` · `demo.description: "Reserva, mueve o cancela una cita"` · `status: paused`
hasta que la persona ponga su calendario (§8) · `owner` sin chat vinculado (lo
vincula la persona con `manage.py owner_invite`; `notify: [booking_created,
booking_cancelled, booking_moved, move_cancel_failed]`). `config`:

- `business_name: Peluquería de Prueba`, `contact_phone: "600 000 000"`.
- `calendar_id: PENDIENTE-calendario-de-demo` (marcador explícito, no un id
  inventado; la persona lo sustituye).
- `services`: `corte` (Corte de pelo, 15 €, 30 min, presencia 30), `corte_barba`
  (Corte y barba, 20 €, 45, 45), `tinte` (Tinte, 35 €, 60, 90), `peinado` (Lavado y
  peinado, 18 €, 30, 30). Respetar `duration_min ≤ client_presence_min`.
- `opening_hours`: lunes a viernes `09:30-14:00` y `17:00-20:30`; sábado
  `09:30-14:00`.
- `slot_step_min: 30`, `min_notice_min: 30`, `booking_window_days: 14`,
  `max_active_bookings: 3`.
- `reminders_enabled: true`, `reminder_window_hours: [0, 2]`: el recordatorio llega
  hasta dos horas antes de la cita, para poder enseñarlo en directo.
- `manual_confirmations_enabled: false`, `special_event` inactivo.
- `info_text`: "Esto es una peluquería de prueba de Autobot. Las citas se guardan
  en un calendario de demostración."

**`tenants/demo-autobuses/`** · `name: Autobuses de Prueba` · `pack: bus` ·
`demo.description: "Consulta horarios entre pueblos"` · `status: active`. `config`:
`business_name: Autobuses de Prueba`, `contact_phone: "600 000 000"`, `office_hours`
lunes a viernes `09:00-14:00`, sin `links`, `start_menu_towns: [Posadas, Córdoba,
Almodóvar del Río, Palma del Río]`, `next_day_search_days` por defecto.

Dataset `datasets/timetable/` (formato de `docs/packs/bus.md`; copiar la estructura
de `tenants/autocares-ss/datasets/timetable/` y simplificar):

- `paradas.yaml`: localidades `posadas`, `almodovar-del-rio` (alias `almodovar`),
  `cordoba`, `palma-del-rio` (alias `palma`); paradas `POS`, `ALM`, `COR`, `PAL`, una
  por localidad. Sin `no_vendibles` ni pendientes.
- `calendario.yaml`: `vigencia: 01/01/2026 - 31/08/2027`, los mismos festivos y el
  mismo `curso` 2026-27 que Autocares (sin festivos locales),
  `sin_servicio_todas_las_lineas: [25/12, 01/01]`. Comentario arriba: "Demo: ampliar
  la vigencia cada verano junto con el curso".
- `observaciones.yaml`: `E`, `tipo: aviso`, ámbito `viaje`: "Sale de la estación de
  autobuses de Córdoba"; y `D`, `tipo: aviso`, ámbito `linea`: "Los domingos solo
  circula un viaje por sentido". Solo avisos: las condiciones necesitan lógica del
  motor.
- `lineas/posadas-cordoba.yaml` (Posadas – Almodóvar del Río – Córdoba), temporada
  `anual`: lunes a viernes, ida POS→ALM→COR a las 07:00, 09:30, 14:00 y 18:30 (15 min
  hasta Almodóvar, 45 hasta Córdoba); vuelta COR→ALM→POS a las 08:30, 13:00, 15:30 y
  20:00; sábados 09:30 y 14:00 de ida y 13:00 y 20:00 de vuelta; domingos y festivos
  `sin_servicio`.
- `lineas/posadas-cordoba-directo.yaml` (directo, sin parada), `anual`: lunes a
  viernes POS→COR 06:45 y 16:00 (35 min), COR→POS 15:00 y 19:30, con la marca `E` en
  las salidas de Córdoba; resto de días `sin_servicio`.
- `lineas/cordoba-palma-del-rio.yaml` (Córdoba – Almodóvar – Posadas – Palma del Río),
  `anual`: todos los días incluidos domingos y festivos, una ida COR→PAL a las 11:00 y
  una vuelta PAL→COR a las 17:00 (Almodóvar +25, Posadas +40, Palma +60 min), con el
  aviso de domingos en la línea.
- Pasar `make bus-formatear` y `make bus-validar TENANT=demo-autobuses` sin errores.
  El dataset no se publica con `bus-publicar` (no hay empresa que revise el PDF).

Si el validador rechaza algún detalle (por ejemplo, una observación de ámbito no
permitido), se corrige lo mínimo para que valide y se anota en el commit.

## 6. Tests

Mantener verde todo `make check`. Se adaptan los tests que usan lo borrado
(`git grep` de §5.9 sobre `tests/` y `src/**/tests/`; hoy:
`tests/integration/test_test_bot.py`, `test_channel_health.py`, `helpers.py`,
`salon_helpers.py`, `test_bus_pack.py`, `test_context.py`, `test_models.py`,
`test_ops.py`, `test_retention.py`, `test_salon_concurrency.py`,
`test_salon_sweep.py`, `test_telegram_commands.py`, `test_webhooks.py`,
`tests/isolation/test_isolation.py`, `tests/tenancy/helpers.py`,
`tests/tenancy/test_registry.py`, `tests/test_settings.py`, `tests/tools/test_qr.py`,
y los de `packs/salon/tests` con `test_calendar_id`). `test_test_bot.py` pasa a
`tests/integration/test_demo.py`.

Tests nuevos, como mínimo:

- **Esquema y registro:** demo válido; demo con `channel`, con `testers.main` o con
  `status: onboarding` rechazado; negocio real sin `channel` rechazado;
  `testers.telegram` rechazado; `demo.description` > 72 rechazado; un demo no
  produce aviso de canal deshabilitado ni entra en `by_public_id`.
- **`bound_calendar_id`:** las cuatro combinaciones de §4.4.
- **Selector, parametrizado por puerta (Telegram y WhatsApp):** lista al primer
  mensaje; elegir → aviso "Demo · …" y después el menú del pack; mensaje con sesión →
  llega al negocio en el canal de la puerta; `/negocio` y `negocio`; paginación;
  negocio `paused` o degradado no aparece y una sesión hacia él da "no disponible";
  un negocio real nunca aparece; sin acceso → Telegram responde como mucho 3 veces
  por hora, WhatsApp nunca responde; reintento del mismo evento no repite respuestas;
  el `menu` sintético de WhatsApp se parsea a `InboundItem`.
- **Webhook WhatsApp de demo:** GET con `verify_token` correcto/incorrecto; POST con
  firma inválida (401, cuenta para el limitador); `phone_number_id` ajeno descartado;
  puerta apagada → 404; un estado de entrega llega al `outbound_message` correcto del
  negocio de demo; un estado desconocido se descarta.
- **Webhook Telegram de demo:** los casos actuales del de pruebas con la ruta nueva.
- **Proactivos y barrido:** recordatorio de una cita creada por la puerta WhatsApp se
  envía por WhatsApp (plantilla) y no por Telegram, y viceversa; persona quitada de
  la lista cerrada → no se envía; `channels_for` según puertas encendidas y estado.
- **Avisos al dueño:** un `NotifyOwner` de una demo crea `Notification` con audiencia
  `owner`.
- **Privacidad y retención:** exportar/olvidar un contacto `demo_wa` incluye y borra su
  sesión y sus eventos de demo; retención de `DemoEvent` y `DemoSession`.
- **Aislamiento:** `PLATFORM_MODELS` = `{DemoSession}`; `DemoEvent` no tiene
  `tenant_id`.
- **Negocios de demo:** la validación de tenants de CI incluye los dos;
  `demo-autobuses` pasa `bus_validar`; un escenario de conversación por pack sobre el
  negocio de demo (consulta Posadas → Córdoba un lunes con la línea directa y la
  normal; reserva completa con `FakeCalendar` en `demo-peluqueria`, con el
  `calendar_id` marcador sustituido en el test).
- **Despliegue/config:** `check_prod_config` con las rutas nuevas.

## 7. Documentación

- `docs/adr/ADR-006-bot-de-demo.md` (nuevo, mismo formato que los otros, `Estado:
  aceptada`): contexto (clientes con un único canal; necesidad de enseñar el producto
  por WhatsApp y Telegram), decisión (selector de plataforma con dos puertas y
  negocios de demo normales; lista cerrada; sin canal de pruebas por cliente),
  alternativas descartadas (pack "demo" que importe otros packs; un número de WhatsApp
  por demo; mantener el canal de pruebas por cliente) y consecuencias.
- `docs/adr/ADR-003-packs.md`: quitar "y todos se prueban desde un bot de Telegram
  compartido"; añadir que cada pack trae su negocio de demo.
- `CLAUDE.md`: el selector vive en `channels/demo/`; regla nueva "Cada pack nuevo
  incluye su negocio de demo en `tenants/demo-<pack>/` y su escenario"; descripción
  inicial sin "bot de Telegram compartido para probar cualquier negocio" (pasa a "un
  bot de demo, por WhatsApp y Telegram, para enseñar los packs").
- `README.md`: sección "Bot de demo en local" (sustituye a "Bot de pruebas en local"):
  bot de Telegram de desarrollo propio, `DEMO_TELEGRAM_TOKEN` y `DEMO_TELEGRAM_USERS`
  en `.env`, `make demo-up`, `/start`.
- `docs/packs/salon.md`: sin `test_calendar_id`; la prueba de cambios se hace con
  `FakeCalendar` o con `demo-peluqueria`.
- `docs/runbooks/alta-baja-negocio.md`: sin `testers.telegram` (paso 3) ni calendario
  de pruebas (paso 5); el paso 9 prueba con `testers.main` en el canal real en
  `onboarding`. Sección nueva "Negocio de demo de un pack nuevo".
- `docs/runbooks/02-negocio-o-canal.md`, `04-calendar.md`, `09-rotar-secretos.md`:
  `test`/bot de pruebas → puertas de demo y sus variables.
- `docs/runbooks/demo.md` (nuevo): qué es, cómo encender/apagar (§5.8), añadir o
  quitar personas, alta de la puerta WhatsApp (checklist de
  `alta-baja-negocio.md`, plantillas `confirmacion_cita` y `recordatorio_cita` en el
  número de demo, webhook `https://api.<dominio>/webhooks/whatsapp-demo` con
  `DEMO_WHATSAPP_VERIFY_TOKEN`), `telegram_set_webhook demo` en el servidor, y
  renovación anual del calendario de `demo-autobuses`.
- `docs/puesta-en-marcha.md`: el bot de pruebas de desarrollo y de producción pasan a
  ser los bots de demo; los calendarios de desarrollo pasan a ser el calendario de
  `demo-peluqueria`; DM Barber sin calendario de pruebas ni prueba desde el bot de
  pruebas (se prueba en `onboarding` con `testers.main`); nueva sección "Demo por
  WhatsApp" con los pasos de §8.

## 8. Acciones manuales (de la persona; ningún agente las da por hechas)

1. Crear dos bots de Telegram de demo con @BotFather: uno para producción y otro para
   local.
2. Proyecto de Google Cloud con cuenta de servicio (`google_sa.json`), un calendario
   "Autobot demo" compartido con ella ("Hacer cambios en los eventos"), y su id en
   `calendar_id` de `demo-peluqueria`; después `status: active`.
3. Bot de avisos (`NOTIFY_BOT_TOKEN`) y `manage.py owner_invite demo-peluqueria` para
   vincular el chat de Telegram de la persona.
4. Rellenar `DEMO_TELEGRAM_USERS` y `DEMO_WHATSAPP_USERS`.
5. Número de WhatsApp de demo: Business Portfolio, app, número, token permanente,
   plantillas aprobadas y webhook a `/webhooks/whatsapp-demo`; variables
   `DEMO_WHATSAPP_*` en el `.env` del servidor.
6. Aprobar los cambios ⚠️ de `Caddyfile` y del webhook de WhatsApp de demo.

## 9. Orden de implementación

Cada paso es un commit con su código, tests y docs, con `make check` verde:

1. Esquema, registro y config: `demo`, `channel` opcional, fuera `testers.telegram` y
   `test_calendar_id`, `bound_calendar_id`, `new_tenant --demo`, `qr` y
   `migrate_salon_events`.
2. Canales internos y puerta Telegram: `Channel`, migración `0008`, `DemoEvent`,
   `DemoSession`, `channels/demo/` con la puerta Telegram, ajustes `DEMO_TELEGRAM_*`,
   runtime (§5.5), operación (§5.6), privacidad y retención, polling y comandos,
   ruta `/webhooks/telegram-demo` en `Caddyfile` y `check_prod_config`.
3. Puerta WhatsApp: ajustes `DEMO_WHATSAPP_*`, `doors`, webhook, `route_demo_status`,
   salud y facturación, ruta en `Caddyfile`.
4. Negocios de demo y local: `demo-peluqueria`, `demo-autobuses`, escenarios,
   `demo-poller`, `make demo-up/demo-down`.
5. Documentación de §7 y repaso final del `git grep` de §5.9.

## 10. Criterios de aceptación

- Con `make demo-up` y las variables locales de Telegram, `/start` al bot de demo
  muestra "Autobuses de Prueba" (y "Peluquería de Prueba" si está `active`); elegir
  uno da el menú de su pack; `/negocio` cambia; una persona fuera de la lista recibe
  el rechazo.
- Ningún cliente real aparece en el selector; un cliente real no tiene ni acepta
  `test_calendar_id` ni `testers.telegram`.
- La puerta WhatsApp, con sus variables, hace lo mismo (verificado con tests y, cuando
  exista el número, a mano), y no contesta a números fuera de la lista.
- Una reserva en la demo de peluquería aparece en el calendario de demo, el aviso
  llega al Telegram del dueño de la demo y el recordatorio llega por la puerta por la
  que se reservó.
- `git grep` de §5.9 limpio y `make check` verde.

## 11. Fuera de alcance

Avisos al dueño por WhatsApp · limpieza automática del calendario de demo · acceso
público sin lista · selector para clientes reales · varias puertas por cliente real.
