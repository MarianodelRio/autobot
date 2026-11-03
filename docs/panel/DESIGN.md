# Panel de Autobot: diseño

**Estado:** aprobado por la persona el 2026-11-03 (decisiones en §15). Revisado con el
informe de revisión independiente del mismo día, cuyos hallazgos ya están incorporados.
Este documento describe **qué** se construye y **cómo** funciona. El orden de trabajo,
las tareas y sus criterios de aceptación están en [`IMPLEMENTATION.md`](IMPLEMENTATION.md).

**Contexto:** el proyecto está en desarrollo temprano. No hay nada desplegado ni tráfico
real, así que no hay datos de producción que migrar. El primer despliegue se hará con todo
esto ya implementado.

---

## 1. Objetivo y alcance

El panel es la herramienta interna de la única persona que opera Autobot. Sustituye
al Django Admin, que desaparece. Al entrar responde a dos preguntas: **¿va todo bien?**
y **¿cuánto se usa?**. Desde ahí se puede actuar sobre la plataforma.

**Incluye (v1):**

| # | Sección | Para qué |
|---|---|---|
| 1 | Resumen | Estado global de un vistazo y KPIs de uso del mes en curso |
| 2 | Clientes | Ver cada negocio; cambiar su config, pausarlo, reactivarlo y activarlo; sustituir sus secretos de canal (solo escritura) |
| 3 | Alta de cliente | Asistente para crear un negocio de un pack existente |
| 4 | Actividad | Lo que está pasando, contado en lenguaje claro: mensajes, respuestas, avisos, alertas y cambios |
| 5 | Logs | Logs técnicos con filtros, del mes en curso |
| 6 | Incidencias | Lo que pide acción (alertas abiertas, envíos `unknown`/`failed`, trabajos fallidos), con sus acciones |
| 7 | Datos | Catálogo explicado de la base de datos y consola SQL de solo lectura |
| 8 | Sistema | Máquina (CPU, RAM, disco), servicios, colas, backups, TLS y versión desplegada |
| 9 | Auditoría | Quién cambió qué y cuándo |

**No incluye (v1):**

- Stripe y cualquier otro pago.
- Acceso de los dueños de los negocios, o desde el móvil.
- Editar los horarios de `bus` desde el panel: se hace por terminal (§4.7).
- Dar de baja o purgar un negocio: se hace por terminal (§4.6).
- Lanzar despliegues desde el panel.
- Tendencias de más de un mes.
- Alertas propias del panel: siguen llegando por Telegram.
- Acceso sin túnel SSH.

## 2. Principios

1. **Una sola fuente de verdad por dato.** La config de los negocios vive en PostgreSQL,
   versionada. Nada de config en git ni en la imagen.
2. **El backend sabe y el frontend pinta.** Toda regla, validación y permiso se
   comprueba en Django. El frontend nunca es la única barrera.
3. **El bot de ops es un reflejo del panel.** Todo lo que el bot manda a Telegram queda
   guardado y se ve en el panel (§7.1). El panel muestra más que el bot, nunca menos.
4. **Nada nuevo expuesto a internet.** El panel solo se alcanza por túnel SSH.
5. **Simple antes que completo.** Solo el mes en curso. Sin tiempo real: se consulta cada
   15–30 s. Solo dos contenedores nuevos (`panel` y `victorialogs`).
6. **Las reglas de la plataforma no cambian:**
   - RLS y `tenant_tx`;
   - idempotencia;
   - ninguna transacción abierta durante llamadas externas;
   - trabajos de cola solo con ids;
   - secretos nunca en claro ni en logs.
7. **Toda escritura queda auditada**, en la misma transacción que el cambio.
8. **Los permisos de BD son reproducibles.** Un único módulo declara el estado deseado de
   GRANT y REVOKE, y se vuelve a aplicar en cada despliegue y tras cada restauración (§5).

## 3. Arquitectura

### 3.1. Contenedores

```
                    Internet
                       │  443
┌──────────────────────▼───────────────────────────────────────────────┐
│ VPS                                                                   │
│  ┌─────────────────────────────┐                                      │
│  │ caddy (público)             │  solo webhooks y /health (como hoy)  │
│  │ añade X-Autobot-Edge: public│                                      │
│  └──────────────┬──────────────┘                                      │
│  ┌──────────────▼──────────────┐      ┌────────────────────────────┐  │
│  │ web (Django, gunicorn)      │◄────►│ worker (Procrastinate)     │  │
│  │ 127.0.0.1:8000              │      │ ops_check cada 5 min:      │  │
│  │ /webhooks/*, /health        │      │ alertas y muestras de      │  │
│  │ /api/panel/*  (NUEVO)       │      │ sistema                    │  │
│  └───┬─────────▲─────────┬─────┘      └──────┬──────────────┬──────┘  │
│      │         │         │ logs JSON (HTTP)  │              │         │
│      │         │         ▼                   ▼              │         │
│      │         │  ┌──────────────────────────────┐          │         │
│      │         │  │ victorialogs (NUEVO)         │          │         │
│      │         │  │ solo red interna, 31 días    │          │         │
│      │         │  └──────────────────────────────┘          │         │
│      │  ┌──────┴──────────────────────┐                     │         │
│      │  │ panel (NUEVO): Caddy        │                     │         │
│      │  │ 127.0.0.1:8080              │                     │         │
│      │  │ /      → SPA estática       │                     │         │
│      │  │ /api/* → web:8000           │                     │         │
│      │  └──────▲──────────────────────┘                     │         │
│      ▼         │                                            ▼         │
│  ┌─────────────┼──────────────────────────────────────────────────┐   │
│  │ db (PostgreSQL 18, RLS)                                        │   │
│  └─────────────┼──────────────────────────────────────────────────┘   │
└────────────────┼──────────────────────────────────────────────────────┘
                 │ ssh -L 127.0.0.1:18000:127.0.0.1:8080  (make panel-tunnel)
            portátil → http://127.0.0.1:18000
```

| Servicio | Imagen | Cambio |
|---|---|---|
| `caddy` | `caddy:2` | Añade la cabecera `X-Autobot-Edge: public` a lo que reenvía a `web` |
| `web` | `ghcr.io/marianodelrio/autobot` | Nueva API `/api/panel/`. Sin Admin ni ficheros estáticos. Monta `./state/ops` en solo lectura (§7.4) |
| `worker` | la misma | Guarda alertas y muestras de sistema |
| `db` | `postgres:18` | Tablas nuevas y rol `fp_readonly` |
| `panel` | `ghcr.io/marianodelrio/autobot-panel` (nueva) | Caddy que sirve la SPA y hace proxy de `/api/` hacia `web:8000`. Unos 20 MB de RAM |
| `victorialogs` | `victoriametrics/victoria-logs` (versión fijada) | Almacén de logs: 31 días, solo red interna, `-memory.allowedPercent=5` (≈ 200 MB como máximo en 4 GB) |

### 3.2. Flujo de una petición del panel

1. El navegador abre `http://127.0.0.1:18000`. El túnel lleva la conexión a `panel:8080`.
2. `panel` sirve la SPA. Cualquier ruta desconocida devuelve `index.html`.
3. La SPA llama a `/api/panel/...` en el **mismo origen**: no hay CORS y las cookies de
   sesión funcionan sin más.
4. `panel` reenvía a `web:8000`. Conserva `Host` y cookies, y elimina cualquier
   `X-Autobot-Edge` que llegue de fuera.
5. En Django, `PanelGateMiddleware` actúa solo sobre `/api/panel/`:
   - si la petición trae `X-Autobot-Edge` (llegó por el Caddy público), responde 404;
   - si el proceso no tiene alias `owner`, responde 503.
6. django-ninja exige sesión con OTP verificado y CSRF en las escrituras (§6.2).

### 3.3. Acceso a la base de datos

| Alias | Rol | Quién lo usa |
|---|---|---|
| `default` | `fp_app` (RLS, sin DDL) | Webhooks, worker y todo el código de `runtime`, `ops` y `channels` |
| `owner` | `fp_owner` (`BYPASSRLS`) | Migraciones, comandos de operación, `tenancy.store`, servicios del panel y tablas de autenticación |
| `readonly` | `fp_readonly` (solo `SELECT`, sin `BYPASSRLS`) | Solo la consola SQL del panel (§8.2) |

- **Enrutado por modelo, no por petición.** `autobot.db_router.AuthDatabaseRouter` manda
  a `owner` los modelos de las apps `auth`, `contenttypes`, `sessions`, `otp_totp` y
  `django_otp` (si existe el alias). Todo lo demás va a `default`.
- **Los servicios del panel usan `.using("owner")` de forma explícita** en cada consulta
  que cruza negocios.
- Cuando el panel llama a código de la plataforma (`build_summary`, `ops.health`,
  `tenant_tx`…), ese código se ejecuta **igual que en el worker**: con `default` y RLS.
  Por eso nunca puede mezclar datos de dos negocios.
- `fp_app` pierde el acceso a las tablas de autenticación (§5). En los webhooks la sesión
  nunca se toca, así que no se consulta.
- Desaparece el router por petición actual (`admin_db.py`).

### 3.4. Por qué así

- **SPA estática con Vite, no Next.js.** Detrás de un login no hace falta renderizar en
  servidor, y sin un runtime de Node en producción hay menos RAM y menos piezas.
