# Panel de Autobot: implementación

Plan de trabajo para llevar a cabo [`DESIGN.md`](DESIGN.md). Está pensado para que un
agente programador lo siga **tarea a tarea, sin tomar decisiones de diseño**: el diseño
explica qué se construye y por qué, y este documento dice en qué orden, qué ficheros se
tocan y cuándo se da una tarea por terminada.

---

## 0. Cómo trabajar con este documento

### 0.1. Antes de empezar

1. Lee [`CLAUDE.md`](../../CLAUDE.md) y [`DESIGN.md`](DESIGN.md) enteros.
2. Si algo de este documento contradice el diseño, gana el diseño. Avisa de la
   contradicción a la persona antes de seguir.
3. Lee el código que vas a tocar antes de cambiarlo. Las rutas de este documento
   corresponden al repo del 2026-11-03 (commit `cab8665`). Si algo ha cambiado desde
   entonces, adapta la tarea y dilo.
4. **Si te encuentras con una decisión que este documento no fija, no la tomes tú:
   pregunta.**

### 0.2. Reglas

- **Una tarea, un commit.** El commit lleva el código, los tests y la documentación
  afectada. El mensaje va en inglés y explica el porqué.
- **No hagas commit ni push sin que la persona lo pida.** Al terminar una tarea, deja el
  árbol listo, resume lo que has hecho y pide permiso.
- **Tareas ⚠️ APROBACIÓN** (RLS, roles, permisos, borrados, cifrado, secretos, webhooks o
  infraestructura): antes de escribir código, presenta un resumen concreto (el SQL, los
  ficheros de compose o Caddy, los scripts) y **espera un sí explícito**.
- **Nunca ejecutes nada contra producción** ni despliegues. Los pasos que tiene que dar la
  persona van en `docs/puesta-en-marcha.md`, sección "Panel".
- **No inventes** credenciales, ids ni resultados de verificaciones reales.
- **Idiomas:** código y comentarios en inglés; textos del panel y documentación en
  español. Sin comentarios obvios.
- **CI en verde al final de cada tarea.** El proyecto está en desarrollo temprano y no hay
  nada desplegado, así que los commits intermedios no tienen que poder desplegarse.
  - Si una tarea no puede dejar un **job** de CI en verde porque depende de una tarea
    posterior, se puede desactivar ese job de forma temporal, con un comentario
    `# TEMPORARY(Tnn): <motivo>` que diga en qué tarea se reactiva, y avisando a la
    persona.
  - Nunca se desactivan ni se marcan como `skip` tests concretos.
- **Comandos nuevos:** cada comando o target de `make` nuevo se documenta en
  `docs/comandos.md` (DESIGN §12) en la misma tarea.

### 0.3. Comandos de verificación

| Ámbito | Comando |
|---|---|
| Backend (siempre) | `make check` (ruff, formato, mypy, import-linter, pytest) |
| Migraciones | `uv run python manage.py makemigrations --check --dry-run && uv run python manage.py lintmigrations` |
| Frontend (desde T23a) | `make panel-check` |
| OpenAPI (desde T14) | `make api && git diff --exit-code panel/openapi.json panel/src/api/schema.d.ts` |
| Local completo (desde T08c) | `make dev-bootstrap` (la primera vez) o `make up`; `make dev-activity`; `make panel-dev` |

Las bases locales creadas antes de T00b necesitan `make db-roles`, o directamente
`make dev-reset`.

### 0.4. Definición de terminado (todas las tareas)

- [ ] Criterios de aceptación cumplidos y cubiertos por tests.
- [ ] `make check` en verde, y `make panel-check` si la tarea toca frontend.
- [ ] Documentación al día: `README`, `docs/`, `docs/comandos.md`, `CLAUDE.md` y los ADR.
- [ ] Ninguna referencia muerta a lo eliminado. Compruébalo con `grep -rn` sobre
      `src tests tools docs deploy Makefile Dockerfile compose*.yaml Caddyfile CLAUDE.md README.md .github`.
- [ ] Si hay UI: probada en el navegador (`make up`, `make dev-activity`, `make panel-dev`),
      con el camino principal, el estado vacío y el de error. Si no puedes probarla, dilo.
- [ ] Pasos manuales nuevos anotados en `docs/puesta-en-marcha.md`.

---

## 1. Mapa de tareas

| Fase | Tarea | Título | Depende de | ⚠️ |
|---|---|---|---|---|
| 0 | T00 | ADR-008, ADR-009, CLAUDE.md y `docs/comandos.md` | — | ⚠️ |
| | T00b | Permisos reproducibles (`db_grants` y `apply_grants`); `fp_readonly` en `init-roles` | T00 | ⚠️ |
| 1 · Fuera el Admin | T01 | `audit_event`, `ops.actions` y comandos de resolución | T00b | ⚠️ |
| | T02 | Eliminar el Django Admin | T01 | |
| 2 · Config en BD | T03 | Tablas de config versionada | T02 | ⚠️ |
| | T04 | Cifrado de secretos | T03 | ⚠️ |
| | T05 | Plantillas de pack; demos fuera de `tenants/` | T02 | |
| | T06a | Renombrado mecánico `TenantFile`→`TenantDocument`, `.file`→`.document` | T05 | |
| | T06b | `TenantSource`, formato de directorio y datasets materializados | T06a | |
| | T06c | Fuente BD, recarga por revisión, `registry_scope` y fixtures de tests | T03, T04, T06b | |
| | T07 | `tenancy.store`, `tenancy.activation` y `ops.status` | T06c | ⚠️ |
| | T08a | Comandos `tenant_config`, `tenant_dataset`, `seed_demos`, `tenant_status` y purga ampliada | T07 | ⚠️ |
| | T08b | Fuera `tenants/`, `secrets.yaml` y `sync_tenants`; `manage.sh`, `prod-manage` y `tenant-push` | T08a | ⚠️ |
| | T08c | Automatización local: `dev-bootstrap`, `dev-reset`, `tenant-import`, worker con recarga, `HOST`, `ngrok` | T08b | |
| | T09 | Herramientas `bus-*` sobre `datos/` | T08b | |
| 3 · Observabilidad | T10 | Módulo de costes e índices | T02 | |
| | T11 | `ops_alert`, `collect` y `sync_alerts`, retención | T02 | ⚠️ |
| | T12 | Muestras de sistema, estado de backups y despliegues | T11 | ⚠️ |
| | T13 | VictoriaLogs y envío de logs | T02 | ⚠️ |
| | T13b | `seed_dev_activity` (`make dev-activity`) | T08c, T11, T12 | |
| 4 · API | T14 | Base de la API: ninja, login, router por modelo, puerta, OpenAPI y `make api` | T02, T08c | ⚠️ |
| | T15 | `GET overview` | T07, T10, T11, T12, T14 | |
| | T16a | Packs y tenants: lectura | T15 | |
| | T16b | Tenants: escritura | T16a | ⚠️ |
| | T17 | Actividad, contactos y avisos | T11, T14 | |
| | T18 | Incidencias, alertas, trabajos y auditoría | T01, T11, T14 | |
| | T19 | Logs | T13, T14 | |
| | T20 | Sistema | T12, T14 | |
| | T21 | Catálogo de datos y consultas guardadas | T14 | ⚠️ |
| | T22 | Consola SQL: alias `readonly` y política `readonly_all` | T21 | ⚠️ |
| 5 · Frontend | T23a | Andamiaje de `panel/`: herramientas, CI, `make fix`, `panel-dev` y `panel-check` | T14 | |
| | T23b | Layout, login, cliente de la API y componentes comunes | T23a | |
| | T24 | Contenedor `panel`, compose, imagen, despliegue y `panel-tunnel` | T23b | ⚠️ |
| | T24b | Despliegue simple: `ensure-env`, `deploy` sin SHA, `rollback` y aviso de éxito | T24, T12 | ⚠️ |
| | T25 | Pantalla Resumen | T15, T23b | |
| | T26 | Clientes: lista y ficha (todo salvo editar) | T16a, T17, T23b | |
| | T27 | Editor de config, historial, estado y secretos | T16b, T26 | |
| | T28 | Asistente de alta | T27 | |
| | T29 | Actividad e Incidencias | T17, T18, T23b | |
| | T30 | Logs | T19, T23b | |
| | T31 | Datos: catálogo, tabla y consulta | T21, T22, T23b | |
| | T32 | Sistema y Auditoría | T18, T20, T23b | |
| 6 · Cierre | T33 | Repaso final de la documentación | todas | |

---

## 2. Tareas

### T00 · ADR-008, ADR-009, CLAUDE.md y `docs/comandos.md` ⚠️

**Objetivo:** dejar las decisiones por escrito antes de tocar código.

**Cambios:**

- **`docs/adr/ADR-008-panel.md`** (aceptada). Recoge DESIGN §3, §6.2, §7, §8.2, §10 y
  §12:
  - SPA servida por Caddy en `panel`, con proxy al mismo origen y acceso por túnel;
  - enrutado de BD por modelo (§3.3);
  - sesión con OTP y `Secure=False`, justificado por el túnel;
  - fin del Django Admin;
  - VictoriaLogs con envío desde la app y métricas leyendo `/proc`;
  - `fp_readonly` y `readonly_all`;
  - alternativas descartadas: Next.js, Vercel, un BFF aparte, Beszel, Netdata,
    Prometheus, Loki y el router por petición.
- **`docs/adr/ADR-009-config-en-bd.md`.** Recoge DESIGN §4 y §5:
  - la BD como fuente de verdad, con versiones inmutables y `config_revision`;
  - tablas con `tenant_id` y sin RLS, con solo `SELECT` para `fp_app`, y por qué;
  - `MultiFernet`, y por qué no un `.env` ni una clave por cliente;
  - plantillas de pack y `seed_demos`;
  - datasets en BD;
  - baja y purga;
  - `apply_grants`;
  - alternativa descartada: commits a git desde el panel.
- **ADR-001, ADR-002 y ADR-005:** añade una línea "Modificada por ADR-00X" en la sección
  correspondiente.
- **`CLAUDE.md`:**
  - Arquitectura: los contenedores pasan a ser `caddy, web, worker, db, panel,
    victorialogs`. Config y datasets en PostgreSQL (ADR-009); secretos de canal cifrados
    en la BD; secretos de la plataforma en `.env`.
  - Packs: "cada pack nuevo incluye su plantilla en `src/packs/<pack>/template/` (crea su
    demo) y su escenario".
  - Reglas:
    - `fp_owner` solo lo usan migraciones, comandos de operación, `tenancy.store` y los
      servicios del panel, siempre con `.using("owner")` explícito;
    - toda tabla nueva con RLS lleva `tenant_isolation` y `readonly_all`;
    - toda tabla nueva sensible se añade a `SENSITIVE_TABLES` en `db_grants.py`;
    - los permisos se declaran en `db_grants.py`, nunca solo en una migración;
    - las tablas `tenant_document_version`, `tenant_dataset_version`, `tenant_secret`,
      `audit_event` y `ops_alert` llevan `tenant_id` sin RLS por diseño (ADR-009).
  - Panel: frontend en `panel/` (TypeScript, Biome, Vitest); la API del panel solo es
    accesible por el túnel.
  - Referencias: añade "Comandos: `docs/comandos.md`".
- **`docs/comandos.md`** (nuevo): la tabla de los comandos `make` y `manage.py` que
  existen hoy, con una línea por comando. Cada tarea posterior la amplía.

**Aceptación:**

- Los dos ADR existen y enlazan a `docs/panel/DESIGN.md`.
- `CLAUDE.md` ya no presenta `tenants/<slug>/`, `secrets.yaml` ni el Django Admin como
  estado actual.

---

### T00b · Permisos reproducibles ⚠️

**Objetivo:** DESIGN §5. Hoy el `REVOKE` de `0002` se pierde al restaurar un backup.

