# Pérdida total de la máquina

## Síntoma

La VPS no responde, el proveedor confirma su pérdida o hay que recuperarse en otra máquina sin acceso a la original.

## Diagnóstico

1. Confirma que no hay forma de recuperar la máquina original (reinicio, consola del proveedor) antes de tratar esto como pérdida total. Si solo necesitas más recursos en el mismo proveedor, no sigas este runbook. Para un traslado planificado, ver [traslado](../procedimientos/traslado.md).
2. Entiende qué se pierde. El backup es horario, así que el snapshot más reciente tiene como mucho una hora, pero no cero. Lo ocurrido entre el snapshot y la pérdida puede estar duplicado o ser irrecuperable:
    - Un mensaje de WhatsApp o Telegram recibido después del snapshot y ya respondido no queda registrado; al reentrar (reintento del canal o del cliente) puede generar una respuesta duplicada.
    - Una cita de `salon` creada o movida en Google Calendar después del snapshot **no tiene fila en la base restaurada**: el bot puede ofrecer ese hueco a otro cliente.
    - Un aviso al dueño o una alerta resuelta antes de la pérdida puede reabrirse sin nada nuevo que resolver.

## Arreglo

Los pasos de restauración están en [restauración y simulacro](../procedimientos/restaurar.md); no se repiten aquí.

1. En la máquina nueva, sigue [restaurar](../procedimientos/restaurar.md): `install-vm.sh --restore-target`, `restore.sh --confirm-empty-target` y la verificación de `/health` y conteos por tenant. `restore.sh` no arranca los workers por defecto.
2. **Antes de arrancar los workers**, revisa a mano por cada negocio activo:
    - El calendario de Google de cada tenant de `salon` frente a las citas que conoce la BD restaurada, en la ventana entre el snapshot y la pérdida. Una cita en Google sin fila necesita que alguien la dé de alta a mano ([comandos](../referencia/comandos.md)) o la elimine si ya no es válida.
    - Alertas (`ops_alert`) abiertas en el panel que ya se resolvieron antes de la pérdida: resuélvelas a mano si procede.
    - Mensajes sin confirmar en Meta o Telegram de antes de la pérdida: espera su reintento natural en vez de reenviar nada a mano ([efectos e idempotencia](../arquitectura/efectos-e-idempotencia.md)).
3. Arranca los workers. En la VPS nueva, como `deploy`, en `/srv/autobot` (`restore.sh` se niega a repetirse sobre un `var/.deployed-sha` ya restaurado):

    ```bash
    deploy/scripts/compose.sh up -d worker-inbound worker-calendar worker-periodic worker-outbound
    ```

    El bot vuelve a responder y `calendar_sweep` corre con lo que la revisión del paso 2 dejó corregido.
4. Si cambia la IP o el dominio, sigue los pasos de DNS y certificados del [traslado](../procedimientos/traslado.md) en lo que aplique.

!!! warning "Aprobación humana"
    Restaurar y corregir citas o alertas son acciones sobre datos de producción: requieren aprobación humana expresa.

## Verificación

Igual que un simulacro de [restauración](../procedimientos/restaurar.md): `/health` 200, conteos por tenant y un flujo por el bot de demo, más la revisión manual del paso 2 anotada (qué se encontró y qué se corrigió) antes de dar el incidente por cerrado.

## Relacionado

- [Restaurar](../procedimientos/restaurar.md), [servidor](../procedimientos/servidor.md), [calendar](calendar.md), [envíos unknown](envios-unknown.md).
