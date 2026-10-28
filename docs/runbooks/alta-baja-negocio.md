# Alta y baja de un negocio

## Alta

1. `manage.py new_tenant <slug> --pack salon|bus --channel whatsapp|telegram` crea
   `tenants/<slug>/tenant.yaml` con `id`, `public_id` aleatorio, `status: onboarding` y
   la config por defecto del pack.
2. Completar la config (`docs/packs/<pack>.md`). En `bus`, añadir el dataset y pasar
   `make bus-validar`.
3. **Canal `main`:**
   - WhatsApp: seguir el checklist de abajo, declarar `channel` y añadir sus secretos a
     `secrets.yaml` (`app_secret`, token permanente y `verify_token`).
   - Telegram: crear el bot con @BotFather a nombre del negocio, declarar `channel` y
     añadir `bot_token` y `webhook_secret` a `secrets.yaml`.
4. **Google Calendar** (`salon`): el negocio comparte su calendario con la cuenta de
   servicio («Hacer cambios en los eventos») y se pone su id en `calendar_id`. Si el
   canal es WhatsApp, crear las plantillas del pack en el WhatsApp Manager.
5. **Avisos al dueño** (opcional): `manage.py notify_link <slug>`. Con el vínculo ya
   hecho, el resumen mensual (opcional) se activa con `owner.summary_monthly: true`
   en su `tenant.yaml` (ver `docs/packs/<pack>.md`); llega por el mismo bot el día 1
   de cada mes, con los datos del mes anterior.
6. Commit y despliegue. Si el canal `main` es Telegram, `manage.py telegram_set_webhook <slug>`.
7. `manage.py tenant_health <slug>` en verde.
8. **Pruebas:** añadir a `testers.main` los ids (Telegram) o teléfonos/BSUID
   (WhatsApp) de las personas del negocio que vayan a probar; con `status:
   onboarding`, el canal `main` solo les contesta a ellas. No hay bot de pruebas
   aparte: se prueba por el canal real del negocio.
9. `status: active`, commit y despliegue. `make qr SLUG=<slug>` genera el QR del canal
   para el local. Activar el canal real necesita aprobación humana explícita.

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
(`docs/mejoras/02-avisos-y-resumenes.md`, `flowpilot/runtime/summary.py:PRICE_EUR`) usa
esta tabla, en euros por mensaje, para España:

| Categoría de plantilla | Precio aprox. | Franja gratuita mensual |
|---|---|---|
| `service` (ventana de 24 h) | 0,0730 € | 1.000 mensajes por número |
| `utility` | 0,0394 € | ninguna |
| `marketing` | 0,0988 € | ninguna |
| `authentication` | 0,0363 € | ninguna |

**No es la tarifa real de ninguna cuenta.** Meta publica el rate card exacto, por
país y moneda, en el panel de facturación de WhatsApp Business Manager de cada
negocio, y cambia como máximo una vez por trimestre (el día 1). Estos valores son
una estimación interna sin contrastar contra ese panel, comprobada por última vez
el 27/10/2026; revísalos si Meta anuncia un cambio de tarifas y, sobre todo, antes
de presentar el coste del resumen como una cifra fiable. Telegram no tiene coste
por mensaje y no entra en este cálculo.

## Negocio de demo de un pack nuevo

Cada pack nuevo trae su propio negocio de demostración, para enseñarlo por las dos
puertas del bot de demo sin usar ningún negocio real (ver `docs/runbooks/demo.md`).

1. `manage.py new_tenant demo-<pack> --pack <pack> --demo "<descripción>"` crea
   `tenants/demo-<pack>/tenant.yaml` con `demo.description` y `status: paused` (sin
   `channel` ni `testers`: un negocio de demo no tiene canal propio).
2. Completar la config del pack como la de cualquier negocio, con datos inventados
   razonables (sin credenciales ni ids reales ajenos a la persona operadora).
3. Si el pack necesita calendario (`salon`): comparte un calendario de la persona
   operadora con la cuenta de servicio y pon su id en `calendar_id`; las dos puertas lo
   usan igual, no hay calendario de pruebas aparte.
4. Escribir el escenario de conversación del pack sobre este negocio (obligatorio,
   como el de cualquier cambio de flujo).
5. `status: active`, commit. No requiere aprobación especial: un negocio de demo nunca
   toca el canal real de un cliente.

## Baja

La persona operadora registra la fecha efectiva de baja y ejecuta el borrado en un
máximo de 30 días; `synced_at` no es una fecha de baja. La entrada del tenant se
conserva hasta comprobar el borrado (ver `retencion-rgpd.md`).

1. `status: offboarded` y despliegue: los webhooks se contestan con 200 sin guardar nada.
2. `manage.py export_tenant <slug>`, si se acordó con el negocio.
3. `manage.py purge_tenant <slug>` borra contactos, conversaciones, eventos, mensajes y
   avisos. Pide escribir el slug para confirmar.
4. Quitar su entrada de `secrets.yaml` y, si su canal es Telegram, `deleteWebhook` de su bot.
5. El negocio revoca el acceso del operador a su portfolio de Meta y deja de compartir
   el calendario.
6. Borrar `tenants/<slug>/`.
