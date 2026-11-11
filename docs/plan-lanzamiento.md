# Plan de lanzamiento

**Objetivo:** al terminar esta lista la plataforma queda lista para producción. Desplegar
es un comando, incorporar un cliente se hace desde el panel y lo que venga después son
solo mejoras.

Basado en una revisión del código en el commit `d883764` (2026-11-09). Las referencias
`fichero:línea` son de ese commit.

**Cómo leerlo**

- Esfuerzo: **S** (menos de medio día), **M** (1–2 días), **L** (3 días o más). Son estimaciones.
- **[Aprobación]**: toca secretos, cifrado, firma de webhooks, RLS, roles, borrados o el
  servidor, y necesita tu visto bueno explícito (`CLAUDE.md`).
- **[Tú]**: lo ejecutas tú; ningún agente lo hace.

Este documento no nombra a los clientes reales. Sus datos concretos están en
`var/limpieza/`, que git ignora.

## 1. Cómo está hoy

**Lo que está bien.** Pasan los 2.100 tests del backend y los 94 del panel, y CI está en
verde. La revisión no encontró fugas entre negocios ni forma de que un contacto toque
citas ajenas. Tampoco credenciales expuestas en historial, GitHub o imágenes. La
reserva es idempotente y las dependencias no tienen vulnerabilidades relevantes.

**Lo que falta para producción:**

| Área | Situación |
|---|---|
| Despliegue | Fallaría en la primera ejecución real: `deploy.sh` no encuentra `.env` (reproducido) |
| Backups | Fallarían siempre: `backup.sh` no define `SHA` (reproducido) |
| Traslado a otra máquina | No funciona de extremo a extremo y hoy arrancaría envíos reales antes de tiempo |
| Alta desde el panel | Imposible sin terminal: la lista de lo que falta no se muestra en ninguna pantalla |
| Datos reales | Siguen en el repo, en el historial y en 47 de las 51 imágenes de `autobot` |
| Robustez | 20 errores concretos, 7 graves; varios reproducidos |

## 2. Decisiones

**Tomadas por ti:**

- El repo sigue público, sin datos de clientes reales en su versión final. El historial de
  git se queda como está.
- Los tests de `bus` usan horarios falsos pequeños, al estilo de la demo.
- El repo y su despliegue son genéricos: nada de un cliente, dominio o servidor concreto.
- Se lanza primero solo con los demos. Los clientes se crean después desde el panel, en
  producción.
- Los horarios de `bus` se suben desde tu máquina por terminal a una biblioteca, nunca
  pasan por git, y al crear un cliente se elige uno desde el panel (C19–C24).
- Terraform descartado: un script por SSH sirve en cualquier proveedor.

**Pendientes de ti.** Junto a cada una, lo que propongo:

| # | Decisión | Propuesta |
|---|---|---|
| D1 | Historial de git | **Resuelta:** no se toca |
| D2 | Tests de `bus` sin datos reales (R1) | **Resuelta:** horarios falsos pequeños |
| D3 | ¿Migrar citas de los bots anteriores? | No: borrar la herramienta |
| D4 | ¿Activar el borrado automático de datos? **[Aprobación]** | Sí, antes del primer cliente |
| D5 | ¿Cómo entran los usuarios a la demo? | Lista cerrada al principio |
| D6 | ¿Demo también por WhatsApp? | Más adelante |
| D7 | Proveedor de la VM | OVH VPS-1 tras confirmar permanencia |
| D8 | Varios peluqueros: las cinco preguntas de E | Las propuestas de E |
| D9 | ¿Quién actualiza horarios y cada cuánto? | Tú: los subes con `bus-subir` y los aplicas desde el panel |
| D10 | ¿Darte de alta como autónomo o SL? Condiciona Meta y el RGPD (G) | Antes del primer cliente de pago |

## 3. Orden de trabajo

Cada fase termina con algo comprobable. Tiempos de una persona, estimados con holgura.

| Fase | Bloques | Termina cuando | Tiempo |
|---|---|---|---|
| 1. Repo limpio | R, F1 | Búsqueda de términos reales en los ficheros actuales vacía y CI en verde | 6–8 días |
| 2. Seguridad y errores | S, X | Críticos corregidos con sus tests | 5–7 días |
| 3. Despliegue | A, T, L | Instalación y traslado ensayados en VMs desechables | 8–10 días |
| 4. Demos en producción | B | Los dos demos funcionan por Telegram | 1–2 días |
| 5. Alta de clientes | C, D | Alta real completa sin terminal | 10–12 días |
| 6. Varios peluqueros | E | Demo con dos peluqueros y escenarios en verde | 8–10 días |
| 7. Cierre | F2, F3, G | Sección 5 completa | 4–6 días + trámites externos |

**Camino corto hasta tener los demos en marcha:** fases 1 a 4. Si quieres adelantarlo,
se puede dejar R1 para después, pero entonces los horarios seguirían públicos.

## 4. Lista de trabajo

### R. Repo genérico y sin datos reales

Hecho el 2026-11-10: la versión actual del repo ya no contiene datos de los clientes
reales; quedan en el historial, un tag y las imágenes antiguas, por decisión tuya. La
plantilla de demo de `bus` usa pueblos reales con horarios inventados que no son de
ningún cliente: se deja así.

- [x] **R1 (L)** Creado `tests/packs/bus/fixtures/horarios_ficticios/`: red inventada
  ("Valdehoz": Pozoluengo, Riomayor, Carrascal, Montealto, Fuenteclara, Odalla, Ribazo,
  Campoalto, Pinarnuevo, Valdejunco, Villagrande…), 8 líneas, cubriendo a demanda,
  viernes lectivo, `solo_si_viajeros` (renombrada, ver R2), las tres temporadas,
  festivos locales, ambigüedad de nombre, parada con coma, nombre corto y trayectos no
  vendibles; «mismo autobús» y «pendientes» los siguen cubriendo `horarios_cicloC/` y
  `horarios_pendientes/` (ya ficticios). Reescritos los tests de `bus` que dependían de
  datos reales (`test_conversation.py`, `test_bus_pack.py`, `test_interactive.py`,
  `test_messages.py`, `test_query.py`, `test_loader.py`, `test_matcher.py`,
  `test_formato.py`, `test_calendario.py`, `test_datos.py`, `test_metrics.py`,
  `test_pack.py`, `test_diff.py`, `tools/test_revision.py`, `tools/test_bus_tools.py`).
  Borrado `horarios_real/`; `compat.py` renombrado a `conversation_harness.py`.
