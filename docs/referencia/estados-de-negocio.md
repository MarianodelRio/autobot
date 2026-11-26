# Estados de negocio

Cómo calcula el panel el nivel de salud de un negocio (`ok`, `notice`, `warning`, `critical`
o `unknown`) y qué lo provoca. Léelo cuando una tarjeta de cliente aparezca en ámbar o rojo.
No confundir con el **estado del ciclo de vida** del negocio (`onboarding`, `active`,
`paused`, `offboarded`), que cambia la persona con `tenant_status`.

La regla está en `apps/backend/src/autobot/ops/status.py` (`tenant_status`). Reúne motivos de
tres fuentes y se queda con el nivel más grave.

## Qué los dispara

| Fuente | Motivo | Nivel |
|---|---|---|
| Registro | La configuración del negocio está degradada. | `critical` |
| Registro | El negocio está `active`, no es demo y su canal principal está desactivado. | `critical` |
| Instantánea de salud | Cada problema de la última comprobación diaria ([alertas](alertas.md)), según su emoji: 🔴, 🟠 o 🟡. | `critical`, `warning` o `notice` |
| Incidencias abiertas del negocio | Cada incidencia abierta del negocio ([alertas](alertas.md), `ops.incidents.open_incidents`, la misma lista que Incidencias), con su título como motivo. Una 🟡 lo deja en `notice`, nunca más alto. Un evento revisado deja de contar; un caso nuevo lo reabre y vuelve a contar. | el de su severidad (`critical`, `warning` o `notice`) |

Orden de gravedad: `critical`, `warning`, `notice`. Se devuelve el primero que tenga motivos
y la lista de motivos sin repetir.

## Cuando no hay motivos

- `ok`: no hay motivos y la última comprobación de salud tiene menos de 24 horas.
- `unknown`: no hay motivos, pero no existe instantánea de salud o tiene más de 24 horas
  («La comprobación de salud falta o tiene más de 24 horas»). No significa que algo falle:
  significa que no se sabe. `tenant_health <slug>` fuerza una comprobación.

Un negocio con motivos nunca es `unknown`: el problema detectado manda.

## Dónde está el código

- `apps/backend/src/autobot/ops/status.py` (`tenant_status`, `TenantStatus`).
- `apps/backend/src/autobot/ops/health.py` (`read_snapshot`): la instantánea que se lee.

## Relacionado

[Alertas](alertas.md), [observabilidad](../arquitectura/observabilidad.md),
[un negocio o canal no responde](../incidencias/negocio-o-canal.md).
