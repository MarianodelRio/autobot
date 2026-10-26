# Bot de demo

**Qué es:** la plataforma, no ningún cliente, enseña FlowPilot con dos puertas (un bot
de Telegram y un número de WhatsApp) y negocios de demostración normales en
`tenants/demo-<pack>/` (`demo-peluqueria`, `demo-autobuses`). La primera respuesta de
cualquier puerta pide elegir negocio; desde ahí la conversación es la del pack real de
ese negocio. Solo una lista cerrada de personas puede usar cada puerta (ver ADR-006).

## Encender y apagar

| Qué | Cómo |
|---|---|
| La puerta Telegram | `DEMO_TELEGRAM_TOKEN`, `DEMO_TELEGRAM_WEBHOOK_SECRET` en `.env` del servidor (vacíos = apagada) y reiniciar `web`/`worker` |
| La puerta WhatsApp | `DEMO_WHATSAPP_PHONE_NUMBER_ID`, `_WABA_ID`, `_APP_SECRET`, `_ACCESS_TOKEN`, `_VERIFY_TOKEN` en `.env` del servidor (los cinco, o apagada) y reiniciar |
| Un negocio de demo | `status: active` o `paused` en su `tenant.yaml` y desplegar |
| Quién entra en Telegram | `DEMO_TELEGRAM_USERS` (ids de Telegram separados por comas) y reiniciar |
| Quién entra en WhatsApp | `DEMO_WHATSAPP_USERS` (teléfonos con prefijo de país o BSUID, separados por comas) y reiniciar |
| Demo local (solo Telegram) | `make demo-up` / `make demo-down`, con un bot de Telegram de desarrollo propio |

## Alta de la puerta WhatsApp

Checklist igual al de un negocio real (`alta-baja-negocio.md`), pero sobre el número
de demo de la plataforma, no de ningún cliente:

1. Business Portfolio, app y número de la plataforma (no el de ningún cliente).
2. System User con token permanente (`whatsapp_business_messaging`,
   `whatsapp_business_management`).
3. Plantillas `confirmacion_cita` y `recordatorio_cita` (las del pack `salon`) creadas
   y aprobadas en el número de demo.
4. Webhook de la app: `https://api.<dominio>/webhooks/whatsapp-demo`, con
   `DEMO_WHATSAPP_VERIFY_TOKEN` como `verify_token` de la suscripción.
5. Variables `DEMO_WHATSAPP_*` en el `.env` del servidor; reiniciar `web`/`worker`.
6. Cambio de infraestructura (ruta nueva en `Caddyfile` y verificación de firma del
   webhook): requiere aprobación humana explícita antes de desplegar, como cualquier
   cambio de este tipo.

## Puerta Telegram en el servidor

`docker compose -p flowpilot -f compose.prod.yaml exec web python manage.py
telegram_set_webhook demo` registra `https://api.<dominio>/webhooks/telegram-demo` con
`DEMO_TELEGRAM_WEBHOOK_SECRET`. En local, sin webhook, `make demo-up` mantiene el
poller (`telegram_poll`) en segundo plano.

## Añadir o quitar personas

Edita `DEMO_TELEGRAM_USERS`/`DEMO_WHATSAPP_USERS` en el `.env` del servidor y reinicia
`web` y `worker`. No hace falta tocar `tenants/` ni desplegar código.

## Renovación anual del calendario de `demo-autobuses`

El dataset de `demo-autobuses` declara una `vigencia` (ver `docs/packs/bus.md`). Cada
verano, antes de que caduque, amplía su rango junto con el nuevo curso escolar: edita
`tenants/demo-autobuses/datasets/timetable/calendario.yaml`, pasa `make bus-formatear`
y `make bus-validar TENANT=demo-autobuses`, y haz commit. Este dataset no se publica
con `make bus-publicar` (no hay empresa real que revise el PDF).

## Diagnóstico

Ver también `docs/runbooks/02-negocio-o-canal.md` (una puerta o negocio de demo no
responde), `docs/runbooks/04-calendar.md` (el calendario de `demo-peluqueria` sin
acceso) y `docs/runbooks/09-rotar-secretos.md` (rotar un secreto de cualquiera de las
dos puertas).
