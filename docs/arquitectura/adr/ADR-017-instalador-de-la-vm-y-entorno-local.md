# ADR-017 — Instalador de la VM desde dentro y un solo comando para local

**Estado:** vigente; sustituye la parte de `server-init.sh` del [ADR-012](ADR-012-instalacion-y-traslado.md)

## Contexto

El ADR-012 instalaba la VM desde el portátil del operador con `server-init.sh` por SSH.
Revisándolo aparecieron tres problemas y una petición:

- `restore.sh` exigía `/var/lib/autobot/bootstrap-complete`, que ningún script creaba
  (el bootstrap escribe `bootstrap-base-complete` y `bootstrap-sshd-complete`);
  `restore-test.sh` y `localprod.sh` lo falsificaban con `touch`.
- `server-init.sh` subía a GitHub (`DEPLOY_SSH_KEY`) la clave privada **del operador**,
  con acceso de `admin` a la VM, y la clave de CI generada nunca llegaba a ningún sitio.
- `ssh-deploy.sh` hacía `git checkout` antes de que `deploy.sh` tomara su candado.
- La persona quiere algo simple: un comando para local y otro para la VM, ejecutado
  dentro de la VM, no orquestado por SSH desde el portátil.

## Decisión

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

## Alternativas consideradas

- **Reducir `server-init.sh` a un envoltorio que copie el repo y llame a `install-vm.sh`**:
  mantiene un segundo punto de entrada y `var/server.env` sin aportar nada; descartado.
- **Subir la clave del operador como secreto de CI**: da a GitHub acceso de administrador;
  descartado.
- **Falsificar el marcador en los simulacros**: oculta justo lo que el marcador debe
  garantizar; descartado.

## Consecuencias

- Hay que clonar el repo en la VM y tener acceso de root/sudo ahí; el portátil ya no
  participa salvo para `gh secret set` y la clave del operador.
- La clave privada de CI existe en `/root` hasta que se entrega: el resumen lo recuerda.
- `restore-test.sh` y `localprod.sh` ya no ejercitan la comprobación del marcador.

## Cuándo revisarla

- Si el repositorio pasa a privado (hace falta credencial de clonado) o si hay más de un operador.
