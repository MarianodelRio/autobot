# Mejora 02 · Bot de dueños: avisos, resumen mensual y estado a demanda

**Estado:** implementada (2026-10-29), con el diseño cerrado con la persona ese mismo
día. Las aprobaciones de §10 las dio la persona antes del paso 4. Commits: `1fc88f6`
(pasos 1 y 2), `0181aff` (paso 3) y `785d9ef` (pasos 4 y 5), más uno de cierre con los
tests y la documentación que faltaban. Siguen pendientes los pasos manuales de §10
(anotados en `docs/puesta-en-marcha.md`); no se ha probado nada contra Telegram, Meta
ni Google reales.

La primera versión (resumen mensual sobre `MetricEvent`, commit `f3dd9df`) es el punto de
partida que describe §3; el resto del documento describe el estado final.

## 1. Qué se construye

El dueño de cada negocio tiene **un único bot de Telegram de la plataforma** (el bot de
avisos que ya existe, `NOTIFY_BOT_TOKEN`). Ese bot pasa de ser solo de salida a ser un
pequeño asistente:

1. **Avisos puntuales** (ya existen, no cambian): cita creada, cancelada, movida, fallo
   al mover (`NotifyOwner` + `owner.notify`).
2. **Resumen mensual automático** (ya existe, se rehace): el día 1 de cada mes a las
   12:00 hora del negocio, con las cifras del mes anterior completo. Se activa con
   `owner.summary_monthly: true`.
3. **Asistente con menú** (nuevo): el dueño escribe cualquier cosa y el bot responde con
   un saludo y botones. De momento hay dos opciones:
   - **📊 Cómo va el mes**: cifras del mes en curso, desde el día 1 hasta este momento.
   - **✉️ Contacto**: el correo del administrador de la plataforma.

   El menú es una lista declarativa: añadir una opción en el futuro es añadir una entrada
   (§6.3).
4. **Vinculación cómoda** (nuevo, sustituye a `notify_link`): el operador genera un
   enlace `t.me/<bot>?start=<código>`. El dueño lo abre, pulsa *Iniciar* y queda
   conectado al momento, sin editar YAML ni desplegar (§5).

## 2. Decisiones (cerradas con la persona, 2026-10-29)

| # | Decisión | Por qué |
|---|---|---|
| D1 | El `chat_id` del dueño se guarda en base de datos (tabla `owner_link`) y **sale del YAML** (`owner.telegram_chat_id` desaparece). | Es lo que escala: dar de alta a un dueño no exige commit ni despliegue, y un dato personal deja de estar en git. Con el `chat_id` en YAML, el enlace solo podría decirle al operador qué línea añadir. |
| D2 | `owner_link` y `owner_event` son **tablas de plataforma sin RLS**, igual que `demo_session`/`demo_event` (ADR-006). | Al llegar un mensaje al bot no se sabe aún de qué negocio es: hay que buscar el negocio *por* `chat_id`. **Requiere aprobación explícita** (§10). |
| D3 | Un `chat_id` puede estar conectado como mucho a **un negocio real**. Solo los negocios de demo pueden compartir chat entre sí. | Lo pidió la persona. Con varios negocios de demo, "Cómo va el mes" responde con un bloque por negocio, sin preguntar a cuál se refiere. |
| D4 | **Las citas de `salon` salen del calendario**, no de mensajes ni de `MetricEvent`. | Hay citas manuales. El calendario es la fuente de verdad: una cita borrada (cancelada) o movida ya no está, y nunca se cuenta dos veces. |
| D5 | Una cita es **un evento cuyo título empieza por el nombre de un servicio**, igual que los que crea el bot (`"<Servicio> - <Nombre>"`), o un evento creado por el bot. Cualquier otro evento (vacaciones, comida, `[CFG] …`, recados) es del peluquero y **no cuenta**. | Se pedirá a cada peluquero que titule sus citas manuales como las automáticas. |
| D6 | **Sin línea de citas canceladas.** Solo cuentan las citas que hay en el calendario en el periodo. | Lo pidió la persona. |
| D7 | Los **ingresos estimados** son la suma, cita a cita, del `price_eur` **actual** del servicio de cada cita. | Una cita manual no guarda precio. Si cambia una tarifa, el resumen de un mes pasado pedido más tarde cambia también; se documenta. |
| D8 | El **estado a demanda solo mira el pasado**: citas cuyo inicio está entre el día 1 a las 00:00 y ahora. No se muestran "citas por venir". | Lo pidió la persona. |
| D9 | El **coste de mensajería** suma todo lo que Meta cobra, usando lo que Meta dice de cada mensaje (`billable` y `pricing_category` del webhook de estados), por un precio aproximado por categoría. Ya no se calcula la franja gratuita por nuestra cuenta. | Desde el 1-10-2026 Meta cobra también "service" (con 1.000 gratis al mes **por número**) y "utility" dentro de la ventana de 24 h. Meta ya aplica esas reglas y las marca en `billable`, incluido el número de demo compartido entre negocios. |
| D10 | El resumen automático sale **el día 1 a las 12:00 hora local** del negocio. | Lo pidió la persona. |
| D11 | Un chat no conectado recibe una respuesta de "no vinculado" con el correo de contacto. | Aprobado por la persona. |
| D12 | El webhook entrante del bot lleva `secret_token`, como los demás bots de Telegram. | Aprobado por la persona el 2026-10-29 (cambio en la firma de webhooks). |
| D13 | Los negocios de demo responden a "Cómo va el mes" aunque estén `paused`, porque lo importante en la demo es enseñar la función. Un negocio real que no está `active` responde con un aviso (§6.4). | Lo pidió la persona: la demo no necesita un resumen perfecto. |
| D14 | `bus` sigue contando "consultas de horario" con `RecordMetric`/`MetricEvent`. | No tiene calendario. `salon` deja de emitir `RecordMetric`. |

