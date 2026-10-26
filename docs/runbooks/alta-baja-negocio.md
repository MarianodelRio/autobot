# Alta y baja de un negocio

## Alta

1. `manage.py new_tenant <slug> --pack salon|bus --channel whatsapp|telegram` crea
   `tenants/<slug>/tenant.yaml` con `id`, `public_id` aleatorio, `status: onboarding` y
   la config por defecto del pack.
2. Completar la config (`docs/packs/<pack>.md`). En `bus`, añadir el dataset y pasar
   `make bus-validar`.
3. **Pruebas:** añadir a `testers.telegram` los ids de Telegram de las personas del
   negocio que vayan a probar.
4. **Canal `main`:**
   - WhatsApp: seguir el checklist de abajo, declarar `channel` y añadir sus secretos a
     `secrets.yaml` (`app_secret`, token permanente y `verify_token`).
   - Telegram: crear el bot con @BotFather a nombre del negocio, declarar `channel` y
     añadir `bot_token` y `webhook_secret` a `secrets.yaml`.
5. **Google Calendar** (`salon`): el negocio comparte su calendario con la cuenta de
   servicio («Hacer cambios en los eventos») y se pone su id en `calendar_id`. El
   operador crea un calendario de pruebas, lo comparte igual y pone su id en
   `test_calendar_id`; deben ser distintos. Si el canal es WhatsApp, crear las
   plantillas del pack en el WhatsApp Manager.
6. **Avisos al dueño** (opcional): `manage.py notify_link <slug>`.
7. Commit y despliegue. Si el canal `main` es Telegram, `manage.py telegram_set_webhook <slug>`.
8. `manage.py tenant_health <slug>` en verde.
9. Pruebas con el negocio por el bot de pruebas y, por el canal `main`, con los ids de
   `testers.main`.
10. `status: active`, commit y despliegue. `make qr SLUG=<slug>` genera el QR del canal
    para el local. Activar el canal real necesita aprobación humana explícita.

### Checklist de un número de WhatsApp

La app de Meta, la WABA y el número están en el Business Portfolio del negocio, con el
operador como administrador; una app y un número por negocio.

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
