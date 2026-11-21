# Envíos `unknown` o `failed`

## Síntoma

En el panel, Incidencias → Envíos sin confirmar muestra mensajes sin entrega confirmada, o salta `outbound_stuck`, `outbound_failed` (envíos fallidos o ambiguos desde hace más de 10 minutos) o `notification_failed` (avisos al dueño fallidos o ambiguos en 24 h). `unknown` puede significar que el proveedor aceptó el envío aunque la conexión se cortase.

## Diagnóstico

1. Busca el mensaje por su identificador interno en el panel y revisa estado, canal, intentos y `unknown_at`. El panel oculta payload, id del proveedor y último error por privacidad; muestra la elegibilidad y el motivo de cada acción.
2. Comprueba en el panel del proveedor (Meta, Telegram) o con el destinatario si el mensaje llegó.
3. `failed` es distinto de `unknown`: las acciones de resolución no admiten mensajes `failed`. Averigua su causa (canal, proveedor, credenciales) en [negocio o canal](negocio-o-canal.md).

## Arreglo

1. Si llegó y lleva más de diez minutos en `unknown`, usa «Marcar enviado» en el panel.
2. Si no llegó, lleva más de diez minutos en `unknown` y el payload y el canal siguen disponibles, usa «Reenviar» y confirma la posibilidad de duplicado.
3. Si el panel no es accesible, en la VPS como `deploy`, en `/srv/autobot`:

    ```bash
    deploy/scripts/manage.sh outbound_resolve <id> --mark-sent --confirm
    deploy/scripts/manage.sh outbound_resolve <id> --resend --confirm
    ```

    Sin `--confirm` el comando explica el riesgo y no hace nada. Desde el portátil: `make prod-manage HOST=<host> CMD="outbound_resolve <id> --mark-sent --confirm"`.
4. Para un `failed` permanente: queda registrado; corrige la causa para envíos futuros y comprueba con un **nuevo envío autorizado** que el canal funciona.

!!! warning "Prohibido"
    No reencoles el envío anterior, no edites filas SQL ni crees otra clave de idempotencia para el mismo efecto. Reenviar es una acción sobre datos de producción: requiere aprobación humana.

## Verificación

- `unknown`: el mensaje queda en `sent` o tiene una nueva entrega confirmada, y Logs, pestaña Operador, registra la resolución.
- `failed`: el registro permanece en ese estado y el nuevo envío autorizado confirma que la causa se corrigió.
- No se crearon duplicados.

## Relacionado

- Por qué no se reintenta a ciegas y cómo se garantiza la idempotencia: [efectos e idempotencia](../arquitectura/efectos-e-idempotencia.md).
- [Cola y latido](cola-y-latido.md), [alertas](../referencia/alertas.md).