## 3. Punto de partida (lo que ya hay en `main`)

- `src/autobot/runtime/summary.py` contiene `previous_month`, `month_to_date`,
  `dispatch_owner_summaries`, `build_summary` (sobre `MetricEvent` + `OutboundMessage`),
  `_messaging_cost` (franja gratuita calculada a mano, precios `PRICE_EUR` erróneos) y
  `_render`.
- `src/autobot/jobs.py` tiene el periodic diario `DISPATCH_OWNER_SUMMARIES` a las 11:00 UTC.
- `src/core/actions.py:RecordMetric` y `src/autobot/runtime/models.py:MetricEvent` (tabla
  `metric_event`, migración `0009`, con RLS) se **mantienen**.
- `src/core/pack.py` contiene `SummaryMetric` y `Pack.summary_metrics`, que **se sustituyen**
  por un gancho `Pack.summary` (§4.1).
- `src/packs/salon/conversation.py` emite `RecordMetric` en `create()` y en `cancel()`; esas
  emisiones **se eliminan**.
- `src/packs/bus/conversation.py:539` emite `RecordMetric("schedule_query")`; **se mantiene**.
- `src/autobot/tenancy/schema.py:Owner` tiene `telegram_chat_id`, `notify` y
  `summary_monthly` con su validador. **Se quitan** `telegram_chat_id` y el validador.
- `src/autobot/runtime/notifications.py` tiene `bot_secrets()` con un secreto de webhook
  ficticio (`"-" * 32`) y `deliver(text, …)`.
- `src/autobot/management/commands/notify_link.py` exige que el bot no tenga webhook,
  porque usa `getUpdates`. **Se elimina**: con webhook ya no puede funcionar.
- `src/autobot/ops/health.py:telegram_health(..., outbound_only=True)` da error si el bot
  de avisos tiene webhook. **Cambia**: ahora tiene que tenerlo.
- Hay tests en `tests/integration/test_summary.py`, `tests/integration/test_notifications.py`,
  `tests/integration/test_process.py` (RecordMetric), `src/packs/salon/tests/test_booking.py`,
  `src/packs/salon/tests/test_management.py` y `src/packs/bus/tests/test_metrics.py`.

## 4. Resumen: cálculo

### 4.1 Contrato pack ↔ plataforma (`src/core/pack.py`)

Se elimina `SummaryMetric` y `Pack.summary_metrics`. Se añade:

```python
@dataclass(frozen=True)
class SummaryLine:
    """One line of the owner's summary, contributed by the pack."""

    icon: str  # one emoji
    label: str
    value: Decimal
    unit: Literal["count", "eur"] = "count"
    note: str | None = None  # shown in brackets after the value


type SummaryHook = Callable[[PackContext, datetime, datetime, Mapping[str, Decimal]], list[SummaryLine]]

# in Pack:
    summary: SummaryHook | None = None
```

- La plataforma llama a `pack.summary(ctx, start, end, recorded)`. `ctx` es un
  `PackContext` sin contacto, como el de un periodic: se construye con `build_context(tenant,
  Channel.MAIN, contact=None, state={}, event_id=None)`. Para un negocio de demo,
  `bound_calendar_id` ya da su calendario con cualquier canal. `[start, end)` es el
  periodo, con fechas *aware* en la zona horaria del tenant. `recorded` son los totales
  de `MetricEvent` del tenant en ese periodo, por `kind`.
- El gancho **se ejecuta sin transacción abierta**, porque `salon` llama a Google Calendar.
  Puede lanzar `TransientError`/`PermanentError` (de `core.errors`) o las de Calendar.
- La plataforma no sabe qué es una cita: solo pinta las líneas.

### 4.2 `salon` (`src/packs/salon/summary.py`, nuevo)

```python
def summarize(ctx, start, end, recorded) -> list[SummaryLine]:
    cfg = configuration(ctx)
    count, revenue, unpriced = 0, Decimal(0), 0
    for event in calendar(ctx).list_events(start, end):
        if event.all_day or not (start <= event.start < end):
            continue  # list_events also returns events that only overlap the window
        if not is_appointment(event, cfg):
            continue
        count += 1
        key = service_of(event, cfg)
        price = cfg.services[key].price_eur if key is not None else None
        if price is None:
            unpriced += 1
        else:
            revenue += price
    return [
        SummaryLine("✂️", "Citas", Decimal(count)),
        SummaryLine("💶", "Ingresos estimados", revenue, unit="eur",
                    note=f"{unpriced} sin precio" if unpriced else None),
    ]
```

