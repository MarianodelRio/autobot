# Añadir un pack

Guía paso a paso para crear un pack nuevo (el código de un tipo de negocio) y dejarlo enchufado a la plataforma. Léela cuando vayas a añadir uno; para entender qué es un pack y por qué la plataforma no sabe nada de citas ni de autobuses, empieza por [Packs](../arquitectura/packs.md).

!!! note "Lo que NO tocas"
    Un pack no importa Django, `integrations`, `autobot` ni otro pack, y no sabe qué canal usa. Si necesitas algo de eso, lo pide al runtime a través del contrato (`PackContext`, acciones). Si lo usan dos packs, sube a `core/`; si solo lo usa uno, se queda en el pack.

Como ejemplo mínimo y completo del contrato, mira el pack de pruebas `apps/backend/tests/fixtures/toy_pack/pack.py`. Los packs reales (`salon`, `bus`) muestran el resto.

## 1. Carpeta y contrato

Crea `apps/backend/src/packs/<nombre>/` con un `__init__.py` y un `pack.py` que declare una instancia de `Pack` llamada `pack` (`apps/backend/src/core/pack.py`, `Pack`). Los campos obligatorios son:

| Campo | Qué es |
|---|---|
| `name` | Nombre del pack; es la clave del registro y el valor de `pack:` en el documento del negocio. |
| `config_schema` | Modelo Pydantic de la configuración (paso 3). |
| `state_version` | Versión del estado de conversación. Súbela cuando cambie su forma. |
| `handle_message` | `Callable[[PackContext, IncomingMessage], PackResult]`: el corazón del pack. |

El resto es opcional y se explica en los pasos siguientes: `periodic`, `health`, `summary`, `templates`, `owner_notices`, `template`, `template_blank`, `needs_calendar`, `load_data`, `dataset_summary` y `conversation_timeout_min`.

`handle_message` recibe el contexto (negocio, configuración validada, contacto, estado de la conversación, reloj, claves de idempotencia) y el mensaje entrante. Devuelve un `PackResult` con tres cosas:

- `replies`: lo que ve la persona, construido con los helpers de `core/ui.py` (`buttons_msg`, `list_msg`, `section`, `row`, `paginate`).
- `state`: el estado nuevo. `None` lo deja como está y `{}` lo reinicia.
- `actions`: efectos para el runtime (`NotifyOwner`, `RecordMetric`, `SendProactive`, `UpdateContact`).

Reglas que el pack debe respetar (están en `CLAUDE.md`):

- **Nunca adivinar en silencio:** o hay una respuesta única, o se pregunta.
- **Idempotencia:** toda acción lleva una clave de `ctx.idem` (`event(...)` por evento, `stable(...)` para lo periódico). Reintentar el mismo mensaje no puede duplicar efectos.
- **Límites comunes de canal:** botones ≤ 3, filas ≤ 10, textos ≤ 4 096, ids ≤ 64 bytes. El escenario lo comprueba.
- **Errores:** `TransientError` se reintenta; `PermanentError` no.
- **Sin transacción abierta** durante llamadas externas, como a Google Calendar. El runtime ya lo respeta; el pack no abre transacciones.

## 2. Registrarlo

Añádelo a `apps/backend/src/packs/registry.py` (`PACKS`), que es el único módulo que importa packs:

```python
from packs.bus import pack as bus
from packs.mipack import pack as mipack
from packs.salon import pack as salon

PACKS: dict[str, Pack] = {p.name: p for p in (bus.pack, mipack.pack, salon.pack)}
```

Es la única forma en que la plataforma llega a un pack. La regla de `import-linter` (paso 9) impide cualquier otra. Los tests registran el `toy_pack` por su cuenta, sin tocar `PACKS`.

## 3. Configuración con Pydantic

Define el modelo en `packs/<nombre>/config.py`. Es la fuente de verdad de lo que un negocio puede configurar:

- Hereda de `BaseModel` con `ConfigDict(extra="forbid")`, como `BusConfig` y `SalonConfig`: un campo desconocido es un error, no se ignora.
- Valida con `Field(...)`, `field_validator` y `model_validator`. Los errores salen en español, porque los lee quien opera el panel.
- Pon `title=` y `description=` en español en cada campo: el panel dibuja su formulario con ellos.

Ese mismo modelo sirve en dos sitios, sin código extra:

