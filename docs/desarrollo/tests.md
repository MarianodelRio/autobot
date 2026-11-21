# Tests

Cómo está organizada la batería de tests del backend y del panel, cómo ejecutar uno solo y cómo se escribe el **escenario de conversación** que exige cada pack. Léelo antes de añadir o cambiar un test, o un flujo de conversación.

## Carpetas

Los tests viven en `apps/backend/tests/` y se reparten por lo que prueban, no por si son unitarios o de integración ([ADR-010](../arquitectura/adr/ADR-010-estructura-del-repo.md)).

| Carpeta | Qué prueba |
|---|---|
| `core/` | `core/`: contrato de packs, conversación, límites, utilidades. Sin BD. |
| `packs/<pack>/` | Cada pack, incluido su escenario de conversación (`bus/test_escenarios.py`; en `salon`, `test_booking.py` y los de gestión). |
| `platform/{channels,runtime,tenancy,owner,ops,panel}/` | `autobot/`, agrupado por dominio. Casi todos usan BD. |
| `contract/` | El contrato con cada proveedor externo simulado: WhatsApp, Telegram y Google Calendar. |
| `isolation/` | El test genérico de RLS: ver [Migraciones y RLS](migraciones-y-rls.md). |
| `tools/` | Los scripts de operación de `apps/backend/src/tools/` y `deploy/scripts/`. |
| `repo/` | Coherencia del repositorio (ver más abajo). |
| `fixtures/` | Payloads de WhatsApp y Telegram, y el `toy_pack`. |
| `helpers/` | Utilidades compartidas (`integration.py`). |

## Marcadores

`pyproject.toml` ejecuta pytest con `--strict-markers`: un marcador no declarado falla.

- `db`: el test necesita PostgreSQL. `conftest.py` lo añade solo a todo test que pide `django_db`; no se marca a mano.
- `contract`: contrato con un proveedor simulado. Se añade solo a todo lo que está bajo `tests/contract/`.

Los tests con BD usan `pytest.mark.django_db(transaction=True, databases=["default", "owner"])` cuando los datos deben confirmarse de verdad, como en producción.

## Ejecutar tests

```bash
make test-fast    # pytest -m "not db": sin base de datos
make test         # toda la suite; necesita la BD local (make local)
make check        # lint, tipos, import-linter y toda la suite
```

Para un solo fichero o un solo test, desde `apps/backend`:

```bash
cd apps/backend
DJANGO_SETTINGS_MODULE=config.settings_dev uv run pytest tests/packs/bus/test_escenarios.py
DJANGO_SETTINGS_MODULE=config.settings_dev uv run pytest tests/packs/bus/test_escenarios.py::test_otro_dia
DJANGO_SETTINGS_MODULE=config.settings_dev uv run pytest -k "otro_dia and telegram" -m "not db"
```

Los tests con BD usan `test_<nombre>`, que crea `init-roles.sh` junto con los roles. Aplican las migraciones como `fp_owner`, ejecutan `apply_grants` y consultan como `fp_app`, es decir, bajo RLS.

## Qué hacen `conftest.py`, `helpers/` y `toy_pack`

`apps/backend/tests/conftest.py`:

- `django_db_setup` apunta todos los alias a la base de pruebas, migra como `fp_owner` y reaplica los permisos.
- `_flush_as_owner` hace que el vaciado entre tests transaccionales lo ejecute `fp_owner`, porque `fp_app` no puede `TRUNCATE`.
- `_block_external_network` hace fallar cualquier conexión que no sea a localhost: ningún test llama a Meta, Google o Telegram.
- `_render_scenarios_with_both_adapters` registra el renderizado con los dos adaptadores de canal en los escenarios (ver abajo).
- `reset_channel_limits` reinicia los límites en memoria de los bots de demo y de dueños.
- `tenants` siembra configuración versionada y secretos cifrados; `clean_jobs` limpia las tablas de Procrastinate, que el vaciado no toca.

`tests/helpers/integration.py` reúne lo común de los tests de integración del runtime: negocios de WhatsApp, Telegram y demo, envío de webhooks con credenciales válidas (`wa_text`, `wa_press`, `post_wa`, `post_tg`), `drain` para procesar la cola, y los proveedores simulados con `httpx.MockTransport`.

`tests/fixtures/toy_pack/` es un pack mínimo que no está en `packs.registry`. Ejercita el arnés de conversación y el runtime sin depender de `salon` ni de `bus`; sirve también de ejemplo mínimo en [Añadir un pack](anadir-un-pack.md).

## Escenarios de conversación

Cada pack debe tener su escenario de conversación, y cada cambio de su flujo lo actualiza (`CLAUDE.md`). El arnés está en `apps/backend/src/core/testing/harness.py` (`Conversation`). Reproduce cada turno como `process_event`, pero sin base de datos ni red:

1. Estado efectivo y comandos globales (`menu`, `alta`, `baja`).
2. El pack (`handle_message`).
3. `plan_sends` en modo estricto, que **falla el test** si una respuesta excede los límites comunes.
4. Las acciones que devuelve el pack.

Respuestas y estado pasan por JSON, como pasarían por `outbound_message.payload` y `conversation.state`.

### Cómo se escribe

Se crea una `Conversation` con el pack, su config y sus datos, y se envían textos (`send`) o pulsaciones (`press`). Cada llamada devuelve un `Turn` con `.expect(...)` encadenable:

```python
@pytest.fixture(params=["whatsapp", "telegram"])
def canal(request: pytest.FixtureRequest) -> ChannelType:
    return request.param


def charla(canal: ChannelType, datos: Datos | None = None, now: str = MIERCOLES) -> Conversation:
    return Conversation(pack, config=CONFIG, data=datos or datos_demo(), channel=canal, now=now)


def test_otro_dia(canal: ChannelType) -> None:
    chat = charla(canal)
    hasta_dias(chat)
    chat.press("dia:2026-09-24")
    chat.press("otro_dia").expect(list_includes="Mañana · jue 24/09")
    chat.press("dia:2026-09-25").expect(text_contains="📅 Viernes 25/09", buttons=RESULTADO)
```

