# Rotar secretos

Cómo cambiar un secreto de canal (Meta, Telegram), de la plataforma (`.env`) o la clave de
cifrado de la base de datos. Léelo cuando un token caduque, se revoque o pueda haberse
expuesto.

!!! warning "Aprobaciones"
    Cambiar cifrado, secretos o firma de webhooks requiere aprobación humana explícita.
    Genera el valor nuevo en el proveedor y guárdalo en el gestor de contraseñas; nunca en
    git, argumentos de jobs, logs ni mensajes de revisión.

**Requisitos:** SSH como `deploy` (clave de operación) o el panel por túnel; el valor nuevo.
**Diagnóstico:** `make tenant-health SLUG=<slug>` (en local) o «Comprobar ahora» en el
panel indica la autenticación; identifica si el secreto es de Meta, Telegram, bot de demo,
avisos u otra integración.

## Secretos de canal y de plataforma

La firma del webhook usa `app_secret` o `webhook_secret`; cambiarla exige coordinación con el proveedor.

**Pasos:** genera el nuevo valor en el proveedor y guárdalo en
el gestor de contraseñas. Para un canal, lo más simple es la ficha del cliente en el
panel (pestaña Configuración, sección Canal, «Cambiar credenciales»): el diálogo
sustituye el valor dejando en blanco los que no cambian, y «Generar» rellena
`verify_token`/`webhook_secret` con un valor aleatorio de 48 caracteres que se
muestra para copiarlo; los valores guardados nunca se muestran. Tras cambiar
`webhook_secret`, pulsa «Registrar webhook» en la misma pantalla (solo Telegram);
tras cambiar `verify_token`, actualízalo también en Meta. Alternativamente, por
terminal, desde el portátil: exporta la configuración de producción y vuelve a
importarla con los secretos nuevos (`make tenant-push SLUG=<slug> SECRETS=<yaml>` exporta la
BD local e importa por SSH; para producción, prepara el directorio y usa
`tenant_config import - --secrets <yaml> --comment "Rotación de canal"` por `manage.sh`).
Ese YAML privado solo es una entrada de importación (slug → campos); se cifra al escribirlo
en BD y no se monta en el servidor.

Los secretos de plataforma se cambian en el `.env` de la VPS (0600, como `deploy`), recreando
`web`, `web-panel` y los cuatro workers (comando en
[despliegue.md](despliegue.md#cambiar-env-sin-desplegar)).

`FP_OWNER_PASSWORD`, `FP_APP_PASSWORD` y `FP_READONLY_PASSWORD` se rotan así, en la VPS como
`deploy`, en `/srv/autobot`: cambia solo la variable en `.env`, ejecuta
`deploy/scripts/ensure-env.sh` (vuelve a derivar `DB_*_URL`), aplica la contraseña al rol con
`deploy/scripts/compose.sh exec -T db bash /docker-entrypoint-initdb.d/init-roles.sh` y
recrea `web`, `web-panel` y los workers. Un `deploy.sh` del mismo SHA no basta: sale antes de ejecutar
`init-roles.sh`. No hay que editar las URL a mano.

Coordina el cambio
de webhook y la ventana de solape; prueba primero con `testers.main`.

**Bot de avisos (dueños):** `NOTIFY_BOT_TOKEN` y `NOTIFY_BOT_WEBHOOK_SECRET` (32
caracteres o más) van en el `.env` de la VPS. Tras cambiar cualquiera de los dos,
recrea `web`, `web-panel` y los cuatro workers (despliegue.md, arriba) y vuelve a registrar el webhook con
`make prod-manage CMD="telegram_set_webhook notify"`, que envía el secreto nuevo a Telegram. Hasta
entonces, las actualizaciones con el secreto antiguo se rechazan con 401 y Telegram las
reintenta. Comprueba que un "hola" al bot recibe el menú. Los vínculos de los dueños
(`owner_link`) no dependen de estos secretos y se conservan.

**Verificación:** `tenant_health` verde, firma nueva aceptada y antigua rechazada,
un mensaje de prueba responde una vez y no hay fallos de autenticación en el panel.

## Rotar la clave de cifrado de la base de datos

`SECRETS_ENCRYPTION_KEY` admite claves Fernet separadas por comas. La primera cifra;
todas pueden descifrar. La clave fija de desarrollo nunca se usa en producción.

1. Genera una clave con `cd apps/backend && uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
   y guárdala en el gestor de contraseñas, sin enviarla a logs ni a git.
2. En el `.env` del servidor, pon `SECRETS_ENCRYPTION_KEY=<nueva>,<anterior>`.
   La persona recrea `web`, `web-panel` y los cuatro workers para que reciban el nuevo
   entorno (en la VPS, como `deploy`: `deploy/scripts/compose.sh up -d --no-deps web
   web-panel worker-inbound worker-calendar worker-periodic worker-outbound`; ver [despliegue.md](despliegue.md#cambiar-env-sin-desplegar)).
3. La persona ejecuta `make prod-manage CMD=tenant_secrets_reencrypt` (desde el portátil).
   Recifra todas las filas de `tenant_secret` con la primera clave, en una transacción
   `owner`; cada cambio deja una auditoría `tenant.secrets` con `reencrypted: true`.
   Si alguna fila es ilegible, revierte toda la operación. Revisa las claves y repite.
4. Cuando termine correctamente, deja solo la nueva clave en `.env` y recrea `web`,
   `web-panel` y los cuatro workers. Comprueba la salud de los canales.
5. **Custodia de la clave (ADR-021).** El snapshot **no** lleva `SECRETS_ENCRYPTION_KEY`: la
   copia que guardas en tu gestor de contraseñas es la única fuera del servidor. Actualiza
   esa entrada **en cada rotación** y guarda también la anterior mientras existan backups
   que la necesiten (retención de restic: seis meses): al restaurar un snapshot hay que dar
   la clave con la que se cifraron sus secretos (varias, separadas por comas, si hace falta;
   ver [restaurar.md](restaurar.md)). Los backups antiguos no se recifran. Los snapshots
   anteriores al ADR-021 aún llevan la clave dentro hasta que caduquen; rotarla la deja
   inútil para los secretos cifrados después.

6. **Si falta la clave en el servidor (ADR-022).** Ni `deploy.sh` ni ninguna otra orden
   genera una clave nueva: si `.env` no la tiene, el despliegue aborta. Repón la entrada del
   gestor de contraseñas en `.env` (`SECRETS_ENCRYPTION_KEY=<clave>`) y vuelve a lanzar.
   Solo en un servidor nuevo y sin datos, `install-vm.sh` la genera en la primera
   instalación (o `deploy/scripts/ensure-env.sh --first-install`): guárdala en el gestor
   en ese momento.

Esto rota el cifrado en reposo; no cambia los tokens en Meta o Telegram. Antes del
primer despliegue, configura una clave propia y conserva `.env` junto con los backups.
