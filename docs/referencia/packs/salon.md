# Pack `salon`

Gestiona reservas de peluquería con Google Calendar. En el menú el cliente puede
pedir, mover o cancelar citas. Si `special_event.active` está activo aparece
la reserva del evento; si `info_text` contiene texto aparece Contacto. La reserva
ofrece solo huecos libres, vuelve a comprobar el hueco antes de escribir y usa un
id determinista para que reintentar el mismo mensaje no duplique la cita.

La configuración vigente está en PostgreSQL. Se edita en el bloque `config` de un
`document.yaml` exportado con `tenant_config export` y se publica con `tenant_config import`:

| Campo | Uso |
|---|---|
| `business_name`, `contact_phone` | Nombre y teléfono que ve el cliente. |
| `calendar_id` | Calendario de Google donde se guardan las citas. |
| `services` | De 1 a 9 claves `a-z0-9_`, cada una con `name`, `price_eur`, `duration_min` y `client_presence_min`. |
| `opening_hours` | Franjas semanales `HH:MM-HH:MM`; día ausente significa cerrado. |
| `slot_step_min`, `min_notice_min`, `booking_window_days`, `max_active_bookings` | Paso de las horas, antelación, horizonte y límite de citas. |
| `reminders_enabled`, `reminder_window_hours` | Barrido de recordatorios. |
| `manual_confirmations_enabled`, `manual_confirmations_since` | Avisos de citas manuales creadas desde una fecha; la fecha es obligatoria si se activa. |
| `holidays` | Calendario de festivos (opcional, ver más abajo). |
| `special_event`, `info_text`, `texts` | Evento especial, contacto y textos sobrescribibles. |

Límites: `business_name` ≤ 60 y `contact_phone` ≤ 30 caracteres; `booking_window_days` de 1 a 90;
los textos de `texts` no pueden estar vacíos (se recortan los espacios de los extremos). La
config rechaza claves desconocidas, en cualquier nivel: un error tipográfico falla al importar.

### Festivos

```yaml
holidays:
  country: ES          # código ISO; lo valida la librería `holidays`
  subdivision: MD      # comunidad autónoma (AN, CT, MD…) o null
  closed_dates: ["2026-05-15"]   # fiestas locales, vacaciones, cierres puntuales
  open_dates: ["2026-12-08"]     # festivo en el que sí se abre
```

Con `holidays` definido, los festivos oficiales del país y la región (más `closed_dates`) no
aparecen en la lista de días ni tienen huecos, y la reserva lo revalida bajo candado. `open_dates`
reabre un festivo con su horario semanal normal; una fecha no puede estar en las dos listas.
Sin `holidays` (por defecto) solo cuenta el día de la semana, como antes. El calendario del
negocio manda siempre sobre esto: `[CFG] CERRADO` y `[CFG] VACACIONES` cierran cualquier día, y
`[CFG] HORARIO HH:MM-HH:MM` abre un día festivo o cerrado esa jornada. Los días de un
`special_event` no se ven afectados por los festivos (los eliges tú explícitamente).

El servicio debe ocupar como máximo el tiempo de presencia del cliente
(`duration_min ≤ client_presence_min`). Los eventos `[CFG] CERRADO`,
`[CFG] VACACIONES` y `[CFG] HORARIO HH:MM-HH:MM` ajustan los huecos del día. El
Cualquier otro evento de día completo (un cumpleaños, «Vacaciones» sin el prefijo `[CFG]`) **no
cierra el día por sí solo**, pero tampoco se ignora: como todo evento que no es `[CFG]` ni
cita del bot, **bloquea las horas que cubre**, y uno de día completo las bloquea todas. Es la
opción conservadora (nunca se reserva sobre algo que el peluquero ha apuntado); para cerrar
un día usa `[CFG] CERRADO`. El
bot distingue citas propias por metadatos privados de Calendar; una cita creada
a mano necesita `Telefono:` (o `WaId:`) en la descripción para que el barrido pueda
identificarla; `Tel:` no se reconoce. Para probar cambios sin tocar el calendario real se usa
`FakeCalendar` (ver `packs/salon/testing.py`, que también alimenta `manage.py chat`) o el negocio de demo
`demo-peluqueria` (`docs/procedimientos/demo.md`).

Las plantillas de WhatsApp las crea el operador en el WhatsApp Manager de cada
negocio y las aprueba Meta:

| Nombre en Meta | Texto | Botones |
|---|---|---|
| `confirmacion_cita` (Utility, `es_ES`) | "Hola {1}, tu cita ha sido confirmada para el {2} a las {3}. Si necesitas cancelarla, pulsa el botón." | Cancelar cita |
| `recordatorio_cita` (Utility, `es_ES`) | "Recuerda que tienes cita el {1} a las {2}. ¿Confirmas tu asistencia?" | Confirmar · Cancelar |

El barrido
de Calendar corre cada 15 minutos y crea avisos idempotentes; el envío real
requiere canal activo, plantillas aprobadas y consentimiento operativo. Los avisos
al dueño (`booking_created`, `booking_cancelled`, `booking_moved`,
`move_cancel_failed`) necesitan su vínculo de Telegram y los interruptores de
configuración apropiados.