- **Mismo origen gracias al proxy de `panel`.** La sesión y el OTP de Django sirven tal
  cual, sin tokens ni CORS.
- **Ninguna API ni BFF aparte.** Django es la única API. Una capa más solo compensaría
  con varios frontends o varios backends.
- **Logs en VictoriaLogs enviados por la propia app.** No hace falta un colector ni el
  socket de Docker, y los logs ya pasan limpios por `PrivacyFilter`.
- **Métricas de máquina leyendo `/proc`.** Dentro del contenedor, `/proc/meminfo`,
  `/proc/stat` y `/proc/loadavg` muestran los valores del host. No hace falta Beszel,
  Netdata ni Prometheus.

## 4. Configuración de los negocios: la base de datos como fuente de verdad

### 4.1. Situación actual (lo que se sustituye)

- `tenants/<slug>/tenant.yaml` vive en git y se copia a la imagen. Al arrancar se carga
  en un registro en memoria (`autobot.tenancy.registry`, con `@cache`), y `sync_tenants`
  copia la parte común a la tabla `tenant`.
- `secrets.yaml` (en el servidor) guarda los secretos de canal de cada negocio.
- `tenants/<slug>/datasets/` guarda los horarios de `bus`. Las herramientas `bus-*`
  usan tags de git.
- El repositorio es público. Los únicos negocios versionados son los demos;
  `tenants/autocares-ss/` está en `.gitignore` y solo existe en el disco de la persona.

### 4.2. Modelo de datos

```
tenant (existente; espejo del documento vigente, para FK y RLS; sin cambios de columnas)
  id uuid PK · slug · name · pack · status · timezone · synced_at

tenant_document_version                       ← config versionada
  id bigint PK
  tenant_id uuid FK→tenant ON DELETE CASCADE
  version int                                 (1, 2, 3… por tenant)
  document jsonb                              (TenantDocument completo, sin secretos)
  comment text
  author text                                 (usuario del panel o "command:<nombre>")
  created_at timestamptz
  UNIQUE (tenant_id, version)

tenant_dataset_version                        ← datasets (horarios de bus)
  id bigint PK
  tenant_id uuid FK→tenant ON DELETE CASCADE
  name text                                   ("timetable")
  version int
  files jsonb                                 ({"lineas/x.yaml": "<texto UTF-8>", ...})
  sha256 text                                 (de json.dumps(files, sort_keys=True))
  comment text · author text · created_at
  UNIQUE (tenant_id, name, version)

tenant_secret                                 ← secretos de canal, cifrados
  tenant_id uuid PK FK→tenant ON DELETE CASCADE
  channel_type text                           ("whatsapp" | "telegram")
  ciphertext bytea                            (token Fernet del JSON de secretos)
  updated_at timestamptz · updated_by text

config_revision                               ← contador global de cambios (una fila)
  id smallint PK (=1) · revision bigint · updated_at
```

- **La versión vigente** de un tenant es la de mayor `version`. Las versiones son
  inmutables: volver atrás crea una versión nueva con el contenido de una anterior. La
  única excepción es la purga (§4.6).
- **`TenantDocument`** es el `TenantFile` actual renombrado (`autobot.tenancy.schema`),
  con `id`, `slug`, `name`, `status`, `timezone`, `pack`, `channel`, `testers`, `owner`,
  `demo` y `config`. Valida igual que hoy.
- **Espejo `tenant`.** Lo actualiza la misma transacción que crea cada versión, y
  `sync_tenants` desaparece.
- **Sin RLS.** Estas cuatro tablas son configuración de la plataforma y cada proceso
  necesita leerlas enteras, igual que hoy lee todos los YAML y `secrets.yaml`. `fp_app`
  solo tiene `SELECT` y solo `fp_owner` escribe. Llevan `tenant_id` sin RLS por diseño
  (ADR-009) y figuran en la lista de excepciones del test de aislamiento.
- **Datos personales.** `document.testers.main` contiene teléfonos o BSUID de testers;
  la purga los elimina (§4.6).

### 4.3. Secretos

- Se cifran con **Fernet** (`cryptography`) mediante `MultiFernet`, a partir de
  `SECRETS_ENCRYPTION_KEY` (en el `.env` de `web` y `worker`). La variable admite varias
  claves separadas por comas: la primera cifra y todas descifran. Así se rota la clave.
  En `prod`, `settings.py` valida al arrancar que cada clave es Fernet válida.
- El contenido descifrado se valida con el `SECRETS_SCHEMA` actual (`WhatsAppSecrets` o
  `TelegramSecrets`).
- **La API nunca devuelve valores.** Solo dice qué campos están puestos y cuándo cambiaron.
- Desde el panel se escriben sustituyendo el juego completo del canal. Un demo no tiene
  canal, así que no admite secretos.
- Los secretos de la **plataforma** (demo, bot de avisos, Django, contraseñas de BD)
  siguen en `.env`.

**Por qué no un `.env` ni una clave por cliente:** con este diseño los secretos de cada
cliente ya están separados, uno por fila, sin tocar a los demás, auditados y aplicados
sin reiniciar. Un `.env` por cliente obligaría a montar N ficheros, reiniciar en cada
cambio, renunciar a que el panel los escriba y perder la auditoría. Una clave por cliente
solo serviría para el borrado criptográfico si las claves vivieran fuera de los backups
(un KMS externo). Aquí estarían en la misma BD o en el mismo `.env`, que también se
respaldan, así que añadiría complejidad sin beneficio. Al purgar un negocio se borran sus
secretos, y las copias antiguas caducan con la retención de restic (6 meses; runbook
RGPD).

### 4.4. Registro: carga, recarga y fijado

- **Carga.** `load_registry(sources, packs)` construye el registro a partir de una lista
  de `TenantSource` (documento, datasets y secretos descifrados). La semántica de errores
  es la de hoy:
  - si el documento no valida, va a `errors`;
  - si falla el pack, la config o `load_data`, el tenant queda degradado;
  - si hay claves repetidas, queda ambiguo;
  - si no tiene secretos o no se pueden descifrar, `main` queda desactivado sin degradar.

  Un tenant roto nunca afecta a los demás.
- **Fuentes:**
  - `sources_from_database()` lee de la BD; la usan web, worker y comandos.
  - `source_from_dir(dir)` y `sources_from_directory(root)` leen el formato de directorio
    de §4.9; los usan tests, `tenant_config import` y la puerta de CI de las plantillas.
- **Recarga ("se aplica al guardar").** Cada escritura de config, dataset, secreto o
  estado incrementa `config_revision.revision` en su transacción. `get_registry()`
  mantiene el registro de cada proceso y, **como mucho cada 2 s**, consulta `revision`
  (con `default`). Si cambió, recarga. La recarga está protegida con un candado de hilo
  (gunicorn usa 4 hilos). Si la consulta de revisión falla, sigue con el registro en
  caché y deja un aviso en el log; solo la **primera** carga propaga el error.
- **Fijado por unidad de trabajo.** `registry_scope()` (un ContextVar) fija el registro
  durante un trabajo de la cola o una petición HTTP. Dentro, cada `get_registry()`
  devuelve el mismo objeto, de modo que un cambio de config nunca llega a mitad de un
  trabajo. Lo aplican:
  - el decorador `contextual` de los trabajos;
  - `RegistryScopeMiddleware`, en todas las peticiones.
- **`loaded_registry()`** devuelve el registro ya cargado o `None`, y nunca consulta. Lo
  usa `redact()`: el logging nunca dispara consultas.
- **Datasets.** Si el tenant tiene datasets y su pack tiene `load_data`, los ficheros se
  escriben en `tempfile.TemporaryDirectory()` con la estructura
  `<tmp>/datasets/<name>/<ruta>` y se llama a `load_data(info, config, tmp)`. Después el
  directorio se borra. Una ruta absoluta o con `..` degrada el tenant. El contrato
  `Pack.load_data` no cambia.

### 4.5. Publicar un cambio

Un único servicio, `autobot.tenancy.store`, aplica todos los cambios, vengan de la API o
de un comando. Cada escritura sigue estos pasos:

1. Abre `transaction.atomic(using="owner")`.
2. `SELECT … FROM config_revision WHERE id = 1 FOR UPDATE`, que serializa toda escritura
   de config.
3. Lee el estado vigente (versiones, datasets y secretos) **dentro** de la transacción.
   Comprueba `base_version` (si no es la vigente, responde `conflict` / 409) y las
   reglas de cambio:
   - en `publish` no se puede cambiar `id`, `slug`, `pack`, `status`, `channel.type`
     ni `channel.public_id` (`forbidden_change`);
   - `rollback` conserva los seis valores actuales y toma el resto de la versión elegida.
4. **Valida** construyendo un registro candidato con todos los documentos vigentes y el
   nuevo. Rechaza si el tenant cae en `errors`, queda degradado o queda ambiguo
   (`public_id` o `phone_number_id` repetidos). La validación es solo CPU y `load_data`,
   sin llamadas externas, así que puede ir dentro de la transacción.
5. Inserta la versión, actualiza el espejo `tenant` (`synced_at=now`), incrementa
   `config_revision` y escribe un `audit_event`.
6. Devuelve el número de versión.

Los errores de validación llevan la ruta del campo (`config.services.corte.price_eur:
...`) y **nunca** el valor recibido.

