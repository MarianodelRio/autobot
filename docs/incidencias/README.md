# Incidencias

Runbooks para cuando algo falla en producción. Cada uno sigue la [plantilla](plantilla.md): síntoma, diagnóstico, arreglo, verificación y relacionado. Empieza por el síntoma que ves.

!!! warning "Producción"
    Cualquier acción sobre datos de producción requiere aprobación humana explícita. Ningún agente ejecuta comandos contra el servidor de producción.

## Por síntoma

| Síntoma | Runbook |
| --- | --- |
| Ningún negocio responde; `/health` falla o da 502/503 | [El bot no responde a nadie](bot-no-responde.md) |
| Un negocio concreto no responde, otros sí | [Un negocio o canal no responde](negocio-o-canal.md) |
| La cola crece, falta el latido o hay trabajos fallidos | [Cola acumulada o latido ausente](cola-y-latido.md) |
| Un contenedor está caído, reiniciándose o con otra imagen | [Contenedor caído](contenedor-caido.md) |
| `salon` no ofrece huecos o no crea citas | [Google Calendar](calendar.md) |
| Mensajes sin entrega confirmada (`unknown` o `failed`) | [Envíos `unknown` o `failed`](envios-unknown.md) |
| Un despliegue nuevo rompe algo | [Volver atrás un despliegue](volver-atras.md) |
| La VPS no responde y no se recupera | [Pérdida total de la máquina](perdida-total.md) |
| Acceso inesperado, token expuesto, fuga de datos | [Incidente de seguridad](incidente-seguridad.md) |

## Por alerta del panel

Las alertas se guardan en `ops_alert` (`apps/backend/src/autobot/ops/check.py`, `collect()` y `sync_alerts()`; las de contenedores, en `apps/backend/src/autobot/ops/containers.py`). La clave es el `kind`; los sufijos `<canal>`, `<servicio>`, `<codigo>` y `<bot>` varían. El catálogo completo, con severidad y causa, está en [alertas](../referencia/alertas.md).

| Alerta (`kind`) | Runbook |
| --- | --- |
| `inbound_delay`, `failed_jobs`, `inbound_stuck` | [cola-y-latido](cola-y-latido.md) |
| `outbound_stuck`, `outbound_failed`, `notification_failed` | [envios-unknown](envios-unknown.md) |
| `registry`, `tenant_unavailable`, `errors:<canal>`, `health:<codigo>` | [negocio-o-canal](negocio-o-canal.md) |
| `auth`, `auth:<canal>`, `bot:notify:auth` | [negocio-o-canal](negocio-o-canal.md) y [rotar secretos](../procedimientos/rotar-secretos.md) |
| `bot:<bot>:<codigo>` (`demo_tg`, `notify`, `demo_wa`) | [negocio-o-canal](negocio-o-canal.md) |
| `calendar:<canal>`, `sweep:<canal>` | [calendar](calendar.md) |
| `container_down:<servicio>`, `container_unhealthy:<servicio>`, `container_restarted:<servicio>`, `container_image:<servicio>`, `container_unexpected:<servicio>`, `containers_stale` | [contenedor-caido](contenedor-caido.md) |
| `containers_restore` | [restauración](../procedimientos/restaurar.md) |
| `deploy_aborted`, `deploy_rollback` | [volver-atras](volver-atras.md) |
| `disk`, `disk_critical` | [Disco lleno](../procedimientos/mantenimiento.md#disco-lleno) |
| `billing`, `billing:demo_wa` | Sin runbook: umbral de mensajes facturables; ver [alta y baja de un negocio](../procedimientos/alta-baja-negocio.md) |
| Aviso de healthchecks.io (latido) | [cola-y-latido](cola-y-latido.md) |

## Relacionado

- [Alertas](../referencia/alertas.md), [cola y workers](../arquitectura/cola-y-workers.md), [efectos e idempotencia](../arquitectura/efectos-e-idempotencia.md).
- [Restauración](../procedimientos/restaurar.md) y [servidor](../procedimientos/servidor.md).
