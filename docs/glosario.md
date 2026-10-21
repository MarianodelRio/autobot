# Glosario

> Términos técnicos de `design.md` explicados en lenguaje llano.

| Término | Qué es (en llano) |
|---|---|
| **Advisory lock** | Candado de PostgreSQL que la aplicación toma por un nombre (p. ej. "calendario X, día Y") para que dos procesos no hagan lo mismo a la vez |
| **API** | La forma en que un programa le pide cosas a otro (p. ej. "envía este mensaje" a Meta) |
| **Backoff exponencial** | Reintentar esperando cada vez más (2 s, 4 s, 8 s…) para no saturar |
| **BSUID** | Identificador de un usuario de WhatsApp propio de cada negocio (`ES.xxxx`); Meta lo envía en lugar del teléfono cuando el usuario usa nombre de usuario |
| **Caddy** | Servidor web que hace de puerta de entrada y consigue y renueva solo los certificados HTTPS |
| **CI** | Integración continua: tests automáticos en cada cambio, antes de aceptarlo |
| **Contenedor / imagen** | La imagen es el programa empaquetado con todo lo que necesita; un contenedor es esa imagen ejecutándose |
| **Dataset** | Datos estructurados de un negocio (p. ej. horarios de autobús) en ficheros, con un validador estricto |
| **Docker Compose** | Herramienta que arranca varios contenedores juntos (web, worker, base de datos…) a partir de un fichero |
| **Expand/contract** | Cambiar la BD en dos pasos para que la versión vieja y la nueva del código funcionen a la vez |
| **Fernet** | Formato de cifrado simétrico de la librería `cryptography`; aquí cifra las credenciales de los negocios |
| **GHCR** | Registro de imágenes de contenedor de GitHub |
| **healthchecks.io** | Servicio externo que avisa si deja de recibir un "latido" periódico; detecta que algo se ha caído aunque no pueda avisar por sí mismo |
| **HMAC / firma** | Un código que demuestra que un mensaje viene de quien dice (Meta) y no ha sido modificado |
| **Idempotente** | Que hacerlo dos veces tiene el mismo efecto que hacerlo una |
| **Migración** | Script que cambia la estructura de la base de datos |
| **Monolito modular** | Un solo programa organizado en módulos bien separados (lo contrario de microservicios) |
| **Procrastinate** | Librería que usa PostgreSQL como cola de trabajos pendientes |
| **pydantic** | Librería para definir y validar estructuras de datos en Python |
| **restic** | Herramienta de copias de seguridad que cifra los datos antes de enviarlos fuera |
| **RLS** (Row-Level Security) | Regla de la base de datos que solo deja ver las filas del negocio activo |
| **RPO / RTO** | Cuántos datos podrías perder como máximo / cuánto tardas en recuperar el servicio |
| **Tenant** | Un negocio de la plataforma |
| **UUIDv7** | Identificador único que además se ordena por fecha de creación |
| **VPS** | Servidor virtual alquilado a un proveedor, con su propia IP |
| **Webhook** | Aviso que un servicio externo (Meta) envía a nuestra URL cuando pasa algo |
| **Worker** | El proceso que hace el trabajo de fondo (lo que no es atender una petición web) |