**Alta (`create_tenant`):**

- Genera `id` (UUIDv7) y `public_id` aleatorio cuando hace falta (`store.new_document`).
- Si el pack tiene `load_data` y no se le pasan datasets, **copia los de la plantilla del
  pack como versión 1**. Así un negocio `bus` nuevo valida desde el primer momento; luego
  se sustituyen por terminal.
- **Estado inicial:**
  - desde la API, `onboarding` para un negocio real y `paused` para un demo;
  - desde un comando (`tenant_config import`), se respeta el `status` del documento.
- Si ya existe la fila espejo con ese `id` pero sin ninguna versión, la adopta.

### 4.6. Estados, activación y baja

El estado no se toca en el formulario de config. Tiene acciones propias, y cada una crea
una versión que solo cambia `status`:

| Acción | Desde → hasta | Dónde | Confirmación |
|---|---|---|---|
| Activar | `onboarding` → `active` (no demo) | Panel | Sin bloqueos en la lista de comprobación previa (§9.6) y escribir el slug |
| Pausar | `active` → `paused` | Panel y comando | Diálogo |
| Reactivar | `paused` → `active` | Panel y comando | Diálogo |
| Dar de baja | `active`/`paused`/`onboarding` → `offboarded` | Solo comando `tenant_status <slug> offboard` | Escribir el slug |

**Lista de comprobación previa a activar** (`autobot.tenancy.activation`). Lleva llamadas
externas, así que se calcula **antes** de abrir la transacción, y dentro solo se vuelve a
comprobar el estado.

**Purga** (`purge_tenant`, que solo admite tenants en `offboarded`). Además de lo que
borra hoy (contactos, conversaciones, eventos, mensajes, avisos, demo y dueño), ahora
borra también:

- `metric_event` y `tenant_secret`;
- todas las versiones de datasets;
- todas las versiones del documento salvo una última versión depurada, con
  `testers.main = []` y `owner = null`.

La fila espejo `tenant` se conserva para que los webhooks tardíos sigan respondiendo.
Todo ocurre en una transacción, con `audit_event` `tenant.purge`.

### 4.7. Datasets (horarios de `bus`)

- Se guardan en `tenant_dataset_version` y se cargan como en §4.4.
- **Se gestionan por terminal** (decisión 7):
  - `tenant_dataset export <slug> <name> <dir|->` saca la versión vigente a un directorio
    o, con `-`, como tar.gz por stdout;
  - `tenant_dataset import <slug> <name> <dir|-> --comment "..."` valida con el pack y
    publica.
- Al importar:
  - el tar se extrae con `tarfile.extractall(filter="data")`;
  - solo se aceptan ficheros de texto UTF-8;
  - si el `sha256` coincide con la versión vigente, no se hace nada ("sin cambios").
- Las herramientas `make bus-*` trabajan sobre `datos/<slug>/` (ignorado por git). La
  revisión compara con `datos/<slug>/.publicado/`, que se obtiene exportando.
- El panel solo **muestra** las versiones de cada dataset.

### 4.8. Plantillas de pack y demos

- Cada pack trae su plantilla en `src/packs/<pack>/template/`:
  - `document.yaml`: un documento de demo completo, con el **mismo `id`** que el demo
    actual;
  - `datasets/<name>/...`: solo si el pack tiene datasets.

  Se declara con `Pack.template: Path | None`.
- **`Pack.template_blank: tuple[str, ...]`** lista las claves de `config` que se vacían
  (`null`) al usar la plantilla como punto de partida de un negocio nuevo. En `salon`
  son `calendar_id`, `contact_phone` y `business_name`, para que un cliente nuevo no
  reserve en el calendario del demo.
- Usos de la plantilla:
  - tests y escenarios (sustituye a `tenants/demo-*`);
  - punto de partida del asistente de alta (su `config` con `template_blank` vacío);
  - datasets iniciales de un alta (§4.5);
  - **creación inicial** de los demos con `seed_demos`, que crea el demo de cada pack solo
    si el tenant no tiene ninguna versión.

  Después de eso, la verdad es la base y los demos se editan en el panel.
- La carpeta `tenants/` desaparece del repositorio y de la imagen, pero sigue en
  `.gitignore`: la persona conserva su copia local de `autocares-ss`. La CI falla si
  `git ls-files tenants datos` no está vacío.

### 4.9. Formato de directorio: importar, exportar y validar

- **Un tenant por directorio:**
  - `<dir>/document.yaml`; también se acepta el nombre antiguo `tenant.yaml`, solo para
    importar;
  - `<dir>/datasets/<name>/**`.
- `tenant_config export <slug> <dir|->` escribe ese formato. Los secretos **nunca** se
  exportan.
- `tenant_config import <dir|-> [--secrets <yaml>] [--comment "..."]` crea el tenant o
  publica una versión, con todas las reglas de `store` y autor `command:tenant_config`.
  `--secrets` acepta el formato del `secrets.yaml` de hoy (slug → secretos) y toma la
  entrada del slug. Con `-`, lee un tar.gz por stdin, que puede llevar un `secrets.yaml`
  en la raíz con ese mismo formato (`make tenant-push`, §12).
- `tenant_config validate --all` vuelve a validar los documentos vigentes con el código
  actual y sale con código ≠ 0 si alguno no valida. `deploy.sh` lo ejecuta con la imagen
  nueva **antes** de cambiar los servicios: un cambio de código que invalide una config
  real aborta el despliegue.

## 5. Permisos de BD reproducibles

- **`src/autobot/db_grants.py`** declara el estado deseado como una lista ordenada de
  sentencias SQL **idempotentes** (GRANT, REVOKE, ALTER DEFAULT PRIVILEGES y
  `GRANT EXECUTE`):
  - **`fp_app`:**
    - `REVOKE INSERT, UPDATE, DELETE` sobre `tenant` (hoy está en `0002` y se pierde
      al restaurar) y sobre las cuatro tablas de config;
    - `REVOKE ALL` sobre `audit_event`, `saved_query` y las tablas de autenticación
      (`auth_*`, `django_session`, `otp_totp_totpdevice`);
    - `REVOKE DELETE` sobre `ops_alert`.
  - **`fp_readonly`:** `SELECT` en todo `public` y en las tablas futuras, salvo las de
    `SENSITIVE_TABLES` (`tenant_secret`, `auth_user`, `django_session`,
    `otp_totp_totpdevice`).
  - **`EXECUTE`** de `purge_platform_history` para `fp_app` (§7.1).
- **`manage.py apply_grants`** (con `owner`) lo aplica. Se ejecuta:
  - en cada **migración** que cree tablas o cambie permisos (`RunPython` que llama a la
    misma función);
  - en cada **despliegue** (`deploy.sh`, después de `migrate`);
  - después de cada **restauración** (`restore.sh`, porque `pg_restore --no-acl` pierde
    los permisos).

  `restore-test.sh` verifica con `has_table_privilege` que se han aplicado.
- **Roles.** `deploy/postgres/init-roles.sh` (idempotente) crea `fp_owner`, `fp_app` y
  `fp_readonly` y fija sus contraseñas desde el entorno. `deploy.sh` y `make db-roles`
  (en local) lo ejecutan siempre: los roles nuevos y las contraseñas rotadas se aplican
  solos.
- **Políticas RLS.** Viven en migraciones porque `pg_restore` sí las restaura. Toda tabla
  con RLS tiene exactamente dos políticas:
  - `tenant_isolation`, la de hoy;
  - `readonly_all`, para la consola (§8.2).

  El test de aislamiento lo exige.

## 6. Backend del panel

### 6.1. Organización

`autobot.panel` es un **subpaquete** de la app `autobot`, no una app de Django nueva.
Usa **django-ninja**, con esquemas Pydantic y OpenAPI generado.

```
src/autobot/
  db_router.py          # AuthDatabaseRouter (§3.3)
  db_grants.py          # permisos deseados (§5)
  tenancy/
    schema.py  registry.py  models.py  tx.py
    store.py            # única escritura de config (§4.5)
    crypto.py           # MultiFernet (§4.3)
    activation.py       # lista de comprobación previa a activar (§9.6)
  ops/
    models.py           # AuditEvent, OpsAlert, SystemSample, SavedQuery
    audit.py            # audit.record(...)
    actions.py          # marcar enviado / reenviar / reintentar (antes en admin.py)
    status.py           # tenant_status(): nivel de salud de un negocio (§7.5)
    system.py           # lectura de /proc y de state/ops (§7.4)
    logship.py          # envío a VictoriaLogs (§7.3)
    check.py            # ops_check: collect() + sync_alerts() (§7.1)
  panel/
    api.py              # NinjaAPI; monta routers; manejadores de error
    auth.py             # PanelAuth, CsrfOnly y router auth
    middleware.py       # PanelGateMiddleware (§3.2)
    errors.py           # ApiError
    routers/            # overview tenants packs activity contacts incidents
                        # logs data system audit
    services/           # overview activity catalog query logs system forms
```

- Los routers son finos: validan la entrada, llaman a servicios y devuelven esquemas.
- `core`, `integrations` y `packs` mantienen sus reglas de importación. El panel solo
  llega a los packs a través de `packs.registry`.

### 6.2. Autenticación y sesión

