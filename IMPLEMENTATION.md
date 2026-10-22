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
| F1 | Núcleo puro (`core`) | 5 | 5 | done |
| F2 | Datos, tenants y aislamiento | 5 | 5 | done |
| F3 | Canales y runtime | 10 | 10 | validación pendiente (M-3.1) |
| F4 | Pack `bus` | 6 | 2 | in_progress |
| F5 | Pack `salon` | 9 | 0 | pending |
| F6 | Avisos, operación y observabilidad | 5 | 0 | pending |
| F7 | Infraestructura y despliegue | 5 | 0 | pending |
| F8 | Puesta en marcha de los negocios | 3 | 0 | pending |
| **Total** | | **52** | **26** | |

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
- **Estado:** done · **Revisión:** aprobada · **Depende de:** T-1.1 · **Diseño:** §6.1, §7.4
- **Hacer:** `core/limits.py` con los límites de §6.1 y `plan_sends`: fusión de textos, texto dentro del interactivo si cabe, validación de límites y truncado con registro.
- **Acepta:** cada regla de §7.4 cubierta; los ids de más de 64 bytes se rechazan.
- **Tests:** unitarios de cada regla y caso límite (1.024 y 4.096 caracteres, 3 botones, 10 filas, títulos de 20 y 24, ids de 64 bytes).
- **Notas:** `check(reply)` devuelve las infracciones separadas en `fatal` y truncables, como descripciones sin contenido, así que se pueden registrar; el arnés de T-1.5 lo reutilizará. `plan_sends(replies, strict=False) -> list[Reply]` es puro: fusiona textos (separador `\n\n`, sin pasar de 4.096), mete el texto previo en el cuerpo del interactivo si caben en 1.024 y aplica los límites. `seq` e `idem_key` se asignan en T-3.6. Las infracciones `fatal` fallan siempre, porque truncarlas rompería los botones. Son ids de más de 64 bytes, vacíos o repetidos; títulos de botón repetidos; mensajes o secciones sin botones o filas; varias secciones sin título; y cuerpo vacío. Se comprueban antes de fusionar y otra vez después de truncar. Las longitudes se cuentan en caracteres; el adaptador de Telegram (T-3.2) tendrá en cuenta que Telegram cuenta en UTF-16. Añadidos a §6.1 los límites reales de WhatsApp que faltaban (cabecera y pie ≤ 60, etiqueta del botón de lista ≤ 20, título de sección ≤ 24, títulos de botón únicos, secciones con filas y con título si hay varias) y precisado §7.4.

### T-1.3 · Utilidades de interfaz, texto y fechas 🤖
- **Estado:** done · **Revisión:** aprobada · **Depende de:** T-1.1 · **Diseño:** §8.3
- **Hacer:** portar a `core/ui.py`, `core/text.py` y `core/dates.py`:
  - `interactive.py` de ambos bots: helpers y `paginate`.
  - `_norm` y `_strip_html` de Peluquería.
  - `format_date_es` y `next_days` con `zoneinfo`.
- **Acepta:** las funciones portadas se comportan como en el origen (sus tests portados pasan); sin `pytz`.
- **Tests:** portados y adaptados de los dos repos.
- **Notas:**
  - **`core/text`:** `fold` es exactamente `_norm` de Peluquería (minúsculas, sin tildes, recortado, conservando la puntuación) y sus tests están portados. El parser del salón (T-5.2) la necesita, porque busca `[cfg]`, `HH:MM-HH:MM` y `corte+barba`. `normalize` es `fold` con la puntuación pasada a espacio y los espacios colapsados (§8.3): es `normalizar` de buscaBus sin las palabras vacías, que se quedan en el pack `bus` (T-4.1). `strip_html` es el original. Añadido `fold` a §8.3.
  - **`core/dates`:** `weekday_es`, `format_date_es` y `next_days(now, n_calendar_days, skip_weekdays=())`. El origen excluía siempre el domingo (su docstring decía lunes a viernes, pero el código quitaba solo el domingo); aquí lo decide quien llama, que pasa `skip_weekdays={6}`. Toma "hoy" en la zona de `now` y rechaza fechas sin zona. Sin `pytz`.
  - **`core/ui`:** `trunc`, `button`, `row`, `section`, `buttons_msg` y `list_msg` construyen `core.replies`. Los títulos y la etiqueta de la lista se truncan como en el origen; cualquier otra infracción lanza `LimitError` (con `core.limits.check`).
  - **`paginate`:** no existe en el origen; sale de `paginar` de buscaBus (que trocea la lista) y del patrón de `build_lineas`. `per_page` tiene que ser positivo. Devuelve las filas de la página, la fila "más" si quedan páginas y siempre la de "volver" (8 + 2 = 10). Quien llama codifica la página siguiente en `more_id`. Una página fuera de rango vuelve a la primera, como en `flujo.py`.
  - **Tests:** portados `TestTrunc`, `TestNorm`, `TestStripHtml`, `TestGetNextDays`, `TestFormatDateEs` y `test_paginar`, adaptados.
  - **Para T-4.x y T-5.x:** los constructores propios de cada bot (`build_*`, `_fila_localidad`, `_titulo_usar`) se quedan en su pack.
  - **Decidido por la persona:** `strip_html`, `next_days`, `format_date_es` y `paginate` se quedan en `core` aunque hoy los use un solo pack; §8.3 admite utilidades genéricas sin lógica de negocio.

### T-1.4 · Reglas comunes de conversación 🤖
- **Estado:** done · **Revisión:** aprobada · **Depende de:** T-1.1 · **Diseño:** §7.2, §7.3
- **Hacer:** en `core/conversation.py`, funciones puras compartidas por el runtime y el arnés:
  - `effective_state`: caducidad y versión del estado.
  - `global_command`: `menu`, `menú`, `inicio`, `/start`, `baja` y `alta`.
  - `recovery_result`.
  - El texto de reinicio amable.
- **Acepta:** caducidad a los 30 min; una versión distinta reinicia; `/start` equivale a `menu`.
- **Tests:** unitarios.
- **Notas:**
  - **`effective_state`:** recibe `state`, `state_version`, `last_inbound_at`, la versión y el timeout del pack y `now`, y devuelve `EffectiveState(state, reset, notices)`. Si la conversación caducó (más de 30 min, estrictamente), reinicia en silencio; si cambió la versión, reinicia y añade el texto amable a `notices`. Si pasan las dos cosas, gana la caducidad. Con un estado vacío no hay nada que reiniciar.
  - **`global_command`:** solo mira mensajes de tipo `text`, normalizados con `core.text.normalize`. `/start` se compara aparte, y también se acepta `/start <param>` (enlaces profundos) y `/start@bot`; un "start" sin barra no es un comando.
  - **`opt_result` y `menu_message`:** son la parte pura de `run_global_command`, para que el arnés de T-1.5 haga lo mismo que el runtime. `baja` y `alta` devuelven `UpdateContact` y un texto de confirmación y conservan el estado; `menu` deja el estado en `{}` y el pack recibe un texto vacío.
  - **`recovery_result()`:** no recibe el tenant, porque el texto es común (§7.2).
  - **Textos:** los de `baja` y `alta` son nuevos; el de recuperación y el de reinicio vienen de §7.2 y §7.3.
  - **Para T-3.5:** `state=None` en el resultado conserva el estado **efectivo** (ya reiniciado si caducó), no el guardado. Las `notices` se envían también con los comandos globales.
  - **Diseño:** §7.3 ampliado y el pseudocódigo de §7.2 al día (`effective_state` con campos sueltos y `notices`, `recovery_result()` sin tenant).

### T-1.5 · Arnés de pruebas de conversación 🤖
- **Estado:** done · **Revisión:** aprobada · **Depende de:** T-1.2, T-1.4 · **Diseño:** §17.2
- **Hacer:** `core/testing/`:
  - Reloj fijo y fixture de tenant de ejemplo.
  - `send` y `press` con `expect` para texto, botones y filas de lista.
  - Comprobación automática de límites en cada respuesta.
  - Simulación de los dos tipos de canal.
  - Un pack de juguete (`tests/toy_pack`) que lo ejercite.
- **Acepta:** el ejemplo de §17.2, adaptado al pack de juguete, se puede escribir tal cual; una respuesta que se sale de los límites hace fallar el test.
- **Tests:** tests del propio arnés con el pack de juguete.
- **Notas:** el render real con los dos adaptadores se añade en T-3.2, cuando existan.
  - **Arnés:** `core/testing/` tiene `Conversation(pack, config=, data=, channel="whatsapp"|"telegram", tenant=, calendar=, now=, attempts=)`, `Turn.expect(text=, text_contains=, buttons=, rows=, list_includes=, nothing=)`, que devuelve el `Turn` para encadenar, `FixedClock` (con `set` y `advance`; da la hora en la zona del tenant, con su horario de verano o de invierno) y `sample_tenant()`. Como fixture del tenant de ejemplo hay una función, no una fixture de pytest; cada pack monta la suya.
  - **Cada turno sigue el orden de `process_event`:** `effective_state`, comando global, pack y `plan_sends(strict=True)`; después, el estado pasa por JSON y se aplican las acciones. Un `TransientError` se reintenta `attempts` veces (por defecto 1) con el mismo evento y después da el texto de recuperación; cualquier otra excepción se propaga para que un fallo no quede oculto. El pack recibe en cada intento una copia del estado pasada por JSON (`allow_nan=False`).
  - **Simulación de canal:** el contacto de WhatsApp tiene teléfono y el de Telegram no.
  - **Comprobaciones extra:**
    - `press` exige que el id se haya ofrecido antes, en una respuesta o en un aviso proactivo (`check=False` lo desactiva).
    - Los `SendProactive` se validan contra su `TemplateSpec`: tiene que estar declarada en `pack.templates`, con el número de botones correcto, payloads ≤ 64 bytes y los parámetros `{n}` justos. Solo se pueden pulsar los botones de los avisos dirigidos a este contacto.
    - `ctx.lock` registra las claves.
  - **`replay()` y `run_periodic()`:** existen para los escenarios de reintento y de barrido de T-5.x. `replay()` deshace estado, cambios del contacto, acciones y respuestas del último turno antes de repetirlo; los efectos del propio pack, como un calendario falso, se mantienen.
  - **Pack de juguete:** `tests/toy_pack/` incluye menú, nombre con `NotifyOwner`, lista paginada con `SendProactive`, error transitorio y una periódica. Lo ejercitan sus escenarios en los dos canales. Un test comprueba que solo importa `core` y `pydantic`, porque import-linter no mira `tests/`.
  - **Diseño:** §17.2 ampliado.

