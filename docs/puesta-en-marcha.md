# Puesta en marcha: pasos pendientes

La plataforma está implementada y probada con simulaciones, pero ninguna parte se ha
probado aún contra servicios reales. Estos son los pasos manuales que faltan, en el
orden en que se desbloquean. Ningún agente los da por hechos ni inventa credenciales,
ids o aprobaciones.

## 1. Desarrollo local con servicios reales

- [x] **Bot de demo de desarrollo, puertas Telegram y WhatsApp:** bot de @BotFather
  distinto del de producción, con un túnel de ngrok hacia `web` como `PUBLIC_URL`, y
  una app de WhatsApp de desarrollo con su webhook (`docs/procedimientos/demo.md`).
  Validado: `/start` y el equivalente por WhatsApp muestran la lista de negocios de
  demo.
- [x] **Google Cloud de la plataforma y calendario de la demo:** proyecto propio (no
  de un negocio), Google Calendar API habilitada, cuenta de servicio con clave JSON
  en `var/google_sa.json`, y un calendario («Autobot demo») compartido con la cuenta de
  servicio como `calendar_id` de la plantilla de `salon`. Validado: una reserva desde
  cualquiera de las dos puertas de la demo aparece una sola vez en ese calendario.
- [x] **Bot de avisos y chat de ops:** bot con @BotFather (`NOTIFY_BOT_TOKEN`) y un
  grupo de ops con él (`OPS_TELEGRAM_CHAT_ID`). Validado: una alerta forzada llega al
  chat.
- [x] **Panel:** usuario con contraseña y TOTP, `make panel-tunnel` y recorrido de
  las pantallas con datos locales.
- [ ] **Sentry y healthchecks.io:** proyecto de Sentry (`SENTRY_DSN`) y dos checks:
  «worker» (periodo 5 min, gracia 10 min, `HEALTHCHECKS_PING_URL`) y «backup»
  (periodo 6 h, gracia 1 h). Pendiente.

Con esto se pueden validar a mano los packs `bus` y `salon` por las dos puertas de
la demo.

## 2. Servidor

- **Dominio y VPS:** VPS en la UE (2 vCPU / 4 GB, Ubuntu 24.04) con tu clave SSH y el
  DNS `api.<dominio>` apuntando a ella.
- **Preparación:** `deploy/scripts/bootstrap-server.sh` siguiendo `docs/procedimientos/servidor.md`.
- **Backups:** bucket en un proveedor distinto del de la VPS (Backblaze B2 o
  Cloudflare R2) con clave limitada a ese bucket, y contraseña de restic; los tres en
  el gestor de contraseñas. Verificar: `restic snapshots` lista el primer backup.
- **Secretos de despliegue:** en la VPS, `/srv/autobot/.env` (con `PUBLIC_HOST` y
  `DJANGO_ALLOWED_HOSTS`, que incluye `127.0.0.1` y `localhost`), `var/google_sa.json`,
  `var/backup.env` y la contraseña de restic como `deploy` con modo 0600, `DEPLOY_UID`,
  deploy key de GitHub de solo lectura y acceso de lectura a GHCR. Las contraseñas,
  claves y `DB_*_URL` internas las genera `make deploy` la primera vez
  (`deploy/scripts/ensure-env.sh`): no hace falta rellenarlas a mano ni inventarlas.
  En GitHub, entorno `production` con aprobación requerida y secretos `DEPLOY_HOST`,
  `DEPLOY_SSH_KEY` y `DEPLOY_KNOWN_HOSTS`.
- **Bot de demo de producción (puerta Telegram):** distinto del de desarrollo, con su
  token y un `DEMO_TELEGRAM_WEBHOOK_SECRET` aleatorio en el `.env` del servidor; tras
  el primer despliegue, `manage.py telegram_set_webhook demo`.
- **Demo por WhatsApp:** número de la plataforma (no de ningún cliente) con Business
  Portfolio, app, token permanente, plantillas `confirmacion_cita` y
  `recordatorio_cita` aprobadas (las del pack `salon`) y webhook a
  `https://api.<dominio>/webhooks/whatsapp-demo` con `DEMO_WHATSAPP_VERIFY_TOKEN`
  (checklist completo en `docs/procedimientos/demo.md`). Variables `DEMO_WHATSAPP_*` en el
  `.env` del servidor. El cambio de `Caddyfile` y la verificación de firma del webhook
  necesitan aprobación humana explícita antes de desplegarse.
- **Bot de avisos como asistente del dueño** (ADR-007):
  generar `NOTIFY_BOT_WEBHOOK_SECRET` (32+ caracteres aleatorios) y poner
  `OWNER_SUPPORT_EMAIL` en el `.env` del servidor; tras el despliegue,
  `manage.py telegram_set_webhook notify`. Por cada negocio con dueño,
  `manage.py owner_invite <slug>` y enviarle el enlace. Contrastar `PRICE_EUR`
  (`apps/backend/src/autobot/runtime/costs.py`) con el rate card del WhatsApp Manager de un negocio
  real y anotar la fecha en `docs/procedimientos/alta-baja-negocio.md`. Pedir a cada
  peluquero que titule sus citas manuales como las del bot
  (`"<Servicio> - <Nombre>"`), para que el resumen las cuente.
- **Primer despliegue** con `make deploy SHA=<sha>`, prueba de vuelta atrás con un SHA
  roto a propósito y simulacro de restauración en una VPS temporal (objetivo: menos
  de 2 h). Requiere aprobación humana. Tras el despliegue, comparar la primera
  `system_sample` (CPU, memoria, carga) con `htop` en la misma VPS, para confirmar que
  lee los valores reales del host y no los del contenedor.
