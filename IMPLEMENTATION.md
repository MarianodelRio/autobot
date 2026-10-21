# IMPLEMENTATION.md — Plan de implementación de FlowPilot

Guía ejecutable para construir FlowPilot. **`design.md` es la fuente de verdad**: cada tarea cita las secciones de `design.md` (`§`) que implementa y no repite su contenido. Si una tarea y `design.md` no coinciden, manda `design.md`; si `design.md` está mal o incompleto, se corrige en el mismo commit que la tarea y se anota en sus notas.

---

## 1. Cómo se usa

### 1.1 Leyenda

- 🤖 **Tarea de agente**: la implementa un agente y la revisa otro.
- 👤 **Acción manual**: la haces tú (cuentas, credenciales, servidor, pruebas reales). El plan dice cuándo hace falta y cómo comprobar que está hecha.
- ⚠️ **Aprobación humana obligatoria** antes de dar la tarea por terminada (`CLAUDE.md`, "Reglas obligatorias"): migraciones de RLS, roles o borrados; cifrado, secretos o firma de webhooks; infraestructura del servidor; datos de producción; activar el canal real de un negocio.

### 1.2 Estados

| Estado | Significado |
|---|---|
| `pending` | Sin empezar |
| `in_progress` | Alguien la está implementando o revisando (el campo **Revisión** dice en qué punto está) |
| `blocked` | No puede avanzar; el motivo va en **Notas** (dependencia, acción manual, decisión pendiente) |
| `done` | Implementada, revisada y aprobada; criterios cumplidos; incluida en `main` en el mismo commit que la marca como `done` |

Campo **Revisión**: `—` (no hay nada que revisar) · `pendiente` (implementación terminada, esperando revisor) · `cambios` (el revisor pide correcciones, listadas en Notas) · `aprobada`.

### 1.3 Ciclo de una tarea

1. **Elegir:** la primera tarea `pending` cuyas dependencias están `done` y cuyas acciones 👤 previas están hechas. Ponerla en `in_progress`. Si la siguiente tarea en orden está bloqueada, se elige otra independiente (apartado 1.6).
2. **Implementar** (agente implementador):
   - Leer la tarea, las secciones de `design.md` que cita y `CLAUDE.md`. Si es un port, leer también el código de origen en `~/Desktop/Peluqueria` o `~/Desktop/buscaBus`.
   - Implementar solo el alcance de la tarea, con los tests que pide.
   - Ejecutar `make check`.
   - Poner Revisión `pendiente` y resumir en Notas qué se hizo y cualquier desviación.
3. **Revisar** (otro agente, en una sesión nueva, sin el contexto del implementador):
   - Leer la tarea, las secciones citadas y el diff.
   - Aplicar la lista del apartado 1.5 y ejecutar `make check`.
   - Resultado: Revisión `aprobada`, o `cambios` con la lista concreta de lo que hay que corregir.
4. **Cerrar**, con la revisión aprobada (y, si la tarea lleva ⚠️, también tu aprobación):
   - Marcar la tarea como `done` y actualizar la tabla de progreso.
   - Hacer **un único commit** en `main` con el código, los tests y el cambio de estado, con el mensaje `T-x.y: <resumen>`. Así cada commit deja el seguimiento al día.

Para retomar el trabajo en una sesión nueva:

- `grep -n "Estado: in_progress\|Estado: blocked" IMPLEMENTATION.md` muestra las tareas abiertas y bloqueadas.
- `git log --oneline` muestra lo último que se cerró.
- Las **Notas** de cada tarea son la memoria entre sesiones: decisiones, desviaciones y temas pendientes. Escríbelas breves.

### 1.4 Definición de terminado (todas las tareas 🤖)

- Se cumplen los criterios de aceptación de la tarea.
- Los tests que pide la tarea existen y pasan, y `make check` está en verde (`ruff`, `mypy`, `import-linter` y `pytest`, el mismo conjunto que CI).
- No hay secretos, teléfonos ni ids de usuario en logs, argumentos de trabajos ni candados.
- `design.md` sigue describiendo lo implementado; si se ha corregido, el cambio va en el mismo commit.
- Notas actualizadas.

### 1.5 Lista de revisión

1. **Alcance:** hace lo que pide la tarea, ni más ni menos.
2. **Diseño:** cumple las secciones citadas (nombres, estados, interfaces, comportamiento ante errores). Si se desvía, la desviación está justificada y reflejada en `design.md`.
3. **Dependencias entre módulos** (§4.4): `core` e `integrations` no importan Django; `packs` solo importan `core`.
4. **Datos:** todo acceso a tablas con `tenant_id` pasa por `tenant_tx`; sin transacciones abiertas durante llamadas externas; las claves idempotentes son las del diseño.
5. **Seguridad:**
   - Verificación de firmas antes de cualquier otra cosa.
   - Secretos solo desde `.env` o `secrets.yaml`.
   - Sin datos personales en logs ni en trabajos.
   - El canal `test` no toca servicios reales (§6.5).
6. **Tests:** cubren el camino feliz y los errores que pide la tarea; los tests de escenarios comprueban los límites de mensajes; nada de red real en CI.
7. **Calidad:** código legible, sin abstracciones que el diseño no pide, textos al usuario en español y código en inglés.

### 1.6 Acciones manuales pendientes

Una acción 👤 sin hacer bloquea **solo** las tareas y validaciones que dependen de ella, nunca el resto del plan:

- Si una tarea depende de una acción 👤 pendiente, se pone en `blocked` con el motivo en Notas y se sigue con otra tarea cuyas dependencias estén cumplidas, aunque sea de otra fase.
- El código que usará credenciales o servicios reales se implementa y se prueba con fixtures, dobles de prueba y datos de ejemplo. Lo único que espera a la acción manual es la prueba contra el servicio real.
- Una validación de fase con pasos manuales pendientes queda con esas casillas sin marcar y se anota en la tabla de progreso. Las fases siguientes pueden avanzar en todo lo que no dependa de ellas.
- **Nunca** se inventan credenciales, ids, tokens ni respuestas de servicios reales, ni se da por hecha una acción manual, una verificación de Meta, una plantilla aprobada o tu aprobación ⚠️. Si falta algo, se deja `blocked` y se pide.

---

## 2. Progreso

| Fase | Contenido | Tareas 🤖 | Hechas | Estado |
|---|---|---:|---:|---|
| F0 | Base del proyecto | 4 | 4 | done |
| F1 | Núcleo puro (`core`) | 5 | 1 | in_progress |
| F2 | Datos, tenants y aislamiento | 5 | 0 | pending |
| F3 | Canales y runtime | 10 | 0 | pending |
| F4 | Pack `bus` | 6 | 0 | pending |
| F5 | Pack `salon` | 9 | 0 | pending |
| F6 | Avisos, operación y observabilidad | 5 | 0 | pending |
| F7 | Infraestructura y despliegue | 5 | 0 | pending |
| F8 | Puesta en marcha de los negocios | 3 | 0 | pending |
| **Total** | | **52** | **5** | |

Dependencias entre fases: F0 → F1 → F2 → F3 → (F4 y F5, en cualquier orden o en paralelo) → F6 → F7 → F8. Mandan las dependencias de cada tarea: cualquier tarea con sus dependencias cumplidas puede hacerse, aunque una fase anterior tenga pendiente una acción manual o una casilla de validación (apartado 1.6).

---

## 3. Acciones manuales 👤 (resumen)