- **Usuario.** Un `django.contrib.auth.User` con `is_staff=True` y un `TOTPDevice`
  confirmado. Se crea con `manage.py panel_user create <usuario>`, que pide la
  contraseña y muestra una vez la URI `otpauth://` y su QR en la terminal (`qrcode` pasa
  a dependencia de ejecución). Esa URI es una credencial y nunca va a logs. Hay un solo
  rol.
- **Endpoints `auth`:**

  | Endpoint | Autenticación | Qué hace |
  |---|---|---|
  | `GET auth/csrf` | sin auth | Pone la cookie CSRF |
  | `POST auth/login {username, password, otp}` | `CsrfOnly`: sin sesión, pero con CSRF comprobado | Autentica (abajo) |
  | `POST auth/logout` | sesión | Cierra la sesión |
  | `GET auth/me` | sesión | `{username}`, o 401 |

- **Login**, todo dentro de `transaction.atomic(using="owner")`:
  1. comprueba el bloqueo por usuario: con 5 fallos en 15 min, el login queda bloqueado
     15 min (caché). No se usa la IP, que siempre es la del contenedor `panel`;
  2. `authenticate`;
  3. `select_for_update` del `TOTPDevice` confirmado y `verify_token`, como hacía
     `OwnerOTPForm`;
  4. `login` y `django_otp.login`.

  Errores siempre genéricos ("Credenciales no válidas"). Se audita `auth.login` y
  `auth.login_failed` (sin contraseña, con el usuario truncado a 150 caracteres).
- **Cookies:**

  | Ajuste | Valor |
  |---|---|
  | Nombres | `autobot_panel_session` y `autobot_panel_csrftoken`, para no chocar con otras apps en `127.0.0.1` |
  | Duración de la sesión | 12 h |
  | `HttpOnly` | sí |
  | `SameSite` | `Strict` |
  | `Secure` | `False`: el tráfico va por el túnel SSH a `127.0.0.1` (ADR-008) |

- **CSRF:** cabecera `X-CSRFToken` en toda escritura.
- Todas las rutas, salvo `auth/csrf` y `auth/login`, exigen
  `is_authenticated and is_staff and is_verified()`. Si no se cumple, 401.

### 6.3. Convenciones de la API

- Prefijo `/api/panel/`, JSON en `snake_case`. `docs_url=None`: no hay Swagger, porque no
  hay ficheros estáticos.
- Fechas en ISO 8601 UTC. El frontend las muestra en `Europe/Madrid`.
- **Errores:** `{"code", "message" (en español), "details": [str]}`.

  | Código | Estado HTTP |
  |---|---|
  | `validation_error` | 422 |
  | `conflict` | 409 |
  | `not_found` | 404 |
  | `forbidden_change`, `invalid_status`, `bad_request` | 400 |
  | `unauthorized` | 401 |
  | `csrf` | 403 |
  | `unavailable`, `logs_unavailable` | 503 |

- **Paginación.** Las listas largas usan un cursor opaco: `?cursor=<texto>&limit=50`
  (máximo 200), que devuelve `{"items": [...], "next_cursor": "..." | null}`. El cursor es
  base64url de JSON con la clave de orden del último elemento.
- **"Mes en curso"** es siempre `month_to_date(now, tz)`: en `Europe/Madrid` para las
  cifras globales y en la zona del tenant para las suyas.
- **OpenAPI.** `manage.py export_openapi panel/openapi.json` escribe el esquema con rutas
  relativas al prefijo (`get_openapi_schema(path_prefix="")`; hay que comprobarlo con la
  versión instalada). El frontend usa `baseUrl: "/api/panel"`. `make api` regenera el
  OpenAPI y los tipos de TypeScript, y la CI falla si no coinciden con lo commiteado.

### 6.4. Endpoints

| Método y ruta | Devuelve / hace |
|---|---|
| `GET overview` | Todo el Resumen (§9.4) en una llamada |
| `GET packs` | Packs: nombre, `has_datasets`, `has_template` |
| `GET packs/{pack}/schema` | JSON Schema del `TenantDocument`, con `config` = schema del pack, más `ui_schema` (§9.5) |
| `GET packs/{pack}/template` | `config` de la plantilla, con `template_blank` a `null` |
| `GET tenants` | Filas `TenantRow` (§9.4) |
| `POST tenants` | Alta (§4.5) |
| `GET tenants/{slug}` | Ficha (documento vigente, versión, estado del registro, salud, canal, dueño, KPIs del mes) |
| `GET tenants/{slug}/versions` · `GET …/versions/{n}` | Historial y documento de una versión |
| `PUT tenants/{slug}/document` | `{document, base_version, comment}`: publica |
| `POST tenants/{slug}/rollback` | `{version, comment}` |
| `POST tenants/{slug}/status` | `{action: "activate"\|"pause"\|"resume", confirm_slug?}` (la baja no está en la API) |
| `GET tenants/{slug}/activation-checklist` | `[{key, label, ok, blocking, detail}]` |
| `GET tenants/{slug}/secrets` · `PUT …/secrets` | Estado, sin valores · sustituir |
| `GET tenants/{slug}/datasets` | Versiones de cada dataset |
| `GET tenants/{slug}/summary` | Bloque del resumen del dueño del mes en curso |
| `POST tenants/{slug}/health-check` | Fuerza la comprobación de salud y devuelve los problemas |
| `GET tenants/{slug}/notifications` | Avisos al dueño |
| `GET tenants/{slug}/contacts?search=` | Contactos |
| `GET contacts/{id}` | Conversación de un contacto (se audita) |
| `GET activity?tenant=&kinds=&status=&cursor=` | Línea temporal (§7.2) |
| `GET incidents` | Alertas abiertas, envíos `unknown`/`failed` y trabajos fallidos |
| `POST outbound/{id}/mark-sent` · `POST outbound/{id}/resend` | `ops.actions` (reenviar exige `{"confirm_duplicate_risk": true}`) |
| `POST jobs/{id}/retry` | `ops.actions` |
| `POST alerts/{id}/resolve` | Solo alertas con `auto_resolves=false` |
| `GET alerts?state=open\|resolved&cursor=` | Todas las alertas (lo que el bot mandó y lo que no) |
| `GET jobs?status=&queue=&cursor=` | Trabajos y sus eventos |
| `GET logs?tenant=&level=&service=&q=&start=&end=&limit=` | Logs (§7.3) |
| `GET system` | §7.4 |
| `GET data/tables` · `GET data/tables/{name}` | Catálogo (§8.1) |
| `POST data/query` | `{sql, tenant: slug\|null}` (§8.2) |
| `GET/POST data/saved-queries` · `PUT/DELETE data/saved-queries/{id}` | Consultas guardadas |
| `GET audit?tenant=&action=&cursor=` | Auditoría |

### 6.5. Auditoría

```
audit_event
  id uuid (v7) PK · at timestamptz · actor text · action text
  tenant_id uuid NULL (sin FK: sobrevive a la purga) · target_type text · target_id text
  summary text (en español) · details jsonb
```

- `ops.audit.record(...)` escribe con `owner` dentro de su propio
  `transaction.atomic(using="owner")`, que se une a la transacción del cambio si existe.
- **Acciones:**
  - negocio: `tenant.create`, `tenant.publish`, `tenant.rollback`, `tenant.status`,
    `tenant.secrets`, `tenant.purge`, `dataset.import`;
  - incidencias: `outbound.mark_sent`, `outbound.resend`, `job.retry`, `alert.resolve`;
  - consulta: `contact.view`, `data.query`;
  - acceso: `auth.login`, `auth.login_failed`.
- **`details` nunca lleva secretos.** `record` lanza `ValueError` si alguna clave, a
  cualquier profundidad, coincide exactamente con alguna de `{"token", "secret",
  "password", "access_token", "app_secret", "verify_token", "bot_token",
  "webhook_secret", "otp"}`. En secretos solo se guardan los **nombres** de los campos.
- `data.query` guarda la consulta, el tenant, las filas, si se truncó, la duración y el
  error si lo hubo; nunca los resultados. `contact.view` guarda el id del contacto.
- **Retención:** 12 meses (§7.1).

## 7. Observabilidad

### 7.1. Alertas persistidas: el bot es un reflejo del panel

```
ops_alert
  id uuid (v7) PK · kind text · tenant_id uuid NULL (sin FK)
  severity text  ("critical" 🔴 | "warning" 🟠 | "notice" 🟡 | "info" 🟢; se deduce del
                  primer emoji del texto; "warning" si no hay emoji)
  text text · first_seen_at · last_seen_at · occurrences int
  sent_count int · last_sent_at NULL
  last_delivery text  ("sent" | "failed" | "cooldown" | "unconfigured")
  auto_resolves bool
  resolved_at NULL · resolved_by text NULL  ("auto" | "info" | usuario)
  UNIQUE (kind, tenant_id) WHERE resolved_at IS NULL   (NULLS NOT DISTINCT)
```

- **`ops_check` se divide en dos:**
  - `collect() -> list[Finding]` (con `Finding` = `kind`, `tenant_id`, `text`) evalúa lo
    mismo que hoy y no envía nada;
  - `sync_alerts(findings)` hace el resto.

  `run()` = `sync_alerts(collect())` más la muestra de sistema y el latido.
