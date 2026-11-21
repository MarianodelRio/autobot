# Un negocio o canal no responde

## Síntoma

Otros negocios funcionan, pero uno no responde en su canal `main`. Alertas posibles: `tenant_unavailable`, `registry`, `errors:<canal>`, `auth`, `health:<codigo>` y `bot:<bot>:<codigo>`.

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

!!! warning "Aprobación humana"
    Cambiar el webhook, rotar secretos o activar `main` necesita aprobación humana.

## Verificación

`tenant_health <slug>` no reporta problemas, un tester autorizado recibe respuesta y otro negocio sigue funcionando.

## Relacionado

- [Rotar secretos](../procedimientos/rotar-secretos.md), [alta y baja de un negocio](../procedimientos/alta-baja-negocio.md), [alta de WhatsApp en Meta](../procedimientos/alta-whatsapp-meta.md).
- [Config y registro](../arquitectura/config-y-registro.md), [canales](../arquitectura/canales.md), [alertas](../referencia/alertas.md).
