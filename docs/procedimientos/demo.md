# Bot de demo en el servidor

Operación del bot de demo en producción: encender o apagar sus dos puertas (Telegram y
WhatsApp), dar acceso a personas y renovar el calendario de `demo-autobuses`. La plataforma,
no ningún cliente, enseña Autobot con un bot de Telegram y un número de WhatsApp, y con
negocios de demostración normales (`demo-peluqueria`, `demo-autobuses`) sembrados desde las
plantillas de cada pack. Cómo funciona por dentro: [../arquitectura/bot-de-demo.md](../arquitectura/bot-de-demo.md)
(ADR-006). La demo en local (ngrok, bot propio de desarrollo) está en
[../desarrollo/demo-local.md](../desarrollo/demo-local.md).

La primera respuesta de cualquier puerta pide elegir negocio; desde ahí la conversación es la
del pack real de ese negocio. La persona puede cambiar de negocio escribiendo `/negocio`
(también `/start` o `negocio`), que vuelve a mostrar la lista. Solo entra una lista cerrada
de personas o quien canjee un código de invitación vigente.

## Objetivo, cuándo y requisitos

- **Objetivo:** tener las puertas de demo encendidas con los accesos correctos.
- **Cuándo:** montar la demo por primera vez, dar o quitar acceso a alguien, rotar un token,
  o renovar el calendario anual.
- **Requisitos:** SSH como `deploy` a la VPS; los valores de `DEMO_*` (ver
  [../referencia/variables-entorno.md](../referencia/variables-entorno.md)); un bot de
  Telegram y, para WhatsApp, un número y una app de Meta de la plataforma.
- **Aprobaciones:** la puerta WhatsApp añade una ruta y verificación de firma de webhook:
  cambio de infraestructura que requiere aprobación humana explícita. Activar un canal real
  también.

## Encender y apagar