- **`send_ops_alert(kind, tenant_id, text, *, informational=False)`:**
  1. Dentro de la transacción del `pg_advisory_xact_lock` de hoy, hace *upsert* de la
     alerta abierta: crea, o suma `occurrences` y pone `last_seen_at` y el `text` actual.
  2. Decide si se envía con el enfriamiento de 30 min de hoy.
  3. Fuera de esa transacción llama a Telegram. Después, en otra transacción corta,
     guarda `last_delivery`, `sent_count` y `last_sent_at`.
  4. `informational=True` (p. ej. "desplegado bien") guarda la alerta ya resuelta
     (`resolved_by="info"`) y no tiene enfriamiento.

  La firma conserva los argumentos actuales.
- **`auto_resolves`** es `false` para `MANUAL_KINDS = {"deploy_aborted",
  "deploy_rollback"}` y `true` para el resto. Todas las demás alertas salen hoy de
  `ops/check.py`.
- **Resolución automática:** al final de `sync_alerts`, toda alerta abierta con
  `auto_resolves=true` cuyo `(kind, tenant_id)` no esté en `findings` queda
  `resolved_at=now, resolved_by="auto"`.
- **Resolución manual:** solo de alertas con `auto_resolves=false`, desde el panel.
- **Al resolverse** (sola o a mano) se borra la clave de enfriamiento `ops:<digest>` en
  la caché. Si el problema vuelve, se avisa al momento.
- Los avisos al dueño ya se guardan (`Notification`) y se ven en la ficha del cliente.
- **Permisos:** el worker (`fp_app`) tiene `SELECT, INSERT, UPDATE` sobre `ops_alert`,
  sin `DELETE`.
- **Retención:** `purge_platform_history(cutoff timestamptz)` es una función
  `SECURITY DEFINER` de `fp_owner` con `SET search_path = public, pg_temp` y `EXECUTE`
  para `fp_app`. Borra las `ops_alert` resueltas antes de `cutoff` y los `audit_event`
  anteriores a `cutoff`. `retention_cleanup` la llama con `now − 12 meses`, bajo el mismo
  `RETENTION_CLEANUP_ENABLED`.

### 7.2. Actividad: logs que se entienden

Es una línea temporal hecha con datos que ya están en la base, contada en español.

| Fuente | Momento (`at`) | Ejemplo |
|---|---|---|
| `inbound_event` (`kind=message`) | `received_at` | 📩 **Peluquería de Prueba** · Telegram · mensaje de *Ana (···0001)*: «quiero cita» · procesado |
| `outbound_message` | `created_at` | 📤 respuesta a *Ana*: «¿Qué día?» · enviada · utility · facturable / ⏳ pendiente / ❓ ambigua / ❌ fallida: `<last_error>` |
| `notification` | `created_at` | 🔔 aviso al dueño `booking_created` · enviado |
| `ops_alert` | `first_seen_at` | 🚨 alerta 🔴 `<text>` · enviada a Telegram (×3) |
| `audit_event` | `at` | ⚙️ config publicada v7 por `mariano`: «cambio de horario» |
| `procrastinate_events` (`type=failed`) con su trabajo | `at` | 💥 trabajo `send_message` falló (intento 3) |

- **Orden total:** `(at DESC, kind_rank ASC, id DESC)`, con
  `kind_rank` = inbound 0, outbound 1, notification 2, alert 3, audit 4, job 5.
- **Paginación.** El cursor es la tupla del último elemento. Cada fuente se consulta con
  la condición equivalente
  (`at < c.at OR (at = c.at AND (rank > c.rank OR (rank = c.rank AND id < c.id))))`) y
  `LIMIT limit + 1`. Después se mezcla y se corta. Así no hay duplicados ni saltos.
- **Filtro por tenant:**
  - `tenant_id` en las tablas que lo tienen;
  - en trabajos, `procrastinate_jobs.args->>'tenant_id'`;
  - las alertas sin tenant salen solo sin filtro.
- **Cada elemento:** `{id, at, kind, tenant (slug|null), channel, icon, title, detail,
  status, link}`. `link` es una ruta del frontend.
- **Pares entrada → salida** por `outbound_message.inbound_event_id`, en la vista de un
  contacto.
- **Textos legibles.** `describe_inbound(channel, payload)` y `describe_outbound(payload)`
  nunca lanzan excepciones. Si no hay contenido (el payload se vacía a los 30 días),
  muestran "(contenido no disponible)".
- **Datos personales:** nombre, teléfono y contenido se muestran (decisión 13). La
  plataforma es encargada del tratamiento de cada negocio y el acceso es para dar
  servicio y soporte. Cada vista de contacto queda auditada (`contact.view`). Los
  contratos de encargo deben cubrirlo (runbook RGPD).

### 7.3. Logs técnicos (VictoriaLogs)

- **Envío:** `VictoriaLogsHandler` en el `LOGGING` de Django, con el filtro `privacy`
  igual que la consola. Se activa solo si `VICTORIALOGS_URL` está definida.
  - `emit` pone la línea en una cola acotada de 10 000 elementos; si está llena, la
    descarta y lo cuenta.
  - Un hilo *daemon* por proceso (se vuelve a crear si cambia el PID, por el fork de
    gunicorn) envía lotes con `POST /insert/jsonline` cada 2 s o cada 500 líneas, con
    timeout de 2 s.
  - Si el envío falla, descarta el lote. Nunca bloquea ni lanza excepciones, y nunca
    escribe logs desde el propio handler.
- **Campos:** los de `JsonFormatter` (`ts`, `level`, `msg`, `service`, `tenant`,
  `channel`, `event_id`, `job`, `exception`) más `release`. Se envían con
  `_stream_fields=service&_time_field=ts&_msg_field=msg`.
- **Retención:** `-retentionPeriod=31d`. Las consultas se recortan al día 1 del mes en
  curso; si se recorta, la respuesta lo indica con `clipped: true`.
- **Consulta.** La LogsQL se construye a partir de los filtros, con valores entrecomillados
  y escapados. No se acepta LogsQL libre. El filtro `tenant` acepta un slug y busca por el
  slug **o** por el id, porque hoy el campo lleva uno u otro.
- Los errores siguen yendo también a Sentry. Si `SENTRY_PROJECT_URL` está definida, el
  panel enlaza a ese proyecto.

### 7.4. Sistema

- **Máquina, en vivo:**
  - CPU %: dos lecturas de `/proc/stat` separadas 200 ms;
  - RAM: `MemTotal` y `MemAvailable` de `/proc/meminfo`;
  - `/proc/loadavg` y `/proc/uptime`;
  - disco: `shutil.disk_usage("/")`.

  Muestran los valores del host; hay que comprobarlo en el primer despliegue.
- **Muestras:** `ops_check` guarda una cada 5 min y borra las de más de 62 días.

  ```
  system_sample
    id bigint PK · taken_at · cpu_pct · mem_used_pct · load1 · disk_used_pct · db_bytes
  ```

- **Servicios:**
  - `web`: siempre bien (es quien responde);
  - `worker`: `procrastinate_workers.last_heartbeat` de hace menos de 60 s;
  - `db`: `SELECT 1`, `pg_database_size` y las 5 tablas más grandes;
  - `victorialogs`: `GET /health`;
  - Caddy público: caducidad del certificado de `PUBLIC_HOST:443`, en caché 1 h.
- **Colas:** pendientes por cola y antigüedad del evento `deferred` más antiguo (el cálculo
  del `/admin/estado/` de hoy).
- **Backups y despliegues:**
  - `deploy/backup.sh` escribe `state/ops/backup.json` (`{finished_at, ok, dump_bytes}`),
    de forma atómica;
  - `deploy/deploy.sh` añade una línea a `state/ops/deploys.jsonl`
    (`{at, sha, previous, result}`) por cada intento.

  `web` monta ambos en solo lectura en `/run/ops`.
- **Versión:** `RELEASE_SHA`.

### 7.5. Salud de un negocio: una sola función

`ops.status.tenant_status(tenant, *, open_alerts) -> TenantStatus(level, reasons)`, con
`level` ∈ `ok`, `notice`, `warning`, `critical`, `unknown`:

| Nivel | Cuándo |
|---|---|
| `critical` | Degradado; o activo, no demo y con `main` desactivado; o un problema 🔴 en la caché `health:<id>`; o alertas abiertas `critical` del tenant |
| `warning` | Problemas 🟠 o alertas `warning` |
| `notice` | Solo 🟡 |
| `unknown` | Falta la caché de salud o tiene más de 24 h |
| `ok` | Ninguno de los anteriores |

La usan el Resumen, la lista de clientes, la ficha y la lista de comprobación previa a
activar. No hay otra lógica de salud.

## 8. Datos

### 8.1. Catálogo

- `panel/services/catalog.py` describe **en español** cada tabla: para qué sirve, quién la
  escribe, su retención, si lleva RLS y la explicación de las columnas que no se entienden
  solas.
  - Un test exige una entrada para cada tabla que exista en la base de test, y que no haya
    entradas sobrantes.
  - En una base real, las tablas sin entrada se muestran en el grupo "Sin catalogar".
- **Grupos:** Negocios y config · Conversaciones y mensajes · Avisos y métricas · Demo y
  dueños · Cola de trabajos · Operación del panel · Django interno.
- **Datos en vivo de cada tabla:**
  - filas: `pg_class.reltuples`, o `count(*)` exacto si la estimación es menor de
    100 000, con `approx` según el caso;
  - tamaño (`pg_total_relation_size`);
  - filas por tenant, si la tabla tiene `tenant_id`;
  - FK entrantes y salientes.
