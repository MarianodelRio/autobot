# ADR-009 — Config y datasets de los negocios en PostgreSQL, versionados

**Estado:** aceptada

## Contexto

Hoy `tenants/<slug>/tenant.yaml` vive en git y se copia a la imagen; `secrets.yaml` vive
en el servidor; los horarios de `bus` van en `tenants/<slug>/datasets/`. El panel necesita
que la persona pueda cambiar la config de un negocio, pausarlo, sustituir sus secretos y
dar de alta uno nuevo, todo con historial y sin reiniciar nada ni tocar git. Este ADR
fija las decisiones de arquitectura.

## Decisión

- **La base de datos es la única fuente de verdad** de la config y los datasets de cada
  negocio. `tenants/` desaparece del repositorio y de la imagen (sigue en `.gitignore`
  para la copia local del tenant de ejemplo); la CI falla si algo queda versionado ahí.
- **Versiones inmutables.** `tenant_document_version` guarda cada versión del
  `TenantDocument`; `tenant_dataset_version` guarda cada versión de los datasets
  (horarios de `bus`). La
  versión vigente es la de mayor número; volver atrás crea una versión nueva con el
  contenido de una anterior, nunca borra las intermedias. La única excepción es la purga.
- **`config_revision`** (una sola fila, global, sin `tenant_id`) es un contador que toda
  escritura incrementa dentro de su transacción. Cada proceso recarga su registro en
  memoria cuando detecta un cambio, consultando como mucho cada 2 s, y lo fija durante la
  vida de una petición o un trabajo de cola (`registry_scope`) para que un cambio de
  config nunca llegue a mitad de un trabajo.
- **Tres tablas** (`tenant_document_version`, `tenant_dataset_version`, `tenant_secret`)
  **llevan `tenant_id` pero no RLS**, más `config_revision`, global y sin `tenant_id`.
  Son configuración de la plataforma: cada proceso necesita leerlas enteras al arrancar o
  al recargar, igual que hoy lee todos los YAML y `secrets.yaml` enteros. Figuran en la
  lista de excepciones del test de aislamiento. `fp_app` solo tiene `SELECT`; solo
  `fp_owner` escribe.
- **Secretos de canal cifrados en la propia base**, con Fernet (`cryptography`,
  `MultiFernet`) a partir de `SECRETS_ENCRYPTION_KEY` (en el `.env` de `web` y `worker`;
  admite varias claves separadas por comas para rotarla). La API del panel nunca devuelve
  los valores: solo qué campos están puestos y cuándo cambiaron. Se escriben sustituyendo
  el juego completo del canal.
- **Un único servicio de escritura, `autobot.tenancy.store`**, usado tanto por la API del
  panel como por los comandos de operación. Cada escritura abre
  `transaction.atomic(using="owner")`, serializa con un `SELECT … FOR UPDATE` de
  `config_revision`, valida construyendo un registro candidato con todos los documentos
  vigentes más el nuevo (rechazando si el tenant cae en `errors`, queda degradado o
  ambiguo), inserta la versión, actualiza el espejo `tenant` y audita, todo en la misma
  transacción.
- **Cada pack trae su plantilla** (`Pack.template`): un documento de demo completo y, si
  el pack tiene datasets, sus ficheros iniciales. Los demos se siembran desde la plantilla
  (`seed_demos`) solo si el tenant no tiene ninguna versión; después, la verdad es la base
  y se editan en el panel. La plantilla es también el punto de partida del asistente de
  alta de un negocio nuevo.
- **Baja y purga.** Dar de baja (`offboarded`) por comando (`tenant_status <slug>
  offboard`) o, para un negocio pausado o en alta, desde el borrado del panel, que lo
  hace por su cuenta. La purga (`tenant_purge`, o «Eliminar cliente» en el panel) borra
  todo lo que el sistema guarda del negocio —incluidos `tenant_secret`, todas las
  versiones de datasets y de documento, sus alertas y su auditoría— y también la fila
  espejo `tenant`: el slug queda libre. Un webhook tardío de ese canal recibe 404.
  Solo permanece una entrada de auditoría `tenant.purge` sin datos del negocio
  (ADR-011).
- **Permisos de base de datos reproducibles.** Un único módulo (`autobot/db/grants.py`) declara el
  estado deseado como sentencias SQL idempotentes (GRANT, REVOKE, `ALTER DEFAULT
  PRIVILEGES`), que se vuelve a aplicar (`apply_grants`) en cada migración que cree tablas
  o cambie permisos, en cada despliegue y después de cada restauración. Así un `REVOKE`
  nunca se pierde al restaurar un backup, que es lo que pasa hoy con el de la migración
  `0002`.
- **Horarios de `bus` por terminal, no por el panel** (`tenant_dataset export`/`import`),
  porque son ficheros extensos con su propio flujo de revisión (`make bus-*`); el panel
  solo los muestra.

## Alternativas consideradas

- **Seguir con YAML en git y copiar a la imagen:** cada cambio exigiría un commit, un
  despliegue y perder la auditoría de quién cambió qué desde el panel; incompatible con
  "se aplica al guardar".
- **Commits a git desde el propio panel** (generar un commit por cada cambio de config):
  añadiría la complejidad de gestionar credenciales de git desde la aplicación y un
  repositorio que mezclaría código y datos de clientes, sin beneficio sobre versionar en
  la propia base de datos, que ya se respalda.
- **Un `.env` por cliente para los secretos de canal:** obligaría a montar un fichero por
  cliente, reiniciar en cada cambio, y renunciar a que el panel los escriba con
  auditoría.
- **Una clave de cifrado por cliente:** solo aportaría borrado criptográfico si las claves
  vivieran fuera de los backups (un KMS externo); aquí estarían en la misma base o en el
  mismo `.env`, que también se respaldan, así que añadiría complejidad sin beneficio real.
- **RLS también en las cuatro tablas de config:** exigiría fijar el tenant antes de poder
  leer la propia config que dice qué tenant es, y el panel necesita leer la de todos los
  negocios a la vez.

## Consecuencias

- Todo cambio de config queda versionado, auditado y se aplica sin reiniciar ningún
  proceso, con un retraso de hasta 2 s por la recarga del registro.
- Las tres tablas de config con `tenant_id`, más `config_revision`, son una excepción
  explícita y vigilada a la regla de RLS; un descuido ahí no tiene la misma red de
  seguridad que el resto de tablas con datos de cliente.
- Restaurar un backup sin `.env` deja los secretos de canal cifrados pero ilegibles; hay
  que restaurar también el `.env` con `SECRETS_ENCRYPTION_KEY`.
- Los permisos de base de datos quedan declarados en un solo sitio y se reaplican solos
  tras cada despliegue o restauración, en vez de depender de que una migración antigua
  siga vigente.

## Cuándo revisarla

- Si algún negocio exige que su config nunca pueda ser leída por un proceso que atiende a
  otros (por ejemplo, por contrato), reconsiderar RLS o una base aparte para ese caso.
- Si el volumen de versiones por tenant crece mucho, añadir una política de purga de
  versiones antiguas (hoy no existe: todas se conservan).

Notas de implementación (formato de directorio, carga y fijado del registro, escrituras
y activación) en
[`docs/arquitectura/config-y-registro.md`](../config-y-registro.md).
