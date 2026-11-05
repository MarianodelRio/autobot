# Alta y baja de un negocio

## Alta

1. Preparar un directorio con `document.yaml` y los datasets necesarios en
   `datasets/<nombre>/`; el nombre antiguo `tenant.yaml` también se acepta al importar.
   Usar un UUIDv7 propio, `public_id` aleatorio y `status: onboarding`. Completar la
   config según `docs/packs/<pack>.md`; en el panel, `Clientes → Nuevo cliente` hace
   lo mismo con un asistente.
2. Declarar el canal y sus ids. Los secretos se pasan en un YAML privado de formato
   `slug: {campos...}`: WhatsApp usa `app_secret`, `access_token` y `verify_token`;
   Telegram, `bot_token` y `webhook_secret` (32 caracteres o más). Nunca van en el documento.
3. `manage.py tenant_config import <dir> --secrets <yaml> --comment "Alta"` publica
   la configuración en la BD del entorno. Cifra los secretos y valida el conjunto antes
   de guardar nada. Para `bus`, sin datasets se copian los iniciales de su plantilla.
4. En `salon`, el negocio comparte su calendario con la cuenta de servicio y declara
   su `calendar_id`. Las plantillas de WhatsApp deben estar creadas y aprobadas.
5. `manage.py owner_invite <slug>` genera el enlace privado y de un solo uso para el
   dueño. `owner.notify` y `owner.summary_monthly` se cambian en la configuración
   versionada, exportando y volviendo a importar. `owner_unlink` desconecta el chat.
6. La persona registra el webhook con `telegram_set_webhook <slug>` si procede y
   ejecuta `tenant_health <slug>`. Con `onboarding`, solo se atiende a `testers.main`.
7. Antes de activar: documento válido, ids y secretos completos, salud sin errores
   críticos, plantillas aprobadas y al menos un mensaje real de un tester por `main`.
   En el panel, la ficha del cliente muestra esas comprobaciones y «Activar» pide
   escribir el slug; la baja siempre se hace por terminal.

Para editar, `tenant_config export <slug> <dir>` crea un directorio nuevo o vacío,
sin secretos. Después de editar, `tenant_config import <dir> --comment "Motivo"`
crea otra versión; en el panel, la ficha del cliente edita la config con formulario
o YAML (diff y comentario obligatorio) y guarda cada versión en su historial. Los
seis campos de identidad y estado no se cambian por importación.
Pausar o reactivar: `tenant_status <slug> pause|resume`, o el mismo botón en la
ficha del cliente. Los datasets también pueden
publicarse con `tenant_dataset import <slug> <nombre> <dir> --comment "Motivo"`.

Los cambios se aplican sin commit ni despliegue, en la siguiente comprobación de revisión
(como máximo dos segundos). Las acciones sobre producción las ejecuta la persona.

### Checklist de un número de WhatsApp

La app de Meta, la WABA y el número están en el Business Portfolio del negocio, con el
operador como administrador; una app y un número por negocio. Explicación no técnica
de este modelo y de cómo migrarlo en el futuro: `docs/runbooks/alta-whatsapp-meta.md`.

- SIM sin WhatsApp activo.
- Gmail y Business Portfolio del negocio.
- Verificación de empresa (2–5 días hábiles; necesaria para el nombre visible).
- App de tipo Business con el producto WhatsApp y el número registrado.
- App suscrita a la WABA (`POST /<WABA_ID>/subscribed_apps`) y campo `messages` suscrito.
- System User con token permanente (`whatsapp_business_messaging`,
  `whatsapp_business_management`).
- Webhook de la app: `https://api.<dominio>/webhooks/whatsapp/<public_id>` con el
  `verify_token` del tenant.
- Plantillas del pack creadas y aprobadas (de 1 a 48 h). `bus` no usa plantillas.

Desde el 1/10/2026 Meta cobra también las respuestas dentro de la ventana de 24 h al
precio *utility* del país; la tarifa se consulta en la cuenta de cada negocio.

### Precios aproximados de mensajería (resumen mensual)

