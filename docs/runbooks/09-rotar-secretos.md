# 9. Rotar secretos de un canal

**Síntoma:** token caducado, revocado o potencialmente expuesto. **Diagnóstico:**
`tenant_health <slug>` indica autenticación; identifica si el secreto es de Meta,
Telegram, bot de demo, avisos u otra integración. La firma del webhook usa
`app_secret` o `webhook_secret`; cambiarla exige coordinación con el proveedor.

**Pasos:** con aprobación humana, genera el nuevo valor en el proveedor y guárdalo en
el gestor de contraseñas. Actualiza `secrets.yaml` o `.env` en la VPS como `deploy`,
modo 0600; reinicia solo `web` y `worker` si necesitan recargarlo. Coordina el cambio
de webhook y ventana de solape; prueba primero con `testers.main`. Nunca incluyas
valores en Git, argumentos de jobs, logs ni mensajes de revisión.

**Bot de avisos (dueños):** `NOTIFY_BOT_TOKEN` y `NOTIFY_BOT_WEBHOOK_SECRET` (32
caracteres o más) van en el `.env` de la VPS. Tras cambiar cualquiera de los dos,
reinicia `web` y `worker` y vuelve a registrar el webhook con
`manage.py telegram_set_webhook notify`, que envía el secreto nuevo a Telegram. Hasta
entonces, las actualizaciones con el secreto antiguo se rechazan con 401 y Telegram las
reintenta. Comprueba que un "hola" al bot recibe el menú. Los vínculos de los dueños
(`owner_link`) no dependen de estos secretos y se conservan.

**Verificación:** `tenant_health` verde, firma nueva aceptada y antigua rechazada,
un mensaje de prueba responde una vez y no hay fallos de autenticación en el panel.

## Rotar la clave de cifrado de la base de datos

`SECRETS_ENCRYPTION_KEY` admite claves Fernet separadas por comas. La primera cifra;
todas pueden descifrar. La clave fija de desarrollo nunca se usa en producción.

1. Genera una clave con `uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
   y guárdala en el gestor de contraseñas, sin enviarla a logs ni a git.
2. En el `.env` del servidor, pon `SECRETS_ENCRYPTION_KEY=<nueva>,<anterior>`.
   La persona recrea `web` y `worker` para que reciban el nuevo entorno.
3. La persona ejecuta `docker compose -p autobot -f compose.prod.yaml exec -T web python manage.py tenant_secrets_reencrypt`.
   Recifra todas las filas de `tenant_secret` con la primera clave, en una transacción
   `owner`; cada cambio deja una auditoría `tenant.secrets` con `reencrypted: true`.
   Si alguna fila es ilegible, revierte toda la operación. Revisa las claves y repite.
4. Cuando termine correctamente, deja solo la nueva clave en `.env` y recrea ambos
   servicios. Comprueba la salud de los canales.
5. Guarda la clave anterior cifrada fuera del servidor mientras existan backups que la
   necesiten (retención de restic: seis meses). Los backups antiguos no se recifran;
   restaurarlos requiere las claves con las que se generaron.

Esto rota el cifrado en reposo; no cambia los tokens en Meta o Telegram. Antes del
primer despliegue, configura una clave propia y conserva `.env` junto con los backups.
