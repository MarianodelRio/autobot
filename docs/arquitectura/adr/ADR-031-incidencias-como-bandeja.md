# ADR-031 — Incidencias como bandeja: condición y evento, «Lo he revisado» y «Descartar»

**Estado:** aceptada; modifica el [ADR-026](ADR-026-conciliacion-de-envios-ambiguos.md) (retira la recuperación en bloque y añade «Descartar») y el [ADR-008](ADR-008-panel.md) (el bot de avisos ya no repite todo lo del panel)

## Contexto

La pantalla Incidencias juntaba tres listas que funcionaban cada una a su manera: alertas
abiertas, envíos `unknown`/`failed` sin ventana de tiempo (hasta 90 días) y trabajos
fallidos (30 días). Además estaban los avisos retenidos, una herramienta suelta de
reenvío en bloque y el historial. En el uso real (una persona operadora, pocos clientes,
avisos por Telegram) eso producía:

- **El mismo problema dos veces.** Un envío rechazado era una alerta (`outbound_failed`)
  y una fila; un trabajo fallido, una alerta (`failed_jobs`) y una fila; un dueño sin
  chat, `owner_unlinked` y «Avisos retenidos».
- **Alertas que no se podían cerrar.** Las que significan «pasó algo» (un envío
  rechazado, un trabajo que falló, el umbral de coste superado) seguían abiertas toda su
  ventana —24 h, o el mes entero en `billing`— aunque ya estuviera revisado, y el panel
  no dejaba cerrarlas (`Esta alerta se resuelve automáticamente`).
- **Listas que no se vaciaban.** Tras el primer `failed`, «Todo en orden» no volvía en
  meses. Un envío rechazado (p. ej. WhatsApp 131047, fuera de la ventana de 24 h) no
  tenía ninguna acción, solo el motivo de por qué no se podía marcar.
- **Ruido en Telegram.** Una alerta abierta se reenviaba cada 30 min (`COOLDOWN_S`).
- **Tres fórmulas** para «incidencias abiertas»: la pantalla, la barra lateral
  (`overview.incidents_open`) y el bot de avisos; y el Resumen subía a crítico con
  cualquier `failed` antiguo.
- **Un fallo**: el historial de resueltas se rompía con la severidad `info` de
  `deploy_ok` (`StatusBadge` no la conocía; la API la declaraba `str`).

## Decisión

- **Una unidad: la incidencia** (`ops_alert`, ampliada). Los envíos, trabajos y avisos
  afectados son **casos** dentro de su incidencia, calculados en vivo desde sus tablas
  (nunca copiados a `ops_alert`, que no tiene RLS). Una sola función de
  «incidencias abiertas» alimenta Incidencias, la barra lateral, el Resumen, el nivel de
  cada negocio y el menú/resumen diario del bot de avisos.
- **Dos naturalezas**, declaradas en un registro en el código por clave (o prefijo):
  - **Condición** («está mal ahora»: contenedor caído, disco, cola atrasada, webhook sin
    suscripción, proveedor caído, credencial rechazada, envíos ambiguos sin decidir…):
    se cierra sola cuando la causa desaparece, como hasta ahora.
  - **Evento** («pasó algo»: envío rechazado, aviso al dueño perdido, trabajo fallido,
    contenedor reiniciado, umbral de coste superado, despliegue abortado o revertido):
    la cierra la persona con **«Lo he revisado»**, que guarda una **marca de revisión**
    (fecha). Solo cuentan los casos posteriores a la marca; uno nuevo **reabre** la
    incidencia con «N nuevos desde tu revisión». Cada periodo abierto es una fila nueva
    que hereda la marca de la última revisión de la misma clave. La hora de un caso es cuándo
    se convirtió en fallo (`failed_at`, `unknown_at`), no cuándo se creó. Un evento con casos
    en tabla que se queda sin ninguno vivo se cierra solo como cierre de la plataforma
    (`auto`, sin tocar la marca).
- **Claves nuevas o divididas:** `outbound_failed` se divide en `outbound_rejected:<clase>`
  (evento, por negocio y clase de error) y `outbound_ambiguous` (condición, por negocio,
  mientras quede algún `unknown` sin decidir, sin límite de 24 h). `failed_jobs` pasa a
  `failed_job:<tarea>` (evento, una por tarea, con nombre en español). `billing`,
  `notification_failed`, `container_restarted:*`, `deploy_aborted` y `deploy_rollback`
  son eventos. `outbound_stuck` queda solo como condición (pendientes viejos sin
  trabajo).
