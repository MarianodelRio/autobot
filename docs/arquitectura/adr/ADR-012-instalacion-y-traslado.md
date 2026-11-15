# ADR-012 — Instalación y traslado del servidor desde la máquina del operador

**Estado:** aceptada

## Contexto

ADR-005 fija una sola VPS con Docker Compose, pero no quién administra el acceso de
`root`/`sudo` ni cómo se repite la instalación en una máquina nueva (traslado de
proveedor, ampliación de recursos, o la primera instalación de verdad). El plan de
lanzamiento (bloques A y T) exige que `make server-init` deje una VM limpia
funcionando de forma idempotente y que `make server-migrate` traslade todo a otra VM
sin que las dos envíen mensajes a la vez. `bootstrap-server.sh` (A1–A11) ya resuelve
los errores bloqueantes del primer despliegue, pero no decide cómo se repite el
bootstrap sin quedarse fuera por SSH, ni qué cuenta puede hacer tareas de `root`
después de que termine.

## Decisión

- **Dos cuentas, una sola clave.** `deploy` (sin `sudo`, en el grupo `docker`: ya
  equivale a `root` por eso, así que limitarle el `sudo` no es una barrera de
  seguridad real, solo evita accidentes) ejecuta los contenedores y acepta además la
  clave de CI, restringida por comando forzado a `deploy/scripts/deploy.sh <sha>`.
  `admin` (con `sudo` sin contraseña: no hay contraseñas en ningún sitio, el único
  control de acceso es la clave) existe solo para tareas de `root` — repetir el
  bootstrap, actualizar paquetes, reiniciar `sshd`. Las dos cuentas aceptan la
  **misma** clave del operador; no hace falta una clave distinta por cuenta.
- **Repo público, clon por HTTPS.** Sin deploy key: `git clone https://.../<repo>.git`
  no necesita ninguna credencial. Si el repo pasara a privado, habría que añadir una.
- **`bootstrap-server.sh` en dos fases.** `--base` (paquetes, Docker, swap, las dos
  cuentas, el clon, los timers) nunca toca `sshd`, así que repetirla desde la misma
  sesión es segura. `--harden-ssh` (cierra `root` y contraseña, activa `ufw`) es una
  invocación aparte, deliberadamente manual: solo tiene sentido una vez verificado,
  desde una sesión nueva, que `deploy@` y `admin@` aceptan la clave del operador.
- **`server-init.sh` (A15, `make server-init`)**, ejecutado por la persona desde su
  máquina, con `var/server.env` (no en git): valida en local (DNS, ficheros,
  `gh auth status`), sube el bootstrap y ejecuta `--base` por SSH, pide confirmar
  antes de `--harden-ssh`, sube los secretos fusionando el `.env` existente (nunca
  lo sustituye), inicializa restic a mano y comprueba su id (A3) antes de activar el
  timer, crea el entorno `production` y sus secretos con `gh`, lanza el primer
  despliegue con comprobación estricta de HTTPS, y por último crea el usuario del
  panel y registra los webhooks. Cada paso comprueba primero si ya está hecho.
- **`server-migrate.sh` (T4, `make server-migrate FROM= TO=`)**: ensaya la
  restauración en el destino con `AUTOBOT_RESTORE_DB_ONLY=true` sin marcarlo como
  desplegado; en el corte, congela el origen (`var/.frozen`, que `deploy.sh` y
  `restore.sh` respetan) antes del backup final, y el destino restaura **ese
  snapshot concreto** (`AUTOBOT_RESTORE_SNAPSHOT=<id>`, nunca `latest`), nunca uno
  que un origen o destino tercero pudiera escribir mientras tanto. Los workers del
  destino solo arrancan tras comprobar por SSH que el origen no tiene ningún
  contenedor de aplicación en marcha.
- **`restic init` siempre manual (A3).** Ningún script lo ejecuta automáticamente:
  un `RESTIC_REPOSITORY` mal escrito crearía un repositorio nuevo, vacío, que
  ocultaría la pérdida del bueno. `backup.sh` compara el id del repositorio contra
  `var/.restic-repo-id` (que escribe la primera vez) y se niega si no coincide.

## Alternativas consideradas

- **`sudoers` limitado para `deploy`** (la propuesta original de A12): más
  complicado de lo que parece (la copia del script tiene que ser de `root`, porque
  si no `deploy` la modifica; `sudo` limpia el entorno, así que `REPO_URL` no
  llegaría) para una barrera que no es real, porque `deploy` ya puede hacerse
  `root` con el grupo `docker`. Descartada a favor de la cuenta `admin` separada.
- **Deploy key SSH para clonar el repo**: innecesaria mientras el repo sea público;
  un secreto más que gestionar y un paso más en `server-init.sh` sin beneficio.
- **`restic init` automático** (lo que hacía `backup.sh` hasta esta revisión):
  oculta en silencio la pérdida del repositorio correcto si el destino está mal
  configurado. Descartado; ahora es un paso manual de `server-init.sh`.

## Consecuencias

- Una cuenta más que crear y mantener (`admin`), pero sin clave ni contraseña
  propias: es la misma clave del operador, solo que entra por otra cuenta.
- El primer `restic init` de cada servidor es un paso manual explícito (dentro de
  `server-init.sh`, con confirmación), no algo que un backup descubre por sí solo.
- Si el repositorio pasa a privado, hay que añadir de nuevo una deploy key de solo
  lectura al clonado de `bootstrap-server.sh --base`.

## Cuándo revisarla

- Si el repositorio deja de ser público.
- Si se necesita más de un operador con acceso de `root`: entonces `admin` pasa a
  tener una clave por persona, en vez de compartir la del operador único actual.
