# Seguridad y secretos

Resumen de las defensas de la plataforma: dónde viven los secretos y cómo se cifran, cómo se autentican los webhooks, qué puede hacer cada rol de base de datos, qué datos personales no pueden salir de la base y qué comprueba CI. Lee esta página para saber qué protege cada capa; el aislamiento entre negocios (RLS) está en [Tenants y RLS](tenants-y-rls.md) y el procedimiento de rotación en [Rotar secretos](../procedimientos/rotar-secretos.md).

## Dónde vive cada secreto

| Secreto | Dónde | Cómo |
|---|---|---|
| Secretos de canal de cada negocio (`app_secret`, `access_token`, `verify_token`, `bot_token`, `webhook_secret`) | Tabla `tenant_secret` | Cifrados con Fernet, nunca en claro en la base |
| Secretos de la plataforma (`DJANGO_SECRET_KEY`, `SECRETS_ENCRYPTION_KEY`, URLs de base de datos, tokens de los bots de demo y de avisos, `SENTRY_DSN`, `HEALTHCHECKS_*`) | `.env` del servidor | Fuera de git y de la imagen. `SECRETS_ENCRYPTION_KEY` tampoco va en los backups (copia en el gestor de contraseñas de la persona) |
| Contraseñas del panel y TOTP | `auth_user`, `otp_totp_totpdevice` | Hash de Django; tablas sensibles |

Nunca hay credenciales en git ni en logs. En producción, `settings.py` rechaza arrancar si `DJANGO_SECRET_KEY` o `SECRETS_ENCRYPTION_KEY` conservan el valor de ejemplo, o si esta última no contiene claves Fernet válidas. Variables completas: [Variables de entorno](../referencia/variables-entorno.md).

## Cifrado de secretos de canal

`apps/backend/src/autobot/tenancy/crypto.py` usa `MultiFernet` con las claves de `SECRETS_ENCRYPTION_KEY` (separadas por comas): **cifra con la primera y descifra con cualquiera**. Eso permite rotar sin parada. `encrypt` serializa el mapa a JSON y devuelve el token; `decrypt` lanza `SecretsUnreadable` (sin detalles) si el token o el formato no son válidos.

- Se escribe solo vía `tenancy.store` (`channel_secrets.py`), validando con `WhatsAppSecrets`/`TelegramSecrets`, en la conexión `owner`, y se audita únicamente el **nombre de los campos** (`tenant.secrets`), nunca los valores.
- Un secreto ilegible desactiva el canal principal de ese negocio sin degradarlo ni afectar a los demás ([Config y registro](config-y-registro.md)).
- La API del panel no devuelve secretos, solo si están presentes.
- **Re-cifrado:** `manage.py tenant_secrets_reencrypt` descifra y vuelve a cifrar todas las filas con la primera clave, en una transacción: si una fila es ilegible, se revierte todo. Cada fila deja una auditoría con `reencrypted: true`. Los backups antiguos no se re-cifran: restaurarlos exige las claves con que se hicieron.
- **La clave no viaja con los datos (ADR-021).** El snapshot de restic lleva el `.env` sin `SECRETS_ENCRYPTION_KEY`; la custodia la persona fuera del servidor y `restore.sh` la exige explícitamente y comprueba que descifra los secretos restaurados ([Backups](../procedimientos/backups.md), [Rotar secretos](../procedimientos/rotar-secretos.md)).
- Los logs protegen además los valores conocidos: `redact` sustituye por `[REDACTED]` los secretos configurados y los de los negocios del registro cargado.

## Firma de los webhooks

Cada webhook comprueba su autenticidad **antes** de parsear el cuerpo (y tras limitar el tamaño a 256 KB), con comparación en tiempo constante (`hmac.compare_digest`):

- **WhatsApp** (`autobot/channels/whatsapp/adapter.py`, `verify`): `X-Hub-Signature-256` = HMAC-SHA256 del cuerpo con `app_secret`. El `GET` de verificación de Meta comprueba `verify_token`.
- **Telegram** (`autobot/channels/telegram/adapter.py`, `verify`): el `secret_token` registrado con `setWebhook` vuelve en una cabecera y se compara con `webhook_secret`.
- Lo mismo aplica a las puertas de demo y al bot de avisos ([Bot de demo](bot-de-demo.md), [Bot de dueños](bot-de-duenos.md)); sin su secreto configurado responden 404.
- Una firma inválida cuenta en un límite por IP (`channels/ratelimit.py`) y no revela por qué falló.