### ✅ Validación F1
- [x] El pack de juguete pasa sus escenarios con el arnés.
- [x] `make check` en verde.

---

## F2 · Datos, tenants y aislamiento

**Resultado verificable:** modelos con RLS probada, registro de tenants que valida `tenants/*` y cola Procrastinate operativa.

### T-2.1 · Roles de BD y alias ⚠️ 🤖
- **Estado:** done · **Revisión:** aprobada (y aprobación ⚠️ de la persona, 2026-10-21) · **Depende de:** T-0.2 · **Diseño:** §12.2, §5.3
- **Hacer:**
  - Script de inicialización de PostgreSQL (local y prod) que crea `fp_owner` (dueño de las tablas, `BYPASSRLS`) y `fp_app`.
  - Alias de Django `default` (`DB_APP_URL`) y `owner` (`DB_OWNER_URL`); las migraciones usan `owner`.
  - Permisos de `fp_app` sobre las tablas de la aplicación y de Procrastinate.
- **Acepta:** las migraciones se ejecutan como `fp_owner`; `fp_app` no puede hacer DDL.
- **Tests:** test de que `fp_app` no tiene `BYPASSRLS` ni puede crear tablas.
- **Notas:**
  - **Script de roles:** `deploy/postgres/init-roles.sh` es idempotente; probado dos veces y con `shellcheck`.
    - Crea `fp_owner` (`BYPASSRLS`, sin superusuario, `CREATEDB`, `CREATEROLE` ni `REPLICATION`) y `fp_app` (sin `BYPASSRLS`). Las contraseñas vienen de `FP_OWNER_PASSWORD` y `FP_APP_PASSWORD` (añadidas a §5.3) y se leen con `\getenv`, así que no aparecen en `ps`. Se probó con comillas, `;` y `\` en las contraseñas, sin inyección. Necesita psql 15 o superior.
    - Pone `fp_owner` como dueño de la base y de `public`. Quita a `PUBLIC` todos los permisos de la base y del esquema (así nadie más tiene `TEMP` ni `CREATE`), y también `CONNECT` y `TEMP` sobre `postgres` y `template1`.
    - Da a `fp_app` `CONNECT`, `USAGE` y, con `ALTER DEFAULT PRIVILEGES FOR ROLE fp_owner`, `SELECT/INSERT/UPDATE/DELETE` sobre tablas y `USAGE/SELECT` sobre secuencias. Eso cubre las tablas de Procrastinate que llegan en T-2.5.
    - Con `POSTGRES_TEST_DB` hace lo mismo con la base de pruebas.
  - **Dónde se ejecuta:** en local, el contenedor `db` lo lanza al inicializar el volumen. En CI hay un paso que lo ejecuta contra el servicio. En producción lo montará `compose.prod.yaml` (T-7.1).
  - **Alias de Django:** `default` (`DB_APP_URL`) y `owner` (`DB_OWNER_URL`). Si la variable no está definida, en local se usa el valor por defecto; si está vacía, como en el worker, no hay alias `owner`. `manage.py migrate` usa `owner` por defecto; no hay *router*, porque uno que negara `default` haría que `migrate --database default` marcara migraciones como aplicadas sin ejecutarlas.
  - **Tests:** como `fp_app` no puede crear bases ni tablas, el `conftest.py` raíz sustituye `django_db_setup`. Usa la base `test_flowpilot` ya creada, apunta los dos alias a ella y migra como `fp_owner`. Los tests consultan como `fp_app`. `make check` necesita `make up`. La base de pruebas se reutiliza; si se edita una migración ya aplicada, se reinicia con `docker compose down -v` (lo dice el README).
  - **`compose.yaml`:** usa `fp_app` y `fp_owner` (el worker, sin `DB_OWNER_URL`), publica `db` en `127.0.0.1:5433` para los tests desde el host (el 5432 suele estar ocupado) y comprueba la salud por TCP (también en CI), porque durante la inicialización `pg_isready` por socket da OK antes de tiempo. El `environment` del worker sustituye entero al del ancla. Hace falta `docker compose down -v` la primera vez.
  - **Pendiente para T-2.5:** los tests transaccionales (`transactional_db`) vacían las tablas con `TRUNCATE` desde cada alias, y `fp_app` no tiene `TRUNCATE`, a propósito, porque ignora RLS. Habrá que vaciar solo con `owner`.
  - **Verificado:** CI simulado en local con un PostgreSQL 18 limpio: script por TCP, `pytest`, `makemigrations --check` y `lintmigrations`.

### T-2.2 · Modelos y políticas RLS ⚠️ 🤖
- **Estado:** done · **Revisión:** aprobada (y aprobación ⚠️ de la persona, 2026-10-21) · **Depende de:** T-2.1 · **Diseño:** §12.1, §12.2
- **Hacer:**
  - Modelos `Tenant`, `Contact`, `Conversation`, `InboundEvent`, `OutboundMessage`, `Notification`, `TestBotEvent` y `TestSession`.
  - UUIDv7, `UNIQUE(tenant_id, id)`, claves foráneas compuestas y restricciones únicas del diseño.
  - Migración con `ENABLE`/`FORCE ROW LEVEL SECURITY` y la política `tenant_isolation` en cada tabla con `tenant_id`.
- **Acepta:** el esquema coincide con §12.1; `makemigrations --check` limpio; el linter de migraciones pasa.
- **Tests:** test de restricciones únicas (eventos duplicados, `idem_key` duplicada).
- **Notas:**
  - **Dónde viven:** una sola app de Django (`flowpilot`). `Tenant` está en `tenancy/models.py` y el resto en `runtime/models.py`; `flowpilot/models.py` los reexporta.
  - **Tipos:** UUIDv7 con `uuid.uuid7` (Python 3.14); `tenant.id` viene del YAML. `UNIQUE(tenant, id)` en los padres (`contact` e `inbound_event`) y las únicas de §12.1.
  - **`0001_initial`:** reordenada a mano (`Tenant` primero, y el FK dentro del `CreateModel` de `Contact`) para que el linter no diera un falso positivo de `NOT NULL`.
  - **`0002_tenant_isolation` (RunSQL, con su reversa):**
    - Claves compuestas: `conversation` y `outbound_message` hacia `contact` (`CASCADE`), y `outbound_message` hacia `inbound_event` (`SET NULL (inbound_event_id)`, PostgreSQL 15 o superior).
    - `ENABLE` y `FORCE ROW LEVEL SECURITY` con la política `tenant_isolation` en las 5 tablas con `tenant_id` y en `tenant`, esta sobre su propio `id`.
    - `test_bot_event` y `test_session` quedan sin RLS.
    - `REVOKE INSERT, UPDATE, DELETE ON tenant FROM fp_app`: solo `sync_tenants`, como `owner`, escribe en el reflejo.
  - **Permisos:** `fp_app` recibe acceso a las tablas nuevas por los permisos por defecto de T-2.1.
  - **Nulos y valores por defecto:** `phone_e164`, `provider_message_id` y `pricing_category` son `NULL` como dice §12.1 (con `noqa: DJ001`). El resto del texto opcional es `""`. Los valores por defecto están también en la base (`db_default`), así que un `INSERT` en SQL no tiene que dar todas las columnas. `idem_key` es `TextField`, porque una clave estable puede llevar un `gcal_id` de hasta 1.024 caracteres. `tenant_id` y `conversation.contact_id` no tienen índice propio, porque ya los cubren las únicas.
  - **`__str__`:** nunca muestra datos personales: el id, el `slug` del tenant o el `update_id`. `TestBotEvent` y `TestSession` llevan `__test__ = False` para que pytest no los recoja como tests.
  - **Tests:** únicas (evento duplicado, `idem_key` duplicada en mensajes y avisos, contacto, conversación, `update_id`), claves compuestas entre tenants, borrados en SQL y RLS activada y forzada justo en las tablas de tenant. Escriben con `owner`; el aislamiento entre tenants llega en T-2.3.
  - **Para T-6.3:** índices de retención por antigüedad (`inbound_event`, `outbound_message`, `contact`, `test_bot_event`) y uno parcial de `outbound_message` con `status = 'unknown'` para §15.3.
  - **Diseño:** §12.1 y §12.2 ampliados con los detalles de implementación.

### T-2.3 · `tenant_tx` y test de aislamiento 🤖
- **Estado:** done · **Revisión:** aprobada · **Depende de:** T-2.2 · **Diseño:** §12.2
- **Hacer:** `tenant_tx(tenant_id)` (`set_config` local, prohibido anidar) y un test genérico que recorra **todos** los modelos con `tenant_id`.
- **Acepta:**
  - El tenant A no lee, modifica, borra ni inserta filas de B.
  - No se pueden crear claves foráneas hacia B.
  - Sin tenant fijado se leen 0 filas.
  - Anidar `tenant_tx` falla.
  - Un modelo nuevo sin política hace fallar el test (comprobado con un modelo temporal).
- **Tests:** `tests/isolation/`.
- **Notas:**
  - **`tenant_tx(tenant_id)`** (`flowpilot/tenancy/tx.py`): `transaction.atomic(using="default", durable=True)` más `set_config('app.tenant_id', …, true)`.
    - **Anidar falla**, con el `RuntimeError` de Django; un bloque durable sí se permite dentro de la transacción de un test.
    - **Al salir bien** vacía el ajuste, así que dentro de un test no queda un tenant colgado. **Ante un error, o con el bloque marcado para rollback** (`needs_rollback`), no hace falta: el rollback, aunque sea a un savepoint, ya lo deshace, e intentarlo daría error u ocultaría el original.
  - **Tests (`tests/isolation/test_isolation.py`):** son transaccionales, porque los tenants los crea `owner` y `fp_app` tiene que verlos commiteados. `conftest.py` hace que el `flush` entre tests se ejecute como `fp_owner`, porque `fp_app` no tiene `TRUNCATE`; es solo para tests y los roles no cambian. Cada modelo con `tenant_id` necesita una factoría en `FACTORIES` o estar en `PLATFORM_MODELS` (`TestSession`, sin RLS por diseño). Para cada modelo se prueba que:
    - A no lee filas de B;
    - `UPDATE`, `DELETE` y `.update()` sobre filas de B afectan a 0 filas;
    - no se insertan filas de B, con los padres de B ya creados para que solo RLS pueda impedirlo;
    - no se mueve una fila a B;
    - no se apunta a filas de B (por cada clave foránea; el error tiene que venir de la clave compuesta `*_fk`);
    - sin tenant se leen 0 filas, `UPDATE` y `DELETE` afectan a 0 y un `INSERT` falla;
    - en la tabla `tenant`, cada uno solo ve el suyo.

    Además:
    - cada tabla con columna `tenant_id`, vista desde `information_schema` para incluir tablas sin modelo, tiene RLS activada y forzada y `tenant_isolation` como única política, con `USING` y `WITH CHECK` exactos;
    - se detectan una tabla sin política y una política permisiva de más;
    - anidar falla, también dentro de otro `atomic`;
    - tres tests no transaccionales, porque ahí `tenant_tx` es un savepoint, comprueban que no queda tenant tras salir bien, tras un error y tras `set_rollback(True)`.
  - **Mutaciones:** comprobadas y revertidas.
    - Un modelo temporal con `tenant_id`, sin política ni factoría, hace fallar el test de cobertura y el de la política.
    - Una política `FOR INSERT WITH CHECK (true)` en `conversation` y `outbound_message` hace fallar las comprobaciones de política y la inserción en `conversation`. En `outbound_message`, el `INSERT ... RETURNING` de Django ya choca con la política de lectura.
  - **Para T-2.5:** este `flush` como `owner` resuelve también los tests transaccionales de Procrastinate.
  - **Diseño:** §12.2 ampliado.

### T-2.4 · Registro de tenants y secretos 🤖
- **Estado:** done · **Revisión:** aprobada · **Depende de:** T-2.2, T-1.1 · **Diseño:** §5.2, §5.3, §5.4
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
- **Notas:**
  - **Esquema común** (`flowpilot/tenancy/schema.py`, pydantic con `extra="forbid"`):
    - Valida `id` como UUIDv7, el formato de `slug` y `public_id`, la zona horaria y el canal discriminado por `type`.
    - `testers.main` se valida según el tipo de canal: BSUID o teléfono en WhatsApp, entero en Telegram.
    - Los ids de Meta (numéricos) y el `bot_username` (`[A-Za-z0-9_]{5,32}`) son opcionales, porque T-4.6 necesita que Autocares valide antes de tenerlos; mientras falten, el canal `main` queda deshabilitado.
    - Los secretos son `SecretStr` (`WhatsAppSecrets` y `TelegramSecrets`, este con `webhook_secret` de 32 caracteres o más).
  - **Registro** (`flowpilot/tenancy/registry.py`):
    - `load_registry(tenants_dir, secrets_file, packs)` es puro y testeable; `get_registry()` es la instancia del proceso, perezosa, con `settings.TENANTS_DIR`, `settings.SECRETS_FILE` (nuevo en settings y `.env.example`) y `packs.registry.PACKS`.
    - **Índices:** por id, slug, `(tipo, public_id)`, `phone_number_id` y tester de Telegram. `visible_to()` cubre el bot de pruebas (los operadores ven todos) y `serving(pack)` da los tenants no degradados ni `offboarded`; T-3.7 decide si `paused` cuenta.
    - **`problems`** reúne lo que debe fallar en CI.
    - **Fallos:**
      - Un fichero ilegible (sin permisos, no UTF-8, YAML inválido), un directorio sin `tenant.yaml` o un fallo en la parte común dejan el tenant fuera, en `errors`.
      - Si el `secrets.yaml` no se puede usar (ilegible, o sin un mapa de slugs con claves de texto), queda en `secrets_error` y los demás tenants cargan igual, con su canal `main` deshabilitado.
      - Pack desconocido, config inválida, `load_data` que falla o claves repetidas dejan el tenant `degraded`. Las repetidas además lo marcan `ambiguous` a él y a todos los implicados: no se enrutan ni se sincronizan.
      - Si faltan secretos o ids, solo se deshabilita el canal `main`.
      - Las entradas de `secrets.yaml` de slugs desconocidos se avisan, solo por nombre.
      - Si no existe `tenants/`, el registro queda vacío y se avisa.
    - **Logs:** registran nombres de campos, nunca valores.
  - **`packs/registry.py`:** `PACKS: dict[str, Pack] = {}`. Los tests registran el pack de juguete con `monkeypatch`.
  - **Comandos:**
    - `sync_tenants` usa `update_or_create` como `owner`, en una transacción por tenant. Omite e informa de los tenants ambiguos (un `id` copiado nunca sobrescribe la fila del otro), de los que chocan por `slug` con otro `id` y de los ilegibles, y no falla por ellos (§5.4).
    - `new_tenant <slug> --pack --channel [--name]` genera UUIDv7, un `public_id` de 16 caracteres `[a-z0-9]`, `status: onboarding`, `Europe/Madrid` y la config por defecto del pack (`null` en los campos obligatorios; los valores por defecto se pasan a JSON con `TypeAdapter`). Nunca sobrescribe. `--channel` es necesario porque el canal es obligatorio en el esquema.
  - **Para T-3.x y T-6.x:** el texto genérico a los contactos de un tenant `degraded` y la alerta 🔴 son del runtime y del bot de avisos.
  - **Tests:** unitarios del registro, integración de los dos comandos (idempotencia, cambios, tenants rotos) y `tests/test_tenants.py`, la puerta de CI sobre `tenants/*` (hoy vacío).
  - **Diseño:** §5.2, §5.4 y §16.1 (`--channel`) ampliados.

### T-2.5 · Cola Procrastinate 🤖
- **Estado:** done · **Revisión:** aprobada · **Depende de:** T-2.1 · **Diseño:** §7.5, §4.2
- **Hacer:**
  - App de Procrastinate con las colas `inbound`, `outbound` y `periodic`, y `flowpilot/jobs.py` con el registro de tareas.
  - El worker de `compose.yaml` ejecuta `procrastinate worker --concurrency 4`.
  - Parada ordenada.
- **Acepta:**
  - Un trabajo de ejemplo se encola y se ejecuta.
  - Dos trabajos con el mismo `lock` se ejecutan en orden de creación y nunca a la vez.
- **Tests:** integración del orden por candado.
- **Notas:**
  - **Integración:** `procrastinate.contrib.django` en `INSTALLED_APPS`, con su app sobre el alias `default` (`fp_app`). Sus migraciones las aplica `fp_owner`, y `fp_app` recibe acceso a sus tablas por los permisos por defecto de T-2.1 (comprobado).
  - **`flowpilot/jobs.py`:** reexporta `app` y declara las colas `INBOUND`, `OUTBOUND` y `PERIODIC`; se descubre con `PROCRASTINATE_AUTODISCOVER_MODULE_NAME = "jobs"`. Todavía no tiene trabajos (llegan en T-3.x); el trabajo de ejemplo vive solo en el test.
  - **Worker en `compose.yaml`:** `manage.py procrastinate worker --concurrency 4 --shutdown-graceful-timeout 50` con `stop_grace_period: 60s`. Añadido el *flag* a §4.2, §7.5 y §14.2.
  - **Verificado en local:** un trabajo encolado desde `web` lo ejecuta el worker, y tras SIGTERM se para de forma ordenada ("Stop requested" → "Stopped worker").
  - **Tests (`tests/integration/test_queue.py`, transaccionales):**
    - un trabajo se encola y se ejecuta;
    - cuatro trabajos con el mismo candado y 4 huecos de concurrencia se ejecutan en orden de creación y sin solaparse (el primero tarda 0,3 s);
    - con candados distintos sí se ejecutan a la vez: `a` espera con un `threading.Event` a que empiece `b`, sin depender de tiempos.

    El worker se lanza en el propio proceso con el mismo conector que el comando (`replace_connector(get_worker_connector())`). Con `DjangoConnector`, el `jsonb` llega como texto y el trabajo falla. Como con `wait=False` el worker se para si los trabajos que quedan están bloqueados por un candado, se relanza hasta vaciar la cola. Pasan estables (6 de 6).
  - **`lintmigrations`:** excluye la app `procrastinate` (`MIGRATION_LINTER_OPTIONS`), porque sus migraciones no son nuestras; cualquier app propia nueva sí se analiza.
  - **Limpieza:** las tablas de Procrastinate son modelos no gestionados y el `flush` no las vacía, así que el test borra sus trabajos como `owner`.
  - **Recarga en local:** §14.2 corregido. El worker no se recarga solo; tras cambiar código, `docker compose restart worker`.

### ✅ Validación F2
- [x] Test de aislamiento en verde en CI.
- [x] `sync_tenants` con un tenant de ejemplo crea su fila `tenant`.
- [x] El orden por candado está comprobado.

---

## F3 · Canales y runtime

**Resultado verificable:** el pack de juguete conversa de extremo a extremo por el bot de pruebas de desarrollo (`telegram_poll`) y por WhatsApp simulado en tests de integración.

### T-3.1 · Contrato de adaptador y adaptador de WhatsApp ⚠️ 🤖
- **Estado:** done · **Revisión:** aprobada (y aprobación ⚠️ de la persona, 2026-10-21) · **Depende de:** T-1.1 · **Diseño:** §6.2, §6.3
- **Hacer:**
  - `ChannelAdapter` y `SendOutcome`.
  - `WhatsAppAdapter`: `verify` (HMAC), `parse` (mensajes, botones de plantilla, BSUID, estados, `phone_number_id`), `render` (incluidas plantillas), `send` con la tabla de resultados y verificación `GET`.
  - Se porta de `webhook.py` y `whatsapp.py` de Peluquería.
- **Acepta:** cada fila de la tabla de §6.3 produce el `SendOutcome` correcto; el cuerpo de las respuestas 4xx nunca se registra.
- **Tests:** contrato contra payloads reales grabados en `tests/fixtures/whatsapp/` (texto, `button_reply`, `list_reply`, botón de plantilla, BSUID, estados con `pricing`, tipos no soportados) y respuestas de error simuladas con `httpx`.
- **Notas:**
  - **Contrato** (`flowpilot/channels/base.py`): `ChannelAdapter[C, S]` es un `Protocol` genérico (canal y secretos de cada tipo), con `InboundItem`, `StatusItem`, `Sent`, `Rejected`, `RetryLater(after_s=None)` y `Ambiguous`. Cada elemento lleva en `payload` su parte del cuerpo, autosuficiente: es lo que guardará `inbound_event.payload`, y `parse_stored` la vuelve a convertir en el mismo elemento (para T-3.5). `StatusItem` añade `provider_message_id` y `error` (solo códigos), que `apply_status` necesita (§7.2).
  - **`WhatsAppAdapter`** (`flowpilot/channels/whatsapp/adapter.py`): `verify` (HMAC del cuerpo crudo con `compare_digest`), `verify_subscription` para el `GET`, `parse`, `acknowledge` (no hace nada), `render` (texto, botones, lista y plantilla con parámetros y `quick_reply`) y `send` con la tabla de §6.3 (`classify`). El cliente `httpx` se inyecta en el constructor; los tests usan `MockTransport`. Nueva variable `WHATSAPP_GRAPH_VERSION` (por defecto `v23.0`) en settings y `.env.example`.
  - **Corrección del diseño (documentación de Meta):** el BSUID llega en `messages[].from_user_id` (y en `contacts[].user_id`), no en `messages[].user_id` como leía Peluquería; se aceptan los dos. Para enviar a un BSUID se usa `recipient` en lugar de `to`. §6.3 y §18 actualizados.
  - **Decisiones añadidas a §6.3:** códigos de destinatario 131021, 131026 y 131030; un 2xx sin `messages[0].id` es `Ambiguous`; un 5xx sin el cuerpo de error de Meta es `Ambiguous`; un fallo al conectar (`ConnectError`, `ConnectTimeout`, `PoolTimeout`) es `RetryLater`, porque no salió nada; `Retry-After` se ignora si no es finito y se limita a 3.600 s; los mensajes `system` se descartan; un texto vacío se descarta, como en Peluquería.
  - **Logs:** solo estado HTTP y códigos de error; nunca cuerpos, identificadores, textos ni tokens (lo comprueba un test). Los *loggers* `httpx` y `httpcore` pasan a `WARNING` en settings, porque en `INFO` registran la URL (la de Telegram, en T-3.2, lleva el token).
  - **De la revisión:** `verify` compara bytes (una cabecera no ASCII lanzaba `TypeError` en lugar de dar `False`). Un canal sin `phone_number_id` no acepta nada. Pendiente de comprobar con el número real (M-4.1): si Meta devuelve los errores de límite 130429 o 131056 con HTTP 400, hoy son `Rejected(other)`, como dice la tabla.
  - **Fixtures:** no hay número de WhatsApp del que grabar; los cuerpos de `tests/fixtures/whatsapp/` siguen los ejemplos de la documentación de Meta, con datos ficticios (lo explica su `README.md`). Sustituirlos por grabaciones reales anonimizadas cuando exista el número de pruebas (M-4.1).
  - **Tests:** `tests/contract/test_whatsapp.py` (firma, `GET`, cada tipo de mensaje y estado, descartes, ida y vuelta del `payload` guardado, `render` y cada fila de la tabla de resultados, también errores de red).

### T-3.2 · Adaptador de Telegram 🤖
- **Estado:** done · **Revisión:** aprobada · **Depende de:** T-3.1 · **Diseño:** §6.4
- **Hacer:**
  - `TelegramAdapter`: `verify` (secret token), `parse` (solo chats privados, `callback_query`), `acknowledge` (`answerCallbackQuery`), `render` (listas como botones con descripciones en el texto, `*negrita*` a HTML con escape) y `send`.
  - Conectar los dos adaptadores al arnés (renderizado de cada respuesta de los escenarios).
- **Acepta:** la tabla de resultados de §6.4 se cumple; los grupos se ignoran; el texto se escapa correctamente.
- **Tests:** contrato con fixtures grabados en `tests/fixtures/telegram/` (mensaje, `/start`, `callback_query`, grupo, sticker, 403, 429 con `retry_after`).
- **Notas:**
  - **`TelegramAdapter`** (`flowpilot/channels/telegram/adapter.py`): `verify` (`secret_token` en bytes y en tiempo constante), `parse`, `acknowledge`, `render`, `send` y `classify` con la tabla de §6.4, más `overflow(out)`. Mismo patrón que WhatsApp: cliente `httpx` inyectable; un fallo al conectar es `RetryLater` y `Retry-After` se limita a 3.600 s.
  - **Canal del bot de pruebas:** el parámetro de canal es `TelegramChannel | None`; `None` es el bot de pruebas, que no tiene `tenant.yaml` (T-3.8 lo usará así).
  - **Para T-3.5:** un `callback_query` no trae fecha, así que su `received_at` es la hora del `parse` y no se repite al volver a parsear el `payload`. El runtime debe usar `inbound_event.received_at`.
  - **Render:** cabecera en negrita y pie descartado también en `Buttons`; descripciones de lista como `título: descripción`, o como texto del botón si empiezan por el título (buscaBus); sin vista previa de enlaces; `*negrita*` → `<b>` tras escapar el HTML. La longitud se cuenta en UTF-16 (nota de T-1.2): `render` trunca sin partir caracteres y registra.
  - **Arnés (§17.2):** `core/testing` no puede importar `flowpilot`, así que tiene `RENDER_CHECKS`, que se ejecuta sobre cada respuesta y cada aviso proactivo. El `conftest.py` raíz registra `flowpilot/channels/testing.check_rendering`, que renderiza con los dos adaptadores, comprueba que el resultado es JSON y falla si no cabe en Telegram. Así lo aplican todos los escenarios, también los de `src/packs/*/tests`.
  - **Logs:** nunca la URL (lleva el token), el texto de las excepciones de `httpx` ni la `description` de Telegram (lo comprueba un test).
  - **Fixtures:** siguen los objetos documentados de la Bot API, con datos ficticios (lo explica su `README.md`). Cuando exista el bot de desarrollo (M-3.1) se pueden sustituir por grabaciones.
  - **De la revisión:** los parámetros de una plantilla se sustituyen de una sola pasada (un `{2}` dentro de un parámetro ya no se sustituía otra vez), `*negrita*` sigue la regla de WhatsApp, la cabecera deja sitio al salto de línea y `check_rendering` usa un cliente HTTP que falla si se le llama.
  - **Diseño:** §6.4 y §17.2 actualizados.

### T-3.3 · Webhooks y `/health` ⚠️ 🤖
- **Estado:** done · **Revisión:** aprobada (y aprobación ⚠️ de la persona, 2026-10-21) · **Depende de:** T-3.2, T-2.4, T-2.5 · **Diseño:** §7.1, §13, §15.3
- **Hacer:**
  - Vistas `GET`/`POST /webhooks/whatsapp/<public_id>` y `POST /webhooks/telegram/<public_id>` según §7.1: límite de 64 KB, 404, 401, reglas de `ignored` por estado y `testers.main`, `ON CONFLICT` y encolado.
  - Límite por IP de las peticiones con firma inválida.
  - `/health` con BD y tenants cargados o `degraded`.
  - URLs de `/admin/` montadas aparte, para que Caddy no las exponga (T-7.1).
- **Acepta:** el webhook no hace ninguna llamada externa; un aviso duplicado no se encola dos veces.
- **Tests:** integración de cada rama de §7.1.
- **Notas:**
  - **Vistas** (`flowpilot/channels/views.py`): `whatsapp` (`GET` de verificación y `POST`) y `telegram`. Orden: IP bloqueada (429), tenant (404 si no existe o su canal `main` está deshabilitado), tamaño ≤ 64 KB (400, mirando también `Content-Length`), firma (401 y cuenta para el límite), JSON (400), `offboarded` (200 sin guardar), guardar y encolar (200; un error de BD o de Procrastinate da 503, y un test comprueba que entonces no queda ni el evento ni el trabajo). El JSON se analiza **después** de verificar la firma (§13: autenticidad antes de nada); §7.1 actualizado.
  - **Guardar y encolar** (`flowpilot/runtime/inbound.py`): `store(tenant, items)`, un `tenant_tx` por elemento con `INSERT … ON CONFLICT DO NOTHING RETURNING id`; si se insertó y está `pending`, encola en la misma transacción `process_event` (candado `conv:<h>`) o `apply_status` (sin candado), con solo los ids como argumentos. Los trabajos se encolan por nombre (`PROCESS_EVENT` y `APPLY_STATUS` en `flowpilot/jobs.py`) porque sus tareas llegan en T-3.5; hasta entonces el worker no sabría ejecutarlos.
  - **`h`** (`flowpilot/runtime/locks.py`): `contact_hash` = 16 hex de `sha256(tenant_id, canal, external_id)`; T-3.6 lo reutilizará para `out:<h>`.
  - **`ignored`:** tenant `paused` o `degraded`, o en `onboarding` y ni el `external_id` ni el teléfono del remitente están en `testers.main` (con BSUID, el `external_id` ya no es el teléfono, y `testers.main` admite los dos). Los estados de entrega no dependen de `testers.main`.
  - **Límite por IP** (`flowpilot/channels/ratelimit.py`): en memoria y por proceso; 20 firmas inválidas en 60 s bloquean la IP con 429 durante la ventana; como mucho 10.000 IPs en memoria. La IP es la última entrada de `X-Forwarded-For`. **Para T-7.1:** depende de que Caddy ponga esa cabecera y de que `web` solo sea accesible a través de Caddy.
  - **`/health`** (`flowpilot/ops/views.py`): 200 con `{"status", "database", "tenants": {"loaded", "degraded", "unreadable"}}`, o 503 sin BD. No da nombres, porque es público.
  - **URLs** (`config/urls.py`): `public` (los dos webhooks y `/health`) e `internal` (`/admin/`). T-7.1 enruta en Caddy solo las públicas.
  - **`provider_event_id` ≤ 200:** el adaptador de WhatsApp descarta ids más largos y el de Telegram usa `update_id` (un entero); un id más largo daría 503 y reintentos sin fin.
  - **Pendiente para T-3.5 (contradicción del diseño):** §5.4 dice que los contactos de un tenant `degraded` reciben un texto genérico, pero §7.1 guarda sus eventos como `ignored`, y un evento `ignored` no se procesa. Hay que decidir cómo se envía ese texto.
  - **Tests:** `tests/integration/test_webhooks.py` (cada rama de §7.1, duplicados, lotes, RLS al guardar, estados `ignored`, `GET`, 503, `/health`, URLs y que no haya llamadas externas) y `tests/contract/test_ratelimit.py`. Comprobado en local: `/health` responde en el contenedor `web`.

### T-3.4 · `ctx`: candados, claves idempotentes y calendario por canal 🤖
- **Estado:** done · **Revisión:** aprobada · **Depende de:** T-2.3 · **Diseño:** §8.2, §9.5, §6.5
- **Hacer:**
  - `build_context`.
  - `ctx.lock`: advisory lock de sesión con espera máxima de 10 s, sin transacción abierta y con la clave prefijada por tenant y calendario.
  - `IdemKeys` (`event` y `stable`).
  - El enlace de `ctx.calendar` al `calendar_id` en el canal `main` y al `test_calendar_id` en el canal `test`, a través de una fábrica de `CalendarPort` inyectable (la implementación real llega en T-5.1).
- **Acepta:** en el canal `test` es imposible obtener un `ctx.calendar` ligado a `calendar_id`; sin lock en 10 s se lanza `TransientError`.
- **Tests:** unitarios e integración del lock (dos procesos que compiten) y del enlace de calendario por canal.
- **Notas:**
  - **`flowpilot/runtime/context.py`:** `build_context(tenant, channel, *, contact, state, event_id, calendars)` devuelve el `PackContext`, con `SystemClock` en la zona del tenant, `IdemKeys(event_id)` (`None` en las periódicas) y un `LoggerAdapter` con `tenant`, `channel` y `event_id`.
  - **Calendario por canal:** `bound_calendar_id` lee `calendar_id` y `test_calendar_id` de la config del pack (los nombres de §9.2) y solo si `needs_calendar`. En `test` sin `test_calendar_id`, o con uno igual al real, lanza `CalendarUnavailable` antes de llamar a la fábrica. La fábrica (`CalendarFactory`: `calendar_id → CalendarPort`) es un parámetro; la de por defecto falla hasta T-5.1, que pondrá la real.
  - **`advisory_lock(key)`:** `pg_try_advisory_lock` cada 100 ms durante `LOCK_TIMEOUT_S` (10 s), en la conexión `default` y fuera de cualquier transacción (dentro de una lanza `RuntimeError`); si no lo consigue, `TransientError`. Se libera en `finally` y, si el desbloqueo falla, se cierra la conexión. La clave lleva el tenant y el calendario ligado, pero a la BD solo llega un hash de 64 bits.
  - **`ctx.log`:** el enmascarado de teléfonos de §8.2 lo hará el filtro de logs de §13, que llega en T-6.2.
  - **Tests** (`tests/integration/test_context.py`, transaccionales): contexto de mensaje y de periódica, calendario real en `main` y de pruebas en `test`, imposibilidad del real en `test` (tres casos, sin llamar a la fábrica), prefijo de la clave, espera y `TransientError` con otra sesión de PostgreSQL que tiene el candado, liberación tras un error, dos hilos con sesiones propias que nunca se solapan y rechazo dentro de una transacción.
  - **De la revisión:** se avisa si al liberar el candado ya no estaba retenido; un fallo al cerrar la conexión no oculta la excepción del bloque; el calendario de pruebas se compara con el real sin mayúsculas ni espacios; un tenant `degraded` da `RuntimeError` en lugar de un `assert`; tests del desbloqueo fallido y de que el segundo hilo espera de verdad.
  - **Diseño:** §8.2 ampliado.

### T-3.5 · `process_event` y `apply_status` 🤖
- **Estado:** done · **Revisión:** aprobada · **Depende de:** T-3.3, T-3.4, T-1.4 · **Diseño:** §7.2, §7.3, §6.6, §8.2
- **Hacer:**
  - tx1, pack sin transacción y tx2 según §7.2.
  - *Upsert* de contacto por `(tenant, canal, external_id)`.
  - Límite por contacto, comandos globales y `acknowledge`.
  - Recuperación en el último reintento y ante excepciones no previstas (con Sentry, si está configurado).
  - `apply_actions`: `SendProactive` resuelto según §6.6 y §8.2, sin enviar a contactos con `opt_out` o `unreachable`; `UpdateContact`; y `NotifyOwner` hasta la cola, que se entrega en T-6.1.
  - `apply_status`.
- **Acepta:** reprocesar un evento no duplica respuestas; un evento que no está `pending` termina sin hacer nada; caducidad y versión aplicadas.
- **Tests:** integración (duplicado, reintento entre tx1 y tx2, excepción del pack que lleva al texto de recuperación, límite por contacto, `baja`/`alta`, estado de WhatsApp que actualiza el mensaje).
- **Notas:**
  - (De la revisión de T-2.5) las tareas síncronas que usan el ORM se ejecutan en hilos del worker: cerrar las conexiones viejas (`close_old_connections`) para no pasar de las ~6 de §4.2. `job.is_last_attempt` necesita `pass_context=True`.
  - **Decidido por la persona (2026-10-21):** un tenant `degraded` guarda sus mensajes como `pending` (antes `ignored`) y `process_event` le responde el texto genérico sin llamar al pack. Así se resuelve la contradicción entre §5.4 y §7.1. `inbound.initial_status` cambiado; §5.4 y §7.1 actualizados.
  - **Trabajos** (`flowpilot/jobs.py`): `process_event` (con `pass_context`) y `apply_status`, con `RetryStrategy(max_attempts=3, exponential_wait=2, retry_exceptions={TransientError})`; esperas de 2, 4 y 8 s (§7.5 decía "2 s → 30 s"; corregido). Procrastinate 3.10 no tiene `is_last_attempt`: `is_last_attempt(context)` = `job.attempts >= 3`. Importan `flowpilot.runtime.process` dentro de la función, porque el runtime encola a través de `jobs`. `app` se reexporta explícitamente para mypy. Nuevos nombres: `SEND_MESSAGE` (T-3.6) y `SEND_NOTIFICATION` (T-6.1).
  - **`flowpilot/runtime/process.py`:** `process_event`, `apply_actions` y `apply_status`, como en §7.2 (ampliado con los detalles). tx2 relee el evento con `FOR UPDATE` y no hace nada si ya no está `pending`.
  - **`flowpilot/runtime/outbound.py`:** `create_replies` (`idem_key = reply:<event_id>:<seq>`), `create_proactive` (con la `idem_key` del pack; `None` si ya existía) y `defer_sends` (candado `out:<h>`). `plan_sends` ya se aplica aquí, porque sin él no hay respuestas que no duplicar; T-3.6 añade `send_message`.
  - **`flowpilot/channels/adapters.py`:** `endpoint(tenant, channel)` da adaptador, canal y secretos del canal `main`; el canal `test` llega en T-3.8 (hoy lanza `NotImplementedError`). Las vistas usan sus adaptadores.
  - **Límite por contacto:** `WindowLimiter` (el limitador de T-3.3 generalizado, con `hit`) en memoria del worker: 20 mensajes en 60 s.
  - **Sentry:** `sentry-sdk` aún no está instalado; la excepción se registra con `log.exception` y T-6.2 la enviará.
  - **De la revisión:** el pack recibe una copia del estado (como en el arnés); un aviso a un teléfono no se envía si cualquier contacto con ese teléfono tiene `opt_out` o `unreachable` (antes podía ganar el contacto creado desde el teléfono, sin `last_activity_at`); el límite por contacto va antes que `degraded`, no envía el texto de reinicio y un reintento no cuenta dos veces (`first_attempt`); un tenant `degraded` y un contacto por encima del límite no tocan la conversación; `menu` usa `received_at` del evento. Tests nuevos: sin transacción durante el pack, el texto de reinicio con `baja`, el estado mutado, el aviso a otro canal, la baja por BSUID con el mismo teléfono y el reintento con el límite.
  - **Pendiente para T-3.8:** `endpoint` del canal `test`, y `NotifyOwner` del canal `test` hacia ops (hoy solo se registra, así que nunca llega al dueño).
  - **Pendiente sin tarea:** un `failed` asíncrono de Meta con código de destinatario (131026) no marca el contacto `unreachable`; solo lo hace `Rejected(kind=recipient)` al enviar (T-3.6).
  - **Tests:** los helpers de integración pasan a `tests/integration/helpers.py` y `conftest.py`. `tests/integration/test_process.py` (28): camino feliz, `plan_sends` y orden de los envíos, evento no `pending`, reintento entre tx1 y tx2, duplicado, `TransientError` reintentado y luego recuperación, excepción del pack, caducidad, versión, `menu`, `baja`/`alta`, límite por contacto, tenant `degraded`, `SendProactive` (con `opt_out`, `unreachable` y a un teléfono sin contacto), `NotifyOwner` con y sin dueño, `apply_status` (por `outbound_ref` y por `wamid`, `unknown` → `sent`, `failed`, estado tardío) y el trabajo ejecutado por el worker. Comprobado en local que el worker arranca con los trabajos nuevos.

### T-3.6 · Envío de mensajes 🤖
- **Estado:** done · **Revisión:** aprobada · **Depende de:** T-3.5 · **Diseño:** §7.4, §7.5
- **Hacer:**
  - `plan_sends` conectado a la creación de `outbound_message`.
  - `send_message` con su máquina de estados, reintentos según `SendOutcome` y candado `out:<h>`.
  - Marca `unreachable` ante `Rejected(kind=recipient)` y alerta preparada ante `Rejected(kind=auth)` (el envío de la alerta llega en T-6.1).
- **Acepta:** un `unknown` no se reenvía ni bloquea los mensajes siguientes; `sending` huérfano pasa a `unknown`.
- **Tests:** integración de cada transición de §7.4.
- **Notas:**
  - **`plan_sends` → `outbound_message`:** ya lo hizo T-3.5 (`create_replies` en tx2), porque su criterio "no duplicar respuestas" lo necesitaba.
  - **`send_message`** (`flowpilot/runtime/outbound.py`): máquina de estados de §7.4. `sending` y `attempts` se confirman en una transacción corta antes de llamar al proveedor (con `endpoint` y `render` ya calculados); el envío va sin transacción; el resultado se guarda en otra. `sent`, `unknown` y `failed` no se tocan; un `sending` huérfano pasa a `unknown`.
  - **Resultados:** `Sent` → `sent` con `provider_message_id` y `sent_at`. `Rejected` → `failed` con `last_error = "<tipo>: <motivo>"`; si es `recipient`, el contacto queda `unreachable`; si es `auth`, se registra `ALERT tenant <slug>: channel token rejected` para que T-6.1 envíe la alerta 🔴 (ops_check buscará `last_error` con `auth:`). `RetryLater` → `pending` y `SendRetry`, salvo en el quinto intento, que da `failed`. `Ambiguous` → `unknown`.
  - **Reintentos sin perder el orden:** `SendRetryStrategy` (en `flowpilot/jobs.py`) reintenta solo `SendRetry`, tras `retry_after` o 2, 4, 8 y 16 s. Comprobado en el SQL de Procrastinate 3.10 (`procrastinate_fetch_job_v2` y `procrastinate_retry_job_v2`): el trabajo reintentado conserva su id y vuelve a `todo`, así que los posteriores con el mismo candado `out:<h>` esperan detrás de él.
  - **Destinatario:** el teléfono si se conoce y, si no, el `external_id`. En WhatsApp, con BSUID, el adaptador usa `recipient` (T-3.1).
  - **Casos límite:** un `payload` vaciado por la retención da `failed` sin enviar; un canal `main` sin secretos, `Rejected(other)`.
  - **Tests** (`tests/integration/test_send.py`, con los adaptadores reales y `httpx.MockTransport`): `pending` → `sent` (cuerpo con teléfono y `biz_opaque_callback_data`), `sent`/`unknown`/`failed` no se reenvían, `sending` huérfano → `unknown`, `sending` confirmado antes de la llamada (visto desde otra sesión), `RetryLater` → `pending` con `retry_after`, quinto intento → `failed`, `recipient` → `unreachable`, `auth` → alerta en el log, `Ambiguous` → `unknown`, `payload` vaciado, Telegram al `chat_id`, la estrategia de reintentos y, con el worker, que un `unknown` no bloquea el mensaje siguiente del contacto. `wa_text` y `wa_press` pasan a `tests/integration/helpers.py`.
  - **De la revisión:** `endpoint` y `render` antes de marcar `sending` (un error ahí deja el mensaje `pending`); si un estado de entrega adelanta a la respuesta HTTP, no se pisa; tests de las esperas exactas y, con el worker, de que un `RetryLater` retiene al siguiente mensaje del contacto.
  - **Para T-3.10 (de la revisión; resuelto en T-3.10 con `retry_stalled_jobs`):** comprobar con un test si Procrastinate 3.10 vuelve a encolar los trabajos de un worker caído. Parece que `prune_stalled_workers` solo borra el worker, y que hace falta `get_stalled_jobs` + `retry_job`, que nadie llama. Si es así, un `send_message` en `doing` retendría `out:<h>` y bloquearía al contacto, y §7.7 ("Procrastinate libera el trabajo") no se cumpliría.
  - **Diseño:** §7.4 y §7.5 ampliados.

### T-3.7 · Periódicas y barridos 🤖
- **Estado:** done · **Revisión:** aprobada · **Depende de:** T-3.5 · **Diseño:** §7.6
- **Hacer:** registro de los `Periodic` de los packs, reparto `run_periodic` por tenant activo, descarte por `max_delay_min` y aplicación de acciones en transacción.
- **Acepta:** un instante programado se encola una sola vez; un barrido retrasado se descarta y se registra.
- **Tests:** integración con una periódica del pack de juguete.
- **Notas:**
  - El barrido por calendario (real y de pruebas) se implementa en T-5.6.
  - **Registro** (`flowpilot/jobs.py`): `dispatch_periodic(timestamp, pack, name)` se registra en `app.periodic_registry` una vez por cada `Periodic` de `PACKS`, con `periodic_id = "<pack>:<name>"` y `task_kwargs` con el pack y el nombre. `cron_for(every_min)` traduce a cron en UTC: divisores de 60 minutos (`*/15 * * * *`), divisores de 24 horas (`0 */6 * * *`) o un día (`0 0 * * *`); cualquier otro valor lanza `ValueError` al arrancar. Hoy `PACKS` está vacío, así que el worker dice "No periodic task found" (comprobado).
  - **Reparto** (`flowpilot/runtime/periodic.py`): `dispatch` encola `run_periodic(tenant_id, name, scheduled_at)` en `periodic` para cada tenant activo, con `queueing_lock = periodic:<tenant_id>:<name>`; si ya hay uno pendiente, `AlreadyEnqueued` se registra y se sigue.
  - **Decisión (de T-2.4: si `paused` cuenta):** solo los tenants `active`, no `degraded` y con el canal `main` habilitado (`is_active`). `onboarding` tampoco, para no enviar avisos a clientes reales durante el alta. Sin secretos o ids, tampoco: los avisos fallarían y gastarían sus claves estables, así que se perderían al arreglarlo; se registra un aviso con el slug. El canal `test` queda para T-5.6.
  - **De la revisión:** `run_periodic` reintenta 2 veces con 60 s de espera (`RetryStrategy(max_attempts=2, wait=60)`), para que una caída breve de Calendar pase. `clean_jobs` borra también `procrastinate_periodic_defers`, que referencia a los trabajos. El cron es UTC: `0 0 * * *` son la 1:00 o las 2:00 en Madrid; un pack que necesite una hora local la comprobará en su handler.
  - **`run_periodic`: vuelve a comprobar el tenant y la periódica; descarta y registra si el retraso desde `scheduled_at` pasa de `max_delay_min`; ejecuta el handler sin transacción con `build_context(contact=None, state={}, event_id=None)` y aplica las acciones con `apply_actions` (canal `main`) y `defer_sends` en un `tenant_tx`.
  - **Tests** (`tests/integration/test_periodic.py`): `cron_for`, registro con el pack de juguete, reparto solo a tenants activos, `queueing_lock`, que Procrastinate difiere un instante una sola vez (`defer_periodic_job` dos veces), acciones aplicadas una vez gracias a la clave estable, descarte por retraso con su registro, tenant que deja de estar activo y el recorrido `dispatch_periodic` → `run_periodic` con el worker.

### T-3.8 · Selector del bot de pruebas 🤖
- **Estado:** done · **Revisión:** aprobada · **Depende de:** T-3.5, T-3.6 · **Diseño:** §6.5, §6.6
- **Hacer:**
  - `POST /webhooks/telegram-test`, `test_bot_event` y `route_test_update` (candado `tg:<h>`).
  - Permisos (`TEST_BOT_OPERATORS` y `testers.telegram`), lista paginada, `fp_select:<slug>` y `test_session`.
  - Evento sintético `menu`, `/negocio`, mensaje "🧪 Pruebas · …".
  - Exclusión de negocios `degraded` u `offboarded` y de los que tienen `needs_calendar` pero no `test_calendar_id`.
  - Reglas de aislamiento de la tabla de §6.5: `NotifyOwner` redirigido a ops con "🧪" y nunca envío por WhatsApp ni por el bot del negocio.
- **Acepta:** se cumplen todas las reglas de §6.5.
- **Tests:** integración (usuario sin permiso, selección, cambio con `/negocio`, negocio no disponible, **aislamiento**: el canal `test` nunca usa `calendar_id`, nunca envía por el canal `main` y sus avisos al dueño van a ops).
- **Notas:**
  - **Decidido por la persona (2026-10-21):** columna `notification.audience` (`owner` | `ops`, `db_default='owner'`) en la migración `0003_notification_audience`, que no toca RLS, roles ni borrados. `send_notification` (T-6.1) enviará los `ops` al chat de ops. §11 y §12.1 actualizados.
  - **Ajustes:** `TEST_BOT_TOKEN`, `TEST_BOT_WEBHOOK_SECRET` (si se da, 32 caracteres o más) y `TEST_BOT_OPERATORS` (ids separados por comas o espacios), opcionales y añadidos a `.env.example`. Sin token el bot está apagado; sin secreto, solo su webhook (en local se usa `telegram_poll`, T-3.9).
  - **Canal `test` en el runtime:** `channels/adapters.endpoint(tenant, "test")` devuelve el adaptador de Telegram con `test_bot_secrets()`, sea cual sea el canal `main`. Sin secreto de webhook se rellena uno aleatorio, porque la vista comprueba el ajuste y no ese valor. `runtime/inbound.store` admite el canal; en `test` los eventos van siempre `pending`. `NotifyOwner` del canal `test` → `notification` con `audience = ops` y `🧪 <negocio>: <texto>`, siempre.
  - **Selector** (`flowpilot/channels/test_bot/selector.py`): `store_update` (lo reutilizará T-3.9), `route_test_update`, `is_available` (reutiliza `bound_calendar_id` de T-3.4 para el calendario de pruebas) y `business_list`. Sus mensajes propios no son de ningún tenant: se envían directamente y como mucho una vez, tras marcar el update `done`. El aviso "🧪 Pruebas · …" va antes de crear el `menu` sintético (`provider_event_id = select:<update_id>`, un update de Telegram con el texto `menu`), para llegar antes que el menú. Al dejar de estar disponible el negocio elegido, se borra la `test_session`.
  - **Webhook** (`flowpilot/channels/test_bot/views.py`, `POST /webhooks/telegram-test`): las mismas comprobaciones que el de un negocio y el mismo limitador por IP; 404 sin `TEST_BOT_WEBHOOK_SECRET`. Añadido a las URL públicas.
  - **Trabajo** `route_test_update(event_id)` en `inbound`, candado `tg:<h>` (`runtime/locks.telegram_user_lock`) y los mismos reintentos que `process_event`.
  - **De la revisión:** §7.2 al día con los avisos del canal `test`; el `menu` sintético se construye parseando su propio `payload` (así cumple el contrato de §6.2); quien no tiene permiso recibe el rechazo como mucho 3 veces por hora (`selector.refusals`, en memoria del worker); tests nuevos: negocio con canal `main` de Telegram probado solo por el bot de pruebas (nunca con su `bot_token`), aviso a ops aunque el dueño no tenga chat y con `send_notification` encolado, límite de rechazos y validación de `TEST_BOT_OPERATORS` y `TEST_BOT_WEBHOOK_SECRET`.
  - **Anotado, sin cambiar:** `tg:<h>` y `conv:<h>` son `sha256` sin clave de ids cortos, así que se podrían revertir por fuerza bruta. El diseño lo admite (la tabla de trabajos no la ve nadie de fuera); un HMAC con `SECRET_KEY` sería una mejora futura para los dos.
  - **Tests** (`tests/integration/test_test_bot.py`, 17): webhook (secreto, duplicado, grupo, apagado), trabajo solo con ids y candado con hash, usuario sin permiso, visibilidad para testers y operador, negocios no disponibles (offboarded, degraded, pack con calendario sin `test_calendar_id`; `paused` sí), paginación, elegir y conversar (contacto `test` sin teléfono, `answerCallbackQuery` del selector y del pack), `/negocio`, negocio que deja de estar disponible, elegir uno no visible y **aislamiento**: un negocio de WhatsApp probado por el bot de pruebas nunca llama a Meta, ni siquiera con un aviso proactivo; sus avisos al dueño van a ops; y el pack recibe solo el calendario de pruebas. El helper `wa_tenant` usa ya un `phone_number_id` distinto por slug.

### T-3.9 · Comandos de Telegram 🤖
- **Estado:** done · **Revisión:** aprobada · **Depende de:** T-3.8 · **Diseño:** §6.4, §16.3
- **Hacer:**
  - `manage.py telegram_poll [<slug>]`: *long polling* que entra por el mismo camino que el webhook.
  - `manage.py telegram_set_webhook <slug|test>`.
  - Objetivo `make telegram-poll`.
- **Acepta:** con el bot de desarrollo, un mensaje entra y el pack responde sin túnel.
- **Tests:** unitario de que `telegram_poll` pasa por la misma función de entrada que el webhook.
- **Notas:**
  - **Misma entrada que el webhook:** `channels/views.accept(tenant, body, parse)` es lo que hace el webhook de un negocio tras verificar la firma (descartar `offboarded`, guardar y encolar); el bot de pruebas usa `test_bot.selector.store_update`. `channels/telegram/polling.source(slug)` elige una u otra y `poll` les pasa cada update.
  - **`poll`:** `getUpdates` con 25 s de espera (cliente con 35 s) y solo `message` y `callback_query`. El `offset` avanza siempre; un update que falla se registra (solo el tipo de error) y no bloquea los siguientes; un fallo de `getUpdates` espera 3 s. Un 409 (el bot tiene webhook) para el comando y explica cómo quitarlo; no se borra el webhook solo, para no romper nunca un bot que use el servidor.
  - **Bot API:** `telegram/adapter.call(client, secrets, method, params)` para los métodos de operación; `TelegramApiError` solo lleva estado y `error_code`, nunca la URL (lleva el token).
  - **`telegram_set_webhook <slug|test> [--delete]`:** `setWebhook` con `PUBLIC_URL` (nuevo ajuste opcional, en `.env.example` y §5.3), `secret_token` y `allowed_updates`; `--delete` llama a `deleteWebhook`, útil para M-3.1 si el bot de desarrollo tuviera un webhook. Nunca escribe el token ni el secreto.
  - **`make telegram-poll [SLUG=…]`:** `docker compose exec web python manage.py telegram_poll $(SLUG)`, con el `.env` del contenedor. Comprobado en local que, sin `TEST_BOT_TOKEN`, falla con un mensaje que remite a M-3.1. La prueba con el bot real queda para la validación de F3.
  - **Pendiente de M-3.1:** el criterio "con el bot de desarrollo, un mensaje entra y el pack responde sin túnel" no se ha podido comprobar (no hay bot de desarrollo todavía). Está probado con dobles de la Bot API; la prueba real es la primera casilla de la Validación F3.
  - **README:** sección "Bot de pruebas en local".
  - **De la revisión:** `source(slug)` exige lo mismo que el webhook (`views.main_channel_tenant`, antes `_tenant`: canal habilitado y no ambiguo), así que ni el *polling* ni `telegram_set_webhook` usan el canal real de un negocio que no está activado. Un token inválido (401 o 404) para el *polling* con un mensaje claro. `Source` lleva el `public_id` del negocio para la URL del webhook. §6.4 anota que, en local, un update que falla al guardarse se pierde.
  - **Tests** (`tests/integration/test_telegram_commands.py`): las fuentes son la entrada del webhook (identidad para el bot de pruebas; `views.accept` para un negocio), *polling* del bot de pruebas y del de un negocio guardando como el webhook, avance del `offset` con errores de red, de un update y 502, el 409, los mensajes de error del comando y `telegram_set_webhook` (bot de pruebas, negocio, `--delete` y errores, sin token ni secreto en la salida).

### T-3.10 · Integración de extremo a extremo del runtime 🤖
- **Estado:** done · **Revisión:** aprobada · **Depende de:** T-3.6, T-3.7, T-3.8 · **Diseño:** §7.7, §17.1
- **Hacer:** batería de integración sobre la tabla de fallos de §7.7 con el pack de juguete:
  - Webhook → cola → worker → envío.
  - Orden de dos mensajes de un mismo contacto.
  - Un tenant `degraded` no afecta a otro.
  - El worker cae a mitad de un evento.
  - Base de datos caída (503 en `web`).
- **Acepta:** cada fila de §7.7 que no depende de Calendar tiene su test.
- **Tests:** `tests/integration/`.
- **Notas:**
  - **Worker caído (lo anotado en T-3.6, confirmado):** Procrastinate 3.10 no reintenta solo los trabajos de un worker que muere: `prune_stalled_workers` borra el worker y su trabajo se queda `doing`, con el candado tomado, y bloquea al contacto para siempre. Nueva periódica `retry_stalled_jobs` en `flowpilot/jobs.py` (`*/5 * * * *`, cola `periodic`, `queueing_lock` propio): `get_stalled_jobs()` (trabajos `doing` de workers sin latido desde hace 30 s, o ya borrados) + `retry_job`. Comprobado en local: tras `docker compose restart worker`, su log muestra `retry_stalled_jobs` diferida por el deferrer periódico y terminada con éxito. §7.5 y §7.7 actualizados.
  - **Batería** (`tests/integration/test_end_to_end.py`, con el worker real en las tres colas, concurrencia 4, el pack de juguete y Meta simulada con `MockTransport`). Filas de §7.7 que no dependen de Calendar:
    - webhook → cola → worker → envío;
    - orden de tres mensajes de un contacto que llegan antes de que el worker arranque;
    - aviso duplicado;
    - `web` caída (503) y el reintento del proveedor, sin pérdida;
    - worker que muere a mitad de un `process_event` (trabajo `doing` de un worker sin latido: lo recupera una pasada de `retry_stalled_jobs`, que el test encola, y responde una vez y en orden) y a mitad de un `send_message` (`sending` → `unknown`, sin reenviar, y el siguiente mensaje sale);
    - excepción del pack → texto de recuperación y evento `failed`;
    - envío ambiguo → `unknown`, sin reenviar y sin bloquear el siguiente;
    - token revocado → `failed` con `auth:` y la línea `ALERT` en el log;
    - contacto que no puede recibir → `unreachable`, sin avisos proactivos (las respuestas a lo que escribe siguen saliendo);
    - tenant `degraded` → texto genérico, y el otro tenant responde normal;
    - BD caída de verdad (puerto sin servidor) → 503 en el webhook y en `/health`, y se recupera.
  - **Fuera de esta tarea:** las filas de Calendar (T-5.x) y las de alertas y latido (T-6.x); "dataset inválido" queda cubierto por `degraded` (sin pack `bus` todavía). De "BD caída" se prueba el 503 de `web`; que el worker se reconecta lo da el *pool* de Procrastinate y `close_old_connections` en cada trabajo, sin test propio. "Se reintenta desde tx1" con un tx1 ya hecho lo cubre el test de T-3.5 de reintento entre tx1 y tx2.
  - **Ajustes en tests anteriores:** `test_queue` y `test_periodic` solo miran sus trabajos, porque el worker difiere ahora `retry_stalled_jobs`, y su limpieza borra antes `procrastinate_periodic_defers`.
  - **De la revisión:** el test del worker caído era inestable (1 de cada ~15): con `wait=False`, el worker de un test puede pararse antes de que su deferrer periódico encole `retry_stalled_jobs`. Ahora el test la encola él mismo, como haría la pasada siguiente (que el worker la difiere lo prueban el registro periódico y el arranque real en local), y admite varias pasadas. `retry_stalled_jobs` sigue con los demás trabajos si uno no se puede reintentar. Más aserciones: estado reiniciado tras la excepción del pack, y que el pack sí pidió el aviso al contacto `unreachable`. Tras los cambios, la batería con `test_queue` y `test_periodic` pasa 15 de 15 veces seguidas.

### 👤 M-3.1 · Bot de pruebas de desarrollo
- **Cuándo:** antes de la validación de F3.
- **Qué:**
  1. Crear un bot con @BotFather (p. ej. `flowpilot_dev_bot`) y poner su token en `.env` local como `TEST_BOT_TOKEN`.
  2. Averiguar tu id de Telegram (p. ej. con @userinfobot) y ponerlo en `TEST_BOT_OPERATORS`.
- **Verificar:** `make telegram-poll` arranca sin errores y el bot responde a `/start` con la lista de negocios.

### ✅ Validación F3
- [ ] Prueba de extremo a extremo en local: desde Telegram, `/start` → elegir el negocio de juguete → conversar → las respuestas llegan en orden.
- [x] Integración y aislamiento en verde en CI (run 39754808767 sobre `339b985`: `check` e `image` en verde).

---

## F4 · Pack `bus`

**Resultado verificable:** la consulta de horarios completa funciona en el bot de pruebas con los datos reales de Autocares San Sebastián, y pasan todas las pruebas portadas de buscaBus.

### T-4.1 · Dataset: modelo, validador y carga 🤖
- **Estado:** done · **Revisión:** aprobada · **Depende de:** T-1.3 · **Diseño:** §10.1
- **Hacer:** portar de buscaBus `modelo.py`, `formato.py`, `loader.py`, `calendario.py` y `datos.py` a `packs/bus/`, con la normalización sobre `core/text`.
- **Acepta:** los errores y avisos del validador son idénticos a los del origen.
- **Tests:** portados `test_formato`, `test_loader` y `test_calendario`, con sus fixtures.
- **Notas:**
  - **Decidido por la persona (2026-10-22):** el código portado conserva los identificadores en español de buscaBus y de §10; lo nuevo del pack, en inglés. Anotado en `CLAUDE.md` y §10.
  - **Port:** los cinco módulos, casi tal cual, en `packs/bus/`. Cambios: imports; `normalizar` = `core.text.normalize` sin las palabras vacías (equivalente); anotaciones para `mypy --strict` (`_parse_temporada_rango` devuelve `list[int]`, mal anotado en el origen) y tres avisos de `ruff` (`zip(strict=True)` tras comprobar la longitud, `noqa: B023` justificado). Las referencias `design.md x.y` de los comentarios pasan a `buscaBus/design.md`.
  - **`datos.py`:** sin el estado global (`instalar`/`actual`/`hay_datos`) ni `cargado`: el registro de tenants guarda lo que devuelve `load_data`. `Datos(horarios, menu_origen)`; el `Matcher` se añade en T-4.3. Los mensajes de error nombran `start_menu_towns`.
  - **Idéntico al origen:** prueba diferencial (fuera del repo) de los dos `validar` sobre el dataset real, las fixtures y 400 mutaciones aleatorias (180 con errores): mismos errores y avisos. Única diferencia, el **orden** de algunos avisos `sin datos` y errores `sin ninguna tabla que la cubra`: en buscaBus dependía del orden de un `frozenset` y cambiaba con `PYTHONHASHSEED` (comprobado); aquí va en orden de semana.
  - **Fixtures:** las de los tres tests (sin `horarios_matcher`, `paradas_ancha` ni `paradas_con_pendientes`, que llegan con sus tests). `horarios_real/` es una copia congelada de `buscaBus/horarios/` (commit `3125dba`), para que las pruebas doradas no dependan del dataset vivo del tenant (T-4.6); lo explica su `README.md`.
  - **De la revisión:** docstrings al día. Anotado: `core.text.fold` quita los caracteres de categoría `Mn` y buscaBus los de `combining() != 0`; solo difieren en marcas raras de clase 0 (`\u034f`), que no aparecen en los datos.
  - **Tests** (`src/packs/bus/tests/`): `test_formato`, `test_loader` y `test_calendario` portados (163), con `conftest.py` (`datos_muchas_lineas`, que devuelve los datos en vez de instalarlos) y `helpers.py` (`modelo_de`, `calendario_de`, para los tipos). Nuevo `test_datos` (6): menú por nombre normalizado, pueblo desconocido, sin prefijo ni errata, duplicado, sin viajes y dataset inválido.

### T-4.2 · Motor de consulta 🤖
- **Estado:** done · **Revisión:** aprobada · **Depende de:** T-4.1 · **Diseño:** §10.2
- **Hacer:** portar `query.py`.
- **Acepta:** las pruebas doradas dan los mismos resultados que en buscaBus.
- **Tests:** portado `test_query`.
- **Notas:**
  - **Port:** `packs/bus/query.py` casi tal cual (imports, anotaciones para `mypy --strict` y dos `if` anidados unidos por `ruff`, sin cambiar la lógica).
  - **Único cambio de comportamiento:** `consultar(..., dias_siguiente=45)`. La ventana de búsqueda del siguiente día con salidas era la constante `SIGUIENTE_CON_SERVICIO_DIAS`; ahora la conversación (T-4.4) pasará `next_day_search_days` de la config (§10.4). La constante sigue siendo el valor por defecto.
  - **Mismos resultados que buscaBus:** prueba diferencial (fuera del repo) de los dos motores sobre el dataset real y las cuatro fixtures de motor: todos los pares de localidades, 12 fechas al azar por par (incluidos 25/12, 01/01 y un festivo local) y, en un 30 %, con `ahora`. 53.040 consultas con `Consulta` idéntica, y `destinos_desde` idéntico para cada origen.
  - **Tests:** `test_query` portado (81, sobre `horarios_real/` y las fixtures de T-4.1), con un helper `_info` para los tipos; nuevo `test_ventana_de_siguiente_con_servicio_configurable`.

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
- **Notas:** el parser usa `core.text.fold` (conserva la puntuación), no `normalize`.

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
- **Notas:** añadir los índices de retención anotados en T-2.2.

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
