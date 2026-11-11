# Bot de demo en local

Con un bot de Telegram de desarrollo propio, distinto del de producción, y (si procede)
una app de WhatsApp de desarrollo, ambos por un túnel de [ngrok](https://ngrok.com)
hacia `web` (mismo mecanismo que producción: webhook, no polling). Procedimiento
completo, incluida la puerta WhatsApp, en [procedimientos/demo.md](../procedimientos/demo.md).

## Puerta Telegram

```bash
make ngrok                                                  # dominio reservado
# en .env: PUBLIC_URL=<esa URL>, DEMO_TELEGRAM_TOKEN, DEMO_TELEGRAM_USERS,
# DEMO_TELEGRAM_WEBHOOK_SECRET (p. ej. `openssl rand -hex 32`)
make up && docker compose restart web worker-inbound worker-outbound
docker compose exec web python manage.py telegram_set_webhook demo
```

En Telegram, escribe `/start` al bot: muestra los negocios de demo disponibles
(`demo-autobuses`, siempre; `demo-peluqueria` solo si está `active`).

Para un bot sin webhook (p. ej. grabar fixtures de un negocio real antes de darlo de
alta), `make telegram-poll SLUG=<slug>` sigue disponible; un bot con webhook no
admite polling a la vez (`docker compose exec web python manage.py
telegram_set_webhook demo --delete` se lo quita, nunca a un bot que use el servidor).

## Puerta WhatsApp

Necesita además una app de WhatsApp de desarrollo con su propio webhook apuntando al
túnel de ngrok (`<URL de ngrok>/webhooks/whatsapp-demo`) y las cinco variables
`DEMO_WHATSAPP_*` en `.env`. Pasos completos en
[procedimientos/demo.md](../procedimientos/demo.md#puerta-whatsapp-en-local-ngrok).