- **Detalle de una tabla.** Solo se aceptan nombres del catálogo. Muestra columnas, tipos,
  relaciones y las 20 filas más recientes, con todos los datos (decisión 13) salvo
  `HIDDEN_COLUMNS`, que siempre salen como `"<oculto>"`:

  | Tabla | Columna |
  |---|---|
  | `tenant_secret` | `ciphertext` |
  | `auth_user` | `password` |
  | `django_session` | `session_data` |
  | `otp_totp_totpdevice` | `key` |
  | `owner_link` | `invite_hash` |
  | `platform_cache` | `value` |

### 8.2. Consola SQL de solo lectura

- **Rol `fp_readonly`:** `LOGIN NOBYPASSRLS`, solo `SELECT`, sin acceso a
  `SENSITIVE_TABLES` (§5). Alias `readonly` (`DB_READONLY_URL`, solo en `web`) con
  `CONN_MAX_AGE = 0`, para que nada de una consulta sobreviva en la conexión.
- **Modo "todos los clientes".** Cada tabla con RLS tiene además esta política:

  ```sql
  CREATE POLICY readonly_all ON <tabla> FOR SELECT TO fp_readonly
    USING (current_setting('app.readonly_all', true) = 'on');
  ```

  - Si se elige un cliente, la consola fija `app.tenant_id`; si no, `app.readonly_all`.
  - La migración la crea en todas las tablas que hoy tienen `tenant_isolation` (consultando
    `pg_policies`), y toda migración futura que añada RLS añade también `readonly_all`
    (regla en CLAUDE.md, vigilada por el test de aislamiento).
  - Es un filtro de comodidad para quien opera, no una barrera. La barrera es que el rol
    solo puede leer.
- **Ejecución** (`panel/services/query.py`):
  1. Recorta los espacios y **un** `;` final. Rechaza SQL vacío o de más de 20 000
     caracteres.
  2. Abre `transaction.atomic(using="readonly")` con:
     - `SET TRANSACTION READ ONLY`;
     - `SET LOCAL statement_timeout = '10s'`;
     - `SET LOCAL idle_in_transaction_session_timeout = '15s'`;
     - `set_config('app.tenant_id', …, true)` o `set_config('app.readonly_all', 'on', true)`.
  3. Ejecuta con un **cursor con nombre** de psycopg (servidor:
     `DECLARE … CURSOR FOR <sql>`). Solo admite **una** sentencia `SELECT`, `WITH … SELECT`
     o `VALUES`; `EXPLAIN` no está admitido (decisión 15b). El SQL va sin parámetros, así
     que `%` no se interpreta.
  4. Lee como mucho 1 001 filas con `fetchmany`, para saber si hay más.
  5. **Siempre** marca rollback. Después audita `data.query` en una transacción `owner`
     aparte.
- **Respuesta:** `{columns: [{name, type}], rows: [[...]], truncated, duration_ms}`.
  - `jsonb` va como JSON;
  - `bytea` y `memoryview` como `"<N bytes>"`;
  - `Decimal`, `UUID` y fechas, como texto;
  - un error de PostgreSQL devuelve 400 con su mensaje, sin trazas.
- **Consultas guardadas:** `saved_query (id, name, sql, created_at, updated_at)`, con
  cuatro de ejemplo (mensajes por día del mes, coste por cliente, contactos más activos,
  trabajos fallidos recientes).

## 9. Frontend

### 9.1. Stack

| Pieza | Elección |
|---|---|
| Build | Vite, TypeScript `strict` y `noUncheckedIndexedAccess` |
| UI | React 19, Tailwind CSS v4, **shadcn/ui** (Radix), `lucide-react` |
| Rutas | TanStack Router (por ficheros, tipadas) |
| Datos | TanStack Query; `openapi-fetch` con tipos de `openapi-typescript` |
| Tablas | TanStack Table (y `@tanstack/react-virtual` en Logs) |
| Gráficas | Recharts (charts de shadcn) |
| Formularios | `@rjsf/core` v6 (tema `@rjsf/shadcn` si encaja; si no, plantillas propias) para la config; `react-hook-form` + `zod` para el resto |
| Editores | CodeMirror 6 (`@uiw/react-codemirror`, `@codemirror/lang-sql`, `@codemirror/lang-yaml`) y `yaml` |
| Diff | `jsondiffpatch` |
| QR | `qrcode.react` (enlace público del canal) |
| Notificaciones | `sonner` |
| Fechas | `date-fns` y `date-fns-tz` (`es`, `Europe/Madrid`) |
| Calidad | Biome, `tsc --noEmit`, Vitest + Testing Library |
| Paquetes | pnpm, Node 24 LTS |
| Fuentes | Geist Sans y Geist Mono, autoalojadas (`@fontsource`) |

### 9.2. Estructura

```
panel/
  package.json  pnpm-lock.yaml  vite.config.ts  tsconfig.json  biome.json
  components.json  index.html  openapi.json  Dockerfile  Caddyfile
  src/
    main.tsx
    routes/                      # finas; importan de features/
      __root.tsx  login.tsx  _app.tsx
      _app/index.tsx
      _app/clientes/index.tsx  _app/clientes/nuevo.tsx
      _app/clientes/$slug.tsx  _app/clientes/$slug/{index,configuracion,historial,
                                 canal,actividad,contactos,avisos,datos}.tsx
      _app/actividad.tsx  _app/incidencias.tsx  _app/logs.tsx
      _app/datos/index.tsx  _app/datos/$tabla.tsx  _app/datos/consulta.tsx
      _app/sistema.tsx  _app/auditoria.tsx
    api/
      client.ts  schema.d.ts (GENERADO)
    features/
      auth/ overview/ tenants/ onboarding/ activity/ incidents/ logs/ data/ system/ audit/
        └─ api.ts · components/ · *.test.tsx
    components/
      ui/ (shadcn)  app-shell.tsx  sidebar.tsx  topbar.tsx  command-menu.tsx
      status-badge.tsx  kpi-card.tsx  data-table.tsx  page-header.tsx  empty-state.tsx
      error-state.tsx  confirm-dialog.tsx  time-ago.tsx  json-diff.tsx  code-editor.tsx
    lib/ format.ts  utils.ts
    styles/globals.css
```

Una sección nueva es una carpeta en `features/`, sus rutas y su router en
`autobot/panel/routers/`.

### 9.3. Diseño visual y navegación

- **Tema oscuro único** (la clase `dark` siempre en `<html>`):

  | Uso | Color |
  |---|---|
  | Fondo | `#09090b` |
  | Superficies | `#18181b` |
  | Bordes | `#27272a` |
  | Texto principal / secundario | `#fafafa` / `#a1a1aa` |
  | Acento | `#818cf8` |
  | `ok` / `notice` | emerald-400 / sky-400 |
  | `warning` / `critical` | amber-400 / red-400 |
  | `unknown` | zinc-400 |

  Radio de 10 px, sombras mínimas y cifras tabulares (Geist Mono). Estilo limpio, a lo
  Linear o Vercel.
- **Menú lateral fijo**, colapsable a iconos y con el estado guardado en `localStorage`:
  Resumen · Clientes · Actividad · Incidencias (n) · Logs · Datos · Sistema · ─ ·
  Auditoría · usuario · Salir.
- **Barra superior:**
  - migas de pan;
  - ⌘K: saltar a un cliente, sección o tabla, o buscar un id;
  - indicador de estado global (`status.level` de `overview`), que enlaza a Incidencias.
- **Pestañas horizontales** en la ficha de cliente y en Datos.
- **Refresco**, solo con la pestaña visible: Resumen, Incidencias y Sistema cada 30 s;
  Actividad cada 15 s (solo la primera página).
- **Toda vista tiene tres estados:**
  - cargando (*skeleton*);
  - vacío, con un texto que explica por qué no hay datos;
  - error, con el mensaje del backend y un botón "Reintentar".

### 9.4. Pantallas

**Login:** usuario, contraseña y código TOTP de 6 dígitos, y "Entrar".

**Resumen** (`/`):

```
┌─ ✅ Todo bien · 3 clientes funcionando · actualizado hace 12 s ──────────────┐
│  (o ⚠️ 2 incidencias: autocares-ss canal sin secretos · …  [Ver])              │
└───────────────────────────────────────────────────────────────────────────────┘
┌ Clientes ──────┐┌ Mensajes (mes) ─┐┌ Usuarios (mes) ─┐┌ Coste WhatsApp (mes) ┐
│ 1 activo       ││ 1.240 entrada   ││ 87              ││ 12,40 €              │
│ 2 demos · 0 ⏸  ││ 1.310 salida    ││                 ││ 310 facturables      │
└────────────────┘└─────────────────┘└─────────────────┘└──────────────────────┘
┌ Mensajes por día (barras entrada/salida) ┐┌ Métricas de packs (p. ej. consultas)┐
└──────────────────────────────────────────┘└─────────────────────────────────────┘
┌ Clientes: negocio · pack · canal · estado · salud · msg mes · coste · últ. act. ┐
└─────────────────────────────────────────────────────────────────────────────────┘
┌ Sistema: CPU · RAM · disco · backup · TLS · versión ┐┌ Últimas alertas ─────────┐
└─────────────────────────────────────────────────────┘└──────────────────────────┘
```