| Id | Acción | Necesaria antes de | Estado |
|---|---|---|---|
| M-0.1 | Repositorio GitHub listo para CI y GHCR | T-0.3 | done |
| M-3.1 | Bot de pruebas de **desarrollo** y tu id de Telegram | Validación F3 | pending |
| M-4.1 | Autocares San Sebastián: personas de prueba y verificación de empresa en Meta | Validación F4 (personas de prueba) y M-8.3 (verificación) | pending |
| M-5.1 | Proyecto de Google Cloud de la plataforma y cuenta de servicio | Validación F5 | pending |
| M-5.2 | Calendarios de desarrollo (real y de pruebas, distintos) | Validación F5 | pending |
| M-6.1 | Bot de avisos y chat de ops | Validación F6 | pending |
| M-6.2 | Sentry y healthchecks.io | Validación F6 | pending |
| M-7.1 | Dominio y VPS | T-7.4 | pending |
| M-7.2 | Almacenamiento de backups | Validación F7 | pending |
| M-7.3 | Secretos de despliegue en GitHub y entorno `production` | Validación F7 | pending |
| M-7.4 | Bot de pruebas de **producción** | Validación F7 | pending |
| M-7.5 | Uptime externo | Validación F7 | pending |
| M-7.6 | Primer despliegue y simulacro de restauración | Fin de F7 | pending |
| M-8.1 | Peluquería: calendarios, secretos y plantillas | T-8.2 | pending |
| M-8.2 | Peluquería: pruebas con el dueño y cambio de webhook | Fin de F8 | pending |
| M-8.3 | Autocares: alta del canal y pruebas con la empresa | Fin de F8 | pending |
| M-8.4 | Retirar los bots antiguos | Fin de F8 | pending |

Cada acción está detallada en su fase, con cómo verificarla.

---

## F0 · Base del proyecto

**Resultado verificable:** el proyecto arranca en local con Docker Compose y CI pasa en GitHub.

### T-0.1 · Esqueleto del proyecto 🤖
- **Estado:** done · **Revisión:** aprobada · **Depende de:** — · **Diseño:** §0, §4.4, §4.5
- **Hacer:**
  - `pyproject.toml` con `uv`, Python 3.14 y las dependencias de §18 fijadas en `uv.lock`. `weasyprint` va como dependencia de desarrollo.
  - Estructura `src/` (`core`, `integrations`, `packs`, `flowpilot`, `config`) y settings de Django por variables de entorno (`.env.example`).
  - Configuración de `ruff` y `mypy`, `pytest` con `pytest-django`.
  - `Makefile` con `up`, `down`, `test`, `check` y `shell`.
- **Acepta:**
  - `uv sync` funciona.
  - `make check` pasa con un test trivial.
  - `manage.py check` funciona sin BD real.
- **Tests:** un test de humo de settings.
- **Notas:** `uv` con `package = false` y `src/` en `sys.path` (`manage.py`, `pythonpath` de pytest, `mypy_path`). Dependencias de §18 más `dj-database-url` (leer `DB_APP_URL`); `whitenoise`, `pyyaml` y `sentry-sdk` se añaden en las tareas que los usan. `ENVIRONMENT=local` (por defecto) da valores de desarrollo; `prod` exige cada variable. `mypy --strict` en todo el repo. Ruff excluye `*.md` (la 0.17 formatea los bloques de código de la documentación). `make up/down/shell` usan Compose, que llega en T-0.2.

### T-0.2 · Contenedores locales 🤖
- **Estado:** done · **Revisión:** aprobada · **Depende de:** T-0.1 · **Diseño:** §4.2, §14.2, §14.6
- **Hacer:**
  - `Dockerfile` multi-etapa (`uv` → imagen mínima, usuario no root).
  - `compose.yaml` local con `db` (postgres:18), `web` (`runserver`) y `worker` (por ahora un comando de espera), con el código montado.
- **Acepta:** `make up` levanta los tres servicios; `docker compose exec web manage.py check` pasa; la imagen se construye sin root.
- **Tests:** —
- **Notas:** Imagen `python:3.14-slim` con el venv de `uv` en `/opt/venv` y usuario `app` (uid 10001); el código queda de root y de solo lectura para `app`. Verificado: `make up` levanta `db`, `web` y `worker`, `manage.py check` pasa en `web`, `id` da `app` y la imagen arranca gunicorn con `--read-only` sin errores gracias a `--no-control-socket` (gunicorn 26 intenta crear su socket de control en `$HOME`; añadido también en §4.2 y §14.2 de `design.md`). `db` no publica puerto (el 5432 del host suele estar ocupado y el diseño no lo expone). Hasta T-2.1, `compose.yaml` conecta con el superusuario local de `db`, porque `runserver` comprueba las migraciones y `fp_app` aún no existe; T-2.1 lo cambia a `fp_app`. El worker usa `sleep infinity` con `init: true` hasta T-2.5. La contraseña de `db` en local es fija (`postgres`), sin interpolar desde `.env`, para que copiar `.env.example` no rompa un volumen ya creado.

### T-0.3 · Integración continua 🤖
- **Estado:** done · **Revisión:** aprobada · **Depende de:** T-0.2, M-0.1 · **Diseño:** §17.3, §14.6
- **Hacer:** `.github/workflows/ci.yml` con las puertas de §17.3:
  - `ruff`, `mypy`, `import-linter` y `pytest` con PostgreSQL 18 como servicio.
  - `makemigrations --check`, `django-migration-linter` y `pip-audit`.
  - Construcción de la imagen.
  - Publicación en GHCR con el tag `<sha>` solo en `main` y si todo lo anterior pasa.
  - Además, `dependabot.yml`.
- **Acepta:** un push a `main` deja CI en verde y la imagen publicada en GHCR.
- **Tests:** —
- **Notas:** Dos jobs. `check` ejecuta, con PostgreSQL 18 como servicio, `ruff`, `mypy`, `import-linter`, `pytest`, `makemigrations --check`, `lintmigrations` y `pip-audit`. `image` depende de `check`, construye siempre con Buildx (con caché `gha`) y solo publica `ghcr.io/marianodelrio/flowpilot:<sha>` en un push a `main`; tiene `packages: write`, así que basta con que Actions esté activo (lo está: permisos por defecto de solo lectura). `pip-audit` audita todo `uv.lock` (`uv export --all-groups`, con hashes). `django-migration-linter` va como dependencia de desarrollo y se añade a `INSTALLED_APPS` solo si está instalado, así que no entra en la imagen. Hasta T-2.1, CI conecta con el superusuario de la BD de servicio. Comprobado en local: el workflow pasa `actionlint`; con un PostgreSQL 18 temporal, `makemigrations --check` detecta una migración que falta y `lintmigrations` detecta un `NOT NULL` añadido (ficheros temporales, ya borrados); y `pip-audit` no encuentra vulnerabilidades. `dependabot.yml` vigila cada semana `uv`, `github-actions`, `docker` y `docker-compose`; por eso el `Dockerfile` usa la imagen base literal y no un `ARG`. `setup-uv` usa un tag completo, porque desde la v8 no publica tags de versión mayor, y fija la misma versión de uv que el `Dockerfile`. En `main` no se cancelan runs, pero un run en cola se sustituye por el siguiente; un SHA intermedio puede quedarse sin imagen, cosa que no importa para desplegar por SHA. Verificado en GitHub: el run 39597647010 sobre `769204e` deja `check` e `image` en verde y publica `ghcr.io/marianodelrio/flowpilot:769204e748edba282323b165b7c8f7a549a7742b`. Se cierra en un commit aparte del workflow porque había que tenerlo en `main` para verificarlo.

### T-0.4 · Reglas de dependencias 🤖
- **Estado:** done · **Revisión:** aprobada · **Depende de:** T-0.1 · **Diseño:** §4.4
- **Hacer:** contratos de `import-linter`:
  - `core` no importa nada del proyecto.
  - `integrations` solo importa `core`.
  - `packs` solo importa `core` (nunca Django, `integrations`, `flowpilot` ni otro pack).
  - `flowpilot` puede importar `core`, `integrations` y `packs.registry`.