**Cambios:**

- **`deploy/postgres/init-roles.sh`:**
  - crea y actualiza `fp_readonly` con
    `LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD :'ro_pw'`,
    leyendo `FP_READONLY_PASSWORD` con `\getenv`;
  - `GRANT CONNECT` en cada base y `GRANT USAGE ON SCHEMA public`.

  Añade `FP_READONLY_PASSWORD` en los sitios donde ya se pasan las otras contraseñas:

  | Fichero | Valor |
  |---|---|
  | `compose.yaml` (`db`) | `fp_readonly` |
  | `compose.prod.yaml` (`db`) | `${FP_READONLY_PASSWORD:?Set FP_READONLY_PASSWORD}` |
  | `.github/workflows/ci.yml` (paso "Database roles") | `fp_readonly` |
  | `deploy/restore-test.sh` | el que corresponda |
  | `tools/check_prod_config.py` (entorno sintético) | el que corresponda |

- **`src/autobot/db_grants.py`:**

  ```python
  SENSITIVE_TABLES: tuple[str, ...] = ("auth_user", "django_session", "otp_totp_totpdevice")
  def statements() -> list[str]  # ordered, idempotent SQL; later tasks extend it
  def apply(connection) -> None  # runs statements() in one transaction
  ```

  Contenido inicial de `statements()`:
  1. `REVOKE INSERT, UPDATE, DELETE ON tenant FROM fp_app` (el de `0002`);
  2. `GRANT SELECT ON ALL TABLES IN SCHEMA public TO fp_readonly`;
  3. `ALTER DEFAULT PRIVILEGES FOR ROLE fp_owner IN SCHEMA public GRANT SELECT ON TABLES TO fp_readonly`;
  4. `REVOKE ALL ON <cada SENSITIVE_TABLE> FROM fp_readonly`.

  Como las tablas de `auth` las crea una migración de terceros, usa `DO $$ … IF EXISTS …`
  para no fallar en una base a medio migrar.
- **`src/autobot/management/commands/apply_grants.py`**: `apply(connections["owner"])` e
  imprime "Permisos aplicados".
- **Migración `00xx_apply_grants`:** `RunPython` que llama a `db_grants.apply` con la
  conexión del `schema_editor`, con un reverso que no hace nada. Va después de las
  migraciones de `auth` y `sessions` (`run_before` o `dependencies`).
- **`deploy/deploy.sh`:**
  - tras `up -d --wait db`, ejecuta
    `docker compose … exec -T db bash /docker-entrypoint-initdb.d/init-roles.sh`. El
    script ya está montado ahí; pásale las variables que necesita;
  - tras `migrate`, `run --rm web python manage.py apply_grants`.

  Sigue pasando `shellcheck`.
- **`deploy/restore.sh`:** tras `pg_restore`, ejecuta `init-roles` y `apply_grants` (con
  la imagen del SHA restaurado).
- **`deploy/restore-test.sh`:** comprueba con
  `SELECT has_table_privilege('fp_app','tenant','INSERT')` que es `f`, y que
  `fp_readonly` no puede leer `auth_user`.
- **`Makefile`:** `db-roles` ejecuta `docker compose exec -T db bash /docker-entrypoint-initdb.d/init-roles.sh`
  con las variables de `compose.yaml`.

**Tests:**

- `tests/integration/test_db_roles.py`: `fp_readonly` existe y no tiene `BYPASSRLS`; no
  puede leer `SENSITIVE_TABLES`; `fp_app` no puede escribir en `tenant`.
- `apply_grants` dos veces seguidas no falla, y después de revocar un permiso a mano lo
  vuelve a dejar como estaba.

**Docs:** `docs/comandos.md` (`apply_grants`, `make db-roles`), `docs/runbooks/06-restaurar.md`
y `servidor.md`.

---

### T01 · Auditoría, `ops.actions` y comandos de resolución ⚠️

**Objetivo:** sacar del Admin la lógica de resolución y la auditoría.

**Cambios:**

- **`src/autobot/ops/models.py`** (nuevo, importado desde `src/autobot/models.py`):

  ```python
  class AuditEvent(models.Model):
      id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
      at = models.DateTimeField(default=timezone.now, db_index=True)
      actor = models.CharField(max_length=150)
      action = models.CharField(max_length=64, db_index=True)
      tenant_id = models.UUIDField(null=True, blank=True, db_index=True)  # no FK: survives purge
      target_type = models.CharField(max_length=64, blank=True, default="")
      target_id = models.CharField(max_length=200, blank=True, default="")
      summary = models.TextField()
      details = models.JSONField(default=dict)
      class Meta:
          db_table = "audit_event"
  ```

  Migración: crea la tabla y llama a `db_grants.apply`. En `db_grants`, añade
  `REVOKE ALL ON audit_event FROM fp_app`.
- **`src/autobot/ops/audit.py`:**
  `record(*, actor, action, summary, tenant_id=None, target_type="", target_id="", details=None) -> None`.
  Escribe con `using("owner")` dentro de su propio `transaction.atomic(using="owner")`.
  Lanza `ValueError` si alguna clave de `details`, a cualquier profundidad, está en el
  conjunto fijo de DESIGN §6.5.
- **`src/autobot/ops/actions.py`:** mueve aquí, sin cambiar el comportamiento,
  `OutboundAdmin.resolve` y `JobAdmin.retry` de `src/autobot/admin.py`.

  ```python
  @dataclass(frozen=True)
  class Result: ok: bool; message: str
  def can_mark_sent(message: OutboundMessage) -> tuple[bool, str]
  def can_resend(message: OutboundMessage, *, db_tenant: Tenant) -> tuple[bool, str]
  def can_retry(job: ProcrastinateJob) -> tuple[bool, str]
  def mark_sent(outbound_id: UUID, *, actor: str) -> Result
  def resend(outbound_id: UUID, *, actor: str) -> Result
  def retry_job(job_id: int, *, actor: str) -> Result
  ```

  - Las funciones `can_*` contienen las reglas que hoy están en línea en `admin.py`:
    `unknown` de más de 10 min; payload, tenant y canal presentes; no `offboarded`; no
    `ambiguous`; `send_message` y `send_notification` no se reintentan.
  - `mark_sent`, `resend` y `retry_job` vuelven a comprobar bajo `select_for_update`,
    conservan el `transaction.on_commit` con `_deferrer` y auditan
    `outbound.mark_sent`, `outbound.resend` y `job.retry`.
  - Mientras exista el Admin, `admin.py` llama a estas funciones.
- **Comandos:**
  - `outbound_resolve <uuid> (--mark-sent | --resend) --confirm`: sin `--confirm`
    explica el riesgo y sale con código 1. Actor: `command:outbound_resolve`.
  - `job_retry <id>`.
- **`tests/isolation/test_isolation.py`:** añade un conjunto explícito
  `NO_RLS_TABLES = {"audit_event"}` que se une a `PLATFORM_TABLES` en el test de tablas.
  Lleva un comentario que remite a ADR-009.

**Tests:**

- `tests/integration/test_actions.py` cubre los casos que hoy prueba `test_admin.py` para
  resolver y reintentar. Adáptalos.
- `fp_app` no puede leer `audit_event`.
- `audit.record` rechaza claves prohibidas, también anidadas.
- Para cada comando, un caso feliz y uno rechazado.

**Docs:** runbooks `05-envios-unknown.md` y `03-cola-y-latido.md`, y `docs/comandos.md`.

---

### T02 · Eliminar el Django Admin

**Objetivo:** DESIGN §11.

**Cambios:**

- **`src/config/settings.py`:**
  - quita `django.contrib.admin`, `django.contrib.messages` y `django.contrib.staticfiles`;
  - quita `MessageMiddleware`, `XFrameOptionsMiddleware`, `WhiteNoiseMiddleware` y
    `AdminDatabaseMiddleware`;
  - quita `DATABASE_ROUTERS`, `STATIC_URL`, `STATIC_ROOT`, `STORAGES` y los context
    processors de mensajes;
  - quita `TEMPLATES` si nada lo usa; búscalo antes.
- **Borra** `src/autobot/admin.py`, `src/autobot/admin_db.py` y
  `src/autobot/templates/admin/`. Si `templates/` queda vacío, bórralo también.
- **`src/config/urls.py`:** quita `internal` y la importación de `site`. Deja
  `urlpatterns = public`; T14 añade el panel.
- **`pyproject.toml`:** quita `whitenoise` y ejecuta `uv lock`.
- **`Dockerfile`:** quita el `RUN … collectstatic` y su comentario.
- **`Makefile`:** quita `admin-tunnel`.
- **Tests:**
  - borra `tests/integration/test_admin.py` (sus casos de acciones ya están en
    `test_actions.py`);
  - borra o adapta los tests de `admin_db`;
  - ajusta `tests/test_settings.py` si mira `INSTALLED_APPS` o el middleware.
- **Docs:**
  - renombra `docs/runbooks/admin.md` a `docs/runbooks/panel.md`. Por ahora explica que
    aún no hay interfaz web, los comandos de T01 y el alta del operador (se completa en
    T14);
  - actualiza los enlaces a `admin.md` en `puesta-en-marcha.md` y `servidor.md`, y las
    menciones al Admin en ADR-001 y ADR-005 (como historia).

**Aceptación:**

- `grep -rn "contrib.admin\|admin.site\|admin_db\|whitenoise\|collectstatic\|admin-tunnel" src tests Dockerfile pyproject.toml Makefile`
  no devuelve nada.
- `/admin/` responde 404.

---

### T03 · Tablas de config versionada ⚠️

**Objetivo:** el modelo de datos de DESIGN §4.2.

**Cambios:**

- **`src/autobot/tenancy/models.py`:**
  - añade `TenantDocumentVersion`, `TenantDatasetVersion`, `TenantSecret` y
    `ConfigRevision`, con las tablas y columnas de DESIGN §4.2;
  - FK a `Tenant` con `CASCADE` y las restricciones `UniqueConstraint` indicadas;
  - `TenantSecret.tenant = OneToOneField(primary_key=True)`;
  - `ConfigRevision.id = SmallIntegerField(primary_key=True)`;
  - el docstring de `Tenant` pasa a "espejo del documento vigente".
- **Migración:**
  1. crea las tablas;
  2. `RunSQL` con `INSERT INTO config_revision (id, revision, updated_at) VALUES (1, 0, now())`;
  3. `db_grants.apply`.

  En `db_grants`, añade
  `REVOKE INSERT, UPDATE, DELETE ON tenant_document_version, tenant_dataset_version, tenant_secret, config_revision FROM fp_app`
  y `tenant_secret` a `SENSITIVE_TABLES`.
- **`tests/isolation/test_isolation.py`:** añade los tres modelos con FK `tenant` a
  `PLATFORM_MODELS`, con el comentario de ADR-009. `ConfigRevision` no tiene tenant.

**Tests:**

- `fp_app` lee las cuatro tablas y no puede insertar, actualizar ni borrar en ellas.
- `fp_owner` sí puede.
- `fp_readonly` no lee `tenant_secret`.

**Docs:** ADR-009 ya lo cubre.

---

### T04 · Cifrado de secretos ⚠️

**Objetivo:** DESIGN §4.3.

**Cambios:**

- **`pyproject.toml`:** añade `cryptography>=50,<51` como dependencia directa; en
  `uv.lock` ya está la 50.x.
- **`src/config/settings.py`:**
  - `SECRETS_ENCRYPTION_KEYS: list[str]`, leída de `env("SECRETS_ENCRYPTION_KEY", <clave Fernet local fija>)`
    y separada por comas;
  - en `prod`, valida cada clave con `Fernet(key)` y lanza `ImproperlyConfigured` si es
    inválida, sin incluir la clave en el mensaje.
