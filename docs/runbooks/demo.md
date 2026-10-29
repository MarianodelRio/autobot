# Bot de demo

**Qué es:** la plataforma, no ningún cliente, enseña Autobot con dos puertas (un bot
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
| Demo local | un túnel de ngrok hacia `web` (puerto 8000) y un webhook real, con un bot de Telegram (y, si procede, una app de WhatsApp) de desarrollo propio — ver más abajo |

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

`docker compose -p autobot -f compose.prod.yaml exec web python manage.py
telegram_set_webhook demo` registra `https://api.<dominio>/webhooks/telegram-demo` con
`DEMO_TELEGRAM_WEBHOOK_SECRET`.

## Puerta Telegram en local (ngrok)

Mismo mecanismo que el servidor (webhook), sobre un túnel de
[ngrok](https://ngrok.com) hacia `web`, en vez de una URL de dominio propio:

1. `ngrok http 8000` (con cuenta gratuita, la URL cambia cada vez que se reinicia el
   túnel; con un dominio reservado de la cuenta, se mantiene).
2. En `.env`: `PUBLIC_URL=<la URL https de ngrok>`, `DEMO_TELEGRAM_TOKEN` (bot de
   desarrollo propio, distinto del de producción), `DEMO_TELEGRAM_USERS` y
   `DEMO_TELEGRAM_WEBHOOK_SECRET` (aleatorio, p. ej. `openssl rand -hex 32`).
3. `docker compose restart web worker` y después `docker compose exec web python
   manage.py telegram_set_webhook demo`.
4. Si la URL de ngrok cambia (reinicio sin dominio reservado), repetir los pasos 2-3
   con la URL nueva.

Para un bot sin webhook (p. ej. grabar fixtures de un negocio real antes de darlo de
alta), `manage.py telegram_poll <slug>` (`make telegram-poll SLUG=<slug>`) sigue
disponible; un bot con webhook no admite polling a la vez (`telegram_set_webhook
demo --delete` se lo quita, nunca a un bot que use el servidor).

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