**Datos de `GET overview`:**

```
Overview {
  generated_at
  status: {level: "ok"|"warning"|"critical", problems: [{text, tenant, link}] (≤ 5)}
  tenants: {active, onboarding, paused, demos, total}           (sin offboarded)
  month: {start, inbound, outbound, users, billable, cost_eur,
          by_day: [{date, inbound, outbound}], metrics: [{pack, kind, label, total}]}
  tenant_rows: [TenantRow]
  incidents_open: int
  system: {cpu_pct, mem_used_pct, disk_used_pct, last_backup_at, backup_ok,
           tls_days_left, release, deployed_at}
  recent_alerts: [AlertBrief] (las 5 últimas, abiertas o no)
}
TenantRow {slug, name, pack, channel: "whatsapp"|"telegram"|"demo", status,
           health: TenantStatus.level, health_reasons, health_checked_at,
           inbound_month, outbound_month, cost_eur_month, last_activity_at}
```

**Reglas del Resumen:**

| Dato | Cómo se calcula |
|---|---|
| `inbound` | `inbound_event` con `kind="message"` desde el día 1 del mes (`received_at`) |
| `outbound` | `outbound_message` en estado `sent` desde el día 1 (`sent_at`) |
| `users` | Contactos distintos de esas salidas |
| `billable` | Salidas con `billable=True` desde el día 1 (`sent_at`) |
| `cost_eur` | Por tenant, con `costs.cost_of(...)`, la fórmula del resumen del dueño; el total es la **suma de los costes por tenant ya redondeados**, para que la tabla sume |
| `metrics` | `metric_event` del mes por `(pack, kind)`, con etiqueta de `METRIC_LABELS` (`schedule_query` → «Consultas de horario»); si no hay etiqueta, el propio `kind` |
| `status.level` | `critical` si hay alertas `critical` abiertas, algún tenant no `offboarded` en `critical`, o envíos `failed` o `unknown` de más de 10 min; `warning` si hay alertas `warning` o algún tenant en `warning`; si no, `ok`. `notice` y `unknown` **no** cambian el nivel global |
| `incidents_open` | Alertas abiertas + envíos `unknown` de más de 10 min + envíos `failed` + trabajos `failed` |
| `last_activity_at` | El mayor entre el último `received_at` y el último `sent_at` del tenant |

**Clientes** (`/clientes`): la misma tabla, con filtros por pack y estado, búsqueda y el
botón "Nuevo cliente".

**Ficha de cliente** (`/clientes/:slug`): cabecera con nombre, estado, salud y acciones
(Activar, Pausar o Reactivar según el estado, y "Comprobar salud"). Pestañas:

| Pestaña | Contenido |
|---|---|
| Resumen | KPIs del mes; bloque del dueño (botón "Cargar", porque puede consultar Calendar); salud y sus motivos; alertas abiertas del cliente |
| Configuración | Editor (§9.5) |
| Historial | Versiones con autor, fecha y comentario; diff con la anterior; "Volver a esta versión" |
| Canal | Tipo e ids; URL del webhook; **enlace público y QR** (`wa.me/<display_phone>` o `t.me/<bot_username>`, como `tools/qr.py`); estado de los secretos y "Sustituir secretos"; testers; dueño enlazado |
| Actividad | La línea temporal del cliente |
| Contactos | Tabla y conversación (pares entrada → salida y `state` en JSON) |
| Avisos | `notification` |
| Datos | Versiones de datasets (solo `bus`) |

### 9.5. Editor de configuración

- **Formulario** generado con `GET packs/{pack}/schema`. El backend combina
  `TenantDocument.model_json_schema()` y `config_schema.model_json_schema()`, y prefija los
  `$defs` para que no choquen. El `ui_schema` incluye:
  - el orden de los grupos: General, Canal, Config del pack;
  - campos de solo lectura: `id`, `slug`, `pack`, `status`, `channel.type` y
    `channel.public_id`;
  - `textarea` para `config.texts.*` e `info_text`;
  - ayudas a partir de `description`.

  Los títulos y descripciones en español salen de `Field(title=..., description=...)` en
  los esquemas Pydantic. Un pack nuevo tiene formulario sin tocar el frontend.
- **Vista YAML** del documento completo, sincronizada con el formulario.
- **Guardar:**
  1. "Ver cambios" muestra el diff con la versión vigente.
  2. Al guardar se pide un comentario.
  3. Se envía `PUT document` con `base_version`.

  Respuestas:
  - **422:** se marcan los campos (las rutas de `details` se convierten en `errorSchema`)
    y además se listan;
  - **409:** aviso con "Recargar" o "Ver diferencias";
  - **éxito:** "Guardado: versión N; se aplica en unos segundos".

  Si se sale con cambios sin guardar, se pide confirmación.

### 9.6. Alta de cliente (`/clientes/nuevo`)

1. **Pack:** tarjetas de `GET packs`.
2. **Datos básicos:**
   - nombre;
   - slug, derivado del nombre (minúsculas, sin acentos, guiones);
     `^[a-z0-9]+(?:-[a-z0-9]+)*$`, como mucho 64 caracteres y que no exista ya;
   - zona horaria (`Europe/Madrid`);
   - canal (WhatsApp o Telegram).
3. **Config:** el editor de §9.5 (solo `config`), precargado con `GET packs/{pack}/template`.
4. **Revisión** y `POST tenants`, que crea el negocio en `onboarding`.

Después se abre la pestaña Canal con lo que falta. El estado del asistente se guarda en
`sessionStorage`.

**Lista de comprobación previa a activar** (`tenancy.activation`):

| Comprobación | ¿Bloquea? |
|---|---|
| Documento válido y no degradado | sí |
| Ids de canal completos (`channel.complete`) | sí |
| Secretos presentes y legibles | sí |
| Salud del canal sin problemas 🔴 (comprobación forzada) | sí |
| Plantillas de WhatsApp aprobadas (si aplica) | sí |
| Algún tester ha escrito (al menos un `inbound_event` del canal `main`) | sí |
| Dueño enlazado | no (aviso) |

### 9.7. Actividad, Incidencias y Logs

- **Actividad:** filtros (cliente, tipos, estado) en la URL, "Cargar más" con el cursor y
  detalle desplegable en cada elemento.
- **Incidencias:**
  - alertas abiertas (severidad, texto, cliente, primera y última vez, ocurrencias,
    última entrega a Telegram); "Resolver" solo si `auto_resolves=false`;
  - envíos `unknown`/`failed`, con su elegibilidad y motivo. "Marcar enviado" y
    "Reenviar"; reenviar pide confirmación con el texto de riesgo del runbook 05;
  - trabajos fallidos, con "Reintentar" solo si `retryable`;
  - debajo, el historial de alertas resueltas.
- **Logs:**
  - rango rápido (15 min, 1 h, 24 h, 7 días, mes) o fechas; servicio, nivel, cliente y
    texto;
  - tabla virtualizada con hora, nivel, servicio, cliente y mensaje;
  - cada fila se despliega con el JSON y la excepción, y "Copiar event_id";
  - aviso si el rango se recortó (`clipped`) y estado 503 "Logs no disponibles".

### 9.8. Datos

- **Catálogo:** grupos plegables con filas (≈ si son estimadas) y tamaño.
- **Tabla:** descripción, columnas, relaciones enlazadas, filas por cliente, las 20 últimas
  filas y "Consultar esta tabla".
- **Consulta:**
  - selector "Todos los clientes" o uno;
  - editor SQL con autocompletado de tablas y columnas del catálogo;
  - ejecutar con el botón o con ⌘↵;
  - tabla de resultados con "Copiar" (TSV) y "Descargar CSV", aviso de truncado,
    duración y el error de PostgreSQL en rojo;
  - panel lateral de consultas guardadas.

### 9.9. Sistema y Auditoría

- **Sistema:**
  - CPU, RAM, disco y carga, con la gráfica del mes;
  - servicios, BD y colas;
  - backup: rojo si `ok=false` o tiene más de 8 h;
  - TLS: ámbar con menos de 20 días y rojo con menos de 7;
  - versión e historial de despliegues, con el SHA enlazado al commit.
- **Auditoría:** tabla filtrable por cliente y acción, con el detalle en JSON.

## 10. Seguridad y privacidad

- **Exposición:**
  - `panel` solo en `127.0.0.1:8080`;
  - `victorialogs` sin puertos publicados;
  - el Caddy público no reenvía `/api/`, y `web` responde 404 si llega `X-Autobot-Edge`.
- **Autenticación:** contraseña y TOTP, bloqueo por usuario, sesión de 12 h, CSRF y
  cookies con nombre propio.
- **BD:**
  - el panel usa `owner` de forma explícita, y el código de la plataforma sigue con RLS
    (§3.3);
  - la consola usa `fp_readonly` y siempre hace rollback;
  - `fp_app` no escribe la config ni ve auth ni la auditoría;
  - los permisos se vuelven a aplicar tras cada despliegue o restauración (§5).
- **Secretos:**
  - cifrados en reposo;
  - nunca se devuelven, exportan, auditan ni aparecen en errores;
  - `redact()` sigue quitándolos de los logs, y también `SECRETS_ENCRYPTION_KEY`.