- **Acepta:** un import prohibido añadido a propósito hace fallar `make check` (probado y revertido).
- **Tests:** —
- **Notas:** Contratos en `[tool.importlinter]` de `pyproject.toml`; `make check` ejecuta `PYTHONPATH=src lint-imports`. Tres contratos `forbidden` (`core`, `integrations` y `packs`, que tampoco pueden importar `django`) y uno `protected`: los `packs.*` solo los importa `packs.registry`, con la excepción `flowpilot` y `flowpilot.** -> packs.registry`. Así un pack no importa a otro ni al registro, y `flowpilot` no importa un pack directamente. `import-linter` exige que `packs.registry` exista, así que se crea vacío (`PACKS = {}`) y T-2.4 lo rellena. Probado y revertido: un import prohibido rompe su contrato (`core → django` y `core → flowpilot`, `integrations → packs`, `packs → django` y `packs → integrations`, un pack que importa otro pack o el registro, `flowpilot → packs.<pack>`), y `make check` falla con código 2. Los imports permitidos (`flowpilot → packs.registry`, `core` e `integrations`, y `registry → pack`) pasan.

### 👤 M-0.1 · Repositorio GitHub
- **Cuándo:** antes de T-0.3.
- **Qué:** en `MarianodelRio/flowpilot`, comprobar que GitHub Actions está activo y que los workflows pueden publicar paquetes (Settings → Actions → Workflow permissions: lectura y escritura, o `packages: write` en el workflow).
- **Verificar:** el primer CI de T-0.3 publica la imagen en la pestaña Packages.

### ✅ Validación F0
- [x] `make up` + `make check` en verde en local.
- [x] CI en verde en `main` y la imagen visible en GHCR.

---

## F1 · Núcleo puro (`core`)

**Resultado verificable:** un pack de juguete conversa a través del arnés de pruebas, sin BD ni red.

### T-1.1 · Tipos del contrato 🤖
- **Estado:** done · **Revisión:** aprobada · **Depende de:** T-0.4 · **Diseño:** §6.1, §8.1, §8.2
- **Hacer:** en `core`:
  - Mensaje entrante y respuestas: `IncomingMessage`, `Text`, `Buttons`, `List`, `Button`, `Section`, `Row`.
  - Acciones: `SendProactive`, `NotifyOwner`, `UpdateContact`, `ContactRef`.
  - Contrato de pack: `PackResult`, `PackContext`, `Pack`, `Periodic`, `TemplateSpec`, `ProactiveMessage`.
  - Utilidades: `IdemKeys`, `Clock`, `TransientError`.
  - Serialización y deserialización JSON de respuestas y avisos proactivos, para `outbound_message.payload`.
- **Acepta:** tipos inmutables donde el diseño lo indica; la serialización de ida y vuelta da objetos iguales; `mypy` estricto en `core`.
- **Tests:** unitarios de serialización.
- **Notas:** Módulos de `core`: `messages`, `replies`, `proactive` (`TemplateSpec` y `ProactiveMessage`, aparte para que `actions` no dependa de `pack`), `actions`, `pack`, `clock`, `idem`, `errors` y `serialization` (`dump_outbound`/`load_outbound`, con una clave `type`). Todo es `frozen` salvo `PackResult`, que el diseño define mutable; las listas se mantienen como `list`, igual que en el diseño. `PackContext.calendar` es `Any`, porque el `Protocol` vive en `packs/salon/ports.py` y `core` no puede importarlo. `HealthIssue(code, message)` es mínimo hasta T-6.2. `Clock` es un `Protocol` con `now()`, con `SystemClock(tz)` en producción (el reloj fijo llega en T-1.5). `Pack` es `kw_only`, para declararlo con nombres y en el orden de §8.1. Las tres cosas quedan reflejadas en §8.1 y §8.2 de `design.md`. `ContactRef` exige exactamente uno de `contact_id` o `phone`. Añadidos a §8.2 de `design.md`: el formato de `IdemKeys` (`event(name)` = `<name>:<event_id>`; `stable(name)` = `name`) y la firma de `Periodic.handler`. Los tests de `core` viven en `src/core/tests/`.

### T-1.2 · Límites comunes y plan de envío 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-1.1 · **Diseño:** §6.1, §7.4
- **Hacer:** `core/limits.py` con los límites de §6.1 y `plan_sends`: fusión de textos, texto dentro del interactivo si cabe, validación de límites y truncado con registro.
- **Acepta:** cada regla de §7.4 cubierta; los ids de más de 64 bytes se rechazan.
- **Tests:** unitarios de cada regla y caso límite (1.024 y 4.096 caracteres, 3 botones, 10 filas, títulos de 20 y 24, ids de 64 bytes).
- **Notas:** —

### T-1.3 · Utilidades de interfaz, texto y fechas 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-1.1 · **Diseño:** §8.3
- **Hacer:** portar a `core/ui.py`, `core/text.py` y `core/dates.py`:
  - `interactive.py` de ambos bots: helpers y `paginate`.
  - `_norm` y `_strip_html` de Peluquería.
  - `format_date_es` y `next_days` con `zoneinfo`.
- **Acepta:** las funciones portadas se comportan como en el origen (sus tests portados pasan); sin `pytz`.
- **Tests:** portados y adaptados de los dos repos.
- **Notas:** —

### T-1.4 · Reglas comunes de conversación 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-1.1 · **Diseño:** §7.2, §7.3
- **Hacer:** en `core/conversation.py`, funciones puras compartidas por el runtime y el arnés:
  - `effective_state`: caducidad y versión del estado.
  - `global_command`: `menu`, `menú`, `inicio`, `/start`, `baja` y `alta`.
  - `recovery_result`.
  - El texto de reinicio amable.
- **Acepta:** caducidad a los 30 min; una versión distinta reinicia; `/start` equivale a `menu`.
- **Tests:** unitarios.
- **Notas:** —

### T-1.5 · Arnés de pruebas de conversación 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-1.2, T-1.4 · **Diseño:** §17.2
- **Hacer:** `core/testing/`:
  - Reloj fijo y fixture de tenant de ejemplo.
  - `send` y `press` con `expect` para texto, botones y filas de lista.
  - Comprobación automática de límites en cada respuesta.
  - Simulación de los dos tipos de canal.
  - Un pack de juguete (`tests/toy_pack`) que lo ejercite.
- **Acepta:** el ejemplo de §17.2, adaptado al pack de juguete, se puede escribir tal cual; una respuesta que se sale de los límites hace fallar el test.
- **Tests:** tests del propio arnés con el pack de juguete.
- **Notas:** el render real con los dos adaptadores se añade en T-3.2, cuando existan.

### ✅ Validación F1
- [ ] El pack de juguete pasa sus escenarios con el arnés.
- [ ] `make check` en verde.

---

## F2 · Datos, tenants y aislamiento

**Resultado verificable:** modelos con RLS probada, registro de tenants que valida `tenants/*` y cola Procrastinate operativa.

### T-2.1 · Roles de BD y alias ⚠️ 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-0.2 · **Diseño:** §12.2, §5.3
- **Hacer:**
  - Script de inicialización de PostgreSQL (local y prod) que crea `fp_owner` (dueño de las tablas, `BYPASSRLS`) y `fp_app`.
  - Alias de Django `default` (`DB_APP_URL`) y `owner` (`DB_OWNER_URL`); las migraciones usan `owner`.
  - Permisos de `fp_app` sobre las tablas de la aplicación y de Procrastinate.
- **Acepta:** las migraciones se ejecutan como `fp_owner`; `fp_app` no puede hacer DDL.
- **Tests:** test de que `fp_app` no tiene `BYPASSRLS` ni puede crear tablas.
- **Notas:** quitar de `compose.yaml` el `DB_APP_URL` con el superusuario local puesto en T-0.2 y usar `fp_app` (y `fp_owner` para migraciones).

### T-2.2 · Modelos y políticas RLS ⚠️ 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-2.1 · **Diseño:** §12.1, §12.2
- **Hacer:**
  - Modelos `Tenant`, `Contact`, `Conversation`, `InboundEvent`, `OutboundMessage`, `Notification`, `TestBotEvent` y `TestSession`.
  - UUIDv7, `UNIQUE(tenant_id, id)`, claves foráneas compuestas y restricciones únicas del diseño.
  - Migración con `ENABLE`/`FORCE ROW LEVEL SECURITY` y la política `tenant_isolation` en cada tabla con `tenant_id`.
- **Acepta:** el esquema coincide con §12.1; `makemigrations --check` limpio; el linter de migraciones pasa.
- **Tests:** test de restricciones únicas (eventos duplicados, `idem_key` duplicada).
- **Notas:** —

