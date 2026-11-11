# Bot de demo

**Qué es:** la plataforma, no ningún cliente, enseña Autobot con dos puertas (un bot
de Telegram y un número de WhatsApp) y negocios de demostración normales en
plantillas en `apps/backend/src/packs/<pack>/template/` (`demo-peluqueria`, `demo-autobuses`).
Los tests validan estas plantillas directamente; `manage.py seed_demos` las siembra
en PostgreSQL solo la primera vez y conserva los cambios posteriores de cada demo. La primera respuesta de
cualquier puerta pide elegir negocio; desde ahí la conversación es la del pack real de
ese negocio. Solo una lista cerrada de personas puede usar cada puerta (ver ADR-006).

## Encender y apagar

| Qué | Cómo |
|---|---|
| La puerta Telegram | `DEMO_TELEGRAM_TOKEN`, `DEMO_TELEGRAM_WEBHOOK_SECRET` en `.env` del servidor (vacíos = apagada) y reiniciar `web`, `worker-inbound` y `worker-outbound` |
| La puerta WhatsApp | `DEMO_WHATSAPP_PHONE_NUMBER_ID`, `_WABA_ID`, `_APP_SECRET`, `_ACCESS_TOKEN`, `_VERIFY_TOKEN` en `.env` del servidor (los cinco, o apagada) y reiniciar |
| Un negocio de demo | `tenant_status <slug> pause` o `resume`, sobre el demo ya sembrado en BD |
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
5. Variables `DEMO_WHATSAPP_*` en el `.env` del servidor; reiniciar `web`, `worker-inbound` y `worker-outbound`.
6. Cambio de infraestructura (ruta nueva en `Caddyfile` y verificación de firma del
   webhook): requiere aprobación humana explícita antes de desplegar, como cualquier
   cambio de este tipo.

## Puerta Telegram en el servidor

Desde `/srv/autobot`, `docker compose exec web python manage.py telegram_set_webhook
demo` registra `https://api.<dominio>/webhooks/telegram-demo` con
`DEMO_TELEGRAM_WEBHOOK_SECRET`.

## Puerta Telegram en local (ngrok)

Mismo mecanismo que el servidor (webhook), sobre un túnel de
[ngrok](https://ngrok.com) hacia `web`, en vez de una URL de dominio propio:

1. `make dev-bootstrap` prepara la BD y siembra los demos. `make ngrok` abre el túnel
   hacia el puerto 8000 con el `NGROK_DOMAIN` de `.env` (tu dominio reservado; también
   se puede pasar en la línea de comandos). Para que el demo de `salon` reserve de
   verdad, fija `DEMO_SALON_CALENDAR_ID` en `.env` antes de sembrar.
2. En `.env`: `PUBLIC_URL=<la URL https de ngrok>`, `DEMO_TELEGRAM_TOKEN` (bot de
   desarrollo propio, distinto del de producción), `DEMO_TELEGRAM_USERS` y
   `DEMO_TELEGRAM_WEBHOOK_SECRET` (aleatorio, p. ej. `openssl rand -hex 32`).
3. `docker compose restart web worker-inbound worker-outbound` y después `docker compose exec web python
   manage.py telegram_set_webhook demo`.
4. Si la URL de ngrok cambia (reinicio sin dominio reservado), repetir los pasos 2-3
   con la URL nueva.

Para un bot sin webhook (p. ej. grabar fixtures de un negocio real antes de darlo de
alta), `manage.py telegram_poll <slug>` (`make telegram-poll SLUG=<slug>`) sigue
disponible; un bot con webhook no admite polling a la vez (`telegram_set_webhook
demo --delete` se lo quita, nunca a un bot que use el servidor).

## Puerta WhatsApp en local (ngrok)

Mismo checklist que [el alta de la puerta WhatsApp](#alta-de-la-puerta-whatsapp), con
una app de WhatsApp **de desarrollo** (nunca la de producción) y la URL de ngrok en
vez del dominio propio:

1. `make ngrok` abre el túnel hacia el puerto 8000 (con `NGROK_DOMAIN` de `.env`).
2. En la app de WhatsApp de desarrollo, el webhook de la suscripción es
   `<URL de ngrok>/webhooks/whatsapp-demo`, con `DEMO_WHATSAPP_VERIFY_TOKEN` como
   `verify_token`.
3. En `.env`: `PUBLIC_URL=<la URL https de ngrok>` y las cinco `DEMO_WHATSAPP_*`
   (`_PHONE_NUMBER_ID`, `_WABA_ID`, `_APP_SECRET`, `_ACCESS_TOKEN`, `_VERIFY_TOKEN`) de
   la app de desarrollo.
4. `docker compose restart web worker-inbound worker-outbound`.
5. Si la URL de ngrok cambia, repetir los pasos 2-3 con la URL nueva.

## Añadir o quitar personas

Edita `DEMO_TELEGRAM_USERS`/`DEMO_WHATSAPP_USERS` en el `.env` del servidor y reinicia
`web`, `worker-inbound` y `worker-outbound`.

## Renovación anual del calendario de `demo-autobuses`

El dataset de `demo-autobuses` declara una `vigencia` (ver `docs/referencia/packs/bus.md`). Cada
verano, antes de que caduque, bajar con `make bus-bajar TENANT=demo-autobuses`, editar
`var/datos/demo-autobuses/timetable/calendario.yaml`, formatear, validar y revisar con los
targets `bus-*`, y publicar con `COMMENT="Renovación anual de demo"`. Para actuar sobre
el servidor, la persona añade `PROD=1` tanto al bajar como al publicar. Es un dataset
ficticio y no tiene una empresa que deba aprobar el PDF.

Actualizar también `apps/backend/src/packs/bus/template/datasets/timetable/calendario.yaml` para
los demos que se creen en el futuro, ejecutar `make check` y hacer commit de ese cambio
de plantilla. `seed_demos` conserva las versiones de los demos ya existentes.

## Diagnóstico

Ver también `docs/incidencias/negocio-o-canal.md` (una puerta o negocio de demo no
responde), `docs/incidencias/calendar.md` (el calendario de `demo-peluqueria` sin
acceso) y `docs/procedimientos/rotar-secretos.md` (rotar un secreto de cualquiera de las
dos puertas).