- **Validación:** `tenant_config validate` e `import`, y el registro al cargar cada negocio (`pack.config_schema.model_validate(...)`).
- **Formulario del panel:** `document_schema()` (`apps/backend/src/autobot/panel/services/forms.py`) genera el JSON Schema del documento del negocio y sustituye `config` por `pack.config_schema.model_json_schema()`. Los campos con título y descripción salen ya como un formulario usable.

Los campos con nombre `info_text` o los textos de un submodelo `texts` se dibujan como área de texto. Si un campo necesita un editor propio, hay que añadir un componente en el panel y registrarlo en `CUSTOM_FIELDS`, en `forms.py`; hoy solo lo hace `salon` (horarios y servicios). Empieza sin ello.

La pestaña Configuración agrupa los campos en secciones plegables ([ADR-027](../arquitectura/adr/ADR-027-alta-y-configuracion-en-una-pestana.md)). Las de un pack se declaran en `PACK_SECTIONS` (`forms.py`), con rutas como `config.services`; un campo que dependa de una casilla se añade a `SHOW_IF`. No es obligatorio: los campos de `config` que ninguna sección nombra salen en «Otros ajustes». Cada sección lleva en `docs` la página (y el ancla) de la documentación que la explica, normalmente la referencia del pack (`referencia/packs/<pack>.md#configuracion`); el panel la enlaza como «Más información». Y cada campo de `config` lleva un `description` corto en su `Field`, que el panel muestra debajo del campo. `test_forms.py` falla si falta alguno de los dos o si el ancla no existe. Si el pack añade pasos de alta, cada `SetupStepOut` indica su `section`.

Si el pack necesita un dato propio que se sube aparte de la configuración (como los horarios de `bus`), declara `load_data` y `dataset_summary`. El flujo está en [ADR-013](../arquitectura/adr/ADR-013-biblioteca-de-conjuntos-de-datos.md).

## 4. Plantilla y negocio de demo

Cada pack incluye `packs/<nombre>/template/document.yaml` (y `datasets/` si lleva datos). De ahí sale su negocio de demo: `manage.py seed_demos` lo siembra en PostgreSQL la primera vez y conserva los cambios posteriores. Mira `packs/bus/template/document.yaml` y `packs/salon/template/document.yaml`.

```yaml
id: <UUID v7 nuevo>       # los tests exigen la versión 7
slug: demo-<nombre>
name: Negocio de Prueba
timezone: Europe/Madrid
pack: <nombre>
config: { ... }           # valida contra tu config_schema
status: active
demo:
  description: Una frase de hasta 72 caracteres para el selector
```

En `Pack`, apunta a la carpeta con `template=Path(__file__).parent / "template"` y lista en `template_blank` los campos de `config` que se vacían cuando el panel usa la plantilla para crear un negocio real, como el nombre y el teléfono. Los datos de demo no deben ser de un cliente real.

Un negocio de demo no tiene canal ni `testers.main`; el bot de demo ([Bot de demo](../arquitectura/bot-de-demo.md)) lo ofrece en su selector sin más trabajo. El test `tests/repo/test_tenants.py` recorre `PACKS` y comprueba que la plantilla valida, que es demo, que el `id` es UUIDv7 y que `template_blank` son campos reales.

!!! warning "Dos sitios con lógica de pack concreta"
    `seed_demos` (`apps/backend/src/autobot/management/commands/seed_demos.py`) sustituye el `calendar_id` de la plantilla de `salon` por `DEMO_SALON_CALENDAR_ID`. Si tu pack tiene un valor que no puede ir en git (un id externo, por ejemplo), hoy hay que añadir un caso parecido ahí y documentar la variable. Es un límite actual de la plataforma, no un patrón a repetir si puedes evitarlo.

Para probarlo sin canal ni BD: `make chat PACK=<nombre>`. Si el pack necesita calendario, rellena `test_calendar` con un doble en memoria; lo usa solo esta herramienta.

## 5. Escenario de conversación (obligatorio)

