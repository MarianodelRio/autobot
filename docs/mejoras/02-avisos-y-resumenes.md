# Mejora 02 · Resúmenes periódicos al dueño

**Estado:** propuesta, pendiente de revisión. Ningún agente la implementa sin que la
persona confirme las decisiones de la sección 2.

## 1. Introducción

Hoy el dueño de un negocio solo recibe avisos puntuales (`NotifyOwner`), y solo en el
pack `salon`: una cita creada, cancelada, movida, o un fallo al mover. No hay ninguna
vista agregada: para saber "cómo va el negocio esta semana" no hay nada que lo diga.

Se añade un resumen con al menos: número de citas (o la métrica de negocio que
corresponda), número de usuarios, mensajes y coste (ingresos estimados y coste
aproximado de mensajería). El dueño puede recibirlo periódicamente y también pedirlo
él mismo al bot de avisos cuando quiera un estado al día.

## 2. Decisiones de diseño (propuestas)

1. **Un resumen por negocio, no por tipo de aviso.** Un solo mensaje con todas las
   cifras, no uno por métrica. Mantiene el límite de frecuencia de Telegram y es más
   legible.
2. **Una sola cadencia: mensual, activable o no.** `owner.summary_monthly: bool`
   (por defecto `False`). No hay elección de frecuencia (ni `daily`/`weekly`/`monthly`
   como lista): o se recibe el resumen mensual, o no se recibe nada automático.
   Simplifica lo que antes eran varias frecuencias combinables.
3. **Dos periodos distintos, según quién lo pide — no uno solo.** Es la aclaración
   importante de esta versión:
   - **Resumen automático** (decisión 2): se dispara **el día 1 de cada mes** y
     reporta sobre **el mes anterior completo** (cerrado, de principio a fin). El día 1
     de noviembre llega el resumen de octubre entero. Es lo que un dueño espera de un
     "resumen mensual": el mes ya terminado, no un fragmento.
   - **Estado a demanda** (decisión 11): reporta sobre **el mes en curso, desde el día
     1 hasta el momento de la pregunta** — un parcial, a propósito, porque la pregunta
     es "¿cómo va este mes hasta ahora?".
   - En ningún caso hay ventana corrediza: ambos son periodos de calendario (un mes
     natural completo, o el trozo del mes natural en curso), calculados en la zona
     horaria del tenant (`tenant.timezone`, ya existente para todo lo demás en la
     plataforma). Como cada uno de los dos es siempre un mes natural o un trozo de un
     único mes natural, ninguno cruza nunca la frontera de fin de mes a mitad de
     cálculo — simplifica el coste de mensajería (decisión 10), que no necesita
     partirse en sub-periodos.
4. **El "coste" de negocio es una estimación de ingresos**, no un cobro confirmado: se
   calcula con el precio configurado del servicio en el momento de la reserva
   (`services.<id>.price_eur` en `salon`), sumando el precio de **cada** reserva, no un
   precio fijo multiplicado por un recuento. No hay cobro real que el sistema conozca;
   si el cliente no se presenta o paga distinto, el resumen no lo sabrá. Se dice así en
   el texto del resumen y en la documentación, para que el dueño no lo lea como
   contabilidad real.
5. **Las citas canceladas no restan de los ingresos estimados.** Se muestran como una
   cifra aparte ("citas canceladas"); restarlas mezclaría "se reservó" con "se hizo", y
   ese segundo dato no existe en el sistema (no hay confirmación de asistencia).
6. **Las citas creadas manualmente en Google Calendar no cuentan.** `RecordMetric` se
   emite en `conversation.py` al reservar/cancelar por el bot; una cita que el dueño
   añade a mano en Calendar nunca pasa por ahí, así que nunca genera una métrica. Es el
   comportamiento correcto (igual que `bus` no tiene ingresos: no es una limitación a
   resolver), pero se documenta explícitamente para que no sorprenda.
7. **Cada pack declara sus propias métricas de negocio** (`Pack.summary_metrics`), con
   su nombre para mostrar y si es un recuento o un importe en euros. La plataforma no
   sabe qué es una "cita"; solo sabe sumar lo que el pack le dice que sume.