- [x] **R2 (S)** Sustituidos por datos ficticios: los teléfonos reales (fixture de
  `salon`, `tests/fixtures/whatsapp/*.json`, el arnés de `bus`), `config_original.yaml`
  (`business_name` → "Salón Ejemplo"), `horarios_cicloC/` (topónimos reales → inventados,
  misma estructura del caso), slugs y nombres en tests y `confirm-dialog.test.tsx`
  (`negocio-ejemplo`), ADR-009:17, y el comentario del `calendario.yaml` de la
  plantilla de demo. Quitados los nombres reales del código: `formato.py:90`
  (`solo_si_viajeros_desde_cordoba` → `solo_si_viajeros`, generalizado en todo el
  código y fixtures), `formato.py:151,1434`, `tools/bus/revision.py:76`, `matcher.py:25`
  (ejemplos inventados), y los ejemplos de `tests/core/test_text.py`.
- [x] **R3 (S)** Sustituir `docs/puesta-en-marcha.md` por este plan: nombra a los clientes
  y duplica pasos. Borrado; `README.md`, `CLAUDE.md`, `docs/README.md` y
  `docs/procedimientos/servidor.md` apuntan ahora a este plan.
- [x] **R4 (M)** Parametrizar lo concreto:

  | Parámetro | Dónde |
  |---|---|
  | `AUTOBOT_IMAGE`, `AUTOBOT_PANEL_IMAGE` | `compose.prod.yaml:34,103`, `restore-test.sh:26,92`, `.env.example`, `variables-entorno.md`; exigidas por `ensure-env.sh` y en `servidor.md` |
  | `ghcr.io/${owner,,}/…` desde `github.repository_owner` | `ci.yml` (job `image`), `deploy.yml` (paso «Verify published image») |
  | `REPO_URL` | `bootstrap-server.sh` (exigido con `:?`), `docs/procedimientos/servidor.md` |
  | `VITE_GITHUB_REPO` (build arg) desde `github.server_url`/`github.repository` | `apps/panel/Dockerfile`, `ci.yml` (job `panel`), `system-page.tsx` (sin enlace si está vacío) |
  | `NGROK_DOMAIN`, sin valor por defecto (`make ngrok` lo lee de `.env`) | `Makefile`, `.env.example`, `comandos.md`, `demo.md` |
  | `DEMO_SALON_CALENDAR_ID`, aplicado en `seed_demos` (avisa si falta) | `salon/template/document.yaml`, `settings.py`, `.env.example`, `variables-entorno.md` |

- [x] **R5 (S) [Tú]** Borrar el paquete antiguo `flowpilot` (hecho el 2026-11-10). No obliga a cambiar
  credenciales y nada del repo lo usa:

  ```bash
  gh auth refresh -h github.com -s delete:packages   # pide confirmar un código
  gh api -X DELETE /user/packages/container/flowpilot
  ```

  Las imágenes antiguas de `autobot` llevan los horarios, igual que el historial: se
  pueden dejar. Si prefieres retirarlas, `gh api -X DELETE /user/packages/container/autobot`
  antes de un despliegue, y CI las vuelve a publicar en el siguiente commit.
- [x] **R6 (S)** Control en CI con los hashes de los términos prohibidos
  (`deploy/ci/forbidden-terms.sha256`, comprobado por `deploy/scripts/check-forbidden-terms.py`
  en el job `forbidden-terms` de `ci.yml`, que bloquea el job `image`), y `**/tests` en
  `apps/backend/.dockerignore`: el patrón actual `tests` solo excluye la raíz, y por eso
  las imágenes llevaban horarios. El control no tiene excepciones.
- [x] **R7 (S) [Tú]** Confirmado: el calendario de la demo no es público.

**Comprobación de R:** `git grep -iE '<términos>'` con los términos de `var/limpieza/` no
devuelve nada. El historial y las imágenes antiguas quedan fuera por decisión tuya.

### S. Seguridad

Lo más urgente es S1 y S2 antes de desplegar, y S3 antes de abrir la demo a nadie.

- [x] **S1 (S) [Aprobación]** Producción acepta valores publicados en el repo:
  `DJANGO_SECRET_KEY=change-me` y la clave de cifrado de `.env.example` y `settings.py:37`,
  y `ensure-env.sh` no corrige los valores de ejemplo (también `DB_*_URL=...localhost`).
  Rechazarlos en `settings.py` y en `ensure-env.sh`.
  Hecho: `settings.py` rechaza `DJANGO_SECRET_KEY=change-me`, la clave de cifrado de
  ejemplo y cualquier `DB_*_URL` con `localhost` cuando `ENVIRONMENT=prod`; `ensure-env.sh`
  rechaza los mismos valores si ya están puestos en el `.env` del servidor (no solo si
  faltan). Tests en `tests/repo/test_settings.py` y `tests/tools/test_ensure_env.py`.
- [x] **S2 (S) [Aprobación]** `WhatsAppSecrets` admite vacíos (`schema.py:164`): con
  `app_secret` vacío cualquiera firma webhooks válidos. Exigir longitud mínima.
  Hecho: `app_secret` exige `min_length=32` (mismo patrón que `TelegramSecrets.webhook_secret`).
  Tests en `tests/platform/tenancy/test_registry.py`.
- [x] **S3 (S)** **Inyección `[CFG]`.** Quien reserve con el nombre `[CFG] cerrado` cierra
  ese día para todos (`booking.py:137`, `parser.py:106`, `slots.py:75`); `[CFG] HORARIO`
  recorta el horario. Ignorar `parse_cfg` si el evento tiene `fp_key`, rechazar `[cfg]`
  en el nombre y añadir escenario.
  Hecho: `conversation.py` rechaza nombres con `[cfg]` antes de reservar; `slots.py` y
  `booking.py` ignoran `parse_cfg` en cualquier evento con `fp_key` (defensa en
  profundidad). Escenario en `tests/packs/salon/test_booking.py`
  (`test_cfg_injection_in_the_client_name_is_rejected`).