- **`src/autobot/tenancy/crypto.py`:**
  - `encrypt(data: Mapping[str, str]) -> bytes`: JSON compacto con `sort_keys`, cifrado
    con `MultiFernet`;
  - `decrypt(token: bytes) -> dict[str, str]`;
  - `class SecretsUnreadable(Exception)`, con un mensaje fijo y sin detalles.
- **`compose.prod.yaml` (`x-app-env`):**
  `SECRETS_ENCRYPTION_KEY: ${SECRETS_ENCRYPTION_KEY:?Set SECRETS_ENCRYPTION_KEY}`.
- **`tools/check_prod_config.py`:** añade un valor sintético al entorno (una clave Fernet
  válida generada en el momento).
- **`.env.example`:** la variable y cómo generarla. `ensure-env` (T24b) la generará en el
  servidor.
- **`redact()`:** añade las claves de `SECRETS_ENCRYPTION_KEYS`.
- **`manage.py tenant_secrets_reencrypt`:** recifra cada `tenant_secret` con la primera
  clave, en una transacción `owner`, y audita `tenant.secrets` con
  `details={"reencrypted": true}`.

**Tests:**

- Ida y vuelta.
- Rotación: cifrar con A; configurar `B,A`; descifrar; recifrar; configurar solo `B` y
  descifrar.
- Token manipulado → `SecretsUnreadable`, y el mensaje no contiene el token.
- `prod` con una clave inválida → `ImproperlyConfigured`.

**Docs:** `09-rotar-secretos.md` (rotar la clave) y `docs/comandos.md`.

---

### T05 · Plantillas de pack; demos fuera de `tenants/`

**Objetivo:** DESIGN §4.8.

**Cambios:**

- **`src/core/pack.py`:** añade a `Pack`:
  - `template: Path | None = None`;
  - `template_blank: tuple[str, ...] = ()`.

  Cada campo lleva un docstring de una línea.
- **Mueve con `git mv`**, conservando los mismos `id`:

  | Origen | Destino |
  |---|---|
  | `tenants/demo-peluqueria/tenant.yaml` | `src/packs/salon/template/document.yaml` |
  | `tenants/demo-autobuses/tenant.yaml` | `src/packs/bus/template/document.yaml` |
  | `tenants/demo-autobuses/datasets/timetable/**` | `src/packs/bus/template/datasets/timetable/**` |

  Actualiza el comentario de cabecera de cada `document.yaml`.
- **`src/packs/salon/pack.py`:** `template=Path(__file__).parent / "template"` y
  `template_blank=("calendar_id", "contact_phone", "business_name")`.
- **`src/packs/bus/pack.py`:** `template=…` y el `template_blank` que corresponda (revisa
  `BusConfig`; si no hay ningún dato real del demo, `()`).
- **Tests que leen `tenants/demo-*`:** `src/packs/*/tests/test_demo_tenant.py`,
  `tests/test_tenants.py`, los escenarios y `tests/integration/test_demo.py`. Pasan a leer
  la plantilla. Mientras no exista T06b, copian la plantilla a un directorio temporal
  como `<slug>/tenant.yaml` y usan el `load_registry` de directorio actual.
- **`tenants/`** queda con `autocares-ss` (ignorado). Si la carpeta queda vacía en git, no
  pasa nada: `Dockerfile` sigue copiándola hasta T08b, así que crea `tenants/.gitkeep`
  para que el `COPY` no falle y bórralo en T08b.

**Tests:** cada plantilla valida, tiene `demo` y un `id` UUIDv7, y las claves de
`template_blank` existen en su `config_schema`.

**Docs:** `docs/packs/salon.md`, `docs/packs/bus.md` y `docs/runbooks/demo.md`.

---

### T06a · Renombrado mecánico

**Objetivo:** dejar los nombres preparados sin cambiar ningún comportamiento.

**Cambios:**

- Renombrados en `src/`, `tests/` y `tools/`:
  - `TenantFile` → `TenantDocument` (`autobot/tenancy/schema.py` y todos sus usos);
  - `LoadedTenant.file` → `LoadedTenant.document`, en todos sus usos (unos 75).
- Busca con `grep -rn "\.file\b" src tests tools` y revisa cada caso: no todo `.file` es
  `LoadedTenant`.
- Actualiza los docstrings que dicen "tenant.yaml" solo cuando el renombrado lo requiera;
  el resto lo hace T08b.

**Aceptación:** `make check` en verde sin ningún cambio funcional, y `grep -rn "TenantFile" src tests tools`
no devuelve nada.

---

### T06b · `TenantSource`, formato de directorio y datasets

**Objetivo:** que el registro se cargue a partir de una lista de fuentes (DESIGN §4.4 y
§4.9), todavía solo desde directorio.

**Cambios en `src/autobot/tenancy/registry.py`:**

- Tipo de fuente:

  ```python
  @dataclass(frozen=True)
  class TenantSource:
      name: str                                   # slug or directory name (error key)
      document: Any                               # raw TenantDocument
      datasets: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
      secrets: Mapping[str, Any] | None = None    # decrypted raw secrets
      secrets_error: str | None = None
      version: int | None = None
  ```

- **`load_registry(sources: Iterable[TenantSource], packs: Mapping[str, Pack]) -> Registry`**,
  con la semántica de DESIGN §4.4:
  - `Registry.secrets_error` y `problems["secrets.yaml"]` desaparecen;
  - `secrets_error` de una fuente hace que `main_disabled` incluya `"secrets cannot be decrypted"`.
- **`source_from_dir(dir: Path, secrets: Mapping[str, Any] | None = None) -> TenantSource`:**
  - lee `document.yaml` o, si no existe, `tenant.yaml`;
  - lee `datasets/<name>/**` como texto UTF-8, con rutas relativas en POSIX;
  - un error de lectura produce una fuente cuyo documento no valida y queda en `errors`
    con el mensaje de hoy.
- **`sources_from_directory(root: Path, secrets_file: Path | None) -> list[TenantSource]`:**
  un `source_from_dir` por cada subdirectorio, más el `secrets.yaml` de hoy (formato
  slug → secretos).
- **Datasets materializados:** DESIGN §4.4.
  - Una ruta absoluta, con `..` o que no sea texto → degradado con
    `"dataset <name>: invalid path"`.
  - `LoadedTenant.path` desaparece y aparece `version: int | None`.
- **`get_registry()`:** temporalmente sigue con `@cache`, cargando con
  `sources_from_directory(settings.TENANTS_DIR, settings.SECRETS_FILE)`, para que todo
  siga funcionando hasta T06c.

**Tests:** `tests/tenancy/test_registry.py` pasa a usar `sources_from_directory`, y su
helper `load()` se adapta. Añade:

- `document.yaml` y `tenant.yaml` se aceptan los dos;
- un dataset con `..` degrada el tenant;
- un dataset se materializa y `load_data` recibe un directorio con `datasets/<name>/...`;
- `secrets_error` desactiva `main` sin degradar.

---

### T06c · Fuente BD, recarga, fijado y fixtures

**Objetivo:** que web y worker carguen la config desde la BD (DESIGN §4.4).

**Cambios:**

- **`sources_from_database(alias="default") -> tuple[int, list[TenantSource]]`**: una
  transacción de lectura, sin N+1.
  - Lee `revision`.
  - Documento vigente con `DISTINCT ON (tenant_id) … ORDER BY tenant_id, version DESC`.
  - Datasets vigentes por `(tenant_id, name)`.
  - `tenant_secret` descifrado; si falla, `secrets_error`.
- **Caché del registro:**
  - `get_registry()` mantiene `(registry, revision, checked_at)` por proceso.
  - Cada ≥ 2 s (`time.monotonic`) consulta `SELECT revision FROM config_revision WHERE id=1`.
  - Si la revisión cambió, recarga bajo `threading.Lock`; otro hilo que llegue a la vez
    espera y reutiliza el resultado.
  - Si la consulta falla y ya hay un registro, `log.warning` y se sigue con el registro
    en caché. Si es la primera carga, se propaga el error.
- **Funciones:**
  - `reset_registry()`, para tests;
  - `loaded_registry() -> Registry | None`, que nunca carga;
  - `registry_scope()`, un context manager que fija el registro en un ContextVar.
    Dentro, `get_registry()` devuelve el fijado.
- **Fijado del registro:**
  - `autobot.ops.logging.contextual` envuelve la llamada en `registry_scope()`;
  - `src/autobot/tenancy/middleware.py` → `RegistryScopeMiddleware`, el primero de
    `MIDDLEWARE` tras `SecurityMiddleware`.
- **`redact()`** usa `loaded_registry()`. Borra cualquier uso de `get_registry.cache_info()`.
- **`/health`** (`src/autobot/ops/views.py`): mete `get_registry()` dentro del `try` y
  responde 503 si falla.
- **`ops/check.py`:** la alerta `"registry"` se basa solo en `registry.errors`.
- **Tests:**
  - `tests/tenancy/helpers.py`: `seed_db(*docs, secrets=None, datasets=None) -> None`,
    que inserta con `owner` la versión 1 (o la siguiente), el espejo, `tenant_secret`
    cifrado y `config_revision += 1`, y llama a `reset_registry()`;
  - el fixture `tenants` de `tests/integration/conftest.py` usa `seed_db` en lugar de
    escribir YAML y llamar a `sync_tenants`;
  - todo `get_registry.cache_clear()` pasa a `reset_registry()` (hay unos 23).
- **Settings:** `TENANTS_DIR` y `SECRETS_FILE` siguen existiendo hasta T08b, pero solo los
  usa `sources_from_directory` en tests y comandos. `get_registry()` ya no los lee.

**Tests nuevos:**

- fuente BD con documento, dataset y secretos cifrados;
- secretos ilegibles;
- recarga: cambiar `revision` y avanzar el reloj parcheado 2 s → recarga; antes no;
- un fallo de la consulta de revisión mantiene la caché;
- dos hilos a la vez → una sola carga;
- dentro de `registry_scope()` un cambio de revisión no se ve;
- `redact()` no hace ninguna consulta (`django_assert_num_queries(0)`);
- `/health` responde 503 si la BD falla en la primera carga.

---

### T07 · `tenancy.store`, `tenancy.activation` y `ops.status` ⚠️

**Objetivo:** el único camino de escritura (DESIGN §4.5 y §4.6), la lista de comprobación
previa a activar (§9.6) y la salud de un negocio (§7.5).

**Cambios:**

- **`src/autobot/tenancy/store.py`:**

  ```python
  class StoreError(Exception):
      def __init__(self, code: str, message: str, details: list[str] | None = None): ...
  # code ∈ {"validation_error","conflict","not_found","forbidden_change","invalid_status","bad_request"}

  def new_document(*, pack: str, slug: str, name: str, timezone: str,
                   channel_type: Literal["whatsapp","telegram"] | None,
                   demo_description: str | None, config: dict) -> dict
  def create_tenant(*, document: dict, datasets: Mapping[str, Mapping[str, str]] | None = None,
                    secrets: Mapping[str, str] | None = None, actor: str, comment: str,
                    keep_status: bool = False) -> int
  def publish(slug: str, *, document: dict, base_version: int, actor: str, comment: str) -> int
  def rollback(slug: str, *, version: int, actor: str, comment: str) -> int
  def change_status(slug: str, *, action: Literal["activate","pause","resume","offboard"],
                    actor: str, confirm_slug: str | None = None) -> int
  def set_secrets(slug: str, *, secrets: Mapping[str, str], actor: str) -> None
  def import_dataset(slug: str, name: str, files: Mapping[str, str], *, actor: str,
                     comment: str) -> int | None        # None = same sha256, nothing done
  def current_sources(alias: str = "owner") -> list[TenantSource]
  ```

  - Todas las escrituras siguen los pasos 1–6 de DESIGN §4.5, con el `FOR UPDATE` de
    `config_revision`.
  - **`new_document`:** genera `id` UUIDv7 y `public_id` (16 caracteres `[a-z0-9]`, como
    hace hoy `new_tenant`), y añade el bloque `channel` con los ids a `None`. Con
    `demo_description`, crea un demo sin canal.
  - **`create_tenant`:**
    - sin `keep_status`, fuerza `onboarding` para un negocio real y `paused` para un demo;
    - si el pack tiene `load_data` y `datasets` es `None`, copia los datasets de la
      plantilla;
    - adopta la fila espejo si existe sin versiones;
    - si el tenant ya tiene versiones, responde `conflict`.
  - **`publish`:** prohíbe cambiar los seis campos de DESIGN §4.5 (`forbidden_change`).
  - **`rollback`:** usa el contenido de la versión elegida con los seis campos vigentes.
  - **`change_status`:**
    - aplica la tabla de DESIGN §4.6;
    - `activate` exige `confirm_slug == slug` y
      `activation.checklist(slug).blocking == []`. La lista se calcula **antes** de abrir
      la transacción; dentro solo se revalida que el estado sigue siendo `onboarding`;
    - `offboard` exige `confirm_slug == slug`.
  - **`set_secrets`:** responde `bad_request` en un demo. Valida con
    `SECRETS_SCHEMA[channel.type]`, cifra, incrementa la revisión y audita los nombres de
    los campos.