Las variables van en el `.env` del servidor (como `deploy`, en `/srv/autobot`). Para que
las lean `web` y los workers, recréalos
([despliegue.md](despliegue.md#cambiar-env-sin-desplegar)):

```bash
# en la VPS, como deploy, en /srv/autobot
deploy/scripts/compose.sh up -d --no-deps web worker-inbound worker-calendar worker-periodic worker-outbound
```

| Qué | Cómo |
|---|---|
| Puerta Telegram | `DEMO_TELEGRAM_TOKEN` y `DEMO_TELEGRAM_WEBHOOK_SECRET` (vacíos = apagada); recrear, y registrar el webhook (abajo) |
| Puerta WhatsApp | `DEMO_WHATSAPP_PHONE_NUMBER_ID`, `_WABA_ID`, `_APP_SECRET`, `_ACCESS_TOKEN` y `_VERIFY_TOKEN` (los cinco, o apagada); recrear |
| Un negocio de demo | `make prod-manage CMD="tenant_status <slug> pause"` o `resume` |
| Quién entra en Telegram | `DEMO_TELEGRAM_USERS` (ids de Telegram, separados por comas); recrear |
| Quién entra en WhatsApp | `DEMO_WHATSAPP_USERS` (teléfonos con prefijo de país o BSUID, separados por comas); recrear |
| Enlace del bot con QR en el panel | `DEMO_TELEGRAM_BOT_USERNAME` |

## Alta de la puerta WhatsApp

Checklist igual al de un negocio real ([alta-baja-negocio.md](alta-baja-negocio.md)), pero
sobre el número de demo de la plataforma:

1. Business Portfolio, app y número de la plataforma (no el de ningún cliente).
2. System User con token permanente (`whatsapp_business_messaging`,
   `whatsapp_business_management`).
3. Plantillas `confirmacion_cita` y `recordatorio_cita` (las del pack `salon`) creadas y
   aprobadas en el número de demo.
4. Webhook de la app: `https://api.<dominio>/webhooks/whatsapp-demo`, con
   `DEMO_WHATSAPP_VERIFY_TOKEN` como `verify_token` de la suscripción.
5. Variables `DEMO_WHATSAPP_*` en el `.env` del servidor y recrear `web` y los workers (arriba).
6. Aprobación humana explícita antes de desplegar cualquier cambio de ruta o de firma.

## Puerta Telegram en el servidor

Con `DEMO_TELEGRAM_*` ya en `.env` y los contenedores recreados, desde el portátil:

```bash
make prod-manage CMD="telegram_set_webhook demo"
```

Registra `https://api.<dominio>/webhooks/telegram-demo` con `DEMO_TELEGRAM_WEBHOOK_SECRET`.
`telegram_set_webhook demo --delete` lo retira.

## Puertas en local

Para probar con un bot de desarrollo propio y un túnel de ngrok, sigue
[../desarrollo/demo-local.md](../desarrollo/demo-local.md). Nunca uses en local los tokens
de producción.

## Añadir o quitar personas

**Por invitación (preferido):** en el panel, pantalla Demo, «Crear invitación» (nota, usos y
caducidad). La persona entra con `/start <código>` en Telegram (el panel da el enlace
`t.me/<bot>?start=<código>` y su QR si `DEMO_TELEGRAM_BOT_USERNAME` está configurada; sin
ella, solo el código) o enviando el código tal cual por WhatsApp. No hace falta tocar el
`.env` ni reiniciar nada. Los códigos tienen 12 caracteres (los de menos de 10 no se
canjean) y quien falla 5 canjes en una hora no puede canjear más hasta que pase (memoria del
proceso; reiniciar `web` o `worker-inbound` lo borra). Revocar un código impide canjearlo de
nuevo, pero no retira el acceso ya concedido; para eso, edita la lista cerrada.

**Por lista cerrada:** edita `DEMO_TELEGRAM_USERS` o `DEMO_WHATSAPP_USERS` en el `.env` del
servidor y recrea `web` y los workers.

## Renovación anual del calendario de `demo-autobuses`

El dataset de `demo-autobuses` declara una `vigencia` (formato en
[../referencia/packs/bus.md](../referencia/packs/bus.md)) y es la entrada `demo` de la
biblioteca (ADR-013; `seed_demos` la sube la primera vez). Cada verano, antes de que caduque,
desde el portátil:

1. `make bus-bajar NOMBRE=demo PROD=1`.
2. Edita `var/datos/demo/timetable/calendario.yaml`.
3. `make bus-formatear NOMBRE=demo`, `make bus-validar NOMBRE=demo` y
   `make bus-revision NOMBRE=demo`.
4. `make bus-subir NOMBRE=demo COMMENT="Renovación anual de demo" PROD=1`.
5. Aplica la versión nueva en el panel: ficha de `demo-autobuses`, Configuración, Horarios,
   «Aplicar» (y en cualquier otro cliente que use la misma entrada). Es un dataset ficticio:
   no hay empresa que apruebe el PDF.
6. Actualiza también `apps/backend/src/packs/bus/template/datasets/timetable/calendario.yaml`
   para los demos futuros, ejecuta `make check` y haz commit. `seed_demos` conserva las
   versiones de los demos ya existentes.

## Verificación

- Un mensaje desde una persona autorizada recibe la lista de negocios; `/negocio` vuelve a
  mostrarla.
- `make prod-manage CMD="telegram_set_webhook demo"` termina sin error y el panel (Sistema,
  Estado) muestra la integración de demo encendida.
- Una invitación nueva se canjea una vez y deja de funcionar al agotarse.

## Relacionado

[../incidencias/negocio-o-canal.md](../incidencias/negocio-o-canal.md) (una puerta o negocio
de demo no responde), [../incidencias/calendar.md](../incidencias/calendar.md) (calendario de
`demo-peluqueria` sin acceso), [rotar-secretos.md](rotar-secretos.md).