- [x] **S4 (S) [Aprobación]** El bloqueo por IP es común a todos los webhooks
  (`channels/views.py:37`): un bot atacante podría bloquear la IP de Telegram para todos.
  Usar `(ip, ruta)` como clave.
  Hecho: clave `f"{ip}:{route}"` en `channels/views.py`. Test en
  `tests/platform/channels/test_webhooks.py`
  (`test_blocking_an_ip_on_whatsapp_does_not_block_it_on_telegram`).
- [x] **S5 (S) [Aprobación]** `init-roles.sh:59` devuelve permisos amplios a `fp_app` y, si
  el despliegue aborta, no se reaplica `apply_grants` (`deploy.sh:111-117`).
  Hecho: `abort()` en `deploy.sh` reaplica `apply_grants` (best effort, como `alert_ops`)
  antes de salir. Tests en `tests/tools/test_deploy.py`.
- [x] **S6 (S) [Aprobación]** `fp_app` puede vaciar la auditoría con
  `purge_platform_history('infinity')`. Forzar un mínimo de un año dentro de la función.
  Hecho: migración `0021_purge_platform_history_min_cutoff.py` redefine la función SQL
  con `least(cutoff, now() - interval '1 year')`. Test en `test_retention.py`
  (`test_purge_platform_history_clamps_cutoff_to_a_year`).
- [x] **S7 (S)** El panel muestra `session_key` en la vista de tablas (`catalog.py:236`).
  Añadir `owner_link.invite_hash` y `platform_cache.value` a `SENSITIVE_TABLES`.
  Hecho: `django_session.session_key` añadido a `HIDDEN_COLUMNS` (catalog.py);
  `owner_link` y `platform_cache` añadidos a `SENSITIVE_TABLES` (grants.py), reaplicado
  por `apply_grants` como siempre (sin migración nueva, ya es la fuente de verdad según
  CLAUDE.md). Tests en `test_data.py` y `test_db_roles.py` (genéricos, ya cubrían ambas
  listas).
- [x] **S8 (S)** Auditar la consola SQL antes de ejecutar y también la vista de tablas: hoy
  un error de `CAST` saca el dato sin dejar rastro.
  Hecho: `query.run()` y `catalog.table_detail()` registran la auditoría antes de
  ejecutar la consulta (no después de que tenga éxito), así un fallo nunca queda sin
  rastro; `table_detail()` también envuelve el `cursor.execute` para no propagar un 500
  sin control. Tests: `test_audits_a_query_even_when_it_fails`,
  `test_table_detail_is_audited_even_on_error`.
- [x] **S9 (M)** `contact_forget` no borra los avisos al dueño, que guardan el nombre del
  cliente (`privacy.py:180`).
  Hecho: `Notification.contact` (FK nula, `on_delete=CASCADE`, igual que
  `OutboundMessage.contact`) en la migración `0022_notification_contact.py`; se rellena
  en `process._notify_owner` (nulo para el resumen mensual, que no es de un contacto).
  `forget()` no necesitó cambios: el `.delete()` de `Contact` ya hace cascada. Test en
  `test_retention.py` (`test_forget_erases_the_owner_notifications_naming_the_contact`).
- [x] **S10 (S)** Evitar que el log de consultas lentas escriba parámetros (`compose.prod.yaml:127`).
  Hecho: `log_parameter_max_length=0` y `log_parameter_max_length_on_error=0` en el
  `command` de `db`. Test en `test_compose_prod.py`.
- [x] **S11 (S) [Aprobación]** Fijar `caddy` y `postgres` por versión o digest, y añadir
  `cap_drop: [ALL]` y `no-new-privileges`.
  Hecho: `postgres:18` y `caddy:2` fijados por digest (comprobado localmente con
  `docker pull`). `cap_drop: [ALL]` + `no-new-privileges:true` en ambos; `caddy` recupera
  solo `NET_BIND_SERVICE` (para los puertos 80/443 como no-root) y `db` solo
  `CHOWN, FOWNER, DAC_OVERRIDE, SETUID, SETGID` (lo mínimo para que el entrypoint de
  postgres pueda arrancar como no-root luego; verificado arrancando ambos contenedores
  en local con esas capacidades exactas, sin más). Tests en `test_compose_prod.py`.
- [x] **S12 (S)** `/health` público solo con `status`; `deploy.sh:29` necesita un detalle
  interno, por ejemplo una ruta solo en 127.0.0.1.
  Hecho: `/health` público devuelve solo `status`; el detalle de tenants/BD se movió a
  `/health/internal`, que Caddy nunca reenvía (fuera de su matcher `@public`); `deploy.sh`
  usa esa ruta. Tests en `test_webhooks.py`, `test_registry_database.py`.
