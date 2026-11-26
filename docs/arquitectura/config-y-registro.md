# Config y registro

La configuración de cada negocio (documento, datasets y secretos de canal) vive en PostgreSQL, versionada, y la plataforma la carga en memoria como un registro. Lee esta página para saber cómo se escribe esa configuración, cómo se valida, cómo la lee cada proceso y cómo se importa o exporta. La decisión está en [ADR-009](adr/ADR-009-config-en-bd.md) y la de la biblioteca de datasets en [ADR-013](adr/ADR-013-biblioteca-de-conjuntos-de-datos.md).

## Qué se guarda y dónde

Nada de la configuración de un negocio está en git ni en la imagen. Cada pieza tiene su tabla (modelos en `apps/backend/src/autobot/tenancy/models.py`):

| Tabla | Contenido |
|---|---|
| `tenant` | Espejo de la identidad (slug, nombre, pack, estado, zona horaria). Solo escribe `fp_owner`. |
| `tenant_document_version` | Una fila por versión del documento del negocio (YAML como JSON). Las versiones nunca se modifican. |
| `tenant_dataset_version` | Una fila por versión de cada dataset del negocio (`files`, `sha256`, procedencia). |
| `tenant_secret` | Secretos del canal, cifrados (ver [Seguridad y secretos](seguridad-y-secretos.md)). |
| `config_revision` | Una sola fila (`id=1`) con un contador que sube con cada escritura. |
| `config_follower` | Una fila por proceso vivo con la revisión que ha cargado (ver [Confirmación](#confirmacion-de-que-un-cambio-esta-aplicado)). Datos de operación: sin `tenant_id` ni RLS. |
| `dataset_library_version` | La biblioteca de datasets, independiente de cualquier negocio. |

Estas tablas llevan `tenant_id` pero sin RLS por diseño: son configuración de la plataforma, no datos de cliente. `fp_app` solo las lee; escribe `fp_owner` (ver [Tenants y RLS](tenants-y-rls.md) y `autobot/db/grants.py`, listas `CONFIG_TABLES` y `SENSITIVE_TABLES`).

## El documento

`TenantDocument` (`apps/backend/src/autobot/tenancy/schema.py`) es la parte común. El bloque `config` lo valida el `config_schema` del pack ([Packs](packs.md)). Campos:

- Identidad: `id` (UUIDv7), `slug`, `name`, `status` (`onboarding`, `active`, `paused`, `offboarded`), `timezone` (nombre IANA), `pack`.
- `channel`: `whatsapp` (ids de Meta, teléfono público, umbral mensual) o `telegram` (usuario del bot), con un `public_id` que forma la URL del webhook.
- `testers.main`: los únicos ids que pueden escribir por el canal principal durante el alta.
- `owner`: tipos de aviso (`notify`) y `summary_monthly` ([Bot de dueños](bot-de-duenos.md)).
- `privacy` (opcional): `policy_url` (`https://…`), el enlace a la política de privacidad que cita la línea de privacidad del bot ([Aviso inicial](packs.md#aviso-inicial)).
- `demo`: marca un negocio de demo. Un demo no tiene canal ni testers y su estado es `active`, `paused` u `offboarded` ([Bot de demo](bot-de-demo.md)). Un negocio que no es demo necesita canal.

El campo `privacy` es opcional para no romper negocios existentes: si falta, el aviso solo nombra al negocio; nunca se inventa un dato. La lista de activación (siguiente sección) exige `privacy.policy_url` antes de abrir el canal real. El antiguo bloque `support` (el contacto de la orden `PERSONA`, retirada en el [ADR-028](adr/ADR-028-aviso-en-una-linea-sin-persona-ni-baja.md)) ya no existe, ni `privacy.controller_name`: si una versión guardada antes los trae, se descartan al cargarla.

Los secretos de canal no van en el documento: `WhatsAppSecrets` (`app_secret`, `access_token`, `verify_token`) o `TelegramSecrets` (`bot_token`, `webhook_secret`).

## El registro en memoria

`apps/backend/src/autobot/tenancy/registry.py` convierte las fuentes (`TenantSource`) en un `Registry` con índices por id, slug, `public_id` y `phone_number_id`. `load_registry` valida cada negocio por separado y **un negocio roto nunca afecta a los demás**:

- Documento ilegible, YAML inválido o parte común inválida: el negocio no se puede identificar y se anota en `Registry.errors`.
- Pack desconocido, `config` inválida, `load_data` que falla o un id repetido: el negocio queda `degraded` (sus contactos reciben un texto genérico). Un id repetido lo marca además `ambiguous`: no se enruta ni se sincroniza.
- Faltan secretos o ids de canal: solo se desactiva su canal principal (`main_disabled`). Un demo siempre tiene el principal desactivado, sin que sea un aviso.

Los mensajes de error llevan rutas y tipos, nunca valores (podrían ser secretos). Los datasets se escriben a un directorio temporal solo durante `Pack.load_data`; las rutas absolutas, con `..` o de contenido que no es texto degradan solo ese negocio.

### Cómo se mantiene al día

Cada proceso (`web`, `web-panel` y cada worker) tiene su propia copia en memoria y un **único hilo refrescador** que la mantiene al día ([ADR-030](adr/ADR-030-registro-siempre-al-dia.md)):

```mermaid
sequenceDiagram
    participant P as panel
    participant DB as PostgreSQL
    participant R as refrescador (cada proceso)
    participant F as config_follower
    P->>DB: guardar versión nueva + config_revision += 1
    loop cada 2 s
        R->>DB: ¿revisión distinta? (+ huellas por negocio)
    end
    R->>DB: leer solo los negocios cambiados
    R->>R: validar y publicar la instantánea nueva, de golpe
    R->>F: revisión cargada (latido cada 15 s)
    P->>F: ¿todos la tienen?
    F-->>P: «Aplicado en N procesos»
```

- **Sondeo propio.** Cada proceso arrancado de verdad comprueba la revisión cada 2 s aunque nadie lo llame, con una conexión fija y sin transacción abierta. Mientras reconstruye, todo sigue con la instantánea anterior; la nueva se publica completa.
- **Recarga incremental.** Cada negocio tiene una **huella** (versión del documento, de cada dataset y de los secretos). Con una revisión nueva solo se leen y se validan los negocios con otra huella; los demás se reutilizan. Un guardado cuesta unos 13 ms de CPU por negocio cambiado y proceso, no 13 ms por cada negocio de la plataforma. Un test de propiedades comprueba que el resultado es igual al de una carga completa.
- **Búsquedas que no se rinden.** Si `tenant_by_id`, `tenant_by_slug` o `tenant_by_public_id` no encuentran un negocio y la revisión cambió, piden una recarga y esperan como mucho 1 s. Nunca reconstruyen en el hilo de una petición de internet.
- **El panel, siempre fresco.** Cada petición a `/api/panel/` hace una comprobación síncrona (`PanelFreshConfigMiddleware`), para que dos procesos de `web-panel` no respondan con datos distintos.
- **Una unidad de trabajo, una versión.** `registry_scope` fija la instantánea durante una petición o un trabajo.
- **Si falla, nada a medias.** Una reconstrucción fallida conserva la instantánea anterior y lo registra (con el ruido limitado a uno por minuto). La primera carga, sin nada que conservar, propaga el error y los webhooks responden 503.

Resultado: un negocio nuevo se encuentra casi al instante; un cambio de uno existente llega a todos los procesos en unos 2 s.

### Confirmación de que un cambio está aplicado

Cada refrescador escribe en `config_follower` una fila por proceso (`service`, `host`, `pid`, `revision` cargada, `seen_at` y `last_error_at`), como mucho cada 15 s salvo que cambie algo. Una fila es **viva** si se vio en los últimos 35 s y está **atrasada** si su revisión es distinta de la de la base. Esa tabla alimenta tres cosas:

- La tarjeta «Configuración cargada» del panel (`GET /api/panel/system/config`).
- El aviso tras guardar: «Aplicado en N procesos» o cuál sigue con la versión anterior. El cambio ya está guardado; es solo información.
- La alerta `config_stale`: un proceso vivo atrasado, o con errores de recarga, durante más de un minuto.

Al pararse, un proceso borra su fila; si muere sin avisar, deja de contar como vivo a los 35 s y `ops_check` la borra al día.

## Escribir configuración: `tenancy/store/`

`autobot.tenancy.store` es el **único camino** para escribir configuración: serializado, validado y auditado. Es un paquete (`apps/backend/src/autobot/tenancy/store/`) con una fachada en `__init__.py`:

| Módulo | Responsabilidad |
|---|---|
| `documents.py` | `new_document`, `create_tenant`, `publish`, `rollback`, `change_status`. |
| `datasets.py` | `import_dataset`, `write_dataset` (copias, nunca referencias). |
| `channel_secrets.py` | `set_secrets`: valida, cifra y sustituye los secretos. |
| `imports.py` | `import_source`: importa documento, datasets y secretos juntos. |
| `validate.py` | `lock`, `current_sources`, `validate_candidate`. |
| `revision.py` | `write_document` y `bump` del contador de revisión. |
| `errors.py` | `StoreError` y la lista `IDENTITY`. |

Cada escritura sigue el mismo patrón, en una transacción con la conexión `owner`:

```mermaid
flowchart LR
    L["lock()<br/>SELECT FOR UPDATE<br/>config_revision"] --> V{"validate_candidate<br/>¿el registro quedaría sano?"}
    V -->|no| X["error con el motivo real<br/>(nada se escribe)"]
    V -->|sí| W["versión nueva + espejo tenant<br/>+ revisión += 1 + auditoría"]
    W --> C["COMMIT"]
```

1. `validate.lock()` toma la fila de `config_revision` con `SELECT FOR UPDATE`: las escrituras se serializan.
2. Se construye un candidato y `validate_candidate` carga el registro **como quedaría** con él; si el candidato sale degradado, ambiguo o rechazado, la escritura falla con el motivo real.
3. Se crea una versión nueva (las anteriores no se tocan), se actualiza el espejo `tenant`, se incrementa la revisión y se registra una auditoría, todo en la misma transacción.

Otras reglas de validación: un conflicto de versión (`base_version`) se rechaza, y dos negocios no pueden compartir `config.calendar_id` (los dados de baja no cuentan). Un pack que necesita datasets (`load_data`) exige elegir uno explícitamente al crear el negocio.

### Campos protegidos

Seis campos forman la identidad (`IDENTITY` en `store/errors.py`) y ni publicar ni importar pueden cambiarlos: `id`, `slug`, `pack`, `status`, `channel.type` y `channel.public_id`. El estado solo cambia con `change_status`, que aplica las transiciones `activate`, `pause`, `resume` y `offboard`. Pausar y dar de baja no revalidan la configuración, para poder sacar de servicio un negocio degradado.

### Volver atrás

`rollback` no restaura el documento entero: crea una versión nueva con solo el contenido editable (`name`, `timezone`, `config`; `CONTENT_KEYS`) y conserva lo vigente de la identidad, el estado, el canal completo, los testers, el dueño y la demo. Así, volver a una versión anterior a conectar WhatsApp no desconecta el número.

### Activar un negocio

```mermaid
stateDiagram-v2
    [*] --> onboarding: create_tenant
    onboarding --> active: activate (checklist sin bloqueos)
    active --> paused: pause
    paused --> active: resume
    onboarding --> offboarded: offboard
    active --> offboarded: offboard
    paused --> offboarded: offboard
```

`activate` solo se permite desde `onboarding` y exige que `activation.checklist(slug)` no tenga bloqueos (`apps/backend/src/autobot/tenancy/activation.py`). La lista comprueba: documento válido y sin degradación, ids de canal completos, secretos legibles, salud del canal sin problemas críticos, plantillas de WhatsApp aprobadas, enlace a la política de privacidad (`privacy.policy_url`) y que algún tester haya escrito por el canal principal. «Dueño enlazado» aparece pero no bloquea. La salud se fuerza **fuera** de la transacción de escritura (nunca hay una transacción abierta durante llamadas a Meta, Google o Telegram) y la lectura del panel (`refresh=False`) solo mira la caché. La lista alimenta los pasos del alta de la pestaña «Configuración» ([ADR-027](adr/ADR-027-alta-y-configuracion-en-una-pestana.md)).

Los estados de salud que ve el operador (`ok`, `notice`, `warning`, `critical`, `unknown`) los centraliza `autobot/ops/status.py` (`tenant_status`); ver [Estados de negocio](../referencia/estados-de-negocio.md).

## Biblioteca de datasets

Un dataset es un conjunto de ficheros de texto que un pack necesita además de su `config` (hoy, el `timetable` de `bus`). La biblioteca (`apps/backend/src/autobot/tenancy/dataset_library.py`, ADR-013) guarda datasets con nombre y versión **independientes de cualquier negocio**:

- Se sube por terminal con `manage.py dataset_library push <pack> <dataset> <nombre> <directorio> --comment ...`; también hay `pull`, `list` y `current-sha` y `push --dry-run`.
- `push` valida el contenido con el `dataset_summary` del propio pack, toma un candado consultivo por entrada y crea una versión nueva, salvo que el contenido sea idéntico. `--base-sha` evita pisar una subida ajena.
- Un negocio **copia** la entrada elegida a su propio `tenant_dataset_version` (al darlo de alta o con «Aplicar» desde su ficha); nunca queda una referencia viva. La copia guarda su procedencia (`source_name`, `source_version`, `source_sha`) solo como información.
- La biblioteca no la lee el registro: `fp_app` no tiene acceso a `dataset_library_version`; solo lo usan `tenancy.store` y los servicios del panel, como `fp_owner`.
- `seed_demos` sube el dataset de la plantilla como una entrada más, llamada `demo` ([Bot de demo](bot-de-demo.md)).

Cómo se suben horarios de `bus` en la práctica: [Horarios de bus](../procedimientos/horarios-bus.md).

## Importar y exportar: `tenant_config`

`manage.py tenant_config` (`apps/backend/src/autobot/management/commands/tenant_config.py`) trabaja con directorios portables, o con un `tar.gz` por `-` (stdin/stdout); la lógica está en `apps/backend/src/autobot/tenancy/archive.py`.

- `export <slug> <destino>`: escribe `document.yaml` y `datasets/<nombre>/...`. La procedencia de cada dataset viaja como `datasets/<nombre>.origin.json` y se conserva al importar. **No exporta secretos.**
- `import <origen> [--secrets fichero] [--comment ...]`: valida documento y datasets juntos antes de publicar. Si el slug no existe lo crea; si existe, publica una versión nueva (sin poder cambiar los campos protegidos). Los secretos solo se importan si se pasan en un fichero (`--secrets`) o hay un `secrets.yaml` en el directorio, y sustituyen a los anteriores completos. Importar el mismo contenido no crea versiones ni auditorías.
- `validate --all`: carga el registro con todo lo que hay en la base y falla si algún negocio está degradado o es ilegible.

`source_from_dir` exige `document.yaml`; el nombre de la carpeta no condiciona el slug del documento. Los enlaces simbólicos en datasets se rechazan.

`seed_demos` y la creación desde el panel usan las mismas funciones del `store`, así que pasan por la misma validación.

## Dónde está el código

- `apps/backend/src/autobot/tenancy/`: `registry.py`, `schema.py`, `activation.py`, `archive.py`, `dataset_library.py`, `crypto.py`, `models.py`, `store/`.
- `apps/backend/src/autobot/management/commands/`: `tenant_config.py`, `dataset_library.py`, `seed_demos.py`.
- `apps/backend/src/autobot/ops/status.py`: salud agregada por negocio.

## Relacionado

- [Tenants y RLS](tenants-y-rls.md): qué tablas llevan RLS y cuáles no.
- [Seguridad y secretos](seguridad-y-secretos.md): cifrado de `tenant_secret`.
- [Packs](packs.md): `config_schema`, `load_data` y `dataset_summary`.
- [Alta y baja de un negocio](../procedimientos/alta-baja-negocio.md) y [Comandos](../referencia/comandos.md).
