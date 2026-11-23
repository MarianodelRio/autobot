# ADR-022 — La clave de cifrado nunca se genera sola

**Estado:** aceptada

## Contexto

`ensure-env.sh` genera los secretos internos que faltan en `.env`, y `deploy.sh` lo ejecuta
en cada despliegue. Con `SECRETS_ENCRYPTION_KEY` eso era peligroso: si la clave desaparecía
de un `.env` ya en uso (edición a mano, `.env` restaurado sin ella), se creaba una nueva en
silencio y todos los secretos de canal de `tenant_secret` quedaban ilegibles. Desde el
[ADR-021](ADR-021-backups-resistentes.md) la clave tampoco viaja en los backups, así que ya
no hay otra copia en el servidor: la única es la del gestor de contraseñas.

## Decisión

- `ensure-env.sh` solo genera `SECRETS_ENCRYPTION_KEY` con `--first-install`. Sin esa opción,
  si falta, aborta con exit 1 sin tocar `.env` y explica dónde está la clave (gestor de
  contraseñas, `rotar-secretos.md`).
- Los demás secretos internos se siguen generando como hasta ahora: perderlos se arregla
  rotándolos; perder la clave de cifrado no tiene arreglo.
- Quién pasa `--first-install`: `install-vm.sh` solo si el servidor aún no ha desplegado
  nunca (no existe `var/.deployed-sha`) y `localprod.sh` (ensayo local con `.env` nuevo).
  `deploy.sh` y `restore.sh` nunca lo pasan: `restore.sh` ya instala la clave dada por la
  persona antes de ejecutar `ensure-env.sh`.
- Al generarla, el script avisa de que hay que guardarla ya en el gestor de contraseñas.

## Alternativas consideradas

- **Variable de entorno `AUTOBOT_FIRST_INSTALL=1`:** se queda puesta en perfiles o scripts y
  vuelve a permitir la generación silenciosa; un argumento explícito vale para una sola
  ejecución.
- **Detectar "primera instalación" mirando la base de datos:** `ensure-env.sh` corre antes de
  levantar la base y no debe depender de ella.
- **Seguir generándola y avisar:** el aviso llega tarde; el daño (secretos ilegibles) ya está
  hecho cuando alguien lo lee.

## Consecuencias

- Un servidor al que le falta la clave no despliega hasta que alguien la repone: es un fallo
  ruidoso en lugar de una pérdida de datos silenciosa.
- La instalación de un servidor nuevo sin datos sigue funcionando sin pasos extra con
  `install-vm.sh`; la clave generada hay que copiarla al gestor de contraseñas a mano.

## Cuándo revisarla

Si la clave pasa a vivir en un gestor de secretos del servidor (KMS o similar) y deja de
estar en `.env`.
