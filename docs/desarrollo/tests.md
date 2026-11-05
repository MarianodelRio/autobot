# Tests

## Estructura

Los tests viven en `apps/backend/tests/`, repartidos por lo que prueban, no por si son
unitarios o de integración ([ADR-010](../arquitectura/adr/ADR-010-estructura-del-repo.md)):

- `core/` — tests de `core/`, sin BD.
- `packs/<pack>/` — tests de cada pack, incluido su escenario de conversación.
- `platform/{channels,runtime,tenancy,owner,ops,panel}/` — tests de `autobot/`,
  agrupados por dominio.
- `contract/` — contrato con cada proveedor externo simulado (WhatsApp, Telegram,
  Google Calendar).
- `isolation/` — el test genérico de aislamiento de RLS.
- `tools/` — tests de los scripts de operación (`tools/`, `deploy/scripts/`).
- `repo/` — comprobaciones sobre el propio repositorio (comandos documentados,
  variables de entorno documentadas, settings).
- `fixtures/` — payloads de WhatsApp/Telegram y el `toy_pack`, un pack mínimo usado
  por varios tests de la plataforma.

## Marcadores

- `db`: el test necesita PostgreSQL. Se aplica automáticamente (vía un hook en
  `conftest.py`) a todo lo que pide la fixture `django_db`; no hace falta marcarlo a
  mano.
- `contract`: contrato con un proveedor externo simulado. Se aplica automáticamente a
  todo lo que vive bajo `tests/contract/`.

```bash
make test       # la suite completa
make test-fast  # pytest -m "not db", sin base de datos levantada
```

## Escenarios de conversación

Cada pack trae su escenario de conversación, obligatorio y que se actualiza con cada
cambio de su flujo (`CLAUDE.md`). Cada escenario se renderiza con los dos adaptadores
de canal (WhatsApp y Telegram) y comprueba los límites comunes (botones ≤ 3, listas
≤ 10 filas, textos ≤ 4096, ids ≤ 64 bytes).
