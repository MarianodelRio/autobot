# Checklist de lanzamiento

Lista priorizada de lo que debe estar resuelto antes de atender datos de un **primer cliente real**. Léela antes de activar el canal real de cualquier negocio. Cada casilla remite a la página donde se explica; marca la casilla solo cuando exista la evidencia (documento firmado, comando verificado), nunca por suposición.

!!! warning "No es asesoramiento jurídico"
    Lista de trabajo. Los puntos legales deben revisarse con abogado. Activar el canal real de un negocio y activar la limpieza requieren aprobación humana explícita (`CLAUDE.md`).

## Bloqueantes (sin esto no se activa un cliente real)

### A. Ajustes técnicos y operativos

- [x] **Limpieza de retención activada en producción** (`RETENTION_CLEANUP_ENABLED=true` por defecto en `compose.prod.yaml`, aprobado el 2026-11-23); comprobar tras el primer despliegue un ciclo nocturno (`retention_cleanup`, 03:00 UTC). En local sigue `false` ([Retención y RGPD](../procedimientos/retencion-rgpd.md#limpieza-automatica)).
- [ ] Elegir el **proveedor VPS** en la UE y firmar su DPA ([subencargados](subencargados.md)).
- [ ] Elegir el **almacenamiento de backups** (otro proveedor, UE) y firmar su DPA; ejecutar un simulacro de restauración ([Restaurar](../procedimientos/restaurar.md)).
- [x] Procedimiento para **reaplicar las supresiones** tras restaurar un backup: libro de supresiones, `privacy_ledger_export` y `privacy_reapply` (ADR-019, [Restaurar](../procedimientos/restaurar.md)).
- [x] El libro de supresiones sale del servidor solo: `backup.sh` lo sube cada hora a restic y `restore.sh` lo reaplica (ADR-025). Comprobar tras el primer backup real que existe un snapshot `autobot-ledger`.
- [ ] **`HEALTHCHECKS_PING_URL` configurada y el check de backups de Healthchecks** (`HEALTHCHECKS_BACKUP_PING_URL` en `var/backup.env`, periodo 1 h, gracia 90 min) **dados de alta con aviso a una persona**: son obligatorios; sin ellos nadie se entera de un worker colgado ni de que los backups pararon ([Backups](../procedimientos/backups.md)).
- [ ] **Simulacro real de restauración desde el bucket S3** (no solo `make restore-test`): restaurar el último snapshot en una VPS desechable con la clave de secretos guardada aparte, comprobar los datos y el libro de supresiones, y anotar el RTO medido ([Restaurar](../procedimientos/restaurar.md), [RPO y RTO](../procedimientos/backups.md#rpo-y-rto)).
- [ ] **Vigilante del host activo** (`autobot-watchdog.timer`): con `NOTIFY_BOT_TOKEN` y `OPS_TELEGRAM_CHAT_ID` en `.env` y un aviso de prueba recibido ([Despliegue](../procedimientos/despliegue.md#vigilante-del-host-watchdogsh)).
- [ ] Confirmar la ubicación y política de Healthchecks.io, y decidir si se usa Sentry (con su DPA).
- [x] **Primera capa de información** en el primer mensaje del bot: una línea con el aviso de asistente automático y el enlace a la política ([información](informacion-al-interesado.md), [ADR-028](../arquitectura/adr/ADR-028-aviso-en-una-linea-sin-persona-ni-baja.md)).
- [ ] Rellenar `privacy.policy_url` en cada negocio (la activación del canal real lo exige; los negocios ya activos deben completarlo).
- [ ] Decidir cómo se da de baja un cliente de los recordatorios antes de activarlos en un negocio real (no hay orden `BAJA` desde el [ADR-028](../arquitectura/adr/ADR-028-aviso-en-una-linea-sin-persona-ni-baja.md)).
- [x] Pack `bus`: **aviso de horarios orientativos** (`schedule_disclaimer`, configurable) ([otras normas](otras-normas.md#10-pack-bus)).
- [ ] Opt-in documentado para recordatorios de WhatsApp y plantillas aprobadas, si se activan (`reminders_enabled`).

### B. Documentos y decisiones

- [ ] **Revisión por abogado** de: contrato de encargado, políticas de privacidad, roles, evaluación de riesgos, bases jurídicas.
- [ ] **Datos del titular** rellenados: `[TITULAR]`, `[NIF]`, `[DOMICILIO]`, `[EMAIL DE PRIVACIDAD]` en todos los textos.
- [ ] **Decisión 1:** cuenta WABA del negocio o de la plataforma ([roles](roles-y-tratamientos.md#decisiones-pendientes)).
- [ ] Decidir plazos de conservación por negocio (12 meses por defecto) y reflejarlos en el Anexo I.
- [ ] **Contrato de encargado firmado** con el negocio (con Anexo III vigente) antes de activar su canal.
- [ ] **Información al negocio** sobre Google Calendar con cuenta gratuita (sin DPA) y su aceptación por escrito ([roles](roles-y-tratamientos.md)).
- [ ] **Política de privacidad del negocio** publicada (o alojada por la plataforma) y enlazada desde el bot.
- [ ] **Política de privacidad de la plataforma** publicada y enlazada desde la demo y el bot de avisos.
- [ ] **Política en @BotFather** para cada bot de Telegram: demo, avisos y cada cliente ([información](informacion-al-interesado.md#4-telegram-politica-en-botfather)).
- [ ] **Registro de actividades** completado con los datos del titular y entregada su parte de encargado al negocio ([registro](registro-de-actividades.md)).
- [ ] Contacto de guardia del negocio para brechas (Anexo I) y del equipo para avisar en 48 h ([brechas](brechas-de-seguridad.md)).
- [ ] Revisión de `bus` con abogado antes de su primer cliente (Ley 10/2025, administración pública) ([otras normas](otras-normas.md)).

## Importante antes del primer mes

- [ ] Aviso legal y web de la plataforma ([LSSI](otras-normas.md#1-comercio-electronico-y-comunicaciones-comerciales)).
- [ ] Software de facturación conforme a VeriFactu (1-01-2027 sociedades, 1-07-2027 resto).
- [ ] Condiciones del servicio que recojan el cambio de proveedor del Reglamento de Datos (preaviso ≤ 2 meses, exportación, sin tasas desde el 12-01-2027).
- [ ] Revisar la política de uso de datos de la API de Google y si hace falta verificación OAuth.
- [ ] Probar el procedimiento de derechos con un contacto de prueba en local ([derechos](derechos-de-los-interesados.md)).
- [ ] Simulacro de brecha (tabla de reloj de 72 h y plantillas) ([brechas](brechas-de-seguridad.md)).

## Revisión periódica

- [ ] Revisar registro, subencargados y evaluación de riesgos cada 12 meses o ante cambios.
- [ ] Seguir el recurso C-703/25 P sobre el DPF y activar el plan B si procede ([subencargados](subencargados.md)).
- [ ] Reevaluar EIPD y DPD si hay IA, datos de salud o crecimiento ([evaluación](evaluacion-de-riesgos.md)).
- [ ] Ley 10/2025: revisar antes del 28-12-2026.

## Relacionado

[Roles y tratamientos](roles-y-tratamientos.md), [Servidor](../procedimientos/servidor.md), [Alta y baja de un negocio](../procedimientos/alta-baja-negocio.md).