8. **Las métricas de pack se guardan como eventos de negocio genéricos**
   (`RecordMetric`, tabla `metric_event`), nunca leyendo directamente la agenda o el
   calendario en el momento del resumen. Evita recalcular desde Google Calendar (que no
   guarda histórico de cancelaciones: `cancel_event` borra el evento), evita mezclar
   citas manuales con las del bot, y mantiene la regla de que un pack no toca la base de
   datos: emite una acción, como ya hace `NotifyOwner`.
9. **Las métricas genéricas las calcula la plataforma**, no el pack, y se reducen a
   tres: **usuarios** (contactos distintos con al menos un mensaje del bot en el
   periodo), **mensajes** (enviados por el bot) y **coste aproximado de mensajería**
   (ver decisión 10). "Usuarios" se calcula sobre `OutboundMessage` (contactos
   distintos con una fila en el periodo), **no** sobre `Contact.last_activity_at`: ese
   campo solo guarda el último instante de actividad, así que para el resumen
   automático, que reporta sobre el mes **anterior ya cerrado** (decisión 3), un
   contacto activo dentro de ese mes pero también después (en el mes en curso, antes de
   que se genere el resumen el día 1) desaparecería incorrectamente. Para el estado a
   demanda esto no pasaría (su periodo siempre termina "ahora"), pero usar la misma
   consulta en los dos casos evita tener dos formas distintas de contar "usuarios"
   según quién pregunta. `OutboundMessage` ya hace falta para "mensajes" y "coste", así
   que no añade ninguna tabla ni consulta nueva, solo un `distinct("contact")`. No se
   desglosan "usuarios nuevos" ni "bajas": no se pidieron y añaden ruido a lo que se
   pidió (número de citas, número de usuarios, coste). Tampoco se desglosa "mensajes"
   por categoría de plantilla (servicio/utility/marketing): en la práctica casi todos
   los negocios usan una sola categoría, así que una cifra total basta; el desglose por
   categoría solo existe internamente, para calcular el coste (decisión 10).
10. **Coste aproximado de mensajería, nuevo en esta versión** (antes estaba fuera de
    alcance). Desde el 1 de octubre de 2026 Meta cobra por los mensajes de WhatsApp
    salientes: los de categoría "service" (respuesta dentro de la ventana de 24h) tienen
    1.000 gratis al mes por número de negocio y se cobran a partir del 1.001; las
    plantillas "utility"/"marketing"/"authentication" se cobran desde el primer mensaje,
    sin franja gratuita. Telegram no tiene coste por mensaje (Bot API gratuita), así que
    solo los mensajes de WhatsApp entran en el cálculo.
    - Ya existe la tabla que hace falta, `OutboundMessage` (`tenant`, `channel`,
      `created_at`, `pricing_category`, `billable`): no se crea nada nuevo, solo se
      agrega sobre ella.
    - Tanto `previous_month` como `month_to_date` (decisión 3) empiezan siempre en el
      día 1 de un mes natural, así que la franja gratuita de "service" se calcula
      directo, sin partir nada por mes: de los mensajes "service" del tenant dentro
      del periodo, los que superan 1.000 se facturan
      (`facturables = max(0, recuento_periodo - 1000)`); nunca hay que mirar fuera del
      periodo ni preguntarse "cuántos llevaba ya el mes pasado", porque el periodo
      siempre coincide con un mes natural entero o con el principio de uno. Para
      "utility"/"marketing"/"authentication", se multiplica directamente
      (`recuento_periodo × precio_categoría`), sin franja.
    - El precio por categoría es una tabla configurable y documentada como
      **aproximada**, no la tarifa real de la cuenta (Meta publica el rate card exacto,
      por país y moneda, dentro del panel de facturación de WhatsApp Business Manager,
      y cambia como máximo una vez por trimestre). El texto del resumen lo dice, igual
      que ya se dice de los ingresos estimados.
