# ADR-017 — Instalación, acceso y traslado del servidor

**Estado:** vigente. Reúne el antiguo ADR-012 (cuentas, bootstrap, traslado y `restic init`
manual), cuya instalación desde el portátil (`server-init.sh`) sustituyó este ADR.

## Contexto

El ADR-005 fija una sola VPS con Docker Compose, pero no decide quién tiene acceso de
`root`, cómo se instala una máquina limpia de forma repetible ni cómo se traslada todo a
otra (cambio de proveedor, ampliación o primera instalación de verdad) sin que las dos
envíen mensajes a la vez.

La primera versión (ADR-012) instalaba la VM desde el portátil con `server-init.sh` por
SSH. Al revisarla aparecieron tres problemas: `restore.sh` exigía un marcador
(`bootstrap-complete`) que ningún script creaba y los simulacros lo falsificaban;
`server-init.sh` subía a GitHub la clave privada **del operador**, con acceso de `admin`; y
`ssh-deploy.sh` hacía `git checkout` antes de que `deploy.sh` tomara su candado. Además, la
persona quería algo simple: un comando para local y otro para la VM, ejecutado dentro de
ella.

## Decisión

### Acceso al servidor

- **Dos cuentas, una sola clave.** `deploy` (sin `sudo`, en el grupo `docker`, que ya
  equivale a `root`, así que limitarle el `sudo` solo evitaría accidentes) ejecuta los
  contenedores y acepta la clave de CI, restringida por comando forzado a
  `deploy/scripts/deploy.sh <sha>`. `admin` (con `sudo` sin contraseña: el único control de
  acceso es la clave) existe solo para tareas de `root`. Las dos aceptan la **misma** clave
  del operador.
- **Repo público, clon por HTTPS**, sin deploy key. Si el repo pasara a privado, habría que
  añadir una de solo lectura.
- **`bootstrap-server.sh` en dos fases.** `--base` (paquetes, Docker, swap, cuentas, clon y
  timers) nunca toca `sshd`, así que repetirla es seguro. `--harden-ssh` (cierra `root` y
  contraseña, activa `ufw`) va aparte y solo tras comprobar, desde una sesión nueva, que
  `deploy@` y `admin@` aceptan la clave.

### Instalación

- **`deploy/scripts/install-vm.sh`** se ejecuta como root (o con `sudo`) dentro de la VM,
  desde un clon del repositorio. Es idempotente y reanudable por pasos (`ci-key`, `base`,
  `env`, `deploy`, `health`, `harden-ssh`, `marker`, `github`; `--only`, `--skip`,
  `--check`). Reutiliza `bootstrap-server.sh` (paquetes, Docker, cuentas, timers, ufw y
  sshd), `ensure-env.sh` y `deploy.sh`. Nunca inventa credenciales ni ejecuta
  `restic init`; termina con un resumen de pasos manuales.
- **Endurecer SSH va al final y con confirmación explícita**: comprueba que la clave del
  operador está en `admin` y `deploy` y que sshd escucha solo en el 22, pide abrir una
  segunda sesión y confirmar. Sin terminal y sin `--yes`, se omite y queda pendiente.
- **Clave de CI propia**: el instalador genera un ed25519 dentro de la VM, instala su
  pública en `deploy` con `restrict,command="/srv/autobot/deploy/scripts/ssh-deploy.sh"`
  y deja la privada en `/root/autobot-ci-deploy-key` (solo root). Se sube como
  `DEPLOY_SSH_KEY` del entorno `production` (desde el portátil, o con `gh` desde la VM
  si está autenticado y se confirma) y se borra con `shred`. La clave del operador nunca
  sale de su máquina. El primer despliegue usa el mismo `ssh-deploy.sh` que el CI.
- **Marcador `bootstrap-complete`**: lo escribe `install-vm.sh` (paso `marker`) solo
  cuando existen el de base y el de sshd. `restore.sh` lo exige. Los simulacros en una
  máquina que no es VM usan `AUTOBOT_RESTORE_SKIP_BOOTSTRAP_CHECK=true`, que se salta la
  comprobación avisándolo, en vez de falsificar el fichero.