Reglas exactas de `is_appointment` / `service_of`:

1. Si `parse_cfg(event.summary)` devuelve algo (`[CFG] …`), **no** es cita.
2. **Evento del bot** (`event.private.get("fp_key")` no vacío): **siempre** es cita.
   El servicio es `event.private["fp_service"]` si está en `cfg.services`. Si no (servicio
   retirado de la configuración), se intenta por título (regla 3). Si tampoco, cuenta como
   cita sin precio.
3. **Por título**, para eventos manuales y como reserva de la regla 2. Se normaliza el
   título con `core.text.fold` y se colapsan los espacios (`" ".join(s.split())`); lo mismo
   con el `name` de cada servicio. Coincide si el título normalizado:
   - es **exactamente** el nombre del servicio (`"tinte"`), o
   - empieza por el nombre seguido de espacios opcionales y un guion `-`, `–` o `—`
     (`"corte de pelo - juan"`, `"corte de pelo– juan"`).

   Si coinciden varios servicios, gana el **nombre más largo** (`"Corte y barba - X"` no
   debe tomarse por `"Corte"`). Un evento manual sin coincidencia **no es cita** (D5),
   aunque tenga `Telefono:` en la descripción.
4. Los eventos `cancelled` ya los descarta `CalendarClient._list`. Los de todo el día
   (`all_day`) nunca son cita.

Se elimina en `src/packs/salon/conversation.py`:
- los `RecordMetric` de `create()` (incluido `booking_revenue`) y de `cancel()`;
- el import de `RecordMetric` y `Decimal` si quedan sin uso;
- el comentario "Decision 11 of the summary proposal".

En `src/packs/salon/pack.py`, `summary_metrics=[…]` se sustituye por `summary=summary.summarize`.

### 4.3 `bus` (`src/packs/bus/pack.py`)

```python
def summarize(ctx, start, end, recorded):
    return [SummaryLine("🚌", "Consultas de horario", recorded.get("schedule_query", Decimal(0)))]
```

Va en `src/packs/bus/summary.py`. Identificadores nuevos en inglés, según la excepción
de CLAUDE.md. `RecordMetric("schedule_query")` en `conversation.py` se queda como está.

### 4.4 Métricas de plataforma (`src/autobot/runtime/summary.py`)

Todas sobre `OutboundMessage` del tenant, dentro de `tenant_tx`:

| Línea | Cálculo |
|---|---|
| 👥 Clientes atendidos | `contact_id` distintos de los mensajes con `status="sent"` y `sent_at` en `[start, end)` |
| 💬 Mensajes enviados | número de esos mismos mensajes (los `failed`, `pending`, `sending` y `unknown` no cuentan) |
| 📱 Coste de WhatsApp | ver abajo; **solo se muestra** si el canal principal del tenant es WhatsApp o si el tenant es de demo |

**Coste** (D9). Se suman los mensajes con `billable=True` y `sent_at` en el periodo,
agrupados por `pricing_category`, multiplicando cada grupo por su precio:

```python
# Approximate Meta price per delivered message, Spain, EUR. Not the account's real
# tariff (Meta's rate card is per recipient country and lives in each business's
# WhatsApp Manager billing panel). Last checked 2026-10-29; see
# docs/runbooks/alta-baja-negocio.md.
PRICE_EUR: dict[str, Decimal] = {
    "marketing": Decimal("0.0585"),
    "utility": Decimal("0.0166"),
    "authentication": Decimal("0.0166"),
    "service": Decimal("0.0166"),
}
```

- **Desaparecen** `SERVICE_FREE_TIER` y el cálculo manual de la franja: los 1.000
  "service" gratis por número ya llegan como `billable=false` desde Meta (el
  `pricing.type` es `free_customer_service`), igual que las entradas gratuitas por
  anuncio. Los mensajes de Telegram nunca tienen `billable`, así que no cuentan.
- Un mensaje con `billable=True` y una categoría que no está en `PRICE_EUR` (por ejemplo
  `authentication_international` o `marketing_lite`) se valora al precio **más alto** de la
  tabla y se registra un `log.warning` con la categoría, sin datos personales. Así el
  coste nunca se queda corto en silencio.
- Un mensaje cuyo estado aún no ha llegado (`billable=None`) no cuenta.
- El resultado se redondea a céntimos (`ROUND_HALF_UP`).
- Los precios de 2026-10-29 son de fuentes públicas no oficiales. "service" a la tarifa
  de utility no está confirmado. **Acción manual**: la persona los contrasta con el rate
  card de su WhatsApp Manager (§10).

### 4.5 `build_summary` y periodos

`previous_month` y `month_to_date` se quedan como están (ya probados). Nueva forma de
`build_summary`:

