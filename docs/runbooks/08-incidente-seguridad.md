# 8. Incidente de seguridad o fuga de datos

**Síntoma:** acceso inesperado, token expuesto o datos personales fuera de su destino.
**Diagnóstico:** registra hora, alcance y sistemas afectados; conserva logs con acceso
restringido y evita publicar payloads o claves en tickets. Revisa accesos a GitHub,
VPS, GHCR, Meta, Telegram y Google según el indicio.

**Pasos:** la persona responsable decide contención y notificaciones. Si hay un token
comprometido, revócalo en el proveedor y sigue el runbook 9 con aprobación humana.
Bloquea la clave SSH afectada y prepara otra verificada antes de cerrar sesiones.
Si existe sospecha sobre datos de producción, ninguna acción de borrado o exportación
se ejecuta sin aprobación expresa; usa el runbook RGPD.

**Verificación:** credenciales antiguas rechazadas, nuevas credenciales operativas,
acceso revisado y cronología/decisiones documentadas fuera de logs públicos.