11. **El dueño puede pedir el estado al bot de avisos**, no solo recibirlo
    periódicamente: una única frase fija ("estado", a falta de decidir el texto exacto)
    que devuelve **el mes en curso hasta ahora** — distinto del resumen automático, que
    da el mes anterior completo (decisión 3). Una sola frase basta porque solo hay un
    periodo posible para la pregunta a demanda (no hace falta "estado de este
    mes"/"estado del mes pasado": el mes pasado ya lo mandó el resumen automático). **No
    depende de tener `summary_monthly` activado**: basta con
    tener `owner.telegram_chat_id` configurado (lo que ya tiene cualquier negocio con
    avisos puntuales activados); pedir el estado a demanda no activa ni sustituye al
    resumen periódico. Esto requiere que el bot de avisos, hoy solo de salida
    (`notifications.py`: *"This bot has no inbound webhook"*), reciba mensajes: un
    webhook nuevo, y resolver qué tenant corresponde al `chat_id` que escribe. Es un
    cambio de arquitectura, no solo de cálculo; se registra como ADR al implementarlo
    (sección 9). Si el `chat_id` no está vinculado a ningún negocio, el bot pregunta en
    vez de adivinar (regla general del CLAUDE.md). **Sin cerrar en esta propuesta:** si
    el mismo `chat_id` correspondiera a más de un negocio (una misma persona dueña de
    varios), cómo el dueño le dice al bot "a cuál de los dos me refiero" no está
    diseñado — probablemente baste con que el bot liste los nombres y el dueño responda
    con uno, pero es una conversación con estado (pregunta → espera respuesta) que hay
    que detallar al implementarlo, no inventarla aquí.
12. **Un negocio de demo puede activar su propio resumen** igual que un negocio real
    (le sirve a quien lo mantenga para ver cuánto se usa la demo). No hay caso especial.
13. **Se entrega por el bot de avisos de Telegram ya existente** (`NOTIFY_BOT_TOKEN`,
    `owner.telegram_chat_id`), reutilizando `send_notification` para el envío
    periódico; el canal de petición a demanda (decisión 11) usa el mismo bot, en modo
    entrante. No se añade un canal nuevo (WhatsApp, email...).
14. **Sin resumen mientras el negocio no está `active`.** Un negocio en `onboarding`,
    `paused` u `offboarded` no manda ni responde resúmenes (igual que ya no recibe
    recordatorios ni barrido de calendario, `runtime/periodic.is_active`).

## 3. Métricas

### Genéricas (toda la plataforma, cualquier pack)

| Métrica | Cómo se calcula |
|---|---|
| Usuarios | `Contact` distintos con algún `OutboundMessage` dentro del periodo (no `last_activity_at`: ver decisión 9) |
| Mensajes | `OutboundMessage` enviados por el bot dentro del periodo |
| Coste aproximado de mensajería | Ver decisión 10: por categoría de plantilla de WhatsApp, con la franja gratuita de "service" |

### Del pack `salon`

| Métrica | `kind` de `RecordMetric` | Unidad | Se emite cuando |
|---|---|---|---|
| Citas creadas | `booking_created` | recuento | se confirma una reserva nueva o un movimiento (`conversation.py: create()`) |
| Citas canceladas | `booking_cancelled` | recuento | se cancela una cita (`conversation.py: cancel()`) |
| Ingresos estimados | `booking_revenue` | euros | junto con `booking_created`, por el precio del servicio reservado (`self.cfg.services[...].price_eur`, el de esa reserva en concreto, no un precio fijo) |

Las citas creadas a mano en Google Calendar no generan ninguna de estas tres métricas
(decisión 6): no pasan por `conversation.py`.

### Del pack `bus`

| Métrica | `kind` de `RecordMetric` | Unidad | Se emite cuando |
|---|---|---|---|
| Consultas de horario | `schedule_query` | recuento | la conversación devuelve un itinerario encontrado: `consulta.estado == "con_salidas"` dentro de `_resultado()`, no cualquier llamada a esa función (menús, errores o "sin horarios" no cuentan) |

`bus` no tiene ingresos: el bot no vende nada, solo informa. No declarar una métrica de
euros para este pack es correcto, no una limitación a resolver.

## 4. Modelo resultante

```
RecordMetric(kind, value=1, idem_key)         # nueva Action, en core/actions.py
    -> MetricEvent(tenant, kind, value, idem_key, created_at)   # tabla nueva, CON RLS (TenantScoped)

Pack.summary_metrics: list[SummaryMetric]      # metadatos estáticos, en core/pack.py
    SummaryMetric(kind, label, unit="count"|"eur")

Owner.summary_monthly: bool   # tenancy/schema.py — por defecto False

runtime/summary.py:
    previous_month(now, tz) -> (start, end)      # para el resumen automático
        el mes natural completo anterior al mes de "now", en la zona horaria del tenant
        (si now es 1 de noviembre, da [1 de octubre, 1 de noviembre))

    month_to_date(now, tz) -> (start, now)        # para el estado a demanda
        start = día 1 del mes de "now", 00:00, en la zona horaria del tenant

    dispatch_owner_summaries(now):
        para cada tenant activo con owner.telegram_chat_id, owner.summary_monthly y
        hoy es día 1 del mes (en su zona horaria):
            start, end = previous_month(now, tenant.timezone)
            build_summary(tenant, start, end) -> texto
            Notification(kind="owner_summary", idem_key=f"summary:{tenant_id}:{start.year}-{start.month:02d}")
            -> send_notification (ya existente)

    build_summary(tenant, start, end) -> str:
        - _generic_metrics(tenant, start, end): usuarios, mensajes
        - _messaging_cost(tenant, start, end): coste aproximado del periodo (decisión 10)
        - _pack_metrics(tenant, start, end): agregados de MetricEvent por SummaryMetric
        - _render(...): el texto (sección 7)

    estado a demanda (decisión 11), sobre el webhook entrante:
        build_summary(tenant, *month_to_date(timezone.now(), tenant.timezone))
```

El `idem_key` se identifica por el mes que se reporta (`{año}-{mes}` de `start`, el mes
anterior), no por la fecha de envío: solo hay un disparo automático al mes (el día 1),
así que la clave del mes reportado ya es única por sí misma.

`MetricEvent` lleva `tenant_id` y RLS como cualquier dato de negocio (no es como
`DemoEvent`, que no tiene tenant todavía cuando se crea). No contiene teléfonos, ids de
usuario ni texto libre: solo `kind` (una cadena fija del pack) y `value` (un número).

## 5. Configuración

`tenancy/schema.py`, `Owner`:

```python
class Owner(Strict):
    telegram_chat_id: int | None = None
    notify: list[str] = []
    summary_monthly: bool = False

    @model_validator(mode="after")
    def _summary_needs_chat(self) -> "Owner":
        if self.summary_monthly and self.telegram_chat_id is None:
            raise ValueError("summary_monthly needs telegram_chat_id")
        return self
```

Ejemplo en un `tenant.yaml`:

```yaml
owner:
  telegram_chat_id: 123456789
  notify: [booking_created, booking_cancelled, move_cancel_failed]
  summary_monthly: true
```

## 6. Cambios en el código

1. **`core/actions.py`**: nueva `RecordMetric(kind: str, value: Decimal = Decimal(1), idem_key: str)`;
   se añade a `type Action`.
2. **`core/pack.py`**: nueva `SummaryMetric(kind: str, label: str, unit: Literal["count", "eur"] = "count")`;
   `Pack` gana `summary_metrics: list[SummaryMetric] = field(default_factory=list)`.
3. **`flowpilot/runtime/models.py`**: nuevo modelo `MetricEvent(TenantScoped)` —
   `kind` (`CharField`, máx. 64), `value` (`DecimalField`), `idem_key` (`TextField`),
   `created_at` (`auto_now_add`); índice `(tenant, kind, created_at)`; restricción única
   `(tenant, idem_key)`, igual que `Notification`. Migración nueva (no destructiva: solo
   crea tabla e índices, sin aprobación especial).
4. **`flowpilot/runtime/process.py`**: nuevo `case RecordMetric():` que inserta la fila
   con `bulk_create(..., ignore_conflicts=True)`, igual que `_notify_owner`; sin cola ni
   llamada externa (es solo un registro).
5. **`flowpilot/tenancy/schema.py`**: `Owner.summary_monthly` (sección 5).
6. **`flowpilot/runtime/summary.py`** (nuevo): `previous_month`, `month_to_date`,
   `dispatch_owner_summaries`, `build_summary`, `_generic_metrics`, `_messaging_cost`,
   `_pack_metrics`, `_render` (sección 4). `_generic_metrics` cuenta "usuarios" como
   contactos distintos con `OutboundMessage` en el periodo (decisión 9, no
   `last_activity_at`, válido tanto para `previous_month` como para `month_to_date`).
   `_messaging_cost` hace la cuenta de la decisión 10 sobre `OutboundMessage`, con la
   tabla de precios por categoría como constante configurable y documentada como
   aproximada.
7. **`flowpilot/jobs.py`**: un periodic nuevo, diario, en UTC a una hora fija (p. ej.
   `"0 7 * * *"`, las 7:00 UTC — por decidir con la persona si prefiere otra hora),
   `DISPATCH_OWNER_SUMMARIES`, que llama a `dispatch_owner_summaries` (que internamente
   solo actúa para cada tenant si hoy es el día 1 de su mes, en su zona horaria — el job
   en sí es diario, el envío real es mensual, y reporta sobre el mes que acaba de
   cerrarse). Un solo disparo
   para toda la plataforma (no uno por pack): esta pieza no es del pack, es de la
   plataforma, así que no usa `dispatch_periodic`/`run_periodic` (eso es para el trabajo
   propio de cada pack, con su `PackContext`).
8. **Webhook entrante del bot de avisos** (decisión 11, nuevo frente de trabajo):
   - Ruta nueva, p. ej. `webhooks/telegram-notify` (`config/urls.py`), análoga a las ya
     existentes de `channels/views.py` pero para el bot de avisos, hoy sin webhook.
   - Resolver `chat_id` → tenant: buscar en el registro los tenants activos cuyo
     `owner.telegram_chat_id` coincide. Si no hay ninguno, o hay más de uno, el bot
     responde preguntando (nunca adivina).
   - Reconocimiento de una única frase fija ("estado"), sin variantes libres ni NLP;
     cualquier otro texto se ignora o responde con ayuda mínima (a decidir el texto
     exacto al implementarlo).
   - Llama a `build_summary(tenant, *month_to_date(timezone.now(), tenant.timezone))`
     y responde por el mismo canal.
   - Disambiguación cuando el `chat_id` corresponde a más de un negocio: pendiente de
     detallar (decisión 11) — no se implementa a ciegas, se diseña ese flujo concreto
     cuando se aborde esta pieza.
9. **`flowpilot/runtime/retention.py`**: añade `MetricEvent` a la lista de tablas con
   recorte anual (`annual`, igual que `Notification`), dentro del bucle por tenant.
10. **`packs/salon/pack.py`**: `summary_metrics=[SummaryMetric("booking_created", "Citas creadas"), SummaryMetric("booking_cancelled", "Citas canceladas"), SummaryMetric("booking_revenue", "Ingresos estimados", unit="eur")]`.
11. **`packs/salon/conversation.py`**:
    - en `create()`, junto a `NotifyOwner`, añadir
      `RecordMetric("booking_created", idem_key=self.ctx.idem.event("metric:booking_created"))`
      y `RecordMetric("booking_revenue", value=Decimal(str(svc.price_eur)), idem_key=self.ctx.idem.event("metric:booking_revenue"))`.
    - en `cancel()`, junto al `NotifyOwner` de `booking_cancelled`, añadir
      `RecordMetric("booking_cancelled", idem_key=self.ctx.idem.event("metric:booking_cancelled"))`.
    - Un movimiento de cita (`moving`) ya cuenta como `booking_created` de la nueva y no
      genera `booking_cancelled` de la antigua (la cancelación de la fuente en un
      movimiento no pasa por `cancel()`); se documenta así, no se intenta "neutralizar"
      el movimiento en las métricas.
12. **`packs/bus/pack.py`**: `summary_metrics=[SummaryMetric("schedule_query", "Consultas de horario")]`.
13. **`packs/bus/conversation.py`**: en `_resultado()` (`conversation.py:521-536`),
    añadir `RecordMetric("schedule_query", idem_key=...)` a las acciones solo cuando
    `consulta.estado == "con_salidas"`, no en cualquier llamada a esa función. Al
    implementarlo, revisar que `PackResult.actions` se propaga en todas las ramas que
    llegan a ese punto (hoy `bus` no usa `actions` en ningún sitio).

## 7. Formato del mensaje

Orden: métricas del pack primero (lo que importa al negocio), genéricas después. Las
dos variantes comparten formato, pero **no** el mismo periodo (decisión 3) — la
cabecera deja claro cuál es cuál:

**Resumen automático** (día 1, sobre el mes anterior completo):

```
📊 Resumen de octubre
• Citas creadas: 12
• Citas canceladas: 1
• Ingresos estimados: 180,00 €
• Usuarios: 9
• Mensajes: 64
• Coste aproximado de mensajería: 1,06 €
```

**Estado a demanda** (en cualquier momento, sobre el mes en curso hasta ahora):

```
📊 Estado de noviembre (hasta hoy, día 12)
• Consultas de horario: 85
• Usuarios: 15
• Mensajes: 110
• Coste aproximado de mensajería: 0,00 € (dentro de los mensajes gratuitos del mes)
```

Una métrica en 0 se muestra igual (distingue "no pasó nada" de "no se sabe"). El texto
cabe sin problema en el límite de 4.096 caracteres de un mensaje; no necesita paginarse.

## 8. Tests

- `tests/core/test_actions.py` (o donde correspondan): `RecordMetric` se transforma en
  `MetricEvent`, es idempotente (dos acciones con el mismo `idem_key` crean una sola fila).
- `tests/flowpilot/test_summary.py` (nuevo):
  - `previous_month`: dado el 1 de noviembre, da `[1 de octubre, 1 de noviembre)`
    completo — ni un día de más ni de menos; caso de borde de cambio de año (1 de
    enero → diciembre del año anterior).
  - `month_to_date`: `start` es el día 1 del mes de `now` a las 00:00 en la zona
    horaria del tenant, incluido el caso de borde (hoy es día 1: el periodo es solo
    ese día, no se adelanta al mes anterior — a diferencia de `previous_month`, que sí
    lo haría).
  - `_generic_metrics` ("usuarios"): un contacto activo dentro del mes anterior
    (`previous_month`) pero también en el mes en curso (antes del día 1, cuando se
    genera el resumen automático) sí cuenta en el resumen del mes anterior — el caso
    que `last_activity_at` habría dejado fuera (decisión 9).
  - construcción del texto con datos variados (cero, varias cifras, redondeo de euros);
    un mes sin actividad da todo a cero, no omite el resumen.
  - un negocio `paused` u `onboarding` no lo recibe; uno con `summary_monthly=False`
    no lo recibe.
  - el disparo automático solo ocurre el día 1 del mes (en la zona horaria del
    tenant), y siempre con los datos de `previous_month`, no de `month_to_date`: un
    día cualquiera de en medio del mes no manda nada, aunque `summary_monthly` esté
    activado.
  - idempotencia del `idem_key` por mes reportado (`{año}-{mes}` de `previous_month`):
    dos disparos del job el mismo día 1 no duplican el envío.
  - `_messaging_cost`: franja gratuita de "service" consumida parcialmente y agotada
    dentro del periodo (el corte exacto entre mensajes gratis y facturables), probado
    tanto con `previous_month` como con `month_to_date`; categorías sin franja se
    multiplican directo; Telegram no cuenta.
  - estado a demanda: funciona con `summary_monthly=False` si hay `telegram_chat_id`;
    da los datos del mes en curso (`month_to_date`), distintos de los que daría el
    resumen automático (que sería del mes anterior); `chat_id` sin tenant responde
    preguntando, no adivina.
- `tests/packs/salon`: `create()` y `cancel()` emiten los `RecordMetric` esperados,
  con el valor de euros correcto; un movimiento de cita no emite `booking_cancelled`;
  una cita manual en Calendar no emite nada (vía `classify()`, sin pasar por el bot).
- `tests/packs/bus`: una consulta con itinerario encontrado (`con_salidas`) emite
  `schedule_query`; un menú, error o "no hay horarios" no lo emite.
- Escenario de conversación (CLAUDE.md lo exige para cualquier cambio de flujo): no es
  estrictamente un cambio de flujo (no cambia ninguna respuesta al cliente en los packs),
  así que no hace falta un escenario nuevo para la parte periódica; **el estado a
  demanda sí es una conversación nueva con el dueño** y necesita su propio escenario
  (petición → respuesta, chat_id desconocido → pregunta, chat_id ambiguo → pregunta).

## 9. Documentación

- `docs/packs/salon.md` y `docs/packs/bus.md`: tabla de métricas de la sección 3,
  y cómo activar `owner.summary_monthly`.
- `docs/runbooks/alta-baja-negocio.md`: mencionar el resumen y el estado a demanda como
  pasos opcionales del alta (si el dueño lo quiere).
- ADR nuevo en `docs/adr/` (al implementarlo, no antes), con al menos estas decisiones:
  - un evento de negocio genérico (`RecordMetric`/`MetricEvent`) en vez de leer la
    agenda o el calendario en el momento del resumen;
  - un periodic de plataforma en vez de uno por pack para el envío;
  - **dar al bot de avisos un webhook entrante** (hoy solo de salida), con la resolución
    de `chat_id` → tenant y su manejo de ambigüedad.
- Tabla de precios aproximados de WhatsApp por categoría: documentar la fuente y la
  fecha de la última comprobación (los precios reales están en el panel de facturación
  de WhatsApp Business Manager de cada negocio, no en este repo), y recordar revisarla
  si Meta cambia tarifas (hasta 4 veces al año, el día 1 de cada trimestre).

## 10. Acciones manuales

Ninguna para el envío periódico: reutiliza el bot de avisos (`NOTIFY_BOT_TOKEN`) y el
`telegram_chat_id` que ya tiene cada negocio con avisos activados. Activar el resumen de
un negocio es solo editar su `tenant.yaml` (`owner.summary_monthly: true`).

Para el estado a demanda (decisión 11), al activar el webhook entrante del bot de avisos
hay que registrarlo contra la API de Telegram (`setWebhook`), igual que ya se hace para
los bots de negocio — es un paso de puesta en marcha, no algo que un agente haga contra
producción sin aprobación.

## 11. Fuera de alcance

- **Elegir qué métricas se muestran por negocio** (en vez de "todas las que declare su
  pack"). Se añade si algún negocio concreto lo necesita.
- **"Qué se pidió más"** (el servicio más reservado, la línea más consultada): pide
  agrupar por una dimensión de texto, no solo sumar un número, y una regla de qué hacer
  si hay empate o pocos datos. Se deja para una iteración posterior si se quiere.
- **Resumen por email o PDF**: el canal es el mismo bot de avisos de Telegram; un
  resumen más largo (por ejemplo con gráfica) es un formato distinto, no una extensión
  de este.
- **Comparar con el periodo anterior** ("un 10% más que el mes pasado"): útil, pero
  exige guardar o recalcular el periodo previo; se deja para cuando haya varios
  resúmenes reales que comparar.
- **Más comandos a demanda que "estado"** (por ejemplo "estado del mes pasado", un
  rango de fechas libre, u otras preguntas al bot): el webhook entrante que añade esta
  mejora se limita a esa única frase, sobre el mes en curso; un lenguaje de comandos
  más amplio es una pieza distinta.
- **Cualquier periodo que no sea "mes anterior completo" (automático) o "mes en curso
  hasta ahora" (a demanda)** — semana, día, trimestre, año...: se simplificó
  deliberadamente a estos dos (decisión 3). Si hiciera falta otro grano, es una
  iteración posterior, no esta.