Cambios en cifrado, secretos o firma de webhooks requieren aprobación humana explícita.

## Roles de base de datos

Tres roles con permisos distintos (declarados en `apps/backend/src/autobot/db/grants.py`):

| Rol | Uso | Permisos |
|---|---|---|
| `fp_app` | `web` público y workers (conexión `default`) | Sujeto a RLS. Lee las tablas de configuración pero no las escribe; sin acceso a `audit_event`, `dataset_library_version` ni a las tablas de auth/sesión/OTP; no puede escribir en `tenant`; en `ops_alert` no borra. |
| `fp_owner` | Migraciones, comandos de operación, `tenancy.store` y servicios del panel | Dueño de las tablas, `BYPASSRLS`. Siempre con `.using("owner")` explícito. Solo `web-panel` (y los comandos `manage.py` de operación, que corren en `web-panel`) reciben `DB_OWNER_URL`; ni el `web` público ni los workers tienen alias `owner` ([ADR-020](adr/ADR-020-api-del-panel-aparte.md)). |
| `fp_readonly` | Consola SQL del panel (solo `web-panel`) | `NOBYPASSRLS`, solo `SELECT`, `temp_file_limit` de 256 MB por sesión; revocado sobre `SENSITIVE_TABLES` (incluidas `audit_event` y `tenant_document_version`). Es la barrera real de la consola; el ámbito por negocio es solo una comodidad. |

`grants.statements()` es la **única fuente de verdad** de los permisos; `apply_grants` (`manage.py apply_grants`) los reaplica tras cada migración que crea tablas, en cada despliegue y tras cada restauración (`pg_restore --no-acl` los pierde). Las tablas sensibles (`SENSITIVE_TABLES`: secretos, sesiones, TOTP, invitaciones, eventos y sesiones de demo y de dueños, `owner_link`…) no son legibles por la consola SQL. Una función `SECURITY DEFINER` (`purge_platform_history`) permite la purga de `ops_alert` y `audit_event` sin dar `DELETE` a `fp_app`, y limita el corte a un año.

Toda tabla nueva con RLS lleva las políticas `tenant_isolation` y `readonly_all`; toda tabla nueva sensible se añade a `SENSITIVE_TABLES`. Ver [Migraciones y RLS](../desarrollo/migraciones-y-rls.md).

## Aislamiento de contenedores y de red

Detalle y motivos en [ADR-020](adr/ADR-020-api-del-panel-aparte.md):

- **Credenciales por servicio:** el `web` público y los workers solo tienen `fp_app`. La API del panel corre en `web-panel`, sin puerto publicado ni red de borde, y es el único proceso de larga vida con `fp_owner` y `fp_readonly`.
- **Redes de Compose separadas** (`edge`, `panel`, `egress`, `data`, `logs`): Caddy solo alcanza `web`; la base de datos y VictoriaLogs están en redes `internal`, sin salida a internet.
- **Contenedores:** `cap_drop: [ALL]`, `no-new-privileges`, sistema de ficheros de solo lectura y `/tmp` en `tmpfs` con `noexec,nosuid`. Excepciones justificadas: `panel` conserva `NET_BIND_SERVICE` (el binario de Caddy lo exige) y `victorialogs` corre como root sin capacidades (el volumen se crea de root).
- **Host:** UFW solo abre 22/80/443 y `autobot-docker-firewall.service` descarta en `DOCKER-USER` cualquier conexión a un puerto publicado de Docker que no sea 80/443 (UFW no filtra lo que publica Docker). `unattended-upgrades` aplica también las actualizaciones de Docker y reinicia de madrugada si hace falta; SSH limita `MaxAuthTries` y `LoginGraceTime` ([servidor.md](../procedimientos/servidor.md)).
- **Backups:** el servidor solo sube; borrar snapshots exige otra credencial que no está en él ([Backups](../procedimientos/backups.md), ADR-021).
- Una prueba de CI (`tests/repo/test_compose_prod.py`) y `make check-prod-config` vigilan estas propiedades.