Crea `apps/backend/tests/packs/<nombre>/` con el escenario del pack y mantenlo actualizado con cada cambio del flujo. Se escribe con `Conversation`, parametrizado por los dos canales. Cubre al menos el camino feliz, cada rama de error, los mensajes no soportados y el reintento (`replay()`). Cómo se escribe y qué comprueba, en [Tests](tests.md#escenarios-de-conversacion).

El renderizado con ambos adaptadores y los límites comunes se comprueban solos al usar `Conversation`; no hace falta código extra.

## 6. Ganchos opcionales

| Gancho | Para qué | Quién lo ejecuta |
|---|---|---|
| `periodic` | Lista de `Periodic(name, every_min, handler, max_delay_min)`: tareas del pack con calendario propio (`salon` barre su calendario cada 15 min). El handler recibe un contexto sin contacto y devuelve acciones. | Procrastinate programa un periódico por pack y nombre (`runtime/jobs.py`). |
| `health` | `Callable[[PackContext], list[HealthIssue]]`: qué falla en el negocio (`salon` comprueba el acceso al calendario). | El comprobador de salud de la plataforma; se ve en el panel y en las alertas. |
| `summary` | `SummaryHook`: líneas (`SummaryLine`) que el pack aporta al resumen mensual del dueño. | `runtime/summary.py`, sin transacción abierta. |
| `templates` | `TemplateSpec`: plantillas de WhatsApp para mensajes proactivos (`name`, `language`, `text` y botones). El `text` debe coincidir con la plantilla aprobada en Meta. | El panel y la comprobación de salud verifican que estén aprobadas. |
| `owner_notices` | `OwnerNotice(kind, label)`: tipos de `NotifyOwner` que el pack puede emitir; el panel los muestra como casillas en `owner.notify`. | El panel y el bot de dueños. |

Prueba cada uno en el escenario: `chat.run_periodic(nombre)` ejecuta un periódico y `chat.notifications`, `chat.metrics` y `chat.proactive` devuelven las acciones.

## 7. import-linter

Ejecuta, desde `apps/backend`, `PYTHONPATH=src uv run lint-imports` (lo hace `make check`). Los contratos de `pyproject.toml` garantizan que:

- `packs` no importa `integrations`, `autobot`, `config` ni `django`.
- Solo `packs.registry` importa un pack.

Un pack que rompa una de las dos reglas falla en CI. Para entender el porqué, mira [ADR-001](../arquitectura/adr/ADR-001-monolito-modular.md) y [ADR-003](../arquitectura/adr/ADR-003-packs.md).

## 8. Documentación y navegación

Es tarea de quien añade el pack, y se hace en el mismo commit:

1. Crea `docs/referencia/packs/<nombre>.md`: qué hace, campos de `config`, flujo de conversación, plantillas, alertas y datasets. Usa `salon.md` y `bus.md` como modelo.
2. Añade la página a `nav` en `mkdocs.yml`, bajo Referencia, junto a las de los otros packs.
3. Si el pack introduce comandos, variables de entorno o decisiones nuevas, actualiza `docs/referencia/comandos.md` o `variables-entorno.md` (los tests de `tests/repo/` lo exigen) y registra un ADR si cambia la arquitectura.
4. Comprueba la documentación con `make docs-check`.

## Lista de comprobación

- [ ] `packs/<nombre>/pack.py` con `pack`, `config.py`, y la conversación.
- [ ] Alta en `packs/registry.py`.
- [ ] `template/document.yaml` válido, y `template_blank`.
- [ ] Escenario en `tests/packs/<nombre>/` con los dos canales.
- [ ] Línea de privacidad: la añade la plataforma debajo del menú: el pack devuelve `PackResult(menu=True)` cuando su respuesta es el menú principal ([Packs](../arquitectura/packs.md#aviso-inicial)). El pack muestra el contacto del negocio en su menú o en «ℹ️ Información» (la salida a una persona) y añade su propio descargo si lo necesita (como `schedule_disclaimer` en `bus`).
- [ ] `make check` en verde (incluye `lint-imports` y `tests/repo/`).
- [ ] `docs/referencia/packs/<nombre>.md` y entrada en `mkdocs.yml`.

## Dónde está el código

- `apps/backend/src/core/pack.py`: `Pack`, `PackContext`, `PackResult`, `Periodic`, `HealthIssue`, `SummaryLine`, `OwnerNotice`.
- `apps/backend/src/core/ui.py`, `core/replies.py`, `core/actions.py`, `core/idem.py`: lo que usa un pack para responder.
- `apps/backend/src/packs/registry.py`: `PACKS`.
- `apps/backend/src/packs/salon/` y `packs/bus/`: packs reales.
- `apps/backend/tests/fixtures/toy_pack/`: pack mínimo de pruebas.

## Relacionado

- [Packs](../arquitectura/packs.md) y [Config y registro](../arquitectura/config-y-registro.md).
- [Tests](tests.md) y [Bot de demo](../arquitectura/bot-de-demo.md).
- Referencia de los packs existentes: [salon](../referencia/packs/salon.md) y [bus](../referencia/packs/bus.md).