- [x] **S13 (S)** GitHub, solo lo imprescindible (decidido el 2026-11-11):
  - Fijar por SHA las actions de `deploy.yml` (`actions/checkout`, `docker/login-action`),
    el único workflow que tiene la clave SSH del servidor.
  - Quitar Dependabot: borrar `.github/dependabot.yml` y cerrar sus PR abiertos (#10–#15)
    con sus ramas. Las dependencias se actualizan a mano.
  - Descartado: permisos por defecto de `GITHUB_TOKEN`, revisor en `production`, protección
    de `main` y aprobación de PR de forks. Solo tú tienes acceso de escritura y los PR de
    forks no reciben los secretos.
  Hecho: `actions/checkout@v7` y `docker/login-action@v4` fijados por el SHA exacto de
  esos tags (consultado con `gh api`). `.github/dependabot.yml` borrado; PR #10–#15
  cerrados y sus ramas remotas borradas (`gh pr close --delete-branch`). Test en
  `test_deploy_workflow.py`.
- ~~**S14 (S)** Limitar ngrok a `/webhooks/*` o rechazar el panel fuera de localhost.~~
  **Descartada (2026-11-11):** ngrok solo se usa para probar en local, nunca en producción.

### X. Errores de funcionamiento

**Graves:**

| Id | Esf. | Problema | Dónde |
|---|---|---|---|
| X1 | S | Si muere el worker durante `ops_check`, se atasca para siempre y no hay más alertas | `jobs.py:251` |
| X2 | S | Un corte de ~30 s de Meta o Telegram pierde respuestas y recordatorios: solo reintenta 2+4+8+16 s | `outbound.py:89`, `jobs.py:113` |
| X3 | M | Si falla algo entre el commit y encolar, la respuesta se pierde. Falta un reconciliador | `jobs.py:62`, `process.py:160` |
| X4 | S | `[CFG] HORARIO 25:00-26:00` en el calendario tumba «Pedir cita» | `parser.py:115`, `slots.py:27` |
| X5 | S | Un 502 de Telegram se reintenta a ciegas y puede duplicar. Debe tratarse como ambiguo | `telegram/adapter.py:216` |
| X6 | S | `bus` elige pueblo en silencio si dos paradas se llaman igual | `bus/matcher.py:88` |
| X7 | S | `bus` se queda atascado en `CONFIRMAR_PUEBLO` | `bus/conversation.py:613` |

**Medios:**

| Id | Esf. | Problema | Dónde |
|---|---|---|---|
| X8 | S | Alertas que no se cierran nunca por un fallo antiguo | `ops/check.py:82,93` |
| X9 | S | `unreachable` no vuelve a false al desbloquear el bot | `outbound.py:174` |
| X10 | M | Un negocio degradado bloquea todos los despliegues; ni siquiera se puede pausar | `deploy.sh:29,118`, `store.py:400` |
| X11 | S | Datasets o enlaces válidos que rompen al usarse (límites) | `bus/interactive.py:66,221` |
| X12 | S | Errores de red no considerados transitorios: pueden quedar dos citas | `google_calendar/client.py:132` |
| X13 | S | Un fallo puntual de salud queda cacheado 24 h | `ops/health.py:178` |
| X14 | M | Una caída de Google frena a todos: 4 hilos para las tres colas | `compose.prod.yaml:98` |
| X15 | S | `procrastinate_jobs` y `_events` crecen sin límite | `retention.py:47` |

**Leves (S, juntos):** foto en cualquier paso de `salon`; mover una cita manual sin nombre la
llama «Cliente»; un `patch` fallido aborta todo el barrido; lista de días tras la
medianoche; coste sin poda en el matcher; la `baja` no se registra en un negocio degradado.

**Rendimiento (S, juntos):** cachear `Credentials` por proceso; `fields=` en las lecturas
de Calendar; escribir `record_calendar` solo al cambiar de estado; repartir los barridos
en el tiempo; índices parciales en `outbound_message`.

### A. Infraestructura e instalación

**Máquina:** 2 vCPU, 4 GB y 2 GB de swap; se estima suficiente para 5–15 negocios, sin
haberlo medido bajo carga.

| Proveedor (sin IVA, 2026-11-09) | Recursos | Precio | Observaciones |
|---|---|---|---|
| OVHcloud VPS-1 | 2 vCore, 4 GB, 40 GB | desde 3,81 €/mes | Confirmar permanencia y centro de datos UE |
| Hetzner CX23 | 2 vCPU, 4 GB, 40 GB | 5,99 €/mes | Sin stock |
| netcup VPS 500 G12.5 | 2 vCPU, 4 GB, 64 GB | 8,26 €/mes con 12 meses | Alternativa |

Total estimado: menos de 10 €/mes, con dominio y planes gratuitos de Sentry,
healthchecks.io y backups.

**Errores que hay que corregir antes de la primera ejecución (S cada uno, salvo indicación):**

- [ ] **A1** Compose no lee el `.env` de la raíz con `-f`. Crear un `lib.sh` común con
  `--env-file "$root/.env"` y usarlo en todos los scripts. **Bloqueante.**
- [ ] **A2** `backup.sh:46` y los `docker compose exec` de la documentación fallan sin
  `SHA`: exportarlo desde `var/.deployed-sha` y añadir `make prod-compose`. **Bloqueante.**
- [ ] **A3** `restic init` no lo hace nadie: el primer backup falla. **Bloqueante.**
- [ ] **A4** Exigir `google_sa.json` como fichero regular: si falta, Docker crea un directorio.
- [ ] **A5** Exigir o derivar `PUBLIC_URL` de `PUBLIC_HOST`.
- [ ] **A6** Imponer `DEPLOY_UID` con `id -u`, también al restaurar.
- [ ] **A7** Corregir `make rollback`: el segundo vuelve al SHA roto (`Makefile:179`).
- [ ] **A8** Dump previo si hay migraciones, y regla de expandir y contraer: hoy la vuelta
  atrás no deshace el esquema, y `abort` lo da por bueno.
- [ ] **A9** Recargar Caddy si cambia su fichero y comprobar HTTPS tras desplegar.
- [ ] **A10** Hacer `pull` de `db` y `caddy` con versión fijada (S11).
- [ ] **A11** Disco: `docker image prune` periódico y límite de tamaño para VictoriaLogs.
- [ ] **A12** `bootstrap-server.sh`: admitir `root` o usuario con `sudo`, cerrar SSH al
  final y dar a `deploy` un `sudoers` limitado a ese script.
- [ ] **A13** Documentar la subida de versión mayor de PostgreSQL.
- [ ] **A14** Política de retención de imágenes en GHCR: restaurar depende de la del SHA.

**Comando de instalación:**

- [ ] **A15 (M) [Tú lo ejecutas]** `make server-init HOST=<ip> [SSH_USER=root|ubuntu]`, con
  `var/server.env` (dominio, repo, imagen y credenciales externas). Idempotente:
  1. Valida en local que no falte nada y que el DNS apunte a la IP.
  2. Genera claves y crea la deploy key con `gh`.
  3. Ejecuta el bootstrap.
  4. Sube `.env`, `google_sa.json`, `backup.env` y la contraseña de restic.
  5. `restic init` y activa el timer.
  6. Crea el entorno `production` y sus secretos con `gh`.
  7. Lanza el despliegue y comprueba HTTPS.
  8. Crea el usuario del panel, registra los webhooks de `demo` y `notify` y hace el
     primer backup.
- [ ] **A16 (M)** Ensayo en VM desechable: instalar, repetir sin cambios, vuelta atrás con
  un SHA roto, backup real y restauración (T3).
- [ ] **A17 (S) [Tú]** Crear cuentas: Sentry, dos checks de healthchecks.io, monitor externo
  de `/health` y backups en R2 o B2, en región UE y en otro proveedor. Con B2, usar su
  endpoint S3 (`backup.sh:22` solo exporta `AWS_*`).
- [ ] **A18 (S)** Actualizar ADR-005 y `docs/procedimientos/servidor.md`.

**A mano para siempre:** alquilar la VM, apuntar el DNS, crear las cuentas externas y
aprobar el despliegue.

### T. Backup y traslado a otro entorno

Para ampliar RAM, cambiar de proveedor o recuperarse si se pierde la máquina.

**Lo que debe entrar en el backup:** base de datos, `.env` (incluye la clave de cifrado),
`google_sa.json`, `.deployed-sha`, certificados y estado de Caddy (`var/state/caddy-*`) y
`deploys.jsonl`. **Guárdalos en el gestor de contraseñas, fuera del backup:** contraseña de
restic, claves S3 y claves SSH.

Si la VM admite ampliar recursos en el propio proveedor, basta con un reinicio y no hace
falta nada de esto.

- [ ] **T1 (S cada uno)** Corregir `restore.sh`:
  - Hoy arranca `worker` con los tokens reales antes de cambiar el DNS (`:82`), así que
    enviaría mensajes reales. Debe ser `--no-start` por defecto.
  - Levantar también `panel` y `victorialogs`.
  - Hacer checkout del SHA del snapshot (`:71`).
  - Exigir que el bootstrap esté hecho antes.
- [ ] **T2 (S)** Añadir Caddy y `deploys.jsonl` a `backup.sh`.
- [ ] **T3 (S)** Arreglar `restore-test.sh`: le falta `DB_READONLY_URL`, y hoy no pasa.
- [ ] **T4 (M) [Tú lo ejecutas]** `make server-migrate FROM=<a> TO=<b>`:
  1. 24 h antes, bajar el TTL del DNS a 60–300 s.
  2. `server-init` en destino en modo restauración, sin desplegar y con el timer parado.
  3. Ensayo en destino y comparación de conteos por negocio.
  4. Corte: parar `caddy`, `web`, `worker` y el timer en origen, y hacer un backup final.
  5. En destino: checkout del SHA, restaurar, `DEPLOY_UID`, roles y permisos, certificados.
  6. Arrancar todo menos `worker` y verificar con `curl --resolve`; después, `worker`.
  7. **[Tú]** Cambiar el DNS. Con el mismo dominio no hay que tocar webhooks.
  8. Actualizar `DEPLOY_HOST` y `DEPLOY_KNOWN_HOSTS`, activar el timer y conservar el
     origen parado 7 días.
- [ ] **T5 (S)** Backup cada hora en lugar de cada seis, si hay reservas reales.
- [ ] **T6 (S)** Procedimiento de pérdida total en `docs/incidencias/`: revisar a mano antes
  de arrancar `worker`, porque lo posterior al snapshot puede duplicarse y las citas nuevas
  quedan en Google sin fila.

| Caso | Datos que se pierden | Tiempo de corte (a medir en A16) |
|---|---|---|
| Traslado planificado | Ninguno (salvo logs técnicos) | 15–30 min más el TTL |
| Pérdida de la máquina | Hasta 6 h (1 h con T5) | 1–2 h |

### L. Entorno local completo

Hoy en local no se pueden probar Caddy con TLS, `read_only` con UID real, gunicorn,
`deploy.sh` ni backups.

- [ ] **L1 (M)** `make localprod-up`: `compose.localprod.yaml` con imágenes construidas en
  local, puertos 8443 y 8081, `var/localprod/.env`, proyecto aparte y restic en disco,
  ejecutando el `deploy.sh` real.
- [ ] **L2 (S)** `make localprod-backup` y `localprod-restore`, para probar el ciclo completo.
- [ ] **L3 (S)** Job de CI con `compose config` y `restore-test`, para que no se vuelva a romper.
- [ ] **L4 (S)** Chat por terminal con un pack, sin canal real, sobre el arnés existente.

El bootstrap, `ufw` y los timers solo se prueban en una VM desechable (A16).

### B. Lanzar con los demos

- [ ] **B1 (S) [Tú]** Bot de demo de producción en Telegram y su token, en `var/server.env`.
- [ ] **B2 (S) [Tú]** Bot de avisos y chat de ops.
- [ ] **B3 (S)** Decidir D5. Hoy cada alta exige editar `.env` y reiniciar; si crece, gestionar
  la lista desde el panel.
- [ ] **B4 (S)** Aviso breve de privacidad en la demo.
- [ ] **B5 (S) [Aprobación]** `RETENTION_CLEANUP_ENABLED=true` (D4): sin esto tampoco
  caducan los datos de la demo.
- [ ] **B6 (S)** Recorrido real de los dos demos y comprobar que parar el worker dispara la alerta.
- [ ] **B7 (M, opcional)** Demo por WhatsApp (D6).

### C. Alta y gestión de clientes en el panel

Objetivo: configurar un cliente entero desde el panel, con todo lo necesario a mano.
Revisado leyendo el código; C25 lo confirma en real.

**Errores:**

- [ ] **C1 (S)** La lista «Pendiente para activar» **no se usa en ninguna pantalla**
  (`missing-checklist.tsx`). Corregir además sus falsos positivos: cuenta mensajes
  ignorados de desconocidos, da plantillas por buenas sin canal o en Telegram y no exige
  `display_phone`, y sin él no hay QR (`activation.py:49-55`).
- [ ] **C2 (S)** Un `salon` nuevo hereda el texto «peluquería de prueba» (`info_text`).
- [ ] **C3 (S)** Un `bus` nuevo hereda nombre, teléfono y pueblos: su pack no tiene
  `template_blank`.
- [ ] **C4 (S)** Un `bus` nuevo recibe en silencio **los horarios inventados de la demo**
  (`store.py:274-280`). Lo resuelve la biblioteca de horarios (C19–C24): el alta exige
  elegir horarios.
- [ ] **C5 (S)** Bloqueo circular en `bus`: los pueblos deben existir en el dataset y el
  dataset en los pueblos, y el error real se pierde (`datos.py:41`, `store.py:123`). Lo
  resuelve la biblioteca (C22): los pueblos se eligen de los horarios escogidos. Corregir
  aparte el mensaje de error.
- [ ] **C6 (M)** Campos nulos sin caja de texto en el formulario (`str|None`, `Owner|None`),
  `demo` visible en clientes reales y `reminder_window_hours` roto.
- [ ] **C7 (S)** Validación ilegible, como `(root): valor no válido` (`store.py:52`); mensajes en inglés.
- [ ] **C8 (S)** `owner.notify` vacío: un dueño recién enlazado **no recibe avisos**.
  Valores por defecto y casillas por pack.
- [ ] **C9 (S)** Tras Activar o Pausar, el siguiente guardado da 409 (`editor.tsx:230`), y la
  caché de 2 s da 404 tras crear (`registry.py:448`).
- [ ] **C10 (S)** Al cambiar `webhook_secret` de Telegram, sigue el antiguo y el panel dice
  «Registrado» (`registration.py:88`). Volver a registrar al guardar.
- [ ] **C11 (S)** Errores silenciosos: guardar sin datos, 422 sin campo, tokens sin recortar.

**Lo que tiene que estar a mano:**

- [ ] **C12 (L)** **Pestaña «Alta»**, la primera en `onboarding` y destino del asistente.
  Cada paso muestra estado, por qué importa, qué hacer, valores con botón de copiar y
  «Comprobar». Requiere ADR y `GET /tenants/{slug}/setup`, más
  `POST .../setup/check/{step}`, con los pasos de canal en sus adaptadores y un hook de pack.
  - **Común:** datos propios, testers («últimos que escribieron → añadir»), mensaje real
    de tester, dueño, QR y Activar.
  - **WhatsApp:** ids y `display_phone`, secretos, URL del webhook (hoy solo sale para
    Telegram), `verify_token`, campo `messages`, `subscribed_apps` y plantillas con su texto
    y estado. Avisar del orden: la verificación da 404 hasta tener 3 ids y 3 secretos.
  - **Telegram:** token, `getMe` rellena el usuario, secreto automático y registro del webhook.
  - **`salon`:** ver D. **`bus`:** horarios elegidos de la biblioteca, su versión, vigencia
    y pueblos (C22–C23).
- [ ] **C13 (S)** **QR de clientes:** hoy desborda y no se descarga. Tamaño y margen
  correctos, descarga en SVG/PNG, vista para imprimir y aviso si falta el dato en vez de ocultarse.
- [ ] **C14 (S)** **QR del chat de avisos del dueño:** el enlace ya existe; añadir QR, estado
  «invitación pendiente» y desconectar. Añadir «Mi QR» al menú del dueño.
- [ ] **C15 (S)** Sistema debe avisar si el webhook del bot de avisos no está registrado: hoy
  marca «ok» y el dueño no recibe respuesta (`system.py:178`).
- [ ] **C16 (M)** Historial y vuelta atrás de configuración (la API ya existe), y lo que hoy
  solo está en terminal: `owner_unlink`, exportar y olvidar contacto, exportar negocio.
- [ ] **C17 (M)** Editores propios: horario por día, servicios en tabla con id automático y
  zona horaria en selector. Plegar textos y evento especial, y revisión final legible.
- [ ] **C18 (M) [Aprobación]** «Conectar WhatsApp» desde el panel por API: `subscribed_apps`,
  registro del número, plantillas y estado. Es lo que más ahorra sin cambiar de modelo.

**Biblioteca de horarios.** Los horarios se suben por terminal a una biblioteca y, al
crear un cliente, se elige uno desde el panel. Sustituye al plan anterior de publicar
horarios directamente sobre cada cliente.

- **Por qué:** resuelve C4 y C5, deja la terminal solo para subir horarios y separa la
  preparación de los datos del alta del cliente.
- **En tu portátil** cada conjunto de horarios es una carpeta en `var/datos/<nombre>/`,
  ignorada por git.
- **En el servidor** se guardan en la base de datos, no en carpetas: así entran en los
  backups y en `server-migrate`, quedan versionados y el panel puede listarlos.
- **El cliente se queda con una copia** de la versión elegida. Una subida nueva nunca le
  cambia los horarios sola: la ficha avisa y se aplica con un botón. Un error al subir no
  rompe a un cliente activo.
- Es genérico: sirve para cualquier pack que declare datasets, no solo `bus`. En el código
  se llama conjunto de datos; en el panel, «Horarios».

- [ ] **C19 (S)** ADR «Biblioteca de conjuntos de datos», que modifica ADR-009, donde hoy
  los datos van ligados a cada cliente. Debe fijar el nombre del concepto, copia frente a
  referencia (propuesta: copia), qué guarda el cliente (nombre y versión de origen) y cómo
  queda la demo.
- [ ] **C20 (M)** Almacén: tabla de la plataforma con nombre, pack, versión, contenido,
  sha, autor, comentario y fecha, sin `tenant_id`. Permisos en `autobot/db/grants.py`. Sin
  RLS, porque no son datos de cliente: no requiere aprobación especial. La plantilla de la
  demo de `bus` pasa a ser una entrada más.
- [ ] **C21 (M)** Comando de subida desde el portátil:
  `make bus-subir NOMBRE=<nombre> DIR=var/datos/<nombre> COMMENT="…" [PROD=1]`.
  1. Valida en local y muestra el diff con la versión anterior de ese nombre.
  2. Prueba en el servidor sin escribir.
  3. Sube por SSH una versión nueva, rechazando si otra persona subió antes (`--base-sha`).
  Nunca toca a ningún cliente.
- [ ] **C22 (M)** Alta en el panel: elegir horarios de la biblioteca, con resumen de líneas,
  pueblos, vigencia y fecha. Los pueblos del menú se eligen de una lista sacada de ellos.
  El alta de un pack con datasets no se completa sin elegirlos.
- [ ] **C23 (S)** Ficha del cliente: horarios en uso (nombre, versión, autor, fecha,
  vigencia), aviso de versión nueva con resumen de cambios y botón «Aplicar». Antes de
  aplicar, avisa si falta algún pueblo del menú. Nunca muestra el contenido.
- [ ] **C24 (S)** Sustituir los comandos actuales `tenant_dataset`, `bus-bajar` y
  `bus-publicar`, y su documentación (`docs/procedimientos/horarios-bus.md`).

**Validación final:**

- [ ] **C25 (S)** Alta real completa, por Telegram en local, de un `salon` y un `bus`, sin
  terminal salvo para subir los horarios.
- [ ] **C26 (S)** Pequeños arreglos de UI: errores con estilo, copiar con confirmación,
  estados en español, móvil, y el texto «comentario obligatorio», que es falso.

### D. Calendario

**Una sola cuenta de servicio para toda la plataforma.** No se crea una por peluquero.
Cada negocio comparte su calendario con su email y da el `calendar_id`. Es un enfoque
válido; el problema es que el panel no lo guía.

Descartados: crear calendarios desde la plataforma (la propiedad no se transfiere fuera de
Workspace) y «Conectar con Google» (verificación de Google, tokens por negocio y página pública).

- [ ] **D1 (S)** Mostrar el email de la cuenta de servicio, con botón de copiar.
- [ ] **D2 (S)** Texto para enviar al peluquero: compartir el calendario y dar el id. Probar
  cuál es el permiso mínimo: «Hacer cambios en eventos» y sus variantes actuales.
- [ ] **D3 (S)** «Comprobar acceso» con **prueba de escritura** (hoy solo lee,
  `client.py:283`), fila propia en la activación y mensaje claro (`health.py:146` lo oculta).
- [ ] **D4 (S)** Avisar en el alta si es un Gmail personal: Google no cubre esas cuentas con su
  contrato de tratamiento de datos.

### E. Varios peluqueros

**Decisión propuesta:** ampliar `salon`, no crear otro pack, y hacerlo para **N peluqueros
con tope de 8** (8 + «me da igual» + volver = 10 filas). Un calendario por peluquero. Con un
solo peluquero el flujo no cambia.

Preguntas (D8), con lo que propongo:

- [ ] «Me da igual»: unión de huecos, asignar al de menos citas ese día y decir con quién.
- [ ] Horario propio: opcional, heredando el del negocio.
- [ ] Servicios por peluquero: opcional.
- [ ] Cierre de todo el negocio: lista en la config.
- [ ] Avisos: solo al dueño de momento.

Trampas que el diseño debe evitar:

- **Doble reserva:** `event_id` no depende del calendario, y un reintento de «me da igual» podría
  elegir otro peluquero y duplicar. Guardar la asignación con `ctx.effects.put` antes de insertar.
- **Candado** por peluquero, tomado tras asignar y revalidando el hueco.
- **Límite de 64 bytes:** `reminder_confirm:` y el id ya ocupan 49. La clave del peluquero debe
  ser corta (≤4), estable y validada.
- **Coste en Google:** reservar pasa de 6 llamadas a N+5, o 4N+2 con «me da igual» (34 con 8).
- **Salud:** el estado por canal taparía un calendario sin acceso con el «ok» de otro.
- Las plantillas de Meta no se tocan, para evitar otra aprobación.

Tareas:

- [ ] **E1 (S)** ADR con lo anterior.
- [ ] **E2 (M)** Limpiar el contrato del pack: `Pack.calendars(config)` y `ctx.calendars`, sin
  que la plataforma lea `staff`. También `Periodic.tracks_health` y `metric_labels`, hoy con
  nombres fijos (`periodic.py:115`, `check.py:143`).
- [ ] **E3 (M)** Plataforma: efectos, candados y arnés de pruebas con varios calendarios.
- [ ] **E4 (L)** Pack: config, disponibilidad, reservar, mover, cancelar, barrido, resumen y
  `state_version`.
- [ ] **E5 (M)** Escenarios de conversación, con los límites de cada canal.
- [ ] **E6 (S)** Demo con dos peluqueros y dos calendarios (exige `dev-reset`).
- [ ] **E7 (S)** Panel: alta de peluqueros y comprobación de cada calendario (requiere D3).

### F. Simplificación y facilidad de desarrollo

**F1. Limpieza inicial (S, junta con R):**

- [ ] Borrar código muerto: `bus/messages.py:36,211`, `event_no_days`, `parse_reminder`,
  `remove_field`, `next_days`, `sources_from_directory`, y compatibilidad con `tenant.yaml`
  (`registry.py:150`, `forms.py:129`), tras renombrar el fichero local.
- [ ] Borrar la migración del bot anterior si D3 se confirma: `salon/migration.py`,
  `tools/salon/migrate_salon_events.py`, y `list_future_events` y `patch_private` del puerto.
- [ ] Referencias rotas a `docs/runbooks/` y restos en la raíz (`.venv`, cachés).

**F2. Comandos finales** (cuando C funcione de extremo a extremo). `make` pasa de 35 a unos 25
objetivos, y `manage.py` de 21 a 14:

| Uso | Comandos |
|---|---|
| `make` desarrollo | `help up down logs shell dev-bootstrap dev-reset dev-activity ngrok test test-fast check fix api panel-dev panel-check new-pack localprod-*` |
| `make` producción | `server-init server-migrate panel-tunnel deploy rollback backup-now restore-test prod-manage prod-compose bus-subir bus-revision` |
| `manage.py` despliegue | `migrate apply_grants seed_demos tenant_config export_openapi` |
| `manage.py` emergencia | `panel_user tenant_secrets_reencrypt telegram_set_webhook` (solo `demo` y `notify`) |
| `manage.py` RGPD | `contact_export contact_forget tenant_data_export tenant_purge` |
| `manage.py` otros | `seed_dev_activity` y el comando de la biblioteca de C21 |

Desaparecen: `status`, `db-roles` (va al bootstrap), `telegram_poll` y `polling.py`,
`check-prod-config`, `tenant-health`/`tenant_health`, `tenant_status`, `outbound_resolve`,
`job_retry`, `owner_invite`, `owner_unlink` (cuando exista en el panel), `tenant-import`,
`tenant-push` y los `bus-*` no listados.

`qr` queda absorbido por C13. Quitar los comandos duplicados tiene un coste: si el panel cae,
la vía de emergencia es `prod-manage shell`.

**F3. Después del lanzamiento (S salvo indicación):**

- [ ] Tests más rápidos: hasher rápido y un solo flush, unas 3–4 veces en los ficheros medidos.
- [ ] `make new-pack NAME=x` a partir de `toy_pack`, y un test de contrato genérico sobre `PACKS`.
- [ ] Guía «Añadir un pack» en `docs/desarrollo/`. Hoy no existe.
- [ ] Comprobar en CI variables y comandos contra la documentación; faltan `VICTORIALOGS_URL`,
  `OPS_STATE_DIR` y `AUTOBOT_BINARY_STDOUT`.
- [ ] Imagen más pequeña: podar `discovery_cache` (−108 MB).
- [ ] Mover `owned` de `integrations` al pack (M): la integración conoce `[cfg]` y `waid`.
- [ ] Revisar los tests del panel que fallan por tiempo en local (90–93 de 94 con carga; en CI, verde).

### G. Antes del primer cliente real

**Legal.** No es asesoramiento jurídico; hazlo revisar por un profesional.

- [ ] **G1** El negocio es responsable; tú, encargado (art. 28 RGPD). Entregarle contrato con
  anexo de subencargados, texto del aviso para el bot, ficha para su registro de actividades
  y procedimiento de derechos y baja. Tú llevas el registro de encargado (art. 30.2).
- [ ] **G2 (S)** Aviso de privacidad en el primer mensaje y enlace en el bot. Telegram exige
  una política accesible.
- [ ] **G3 (M)** **Consentimiento para recordatorios:** Meta exige opt-in y hoy solo existe
  `opt_out` por contacto y `reminders_enabled` por negocio. Con escenarios.
- [ ] **G4** Decidir D10. Meta pide datos de entidad legal y documentos oficiales.

**WhatsApp:**

- [ ] **G5 (S)** Corregir los documentos: `alta-whatsapp-meta.md:30-31,71-72,92-122`,
  `alta-baja-negocio.md:50-61`, ADR-006:49. Falta avisar de que **hace falta método de pago**.
- [ ] **G6 (S)** Fijar el precio al cliente con la tarifa real. Desde el 1/10/2026 Meta cobra las
  respuestas en ventana y los mensajes utility; hay 1.000 service gratis al mes por número.
  Referencia: 200 citas con confirmación y recordatorio serían unos 6,64 €/mes sin IVA.

**Modelo futuro de incorporación:**

- [ ] **G7 (M) [Aprobación]** Telegram **Managed Bots** (Bot API 9.6): el dueño crea el bot con un
  toque y no hay que pasar por BotFather. Requiere ADR y probarlo.
- [ ] **G8 (L) [Aprobación]** Tras el alta fiscal y con varios clientes: **Tech Provider con Hosted
  Embedded Signup** en WhatsApp, para que el negocio se conecte solo. Conviene no acumular
  muchas altas con el modelo actual, porque migrar no es gratis.
- [ ] Descartados: BSP (360dialog desde 49 €/número/mes) y número compartido para clientes reales.

## 5. Listo para producción

Se da por terminado cuando todo esto se cumple:

- [ ] Ningún término real aparece en la versión final del repo ni en las imágenes nuevas.
  El repo no nombra ningún cliente, dominio o servidor concreto.
- [ ] S1–S3 y X1–X7 corregidos, con tests. Resto de S y X resueltos o aplazados por escrito.
- [ ] `make server-init` deja una VM limpia funcionando, y repetirlo no cambia nada.
- [ ] Vuelta atrás probada con un SHA roto.
- [ ] Backup automático en restic y restauración ensayada, con su tiempo anotado.
- [ ] `make server-migrate` ensayado entre dos VMs desechables.
- [ ] Parar el worker dispara la alerta y arrancarlo la recupera.
- [ ] Demos funcionando en producción con HTTPS válido.
- [ ] Alta completa de `salon` y `bus` desde el panel, sin terminal salvo la carga de horarios.
- [ ] QR del canal descargable y QR del chat de avisos funcionando.
- [ ] Salón con dos peluqueros probado con reservas reales.
- [ ] `make localprod-up` reproduce producción en local.
- [ ] Documentos legales listos antes del primer cliente.

## 6. Cómo se trabajará después

| Quiero… | Cómo |
|---|---|
| Añadir un cliente | Panel → Nuevo cliente → pestaña Alta |
| Cambiar horarios, servicios, textos | Ficha del cliente, sin desplegar |
| Subir horarios de `bus` | `make bus-subir NOMBRE=x DIR=var/datos/x COMMENT=… PROD=1` |
| Cambiar los horarios de un cliente | Ficha del cliente → Horarios → Aplicar |
| Desplegar un cambio | Commit en `main`, CI en verde, `make deploy` |
| Volver atrás | `make rollback` |
| Añadir un pack | `make new-pack NAME=x`, implementar, `make check` |
| Probar todo en local | `make localprod-up` |
| Ampliar la máquina | Ampliarla en el proveedor o `make server-migrate` |

## 7. Qué no se ha podido comprobar

- Nada se ha ejecutado en una VM real ni contra Meta, Telegram o Google en producción.
- Consumo real de memoria y tiempos de corte: son estimaciones, a medir en A16.
- Render real de los formularios del panel: revisado leyendo el código y la librería.
- Sin herramienta específica de secretos: se usaron regex y entropía, que no detectan
  contraseñas débiles en texto libre.
- Precio de OVH y netcup sin permanencia; stock de los proveedores el día de la compra.
- Tarifa exacta de Meta para España; requisitos de Meta para autónomos.

## Fuentes (consultadas el 2026-11-09)

- Infraestructura: [Hetzner](https://www.hetzner.com/cloud/cost-optimized),
  [OVHcloud](https://www.ovhcloud.com/es-es/vps/), [netcup](https://www.netcup.com/en/server/vps).
- Meta: [precios](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing),
  [límites](https://developers.facebook.com/documentation/business-messaging/whatsapp/messaging-limits),
  [política](https://whatsappbusiness.com/es-la/policy/),
  [Embedded Signup](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/overview),
  [Tech Provider](https://developers.facebook.com/documentation/business-messaging/whatsapp/solution-providers/get-started-for-tech-providers),
  [QR](https://developers.facebook.com/documentation/business-messaging/whatsapp/qr-codes).
- Telegram: [changelog de la Bot API](https://core.telegram.org/bots/api-changelog),
  [términos para bots](https://telegram.org/tos/bot-developers).
- Google: [cuotas de Calendar](https://developers.google.com/workspace/calendar/api/guides/quota),
  [verificación](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification),
  [Addendum](https://cloud.google.com/terms/data-processing-addendum).
- AEPD: [contratos de encargo](https://www.aepd.es/es/node/813),
  [pymes y Facilita](https://www.aepd.es/derechos-y-deberes/cumple-tus-deberes/directrices-de-aplicacion/pymes).
