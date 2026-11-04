# Puesta en marcha: pasos pendientes

La plataforma está implementada y probada con simulaciones, pero ninguna parte se ha
probado aún contra servicios reales. Estos son los pasos manuales que faltan, en el
orden en que se desbloquean. Ningún agente los da por hechos ni inventa credenciales,
ids o aprobaciones.

## 1. Desarrollo local con servicios reales

- **Bot de demo de desarrollo (puerta Telegram):** crear un bot con @BotFather (p. ej.
  `autobot_dev_bot`), distinto del de producción, poner su token en
  `DEMO_TELEGRAM_TOKEN` y tu id de Telegram (@userinfobot) en `DEMO_TELEGRAM_USERS`
  del `.env` local; con un túnel de ngrok hacia `web` como `PUBLIC_URL` y
  `DEMO_TELEGRAM_WEBHOOK_SECRET`, se registra el webhook igual que en producción
  (`docs/runbooks/demo.md`). Verificar: `/start` muestra la lista de negocios de
  demo.
- **Google Cloud de la plataforma:** proyecto propio (no de un negocio), Google
  Calendar API habilitada y cuenta de servicio con clave JSON en `google_sa.json`
  (ignorado por git) y en el gestor de contraseñas.
- **Calendario de la demo:** un calendario («Autobot demo»), compartido con la
  cuenta de servicio, como `calendar_id` de la plantilla `src/packs/salon/template/document.yaml`; después,
  `status: active`. Verificar: una reserva desde cualquiera de las dos puertas de la
  demo aparece una sola vez en ese calendario.
- **Bot de avisos y chat de ops:** bot con @BotFather (`NOTIFY_BOT_TOKEN`) y un grupo
  de ops con él (`OPS_TELEGRAM_CHAT_ID`). Verificar: una alerta forzada llega al chat.
- **Sentry y healthchecks.io:** proyecto de Sentry (`SENTRY_DSN`) y dos checks:
  «worker» (periodo 5 min, gracia 10 min, `HEALTHCHECKS_PING_URL`) y «backup»
  (periodo 6 h, gracia 1 h).

Con esto se pueden validar a mano los packs `bus` y `salon` por la puerta Telegram de
la demo.

## 2. Servidor

- **Dominio y VPS:** VPS en la UE (2 vCPU / 4 GB, Ubuntu 24.04) con tu clave SSH y el
  DNS `api.<dominio>` apuntando a ella.
- **Preparación:** `deploy/bootstrap-server.sh` siguiendo `docs/runbooks/servidor.md`.
- **Backups:** bucket en un proveedor distinto del de la VPS (Backblaze B2 o
  Cloudflare R2) con clave limitada a ese bucket, y contraseña de restic; los tres en
  el gestor de contraseñas. Verificar: `restic snapshots` lista el primer backup.
- **Secretos de despliegue:** en la VPS, `/srv/autobot/.env` (con `PUBLIC_HOST` y
  `DJANGO_ALLOWED_HOSTS`, que incluye `127.0.0.1` y `localhost`), `google_sa.json`,
  `backup.env` y la contraseña de restic como `deploy` con modo 0600, `DEPLOY_UID`,
  deploy key de GitHub de solo lectura y acceso de lectura a GHCR. Las contraseñas,
  claves y `DB_*_URL` internas las genera `make deploy` la primera vez
  (`deploy/ensure-env.sh`, DESIGN §12): no hace falta rellenarlas a mano ni inventarlas.
  En GitHub, entorno `production` con aprobación requerida y secretos `DEPLOY_HOST`,
  `DEPLOY_SSH_KEY` y `DEPLOY_KNOWN_HOSTS`.
- **Bot de demo de producción (puerta Telegram):** distinto del de desarrollo, con su
  token y un `DEMO_TELEGRAM_WEBHOOK_SECRET` aleatorio en el `.env` del servidor; tras
  el primer despliegue, `manage.py telegram_set_webhook demo`.
- **Demo por WhatsApp:** número de la plataforma (no de ningún cliente) con Business
  Portfolio, app, token permanente, plantillas `confirmacion_cita` y
  `recordatorio_cita` aprobadas (las del pack `salon`) y webhook a
  `https://api.<dominio>/webhooks/whatsapp-demo` con `DEMO_WHATSAPP_VERIFY_TOKEN`
  (checklist completo en `docs/runbooks/demo.md`). Variables `DEMO_WHATSAPP_*` en el
  `.env` del servidor. El cambio de `Caddyfile` y la verificación de firma del webhook
  necesitan aprobación humana explícita antes de desplegarse.
