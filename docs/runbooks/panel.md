# Panel interno

Todavía no hay interfaz web: el Django Admin se eliminó (ADR-008) y el panel que lo
sustituye se implementa en tareas posteriores (`docs/panel/IMPLEMENTATION.md`). Por
ahora la operación se hace por los comandos de `manage.py` (`docs/comandos.md`):

- **Envíos ambiguos o fallidos** (runbook 05): `outbound_resolve <id> (--mark-sent|--resend)
  --confirm`.
- **Trabajos fallidos** (runbook 03): `job_retry <id>`.

Ambos comandos llaman a `autobot.ops.actions`, que comprueba la elegibilidad bajo
bloqueo y audita el cambio (`audit_event`) en la misma transacción. El alta del
operador del panel (usuario, contraseña y TOTP) se completa en T14
(`docs/panel/IMPLEMENTATION.md`); hasta entonces no hay sesión ni acceso web alguno,
solo `ssh` y `manage.py` contra el servidor.