```python
def build_summary(tenant, start, end, *, calendars=google_calendar) -> SummaryBlock:
    with tenant_tx(tenant.id):                       # 1. DB only
        recorded = _recorded_metrics(start, end)     #    MetricEvent totals by kind
        generic = _generic_metrics(start, end)
        cost = _messaging_cost(start, end)
    pack_lines, pack_failed = _pack_lines(tenant, start, end, recorded, calendars)  # 2. no tx
    return SummaryBlock(tenant, start, end, pack_lines, pack_failed, generic, cost)
```

- `_pack_lines` devuelve `[]` si el tenant no tiene pack (degradado) o el pack no tiene
  `summary`. Si el gancho lanza una excepción, devuelve `([], True)` y registra un
  `log.warning` con el tipo de excepción.
- El **resumen automático** no se envía si `pack_failed`: lanza `TransientError` para
  reintentar (§7). Mandar un resumen sin citas sería engañoso.
- El **estado a demanda** sí se envía con `pack_failed`, poniendo una línea de aviso en
  lugar de las líneas del pack (§6.4).
- `render(blocks: list[SummaryBlock], *, monthly: bool) -> str` pinta uno o varios
  bloques (varios solo en el caso de demo, D3). Cada importe en euros va con el formato
  actual de `_eur` (`1.234,50 €`) y cada recuento como entero.

## 5. Vinculación del dueño

### 5.1 Tabla `owner_link` (`src/autobot/runtime/models.py`, plataforma, sin RLS)

```python
class OwnerLink(models.Model):
    """The owner's Telegram chat for a tenant, and its pending invite. No RLS: the
    notify bot must find the tenant *from* the chat (like DemoSession, ADR-006/007)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name="+")
    chat_id = models.BigIntegerField(null=True, blank=True)       # NULL until linked
    linked_at = models.DateTimeField(null=True, blank=True)
    invite_hash = models.CharField(max_length=64, null=True, blank=True, unique=True)  # sha256 hex
    invite_expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "owner_link"
        indexes = [models.Index(fields=["chat_id"], name="owner_link_chat_idx")]

    def __str__(self) -> str:
        return f"owner_link {self.id}"  # never the chat id
```

- Una fila por tenant como máximo, con su vínculo y su invitación pendiente.
- En la base de datos **no** hay restricción única sobre `chat_id`, porque los negocios de
  demo lo comparten. La regla D3 se aplica en código al vincular (§5.3).
- Funciones de acceso en `src/autobot/owner/links.py`, el módulo nuevo (§6):
  - `owner_chat(tenant_id) -> int | None`;
  - `tenants_of_chat(chat_id) -> list[LoadedTenant]`: tenants del registro con ese chat,
    sin `offboarded` ni `ambiguous`.

### 5.2 Comandos de operación

- **`manage.py owner_invite <slug>`** (nuevo):
  - genera un código con `secrets.token_urlsafe(24)` (32 caracteres, válido para el
    parámetro `start` de Telegram, que admite `[A-Za-z0-9_-]{1,64}`);
  - guarda su `sha256` en `invite_hash`, con caducidad a 7 días
    (`OWNER_INVITE_DAYS = 7`). Un código pendiente anterior queda sustituido;
  - obtiene el `username` del bot con `getMe` y muestra:
    `Enlace para <Nombre> (caduca el dd/mm/aaaa): https://t.me/<username>?start=<código>`;
  - si el tenant ya tiene chat, avisa: "Ya hay un chat conectado; este enlace lo
    sustituirá cuando se use";
  - da error si el slug no existe, si es `offboarded` o si falta `NOTIFY_BOT_TOKEN`.

  El código solo se muestra en la salida del comando. Nunca se registra en logs.
- **`manage.py owner_unlink <slug>`** (nuevo): pone a `NULL` `chat_id`, `linked_at` y la
  invitación. Sirve para un cambio de dueño o una petición RGPD.
- **`manage.py notify_link`**: se **elimina**, con sus tests en
  `tests/integration/test_notifications.py` y `tests/integration/test_telegram_commands.py`
  si los hay.

### 5.3 Flujo `/start <código>` (lo atiende el bot, §6)

1. Se busca `OwnerLink` por `invite_hash = sha256(código)` con `invite_expires_at > now`.
   Si no existe o ha caducado: texto `INVITE_INVALID`.
2. Si el tenant del enlace es `offboarded`: `INVITE_INVALID`.
3. **Regla D3.** Si el tenant **no** es de demo y el chat ya está conectado a otro tenant
   real (no demo, no `offboarded`): texto `CHAT_TAKEN`. El código **no** se consume.
4. Si no, en una transacción: `chat_id = <chat>`, `linked_at = now`,
   `invite_hash = NULL`, `invite_expires_at = NULL`. El código es de un solo uso. Se
   responde `LINKED` con el menú.
5. Un `/start` sin código, o con un código cuando el chat ya está conectado a ese mismo
   tenant, se trata como un mensaje normal (saludo y menú).

## 6. El bot de dueños (entrante)

Módulo nuevo `src/autobot/owner/`:
- `views.py`: webhook;
- `inbox.py`: guardar y procesar eventos;
- `links.py`: §5;
- `menu.py`: opciones;
- `texts.py`: todos los textos.