- **Errores traducidos.** Cada adaptador de canal clasifica su error en una clase
  (las diferencias entre canales siguen en sus adaptadores, ADR-003) y `ops` da el texto
  en español y el consejo: p. ej. `outside_window` (WhatsApp 131047: solo con plantilla,
  reintentar no sirve), `undeliverable` (131026, número sin WhatsApp), `blocked`
  (Telegram 403), `auth`, `rate`, `other`. Se leen los dos formatos de WhatsApp (rechazo
  síncrono y `status failed` asíncrono).
- **Envíos ambiguos (`unknown`):** «Marcar enviado», «Reenviar» (se mantiene) y
  **«Descartar»**: nuevo estado final `discarded` (no se reenvía, la conciliación del
  ADR-026 ya no lo toca, no vuelve a salir). Un estado posterior del proveedor que
  confirme la entrega lo pasa a `sent` (es evidencia real). `outbound_resolve` gana
  `--discard`. **«Descartar todos»** en la incidencia `outbound_ambiguous` descarta de una vez
  todos los envíos sin decidir del negocio: se permite porque no envía nada (a diferencia del
  reenvío en bloque retirado); un solo registro de auditoría con el número.
- **Se retira la recuperación en bloque** (endpoints, acciones, pantalla): la persona
  operadora no la usa; solo queda «Descartar todos», que no envía nada. Los recordatorios caducados durante una caída no se reenvían.
- **Avisos por Telegram:** solo 🔴 y 🟠 avisan al abrirse; 🟡 queda en el panel y en el
  resumen diario. Cada apertura (condición o evento, también una reapertura) avisa como
  mucho una vez por hora por clave y negocio. Nada de repetir cada 30 min. Si la severidad
  sube dentro de una incidencia abierta, se actualiza y avisa: a 🔴 siempre (una crítica
  nunca espera), a 🟠 como mucho una vez por hora. `deploy_aborted` y `deploy_rollback` avisan en cada caso nuevo (cada
  despliegue fallido importa). «Resuelta» se sigue enviando para las críticas cuya apertura
  avisó. Las
  **entregas fallidas** se reintentan una vez por hora (sin contar como aviso nuevo),
  para que el latido `/fail` de healthchecks se recupere solo.
- **Demos igual que clientes** en severidad. Solo se excluyen las comprobaciones que no
  aplican a una demo (dueño sin chat, negocio en silencio, canal principal), como ya
  ocurría.
- **Severidad como tipo cerrado** (`critical`, `warning`, `notice`, `info`) en la API;
  el panel conoce `info` y muestra «Desconocido» ante cualquier otro valor en vez de
  romper la pantalla.
- **Envíos revisados** se consultan en la actividad del cliente (filtro «Envíos con
  error»: `failed`, `unknown`, `discarded`). Las cifras diarias dejan de contar `expired`
  como fallo (ADR-024).

## Alternativas consideradas

- **«Silenciar» con fecha de fin:** descartada por la persona operadora: prefiere ver lo
  que falla también durante un mantenimiento.
- **Marcar cada envío como revisado** (columna en `outbound_message`): una marca de
  revisión por incidencia basta para los eventos y no toca la tabla de datos de cliente.
- **«Descartar» como columna** (`discarded_at`) manteniendo `unknown`: obliga a añadir el
  filtro en la conciliación, el índice parcial, la alerta, las acciones, el panel y las
  cifras; un estado final propio lo excluye de todo lo que ya filtra por `unknown`.
- **Mantener el reenvío en bloque plegado:** no compensa mantener una herramienta que no
  se usa y que puede duplicar mensajes.
- **Recordatorio diario de las abiertas por Telegram:** el resumen diario ya las lista.

## Consecuencias

- La bandeja llega a cero: «Todo en orden» significa que no hay incidencias abiertas.
- Revisar un evento baja el nivel del negocio y del Resumen; un caso nuevo lo vuelve a
  subir.
- Migración que solo añade: campos en `ops_alert` (marca de revisión, recuento de
  casos, detalles sin datos personales) y el valor `discarded` (con `status` de 10
  caracteres) en `outbound_message`, y `failed_at` en `outbound_message` y `notification`
  (migración 0038); sin cambios de RLS ni de roles.
- Los 🟡 dejan de llegar por Telegram en el momento.
- La auditoría gana `incident.review`, `outbound.discard` y `outbound.discard_all`; `alert.resolve` y las de
  reenvío en bloque quedan como históricas.

## Cuándo revisarla

- Si opera más de una persona y hace falta «asignada a» o «en curso» antes de cerrar.
- Si los recordatorios perdidos en caídas pasan a importar a los clientes (volver a
  plantear un reenvío acotado y con plantilla).
- Si un tipo de evento reabre tan a menudo que el aviso horario molesta: agrupar más o
  convertirlo en condición con umbral.