- **`src/autobot/tenancy/activation.py`:**
  `checklist(slug) -> Checklist(items: list[Item], blocking: list[str])`, con los ítems de
  DESIGN §9.6. La salud se fuerza con `health.daily(..., force=True)` sin ninguna
  transacción abierta.
- **`src/autobot/ops/status.py`:**
  `tenant_status(tenant: LoadedTenant, *, open_alerts: Sequence[OpsAlertLike] = ()) -> TenantStatus`,
  con la tabla de DESIGN §7.5. `OpsAlertLike` es un `Protocol` con `severity` y
  `tenant_id`, para no depender de T11.

**Tests** (`tests/tenancy/test_store.py`, `test_activation.py` y `tests/ops/test_status.py`):

- alta, publicación, vuelta atrás y cada transición de estado: versión, espejo, revisión
  y auditoría;
- 409 con `base_version` antigua;
- `forbidden_change` para cada uno de los seis campos;
- error de validación con detalles por campo y sin valores;
- `public_id` repetido;
- alta de `bus` sin datasets → copia los de la plantilla y valida;
- `create_tenant` con `keep_status`;
- `activate` con bloqueos o sin `confirm_slug` → rechazo;
- `offboard` sin confirmar → rechazo;
- `set_secrets` inválidos, válidos y en un demo;
- `import_dataset` inválido, y con el mismo `sha256` → `None`;
- `tenant_status`, un caso por nivel.

---

### T08a · Comandos de config y purga ampliada ⚠️ (borrados)

**Objetivo:** DESIGN §4.6, §4.7 y §4.9.

**Cambios en `src/autobot/management/commands/`:**

- **`tenant_config.py`** (subcomandos con `add_subparsers`):
  - `export <slug> <dir|->`;
  - `import <dir|-> [--secrets <yaml>] [--comment "..."]`: equivale a
    `create_tenant(keep_status=True)` o a `publish` con la `base_version` vigente, más
    `set_secrets` y un `import_dataset` por dataset;
  - `validate --all`: carga `current_sources()` y `load_registry`, imprime los problemas
    y sale con código 1 si alguno no valida.

  El tar de `-` se lee y se escribe en `sys.stdin.buffer` y `sys.stdout.buffer`, y se
  extrae con `filter="data"`.
- **`tenant_dataset.py`:** `export <slug> <name> <dir|->` e
  `import <slug> <name> <dir|-> --comment "..."`. Si no hay cambios, imprime "sin cambios".
- **`seed_demos.py`:** por cada pack de `PACKS` con plantilla, `create_tenant(keep_status=True)`
  si el `id` no tiene versiones. Imprime `created <slug>` o `exists <slug>`.
- **`tenant_status.py`:** `tenant_status <slug> pause|resume|offboard`. Para `offboard`
  pide el slug con `input()`. Actor: `command:tenant_status`.
- **`src/autobot/runtime/privacy.py` → `purge(tenant)`:**
  - se niega si `tenant.status != "offboarded"`, con `CommandError` y un mensaje claro;
  - además de lo de hoy, borra `MetricEvent`, `TenantSecret` y todas las versiones de
    datasets y del documento, y crea una versión final depurada (`testers.main=[]`,
    `owner=None`, la siguiente en numeración);
  - incrementa la revisión y audita `tenant.purge`, todo en la misma transacción `owner`.

**Tests:**

- `export` → `import` produce una versión idéntica;
- `--secrets` con el formato de `secrets.yaml`;
- `validate --all` sale con código 1 ante un documento inválido insertado a mano;
- `seed_demos` dos veces: la segunda no hace nada;
- `tenant_status offboard` exige la confirmación;
- la purga de un tenant no `offboarded` se rechaza;
- la purga completa deja exactamente una versión depurada y ningún secreto, métrica ni
  dataset.

**Docs:** `alta-baja-negocio.md` (baja y purga), `retencion-rgpd.md` y `docs/comandos.md`.

---

### T08b · Fuera `tenants/`, `secrets.yaml` y `sync_tenants`; `prod-manage` y `tenant-push` ⚠️

**Objetivo:** que la base de datos sea la única fuente de verdad en todo el repo.

**Cambios:**

- **Eliminar:**
  - `sync_tenants.py` y `new_tenant.py`;
  - `TENANTS_DIR` y `SECRETS_FILE` de settings, y `sources_from_directory` ya sin
    defaults de settings;
  - `tenants/.gitkeep` y `secrets.example.yaml`;
  - el target `tenant-sync`;
  - `COPY tenants ./tenants` del `Dockerfile`;
  - en `compose.yaml`, los montajes `./tenants` y `./secrets.yaml`;
  - en `compose.prod.yaml`, el montaje de `secrets.yaml` y `SECRETS_FILE`. **Se conserva**
    `google_sa.json`.
- **`.gitignore`:** deja `/tenants/` entero ignorado (sustituye a la línea de
  `autocares-ss`) y añade `/datos/`.
- **CI:** un paso "No tenant data in git" con
  `test -z "$(git ls-files tenants datos)"`.
- **`deploy/deploy.sh`:** sustituye `sync_tenants --strict` por
  `tenant_config validate --all` (con la imagen nueva, antes de `up`; si falla, `abort`)
  seguido de `seed_demos`.
- **`deploy/backup.sh`:** quita `secrets.yaml` de la lista de restic.
- **`deploy/restore.sh`:** quita `secrets.yaml` de la comprobación y de la copia.
- **`deploy/restore-test.sh`:** quita el `secrets.yaml` sintético y cambia
  `sync_tenants --strict` por `tenant_config validate --all`.
- **`tools/qr.py`:** `tenant_link(slug)` pasa a ser `tenant_link_from_file(path)`, que
  lee un `document.yaml` exportado. `make qr FILE=datos/<slug>/document.yaml`.
- **`tests/test_settings.py`** y cualquier test que use `TENANTS_DIR` o `SECRETS_FILE`.
- **`deploy/manage.sh`** (nuevo, en el servidor):

  ```bash
  #!/usr/bin/env bash
  # Run manage.py in production with the deployed image. As deploy, on the VPS.
  set -euo pipefail
  cd "$(dirname "$0")/.."
  SHA=$(cat .deployed-sha); export SHA
  tty=(-T); [[ -t 0 ]] && tty=()
  exec docker compose --project-name autobot -f compose.prod.yaml run --rm "${tty[@]}" web python manage.py "$@"
  ```

- **`Makefile`:**
  - `prod-manage`:
    `ssh $(if $(TTY),-t,) deploy@$(HOST) /srv/autobot/deploy/manage.sh $(CMD)`
    (`TTY=1` para los comandos interactivos);
  - `tenant-push`: `SLUG=` obligatorio y `SECRETS=` opcional (un `secrets.yaml` local).
    El target llama a un script `tools/tenant_push.sh` que:
    1. crea un directorio temporal con `mktemp -d` y lo borra al salir con `trap`;
    2. ejecuta `tenant_config export $(SLUG) <tmp>` contra la BD **local** (el export
       nunca incluye secretos);
    3. si se pasa `SECRETS`, copia **solo la entrada del slug** a `<tmp>/secrets.yaml`
       (con `yq` o un `python3 -c` de una línea);
    4. ejecuta `tar -C <tmp> -cz . | ssh deploy@$(HOST) /srv/autobot/deploy/manage.sh tenant_config import - --comment push`.

    Para ello, `tenant_config import -` acepta un `secrets.yaml` opcional en la raíz del
    tar, con el mismo formato que `--secrets`.
- **Docs:**
  - `alta-baja-negocio.md`: alta por el panel o con `tenant_config import`;
  - `alta-whatsapp-meta.md`, `09-rotar-secretos.md`, `demo.md`, `servidor.md`, `README.md`,
    `07-volver-atras.md` (la config se recupera con una versión, no con un despliegue) y
    `CLAUDE.md`;
  - `docs/comandos.md`.

**Aceptación:**

- `git ls-files tenants secrets.example.yaml` vacío.
- `grep -rn "TENANTS_DIR\|SECRETS_FILE\|sync_tenants\|new_tenant\|secrets.yaml\|tenant.yaml" src tests tools deploy docs Makefile Dockerfile compose*.yaml README.md CLAUDE.md .github`
  solo da referencias históricas (ADR antiguos) o el formato aceptado al importar.

---

### T08c · Automatización local

**Objetivo:** DESIGN §12, en la parte de desarrollo.

**Cambios:**

- **`Makefile`:**
  - `dev-bootstrap`:
    1. `docker compose up -d --wait db`;
    2. `make db-roles`;
    3. `docker compose run --rm web python manage.py migrate --database owner`. Revisa
       cómo se migra hoy en local y usa lo mismo;
    4. `apply_grants`;
    5. `seed_demos`;
    6. `docker compose up -d web worker` (más `victorialogs` cuando exista, en T13).

    Desde T14 añade también "si no hay usuario, `panel_user create`". Es idempotente.
  - `dev-reset`: `docker compose down -v` (pregunta antes con `read -p`) seguido de
    `dev-bootstrap`;
  - `tenant-import`: `DIR=` obligatorio y `SECRETS=` opcional; ejecuta
    `docker compose exec web python manage.py tenant_config import /work --secrets …`
    montando `DIR`. Si es más simple, usa `uv run` desde el host con `DB_OWNER_URL` local;
  - `HOST ?= autobot`, al principio del Makefile;
  - `ngrok`: `ngrok http --domain=$(NGROK_DOMAIN) 8000`, con
    `NGROK_DOMAIN ?= unpermanently-repairable-devon.ngrok-free.dev`.
- **`compose.yaml` (`worker`):** comando de desarrollo con recarga:
  `watchfiles --filter python "python manage.py procrastinate worker --concurrency 4" /app/src`.
  Añade `watchfiles` al grupo `dev` de `pyproject.toml`; si la imagen local no instala
  dev, instálalo en el `Dockerfile` solo para la etapa local o usa
  `uv run --with watchfiles`. Elige lo más simple que funcione y documéntalo.
- **Docs:** `docs/comandos.md` y `README.md` (arranque local en tres comandos), y
  `docs/runbooks/demo.md` (`make ngrok`).

**Aceptación:** en una máquina limpia, `make dev-bootstrap` deja web y worker en marcha
con los dos demos cargados, y `make dev-reset` lo repite desde cero.

---

### T09 · Herramientas `bus-*` sobre `datos/`

**Cambios:**