Sigue el patrón de `src/autobot/channels/demo/` (`views.py` + `selector.py`).

### 6.1 Entrada

- **Ruta** `webhooks/telegram-notify` → `owner.views.telegram_notify`, en
  `src/config/urls.py` dentro de `public`. Mismas comprobaciones y en el mismo orden que
  `telegram_demo`: IP bloqueada → 429; sin `NOTIFY_BOT_TOKEN` o sin
  `NOTIFY_BOT_WEBHOOK_SECRET` → 404; cuerpo grande → 400; `TELEGRAM.verify` → 401 (cuenta
  para el límite por IP); JSON → 400. Después `TELEGRAM.parse(body, None)` y, por cada
  `InboundItem`, `store_owner_event(item)`. Un error de base de datos o de cola → 503.
- **`bot_secrets()`** en `notifications.py`: `webhook_secret` pasa a ser
  `settings.NOTIFY_BOT_WEBHOOK_SECRET` o, si está vacío, un valor aleatorio, como
  `_telegram_door()`, para que la verificación falle siempre.
- **Tabla `owner_event`** (plataforma, sin RLS, copia de `DemoEvent` sin `channel`):
  `id`, `provider_event_id` (`update_id`, único), `payload` (JSON del item), `status`
  (`pending`/`done`/`failed`) y `received_at`, con índice de retención. Se guarda con
  `INSERT … ON CONFLICT (provider_event_id) DO NOTHING RETURNING id` (como `INSERT_EVENT`
  del selector) y en la misma transacción se encola el trabajo.
- **Trabajo** `HANDLE_OWNER_EVENT = "handle_owner_event"` en `src/autobot/jobs.py`: cola
  `INBOUND`, argumento solo `event_id`, `retry=INBOUND_RETRY` y candado
  `owner_chat_lock(chat_id)`. Este candado es nuevo en `src/autobot/runtime/locks.py` y
  usa un hash, como `demo_user_lock`, sin el id en claro.
- **Desarrollo local**:
  - `telegram_poll notify` y `telegram_set_webhook notify [--delete]`: nuevo destino
    `notify` en `polling.source()`, que entra por el mismo `store_owner_event`;
  - URL `/webhooks/telegram-notify`;
  - `telegram_set_webhook notify` exige `NOTIFY_BOT_WEBHOOK_SECRET`.

### 6.2 Proceso (`inbox.handle_owner_event`)

Patrón de `route_demo_event`: el evento se marca `done` **antes** de enviar; se envía
como mucho una vez y un envío ambiguo nunca se repite.

1. Se vuelve a parsear el `payload`. Si es un callback, `TELEGRAM.acknowledge(...)`.
2. `chat_id = int(item.external_id)`. En chats privados, el id de usuario coincide con el
   del chat, y `parse` ya descarta grupos y bots.
3. Si el texto es `/start <algo>` → flujo de §5.3.
4. `tenants = tenants_of_chat(chat_id)`:
   - vacío → `NOT_LINKED`, con un máximo de 3 respuestas por hora y chat. Se usa un
     `WindowLimiter(limit=3, window_s=3600)` como `selector.refusals`; pasado el
     límite, silencio;
   - si no, según el `payload` del botón:
     - `owner:status` → §6.4;
     - `owner:contact` → `CONTACT`;
     - cualquier otro botón, texto o mensaje no soportado → `GREETING`.
5. Cada respuesta lleva el menú (§6.3), salvo `NOT_LINKED` e `INVITE_INVALID`.
6. Se envía con `deliver(reply, chat_id, reference=event.id)`. `deliver` se generaliza
   para recibir un `Outbound` en lugar de un `str`. `send_notification` y
   `send_ops_alert` pasan a envolver su texto en `Text(...)`.
7. Logs: solo `event_id` y, si se conoce, el slug del tenant. Nunca el `chat_id`, el
   nombre ni el código.

### 6.3 Menú ampliable (`owner/menu.py`)

```python
@dataclass(frozen=True)
class MenuOption:
    id: str                                   # button payload, "owner:<name>", ≤ 64 bytes
    title: str                                # ≤ 20 characters (MAX_BUTTON_TITLE)
    answer: Callable[[OwnerChat], str]        # the reply text
    available: Callable[[OwnerChat], bool] = lambda chat: True

MENU: list[MenuOption] = [
    MenuOption("owner:status", "📊 Cómo va el mes", status_text),
    MenuOption("owner:contact", "✉️ Contacto", contact_text,
               available=lambda chat: bool(settings.OWNER_SUPPORT_EMAIL)),
]
```

- `OwnerChat` es un dataclass con `chat_id` y `tenants: list[LoadedTenant]`.
- `menu_reply(chat, body)` construye la respuesta con las opciones disponibles:
  `buttons_msg` si hay 3 o menos, `list_msg` si hay entre 4 y 10. Así se respetan los
  límites comunes. Un test comprueba que `MENU` cumple los límites de id y título.
- Añadir una opción = añadir su función y una entrada en `MENU`, con su test.

### 6.4 Textos (`owner/texts.py`)

