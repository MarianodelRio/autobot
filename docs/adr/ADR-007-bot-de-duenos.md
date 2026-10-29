# ADR-007 — El bot de avisos se convierte en el asistente del dueño

**Estado:** aceptada

## Contexto

El bot de Telegram de avisos (`NOTIFY_BOT_TOKEN`) solo enviaba: citas creadas,
canceladas, movidas, y el resumen mensual. Vincular el chat de un dueño exigía un
comando manual con `getUpdates` (`notify_link`) y guardar su `chat_id` en
`tenant.yaml`, en texto plano, en git. Dar de alta a un dueño nuevo o cambiarlo de
chat exigía un commit y un despliegue, por un dato que no es configuración del
negocio, sino personal.

Se añade un asistente: el dueño puede escribirle al bot y preguntar cómo va el mes en
curso, o pedir el contacto del operador. Eso
exige que el bot tenga webhook entrante — hasta ahora era puramente de salida — y que
la plataforma sepa, al recibir un mensaje, a qué negocio pertenece ese chat sin
conocerlo todavía.

## Decisión

- **El `chat_id` del dueño vive en una tabla de plataforma, `owner_link`, sin RLS**,
  igual que `demo_session` (ADR-006): al llegar un mensaje al bot solo se tiene el
  `chat_id`, y hay que *buscar* el negocio a partir de él, lo mismo que hace el
  selector de la demo. `owner.telegram_chat_id` desaparece de `tenant.yaml`.
- **Vinculación por enlace de un solo uso**: `manage.py owner_invite <slug>` genera un
  código aleatorio, guarda su sha256 en `owner_link.invite_hash` (caduca a los 7
  días) y muestra `t.me/<bot>?start=<código>`. El dueño lo abre y queda conectado al
  momento; el código nunca se registra en logs. `manage.py owner_unlink` desconecta
  un chat (cambio de dueño, petición RGPD).
- **Un chat se conecta a lo sumo a un negocio real**; solo los negocios de demo
  pueden compartir chat entre sí (igual que comparten calendario). La comprobación
  vive en código, no en una restricción de base de datos, porque la demo la rompe a
  propósito.
- **El webhook entrante del bot de avisos lleva `secret_token`**, como los demás
  bots de Telegram (`NOTIFY_BOT_WEBHOOK_SECRET`); sin él, 404, como la puerta de
  demo. Esto es un cambio en la firma de webhooks y, junto con la tabla sin RLS,
  requiere aprobación explícita (concedida el 2026-10-29).
- **Un evento entrante del bot de avisos** se guarda en `owner_event`, sin RLS y sin
  datos personales en sus índices, y se procesa como el resto de la entrada
  (idempotente por `update_id`, marcado `done` antes de responder, candado por chat
  con solo un hash). El bot de avisos pasa a comprobarse con webhook, como el de
  demo, en vez de con `getUpdates`.
- **Menú declarativo** (`autobot/owner/menu.py`): cada opción es una entrada de `MENU`
  (id `owner:<nombre>`, título, respuesta y disponibilidad). Hoy hay dos: "📊 Cómo va
  el mes" y "✉️ Contacto" (solo si `OWNER_SUPPORT_EMAIL` está definido). Hasta 3
  opciones van como botones; de 4 a 10, como lista.

### Resumen del dueño (decidido con la persona el 2026-10-29)

- **Dos periodos de calendario**, en la zona horaria del negocio:
  - **Automático:** el mes anterior completo. Sale el día 1 a partir de las 12:00
    locales. El periodic corre cada hora y un envío perdido se recupera ese mismo día;
    la clave `summary:<tenant>:<año-mes>` evita duplicados.
  - **A demanda:** desde el día 1 a las 00:00 hasta ahora, **solo lo ya pasado**.
- **Cada pack aporta sus líneas** con el gancho `Pack.summary(ctx, start, end, recorded)`,
  que se ejecuta sin transacción abierta. La plataforma no sabe qué es una cita.
  - **`salon`** lee las citas **del calendario, que es la fuente de verdad**: así cuenta
    las manuales, y una cita cancelada (borrada) o movida nunca se cuenta dos veces. Es
    cita un evento del bot o uno cuyo título empieza por el nombre de un servicio, igual
    que los del bot (`"<Servicio> - <Nombre>"`). Gana el nombre más largo, sin distinguir
    mayúsculas, acentos ni el tipo de guion. Los demás eventos (vacaciones,
    `[CFG] …`, recados) y los de todo el día no cuentan, y no hay línea de canceladas.
    Los ingresos estimados suman el `price_eur` **actual** del servicio de cada cita.
  - **`bus`** cuenta consultas de horario con `RecordMetric`/`MetricEvent`, porque no
    tiene calendario.
- **Métricas de plataforma**, sobre `OutboundMessage` con `status="sent"`, por `sent_at`:
  - clientes atendidos y mensajes enviados;
  - **coste de WhatsApp**: los mensajes con `billable=True` por un precio aproximado por
    categoría (`PRICE_EUR`). No se calcula la franja gratuita: Meta ya marca como no
    cobrados los 1.000 "service" gratis al mes por número, incluido el número de demo
    compartido. Una categoría desconocida se valora al precio más alto.
- Si falla el gancho del pack, el resumen automático se reintenta en lugar de salir sin
  citas; el estado a demanda muestra un aviso en su lugar.
- Un negocio de demo responde a "Cómo va el mes" aunque esté `paused`, porque la demo
  existe para enseñar la función. Un negocio real que no está `active` responde que aún
  no está activo.

## Alternativas consideradas

- **Seguir con `owner.telegram_chat_id` en YAML y solo mejorar el comando manual**:
  no resuelve el problema de fondo (un dato personal en git, un commit por alta) y
  no permite el asistente conversacional sin añadir ya un webhook entrante de todos
  modos.
- **Una fila `owner_link` con RLS, vinculada al tenant desde el principio**: no es
  posible — al llegar el mensaje no se sabe aún de qué tenant es, que es justo lo que
  RLS necesita saber primero (`app.tenant_id`).
- **Vinculación por `/start <slug>` en vez de un código**: expondría el slug del
  negocio (no es secreto, pero permitiría a cualquiera intentar vincularse a un
  negocio ajeno); un código aleatorio de un solo uso no tiene ese problema y además
  es la mecánica nativa de Telegram para enlaces de inicio.

## Consecuencias

- Dar de alta o cambiar el dueño de un negocio ya no exige commit ni despliegue:
  `manage.py owner_invite <slug>` y enviar el enlace.
- El bot de avisos pasa a tener la misma superficie de ataque que la puerta de demo
  (un webhook público), con las mismas defensas (secreto, límite por IP, límite de
  tamaño) y los mismos límites de respuesta sin vínculo (como mucho 3 veces por hora
  y chat).
- `tools`/scripts que leyeran `owner.telegram_chat_id` de `tenant.yaml` dejan de
  funcionar; ninguno lo hacía fuera de la plataforma misma.

## Cuándo revisarla

- Si un negocio necesitara varios dueños (varios chats) a la vez, `owner_link` tendría
  que dejar de ser una fila por tenant; de momento ningún negocio lo ha pedido.
