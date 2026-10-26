# 6. Restauración y simulacro trimestral

**Síntoma:** pérdida de datos/servidor o fecha de simulacro. **Diagnóstico:** comprueba
en restic el último snapshot con tag `flowpilot`, su fecha y el ping del backup.
Revisa que dispones de la contraseña y las credenciales S3 fuera del repositorio.
No restaures sobre una instalación con volumen de BD existente.

**Pasos:** prepara una VPS temporal o un proyecto local aislado, instala Docker y
restic, clona el SHA que contenga `deploy/restore.sh`, y crea `backup.env` y
`restic-password` como `deploy` con modo 0600. Ejecuta
`deploy/restore.sh --confirm-empty-target`. Si falla tras crear el volumen, conserva
`.restore-incomplete` y vuelve a ejecutar el mismo comando tras arreglar la causa;
el script solo admite ese reintento controlado. Si el snapshot era inválido y aún no
se creó volumen, corrige la fuente antes de repetir. No apuntes DNS hasta verificar.
Para prueba puramente local ejecuta `make restore-test` con Docker y restic; crea
dos proyectos temporales y compara conteos por tenant.

**Verificación:** `/health` responde 200, compara por tenant los conteos de `contact`,
`inbound_event` y `outbound_message` con el origen o informe previo; comprueba un
flujo por el bot de demo. Anota SHA, snapshot, hora de inicio/fin y duración; la
meta es menos de dos horas. Borra la VPS temporal tras el simulacro autorizado.