Los textos usan `*negrita*`, que el adaptador de Telegram convierte en `<b>`.

| Clave | Texto |
|---|---|
| `GREETING` (1 negocio) | `👋 ¡Hola! Soy el asistente de *{name}*.\n¿Qué necesitas?` |
| `GREETING` (varios, demo) | `👋 ¡Hola! Soy tu asistente de Autobot.\n¿Qué necesitas?` |
| `CONTACT` | `✉️ ¿Dudas, cambios o algo que no va?\nEscríbeme a {email} y te respondo lo antes posible.` |
| `NOT_LINKED` | `🤔 Este chat no está conectado a ningún negocio.\nSi eres cliente de Autobot, pide tu enlace de activación a {email}.` (sin correo configurado: `…pide tu enlace de activación a quien te dio de alta.`) |
| `LINKED` | `✅ ¡Listo! Este chat ya está conectado con *{name}*.\nPor aquí te llegarán los avisos y resúmenes de tu negocio.` |
| `INVITE_INVALID` | `⌛ Este enlace ya no es válido. Pide uno nuevo a {email}.` (sin correo: `Pide uno nuevo a quien te lo envió.`) |
| `CHAT_TAKEN` | `⚠️ Este chat ya está conectado con otro negocio. Si necesitas cambiarlo, escribe a {email}.` |
| `NOT_ACTIVE` | `⏸️ El bot de *{name}* todavía no está activo. Cuando lo esté, aquí verás tus cifras.` |
| `PACK_FAILED` | `⚠️ Ahora no puedo leer tu agenda; prueba en unos minutos.` |

**"Cómo va el mes"** (`status_text`): para cada tenant del chat, ordenados por nombre:
- un tenant real que no está `active` (o está degradado) da `NOT_ACTIVE`;
- un tenant de demo `active` o `paused` (D13), o un tenant real `active`, da
  `build_summary(tenant, *month_to_date(now, tz))` pintado así:

```
📊 *Así va noviembre* (hasta hoy, día 12)
Peluquería Ana

✂️ Citas: 20
💶 Ingresos estimados: 340,00 €
👥 Clientes atendidos: 15
💬 Mensajes enviados: 110
📱 Coste de WhatsApp: 0,42 €

ℹ️ Ingresos según tus precios actuales; coste aproximado.
```

Con varios negocios (solo demo), un bloque por negocio separado por una línea en blanco,
y la nota `ℹ️` una sola vez al final.

**Resumen automático** (texto de la `Notification`, sin botones):

```
📊 *Tu resumen de octubre*
Peluquería Ana

✂️ Citas: 42
💶 Ingresos estimados: 680,00 € (3 sin precio)
👥 Clientes atendidos: 31
💬 Mensajes enviados: 210
📱 Coste de WhatsApp: 1,25 €

ℹ️ Ingresos según tus precios actuales; coste aproximado (la factura real está en tu cuenta de Meta).
```

- Una línea a 0 se muestra igual.
- La línea de coste solo aparece para WhatsApp o demo (§4.4).
- `bus` muestra `🚌 Consultas de horario: N` en lugar de citas e ingresos.
- La nota `ℹ️` menciona los ingresos solo si alguna línea del pack es `eur`.

## 7. Envío automático

- **Periodic** `DISPATCH_OWNER_SUMMARIES`: cron `"0 * * * *"`, cada hora en punto (antes
  `"0 11 * * *"`). `dispatch_owner_summaries(now)` encola, por cada tenant que cumple
  `_due`, el trabajo **nuevo** `SEND_OWNER_SUMMARY = "send_owner_summary"`. Ese trabajo
  va en la cola `PERIODIC`, con argumentos `tenant_id`, `year` y `month` del mes
  reportado, `queueing_lock=f"summary:{tenant_id}"` y
  `retry=RetryStrategy(max_attempts=3, wait=300, retry_exceptions={TransientError})`.
  Las llamadas a Calendar ya no van en el dispatcher.
- **`_due(tenant, now)`**: todas estas condiciones a la vez:
  - `status == "active"` y no degradado;
  - `owner.summary_monthly`;
  - `owner_chat(tenant.id)` no es `None`;
  - en la zona del tenant, `day == 1` y `hour >= SUMMARY_LOCAL_HOUR` (12).

  Que sea `>=` y no `==` permite recuperar el envío más tarde ese mismo día si el worker
  estuvo parado a las 12. La clave de idempotencia evita duplicados.
- **`send_owner_summary`**:
  1. si ya existe la `Notification` con `idem_key = f"summary:{tenant_id}:{YYYY-MM}"`,
     termina sin llamar a Calendar;
  2. si no, `build_summary` (`pack_failed` → `TransientError`);
  3. en `tenant_tx`, `bulk_create(ignore_conflicts=True)` de la `Notification` y
     `defer` de `SEND_NOTIFICATION`, como ahora.