El "coste aproximado de mensajería" del resumen al dueño
(ADR-007, `autobot/runtime/costs.py:PRICE_EUR`) suma
todos los mensajes que Meta marca como facturables (`billable=True` en el webhook de
estados) en el periodo, agrupados por la categoría que indica el propio webhook
(`pricing_category`), con esta tabla de precios aproximados en euros por mensaje, para
España:

| Categoría | Precio aprox. |
|---|---|
| `marketing` | 0,0585 € |
| `utility` | 0,0166 € |
| `authentication` | 0,0166 € |
| `service` (ventana de 24 h) | 0,0166 € |

Ya no se calcula ninguna franja gratuita por nuestra cuenta: desde el 1/10/2026 Meta
aplica sus propias franjas (1.000 mensajes `service` gratis al mes por número, entradas
gratuitas por anuncio, etc.) y marca esos mensajes como `billable=False`, así que
simplemente no cuentan. Una categoría que no esté en la tabla (por ejemplo, una nueva
que añada Meta) se valora al precio más alto de la tabla, para que el coste nunca se
quede corto en silencio.

**No es la tarifa real de ninguna cuenta.** Meta publica el rate card exacto, por
país y moneda, en el panel de facturación de WhatsApp Business Manager de cada
negocio, y cambia como máximo una vez por trimestre (el día 1). Estos valores son
una estimación interna sin contrastar contra ese panel, comprobada por última vez
el 29/10/2026 ("service" a la tarifa de `utility`, sin confirmar); revísalos si Meta
anuncia un cambio de tarifas y, sobre todo, antes de presentar el coste del resumen
como una cifra fiable. Telegram no tiene coste por mensaje y no entra en este cálculo.

## Negocio de demo de un pack nuevo

Cada pack nuevo trae su propio negocio de demostración, para enseñarlo por las dos
puertas del bot de demo sin usar ningún negocio real (ver `docs/runbooks/demo.md`).

1. Crear `apps/backend/packs/<pack>/template/document.yaml` con un UUIDv7 fijo,
   `demo.description` y `status: paused`, sin `channel` ni `testers`.
2. Completar la config con datos ficticios y añadir los datasets necesarios en
   `template/datasets/<nombre>/`.
3. Declarar `Pack.template` y `Pack.template_blank`: los campos de config que deben
   vaciarse al iniciar un negocio real. En `salon` son calendario, teléfono y nombre.
4. Escribir el escenario de conversación sobre la plantilla y ejecutar `make check`.
5. Hacer commit de la plantilla y sus tests. `manage.py seed_demos` crea los demos que todavía no tienen versiones; después los
   cambios operativos se hacen sobre el demo de la BD, sin sobrescribirlo con la plantilla.
   Un calendario de demo debe pertenecer a la persona operadora y estar compartido con
   la cuenta de servicio antes de probar reservas reales.

## Baja

La persona operadora registra la fecha efectiva de baja y ejecuta el borrado en un
máximo de 30 días; `synced_at` no es una fecha de baja. La entrada del tenant se
conserva hasta comprobar el borrado (ver `retencion-rgpd.md`).

1. `manage.py tenant_status <slug> offboard` pide escribir el slug y publica la baja.
   Los webhooks tardíos se contestan con 200 sin guardar nada.
2. Si el canal es Telegram, la persona retira el webhook mientras los secretos siguen
   disponibles.
3. `manage.py tenant_data_export <slug> --output <ruta-privada>`, si se acordó con el negocio.
4. `manage.py tenant_purge <slug>` exige de nuevo el slug y comprueba que sigue dado de
   baja. Borra contactos, conversaciones, eventos, mensajes, avisos, métricas, secretos y
   versiones de datasets. Deja una sola versión del documento, con `testers.main: []`
   y `owner: null`, y conserva el espejo para los webhooks tardíos. Se audita atómicamente.
5. El negocio revoca el acceso del operador a Meta y deja de compartir el calendario.
6. Retirar las copias locales de importación o guardarlas cifradas fuera del repositorio.
   Las copias antiguas de la BD caducan con la retención de backups; ver RGPD.