- **`--restore-target`** deja la VM lista solo para restaurar (sin `.env` ni despliegue):
  es lo que espera `server-migrate.sh` en el destino.
- **`server-init.sh` se retira**, con su target `make server-init`, sus tests y
  `var/server.env` como entrada de instalación (`server-migrate.sh` solo lo usa para
  `PUBLIC_HOST`). `make install-vm` es un envoltorio de `sudo install-vm.sh`.
- **Candado antes del checkout**: `ssh-deploy.sh` toma `var/.deploy.lock` antes de tocar el
  árbol y avisa a `deploy.sh` con `AUTOBOT_DEPLOY_LOCK_HELD=1` para que no lo tome dos veces.
- **Local**: `make local` (`deploy/scripts/install-local.sh`) comprueba requisitos, crea
  `.env` desde `.env.example` si falta, y repite db, roles, build, migrate, `apply_grants`,
  `seed_demos`, servicios y salud, sin borrar datos. `make dev-bootstrap` queda como alias.
- Otras mejoras de la misma revisión: `server-migrate.sh` exige FROM distinto de TO y un
  destino sin despliegue antes de `down -v`; `backup.sh` valida el volcado
  (`pg_restore --list`), comprueba espacio y ejecuta `restic check --read-data-subset`
  semanal (la retención no cambia); `restore-test.sh` arranca `web` y comprueba
  `/health/internal` y que la clave restaurada descifra `tenant_secret`; `ensure-env.sh`
  deriva siempre `DB_*_URL` de `FP_*_PASSWORD`; un `caddy reload` fallido avisa a ops.

### Traslado y copias

- **`server-migrate.sh` (`make server-migrate FROM= TO=`)** ensaya la restauración en el
  destino sin marcarlo como desplegado. En el corte congela el origen (`var/.frozen`, que
  `deploy.sh` y `restore.sh` respetan) antes del backup final, y el destino restaura **ese
  snapshot concreto** (nunca `latest`). Los workers del destino solo arrancan tras
  comprobar por SSH que el origen no tiene ningún contenedor de aplicación en marcha.
- **`restic init` siempre manual.** Un `RESTIC_REPOSITORY` mal escrito crearía un
  repositorio nuevo y vacío que ocultaría la pérdida del bueno. `backup.sh` compara el id
  del repositorio con `var/.restic-repo-id` y se niega si no coincide.

## Alternativas consideradas

- **`sudoers` limitado para `deploy`**: más complicado de lo que parece (la copia del
  script tiene que ser de `root` y `sudo` limpia el entorno) para una barrera que no es
  real, porque `deploy` ya puede hacerse `root` con el grupo `docker`.
- **Deploy key SSH para clonar**: innecesaria mientras el repo sea público.
- **`restic init` automático**: oculta en silencio la pérdida del repositorio correcto.
- **Reducir `server-init.sh` a un envoltorio que copie el repo y llame a `install-vm.sh`**:
  mantiene un segundo punto de entrada y `var/server.env` sin aportar nada; descartado.
- **Subir la clave del operador como secreto de CI**: da a GitHub acceso de administrador;
  descartado.
- **Falsificar el marcador en los simulacros**: oculta justo lo que el marcador debe
  garantizar; descartado.

## Consecuencias

- Una cuenta más (`admin`), sin clave ni contraseña propias.
- El primer `restic init` de cada servidor es un paso manual explícito.
- Hay que clonar el repo en la VM y tener acceso de root/sudo ahí; el portátil ya no
  participa salvo para `gh secret set` y la clave del operador.
- La clave privada de CI existe en `/root` hasta que se entrega: el resumen lo recuerda.
- `restore-test.sh` y `localprod.sh` ya no ejercitan la comprobación del marcador.
- Tiempos de corte estimados, sin medir aún en dos VMs reales: traslado planificado,
  15-30 minutos más el TTL del DNS y sin pérdida de datos (salvo logs técnicos); pérdida de
  la máquina, 1-2 horas y hasta una hora de datos.

## Cuándo revisarla

- Si el repositorio pasa a privado (hace falta credencial de clonado).
- Si hay más de un operador con acceso de `root`: `admin` pasaría a tener una clave por
  persona.