- **Datos personales:**
  - visibles en el panel (decisión 13), con los accesos auditados;
  - los logs técnicos siguen enmascarando teléfonos y secretos;
  - la purga elimina testers y dueño de la config.
- **Cabeceras de `panel`:** CSP `default-src 'self'` (con `style-src 'self'
  'unsafe-inline'`), `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` y
  `X-Content-Type-Options: nosniff`.
- **Repositorio público:** `tenants/` y `datos/` siguen ignorados, y la CI comprueba que
  no hay nada versionado ahí.
- **Backups:** `pg_dump` incluye la config, las versiones y los secretos cifrados.
  `SECRETS_ENCRYPTION_KEY` está en `.env`, que restic ya copia. Restaurar la base sin
  `.env` deja los secretos ilegibles.

## 11. Eliminación del Django Admin

**Se elimina:**

- `django.contrib.admin`, `django.contrib.messages` y `django.contrib.staticfiles`, con
  sus middleware y context processors;
- `XFrameOptionsMiddleware`;
- `src/autobot/admin.py`, `src/autobot/admin_db.py` y `src/autobot/templates/admin/`;
- la ruta `admin/`;
- `whitenoise`, `STATIC_*`, `STORAGES` y el `collectstatic` del `Dockerfile`;
- `TEMPLATES`, si nada más lo usa;
- `make admin-tunnel`.

**Se conserva:** `auth`, `contenttypes`, `sessions`, `django_otp`,
`django_otp.plugins.otp_totp` y `procrastinate.contrib.django`.

**Se reubica:**

- la lógica de las acciones pasa a `autobot.ops.actions`;
- comandos de respaldo `outbound_resolve` y `job_retry`;
- la auditoría pasa a `audit_event`.

## 12. Herramientas de desarrollo y operación

Para que los agentes lo sepan, `docs/comandos.md` es la **referencia única** de comandos,
y `CLAUDE.md` enlaza a ella. Cada tarea que añade un comando lo documenta ahí.

**Desarrollo (local):**

| Comando | Qué hace |
|---|---|
| `make dev-bootstrap` | La primera vez: levanta `db`, ejecuta `make db-roles`, migra, `apply_grants`, `seed_demos`, crea el usuario del panel si no existe y levanta `web`, `worker` y `victorialogs` |
| `make dev-reset` | Borra el volumen de la BD local y repite `dev-bootstrap` |
| `make db-roles` | Ejecuta `init-roles.sh` dentro del contenedor `db` (roles nuevos y contraseñas) |
| `make tenant-import DIR= [SECRETS=]` | `tenant_config import` contra la BD local |
| `make dev-activity` | `manage.py seed_dev_activity`: actividad falsa y realista (mensajes, respuestas, avisos, alertas abiertas y resueltas, un `unknown`, un trabajo fallido y muestras de sistema) para ver el panel con datos. Se niega fuera de `local` |
| `make api` | Regenera `panel/openapi.json` y `panel/src/api/schema.d.ts` |
| `make fix` | `ruff check --fix`, `ruff format`, `biome check --write` y `make api` |
| `make check` / `make panel-check` | Puertas de calidad del backend y del frontend |
| `make panel-dev` | Vite en :5173, con proxy a :8000 |
| `make ngrok` | Túnel ngrok del dominio reservado, para los webhooks de demo en local |

El `worker` local se reinicia solo al cambiar el código (`watchfiles`), igual que
`runserver`.

**Operación (los ejecuta la persona, nunca un agente):**

| Comando | Qué hace |
|---|---|
| `make deploy [SHA=]` | Sin SHA usa `origin/main`, tras comprobar con `gh` que su CI está en verde |
| `make rollback` | Vuelve a desplegar el `previous` del último despliegue correcto (`deploys.jsonl`) |
| `make prod-manage CMD="..."` | Ejecuta `manage.py` en producción, a través de `deploy/manage.sh` en el servidor (con `-t` si es interactivo) |
| `make tenant-push SLUG= [SECRETS=]` | Exporta de local e importa en producción por tar en stdin; los secretos viajan por el mismo canal SSH y en el servidor solo tocan el `tmpfs` del contenedor |
| `make panel-tunnel` | Túnel SSH al panel |
| `make backup-now`, `make restore-test` | Como hoy |

- `HOST ?= autobot`: se apoya en un alias `autobot` en `~/.ssh/config`, así que no hace
  falta `HOST=`.
- **`deploy/ensure-env.sh`**, al principio de `deploy.sh`:
  - comprueba que están todas las variables obligatorias;
  - **genera** las internas que falten (`DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD`,
    `FP_OWNER_PASSWORD`, `FP_APP_PASSWORD`, `FP_READONLY_PASSWORD`, las `DB_*_URL`,
    `SECRETS_ENCRYPTION_KEY`, `DEMO_TELEGRAM_WEBHOOK_SECRET` y
    `NOTIFY_BOT_WEBHOOK_SECRET`);
  - nunca inventa credenciales externas (Meta, Telegram, Sentry, healthchecks): si
    faltan, aborta y dice cuáles.
- **`deploy.sh`**, por orden:
  1. `ensure-env`;
  2. `db`;
  3. `init-roles`;
  4. `pull`;
  5. `migrate`;
  6. `apply_grants`;
  7. `tenant_config validate --all`;
  8. `seed_demos`;
  9. `up`;
  10. comprobaciones de salud (web, worker, panel).

  Termina con una línea en `deploys.jsonl` y un aviso informativo "🟢 Desplegado
  `<sha corto>`" al chat de ops.

## 13. Rendimiento y recursos

- **RAM:** `panel` unos 20 MB y `victorialogs` hasta unos 200 MB. Se comprueba con
  `docker stats` tras el primer despliegue.
- **Índices nuevos** para los agregados del mes: `outbound_message (tenant_id, sent_at)` e
  `inbound_event (tenant_id, received_at)`. Objetivo: `GET overview` en menos de 300 ms con
  15 negocios.
- **Recarga del registro:** como mucho una consulta trivial cada 2 s por proceso.

## 14. Fuera de alcance y evolución prevista

- Stripe (con su propio ADR): suscripción por tenant, Checkout y un webhook público.
- Tailscale y la versión móvil.
- Resumen diario de la plataforma por Telegram, con los mismos datos que el Resumen.
- Editar los datasets desde el panel y tendencias de más de un mes.
- Botón de despliegue y más roles.

## 15. Decisiones registradas

| # | Decisión | Fecha |
|---|---|---|
| 1 | Config y datasets en PostgreSQL, versionados; los demos también, sembrados desde la plantilla | 2026-11-03 |
| 2 | Acceso solo por túnel SSH | 2026-11-03 |
| 3 | Secretos de canal cifrados en la BD y de solo escritura; sin `.env` ni clave por cliente (§4.3) | 2026-11-03 |
| 4 | Consola SQL de solo lectura con catálogo explicado | 2026-11-03 |
| 5 | Stripe fuera de la v1 | 2026-11-03 |
| 6 | Los cambios de config se aplican al guardar | 2026-11-03 |
| 7 | Horarios de `bus` por terminal | 2026-11-03 |
| 8 | Solo la persona usa el panel; un rol | 2026-11-03 |
| 9 | Acciones v1: pausar, reactivar, cambiar config, activar, alta; baja solo por comando | 2026-11-03 |
| 10 | Tema oscuro, moderno y simple; "Autobot"; solo escritorio | 2026-11-03 |
| 11 | Primera tarea: eliminar el Django Admin | 2026-11-03 |
| 12 | KPIs del mes en curso; coste con la fórmula del resumen del dueño | 2026-11-03 |
| 13 | Datos personales visibles, con los accesos auditados | 2026-11-03 |
| 14 | Consola con selector "todos" o un cliente | 2026-11-03 |
| 15 | Consola siempre de solo lectura | 2026-11-03 |
| 15b | Consola: solo `SELECT`/`WITH`/`VALUES` (cursor con nombre), sin `EXPLAIN` | 2026-11-03 |
| 16 | Alertas en Telegram; todo lo que manda el bot se ve en el panel | 2026-11-03 |
| 17 | Logs técnicos del mes en curso (31 días) | 2026-11-03 |
| 18 | Frontend en `panel/` en este repo, con CI propia | 2026-11-03 |
| 19 | SPA con Vite servida por un Caddy interno que hace de proxy | 2026-11-03 |
| 20 | VictoriaLogs con envío desde la app; métricas leyendo `/proc` | 2026-11-03 |
| 21 | Baja con `tenant_status offboard`; la purga borra secretos, métricas, datasets y versiones salvo una depurada | 2026-11-03 |
| 22 | El alta de `bus` copia el horario de la plantilla como versión 1 | 2026-11-03 |
| 23 | Retención de auditoría y alertas con una función `SECURITY DEFINER` | 2026-11-03 |
| 24 | Permisos reproducibles con `apply_grants` (migraciones, despliegue, restauración) | 2026-11-03 |
| 25 | Registro fijado por trabajo o petición (`registry_scope`) | 2026-11-03 |
| 26 | Enrutado de BD por modelo (auth → `owner`); el panel usa `owner` de forma explícita | 2026-11-03 |
| 27 | Sin tráfico ni despliegue previo: no hay migración de producción; los commits intermedios no tienen que ser desplegables, pero la CI queda en verde | 2026-11-03 |