### T-2.3 · `tenant_tx` y test de aislamiento 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-2.2 · **Diseño:** §12.2
- **Hacer:** `tenant_tx(tenant_id)` (`set_config` local, prohibido anidar) y un test genérico que recorra **todos** los modelos con `tenant_id`.
- **Acepta:**
  - El tenant A no lee, modifica, borra ni inserta filas de B.
  - No se pueden crear claves foráneas hacia B.
  - Sin tenant fijado se leen 0 filas.
  - Anidar `tenant_tx` falla.
  - Un modelo nuevo sin política hace fallar el test (comprobado con un modelo temporal).
- **Tests:** `tests/isolation/`.
- **Notas:** —

### T-2.4 · Registro de tenants y secretos 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-2.2, T-1.1 · **Diseño:** §5.2, §5.3, §5.4
- **Hacer:**
  - Esquema común de `tenant.yaml` (`channel`, `testers`, `owner`, estados) y carga de `secrets.yaml`.
  - Validación de la config con el esquema del pack y llamada a `load_data`.
  - Índices en memoria y estado `degraded` por tenant.
  - Comandos `sync_tenants` y `new_tenant`.
  - Test de CI que valida todos los `tenants/*`.
  - `packs/registry.py`, con el pack de juguete solo en tests.
- **Acepta:**
  - Un tenant con errores queda `degraded` sin afectar a los demás.
  - Faltan secretos → canal `main` deshabilitado.
  - `sync_tenants` es idempotente.
  - `new_tenant` genera un `id` UUIDv7 y un `public_id` aleatorio.
- **Tests:** unitarios de validación (ids o `phone_number_id` duplicados, campos por tipo de canal, `testers`), `degraded` e idempotencia de `sync_tenants`.
- **Notas:** —

### T-2.5 · Cola Procrastinate 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-2.1 · **Diseño:** §7.5, §4.2
- **Hacer:**
  - App de Procrastinate con las colas `inbound`, `outbound` y `periodic`, y `flowpilot/jobs.py` con el registro de tareas.
  - El worker de `compose.yaml` ejecuta `procrastinate worker --concurrency 4`.
  - Parada ordenada.
- **Acepta:**
  - Un trabajo de ejemplo se encola y se ejecuta.
  - Dos trabajos con el mismo `lock` se ejecutan en orden de creación y nunca a la vez.
- **Tests:** integración del orden por candado.
- **Notas:** —

### ✅ Validación F2
- [ ] Test de aislamiento en verde en CI.
- [ ] `sync_tenants` con un tenant de ejemplo crea su fila `tenant`.
- [ ] El orden por candado está comprobado.

---

## F3 · Canales y runtime

**Resultado verificable:** el pack de juguete conversa de extremo a extremo por el bot de pruebas de desarrollo (`telegram_poll`) y por WhatsApp simulado en tests de integración.

### T-3.1 · Contrato de adaptador y adaptador de WhatsApp ⚠️ 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-1.1 · **Diseño:** §6.2, §6.3
- **Hacer:**
  - `ChannelAdapter` y `SendOutcome`.
  - `WhatsAppAdapter`: `verify` (HMAC), `parse` (mensajes, botones de plantilla, BSUID, estados, `phone_number_id`), `render` (incluidas plantillas), `send` con la tabla de resultados y verificación `GET`.
  - Se porta de `webhook.py` y `whatsapp.py` de Peluquería.
- **Acepta:** cada fila de la tabla de §6.3 produce el `SendOutcome` correcto; el cuerpo de las respuestas 4xx nunca se registra.
- **Tests:** contrato contra payloads reales grabados en `tests/fixtures/whatsapp/` (texto, `button_reply`, `list_reply`, botón de plantilla, BSUID, estados con `pricing`, tipos no soportados) y respuestas de error simuladas con `httpx`.
- **Notas:** —

### T-3.2 · Adaptador de Telegram 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-3.1 · **Diseño:** §6.4
- **Hacer:**
  - `TelegramAdapter`: `verify` (secret token), `parse` (solo chats privados, `callback_query`), `acknowledge` (`answerCallbackQuery`), `render` (listas como botones con descripciones en el texto, `*negrita*` a HTML con escape) y `send`.
  - Conectar los dos adaptadores al arnés (renderizado de cada respuesta de los escenarios).
- **Acepta:** la tabla de resultados de §6.4 se cumple; los grupos se ignoran; el texto se escapa correctamente.
- **Tests:** contrato con fixtures grabados en `tests/fixtures/telegram/` (mensaje, `/start`, `callback_query`, grupo, sticker, 403, 429 con `retry_after`).
- **Notas:** —

### T-3.3 · Webhooks y `/health` ⚠️ 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-3.2, T-2.4, T-2.5 · **Diseño:** §7.1, §13, §15.3
- **Hacer:**
  - Vistas `GET`/`POST /webhooks/whatsapp/<public_id>` y `POST /webhooks/telegram/<public_id>` según §7.1: límite de 64 KB, 404, 401, reglas de `ignored` por estado y `testers.main`, `ON CONFLICT` y encolado.
  - Límite por IP de las peticiones con firma inválida.
  - `/health` con BD y tenants cargados o `degraded`.
  - URLs de `/admin/` montadas aparte, para que Caddy no las exponga (T-7.1).
- **Acepta:** el webhook no hace ninguna llamada externa; un aviso duplicado no se encola dos veces.
- **Tests:** integración de cada rama de §7.1.
- **Notas:** —

### T-3.4 · `ctx`: candados, claves idempotentes y calendario por canal 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-2.3 · **Diseño:** §8.2, §9.5, §6.5
- **Hacer:**
  - `build_context`.
  - `ctx.lock`: advisory lock de sesión con espera máxima de 10 s, sin transacción abierta y con la clave prefijada por tenant y calendario.
  - `IdemKeys` (`event` y `stable`).
  - El enlace de `ctx.calendar` al `calendar_id` en el canal `main` y al `test_calendar_id` en el canal `test`, a través de una fábrica de `CalendarPort` inyectable (la implementación real llega en T-5.1).
- **Acepta:** en el canal `test` es imposible obtener un `ctx.calendar` ligado a `calendar_id`; sin lock en 10 s se lanza `TransientError`.
- **Tests:** unitarios e integración del lock (dos procesos que compiten) y del enlace de calendario por canal.
- **Notas:** —

### T-3.5 · `process_event` y `apply_status` 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-3.3, T-3.4, T-1.4 · **Diseño:** §7.2, §7.3, §6.6, §8.2
- **Hacer:**
  - tx1, pack sin transacción y tx2 según §7.2.
  - *Upsert* de contacto por `(tenant, canal, external_id)`.
  - Límite por contacto, comandos globales y `acknowledge`.
  - Recuperación en el último reintento y ante excepciones no previstas (con Sentry, si está configurado).
  - `apply_actions`: `SendProactive` resuelto según §6.6 y §8.2, sin enviar a contactos con `opt_out` o `unreachable`; `UpdateContact`; y `NotifyOwner` hasta la cola, que se entrega en T-6.1.
  - `apply_status`.
- **Acepta:** reprocesar un evento no duplica respuestas; un evento que no está `pending` termina sin hacer nada; caducidad y versión aplicadas.
- **Tests:** integración (duplicado, reintento entre tx1 y tx2, excepción del pack que lleva al texto de recuperación, límite por contacto, `baja`/`alta`, estado de WhatsApp que actualiza el mensaje).
- **Notas:** —

### T-3.6 · Envío de mensajes 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-3.5 · **Diseño:** §7.4, §7.5
- **Hacer:**
  - `plan_sends` conectado a la creación de `outbound_message`.
  - `send_message` con su máquina de estados, reintentos según `SendOutcome` y candado `out:<h>`.
  - Marca `unreachable` ante `Rejected(kind=recipient)` y alerta preparada ante `Rejected(kind=auth)` (el envío de la alerta llega en T-6.1).
