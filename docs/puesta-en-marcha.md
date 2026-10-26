# Puesta en marcha: pasos pendientes

La plataforma está implementada y probada con simulaciones, pero ninguna parte se ha
probado aún contra servicios reales. Estos son los pasos manuales que faltan, en el
orden en que se desbloquean. Ningún agente los da por hechos ni inventa credenciales,
ids o aprobaciones.

## 1. Desarrollo local con servicios reales

- **Bot de pruebas de desarrollo:** crear un bot con @BotFather (p. ej.
  `flowpilot_dev_bot`), poner su token en `TEST_BOT_TOKEN` y tu id de Telegram
  (@userinfobot) en `TEST_BOT_OPERATORS` del `.env` local. Verificar: `make
  telegram-poll` arranca y `/start` muestra la lista de negocios.
- **Google Cloud de la plataforma:** proyecto propio (no de un negocio), Google
  Calendar API habilitada y cuenta de servicio con clave JSON en `google_sa.json`
  (ignorado por git) y en el gestor de contraseñas.
- **Calendarios de desarrollo:** dos calendarios, «FlowPilot dev (real)» y «FlowPilot
  dev (pruebas)», compartidos con la cuenta de servicio, como `calendar_id` y
  `test_calendar_id` de un tenant `tenants/dev-salon/` en `onboarding`. Verificar: una
  reserva desde el bot de pruebas aparece solo en el de pruebas.
- **Bot de avisos y chat de ops:** bot con @BotFather (`NOTIFY_BOT_TOKEN`) y un grupo
  de ops con él (`OPS_TELEGRAM_CHAT_ID`). Verificar: una alerta forzada llega al chat.
- **Sentry y healthchecks.io:** proyecto de Sentry (`SENTRY_DSN`) y dos checks:
  «worker» (periodo 5 min, gracia 10 min, `HEALTHCHECKS_PING_URL`) y «backup»
  (periodo 6 h, gracia 1 h).

Con esto se pueden validar a mano los packs `bus` y `salon` por el bot de pruebas.

## 2. Servidor

- **Dominio y VPS:** VPS en la UE (2 vCPU / 4 GB, Ubuntu 24.04) con tu clave SSH y el
  DNS `api.<dominio>` apuntando a ella.
- **Preparación:** `deploy/bootstrap-server.sh` siguiendo `docs/runbooks/servidor.md`.
- **Backups:** bucket en un proveedor distinto del de la VPS (Backblaze B2 o
  Cloudflare R2) con clave limitada a ese bucket, y contraseña de restic; los tres en
  el gestor de contraseñas. Verificar: `restic snapshots` lista el primer backup.
- **Secretos de despliegue:** en la VPS, `/srv/flowpilot/.env`, `secrets.yaml`,
  `google_sa.json`, `backup.env` y la contraseña de restic como `deploy` con modo
  0600, `DEPLOY_UID`, deploy key de GitHub de solo lectura y acceso de lectura a GHCR.
  En GitHub, entorno `production` con aprobación requerida y secretos `DEPLOY_HOST`,
  `DEPLOY_SSH_KEY` y `DEPLOY_KNOWN_HOSTS`.
- **Bot de pruebas de producción:** distinto del de desarrollo, con su token y un
  `TEST_BOT_WEBHOOK_SECRET` aleatorio en el `.env` del servidor; tras el primer
  despliegue, `manage.py telegram_set_webhook test`.
- **Primer despliegue** con `make deploy SHA=<sha>`, prueba de vuelta atrás con un SHA
  roto a propósito y simulacro de restauración en una VPS temporal (objetivo: menos
  de 2 h). Requiere aprobación humana.
- **Uptime externo:** monitor de `https://api.<dominio>/health` cada 5 min, con aviso
  de caducidad del certificado.

Verificación del servidor:

- [ ] `/health` responde 200 con certificado válido; `/admin/` da 404 desde fuera y
      funciona con `make admin-tunnel`.
- [ ] Consulta completa de Autocares y reserva de `dev-salon` (calendario de pruebas)
      por el bot de pruebas de producción.
- [ ] Un backup automático aparece en restic y el check «backup» está verde.
- [ ] Simulacro de restauración hecho y anotado.
- [ ] Parar el worker dispara la alerta de healthchecks.io; arrancarlo la recupera.

## 3. Negocios

### DM Barber Shop (`salon`, WhatsApp)

- Crear `tenants/dm-barber/tenant.yaml` con la config actual del
  bot anterior (horario, servicios, ventana, evento especial e
  interruptores de envío con sus valores actuales), canal WhatsApp de la app
  existente en `onboarding` y `manual_confirmations_since` igual a la fecha de arranque.
- El negocio comparte su calendario real; tú creas y compartes el de pruebas.
- Secretos de la app de Meta existente en `secrets.yaml` y plantillas
  `confirmacion_cita` y `recordatorio_cita` aprobadas. Verificar: `tenant_health
  dm-barber` en verde.
- Migrar las citas antiguas: `tools/migrate_salon_events.py dm-barber --dry-run`,
  revisar el informe y ejecutar la migración real; comprobar después que «Ver mis
  citas» de un cliente existente muestra sus citas. La migración solo añade
  propiedades privadas a los eventos y no hace falta deshacerla.
- Prueba con el dueño desde el bot de pruebas. En hora valle, cambiar el webhook de
  Meta a `https://api.<dominio>/webhooks/whatsapp/<public_id>`, probar con un
  `testers.main`, poner `status: active` y desplegar. Parar el servicio de la VM de
  GCP y conservarla una semana; para volver atrás basta con restaurar la URL antigua.

### Autocares San Sebastián (`bus`, WhatsApp)

- Ids de Telegram de la empresa en `testers.telegram`, SIM sin WhatsApp y
  verificación de empresa en su Business Portfolio.
- La empresa revisa el bot por el bot de pruebas y confirma el PDF de `make bus-revision`.
- Alta de WhatsApp con el checklist de `docs/runbooks/alta-baja-negocio.md`, ids de
  Meta en `tenant.yaml`, secretos, `status: active` y despliegue.

### Comprobación final

Antes de activar cada negocio, recorrer en producción todo lo que ofrece su pack
(`docs/packs/`): en `salon`, también un recordatorio real y la confirmación de una
cita manual. Tras una semana sin alertas 🔴 abiertas, borrar la VM de GCP (servicio,
nginx, DuckDNS) y archivar los repositorios de los bots anteriores.

Activar un canal real, cambiar un webhook y tocar datos de producción necesitan
aprobación humana explícita.
