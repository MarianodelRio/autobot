# ADR-013 — Biblioteca de conjuntos de datos

**Estado:** aceptada

## Contexto

ADR-009 liga los datasets de un pack (hoy solo los horarios de `bus`) directamente al
cliente: `tenant_dataset export`/`import` los sube o baja uno a uno, por terminal, y el
panel solo los muestra. Esto causaba dos errores concretos en la primera versión:

- **Datos de demo heredados.** Al dar de alta un `bus` sin pasar datasets explícitos, `store.create_tenant`
  copia en silencio los del *template* de la demo (`store.py`, antes de este ADR):
  un cliente real se queda con tres líneas inventadas entre Posadas y Córdoba sin que
  nadie lo note.
- **Bloqueo circular.** Si cambias los pueblos de la config antes de subir el dataset real (o al
  revés), `bus.load_data` falla con un `RuntimeError` concreto (p. ej. «Nowhere no es
  una localidad conocida de horarios/»), pero `store._validate` lo reduce a «datasets:
  datos no válidos», sin decir cuál. La única salida hoy es subir documento y dataset
  juntos con `tenant_config import`, por terminal.

Las dos vienen de la misma causa: no hay sitio donde preparar y validar unos horarios
*antes* de que un alta los necesite, y no hay lista de la que elegir pueblos ya
conocidos. Se decide una biblioteca de conjuntos de
datos: se suben por terminal, igual que hoy, pero antes de dar de alta a nadie; el alta
elige una entrada ya validada.

## Decisión

- **Tabla nueva, `dataset_library_version`:** `id` (UUIDv7), `pack`, `dataset` (p. ej.
  `"timetable"`), `name` (slug elegido al subir, p. ej. `"linea-cordoba"`), `version`
  (entero, por `(pack, dataset, name)`), `files` (jsonb, igual que
  `tenant_dataset_version.files`), `sha256`, `summary` (jsonb: lo que
  `Pack.dataset_summary` calculó al subir — líneas, pueblos, vigencia — para que el
  panel nunca cargue el contenido), `author`, `comment`, `created_at`. Es configuración
  de la plataforma: **sin `tenant_id`, sin RLS**, igual que `tenant_document_version`;
  permisos declarados en `autobot/db/grants.py` (`fp_app` sin acceso directo, solo a
  través del registro cuando el pack la necesita; `fp_readonly` con `SELECT`, como el
  resto de tablas de configuración).
- **Copia, no referencia.** Elegir una entrada de la biblioteca en el alta, o aplicar
  una versión nueva desde la ficha, **copia** sus ficheros a
  `tenant_dataset_version` (que gana tres columnas: `source_name`, `source_version`,
  `source_sha`, simples, sin FK). Una subida mala a la biblioteca nunca toca a un
  cliente activo; la purga de un cliente (ADR-011) no borra nada de la biblioteca, y al
  revés, borrar una entrada de la biblioteca no afecta a los clientes que ya copiaron de
  ella. El cliente solo guarda de dónde vino su copia, nunca una relación viva.
- **`Pack.dataset_summary(dataset: str, root: Path) -> dict`,** hook nuevo y opcional en
  `core.pack.Pack`, junto a `load_data`. Igual que este, recibe un directorio con la
  forma de `datasets/<name>/` y valida el contenido con las reglas propias del pack
  (para `bus`, `loader.cargar` sin pueblos del menú); de ahí sale el `summary` que se
  guarda en la biblioteca y lo que permite construir la lista de pueblos del alta
  sin necesitar la config del cliente. Rompe el bloqueo circular: primero se suben y
  validan los horarios en la biblioteca, sin pueblos; el pueblo se elige de esa lista.
- **El alta de un pack con datasets no se completa sin elegir una entrada** de la
  biblioteca para cada dataset que declare; así deja de poder ocurrir la herencia de horarios de la demo. La demo de
  `bus` deja de ser un caso especial: `seed_demos` sube su propio dataset como una
  entrada más de la biblioteca (`bus/timetable/demo`, comentario «Plantilla de la
  demo»), y la demo es una copia de esa entrada, igual que cualquier cliente.
- **Subida con `--base-sha`.** El comando rechaza la subida si el `sha256` de la
  última versión de esa `(pack, dataset, name)` no coincide con el que se le pasa,
  igual que `publish` rechaza una config con `base_version` desactualizado. Si el
  `sha256` de la subida es idéntico al vigente, no crea versión nueva.
- **Comandos que desaparecen:** `tenant_dataset` (import/export), `bus-bajar`,
  `bus-publicar`, el concepto de `.publicado/` y `tools/bus/data.py`. Los sustituye un
  comando nuevo de la biblioteca y la elección en el alta; `bus-validar` y
  `bus-formatear` siguen, ahora sobre `var/datos/<nombre>/` sin más cambio que el
  nombre con el que se identifica el conjunto.

  *Actualización (2026-11-20):* al implementarlo, `bus-bajar` y `.publicado/` no
  desaparecieron. `bus-bajar` baja ahora una entrada de la biblioteca (no de un
  cliente) y deja una copia en `var/datos/<nombre>/.publicado/timetable`, que es la
  base del diff de `bus-revision`. Sí desaparecieron `tenant_dataset`, `bus-publicar` y
  `tools/bus/data.py`.

## Alternativas consideradas

- **Referencia en vez de copia:** el cliente apuntaría a la fila de la biblioteca en
  vez de copiar sus ficheros. Se descarta: una subida nueva cambiaría los horarios de
  todos los clientes que la usan a la vez, sin el paso explícito «Aplicar» que exige el
  plan, y `fp_app` tendría que poder leer la biblioteca en cada arranque del registro en
  vez de solo `tenant_dataset_version`.
- **Seguir subiendo datasets por cliente (estado actual):** es exactamente lo que causa
  los dos errores; no resuelve nada por sí solo.
- **Guardar el contenido también en el cliente de origen más una tabla de versiones
  separada sin copiar:** más complejo que una sola tabla con columnas de origen, sin
  beneficio real, porque el contenido ya vive en `tenant_dataset_version` igual que hoy.

## Consecuencias

- El alta de un pack con datasets pasa a depender de que exista al menos una entrada de
  la biblioteca para ese pack y ese dataset; si no la hay, el alta no se puede completar
  hasta subir una por terminal. Es el comportamiento querido (impide heredar horarios de la demo), pero cambia
  el orden de trabajo: horarios primero, alta después.
- Una tabla más sin `tenant_id` ni RLS: entra en la lista de excepciones vigiladas de
  ADR-009 y en `SENSITIVE_TABLES`/`CONFIG_TABLES` de `grants.py` si se decide que lo
  sea (no lleva secretos, así que no es sensible, pero sí es de la plataforma).
- `tenant_dataset_version` crece con tres columnas opcionales (`source_name`,
  `source_version`, `source_sha`); los datasets importados por `tenant_config import`
  (sin pasar por la biblioteca) las dejan a `null`.
- Los comandos y la documentación de `horarios-bus.md` cambian; cualquier automatismo
  externo que invocara `tenant_dataset` o `bus-publicar` directamente deja de
  funcionar.

## Cuándo revisarla

- Si otro pack necesita datasets compartidos entre clientes de verdad (no solo como
  plantilla inicial), reconsiderar la copia en favor de una referencia para ese caso
  concreto.
- Si el volumen de versiones de la biblioteca crece mucho, añadir una política de
  purga de versiones antiguas sin cliente que las use (hoy no existe, igual que para
  `tenant_document_version`).