- **`tools/bus_tenant.py`:** `dataset_dir(slug) = REPO_ROOT / "datos" / slug / "timetable"`.
- **`tools/bus_revision.py`:** compara con `--base <dir>`, que por defecto es
  `datos/<slug>/.publicado/timetable`. Se elimina el uso de git.
- **`tools/bus_publicar.py`:** se sustituye por la lógica de los targets de abajo.
- **`Makefile`:**

  | Target | Qué hace |
  |---|---|
  | `bus-bajar TENANT= [PROD=1]` | Exporta la versión vigente a `datos/<slug>/timetable` y a `datos/<slug>/.publicado/timetable`. Sin `PROD`, desde la BD local; con `PROD=1`, desde producción vía `prod-manage` (`tenant_dataset export <slug> timetable -` con tar por stdout) |
  | `bus-validar`, `bus-formatear`, `bus-revision` | Sobre `datos/<slug>/` |
  | `bus-publicar TENANT= COMMENT= [PROD=1]` | Importa `datos/<slug>/timetable`. Sin `PROD`, en local; con `PROD=1`, por tar a `prod-manage tenant_dataset import <slug> timetable - --comment "$(COMMENT)"` |

**Tests:** los de `tests/tools/`, adaptados; `bus_revision --base`.

**Docs:** `docs/runbooks/10-horarios-bus.md` (el flujo paso a paso: bajar, editar,
formatear, validar, revisar, aprobar con la empresa y publicar), `docs/packs/bus.md` y
`docs/comandos.md`.

---

### T10 · Módulo de costes e índices

**Cambios:**

- **`src/autobot/runtime/costs.py`:**
  - mueve aquí `PRICE_EUR`;
  - `cost_of(counts: Mapping[str | None, int]) -> Decimal`: la misma lógica, log y
    redondeo que hoy;
  - `billable_counts(queryset) -> dict[str | None, int]`.

  `summary.py` pasa a usarlas.
- **Regla:** todo "mes en curso" usa `runtime.summary.month_to_date`. No crees otro
  helper.
- **Migración de índices:** `outbound_message (tenant_id, sent_at)` e
  `inbound_event (tenant_id, received_at)`.

**Tests:** los del resumen del dueño siguen pasando; `cost_of` con una categoría
desconocida, con `None` y con el redondeo.

---

### T11 · Alertas persistidas ⚠️ (permisos y función SECURITY DEFINER)

**Objetivo:** DESIGN §7.1.

**Cambios:**

- **`OpsAlert`** en `src/autobot/ops/models.py` (`db_table="ops_alert"`), con los campos
  de DESIGN §7.1 y
  `UniqueConstraint(fields=["kind","tenant_id"], condition=Q(resolved_at__isnull=True), name="ops_alert_one_open", nulls_distinct=False)`.
- **Migración:**
  - crea la tabla;
  - crea la función
    `purge_platform_history(cutoff timestamptz) RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp`,
    que borra `ops_alert` con `resolved_at < cutoff` y `audit_event` con `at < cutoff`;
  - `db_grants.apply`.

  En `db_grants`, añade `REVOKE DELETE ON ops_alert FROM fp_app`,
  `REVOKE ALL ON FUNCTION purge_platform_history(timestamptz) FROM PUBLIC` y
  `GRANT EXECUTE ON FUNCTION purge_platform_history(timestamptz) TO fp_app`.
- **`tests/isolation`:** `NO_RLS_TABLES |= {"ops_alert"}`.
- **`src/autobot/runtime/notifications.py`:**
  - `send_ops_alert(kind, tenant_id, text, *, informational=False) -> bool`, con los
    pasos de DESIGN §7.1 y la severidad deducida del primer emoji;
  - `MANUAL_KINDS = frozenset({"deploy_aborted", "deploy_rollback"})`, que define
    `auto_resolves`;
  - `resolve_alert(alert, *, by: str) -> None` pone `resolved_at` y `resolved_by` y borra
    la clave `ops:<digest>` de la caché. La usan `sync_alerts` y el panel.
- **`src/autobot/ops/check.py`:**
  - `@dataclass(frozen=True) class Finding: kind: str; tenant_id: UUID | None; text: str`;
  - `collect() -> list[Finding]`: todo lo que hoy hace `run()` salvo enviar. Las
    comprobaciones de Telegram y Meta (`health.daily`) siguen ocurriendo aquí, sin
    transacción abierta;
  - `sync_alerts(findings) -> None`: `send_ops_alert` por cada hallazgo y, al final,
    resuelve las abiertas con `auto_resolves=True` que no estén en `findings`;
  - `run()`: `sync_alerts(collect())`, después la muestra de sistema (T12) y el latido.
- **`deploy/deploy.sh`:** sus `alert_ops` siguen usando los `kind` de `MANUAL_KINDS`.
- **`src/autobot/runtime/retention.py`:** con `RETENTION_CLEANUP_ENABLED`, ejecuta
  `SELECT purge_platform_history(now() - interval '12 months')`.

**Tests:**

- la primera alerta crea la fila y la envía;
- la segunda, en enfriamiento, suma `occurrences` y queda con `"cooldown"`;
- sin bot configurado → `"unconfigured"`;
- un fallo de Telegram → `"failed"`, sin ninguna transacción abierta durante la llamada
  (compruébalo con un `httpx.MockTransport` que verifique
  `connection.in_atomic_block is False`);
- `collect()` sin efectos (sin llamadas a `send_ops_alert`);
- un hallazgo que desaparece → resuelto `"auto"`;
- `deploy_aborted` no se resuelve solo;
- al resolver se borra el enfriamiento y una nueva aparición se envía al momento;
- `informational` queda guardada ya resuelta;
- `purge_platform_history` ejecutada como `fp_app` borra solo lo antiguo.

**Docs:** `03-cola-y-latido.md`.

---

### T12 · Muestras de sistema, backups y despliegues ⚠️

**Objetivo:** DESIGN §7.4.

**Cambios:**

- **`src/autobot/ops/system.py`:** funciones puras con `root: Path = Path("/proc")`:
  - `cpu_percent(interval=0.2)`, `memory()`, `load()`, `uptime_s()` y `disk(path="/")`.
    Devuelven `None` si falta el fichero;
  - `read_backup_status(dir)` lee `backup.json`;
  - `read_deploys(dir, limit=20)` lee las últimas líneas válidas de `deploys.jsonl` e
    ignora las corruptas.
- **`SystemSample`** (`db_table="system_sample"`). `fp_app` tiene los privilegios por
  defecto, incluido el borrado de las muestras antiguas.
- **`ops/check.py` → `run()`:**
  - guarda una muestra con `db_bytes = pg_database_size(current_database())`;
  - borra las de más de 62 días;
  - sustituye el `shutil.disk_usage(settings.BASE_DIR)` por `system.disk()`, conservando
    la alerta del 85 %.
- **Settings:** `OPS_STATE_DIR = Path(os.environ.get("OPS_STATE_DIR", BASE_DIR / "state" / "ops"))`.
- **`deploy/backup.sh`:** escribe `state/ops/backup.json` de forma atómica (fichero
  temporal + `mv`). En caso de error, un `trap` escribe `ok: false`.
- **`deploy/deploy.sh`:** cada final escribe una línea en `state/ops/deploys.jsonl`, con
  `result` ∈ `deployed`, `already`, `aborted`, `rolled_back` o `rollback_failed`.
- **`compose.prod.yaml` (`web`):** `volumes:` con **los dos montajes**,
  `./google_sa.json:/run/secrets/google_sa.json:ro` (porque sobrescribir la lista del ancla
  lo perdería) y `./state/ops:/run/ops:ro`, más `OPS_STATE_DIR: /run/ops`.
- **`deploy/bootstrap-server.sh`:** crea `state/ops`, cuyo propietario es `deploy`.
- **`tools/check_prod_config.py`:** comprueba que `web` mantiene el montaje de
  `google_sa.json`.

**Tests:**

- `system.py` con un `/proc` falso;
- `read_deploys` con líneas corruptas;
- `run()` guarda una muestra y borra las antiguas;
- `shellcheck`.

**Docs:** `servidor.md`; en `puesta-en-marcha.md`, comparar con `htop` tras el primer
despliegue.

---

### T13 · VictoriaLogs y envío de logs ⚠️

**Objetivo:** DESIGN §7.3.

**Cambios:**

- **`compose.prod.yaml`:**
  - servicio `victorialogs`, con la imagen fijada a la última versión estable. Comprueba
    el formato real de la etiqueta en Docker Hub;
  - `command: ["-storageDataPath=/vlogs", "-retentionPeriod=31d", "-memory.allowedPercent=5", "-httpListenAddr=:9428"]`;
  - volumen `vlogs`, `restart: unless-stopped` y `logging: *logging`, **sin `ports`**;
  - en `x-app-env`, `VICTORIALOGS_URL: http://victorialogs:9428`.
- **`compose.yaml`:** el mismo servicio, publicado en `127.0.0.1:9428`.
- **`deploy/deploy.sh`:** `pull` y `up` incluyen `victorialogs`. Su caída **no** provoca
  la vuelta atrás, porque los logs no son críticos.
- **`tools/check_prod_config.py`:** comprueba que `victorialogs` no publica puertos.
- **`src/autobot/ops/logging.py`:** extrae de `JsonFormatter` una función
  `record_dict(record) -> dict`. El formatter la usa y el handler también.
- **`src/autobot/ops/logship.py`, `VictoriaLogsHandler`:**
  - cola `queue.Queue(maxsize=10_000)` con `put_nowait`; si está llena, suma al contador
    de descartados;
  - hilo daemon, que se vuelve a crear si cambia `os.getpid()`;
  - envía cada 2 s o cada 500 líneas con
    `httpx.post(f"{url}/insert/jsonline?_stream_fields=service&_time_field=ts&_msg_field=msg", content=…, timeout=2)`;
  - si falla, descarta el lote. Como mucho escribe una línea a `sys.stderr` por minuto,
    nunca al logging;
  - con `atexit`, un último envío con timeout de 1 s.
- **Settings:** el handler, con el filtro `privacy`, se añade al `root` solo si
  `VICTORIALOGS_URL` está definida.
- Comprueba los parámetros de `/insert/jsonline` contra la documentación de la versión
  fijada.

**Tests:**

- lotes, cola llena y descartes con `httpx.MockTransport`;
- un fallo de red no lanza excepción;
- no hay recursión;
- un teléfono sale enmascarado;
- desactivado sin la variable (para `tests/test_network_guard.py`).

**Docs:** `servidor.md` y `01-bot-no-responde.md`.

---

### T13b · `seed_dev_activity`

**Objetivo:** que el panel tenga datos en local para desarrollarlo y evaluarlo (DESIGN §12).

**Cambios:**

- **`src/autobot/management/commands/seed_dev_activity.py`** con `--days N` (por defecto,
  los transcurridos del mes en curso).
  - Si `settings.ENVIRONMENT != "local"`, lanza `CommandError`.
  - Sobre los tenants existentes (demos y los importados), crea con `owner` y
    `tenant_id`, y nunca llama a servicios externos:
    - contactos falsos (`+34 600 00x xxx`);
    - conversaciones;
    - unos 20–60 `inbound_event` y `outbound_message` por día, con `billable` y
      `pricing_category` variados;
    - algún `unknown` de hace más de 10 min y algún `failed`;
    - `notification`;
    - `metric_event` (`schedule_query` en `bus`);
    - 3 alertas abiertas y 5 resueltas;
    - un trabajo `failed` en `procrastinate_jobs`, con sus eventos;
    - un `system_sample` cada 5 min durante los últimos 2 días;
    - `state/ops/backup.json` y `deploys.jsonl` de ejemplo en `OPS_STATE_DIR`.
  - Es idempotente: con `--reset` borra antes lo que creó, marcado con
    `external_id` que empieza por `dev-` o un `kind` reconocible.
  - Si el modelo de un payload no es evidente, usa `tests/fixtures/` como referencia.
