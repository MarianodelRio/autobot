# ADR-015 — Varios peluqueros en `salon`

**Estado:** Aceptada — pendiente de implementar

> Nota: el código aún no lo implementa (`SalonConfig` tiene un solo `calendar_id` y `periodic.py` y `check.py` siguen mirando `name == "calendar_sweep"`).

## Contexto

Hoy `salon` asume un solo calendario por negocio: `SalonConfig.calendar_id`, bindado por
la plataforma a `ctx.calendar` (un único `CalendarPort`) en `autobot/runtime/context.py`
(`bound_calendar_id`, `build_context`). `Pack.needs_calendar: bool` es todo lo que un pack
declara; la plataforma no sabe nada de "varios calendarios" ni de a quién pertenece cada
uno. Un negocio con más de un peluquero necesita hoy un calendario por persona, y el
pack no tiene manera de repartir citas entre ellos.

La plataforma expone además dos sitios que adivinan el nombre de un periodic en vez de
que el pack lo declare: `autobot/runtime/periodic.py` (`record(..., sweep=name ==
"calendar_sweep")`) y `autobot/ops/check.py` (`any(p.name == "calendar_sweep" for p in
tenant.pack.periodic)`, usado también por el recuento «N de M accesibles» de la tarjeta
Estado del Sistema). Esto es independiente de varios peluqueros, pero toca el mismo
contrato (`Periodic`) y conviene resolverlo a la vez.

`autobot/ops/state.py` guarda el estado de Calendar por `(tenant_id, channel)`:
`record_calendar(tenant_id, channel, status)` escribe `calendar_errors` y
`calendar_unavailable` en una sola entrada de caché por canal. Con varios calendarios,
una llamada "ok" a un calendario resetearía `calendar_unavailable` aunque otro calendario
del mismo canal esté caído: el estado de uno tapa el de otro (trampa ya identificada al diseñarlo).

## Decisión

- **Se amplía `salon`, no se crea un pack nuevo.** Un calendario por peluquero. Con un
  solo peluquero el flujo no cambia (incluida la demo y los negocios existentes:
  ver «Migración» más abajo).
- **Tope de 8 peluqueros** (8 filas + «me da igual» + «volver» = 10, el límite común de
  una lista de botones/filas, `core.limits`).
- **Clave de peluquero:** `[a-z0-9]{1,4}`, estable (no se reutiliza al borrar uno),
  validada igual que las claves de servicio (`SalonConfig.service_keys`). Corta porque
  el pack la usa en candados (`ctx.lock`) y en claves de métricas/estado, nunca en el id
  del evento de Google (ese sigue siendo opaco y no colisiona entre calendarios
  distintos, así que no necesita llevar la clave).
- **Contrato del pack (`core/pack.py`):**
  - `Pack.needs_calendar: bool` se sustituye por `Pack.calendars: Callable[[BaseModel],
    Sequence[str]] | None`: dado la config ya validada, las claves de calendario que el
    pack necesita (p. ej. `["ana", "bea"]`, o `["main"]` para un pack de un solo
    calendario que prefiera no migrar a varios — `bus` no lo declara y sigue sin
    calendario). Nunca None ni vacío si está declarado: una config sin peluqueros no es
    válida (lo exige `SalonConfig`, ver abajo).
  - `PackContext.calendar: Any` se sustituye por `PackContext.calendars: Mapping[str,
    Any]`, con una entrada por clave de `Pack.calendars(config)`. Nunca parcial: si un
    calendario no está accesible, su valor es igualmente un `CalendarPort` (las
    llamadas fallarán con `TransientError`/`PermanentError` como hoy); la plataforma no
    decide por el pack qué hacer con un calendario caído.
  - `Periodic.tracks_health: bool = False` y `Periodic.metric_labels: tuple[str, ...] =
    ()` sustituyen a los dos sitios que miran `p.name == "calendar_sweep"`.
    `tracks_health` reemplaza el uso en `ops/check.py` (cuenta para «N de M
    accesibles») y en `periodic.py` (`record(..., sweep=periodic.tracks_health)`).
    `metric_labels` documenta qué claves de `ctx.lock`/estado genera este periodic (hoy
    ninguna lo necesita fuera de calendar_sweep; se deja declarado para que
    `ops/state.py` pueda, en el futuro, purgar por patrón sin adivinar nombres).
- **Estado y salud por calendario, no por canal (`autobot/ops/state.py`):**
  - `record_calendar(tenant_id, channel, status)` pasa a `record_calendar(tenant_id,
    channel, calendar_key, status)`, con una entrada de caché por
    `(tenant_id, channel, calendar_key)` (`key()` gana un segmento opcional). Cada
    calendario mantiene su propio `calendar_errors`/`calendar_unavailable`.
  - `ops/check.py` y `ops/health.py` iteran las claves de `tenant.pack.calendars(config)`
    (cuando el pack las declara) en vez de mirar una sola entrada: un calendario caído
    nunca queda tapado por el `ok` de otro. El mensaje de salud identifica el peluquero
    por su clave, nunca por nombre real (`HealthIssue("calendar_unavailable:<clave>",
    ...)`), igual que ya se hace con el canal.
  - La tarjeta Sistema sigue mostrando «N de M accesibles» a nivel de negocio: un
    negocio con un calendario caído de ocho cuenta como «no accesible» para esa fila (M
    sigue siendo el número de negocios, no de calendarios — no se cambia esa semántica,
    solo se corrige qué hace que un negocio cuente como caído).
- **Candados:** `ctx.lock` deja de incluir el calendario en su prefijo (antes
  `f"{tenant}:{calendar_id}:{key}"`, con un solo calendario posible); pasa a
  `f"{tenant}:{key}"`, y es el pack quien compone `key` con la clave de peluquero
  (`f"cal:{stylist}:{day.isoformat()}"`). Evita que la plataforma necesite saber cuántos
  calendarios hay.