- **`send_notification`**: el destinatario sale de `owner_chat(tenant_id)` en lugar de
  `owner.telegram_chat_id`. La regla `allowed` (resumen siempre, avisos solo si están en
  `owner.notify`) no cambia. `process._notify_owner` deja de mirar `telegram_chat_id`:
  crea la notificación si `action.kind in owner.notify`, y `send_notification` solo la
  registra en el log si no hay chat, como hoy.

## 8. Configuración

`src/autobot/tenancy/schema.py`:

```python
class Owner(Strict):
    notify: list[str] = []
    summary_monthly: bool = False
```

Sin `telegram_chat_id` (extra=forbid hace fallar en CI cualquier YAML que lo tenga;
ninguno en `tenants/` lo tiene hoy) y sin validador.

`src/config/settings.py` + `.env.example` + `compose.prod.yaml` (variables explícitas):

| Variable | Uso |
|---|---|
| `NOTIFY_BOT_WEBHOOK_SECRET` | `secret_token` del webhook del bot de avisos (≥ 32 caracteres). Vacío → webhook en 404. |
| `OWNER_SUPPORT_EMAIL` | Correo de contacto que ve el dueño. Vacío → la opción "Contacto" no aparece. |

`src/autobot/ops/health.py` y `ops/check.py`: el bot de avisos pasa a comprobarse como el
de demo (`outbound_only=False`, se espera webhook). El `Issue("notify_webhook")` se
elimina.

`Caddyfile`: se añade `/webhooks/telegram-notify` a `@public`.

`src/autobot/runtime/retention.py`: `owner_event` a 7 días, como `demo_event`.
`owner_link` no caduca; se borra con el tenant (`CASCADE`). Hay que comprobar que
`purge_tenant` lo cubre y añadirlo a su test.

## 9. Tests

**Contrato y packs**
- `src/packs/salon/tests/test_summary.py` (nuevo, con `FakeCalendar`):
  - cuentan las citas del bot y las manuales con título `"Servicio - X"`, `"Servicio"`,
    con mayúsculas o acentos distintos y con `–`/`—`;
  - **no** cuentan `[CFG] VACACIONES`, "Comida", un evento con `Telefono:` pero título
    libre, los eventos de todo el día ni uno que empieza antes de `start`;
  - el nombre más largo gana (`"Corte y barba - X"` frente a `"Corte"`);
  - un evento del bot con `fp_service` retirado, por título o sin precio;
  - suma de ingresos, "N sin precio" y `end` exclusivo.
- `test_booking.py` / `test_management.py`: `create()`/`cancel()` ya **no** emiten
  `RecordMetric`. Las aserciones antiguas se sustituyen por `salon.metrics == []`.
- `src/packs/bus/tests/test_summary.py`: la línea sale de `recorded["schedule_query"]` y
  vale 0 si falta. `test_metrics.py` no cambia.

**Plataforma** (`tests/integration/`)
- `test_summary.py`, actualizar:
  - `_generic_metrics` cuenta solo `sent` por `sent_at`;
  - `_messaging_cost` sobre `billable=True`, con categorías mezcladas, una categoría
    desconocida al precio máximo, `billable=None`/`False` fuera y Telegram fuera. Se
    borran los tests de la franja de 1.000;
  - `build_summary` sin transacción durante el gancho del pack: un `FakeCalendar` que
    afirma `not connection.in_atomic_block`, como el `handler` de
    `test_notifications.py`;
  - `pack_failed`: el automático lanza `TransientError`, el de demanda pinta `PACK_FAILED`;
  - `_due` según la hora: día 1 a las 11:59 locales no, a las 12:00 sí, a las 18:00 sí
    (recuperación); día 2 no; sin chat conectado no;
  - `send_owner_summary` idempotente: dos ejecuciones dan una sola `Notification` y la
    segunda no llama a Calendar;
  - el renderizado con 1 bloque y con 2 (demo).
- `test_owner_bot.py` (nuevo). Es el **escenario de conversación** del bot de dueños, con
  Telegram simulado como en `test_notifications.py`:
  - webhook: 404 sin secreto, 401 con secreto erróneo, update duplicado guardado una vez;
  - `/start <código>` válido → conectado + `LINKED` con menú; caducado o desconocido →
    `INVITE_INVALID`; reutilizado → `INVITE_INVALID`;
  - D3: chat ya conectado a un negocio real + invitación de otro real → `CHAT_TAKEN` y
    código intacto; dos negocios de demo con el mismo chat → permitido;
  - texto libre → `GREETING` con botones; `owner:status` → cifras del mes en curso;
    `owner:contact` → correo; sin `OWNER_SUPPORT_EMAIL` el menú solo tiene un botón;
  - chat no conectado → `NOT_LINKED`; a la cuarta vez en una hora, silencio;
  - negocio real `paused` → `NOT_ACTIVE`; demo `paused` → cifras (D13);
  - todas las respuestas cumplen los límites comunes (`core.limits`, `overflow` de
    Telegram);
  - ningún log contiene el `chat_id` ni el código (`caplog`).
- `test_notifications.py`: el destinatario sale de `OwnerLink`; se eliminan los tests de
  `notify_link`.
- `tenancy/test_commands.py` (o equivalente): `owner_invite` (enlace, sustitución, slug
  desconocido, sin token) y `owner_unlink`.