- **`Makefile`:** `dev-activity` (`docker compose exec web python manage.py seed_dev_activity`).

**Tests:** el comando se niega en `prod`; crea filas en todas las fuentes de la línea
temporal; `--reset` lo deja limpio.

**Docs:** `docs/comandos.md` y `README.md`.

---

### T14 · Base de la API del panel ⚠️

**Objetivo:** DESIGN §3.2, §3.3, §6.1, §6.2 y §6.3.

**Cambios:**

- **Dependencias:** `django-ninja` (la última 1.x compatible con Django 5.2 y Pydantic 2)
  y `qrcode` (pasa del grupo `dev` a las dependencias). Después, `uv lock`.
- **`src/autobot/db_router.py` → `AuthDatabaseRouter`:**
  - para las apps `auth`, `contenttypes`, `sessions`, `otp_totp` y `django_otp`,
    devuelve `"owner"` si está en `settings.DATABASES`; si no, `None`;
  - `allow_relation` permite las relaciones entre esas apps;
  - `allow_migrate` no cambia nada.

  Va en `DATABASE_ROUTERS`.
- **`db_grants`:** `REVOKE ALL` desde `fp_app` sobre `auth_user`, `auth_group`,
  `auth_permission`, `auth_user_groups`, `auth_user_user_permissions`,
  `auth_group_permissions`, `django_session` y `otp_totp_totpdevice`.
- **`src/autobot/panel/middleware.py` → `PanelGateMiddleware`:** DESIGN §3.2, punto 5.
  Va antes de `SessionMiddleware`.
- **`src/autobot/panel/errors.py`:** `ApiError(code, message, status, details=None)`.
- **`src/autobot/panel/auth.py`:**
  - `PanelAuth`: autenticación por sesión de ninja con CSRF. Exige
    `is_authenticated and is_staff and is_verified()`;
  - `CsrfOnly`: devuelve un valor verdadero tras comprobar el CSRF con la utilidad de
    ninja (`ninja.utils.check_csrf`, o la equivalente en la versión instalada);
  - router `auth` (DESIGN §6.2), con el login dentro de `transaction.atomic(using="owner")`
    y `select_for_update` del dispositivo, y el bloqueo **solo por usuario**.
- **`src/autobot/panel/api.py`:**
  - `NinjaAPI(title="Autobot panel", version="1", urls_namespace="panel", auth=PanelAuth(), docs_url=None)`;
  - manejadores de `ApiError`, `StoreError` (con su código), errores de validación de
    ninja (422, `validation_error`) y `Http404`.
- **`src/config/urls.py`:** `urlpatterns = public + [path("api/panel/", api.urls)]`.
- **Settings:** las cookies de DESIGN §6.2:

  ```python
  SESSION_COOKIE_NAME = "autobot_panel_session"
  CSRF_COOKIE_NAME = "autobot_panel_csrftoken"
  SESSION_COOKIE_AGE = 12 * 3600
  SESSION_COOKIE_HTTPONLY = True
  SESSION_COOKIE_SAMESITE = "Strict"
  CSRF_COOKIE_SAMESITE = "Strict"
  SESSION_COOKIE_SECURE = False  # SSH tunnel to 127.0.0.1 (ADR-008)
  CSRF_COOKIE_SECURE = False
  ```

  `DJANGO_ALLOWED_HOSTS` de producción debe incluir `127.0.0.1` y `localhost`.
  `ensure-env` (T24b) lo comprueba; mientras tanto, anótalo en `puesta-en-marcha.md`.
- **`Caddyfile` público:** en `handle @public`, `reverse_proxy web:8000 { header_up X-Autobot-Edge public }`.
  `tools/check_prod_config.py` comprueba que la cabecera llega al servidor de prueba.
- **`panel_user.py`:**
  - `create <usuario>`: contraseña con `getpass` dos veces y los validadores de Django;
    crea `is_staff=True` con `owner` y un `TOTPDevice(confirmed=True)`; imprime la
    `config_url` y su QR en ASCII (`qrcode`) **una vez**, con un aviso de credencial;
  - `reset-totp <usuario>` y `set-password <usuario>`;
  - `exists` sale con código 0 o 1 (lo usa `dev-bootstrap`).
- **`export_openapi.py <ruta>`:**
  `json.dumps(api.get_openapi_schema(path_prefix=""), indent=2, sort_keys=True, ensure_ascii=False) + "\n"`.
  Comprueba el nombre del parámetro en la versión instalada.
- **`panel/openapi.json`:** generado. Por ahora es lo único que hay en `panel/`.
- **`Makefile`:** `api` (por ahora solo el OpenAPI; T23a le añade los tipos TS).
  `dev-bootstrap` crea el usuario si `panel_user exists` falla (pidiéndolo por terminal).
- **CI (job `check`):**
  `make api` (o el comando equivalente con `uv run`) seguido de
  `git diff --exit-code panel/openapi.json`.

**Tests** (`tests/integration/panel/test_auth.py`, con `HTTP_HOST="127.0.0.1"`):

- login correcto;
- contraseña mala, OTP malo y usuario sin dispositivo → 401 genérico;
- bloqueo tras 5 fallos;
- `me` sin sesión → 401; sesión sin OTP → 401;
- `POST` sin CSRF → 403, también en `login`;
- `X-Autobot-Edge` → 404;
- sin `owner` → 503;
- `logout`;
- auditoría del login;
- `fp_app` no puede leer `auth_user`;
- una petición de webhook no consulta ninguna tabla de sesión;
- `panel_user create` con `getpass` parcheado.

**Docs:** `docs/runbooks/panel.md` (alta del operador con `make prod-manage TTY=1 CMD="panel_user create <u>"`
y recuperación del TOTP) y `docs/comandos.md`.

---

### T15 · `GET overview`

**Objetivo:** DESIGN §9.4.

**Cambios:**

- `src/autobot/panel/services/overview.py` y `routers/overview.py`, con los esquemas de
  DESIGN §9.4 (`Overview`, `TenantRow`, …) como `ninja.Schema`.
- `tenant_rows(now) -> list[TenantRow]` es una función pública: la reutiliza T16a.
- **Reglas de cálculo:** la tabla de DESIGN §9.4.
  - Todas las consultas con `.using("owner")`, agregadas por `tenant_id` y sin N+1.
  - Salud con `ops.status.tenant_status` y las alertas abiertas del tenant.
  - `by_day` con `TruncDate(..., tzinfo=ZoneInfo("Europe/Madrid"))`.
  - `system` sale de `ops.system`, de `read_backup_status` y `read_deploys`, y de
    `tls_days_left` (de T20; hasta entonces, `None`).

**Tests:**

- dos tenants y un demo con datos conocidos → todas las cifras;
- coste igual a la suma de `cost_of` por tenant;
- la frontera del día 1 en Madrid;
- `status.level` en los tres niveles, y `notice` y `unknown` no lo suben;
- `incidents_open`;
- `django_assert_max_num_queries(25)`.

---

### T16a · Packs y tenants: lectura

**Cambios en `routers/packs.py`, `routers/tenants.py` y `services/forms.py`:**

- **`document_schema(pack)` y `ui_schema(pack)`**, según DESIGN §9.5.
  - Añade `Field(title=..., description=...)` en español a los campos sin título de
    `TenantDocument`, `Owner`, `Testers`, `WhatsAppChannel`, `TelegramChannel`,
    `DemoInfo` y los `config.py` de `salon` y `bus`.
  - Son solo metadatos: no cambian la validación. Compruébalo con tests de las
    plantillas.
- **Endpoints de lectura** de DESIGN §6.4:
  - `GET packs`, `packs/{pack}/schema` y `packs/{pack}/template` (con `template_blank` a
    `null`);
  - `GET tenants` (con `tenant_rows`);
  - `GET tenants/{slug}`, que incluye `webhook_url = PUBLIC_URL + "/webhooks/<type>/<public_id>"`,
    `public_link` (la lógica de `tools/qr.py`, movida a `autobot/tenancy/links.py` y
    reutilizada por la herramienta) y `owner_linked`;
  - `versions` y `versions/{n}`;
  - `datasets`;
  - `secrets`, que **nunca** devuelve valores e incluye `readable`;
  - `activation-checklist` (con `tenancy.activation`);
  - `summary` (`build_summary` con `month_to_date`; se ejecuta como código de la
    plataforma, con `tenant_tx` y RLS, sin `owner`);
  - `notifications`.
- **`POST tenants/{slug}/health-check`** también va aquí. No escribe config: fuerza la
  caché de salud.

**Tests:**

- cada ruta;
- el schema de `salon` y `bus` es un JSON Schema válido (añade `jsonschema` al grupo dev)
  y su plantilla lo cumple;
- `GET secrets` nunca contiene el valor de prueba (búscalo en el JSON entero);
- **`GET summary` del tenant A no cuenta filas de B**: es el riesgo A1 de la revisión.

---

### T16b · Tenants: escritura ⚠️ (secretos)

**Cambios:** `POST tenants`, `PUT document`, `POST rollback`, `POST status` y
`PUT secrets`, que llaman a `store` con `actor=request.user.username`.

| `StoreError` | HTTP |
|---|---|
| `validation_error` | 422 |
| `conflict` | 409 |
| `not_found` | 404 |
| `forbidden_change`, `invalid_status`, `bad_request` | 400 |

`POST status` rechaza `offboard` con 400 (solo por comando).

**Tests:**

- un caso feliz por endpoint;
- 422 con detalles y sin valores;
- 409;
- `offboard` → 400;
- `PUT secrets` en un demo → 400;
- todo queda auditado con el usuario.

---

### T17 · Actividad, contactos y avisos

**Cambios en `services/activity.py`, `routers/activity.py` y `routers/contacts.py`:**

- Las fuentes, campos `at`, orden total, cursor y filtros de DESIGN §7.2.
- El cursor es base64url de `{"at": iso, "rank": int, "id": str}`.
- `describe_inbound` y `describe_outbound`:
  - Telegram: `message.text`, `callback_query.data`.
  - WhatsApp: `text.body`, `interactive.button_reply.title`,
    `interactive.list_reply.title`.
  - Salida: el `Outbound` de `core.serialization` (texto, más títulos de botones y filas).
  - Toma como referencia `tests/fixtures/` y los adaptadores.
- `GET tenants/{slug}/contacts?search=&cursor=` (en `display_name`, `phone_e164` y
  `external_id`) y `GET contacts/{id}`, con los últimos 50 intercambios y auditoría
  `contact.view`.

**Tests:**

- orden y paginación con empates de `at` entre fuentes (sin duplicados ni saltos);
- filtros, incluido el de trabajos por `args->>'tenant_id'`;
- payload vacío;
- auditoría;
- textos legibles con fixtures reales.

---

### T18 · Incidencias, alertas, trabajos y auditoría

**Cambios en `routers/incidents.py` y `routers/audit.py`:**

- `GET incidents`:
  - alertas abiertas, ordenadas por severidad y `last_seen_at`, con `auto_resolves`;
  - envíos `unknown`/`failed`, con `can_mark_sent` y `can_resend` y sus motivos;
  - trabajos `failed`, con `can_retry` y su último evento.
- `POST outbound/{id}/mark-sent` y `resend` (este exige `confirm_duplicate_risk: true`;
  si no, 400), y `POST jobs/{id}/retry`. Si la acción no es elegible, 409 con el motivo.
- `POST alerts/{id}/resolve`: 400 si `auto_resolves`. Si no, llama a `resolve_alert` y
  audita `alert.resolve`.
- `GET alerts`, `GET jobs` (sin `args` completos, solo los ids) y `GET audit`, con
  cursor `(at, id)`.

**Tests:** cada acción elegible y no elegible; reenviar sin confirmación; resolver una
alerta automática → 400; auditoría.