- **Bot de avisos como asistente del dueño** (ADR-007):
  generar `NOTIFY_BOT_WEBHOOK_SECRET` (32+ caracteres aleatorios) y poner
  `OWNER_SUPPORT_EMAIL` en el `.env` del servidor; tras el despliegue,
  `manage.py telegram_set_webhook notify`. Por cada negocio con dueño,
  `manage.py owner_invite <slug>` y enviarle el enlace. Contrastar `PRICE_EUR`
  (`autobot/runtime/summary.py`) con el rate card del WhatsApp Manager de un negocio
  real y anotar la fecha en `docs/runbooks/alta-baja-negocio.md`. Pedir a cada
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
- Migrar las citas antiguas: `tools/migrate_salon_events.py dm-barber --dry-run`,
  revisar el informe y ejecutar la migración real; comprobar después que «Cancelar
  cita» de un cliente existente lista sus citas. La migración solo añade
  propiedades privadas a los eventos y no hace falta deshacerla.
- Prueba con el dueño por su canal real, en `onboarding` con su id en `testers.main`
  (no hay bot de pruebas aparte: la demo de la plataforma nunca habla con un negocio
  real). En hora valle, cambiar el webhook de Meta a
  `https://api.<dominio>/webhooks/whatsapp/<public_id>`, poner `status: active` y
  desplegar. Parar el servicio de la VM de GCP y conservarla una semana; para volver
  atrás basta con restaurar la URL antigua.

### Autocares San Sebastián (`bus`, WhatsApp)

- Ids de Telegram o teléfonos de la empresa en `testers.main`, SIM sin WhatsApp y
  verificación de empresa en su Business Portfolio.
- La empresa revisa el bot en `onboarding` por su canal real y confirma el PDF de
  `make bus-revision`.
- Alta de WhatsApp con el checklist de `docs/runbooks/alta-baja-negocio.md`, ids de
  Meta en el documento de importación y secretos cifrados en la BD. Importar primero
  en local, transferir con `make tenant-push HOST=<servidor> SLUG=<slug> SECRETS=<yaml>`
  y comprobar la activación cuando el panel esté disponible.

### Comprobación final

Antes de activar cada negocio, recorrer en producción todo lo que ofrece su pack
(`docs/packs/`): en `salon`, también un recordatorio real y la confirmación de una
cita manual. Tras una semana sin alertas 🔴 abiertas, borrar la VM de GCP (servicio,
nginx, DuckDNS) y archivar los repositorios de los bots anteriores.

Activar un canal real, cambiar un webhook y tocar datos de producción necesitan
aprobación humana explícita.

`SECRETS_ENCRYPTION_KEY` la genera `make deploy` la primera vez si falta
(`deploy/ensure-env.sh`); conserva una copia cifrada de `.env` con los backups —
sin ella no se pueden descifrar los secretos de canal ya guardados. La clave local
solo sirve en desarrollo; procedimiento de rotación en
[rotar secretos](runbooks/09-rotar-secretos.md).

### Configuración del primer despliegue del panel

La persona importa la copia local de cada negocio con `tenant_config import <dir>
--secrets <yaml>`; el nombre antiguo `tenant.yaml` se admite solo como entrada. Las
plantillas de demo se siembran con `seed_demos`. Los comandos de producción pasan por
`make prod-manage HOST=<servidor> CMD="..."`; para transferir la configuración local se
usa `make tenant-push HOST=<servidor> SLUG=<slug> SECRETS=<yaml>`. El tar de entrada puede
llevar un `secrets.yaml` temporal con solo ese slug; los exports ordinarios no lo incluyen.
Al comprobar el resultado, retirar las copias locales de importación o guardarlas
cifradas fuera del repositorio. La lista completa del panel se termina en T33.

Tras el primer despliegue, crea el usuario del panel con `make prod-manage TTY=1
CMD="panel_user create <usuario>"` y guarda el QR del TOTP al momento (solo se muestra
una vez; `docs/runbooks/panel.md`). Comprueba `DJANGO_ALLOWED_HOSTS` en el `.env` del
servidor: debe incluir `127.0.0.1` y `localhost`, porque el panel llega con ese host al
entrar por el túnel SSH.