## Datos personales fuera de logs y trabajos

- **Trabajos de la cola**: reciben solo ids (`event_id`, `tenant_id`, `notification_id`). Nunca teléfonos, ids de usuario ni datos personales en argumentos.
- **Candados**: se construyen con hashes (`contact_hash`, `demo_user_lock`, `owner_chat_lock` en `autobot/runtime/locks.py`), no con identificadores en claro.
- **Logs**: `PrivacyFilter` redacta secretos, cabeceras de autorización, tokens de bot y teléfonos (solo quedan los 4 últimos dígitos); los identificadores de contexto son ids opacos. Las excepciones solo registran su tipo en las rutas sensibles.
- **Sentry**: `before_send` descarta peticiones, variables locales y texto de excepciones.
- **Estado de Calendar y salud** (`ops/state.py`): cuentas y marcas de tiempo, nunca ids de calendario ni de cliente.
- **Demo**: lo que se recibe de un desconocido no se guarda (WhatsApp) o se vacía (Telegram); ver [Bot de demo](bot-de-demo.md#quien-puede-usar-la-demo).
- **Retención y borrado**: plazos, exportación y olvido de contactos en [Retención y borrado de datos](../procedimientos/retencion-rgpd.md).

## Términos prohibidos en CI

El trabajo `forbidden-terms` de CI ejecuta `deploy/scripts/check-forbidden-terms.py`: falla si algún fichero versionado contiene el nombre de un cliente real. `deploy/ci/forbidden-terms.sha256` guarda solo huellas SHA-256, nunca los términos en claro, de modo que filtrar el fichero no revela nada. El script normaliza cada secuencia de 1 a 4 palabras de cada fichero, la hashea y compara; si hay coincidencia imprime el fichero, no el término. Los datos de clientes reales no se suben a git (`var/tenants/` y `var/datos/` están ignorados).

## Cadena de suministro y análisis en CI

CI no usa secretos propios: todos los jobs corren con `contents: read` y solo `image` añade `packages: write`. Qué se escanea y cómo tratar un fallo:

| Control | Qué hace | Si falla |
|---|---|---|
| Acciones fijadas por SHA | Toda `uses:` lleva el SHA de 40 caracteres y un comentario con la versión; las subidas se hacen a mano (no se usa Dependabot) | Para subir una acción, resuelve el SHA real del tag (`git ls-remote https://github.com/<propietario>/<repo> 'refs/tags/<tag>^{}'`) y conserva el comentario |
| Imágenes base por digest | Los `FROM` de `apps/backend/Dockerfile` y `apps/panel/Dockerfile` llevan `tag@sha256:…`; al subir una imagen se cambian tag y digest a la vez | No inventes el digest: resuélvelo con `docker buildx imagetools inspect <imagen:tag>` |
| `secrets-scan` (gitleaks) | Busca credenciales en todo el historial. `.gitleaks.toml` solo permite, por ruta concreta, la clave Fernet de ejemplo, tokens falsos de tests y el bundle de Mermaid | Un secreto real: revócalo y rótalo primero ([Rotar secretos](../procedimientos/rotar-secretos.md)); borrarlo del historial no basta. Un valor de ejemplo: añade una excepción por ruta, nunca global |
| `pnpm audit` | Dependencias de producción del panel, falla desde severidad alta | Actualiza la dependencia; si no hay arreglo, decláralo en el PR con la justificación antes de ignorarlo |
| `pip-audit` | Dependencias bloqueadas del backend | Igual que el anterior |
| `dockerfile-lint` | `hadolint` (Dockerfile) y `actionlint` (workflows). Una excepción de hadolint va en línea (`# hadolint ignore=DLxxxx`) con motivo | Corrige la regla; ignórala solo si es un falso positivo |
| Trivy sobre las dos imágenes | Antes de publicar: falla con HIGH o CRITICAL que tengan arreglo (`--ignore-unfixed`) | Reconstruye con la base actualizada (sube el digest) o la dependencia afectada; no se publica nada hasta que pase. Excepción solo en `.trivyignore`, con motivo y caducidad |
| CodeQL (`codeql.yml`) | Python y JavaScript/TypeScript; único job con `security-events: write` | Revisa las alertas en la pestaña Security del repositorio |

Los binarios de gitleaks, hadolint, actionlint y Trivy se descargan con versión y SHA-256 fijos en el propio workflow, y la descarga falla si el hash no coincide. Al subir una versión, cambia ambos valores.

## Auditoría y acceso al panel

- Toda escritura del panel y de los comandos de operación se registra en `audit_event` (`autobot/ops/audit.py`), que rechaza claves con forma de secreto en sus `details`.
- El panel solo es accesible por túnel SSH, con contraseña más TOTP, límite de intentos y CSRF; la API devuelve 404 a cualquier petición que llegue del Caddy público. Detalle en [Panel](panel.md).

## Cuentas externas y acceso

La plataforma depende de cuentas de terceros que, si alguien entra en ellas, dan acceso a producción o a los datos aunque el servidor esté bien protegido. Este repo es público: aquí solo va la lista de tipos de cuenta y las reglas; los datos concretos (usuarios, ids, URLs) viven en el gestor de contraseñas de la persona que opera.

| Cuenta | Qué permite | Regla |
|---|---|---|
| GitHub | Cambiar el código, aprobar despliegues (entorno `production`) y leer los secretos de CI | Segundo factor. `main` con un ruleset que impide borrarla y forzar pushes; `production` limitado a `main` y con aprobación |
| Proveedor de la VPS | Consola de emergencia, reinstalar, borrar la máquina y sus backups | Segundo factor |
| Proveedor de los backups (S3) | Leer o borrar los snapshots | Segundo factor en la cuenta raíz; el servidor usa una credencial sin borrado y la purga otra distinta (ADR-021) |
| Proveedor DNS | Redirigir los webhooks a otra máquina | Segundo factor |
| healthchecks.io | Silenciar los avisos de worker colgado y de backups parados | Segundo factor |
| Meta Business | Números de WhatsApp, apps, tokens y facturación | Segundo factor; revisar quién tiene acceso a cada app y cuenta de WhatsApp |
| Google Cloud | La cuenta de servicio de Calendar | Segundo factor |
| Telegram (cuenta de la persona) | BotFather (tokens de los bots) y el chat de avisos | Segundo factor (contraseña de Telegram) |

En el gestor de contraseñas, como entradas separadas: `SECRETS_ENCRYPTION_KEY`, la contraseña de restic, las dos credenciales S3, la clave SSH de operación, los tokens de los bots, las URLs de healthchecks y los códigos de recuperación de cada segundo factor. Si el TOTP del panel está en el mismo gestor que su contraseña, los dos factores caen juntos: mejor en una app de autenticación aparte. Una revisión trimestral comprueba que todo sigue así ([mantenimiento](../procedimientos/mantenimiento.md#calendario)).

## Dónde está el código

- `apps/backend/src/autobot/tenancy/crypto.py`, `tenancy/store/channel_secrets.py`, `management/commands/tenant_secrets_reencrypt.py`.
- `apps/backend/src/autobot/channels/whatsapp/adapter.py`, `channels/telegram/adapter.py`, `channels/views.py`, `channels/ratelimit.py`.
- `apps/backend/src/autobot/db/grants.py`, `db/router.py`, `management/commands/apply_grants.py`.
- `apps/backend/src/autobot/ops/logging.py`, `ops/audit.py`, `runtime/locks.py`.
- `deploy/scripts/check-forbidden-terms.py`, `deploy/ci/forbidden-terms.sha256`.
- Tests: `apps/backend/tests/platform/tenancy/test_crypto.py`, `test_secrets_reencrypt.py`, `tests/platform/ops/test_db_roles.py`.

## Relacionado

- [Tenants y RLS](tenants-y-rls.md), [Config y registro](config-y-registro.md), [Panel](panel.md), [Observabilidad](observabilidad.md).
- [Rotar secretos](../procedimientos/rotar-secretos.md) y [Incidente de seguridad](../incidencias/incidente-seguridad.md).