- `test_models.py` / `test_db_roles.py`: `owner_link` y `owner_event` en la lista de tablas
  de plataforma **sin** RLS (la de la línea ~213 enumera las que sí la tienen).
- `test_retention.py`: purga de `owner_event` a 7 días.

## 10. Aprobaciones y acciones manuales

**Requieren aprobación explícita de la persona antes de implementarlas** (CLAUDE.md):
1. La migración que crea `owner_link` y `owner_event` **sin RLS** (D2), una tabla de
   plataforma con el `chat_id` del dueño.
2. Los cambios de infraestructura: la ruta nueva en `Caddyfile` y las variables nuevas en
   `compose.prod.yaml`.
3. La firma del webhook nuevo (D12) ya la aprobó la persona el 2026-10-29.

**Pasos manuales de puesta en marcha** (a anotar en `docs/puesta-en-marcha.md`; ningún
agente los hace contra producción):
- Generar `NOTIFY_BOT_WEBHOOK_SECRET` y poner `OWNER_SUPPORT_EMAIL` en el `.env` del servidor.
- Desplegar y después `manage.py telegram_set_webhook notify`.
- Por cada negocio con dueño: `manage.py owner_invite <slug>` y enviarle el enlace.
- Contrastar `PRICE_EUR` con el rate card del WhatsApp Manager y anotar la fecha en el
  runbook.
- Pedir a cada peluquero que titule sus citas manuales como las del bot
  (`"<Servicio> - <Nombre>"`).

## 11. Plan de implementación (un commit por paso, con tests y documentación)

1. **Coste y métricas de plataforma**: `PRICE_EUR` nuevo, coste por `billable`, mensajes y
   clientes por `status="sent"`/`sent_at`. Runbook de precios actualizado.
2. **Gancho `Pack.summary`**: `SummaryLine` en `core`, `salon/summary.py` sobre el calendario,
   `bus/summary.py`, quitar `SummaryMetric`/`summary_metrics` y los `RecordMetric` de
   `salon`, `build_summary` en dos fases. `docs/packs/salon.md` y `bus.md` actualizados.
3. **Envío a las 12:00 locales**: cron por horas, `_due` con hora, trabajo
   `send_owner_summary` con reintentos.
4. **Vinculación y bot entrante** (**tras la aprobación de §10**): migración `0010`
   (`owner_link`, `owner_event`), `owner_invite`/`owner_unlink`, se quita `notify_link` y
   `Owner.telegram_chat_id`, `send_notification` lee de `OwnerLink`, webhook +
   `owner_event` + `handle_owner_event`, destinos `notify` de `telegram_poll` y
   `telegram_set_webhook`, salud del bot, `Caddyfile`, variables y **ADR-007**.
5. **Menú**: `menu.py`, `texts.py`, "Cómo va el mes", "Contacto", escenario
   `test_owner_bot.py` completo.

Documentación que hay que tocar a lo largo del plan:
- `README.md`: menciona el bot de dueños.
- `docs/packs/salon.md`: sección "Resumen mensual" con la regla de títulos de D5, sin
  métricas `RecordMetric`.
- `docs/packs/bus.md`: sin `telegram_chat_id`.
- `docs/runbooks/alta-baja-negocio.md`: paso 5 con `owner_invite` en lugar de
  `notify_link`, y precios.
- `docs/runbooks/09-rotar-secretos.md`: `NOTIFY_BOT_WEBHOOK_SECRET`.
- `docs/puesta-en-marcha.md`: §10.
- `docs/mejoras/01-bot-de-demo.md`: las menciones a `notify_link` pasan a `owner_invite`.
- El comentario de cabecera de `tenants/demo-peluqueria/tenant.yaml`.
- `docs/adr/ADR-007-bot-de-duenos.md`: webhook entrante del bot de avisos, `chat_id` en
  BD sin RLS (y por qué no en YAML), resumen con el calendario como fuente de verdad
  mediante el gancho del pack.

> **Ojo al implementar:** en el árbol de trabajo hay cambios sin confirmar de la persona
> (`Makefile`, `README.md`, `compose.yaml`, `docs/puesta-en-marcha.md`,
> `docs/runbooks/demo.md`, `tenants/demo-peluqueria/tenant.yaml`,
> `docs/mejoras/03-…`, `docs/mejoras/04-…`). Al editar esos ficheros hay que conservar
> esos cambios y no incluirlos en los commits de esta mejora salvo que la persona lo diga.

## 12. Fuera de alcance

- Más opciones en el menú (el mes pasado, rangos libres, "qué servicio se pidió más",
  desvincularse uno mismo): el menú está preparado, pero cada opción es una mejora aparte.
- Comparar con el mes anterior, gráficas, email o PDF.
- Citas canceladas o "no presentados" (D6).
- Reconocer citas manuales con títulos libres o por la descripción (D5).
- Precio por país del destinatario: todo se valora con la tabla de España.
- Varios dueños (varios chats) por negocio: una fila `owner_link` por tenant.
- Ver los resúmenes en `/admin/estado/` (mejora 03).
