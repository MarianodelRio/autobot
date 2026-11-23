# Un negocio o canal no responde

## Síntoma

Otros negocios funcionan, pero uno no responde en su canal `main`. Alertas posibles: `tenant_unavailable`, `registry`, `errors:<canal>`, `auth`, `tenant_silent`, `webhook_unsubscribed`, `webhook_errors`, `number_quality`, `health:<codigo>` y `bot:<bot>:<codigo>`.

## Diagnóstico

1. Salud del negocio. En la VPS, como `deploy`, en `/srv/autobot` (o desde el portátil con `make prod-manage HOST=<host> CMD="tenant_health <slug>"`):

    ```bash
    deploy/scripts/manage.sh tenant_health <slug>
    ```

    Muestra los problemas detectados (`degraded`, `channel_disabled`, errores de webhook o plantillas).

2. Estado del negocio. Mira en la ficha del cliente del panel si figura `onboarding`, `paused`, `offboarded` o `degraded`. En `onboarding`, `main` solo acepta testers declarados.
3. Identidad del canal. Compara `public_id`, ids de canal y secretos con la configuración aprobada en la ficha del cliente. No muestres secretos en pantalla compartida ni tickets.
4. Si en vez de un negocio real falla el bot de demo, revisa sus variables `DEMO_TELEGRAM_*` / `DEMO_WHATSAPP_*` ([variables de entorno](../referencia/variables-entorno.md)) y las alertas `auth:<canal>` o `bot:demo_*`.

## Arreglo

1. Comprueba el webhook y los permisos del canal con la persona responsable.
2. Corrige la configuración desde el panel (ficha del cliente) o, en la VPS como `deploy`, con `tenant_config`:

    ```bash
    deploy/scripts/manage.sh tenant_config export <slug> <dir>
    deploy/scripts/manage.sh tenant_config import <dir> --comment "<motivo>"
    ```

    Los secretos se cargan con `tenant_config import --secrets <yaml>`. No hace falta desplegar.
3. Un tenant degradado no debe arrastrar a otros.

### Negocio en silencio

`tenant_silent`: un negocio activo no recibe mensajes desde hace más de lo habitual. Puede ser normal (vacaciones, cierre) o un canal roto. Comprueba primero `webhook_unsubscribed`, `webhook_errors` y `auth` del mismo negocio, y envía tú un mensaje de prueba al número o bot: si no aparece en la bandeja del panel, el problema está entre Meta/Telegram y nosotros. Si el negocio está cerrado, avisa a la persona responsable; la alerta se resuelve sola al llegar el siguiente mensaje.

### Webhook sin suscripción

`webhook_unsubscribed`: en WhatsApp, la app ya no está suscrita a la cuenta (Meta la desactiva si el webhook falla muchas veces o alguien la quitó). Repite la suscripción desde la pestaña «Alta» del panel («Comprobar» y después suscribir); es una acción sobre el canal real, necesita aprobación. En Telegram, vuelve a registrar el webhook desde el panel. `webhook_errors`: Telegram no consigue entregar; revisa que `PUBLIC_URL` y el proxy responden y mira [el bot no responde](bot-no-responde.md).

### Calidad del número

`number_quality`: Meta ha bajado la calidad (`YELLOW`) o restringido el número (`RED`, `RESTRICTED`...). Revisa en WhatsApp Manager el motivo (bloqueos o denuncias de clientes), reduce los mensajes proactivos y espera a que Meta la recupere; con 🔴 el envío puede estar limitado. No hay arreglo por nuestro lado.

!!! warning "Aprobación humana"
    Cambiar el webhook, rotar secretos o activar `main` necesita aprobación humana.

## Verificación

`tenant_health <slug>` no reporta problemas, un tester autorizado recibe respuesta y otro negocio sigue funcionando.

## Relacionado

- [Rotar secretos](../procedimientos/rotar-secretos.md), [alta y baja de un negocio](../procedimientos/alta-baja-negocio.md), [alta de WhatsApp en Meta](../procedimientos/alta-whatsapp-meta.md).
- [Config y registro](../arquitectura/config-y-registro.md), [canales](../arquitectura/canales.md), [alertas](../referencia/alertas.md).