- **Acepta:** un `unknown` no se reenvía ni bloquea los mensajes siguientes; `sending` huérfano pasa a `unknown`.
- **Tests:** integración de cada transición de §7.4.
- **Notas:** —

### T-3.7 · Periódicas y barridos 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-3.5 · **Diseño:** §7.6
- **Hacer:** registro de los `Periodic` de los packs, reparto `run_periodic` por tenant activo, descarte por `max_delay_min` y aplicación de acciones en transacción.
- **Acepta:** un instante programado se encola una sola vez; un barrido retrasado se descarta y se registra.
- **Tests:** integración con una periódica del pack de juguete.
- **Notas:** el barrido por calendario (real y de pruebas) se implementa en T-5.6.

### T-3.8 · Selector del bot de pruebas 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-3.5, T-3.6 · **Diseño:** §6.5, §6.6
- **Hacer:**
  - `POST /webhooks/telegram-test`, `test_bot_event` y `route_test_update` (candado `tg:<h>`).
  - Permisos (`TEST_BOT_OPERATORS` y `testers.telegram`), lista paginada, `fp_select:<slug>` y `test_session`.
  - Evento sintético `menu`, `/negocio`, mensaje "🧪 Pruebas · …".
  - Exclusión de negocios `degraded` u `offboarded` y de los que tienen `needs_calendar` pero no `test_calendar_id`.
  - Reglas de aislamiento de la tabla de §6.5: `NotifyOwner` redirigido a ops con "🧪" y nunca envío por WhatsApp ni por el bot del negocio.
- **Acepta:** se cumplen todas las reglas de §6.5.
- **Tests:** integración (usuario sin permiso, selección, cambio con `/negocio`, negocio no disponible, **aislamiento**: el canal `test` nunca usa `calendar_id`, nunca envía por el canal `main` y sus avisos al dueño van a ops).
- **Notas:** —

### T-3.9 · Comandos de Telegram 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-3.8 · **Diseño:** §6.4, §16.3
- **Hacer:**
  - `manage.py telegram_poll [<slug>]`: *long polling* que entra por el mismo camino que el webhook.
  - `manage.py telegram_set_webhook <slug|test>`.
  - Objetivo `make telegram-poll`.
- **Acepta:** con el bot de desarrollo, un mensaje entra y el pack responde sin túnel.
- **Tests:** unitario de que `telegram_poll` pasa por la misma función de entrada que el webhook.
- **Notas:** —

### T-3.10 · Integración de extremo a extremo del runtime 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-3.6, T-3.7, T-3.8 · **Diseño:** §7.7, §17.1
- **Hacer:** batería de integración sobre la tabla de fallos de §7.7 con el pack de juguete:
  - Webhook → cola → worker → envío.
  - Orden de dos mensajes de un mismo contacto.
  - Un tenant `degraded` no afecta a otro.
  - El worker cae a mitad de un evento.
  - Base de datos caída (503 en `web`).
- **Acepta:** cada fila de §7.7 que no depende de Calendar tiene su test.
- **Tests:** `tests/integration/`.
- **Notas:** —

### 👤 M-3.1 · Bot de pruebas de desarrollo
- **Cuándo:** antes de la validación de F3.
- **Qué:**
  1. Crear un bot con @BotFather (p. ej. `flowpilot_dev_bot`) y poner su token en `.env` local como `TEST_BOT_TOKEN`.
  2. Averiguar tu id de Telegram (p. ej. con @userinfobot) y ponerlo en `TEST_BOT_OPERATORS`.
- **Verificar:** `make telegram-poll` arranca sin errores y el bot responde a `/start` con la lista de negocios.

### ✅ Validación F3
- [ ] Prueba de extremo a extremo en local: desde Telegram, `/start` → elegir el negocio de juguete → conversar → las respuestas llegan en orden.
- [ ] Integración y aislamiento en verde en CI.

---

## F4 · Pack `bus`

**Resultado verificable:** la consulta de horarios completa funciona en el bot de pruebas con los datos reales de Autocares San Sebastián, y pasan todas las pruebas portadas de buscaBus.

### T-4.1 · Dataset: modelo, validador y carga 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-1.3 · **Diseño:** §10.1
- **Hacer:** portar de buscaBus `modelo.py`, `formato.py`, `loader.py`, `calendario.py` y `datos.py` a `packs/bus/`, con la normalización sobre `core/text`.
- **Acepta:** los errores y avisos del validador son idénticos a los del origen.
- **Tests:** portados `test_formato`, `test_loader` y `test_calendario`, con sus fixtures.
- **Notas:** —

### T-4.2 · Motor de consulta 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-4.1 · **Diseño:** §10.2
- **Hacer:** portar `query.py`.
- **Acepta:** las pruebas doradas dan los mismos resultados que en buscaBus.
- **Tests:** portado `test_query`.
- **Notas:** —

### T-4.3 · Matcher y fechas 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-4.1 · **Diseño:** §10.3
- **Hacer:** portar `matcher.py` y `fechas.py`.
- **Acepta:** se cumplen las 7 ramas del matcher, el caso Villafranca y el formato cerrado de fechas.
- **Tests:** portados `test_matcher` y `test_fechas`.
- **Notas:** —

### T-4.4 · Conversación, config y declaración del pack 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-4.2, T-4.3, T-1.5 · **Diseño:** §10.3, §10.4, §8
- **Hacer:**
  - Portar `flujo.py`, `messages.py` y los constructores de listas a la máquina de estados del pack sobre `PackContext`.
  - `BusConfig`, `load_data` (comprueba `start_menu_towns`) y `pack` en `packs/registry.py`.
  - Los textos no reconocidos se registran sin identificador de contacto.
- **Acepta:** todos los escenarios de §10.5 en verde con el arnés, en los dos tipos de canal.
- **Tests:** portados `test_conversation` y `test_interactive`; escenarios de §10.5.
- **Notas:** —

### T-4.5 · Herramientas de horarios 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-4.1 · **Diseño:** §10.1, §16.3
- **Hacer:**
  - Portar `validar`, `formatear`, `revision` (HTML y PDF) y `diff`, como `tools/bus_*.py` con el parámetro `TENANT`.
  - Objetivos `make bus-validar`, `bus-formatear`, `bus-revision` y `bus-publicar` (este crea el tag `datos/<slug>/AAAA-MM-DD`).
- **Acepta:** el PDF de revisión de los datos reales muestra los cambios desde el último tag.
- **Tests:** portados `test_formatear`, `test_diff` y `test_revision`.
- **Notas:** —

### T-4.6 · Tenant de Autocares San Sebastián 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-4.4, T-2.4 · **Diseño:** §5.2, §10.1
- **Hacer:**
  - `tenants/autocares-ss/` con `tenant.yaml` (canal `main` de **WhatsApp**, decidido; los ids de Meta se rellenan en M-8.3), `status: onboarding`, `testers` y la config portada de `buscaBus/config.yaml`.
  - El dataset copiado de `buscaBus/horarios/` sin cambios, con los comentarios de las preguntas abiertas (P28, P30, P37).
  - Tag inicial `datos/autocares-ss/<fecha>` equivalente al último publicado.
- **Acepta:** el tenant valida en CI y `make bus-validar TENANT=autocares-ss` no da errores.
- **Tests:** la validación de tenants de CI.
- **Notas:** —

### 👤 M-4.1 · Autocares San Sebastián: personas de prueba y verificación en Meta
- **Decidido:** su canal de producción es **WhatsApp**, con un número propio y la app de Meta en el portfolio de la empresa (§6.3).
- **Cuándo:** cuanto antes. No bloquea T-4.6: el tenant se crea con `testers` vacío y se completa cuando lleguen los ids. La verificación de empresa tarda de 2 a 5 días hábiles y solo bloquea M-8.3.
- **Qué:**
  1. Conseguir los ids de Telegram de las personas de la empresa que vayan a probar (`testers.telegram`).
  2. Pedir a la empresa una SIM sin WhatsApp activo para el número.
  3. Crear o localizar su Business Portfolio, con el operador como administrador, e iniciar la verificación de empresa.