- **Uptime externo:** monitor de `https://api.<dominio>/health` cada 5 min, con aviso
  de caducidad del certificado.

Verificación del servidor:

- [ ] `/health` responde 200 con certificado válido.
- [ ] Consulta completa de `demo-autobuses` y reserva de `demo-peluqueria` por la
      puerta Telegram de la demo de producción, y lo mismo por la puerta WhatsApp una
      vez dada de alta.
- [ ] Un backup automático aparece en restic y el check «backup» está verde.
- [ ] Simulacro de restauración hecho y anotado.
- [ ] Parar el worker dispara la alerta de healthchecks.io; arrancarlo la recupera.

## 3. Negocios

### DM Barber Shop (`salon`, WhatsApp)

- Preparar un `document.yaml` de importación con la config actual del
  bot anterior (horario, servicios, ventana, evento especial e
  interruptores de envío con sus valores actuales), canal WhatsApp de la app
  existente en `onboarding` y `manual_confirmations_since` igual a la fecha de arranque.
- El negocio comparte su calendario real.
- Secretos de la app de Meta existente en un YAML privado de importación y plantillas
  `confirmacion_cita` y `recordatorio_cita` aprobadas. Verificar: `tenant_health
  dm-barber` en verde.
- Migrar las citas antiguas: `apps/backend/src/tools/salon/migrate_salon_events.py dm-barber --dry-run`,
  revisar el informe y ejecutar la migración real; comprobar después que «Cancelar
  cita» de un cliente existente lista sus citas. La migración solo añade
  propiedades privadas a los eventos y no hace falta deshacerla.
- Prueba con el dueño por su canal real, en `onboarding` con su id en `testers.main`
  (no hay bot de pruebas aparte: la demo de la plataforma nunca habla con un negocio
  real). En hora valle, cambiar el webhook de Meta a
  `https://api.<dominio>/webhooks/whatsapp/<public_id>`, y activarlo desde el panel
  («Activar»), sin desplegar. Parar el servicio de la VM de GCP y conservarla una
  semana; para volver atrás basta con restaurar la URL antigua.

### Autocares San Sebastián (`bus`, WhatsApp)

- Ids de Telegram o teléfonos de la empresa en `testers.main`, SIM sin WhatsApp y
  verificación de empresa en su Business Portfolio.
- La empresa revisa el bot en `onboarding` por su canal real y confirma el PDF de
  `make bus-revision`.
- Alta de WhatsApp con el checklist de `docs/procedimientos/alta-baja-negocio.md`, ids de
  Meta en el documento de importación y secretos cifrados en la BD. Importar primero
  en local, transferir con `make tenant-push HOST=<servidor> SLUG=<slug> SECRETS=<yaml>`
  y activarlo desde el panel («Activar»).

### Comprobación final

Antes de activar cada negocio, recorrer en producción todo lo que ofrece su pack
(`docs/referencia/packs/`): en `salon`, también un recordatorio real y la confirmación de una
cita manual. Tras una semana sin alertas 🔴 abiertas, borrar la VM de GCP (servicio,
nginx, DuckDNS) y archivar los repositorios de los bots anteriores.

Activar un canal real, cambiar un webhook y tocar datos de producción necesitan
aprobación humana explícita.

`SECRETS_ENCRYPTION_KEY` la genera `make deploy` la primera vez si falta
(`deploy/scripts/ensure-env.sh`); conserva una copia cifrada de `.env` con los backups —
sin ella no se pueden descifrar los secretos de canal ya guardados. La clave local
solo sirve en desarrollo; procedimiento de rotación en
[rotar secretos](procedimientos/rotar-secretos.md).

## 4. Panel

No hay nada desplegado todavía, así que no hay migración de datos de producción; estos
pasos se suman a los del servidor (§2) y usan `autocares-ss` (§3) como negocio de
ejemplo:

- [ ] En el `.env` del servidor, rellenar las variables **externas** (tokens, ids de
      Meta, `PUBLIC_HOST`, `DJANGO_ALLOWED_HOSTS` con `127.0.0.1,localhost`, Sentry y
      healthchecks); `ensure-env` genera las internas la primera vez que se despliega.
- [ ] `make deploy` (con la aprobación del entorno `production` en GitHub).
- [ ] En local, `make tenant-import DIR=var/tenants/autocares-ss SECRETS=var/secrets.yaml` y
      comprobar la ficha en el panel local (`make panel-dev`). Después,
      `make tenant-push SLUG=autocares-ss SECRETS=var/secrets.yaml`. El nombre antiguo
      `tenant.yaml` se admite solo como entrada al importar.
- [ ] `make prod-manage TTY=1 CMD="panel_user create <usuario>"` y guardar el QR del
      TOTP al momento: solo se muestra una vez (`docs/procedimientos/panel.md`). Comprobar
      que `DJANGO_ALLOWED_HOSTS` del servidor incluye `127.0.0.1` y `localhost`, porque
      el panel llega con ese host al entrar por el túnel SSH.
- [ ] `make panel-tunnel` y abrir `http://127.0.0.1:18000`: entrar con usuario,
      contraseña y TOTP, y recorrer Resumen, Clientes, Incidencias, Logs, Datos y
      Sistema con datos reales.
- [ ] Comprobar la CPU y la RAM del contenedor `panel` frente a `htop` en el host y
      `docker stats` (unos 20 MB de RAM).
- [ ] Una vez verificado, borrar las copias locales de `var/tenants/autocares-ss` y
      `var/secrets.yaml`, o guardarlas cifradas fuera del repositorio.
