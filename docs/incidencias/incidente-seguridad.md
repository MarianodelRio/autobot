# Incidente de seguridad o fuga de datos

## Síntoma

Acceso inesperado, token expuesto o datos personales fuera de su destino. No hay alerta automática específica: lo detecta una persona o un proveedor.

## Diagnóstico

1. Registra hora, alcance y sistemas afectados.
2. Conserva los logs con acceso restringido; no publiques payloads ni claves en tickets.
3. Revisa accesos a GitHub, VPS, GHCR, Meta, Telegram y Google según el indicio.

## Parte RGPD: plazos que corren desde que lo sabes

Si hay datos personales afectados, es una violación de la seguridad en el sentido del RGPD y **corren plazos legales desde el momento en que se tiene conocimiento**: anota esa hora en el paso 1.

- **Avisar al negocio afectado sin dilación y, por contrato, en 48 horas como máximo** (la plataforma es encargada de los datos de sus clientes).
- **El negocio (responsable) notifica a la AEPD en 72 horas** por la sede electrónica, si hay riesgo para las personas; si los datos son de la propia plataforma (demo, dueños, operadores), la notifica la plataforma.
- Comunicar a los afectados si el riesgo es alto, y **registrar la brecha** aunque no se notifique.

Procedimiento completo, plantillas y registro interno en [Brechas de seguridad](../cumplimiento/brechas-de-seguridad.md).

## Arreglo

1. La persona responsable decide contención y notificaciones.
2. Si hay un token comprometido, revócalo en el proveedor y sigue [rotar secretos](../procedimientos/rotar-secretos.md).
3. Bloquea la clave SSH afectada y prepara otra verificada antes de cerrar sesiones.
4. Si hay sospecha sobre datos de producción, ninguna acción de borrado o exportación se ejecuta sin aprobación expresa; usa [retención y derechos de datos](../procedimientos/retencion-rgpd.md).

!!! warning "Aprobación humana"
    Rotar secretos, borrar o exportar datos y tocar el servidor de producción requieren aprobación humana explícita.

## Verificación

Credenciales antiguas rechazadas, nuevas credenciales operativas, acceso revisado y cronología y decisiones documentadas fuera de logs públicos.

## Relacionado

- [Brechas de seguridad (RGPD, plazo de 72 h)](../cumplimiento/brechas-de-seguridad.md), [rotar secretos](../procedimientos/rotar-secretos.md), [retención y derechos de datos](../procedimientos/retencion-rgpd.md), [seguridad y secretos](../arquitectura/seguridad-y-secretos.md).