- **Reserva idempotente con «me da igual» (evita doble reserva):** antes de llamar a
  `insert_event`, el pack guarda con `ctx.effects.put` la asignación elegida (clave de
  peluquero + hueco) bajo la clave idempotente del evento (`ctx.idem.event(operation)`).
  Un reintento lee primero `ctx.effects.get`: si ya hay una asignación, la reutiliza en
  vez de recalcular «el de menos citas ese día» (que podría devolver otro peluquero y
  duplicar la cita en dos calendarios). El candado de reserva se toma **después** de
  elegir peluquero (leyendo el efecto o calculándolo) y **revalidando el hueco** bajo el
  candado, igual que hoy hace `booking.reserve` con un solo calendario.
- **Coste en Google:** reservar pasa de 6 llamadas a `N + 5` (una lectura de huecos por
  calendario), o `4N + 2` cuando el cliente pide «me da igual» (hay que mirar la
  disponibilidad de los N para poder unirla y elegir). Con el tope de 8, 34 llamadas en
  el peor caso. Se acepta: ya es el límite acordado y no hay reserva por lotes en la API
  de Calendar que lo evite sin cambiar de proveedor.
- **Preguntas abiertas del diseño, resueltas así:**
  - **«Me da igual»:** unión de huecos de todos los peluqueros con ese servicio, elige
    al de menos citas confirmadas ese día (empate: el primero por clave) y lo dice en la
    confirmación («Te atenderá Ana»).
  - **Horario propio:** opcional por peluquero; si no se declara, hereda
    `opening_hours`/`special_event` del negocio.
  - **Servicios por peluquero:** opcional; si no se declara, ofrece todos los del
    negocio.
  - **Cierre de todo el negocio:** una lista de fechas en la config (no por peluquero),
    que cierra los N calendarios a la vez.
  - **Avisos:** solo al dueño del negocio, no por peluquero (no hay destinatario propio
    de cada uno todavía).
- **Plantillas de Meta no se tocan**: ningún texto de plantilla cambia (evita una
  aprobación nueva en Meta); el nombre del peluquero, cuando aplica, va como parámetro
  de la plantilla existente, no en texto nuevo.
- **Migración de un tenant con un solo peluquero:** `SalonConfig.calendar_id` (una
  cadena) se sustituye por `SalonConfig.stylists: dict[str, Stylist]` (clave de
  peluquero → nombre, calendar_id, horario y servicios propios opcionales), con mínimo
  una entrada. El paso `calendar_id` → `stylists: {main: {calendar_id: ...}}` para un
  documento guardado con el esquema antiguo se hará con una migración puntual de los
  documentos de config (la migración del bot anterior, `salon/migration.py`, se retiró el
  2026-11-20 y ya no existe). Un negocio con un
  solo peluquero usa la clave `main` por convención (no elegible por el operador) y su
  flujo de conversación no pregunta «¿con quién?».

## Alternativas consideradas

- **Pack nuevo (`salon_multi` o similar):** descartada por el propio plan — duplicaría
  toda la lógica de reservas, horarios y recordatorios ya probada en `salon`, y un
  negocio no puede pasar de uno a varios peluqueros sin migrar de pack.
- **Un solo calendario para todo el negocio, con el peluquero como metadato del evento
  (no un calendario propio):** más barato en llamadas a Google, pero un peluquero no
  puede compartir *su propio* calendario ya existente (el caso real: cada peluquero ya
  tiene Google Calendar y comparte el suyo, no pide uno nuevo) y mezclaría el acceso de
  escritura de los N peluqueros en una sola cuenta compartida.
- **Candado único por negocio (no por peluquero) al reservar:** más simple, pero serializa
  las reservas de los 8 peluqueros entre sí sin necesidad; el candado por peluquero basta
  para evitar la doble reserva real (dos clientes sobre el mismo hueco del mismo
  peluquero) sin bloquear reservas simultáneas de peluqueros distintos.
- **Resolver «me da igual» sin guardar la asignación en `ctx.effects` (recalcular en cada
  reintento):** descartada explícitamente en el diseño: un reintento podría elegir otro
  peluquero y duplicar la cita.

## Consecuencias

- `core/pack.py`, `autobot/runtime/context.py`, `autobot/ops/health.py`,
  `autobot/ops/check.py`, `autobot/ops/state.py`, `autobot/runtime/periodic.py` y todo
  `packs/salon/` cambian de contrato; `bus` (sin calendario) y `toy_pack` no se tocan
  más allá de ajustar la forma del campo si `needs_calendar` deja de existir como tal.
- El panel necesita una pantalla nueva para dar de alta cada peluquero y comprobar su
  calendario por separado (puede reusar `check_write_access`).
- Los escenarios de conversación de `salon` se amplían para cubrir «con quién» y «me da
  igual», respetando los límites de cada canal.
- La demo de `salon` pasa a tener dos peluqueros por defecto, lo que exige un
  `dev-reset` (dos calendarios de demo nuevos) y no es retrocompatible con el estado de
  demo actual sin ese reinicio.
- Un negocio real sigue funcionando igual con un solo peluquero (clave `main`), sin que
  el dueño note el cambio salvo que decida añadir uno más.

## Cuándo revisarla

Si Google Calendar ofreciera alguna vez una forma de comprobar/reservar varios
calendarios en una sola llamada (hoy no existe), el presupuesto de `N + 5` / `4N + 2`
llamadas dejaría de ser la cota real y convendría revisar si el tope de 8 sigue siendo
necesario por ese motivo. Si un negocio pidiera avisos por peluquero (hoy descartado),
habría que decidir el destinatario antes de tocar `owner.notify`.