- **Verificar:** los ids están en `testers.telegram` del tenant, la SIM está disponible y la verificación figura como enviada en Meta Business Manager.

### ✅ Validación F4
- [ ] Pasan todas las pruebas portadas de buscaBus.
- [ ] Prueba de extremo a extremo en local con el bot de pruebas: elegir Autocares → Pozoblanco → Córdoba → un día → resultado correcto (comparado con buscaBus) → "Ver la vuelta".

---

## F5 · Pack `salon`

**Resultado verificable:** la reserva completa funciona en el bot de pruebas contra un **calendario de pruebas real** de Google, y nunca contra el calendario del negocio.

### T-5.1 · Cliente de Google Calendar 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-0.4 · **Diseño:** §9.3
- **Hacer:**
  - `integrations/google_calendar/` con la implementación de `CalendarPort` ligada a un calendario: cuenta de servicio, timeout de 10 s, 2 reintentos rápidos, errores transitorios y permanentes, paginación con tope, 409 → `get_event`, limpieza de HTML y comprobación de cada escritura.
  - Fábrica para `ctx.calendar` (T-3.4).
- **Acepta:** el cliente no recibe nunca un `calendar_id` del pack.
- **Tests:** contrato con respuestas grabadas (409, paginación, día completo, 403, 404, 5xx).
- **Notas:** el `Protocol` vive en `packs/salon/ports.py`, y el cliente lo cumple sin importarlo.

### T-5.2 · Huecos y lectura del calendario 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-1.3 · **Diseño:** §9.3, §9.4
- **Hacer:** portar a `packs/salon/`:
  - `compute_slots`.
  - El lector de `[CFG]`.
  - La clasificación de eventos (bot, manual o bloqueo).
  - El parser de descripciones (incluidos `WaId:` y los alias heredados).
  - La partición mañana/tarde.
- **Acepta:** los tests portados de `slots`, `parser` y `calendar` de Peluquería pasan.
- **Tests:** unitarios portados y casos de §9.4 (presencia larga cerca del cierre, antelación mínima).
- **Notas:** —

### T-5.3 · Config del pack 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-1.1 · **Diseño:** §9.2
- **Hacer:** `SalonConfig` con sus validaciones (incluidas `test_calendar_id` distinto de `calendar_id` y `manual_confirmations_since` obligatorio), `SalonTexts` con los textos de Peluquería y `TemplateSpec` de las dos plantillas (§9.7).
- **Acepta:** la config real de Peluquería, convertida, valida.
- **Tests:** unitarios de cada validación.
- **Notas:** —

### T-5.4 · `FakeCalendar` y flujo de reserva 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-5.2, T-5.3, T-1.5 · **Diseño:** §9.1, §9.5, §9.3
- **Hacer:**
  - `packs/salon/testing.py` (`FakeCalendar`).
  - Máquina de estados de Pedir cita: límite (falla en abierto), servicio, día, mañana/tarde, hora, nombre, creación con `ctx.lock` e id determinista, confirmación y `SlotTaken`.
- **Acepta:** los escenarios de reserva de §9.8 en verde.
- **Tests:** escenarios (reserva completa, día sin huecos, mañana/tarde, `SlotTaken`, límite, Calendar caído al pedir cita y al crear, reintento sin duplicado).
- **Notas:** —

### T-5.5 · Ver, mover, cancelar, evento especial y botones 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-5.4 · **Diseño:** §9.1
- **Hacer:**
  - Ver mis citas, mover (crea la nueva y después cancela la antigua, `move_cancel_failed`) y cancelar.
  - Evento especial y "Contacto".
  - Botones de avisos proactivos con comprobación de propiedad (incluidas las citas antiguas con `WaId:`).
  - `NotifyOwner` de cada tipo.
- **Acepta:** escenarios de §9.8 correspondientes en verde.
- **Tests:** escenarios (mover, cancelar, evento activo e inactivo, botón sobre una cita ajena, cita antigua con `WaId:`).
- **Notas:** —

### T-5.6 · Barrido, plantillas y salud del pack 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-5.5, T-3.7 · **Diseño:** §9.6, §9.7, §6.5
- **Hacer:**
  - `calendar_sweep` ejecutado **por calendario**: el real con contactos `main` y el de pruebas con contactos `test`, este último sin confirmaciones manuales.
  - Recordatorios y confirmaciones con sus claves estables.
  - `pack.health` (acceso al calendario).
- **Acepta:** un recordatorio sale una sola vez en dos barridos; no hay confirmaciones de citas anteriores a `manual_confirmations_since`; el barrido del calendario de pruebas nunca envía por el canal `main`.
- **Tests:** escenarios e integración del barrido (los casos de §9.8 y el aislamiento por calendario).
- **Notas:** —

### T-5.7 · Reserva por los dos tipos de canal 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-5.6, T-3.8 · **Diseño:** §9.8, §6.6
- **Hacer:** escenarios e integración de la reserva completa con canal `main` de WhatsApp, canal `main` de Telegram y bot de pruebas.
  - Con WhatsApp, las confirmaciones manuales a un teléfono salen.
  - Con Telegram, se registran y no salen.
- **Acepta:** se cumplen las reglas de §6.6 y los escenarios están en verde.
- **Tests:** escenarios e integración.
- **Notas:** —

### T-5.8 · Migración de citas existentes ⚠️ 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-5.1, T-5.2 · **Diseño:** §9.3
- **Hacer:** `tools/migrate_salon_events.py <slug> [--dry-run]`.
  - Recorre las citas futuras con `WaId:`, crea sus contactos y añade `fp_contact`, `fp_key` y `fp_service`.
  - Es idempotente y muestra un informe.
- **Acepta:** ejecutado dos veces, la segunda no cambia nada; `--dry-run` no escribe nada.
- **Tests:** con `FakeCalendar`.
- **Notas:** escribe en el calendario real del negocio, así que solo lo ejecuta el operador (M-8.1).

### T-5.9 · Concurrencia de reservas 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-5.4, T-3.4 · **Diseño:** §9.5, §17.1
- **Hacer:** integración con BD real: dos contactos reservan el mismo hueco a la vez.
- **Acepta:** una reserva se confirma y la otra recibe `SlotTaken`; un reintento de una reserva ya creada no duplica.
- **Tests:** `tests/integration/`.
- **Notas:** —

### 👤 M-5.1 · Google Cloud de la plataforma
- **Cuándo:** antes de la validación de F5.
- **Qué:**
  1. Crear un proyecto de Google Cloud de la plataforma (con tu cuenta, no la de un negocio).
  2. Habilitar Google Calendar API.
  3. Crear una cuenta de servicio con clave JSON.
  4. Guardar el JSON en local (`google_sa.json`, ignorado por git) y en el gestor de contraseñas, y apuntar el email de la cuenta de servicio.
- **Verificar:** `manage.py shell` → `check_access` contra los dos calendarios de M-5.2 devuelve OK.

### 👤 M-5.2 · Calendarios de desarrollo
- **Cuándo:** antes de la validación de F5.
- **Qué:** crear **dos** Google Calendars, "FlowPilot dev (real)" y "FlowPilot dev (pruebas)", compartirlos con el email de la cuenta de servicio con "Hacer cambios en los eventos" y usarlos, respectivamente, como `calendar_id` y `test_calendar_id` de un tenant `salon` de desarrollo (`tenants/dev-salon/`, `status: onboarding`). Tienen que ser distintos (validación de T-5.3).
- **Verificar:** el tenant `dev-salon` valida; al reservar desde el bot de pruebas, la cita aparece en "FlowPilot dev (pruebas)" y no en "FlowPilot dev (real)".

### ✅ Validación F5
- [ ] Escenarios de §9.8 en verde.
- [ ] Prueba de extremo a extremo en local con calendario real de pruebas:
  - [ ] Reservar desde el bot de pruebas; la cita aparece en el calendario de pruebas con el formato de §9.3.
  - [ ] Moverla y cancelarla.
  - [ ] Un evento `[CFG] CERRADO` quita ese día.
  - [ ] Con un recordatorio forzado (ventana ajustada), llega por el bot de pruebas y "Confirmar" escribe `Estado: confirmada`.
  - [ ] "FlowPilot dev (real)" no se toca en ningún momento.

