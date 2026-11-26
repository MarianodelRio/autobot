# Incidente de seguridad o fuga de datos

## Síntoma

Acceso inesperado, token expuesto o datos personales fuera de su destino. No hay alerta automática específica: lo detecta una persona o un proveedor.

## Diagnóstico

1. Registra hora, alcance y sistemas afectados.
2. Conserva los logs con acceso restringido; no publiques payloads ni claves en tickets.
3. Revisa accesos a GitHub, VPS, GHCR, Meta, Telegram y Google según el indicio.

## Si hay datos personales afectados

Avisa al negocio afectado cuanto antes: hay **72 horas** desde que se sabe para notificarlo a la AEPD si hay riesgo para las personas. Anota esa hora en el paso 1.

## Arreglo

1. La persona responsable decide contención y notificaciones.
2. Si hay un token comprometido, revócalo en el proveedor y sigue [rotar secretos](../procedimientos/rotar-secretos.md).
3. Bloquea la clave SSH afectada y prepara otra verificada antes de cerrar sesiones.
4. Si hay sospecha sobre datos de producción, ninguna acción de borrado o exportación se ejecuta sin aprobación expresa; usa [retención y borrado de datos](../procedimientos/retencion-rgpd.md).

!!! warning "Aprobación humana"
    Rotar secretos, borrar o exportar datos y tocar el servidor de producción requieren aprobación humana explícita.

## Portátil perdido o cuenta de GitHub comprometida

El portátil de la persona que opera guarda la clave SSH de `deploy` y `admin`, la sesión de `gh` (que puede lanzar y aprobar despliegues), la credencial de purga de los backups (la única que puede borrar snapshots) y, si están abiertas, las sesiones del gestor de contraseñas y de Telegram. El panel necesita además el túnel SSH, la contraseña y el TOTP. Desde otra máquina de confianza, por este orden:

1. **Gestor de contraseñas:** cambia la contraseña maestra y cierra la sesión del portátil. Todo lo demás se recupera desde ahí.
2. **GitHub:** cambia la contraseña, cierra las sesiones, revoca los tokens (`gh`, PAT) y las claves SSH de la cuenta. Revisa los últimos pushes a `main`, las ejecuciones de `Deploy` y sus aprobaciones, y que el ruleset de `main` y el entorno `production` siguen como estaban. Si hubo un despliegue que no lanzaste: [volver atrás](volver-atras.md).
3. **SSH del servidor:** con una clave nueva, desde la consola del proveedor si hace falta, sustituye la clave antigua en `authorized_keys` de `admin` y `deploy`. La clave de CI es otra y solo admite `deploy.sh <sha>`: rótala si los secretos de GitHub pudieron leerse ([servidor](../procedimientos/servidor.md#pasos), paso 5).
4. **Backups:** desactiva la credencial de purga en el proveedor y crea otra. El versionado del bucket conserva 30 días lo que se borrara: comprueba los snapshots con `restic snapshots` antes de purgar nada ([backups](../procedimientos/backups.md)).
5. **Panel:** cambia la contraseña del operador y, si el TOTP estaba en el portátil, emite uno nuevo ([panel](../procedimientos/panel.md#alta-del-operador)).
6. **Telegram, Meta, Google y el proveedor de la VPS:** cierra las sesiones del portátil. Rota cualquier secreto de producción que estuviera en claro en el portátil ([rotar secretos](../procedimientos/rotar-secretos.md)).

## Verificación

Credenciales antiguas rechazadas, nuevas credenciales operativas, acceso revisado y cronología y decisiones documentadas fuera de logs públicos.

## Relacionado

- [Rotar secretos](../procedimientos/rotar-secretos.md), [retención y borrado de datos](../procedimientos/retencion-rgpd.md), [seguridad y secretos](../arquitectura/seguridad-y-secretos.md).