---

### T19 · Logs

**Cambios en `services/logs.py` y `routers/logs.py`:**

- `build_query(filters) -> str`:
  - escapa `\` como `\\` y `"` como `\"`;
  - por defecto, la última hora;
  - recorta `start` al día 1 del mes en curso (Madrid) y devuelve `clipped`;
  - `limit` de 200 por defecto, con un máximo de 1 000.
  - Comprueba la sintaxis de LogsQL contra la documentación de la versión fijada en T13.
- `GET logs` → `GET {VICTORIALOGS_URL}/select/logsql/query` con timeout de 10 s.
  Devuelve `{items: [...], truncated, clipped}`. El `tenant` UUID se traduce a slug.
  Si no está disponible, 503 `logs_unavailable`.

**Tests:** escapes (`"`, `\`, `|`), recorte del rango, `MockTransport` y 503.

---

### T20 · Sistema

**Cambios en `services/system.py` y `routers/system.py`:**

- `GET system` con la estructura de DESIGN §7.4:
  - `machine`, `samples` del mes, `services`, `database`, `queues`, `backup` (`stale` si
    tiene más de 8 h), `deploys`, `release` y `tls`.
- `queues` replica el cálculo de `OperationsSite.state` del Admin borrado. Recupéralo con
  `git show cab8665:src/autobot/admin.py`.
- `tls_days_left()`: `ssl` + `socket.create_connection((host, 443), timeout=5)`, con
  `host` sacado de `PUBLIC_URL` y una caché de 1 h. Si falla, `None`. T15 lo usa.

**Tests:** `/proc` falso, `OPS_STATE_DIR` falso, TLS parcheado y un worker sin latido.

---

### T21 · Catálogo de datos y consultas guardadas ⚠️ (permisos)

**Cambios:**

- **`services/catalog.py`:**
  - `CATALOG: dict[str, TableDoc]`, con
    `TableDoc(group, description, written_by, retention, rls, columns: dict[str, str])`,
    para **todas** las tablas de la base de test;
  - `HIDDEN_COLUMNS` (DESIGN §8.1).
- **`GET data/tables`:** lo de DESIGN §8.1. Las tablas reales sin entrada van al grupo
  "Sin catalogar".
- **`GET data/tables/{name}`:**
  - solo nombres que estén en el catálogo;
  - las 20 más recientes, ordenadas por la primera columna de fecha conocida (`at`,
    `created_at`, `received_at`, `taken_at` o `updated_at`) o, si no hay, por la PK;
  - `bytea` como `"<N bytes>"` y `HIDDEN_COLUMNS` como `"<oculto>"`.
- **`SavedQuery`** (`db_table="saved_query"`), con `db_grants`
  `REVOKE ALL ON saved_query FROM fp_app`. Migración de datos con 4 consultas de ejemplo.
  CRUD.

**Tests:**

- todas las tablas de `connection.introspection.table_names()` tienen entrada, y no hay
  entradas sobrantes;
- un nombre fuera del catálogo → 404;
- cada una de las 6 `HIDDEN_COLUMNS` sale oculta;
- CRUD.

---

### T22 · Consola SQL ⚠️ (políticas RLS)

**Objetivo:** DESIGN §8.2. El rol ya existe desde T00b.

**Cambios:**

- **Migración `00xx_readonly_all`** (`RunPython` o `RunSQL` con su reverso):
  - por cada tabla devuelta por
    `SELECT tablename FROM pg_policies WHERE schemaname='public' AND policyname='tenant_isolation'`,
    `CREATE POLICY readonly_all … FOR SELECT TO fp_readonly USING (current_setting('app.readonly_all', true) = 'on')`;
  - si `fp_readonly` no existe, falla con un mensaje claro ("run init-roles.sh").
- **`tests/isolation/test_isolation.py` → `isolation_problems`:** acepta exactamente
  `tenant_isolation` (como hoy) **y** `readonly_all` (`cmd=SELECT`, `roles={fp_readonly}`,
  el `qual` esperado), y exige que estén las dos.
- **Settings:** alias `readonly` desde `DB_READONLY_URL`, con `CONN_MAX_AGE=0`.

  | Entorno | Valor |
  |---|---|
  | Local | `postgres://fp_readonly:fp_readonly@localhost:5433/autobot` |
  | CI | `DB_READONLY_URL: postgres://fp_readonly:fp_readonly@localhost:5432/autobot` en el `env` del job |
  | Worker en producción | Vacía, sin alias |
  | `web` en producción | `DB_READONLY_URL: ${DB_READONLY_URL:?Set DB_READONLY_URL}` |

  `tools/check_prod_config.py` lleva un valor sintético y comprueba que el worker no la
  tiene.
- **`services/query.py` → `run(sql, tenant_id, actor) -> QueryResult`:** los pasos de
  DESIGN §8.2.
  - El cursor con nombre es `connections["readonly"].connection.cursor(name="panel_query")`
    dentro del `atomic`.
  - El rollback se fuerza con `transaction.set_rollback(True, using="readonly")`.
  - Un `DatabaseError` se convierte en 400 con `str(exc)` recortado, sin traza.
  - La auditoría va después, en `owner`.
- **`POST data/query`.**

**Tests:**

- sin ajustes, 0 filas en `contact`; con `readonly_all`, todas; con `app.tenant_id`, solo
  las suyas;
- `INSERT`, `UPDATE`, `DELETE` y `CREATE` fallan;
- `SELECT 1; SELECT 2` se rechaza;
- `EXPLAIN SELECT 1` se rechaza con un mensaje claro;
- `LIKE '%a%'` funciona;
- `SENSITIVE_TABLES` da permiso denegado;
- `pg_sleep(11)` corta por timeout;
- truncado a 1 000;
- auditoría;
- tras la consulta no queda ninguna transacción ni ajuste en la conexión.

**Docs:** ADR-002 (la política adicional) y la regla en `CLAUDE.md` (ya hecha en T00;
revísala).

---

### T23a · Andamiaje del frontend

**Objetivo:** dejar las herramientas y la CI del frontend (DESIGN §9.1 y §9.2).

**Cambios:**

- **Proyecto:** `panel/` creado con `pnpm create vite` (react-ts), Node 24 y
  `"packageManager": "pnpm@<versión>"`. Las dependencias son las de DESIGN §9.1.
- **Scripts:**

  ```json
  "dev": "vite", "build": "tsc -b && vite build", "preview": "vite preview",
  "check": "biome check .", "fix": "biome check --write .",
  "typecheck": "tsc -b --noEmit", "test": "vitest run",
  "gen:api": "openapi-typescript openapi.json -o src/api/schema.d.ts"
  ```

- **`vite.config.ts`:**
  - alias `@` → `src`;
  - plugin de TanStack Router;
  - `server.proxy = { "/api": { target: "http://127.0.0.1:8000", changeOrigin: false } }`;
  - Vitest con `jsdom`.
- **Configuración:** `tsconfig` (`strict` y `noUncheckedIndexedAccess`) y `biome.json`
  (recomendado, 2 espacios y comillas dobles).
- **`Makefile`:**
  - `panel-dev`: `pnpm -C panel dev`;
  - `panel-check`: `check`, `typecheck`, `test` y `build`;
  - `api`: también `pnpm -C panel gen:api`;
  - `fix`: `uv run ruff check --fix .`, `uv run ruff format .`, `pnpm -C panel fix` y
    `make api`.
- **CI:** job `panel`:
  1. `setup-node` 24 y `pnpm/action-setup`;
  2. `pnpm -C panel install --frozen-lockfile`;
  3. `pnpm -C panel gen:api && git diff --exit-code panel/src/api/schema.d.ts`;
  4. `check`, `typecheck`, `test` y `build`.

  El job `image` depende de `check` y de `panel`.
- **`.gitignore`:** `panel/node_modules/` y `panel/dist/`.
- **Página mínima** "Autobot" para que el build tenga algo que compilar.

**Docs:** `README.md` y `docs/comandos.md`.

---

### T23b · Layout, login, cliente de la API y componentes

**Cambios:**

- **shadcn:** `components.json` con `new-york`, `zinc` y variables CSS, y los componentes
  `button`, `card`, `badge`, `input`, `label`, `table`, `tabs`, `dialog`,
  `alert-dialog`, `dropdown-menu`, `command`, `tooltip`, `skeleton`, `separator`,
  `scroll-area`, `sheet`, `select`, `textarea`, `form`, `sidebar` y `chart`.
- **Tema:** `src/styles/globals.css` con los colores de DESIGN §9.3 y Geist; `dark`
  siempre activo.
- **`src/api/client.ts`:**
  - `createClient<paths>({ baseUrl: "/api/panel" })`;
  - un middleware que pone `X-CSRFToken` (leído de la cookie `autobot_panel_csrftoken`)
    en los métodos que no son seguros;
  - un 401 fuera de `auth/me` y `auth/login` invalida `me` y navega a
    `/login?redirect=…`;
  - normaliza los errores a `ApiError {code, message, details, status}`.
- **`features/auth`:** `useMe`, `LoginPage` (`react-hook-form` + `zod`; código de 6
  dígitos; muestra el error genérico) y `useLogout`. `GET auth/csrf` al arrancar.
- **Rutas:** `__root`, `login` y `_app` (`beforeLoad` con `ensureQueryData(me)` que
  redirige si falla). Una página "Próximamente" por sección.
- **`app-shell`, `sidebar`, `topbar`:** lo de DESIGN §9.3. El punto de estado queda gris
  hasta T25.
- **`command-menu`:** las secciones.
- **Comunes:** `status-badge` (los 5 niveles de §7.5 más `active`, `paused`, `onboarding`
  y `offboarded`), `kpi-card`, `data-table`, `page-header`, `empty-state`, `error-state`,
  `confirm-dialog` (con un texto opcional que hay que escribir), `time-ago`,
  `code-editor` (carga perezosa) y `json-diff`.
- **`lib/format.ts`:** `formatDateTime`, `formatDate`, `formatRelative`, `formatEur`
  (`12,40 €`), `formatNumber` (`1.240`) y `formatBytes`.
- **QueryClient:** `staleTime` de 10 s; un reintento salvo con 4xx;
  `refetchOnWindowFocus`.

**Tests:** `format.ts`, el CSRF del cliente, la validación y el error de `LoginPage`, la
redirección de `_app` y `confirm-dialog` con texto.

**Aceptación:** en local, `make up` + `make panel-dev` → login con TOTP, menú y salir.

---

### T24 · Contenedor `panel`, despliegue y túnel ⚠️

**Cambios:**

- **`panel/Dockerfile`:**
  1. etapa `node:24-alpine`: `corepack enable`, `pnpm install --frozen-lockfile` y
     `pnpm build`;
  2. etapa `caddy:<2.x fijada>-alpine`: copia `dist/` a `/srv` y el `Caddyfile`, con un
     usuario no root;
  3. `ENV XDG_CONFIG_HOME=/tmp/config XDG_DATA_HOME=/tmp/data`, porque el sistema de
     ficheros es de solo lectura.
- **`panel/Caddyfile`:**

  ```
  {
      admin off
      auto_https off
  }
  :8080 {
      encode zstd gzip
      header {
          Content-Security-Policy "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
          X-Frame-Options DENY
          Referrer-Policy no-referrer
          X-Content-Type-Options nosniff
      }
      handle /healthz {
          respond "ok" 200
      }
      handle /api/* {
          reverse_proxy web:8000 {
              header_up -X-Autobot-Edge
          }
      }
      handle {
          root * /srv
          try_files {path} /index.html
          file_server
      }
  }
  ```

- **`compose.prod.yaml`:** servicio `panel`:
  - `image: ghcr.io/marianodelrio/autobot-panel:${SHA:?Set the published image SHA}`;
  - `ports: ["127.0.0.1:8080:8080"]`, `read_only: true` y `tmpfs: [/tmp]`;
  - `restart: unless-stopped`, `logging: *logging` y `depends_on` de `web` en estado
    `service_healthy`;
  - `healthcheck: wget -qO- http://127.0.0.1:8080/healthz`.
- **`compose.yaml`:** `panel` construido desde `./panel`, con `profiles: [panel]`.
- **`tools/check_prod_config.py`:** `panel` solo en `127.0.0.1` y en modo `read_only`.
- **CI (job `image`):** un segundo `build-push-action` con `context: panel` y la imagen
  `ghcr.io/marianodelrio/autobot-panel:${{ github.sha }}`.
- **`deploy.yml`:** verifica también el manifiesto del panel.
- **`deploy/deploy.sh`:**
  - `pull` y `up` incluyen `panel`;
  - añade `wait_panel` (`curl http://127.0.0.1:8080/healthz`);
  - si falla, vuelta atrás, que también incluye `panel`.
- **`Makefile`:** `panel-tunnel: ssh -o ExitOnForwardFailure=yes -N -L 127.0.0.1:18000:127.0.0.1:8080 deploy@$(HOST)`.

**Pruebas:**

- `shellcheck`;
- `docker compose --profile panel up --build`;
- en `http://127.0.0.1:8080`: login, recargar una ruta profunda y un `POST` con CSRF
  (comprueba que `Host` se conserva).

**Docs:** `servidor.md`, `panel.md`, `puesta-en-marcha.md` y `docs/comandos.md`.

---

### T24b · Despliegue simple ⚠️

**Objetivo:** DESIGN §12, en la parte de operación.

**Cambios:**

- **`deploy/ensure-env.sh`:** se llama al principio de `deploy.sh`.
  1. Lee `.env` (si falta, lo crea con modo 0600).
  2. Genera las variables internas de DESIGN §12 que falten:
     - contraseñas con `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`;
     - `SECRETS_ENCRYPTION_KEY` con una clave Fernet: 32 bytes aleatorios en base64
       urlsafe, que pueden generarse sin `cryptography` con `base64.urlsafe_b64encode(os.urandom(32))`;
     - `DB_APP_URL`, `DB_OWNER_URL` y `DB_READONLY_URL` a partir de las contraseñas, con el
       host `db`.

     Las añade al final de `.env` con un comentario de fecha.
  3. Si faltan obligatorias externas (`PUBLIC_HOST`, `DJANGO_ALLOWED_HOSTS`, …),
     aborta y las lista. Si `DJANGO_ALLOWED_HOSTS` no incluye `127.0.0.1` ni
     `localhost`, aborta también.
  4. Nunca imprime valores.
- **`deploy/deploy.sh`:**
  - el orden completo de DESIGN §12;
  - al terminar bien, `alert_ops deploy_ok '🟢 Desplegado <sha corto>'`, con
    `informational`. Para ello, `alert_ops` acepta un tercer argumento que lo pasa a
    `send_ops_alert(..., informational=True)`.
- **`Makefile`:**
  - `deploy`: `SHA ?= $(shell git rev-parse origin/main)`. Antes, comprueba con
    `gh run list --workflow ci.yml --commit $(SHA) --json conclusion -q '.[0].conclusion'`
    que es `success`; si no, aborta;
  - `rollback`: lee del servidor (`ssh … tail -n 50 /srv/autobot/state/ops/deploys.jsonl`)
    el último `deployed` y su `previous`. Pide confirmación y ejecuta
    `make deploy SHA=<previous>`.

**Tests:** `shellcheck`, y una prueba de `ensure-env.sh` con un `.env` temporal, añadida a
`tests/tools/` o como script en CI: genera las internas, no toca las existentes y aborta
si falta una externa.

**Docs:** `puesta-en-marcha.md` (el primer despliegue queda en: rellenar las externas,
`make deploy`, `make tenant-push`, `panel_user create` y `panel-tunnel`), `07-volver-atras.md`
(`make rollback`) y `docs/comandos.md`.

---

### T25 · Pantalla Resumen

**Cambios:** `src/features/overview/` y `_app/index.tsx`, según DESIGN §9.4:

- banner de estado con los problemas enlazados;
- 4 KPIs y la tarjeta de métricas de packs;
- barras por día (Recharts);
- tabla de clientes, con cada fila enlazada a la ficha;
- tarjeta de sistema y últimas alertas;
- refresco cada 30 s.

Además, el punto de estado de `topbar` pasa a usar `status.level`, y `command-menu`
incluye los clientes.

**Tests:** el banner en sus tres niveles, los KPIs formateados y los estados vacío y de
error.

---

### T26 · Clientes: lista y ficha

**Cambios:** `src/features/tenants/`.

- **`/clientes`:** la tabla, con filtros, búsqueda y "Nuevo cliente".
- **`/clientes/$slug`:** cabecera con las acciones según el estado. Pausar, Reactivar y
  Activar se conectan en T27; "Comprobar salud" va con `health-check`.
- **Pestañas** de DESIGN §9.4: Resumen, Canal (solo lectura, con el enlace público y el
  QR de `qrcode.react`), Actividad (crea aquí el componente compartido
  `features/activity/components/timeline.tsx`), Contactos (con un `sheet` para la
  conversación), Avisos y Datos.

**Tests:** acciones según el estado, carga de las pestañas, emparejado de entrada y
salida, y el QR con el enlace correcto.

---

### T27 · Editor de config, historial, estado y secretos

**Cambios:** `src/features/tenants/config/`, según DESIGN §9.5:

- **Formulario rjsf.** Prueba primero `@rjsf/shadcn`; si no funciona con la versión
  instalada de shadcn, usa plantillas propias mínimas (`FieldTemplate`,
  `ObjectFieldTemplate`, `ArrayFieldTemplate` y widgets de texto, número, check, select
  y textarea). Deja la elección en un comentario de una línea.
- **Pestaña YAML** sincronizada con el formulario.
- **"Ver cambios"** con `json-diff`.
- **Guardar:** comentario obligatorio. 422 → `errorSchema` y lista; 409 → aviso;
  éxito → toast. Confirmación al salir con cambios sin guardar.
- **Historial:** lista, diff con la anterior y "Volver a esta versión".
- **Estado:** Pausar y Reactivar con `confirm-dialog`. Activar abre la lista de
  comprobación y escribe el slug.
- **Canal:** formulario "Sustituir secretos". Los valores no pasan por la caché de
  TanStack Query ni por el almacenamiento del navegador, y el formulario se vacía al
  terminar.

**Tests:** de 422 a errores de campo, 409, diff, activación bloqueada y con slug, y el
formulario de secretos vaciado.

---

### T28 · Asistente de alta

**Cambios:** `src/features/onboarding/` y `/clientes/nuevo`, con los 4 pasos de DESIGN
§9.6. El estado se guarda en `sessionStorage`. Al terminar, navega a la pestaña Canal con
la lista de lo que falta.

**Tests:** el slug derivado y su validación (incluido que no exista), el bloqueo con
errores, el cuerpo del `POST`, y un 422 que vuelve al paso 3 con los errores marcados.

---

### T29 · Actividad e Incidencias

**Cambios:**

- **`timeline`:** `useInfiniteQuery` con `cursor`.
- **`/actividad`:** filtros en la URL; la primera página se refresca cada 15 s.
- **`/incidencias`:** los bloques de DESIGN §9.7; "Resolver" solo si `auto_resolves=false`.
- **`sidebar`:** el contador `incidents_open`.

**Tests:** las acciones y el refresco, la confirmación de reenviar y los filtros en la
URL.

---

### T30 · Logs

**Cambios:** `src/features/logs/`, según DESIGN §9.7, con tabla virtualizada, filtros en
la URL, avisos de `clipped` y 503, y "Copiar event_id".

**Tests:** los parámetros, la fila desplegable, 503 y `clipped`.

---

### T31 · Datos

**Cambios:** `src/features/data/`, según DESIGN §9.8. Catálogo, tabla y consulta:

- CodeMirror con SQL y autocompletado del catálogo;
- ⌘↵ para ejecutar;
- CSV y TSV;
- consultas guardadas;
- la última consulta, en `localStorage`.

**Tests:** CSV (comillas y saltos de línea), truncado, ⌘↵ y CRUD de consultas guardadas.

---

### T32 · Sistema y Auditoría

**Cambios:** `/sistema` y `/auditoria`, según DESIGN §9.9.

**Tests:** los umbrales de color, el caso sin backup y el filtro de auditoría.

---

### T33 · Repaso final de la documentación

**Cambios:**

- `docs/runbooks/panel.md` completo.
- Repaso de todos los runbooks para que digan, por ejemplo, "en el panel: Clientes → X
  → Configuración" o el comando que toque, en lugar de mencionar `tenant.yaml` o el Admin.
- `docs/puesta-en-marcha.md`, sección "Panel": la lista ordenada de pasos del primer
  despliegue (§3), con casillas.
- `README.md` y `docs/comandos.md` completos y coherentes con el `Makefile`. Un test
  (`tests/test_docs.py`) comprueba que cada target del `Makefile` aparece en
  `docs/comandos.md`.
- Busca con `grep` cualquier resto de `tenants/`, `secrets.yaml`, `Admin`,
  `/admin/estado`, `admin-tunnel` y `sync_tenants`.

**Aceptación:** con solo leer `README.md`, `docs/comandos.md`, `docs/runbooks/panel.md`
y `puesta-en-marcha.md`, una persona arranca todo en local y sabe qué falta para
producción.

---

## 3. Primer despliegue (para la persona)

No hay nada desplegado, así que no hay migración de datos de producción. Los pasos se
escriben en `docs/puesta-en-marcha.md`, sección "Panel", y se suman a los que ya existen
allí (servidor, Meta y Telegram):

1. En el `.env` del servidor, rellenar las variables **externas** (tokens, ids de Meta,
   `PUBLIC_HOST`, `DJANGO_ALLOWED_HOSTS` con `127.0.0.1,localhost`, Sentry y
   healthchecks). `ensure-env` genera las internas.
2. `make deploy` (con la aprobación del entorno `production` en GitHub).
3. En local, `make tenant-import DIR=tenants/autocares-ss SECRETS=secrets.yaml` y
   comprobar la ficha en el panel local. Después,
   `make tenant-push SLUG=autocares-ss SECRETS=secrets.yaml`.
4. `make prod-manage TTY=1 CMD="panel_user create <usuario>"` y registrar el TOTP.
5. `make panel-tunnel` y abrir `http://127.0.0.1:18000`.
6. Comprobar CPU y RAM del panel frente a `htop` en el host, y `docker stats`.
7. Una vez verificado, borrar las copias locales de `tenants/autocares-ss` y
   `secrets.yaml`, o guardarlas cifradas fuera del repo.

## 4. Puntos a verificar durante la implementación

| Punto | Tarea | Qué comprobar |
|---|---|---|
| Cursor con nombre de psycopg 3 dentro del `atomic` de Django | T22 | Una sola sentencia, sin interpretar `%`, lectura por partes; test obligatorio |
| Parámetro `path_prefix` de `get_openapi_schema` y CSRF de ninja | T14 | Contra la versión instalada; tests de 403 |
| `registry_scope` en trabajos y peticiones | T06c | Que ningún trabajo vea dos registros distintos |
| Caddy conserva `Host` | T24 | CSRF extremo a extremo |
| `/proc` del host dentro del contenedor | T12 | Primer despliegue, paso 6 |
| Tema shadcn de rjsf | T27 | Plantillas propias si no encaja |
| Sintaxis de LogsQL y `/insert/jsonline` | T13, T19 | Contra la versión fijada |
| `watchfiles` en la imagen local | T08c | La opción más simple que funcione |
| RAM de la VPS | T13, T24 | `docker stats` en el primer despliegue |