---

## F6 · Avisos, operación y observabilidad

**Resultado verificable:** las alertas llegan al chat de ops, el latido externo detecta un worker parado y el Admin muestra el estado.

### T-6.1 · Bot de avisos 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-3.6 · **Diseño:** §11, §6.5
- **Hacer:**
  - Entrega de `NotifyOwner` (`notification` y `send_notification`), incluida la redirección a ops del canal `test`.
  - `manage.py notify_link <slug>`.
  - Envío de alertas de operación con enfriamiento de 30 min en la caché de Django en BD.
- **Acepta:** un aviso se entrega una sola vez; sin `telegram_chat_id` solo se registra; una alerta no se repite antes de 30 min.
- **Tests:** integración con Telegram simulado.
- **Notas:** —

### T-6.2 · Comprobación de operación y salud 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-6.1, T-5.6, T-4.4 · **Diseño:** §15.3, §15.1, §15.2
- **Hacer:**
  - `ops_check` cada 5 min con todas las comprobaciones de §15.3 y latido a `HEALTHCHECKS_PING_URL`.
  - Salud diaria de canales: plantillas aprobadas y token de WhatsApp, y `getWebhookInfo` de los bots.
  - `manage.py tenant_health <slug>`.
  - Logs JSON con los campos de §15.1 y el filtro que enmascara teléfonos y tokens.
  - Sentry.
- **Acepta:** cada fila de §15.3 dispara su alerta en un test; los logs no contienen teléfonos completos.
- **Tests:** unitarios e integración por comprobación; test del filtro de logs.
- **Notas:** —

### T-6.3 · Retención y RGPD ⚠️ 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-3.6 · **Diseño:** §12.3, §16.2
- **Hacer:** `retention_cleanup` nocturno por lotes y los comandos `export_contact`, `forget_contact`, `export_tenant` y `purge_tenant` (este último pide escribir el slug para confirmar).
- **Acepta:** cada plazo de §12.3 se aplica; `purge_tenant` no toca otros tenants.
- **Tests:** integración con fechas simuladas.
- **Notas:** —

### T-6.4 · Django Admin 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-6.2 · **Diseño:** §12.2, §13, §15.4, §7.4
- **Hacer:**
  - Admin sobre el alias `owner`, con 2FA (`django-otp`) e integración de Procrastinate.
  - Acciones "Marcar enviado" y "Reenviar" para mensajes `unknown`.
  - Vista "Estado" de §15.4.
- **Acepta:** el Admin solo es accesible por las URLs no públicas; cada cambio queda en `LogEntry`.
- **Tests:** integración de las acciones y de que las URLs de admin no están en el conjunto público.
- **Notas:** —

### T-6.5 · QR y comandos de operación 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-2.4 · **Diseño:** §16.3
- **Hacer:** `tools/qr.py <slug>` (enlace `wa.me` o `t.me` según el canal) y los objetivos del `Makefile` que no dependen del servidor.
- **Acepta:** el QR se genera para los dos tipos de canal.
- **Tests:** unitario del enlace generado.
- **Notas:** —

### 👤 M-6.1 · Bot de avisos y chat de ops
- **Cuándo:** antes de la validación de F6.
- **Qué:** crear el bot de avisos con @BotFather (`NOTIFY_BOT_TOKEN`) y un chat o grupo de ops con ese bot, y anotar su id (`OPS_TELEGRAM_CHAT_ID`). Primero en `.env` local; en el servidor, en M-7.3.
- **Verificar:** una alerta forzada llega al chat de ops.

### 👤 M-6.2 · Sentry y healthchecks.io
- **Cuándo:** antes de la validación de F6.
- **Qué:**
  - Crear un proyecto en Sentry (`SENTRY_DSN`).
  - En healthchecks.io, crear dos checks con notificaciones por email y Telegram:
    - "worker", periodo 5 min y gracia 10 min (`HEALTHCHECKS_PING_URL`).
    - "backup", periodo 6 h y gracia 1 h; se usa en F7.
- **Verificar:** una excepción forzada aparece en Sentry; el check "worker" se pone verde con el worker en marcha.

### ✅ Validación F6
- [ ] Parar el worker en local → healthchecks.io avisa en ≤ 15 min.
- [ ] Una alerta 🔴 simulada (por ejemplo, un tenant `degraded`) llega al chat de ops una sola vez.
- [ ] El Admin funciona con 2FA y la vista "Estado" muestra datos.

---

## F7 · Infraestructura y despliegue

**Resultado verificable:** FlowPilot corriendo en la VPS con HTTPS, desplegado desde GitHub, con backups externos y una restauración probada.

### T-7.1 · Compose de producción y Caddy ⚠️ 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-6.4 · **Diseño:** §14.2, §14.3, §13
- **Hacer:**
  - `compose.prod.yaml`: imagen de GHCR por `SHA`, `read_only`, `tmpfs`, secretos montados de solo lectura, logs rotados y `web` publicado solo en `127.0.0.1:8000`.
  - `Caddyfile` con solo las rutas públicas de §14.3.
  - `.env.example` y `secrets.example.yaml` de producción.
- **Acepta:** en local, con la configuración de producción, las rutas no públicas devuelven 404 a través de Caddy.
- **Tests:** script de comprobación de rutas incluido en `make check-prod-config`.
- **Notas:** —

### T-7.2 · Despliegue 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-7.1, T-0.3 · **Diseño:** §14.6
- **Hacer:**
  - `deploy/deploy.sh <sha>`: pull, migraciones con `sync_tenants`, `up`, espera de `/health` y vuelta automática al SHA anterior con aviso a ops.
  - `.github/workflows/deploy.yml` con `workflow_dispatch` y el entorno `production`.
  - Objetivo `make deploy`.
- **Acepta:** un SHA con `/health` roto vuelve solo al anterior (probado en el servidor en M-7.6).
- **Tests:** `shellcheck` del script en CI.
- **Notas:** —

### T-7.3 · Backups y restauración 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-7.1 · **Diseño:** §14.4
- **Hacer:**
  - `deploy/backup.sh` (`pg_dump`, ficheros de secretos, restic, `forget --prune` con la política del diseño y ping a healthchecks).
  - `deploy/restore.sh` y el timer de systemd cada 6 h.
  - Objetivos `make backup-now` y `make restore-test`.
- **Acepta:** restaurar en local un backup hecho en local deja los mismos conteos por tenant.
- **Tests:** `shellcheck`; prueba de restauración en local documentada en las notas.
- **Notas:** —

### T-7.4 · Preparación del servidor ⚠️ 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-7.2, T-7.3, M-7.1 · **Diseño:** §13, §14.1
- **Hacer:** `deploy/bootstrap-server.sh` (idempotente) y su runbook:
  - Usuario `deploy` con clave restringida a `deploy.sh`; SSH solo con clave; root deshabilitado.
  - `ufw` con 22, 80 y 443; `unattended-upgrades`; `fail2ban`.
  - Docker y el plugin de Compose; directorio `/srv/flowpilot`; timer de backup.
- **Acepta:** ejecutado dos veces, no cambia nada la segunda vez; un escaneo externo de puertos solo muestra 22, 80 y 443.
- **Tests:** `shellcheck`.
- **Notas:** lo ejecutas tú en el servidor (M-7.6).

### T-7.5 · Runbooks y documentación de packs 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-7.4, T-5.6, T-4.5 · **Diseño:** §16.4, §19
- **Hacer:** `docs/runbooks/` 1–11 y `docs/packs/salon.md` y `docs/packs/bus.md` (este con el formato completo del dataset, a partir de `buscaBus/design.md`, apartado 2.3). Pasos concretos y verificables, sin repetir `design.md`.
- **Acepta:** cada runbook tiene síntomas, diagnóstico, pasos y verificación.
- **Tests:** —
- **Notas:** —

