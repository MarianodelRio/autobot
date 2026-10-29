# Pack `salon`

Gestiona reservas de peluquería con Google Calendar. En el menú el cliente puede
pedir, ver, mover o cancelar citas. Si `special_event.active` está activo aparece
la reserva del evento; si `info_text` contiene texto aparece Contacto. La reserva
ofrece solo huecos libres, vuelve a comprobar el hueco antes de escribir y usa un
id determinista para que reintentar el mismo mensaje no duplique la cita.

La configuración está en `tenants/<slug>/tenant.yaml`, bloque `config`:

| Campo | Uso |
|---|---|
| `business_name`, `contact_phone` | Nombre y teléfono que ve el cliente. |
| `calendar_id` | Calendario de Google donde se guardan las citas. |
| `services` | De 1 a 9 claves `a-z0-9_`, cada una con `name`, `price_eur`, `duration_min` y `client_presence_min`. |
| `opening_hours` | Franjas semanales `HH:MM-HH:MM`; día ausente significa cerrado. |
| `slot_step_min`, `min_notice_min`, `booking_window_days`, `max_active_bookings` | Paso de las horas, antelación, horizonte y límite de citas. |
| `reminders_enabled`, `reminder_window_hours` | Barrido de recordatorios. |
| `manual_confirmations_enabled`, `manual_confirmations_since` | Avisos de citas manuales creadas desde una fecha; la fecha es obligatoria si se activa. |
| `special_event`, `info_text`, `texts` | Evento especial, contacto y textos sobrescribibles. |

El servicio debe ocupar como máximo el tiempo de presencia del cliente
(`duration_min ≤ client_presence_min`). Los eventos `[CFG] CERRADO`,
`[CFG] VACACIONES` y `[CFG] HORARIO HH:MM-HH:MM` ajustan los huecos del día. El
bot distingue citas propias por metadatos privados de Calendar; una cita creada
a mano necesita `Telefono:` en la descripción para que el barrido pueda
identificarla. Para probar cambios sin tocar el calendario real se usa
`FakeCalendar` (ver `packs/salon/testing.py`) o el negocio de demo
`demo-peluqueria` (`docs/runbooks/demo.md`).

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

Para activar el resumen mensual del negocio, añade en su `tenant.yaml`:

```yaml
owner:
  summary_monthly: true
```

Requiere que el dueño ya esté vinculado al bot de avisos (`manage.py owner_invite
<slug>`, no un dato en YAML: ver `docs/runbooks/alta-baja-negocio.md`). Llega por el
mismo bot el día 1 de cada mes, con los datos del mes anterior ya cerrado, y también se
puede consultar en cualquier momento escribiéndole al bot ("Cómo va el mes").

Para cambiar horario o servicios, edita YAML, ejecuta `make check`, prueba una
reserva completa y una cancelación con `FakeCalendar` o con `demo-peluqueria`,
y despliega el SHA aprobado. Usa `tenant_health <slug>` para comprobar acceso
Calendar y plantillas antes de activar el canal real. Los procedimientos de
incidencia y de secretos están en `docs/runbooks/04-calendar.md` y
`docs/runbooks/09-rotar-secretos.md`.