Ejemplo de `tests/packs/bus/test_escenarios.py`. Puntos a tener en cuenta:

- **Se parametriza por canal** (`whatsapp` y `telegram`): el mismo escenario corre dos veces.
- `press(id)` exige que el id se haya ofrecido antes en una respuesta; pulsar un botón inexistente falla.
- `expect` admite `text`, `text_contains`, `buttons`, `rows`, `list_includes` y `nothing`. Para lo demás, se inspeccionan `turn.replies` y `chat.state`.
- `chat.now(...)` mueve el reloj. `chat.replay()` reprocesa el último mensaje con el mismo id de evento, como un reintento tras una caída.
- Las acciones del pack se leen en `chat.notifications`, `chat.metrics`, `chat.proactive` y `chat.actions`. `chat.run_periodic(nombre)` ejecuta un `Periodic`.
- Si el pack necesita calendario, se pasa `calendar=` con un doble en memoria (`salon` usa `FakeCalendar`, en `packs/salon/testing.py`).
- `attempts=N` simula los reintentos de un `TransientError` antes del texto de recuperación.

`salon` define la fixture en `tests/packs/salon/conftest.py` y sus escenarios la usan sin más:

```python
def test_full_booking(salon: Conversation) -> None:
    choose(salon)
    salon.send("Lucía García").expect(text_contains="¡Tu cita está confirmada!")
    assert salon.notifications[0].kind == "booking_created"
```

### Cómo comprueban los límites de canal

Hay dos capas, y las dos están en el arnés:

- **Límites comunes** (`core/limits.py`): botones ≤ 3, filas de lista ≤ 10, textos ≤ 4 096, ids ≤ 64 bytes, y los límites de títulos y cabeceras. Los aplica `plan_sends(strict=True)`; una respuesta fuera de límites lanza `LimitError`.
- **Renderizado real**: el `conftest.py` raíz añade `autobot.channels.testing.check_rendering` a `core.testing.harness.RENDER_CHECKS`. Cada respuesta y cada mensaje proactivo se renderizan con los adaptadores de WhatsApp y Telegram y se serializan a JSON. `core` no puede importar los adaptadores, y por eso el registro se hace desde el `conftest.py`.

Quien escribe un escenario no comprueba los límites a mano: salen gratis al usar `Conversation`. Un test del propio mecanismo está en `tests/fixtures/toy_pack/test_harness.py` (`test_reply_out_of_limits_fails_the_test`).

## Fixtures de payloads de canal

`tests/fixtures/whatsapp/` y `tests/fixtures/telegram/` guardan cuerpos de webhook (`text.json`, `button_reply.json`, `message.json`, `callback_query.json`…) y respuestas de los proveedores (`send_ok.json`, `error_429.json`, `graph_*.json`). Los usan los tests de `contract/` y los de integración mediante `fixture("whatsapp/text.json")` de `tests/helpers/integration.py`, que cambian el id y el texto de cada mensaje con `wa_text` o `wa_press`.

Hoy **no son grabaciones reales**: siguen la forma de los ejemplos oficiales de Meta y de la Bot API, con ids, teléfonos y nombres ficticios. El `README.md` de cada carpeta indica su procedencia. Para sustituirlas por reales:

- **Telegram:** con un bot de desarrollo sin webhook, `make telegram-poll SLUG=<slug>` recibe los updates; guarda los que interesen.
- **WhatsApp:** cuando haya un número de pruebas, copia los cuerpos recibidos por el webhook.

En ambos casos hay que anonimizar teléfonos, BSUID, ids de usuario y nombres antes de guardar nada en git. Un fixture con datos reales es un dato personal en el repositorio.

## Coherencia del repo (`tests/repo/`)

Tests que comprueban que el repositorio, la documentación y el código no se separan. No necesitan servicios externos y cuentan en CI:

- `test_docs.py`: todo objetivo de `make` con `##` está en `docs/referencia/comandos.md`; todo comando de `manage.py` también; toda variable de `.env.example` está en `docs/referencia/variables-entorno.md`.
- `test_settings.py`: la validación de `config.settings` (producción exige todas las variables, `ENVIRONMENT` desconocido falla cerrado, etc.).
- `test_tenants.py`: la plantilla de cada pack de `packs.registry` valida, incluido su demo y los campos de `template_blank`.

Si añades un objetivo de `make`, un comando o una variable y no lo documentas, estos tests fallan.

## Tests del panel

El frontend usa Vitest con jsdom, `@testing-library/react` y `@testing-library/user-event`. Los tests viven junto al código (`*.test.ts` y `*.test.tsx`). Se ejecutan con `pnpm -C apps/panel test`, o con `make panel-check` junto a Biome, `tsc` y el build. Más detalle (convenciones, cómo simular la API) en [Panel](panel.md#tests-del-panel).

## Dónde está el código

- `apps/backend/tests/` y su `conftest.py`.
- `apps/backend/src/core/testing/` (`harness.py`, `clock.py`, `effects.py`).
- `apps/backend/src/autobot/channels/testing.py`: `check_rendering`.
- `apps/backend/pyproject.toml`: marcadores y `--strict-markers`.

## Relacionado

- [Añadir un pack](anadir-un-pack.md) y [Migraciones y RLS](migraciones-y-rls.md).
- [Entorno local](entorno-local.md): `make check` y `make test-fast`.
- [Canales](../arquitectura/canales.md): los adaptadores que renderizan las respuestas.
