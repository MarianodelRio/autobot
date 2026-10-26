# 9. Rotar secretos de un canal

**Síntoma:** token caducado, revocado o potencialmente expuesto. **Diagnóstico:**
`tenant_health <slug>` indica autenticación; identifica si el secreto es de Meta,
Telegram, bot de pruebas, avisos u otra integración. La firma del webhook usa
`app_secret` o `webhook_secret`; cambiarla exige coordinación con el proveedor.

**Pasos:** con aprobación humana, genera el nuevo valor en el proveedor y guárdalo en
el gestor de contraseñas. Actualiza `secrets.yaml` o `.env` en la VPS como `deploy`,
modo 0600; reinicia solo `web` y `worker` si necesitan recargarlo. Coordina el cambio
de webhook y ventana de solape; prueba primero con `testers.main`. Nunca incluyas
valores en Git, argumentos de jobs, logs ni mensajes de revisión.

**Verificación:** `tenant_health` verde, firma nueva aceptada y antigua rechazada,
un mensaje de prueba responde una vez y no hay fallos de autenticación en el panel.
