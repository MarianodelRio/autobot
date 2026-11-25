# Envíos `unknown` o `failed`

## Síntoma

En el panel, Incidencias muestra mensajes sin entrega confirmada, o salta `outbound_stuck`, `outbound_failed` (envíos fallidos o ambiguos desde hace más de 10 minutos) o `notification_failed` (avisos al dueño fallidos, ambiguos o caducados en 24 h). `unknown` puede significar que el proveedor aceptó el envío aunque la conexión se cortase.

Antes de que intervenga una persona, la plataforma concilia sola ([ADR-026](../arquitectura/adr/ADR-026-conciliacion-de-envios-ambiguos.md)): un estado de entrega de Meta lo pasa a `sent` y, si a los 10 minutos no hay evidencia, `reconcile_unknown` lo **reenvía una sola vez** (respuestas, menús, disculpas y recordatorios; un duplicado es inocuo). Si el reenvío vuelve a ser ambiguo, o es una clase que no admite duplicados, se queda `unknown` y salta `outbound_failed` a los 20 minutos: ahí sí decide una persona.

## Diagnóstico

1. Busca el mensaje por su identificador interno en el panel y revisa estado, canal, intentos, `unknown_at` y el último error (solo estado y códigos del proveedor, nunca el cuerpo de su respuesta). El panel oculta el contenido y el id del proveedor por privacidad; muestra la elegibilidad y el motivo de cada acción. Cada adaptador traduce el error a una clase con su consejo en español (`ops/send_errors.py`): `outside_window` (WhatsApp 131047: fuera de la ventana de 24 h, solo con plantilla), `undeliverable` (número no válido o sin WhatsApp), `blocked` (la persona bloqueó el bot), `auth` (credencial rechazada), `rate` (límite del proveedor; se reintenta solo), `marketing_declined`, `spam_limit` y `other` (con el código).
2. Comprueba en el panel del proveedor (Meta, Telegram) o con el destinatario si el mensaje llegó.
3. `expired` no es un fallo: el mensaje pasó su plazo (30 minutos una respuesta, hasta 24 h un recordatorio) sin que el proveedor lo aceptara y no se envió. No hay nada que resolver; una respuesta caducada ya generó su disculpa. Si hay muchos a la vez, es una caída del proveedor: ver [caída de un proveedor](#caida-de-un-proveedor).
4. `failed` es distinto de `unknown`: las acciones de resolución no admiten mensajes `failed`. Averigua su causa (canal, proveedor, credenciales) en [negocio o canal](negocio-o-canal.md).

## Arreglo

1. **Marcar enviado**, si llegó y lleva más de diez minutos en `unknown`: da por buena la entrega y pasa a `sent`.
2. **Reenviar**, si no llegó, lleva más de diez minutos en `unknown` y el payload y el canal siguen disponibles: confirma la posibilidad de duplicado.
3. **Descartar**, si no hay que enviarlo ni confirmarlo (el momento ya pasó, o no se puede saber y no compensa el riesgo de duplicado): sin espera mínima, pasa al estado final `discarded` (deja de salir en Incidencias, no se reenvía y la conciliación lo ignora; no cuenta como fallo). Queda auditado (`outbound.discard`). Si más tarde llega un estado de entrega que demuestre que sí salió, pasa a `sent`. Se consulta después en la actividad del negocio, filtrando por los envíos con error.
4. Si el panel no es accesible, en la VPS como `deploy`, en `/srv/autobot`:

    ```bash
    deploy/scripts/manage.sh outbound_resolve <id> --mark-sent --confirm
    deploy/scripts/manage.sh outbound_resolve <id> --resend --confirm
    deploy/scripts/manage.sh outbound_resolve <id> --discard --confirm
    ```

    Sin `--confirm` el comando explica el riesgo y no hace nada. Desde el portátil: `make prod-manage HOST=<host> CMD="outbound_resolve <id> --mark-sent --confirm"`.
5. Para un `failed` permanente: queda registrado; corrige la causa para envíos futuros y comprueba con un **nuevo envío autorizado** que el canal funciona.

!!! warning "Prohibido"
    No reencoles el envío anterior, no edites filas SQL ni crees otra clave de idempotencia para el mismo efecto. Reenviar es una acción sobre datos de producción: requiere aprobación humana.

## Caída de un proveedor

Si salta `provider_outage` (🟠), Meta o Telegram no responden. No hay que hacer nada con cada mensaje: se reintentan solos, con espera de hasta 5 minutos, mientras no caduquen (una respuesta, a los 30 minutos; un recordatorio, hasta 24 h o 30 minutos antes de la cita). Mientras el cortacircuitos está abierto no se llama al proveedor: una sonda de solo lectura cada minuto detecta la recuperación y lo cierra. Los mensajes en espera no vuelven todos a la vez: cada uno suma una espera aleatoria (una respuesta, de 0 a 30 s; un recordatorio, de 15 a 90 s) y las respuestas tienen prioridad en la cola sobre los recordatorios. Durante la caída, y 20 minutos después, no saltan las alertas `health:whatsapp_unavailable` / `health:telegram_unavailable` de cada negocio: solo `provider_outage`.

1. Comprueba el estado del proveedor (página de estado de Meta o de Telegram).
2. Al recuperarse, los envíos pendientes salen solos y la alerta se resuelve sola. Las respuestas caducadas se sustituyen por una disculpa por contacto (como mucho una cada 6 horas) y quedan `expired`.
3. Los recordatorios `expired` cuya cita sigue por delante los revive el siguiente barrido del calendario (`calendar_sweep`), sin intervención.
4. Si la alerta no se resuelve aunque el proveedor funcione, mira los logs de `worker-outbound` (`provider … breaker opened/closed`) y recuerda que reiniciar ese worker deja el cortacircuitos cerrado.

## Avisos retenidos

Si el dueño de un negocio no ha conectado su chat de avisos, los avisos quedan `held` (no `failed`), en Incidencias aparece «Avisos retenidos» y, si es un negocio real y activo, salta `owner_unlinked` (🟡). Genera un enlace de invitación en la ficha del negocio y pide al dueño que lo abra: al conectar, los avisos de menos de 2 horas salen solos y los más viejos caducan. No hay que resolver nada a mano.

## Verificación

- `unknown`: el mensaje queda en `sent` o tiene una nueva entrega confirmada, y Logs, pestaña Operador, registra la resolución.
- `failed`: el registro permanece en ese estado y el nuevo envío autorizado confirma que la causa se corrigió.
- No se crearon duplicados.

## Relacionado

- Por qué no se reintenta a ciegas y cómo se garantiza la idempotencia: [efectos e idempotencia](../arquitectura/efectos-e-idempotencia.md).
- [Cola y latido](cola-y-latido.md), [alertas](../referencia/alertas.md).