### 👤 M-7.1 · Dominio y VPS
- **Cuándo:** antes de T-7.4.
- **Qué:**
  1. Comprar el dominio.
  2. Crear la VPS (Hetzner, UE, 2 vCPU / 4 GB, Ubuntu 24.04) con tu clave SSH.
  3. Crear el registro DNS `api.<dominio>` → IP de la VPS.
- **Verificar:** `ssh root@<ip>` funciona y `dig api.<dominio>` devuelve la IP.

### 👤 M-7.2 · Almacenamiento de backups
- **Cuándo:** antes de la validación de F7.
- **Qué:**
  1. Crear un bucket en Backblaze B2 o Cloudflare R2 (otro proveedor distinto del de la VPS) con una clave limitada a ese bucket.
  2. Generar la contraseña de restic.
  3. Guardar las tres cosas en el gestor de contraseñas.
- **Verificar:** `restic snapshots` desde la VPS lista el primer backup.

### 👤 M-7.3 · Secretos de despliegue
- **Cuándo:** antes de la validación de F7.
- **Qué:**
  1. En la VPS, crear `/srv/flowpilot/.env`, `secrets.yaml` y `google_sa.json` (`chmod 600`).
  2. En GitHub, crear el entorno `production` con aprobación requerida y sus secretos: host, clave SSH de despliegue y `known_hosts`.
- **Verificar:** `deploy.yml` llega a conectar con la VPS.

### 👤 M-7.4 · Bot de pruebas de producción
- **Cuándo:** antes de la validación de F7.
- **Qué:**
  1. Crear un bot distinto del de desarrollo (p. ej. `flowpilot_pruebas_bot`).
  2. Poner su token y un `TEST_BOT_WEBHOOK_SECRET` aleatorio en el `.env` del servidor.
  3. Tras el primer despliegue, ejecutar `manage.py telegram_set_webhook test`.
- **Verificar:** `getWebhookInfo` sin errores y `/start` responde con la lista.

### 👤 M-7.5 · Uptime externo
- **Cuándo:** tras el primer despliegue.
- **Qué:** crear un monitor en UptimeRobot o Better Stack para `https://api.<dominio>/health` cada 5 min, con alerta de caducidad del certificado.
- **Verificar:** el monitor está en verde.

### 👤 M-7.6 · Primer despliegue y simulacro de restauración ⚠️
- **Cuándo:** al final de F7.
- **Qué:**
  1. Ejecutar `bootstrap-server.sh` y lanzar `deploy.yml`.
  2. Comprobar la vuelta atrás desplegando a propósito un SHA con `/health` roto.
  3. Hacer el primer simulacro de restauración en una VPS temporal y anotar el tiempo (objetivo: menos de 2 h).
- **Verificar:** checklist de la validación de F7.

### ✅ Validación F7
- [ ] `https://api.<dominio>/health` responde 200 con certificado válido; `/admin/` devuelve 404 desde fuera y funciona por `make admin-tunnel`.
- [ ] Prueba de extremo a extremo en producción con el bot de pruebas: Autocares (consulta completa) y `dev-salon` contra su calendario de pruebas.
- [ ] Un backup automático aparece en restic y el check "backup" está verde.
- [ ] Simulacro de restauración hecho y anotado.
- [ ] Parar el worker en producción → alerta de healthchecks.io; arrancarlo → recuperación.

---

## F8 · Puesta en marcha de los negocios

**Resultado verificable:** DM Barber Shop y Autocares San Sebastián atendidos por FlowPilot en su canal real; bots antiguos retirados.

### T-8.1 · Tenant de DM Barber Shop 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-5.7 · **Diseño:** §5.2, §9.2
- **Hacer:** `tenants/dm-barber/tenant.yaml`:
  - Canal `main` de WhatsApp con los ids de la app actual, `status: onboarding` y `testers`.
  - Config portada de `Peluqueria/config.yaml`: horario, servicios, ventana, evento especial e interruptores de envío **con sus valores actuales**.
  - `manual_confirmations_since` igual a la fecha de la puesta en marcha.
  - `calendar_id` real y `test_calendar_id` (M-8.1).
- **Acepta:** valida en CI; el horario y los servicios coinciden con los del bot actual.
- **Tests:** validación de tenants de CI.
- **Notas:** —

### T-8.2 · Ensayo de migración de citas 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-8.1, T-5.8, M-8.1 · **Diseño:** §9.3
- **Hacer:** preparar y documentar en `docs/runbooks/` el procedimiento de migración (tú ejecutas los comandos):
  - `migrate_salon_events.py dm-barber --dry-run` en producción e informe revisado.
  - Ejecución real.
  - Comprobaciones posteriores: "Ver mis citas" de un cliente existente muestra sus citas.
- **Acepta:** el procedimiento está escrito, con la vuelta atrás (la migración solo añade propiedades privadas; no hace falta deshacerla).
- **Tests:** —
- **Notas:** —

### T-8.3 · Verificación final de extremo a extremo 🤖
- **Estado:** pending · **Revisión:** — · **Depende de:** T-8.2 · **Diseño:** §1.1
- **Hacer:** checklist de aceptación en `docs/runbooks/` que recorre todas las funcionalidades de §1.1 en producción, para ejecutarla en M-8.2 y M-8.3.
- **Acepta:** cada punto de §1.1 tiene al menos una comprobación concreta.
- **Tests:** —
- **Notas:** —

### 👤 M-8.1 · DM Barber Shop: calendarios, secretos y plantillas ⚠️
- **Cuándo:** antes de T-8.2.
- **Qué:**
  1. El negocio comparte su calendario real con la cuenta de servicio de la plataforma.
  2. Tú creas su calendario de pruebas y lo compartes igual.
  3. Pones los secretos de la app de Meta existente en `secrets.yaml`: `app_secret`, token permanente y `verify_token`.
  4. Compruebas que `confirmacion_cita` y `recordatorio_cita` están aprobadas.
  5. Despliegas y ejecutas la migración de citas (T-8.2).
- **Verificar:** `manage.py tenant_health dm-barber` en verde.

### 👤 M-8.2 · DM Barber Shop: pruebas y cambio de webhook ⚠️
- **Cuándo:** tras M-8.1.
- **Qué:**
  1. Prueba con el dueño desde el bot de pruebas (calendario de pruebas).
  2. En hora valle, cambiar la URL del webhook en la app de Meta a `https://api.<dominio>/webhooks/whatsapp/<public_id>` con el `verify_token` nuevo.
  3. Probar con un `tester.main`, poner `status: active` y desplegar.
  4. Parar el servicio en la VM de GCP, pero conservarla una semana. Para volver atrás, se restaura la URL antigua del webhook.
- **Verificar:** checklist de T-8.3 para `salon`, incluidos un recordatorio real y la confirmación de una cita manual.

### 👤 M-8.3 · Autocares San Sebastián: canal y pruebas ⚠️
- **Cuándo:** con F7 terminada.
- **Qué:**
  1. La empresa revisa el bot desde el bot de pruebas y confirma el PDF de `make bus-revision`.
  2. Alta de WhatsApp con el checklist de §6.3 en el portfolio de la empresa: número, app, System User con token permanente y webhook a `https://api.<dominio>/webhooks/whatsapp/<public_id>`. Rellenar los ids de Meta en `tenant.yaml`. Este pack no usa plantillas.
  3. Secretos en `secrets.yaml`, `status: active` y despliegue.
- **Verificar:** checklist de T-8.3 para `bus`.

### 👤 M-8.4 · Retirar los bots antiguos
- **Cuándo:** una semana después de M-8.2 sin incidencias.
- **Qué:** apagar y borrar la VM de GCP (servicio, nginx, DuckDNS) y archivar los repositorios `Peluqueria` y `buscaBus` en GitHub (solo lectura).
- **Verificar:** la VM no existe y los repositorios figuran como archivados.

### ✅ Validación F8 (final)
- [ ] Checklist de T-8.3 completa en los dos negocios.
- [ ] Una semana sin alertas 🔴 sin resolver.
- [ ] Bots antiguos retirados.
