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
    deploy/scripts/compose.sh logs --tail=100 worker-periodic
    ```
5. Si fallan las respuestas de `salon` y no las de otros negocios, mira `worker-calendar` (cola `inbound_ext`):

    ```bash
    deploy/scripts/compose.sh logs --tail=100 worker-calendar
    ```

    Con Google caído o lento el comportamiento esperado es degradado, no atascado ([ADR-023](../arquitectura/adr/ADR-023-colas-aisladas-y-degradacion.md)): las llamadas fallan en pocos segundos (2 intentos de 2,5 s, dentro de un presupuesto de 8 s por mensaje); tras 5 fallos seguidos, o la mitad de las llamadas de 30 s fallando o lentas, un cortacircuitos hace fallar al instante (`Calendar circuit open`) y deja pasar una llamada de prueba cada 8 s; y la persona recibe «Ahora mismo no puedo completar tu consulta. Prueba de nuevo en unos minutos.» conservando su paso. Los negocios sin Calendar (`bus`) y los envíos no se ven afectados. Un error de cuota (429 o `quotaExceeded`) no se reintenta dentro del cliente.

## Caída general de Google

Si salta `calendar_outage` (🔴), Google Calendar falla en muchos negocios a la vez: no es un problema de cada calendario. Es la única alerta que se levanta (y la única que avisa al recuperarse): las alertas por negocio (`calendar:<canal>`, `health:<canal>:calendar_unavailable`, `errors:<canal>`) quedan agrupadas en ella. No hay que tocar ningún negocio.

1. Mira el estado de Google Workspace / Calendar API.
2. Los mensajes de `salon` reciben el texto de servicio degradado y los de `bus` no se ven afectados (ver diagnóstico, punto 5). Al volver Google, el cortacircuitos se cierra solo y la alerta se resuelve sola.
3. Si no se resuelve aunque Google funcione, comprueba que la cuenta de servicio no ha perdido acceso al proyecto (cuota, facturación, credenciales).

Un negocio suelto con `calendar:<canal>` mientras no hay `calendar_outage` sí es de ese negocio: sigue el diagnóstico de arriba.

## Arreglo

1. Si se retiró el acceso, el negocio vuelve a compartir el calendario con permiso para modificar eventos.
2. Para 429/5xx, espera: el cortacircuitos se cierra solo cuando Google vuelve a contestar. Si hay mensajes que recibieron el texto de servicio degradado, no hace falta reenviarlos: la persona repite su última acción. No repitas manualmente una creación cuyo resultado sea ambiguo ([efectos e idempotencia](../arquitectura/efectos-e-idempotencia.md)).
3. Para un hueco recién ocupado, el cliente debe recibir nuevas horas.
4. Si el error persiste, pausa el canal afectado por cambio de configuración (necesita aprobación humana) y avisa al negocio.

## Verificación

`tenant_health <slug>` no reporta `calendar_unavailable`. Para un negocio de demo, una reserva de prueba por cualquiera de sus puertas aparece una sola vez en su calendario.

## Relacionado

- [Pack `salon`](../referencia/packs/salon.md), [efectos e idempotencia](../arquitectura/efectos-e-idempotencia.md), [negocio o canal](negocio-o-canal.md), [alertas](../referencia/alertas.md).
