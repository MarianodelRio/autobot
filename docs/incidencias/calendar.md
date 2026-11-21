# Google Calendar sin acceso o con errores

## Síntoma

El pack `salon` no muestra huecos, no crea citas, o el panel muestra `calendar:<canal>` (Calendar sin acceso o con tres errores seguidos) o `sweep:<canal>` (el barrido de calendario no se completa desde hace más de una hora).

## Diagnóstico

1. Salud del negocio. En la VPS, como `deploy`, en `/srv/autobot` (o `make prod-manage HOST=<host> CMD="tenant_health <slug>"` desde el portátil):

    ```bash
    deploy/scripts/manage.sh tenant_health <slug>
    ```

    `<canal>:calendar_unavailable` indica fallo de Calendar sin distinguir causa.
2. Verifica que el calendario está compartido con la cuenta de servicio: el real del negocio en `main`, o el único calendario de un negocio de demo, usado por sus puertas.
3. Consulta permisos y estado de Google para separar falta de acceso de errores transitorios. No copies el JSON de credenciales.
4. Si solo salta `sweep:<canal>`, mira los logs del worker periódico:

    ```bash
    deploy/scripts/compose.sh logs --tail=100 worker-outbound
    ```

## Arreglo

1. Si se retiró el acceso, el negocio vuelve a compartir el calendario con permiso para modificar eventos.
2. Para 429/5xx, espera y observa el reintento normal. No repitas manualmente una creación cuyo resultado sea ambiguo ([efectos e idempotencia](../arquitectura/efectos-e-idempotencia.md)).
3. Para un hueco recién ocupado, el cliente debe recibir nuevas horas.
4. Si el error persiste, pausa el canal afectado por cambio de configuración (necesita aprobación humana) y avisa al negocio.

## Verificación

`tenant_health <slug>` no reporta `calendar_unavailable`. Para un negocio de demo, una reserva de prueba por cualquiera de sus puertas aparece una sola vez en su calendario.

## Relacionado

- [Pack `salon`](../referencia/packs/salon.md), [efectos e idempotencia](../arquitectura/efectos-e-idempotencia.md), [negocio o canal](negocio-o-canal.md), [alertas](../referencia/alertas.md).