### Resumen mensual al dueño

El pack declara un gancho `summary` (`packs/salon/summary.py`) que lee las citas y los
ingresos estimados **directamente del calendario**, no de mensajes ni de métricas
(ADR-007): el calendario es la fuente de
verdad, así que una cita cancelada o movida no se cuenta dos veces y una cita añadida a
mano por el peluquero también cuenta.

Un evento del periodo cuenta como cita si lo creó el bot, o si no, cuando su título
(normalizado, sin acentos ni mayúsculas) es exactamente el nombre de un servicio, o
empieza por ese nombre seguido de un guion (`-`, `–` o `—`): por ejemplo
`"Corte de pelo - Juan"`. Si varios servicios coinciden, gana el de nombre más largo
(`"Corte y barba - X"` no se confunde con `"Corte"`). Cualquier otro evento (vacaciones,
`[CFG] …`, comidas, recados) no cuenta, aunque tenga un teléfono en la descripción: hay
que pedir a cada peluquero que titule sus citas manuales como las del bot. Los ingresos
son la suma del `price_eur` **actual** de cada cita con servicio reconocido; una cita sin
precio (servicio retirado, o sin coincidencia de título) cuenta como cita pero no suma
ingresos. No hay línea de citas canceladas: solo se cuenta lo que hay en el calendario en
el periodo.

Para activar el resumen mensual del negocio, añade en su documento exportado:

```yaml
owner:
  summary_monthly: true
```

Requiere que el dueño ya esté vinculado al bot de avisos (`manage.py owner_invite
<slug>`, no un dato en YAML: ver `docs/procedimientos/alta-baja-negocio.md`). Llega por el
mismo bot el día 1 de cada mes, con los datos del mes anterior ya cerrado, y también se
puede consultar en cualquier momento escribiéndole al bot ("Cómo va el mes").

Para cambiar horario o servicios desde el panel (pestaña «Configuración»), `opening_hours`
tiene un editor por día (abierto/cerrado y tramos con selector de hora, nunca un día con
una lista vacía: cerrado quita la clave) y `services` una tabla con id numérico automático;
por terminal, edita YAML, ejecuta `make check`, prueba una reserva completa y una
cancelación con `FakeCalendar` o con `demo-peluqueria`, y publica con
`tenant_config import <dir> --comment "Motivo"`. Usa `tenant_health <slug>` para comprobar acceso
Calendar y plantillas antes de activar el canal real. Los procedimientos de
incidencia y de secretos están en `docs/incidencias/calendar.md` y
`docs/procedimientos/rotar-secretos.md`.

La plantilla inicial del demo está en `apps/backend/src/packs/salon/template/document.yaml`.
Al crear un negocio desde ella se vacían `calendar_id`, `contact_phone` y
`business_name`, para que el negocio nuevo use sus propios datos y calendario.

## Conversación

- **Nombre**: el mensaje que lo pide lleva «❌ Cancelar» (vuelve al menú sin reservar) y, si el
  contacto tiene nombre conocido, «Usar {nombre}». Las palabras de escape (`cancelar`, `volver`,
  `atrás`, `salir`, `no`, `nada`, `hola`, `gracias`, `adiós`, `ayuda`…) no son nombres y
  vuelven al menú. El nombre debe tener al menos una letra, entre 2 y 100 caracteres, y se
  limpia de `*`, `_`, `` ` ``, `~` y saltos de línea. En este paso `alta` y `baja` son texto (un
  nombre), no los comandos de avisos; en cualquier otro paso siguen siéndolo
  (`Pack.expects_free_text`).
- **Cancelar** una cita pide confirmación («¿Cancelar Corte de pelo del martes 24 de marzo a las
  10:00?» [Sí, cancelar] [No]). Los botones de cancelar de los avisos proactivos
  (`reminder_cancel`, `booking_cancel`) siguen siendo de un toque, porque son la respuesta
  explícita a un aviso de esa cita. Una cita ya pasada no se puede cancelar ni mover.
- **Mover**: la propia cita no bloquea los huecos que ocupa (ni al listarlos ni al revalidar
  bajo candado).
- **Texto libre** en un paso de lista (servicio, día, hora, cita) no pierde el progreso: se
  repite el paso con «Elige una opción de la lista o escribe *menú*». Los pies de esos mensajes
  lo dicen; en el menú, cualquier texto muestra el menú. Un audio o una imagen recibe un
  texto genérico y se repite el paso (solo en el paso del nombre se pide escribirlo).
- **Sin días**: si no queda ningún día con hueco se dice y se da el teléfono; si solo se llena el
  día elegido se avisa («No hay horarios disponibles para ese día») y se ofrecen los demás.
- **Cambio de hora**: los huecos que no existen por el cambio de hora (02:00–03:00 el último
  domingo de marzo) no se ofrecen, y la hora repetida de octubre se ofrece una vez.
