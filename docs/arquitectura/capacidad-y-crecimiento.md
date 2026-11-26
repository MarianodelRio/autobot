# Capacidad y crecimiento

Esta página reúne lo que se sabe de la capacidad de la plataforma, medido en pruebas de carga y de fallos (noviembre de 2026), y el plan para crecer: qué limita en cada etapa, qué señales indican que toca dar el siguiente paso y qué habrá que cambiar entonces. Léela antes de dimensionar el servidor, de decidir un cambio de proveedor o de abordar una mejora de escalabilidad.

## En resumen

- **Capacidad medida hoy:** unos 14 mensajes por segundo sostenidos con p95 de 4,3 s, en una máquina de 2 núcleos (la mitad de la objetivo). Con el tráfico de la prueba (unas 300 conversaciones al mes por negocio, con picos) son unos 500-700 negocios.
- **Para planificar:** una VPS de 4 vCPU y 8 GB atiende **400-500 negocios con margen**. Por encima, el primer límite es `worker-outbound`, no la máquina.
- **Ya hecho** (para llegar a 50 negocios sin sustos): cuatro workers y cola aislada para los packs con calendario ([ADR-023](adr/ADR-023-colas-aisladas-y-degradacion.md)), envíos por caducidad que aguantan caídas de horas de Meta o Telegram ([ADR-024](adr/ADR-024-envio-saliente-por-caducidad.md)), conciliación de envíos ambiguos ([ADR-026](adr/ADR-026-conciliacion-de-envios-ambiguos.md)), clave de cifrado que nunca se regenera sola ([ADR-022](adr/ADR-022-la-clave-de-cifrado-nunca-se-genera-sola.md)), libro de supresiones y purga vigilados ([ADR-025](adr/ADR-025-libro-de-supresiones-y-purga-vigilados.md)), alertas de negocio en silencio, de webhook y de colas con retraso, recarga del registro sin bloqueo, `redact()` independiente del número de negocios y panel paginado.
- **Cómo crecer:** se decide con las señales de [Cuándo dar el siguiente paso](#cuando-dar-el-siguiente-paso), no por número de negocios; el orden de las mejoras está en [Mejoras futuras](#mejoras-futuras).

## Cómo se midió

- Una copia de la pila de producción en local (misma configuración de `web`, workers y PostgreSQL 18), con negocios sintéticos de los dos packs (`salon` y `bus`) y simuladores de Meta, Telegram y Google Calendar con latencias realistas. Nunca datos ni APIs reales.
- Primera ronda: máquina de 4 CPU y 7 GB, con el generador de carga en un núcleo aparte. Segunda ronda: i3-7020U de 2 núcleos y 4 hilos con 7,8 GB y el generador en la misma máquina (más desfavorable). Cada escenario dura 7 minutos con un tráfico por negocio de unas 300 conversaciones al mes, con picos.
- Escenarios: carga base, ráfaga viral, cambio de configuración, despliegue, Google degradado, caída de Meta (minutos a 12 h), tormentas de 429, 5xx sin cuerpo, `kill -9` de un worker, ráfagas de avisos al dueño.
- Las cifras de la segunda ronda son pesimistas: el generador de carga, los simuladores y la plataforma comparten dos núcleos.

### Cómo repetir la prueba

El arnés no vive en el repo (es desechable); para repetirla basta con montar lo mismo:

1. Un PostgreSQL 18 propio, **nunca la base de desarrollo**, con los `-c` de `compose.prod.yaml`, migraciones como `fp_owner` y `manage.py apply_grants`.
2. `web`, `web-panel` y los cuatro workers en el host con los mismos comandos, colas, concurrencias, `WORKER_DB_POOL_MAX` y `PYTHON_CPU_COUNT` que `compose.prod.yaml`.
3. Simuladores locales de Meta Graph, Telegram Bot API y Google Calendar (latencias de 80-300 ms, modo degradado y modo caída), con las URLs redirigidas desde un `sitecustomize.py` fuera del repo.
4. Negocios sintéticos creados con `store.create_tenant` a partir de las plantillas de `salon` y `bus` (60/40), con secretos falsos.
5. Un generador de webhooks firmados con conversaciones de varios turnos que siguen las opciones reales de cada respuesta, con identificadores únicos por ejecución.
6. Medir del envío del webhook a la llegada de la respuesta al simulador (p50, p95, p99, % de más de 5 s y de 30 s, respuestas que faltan), las esperas en cola de `procrastinate_jobs`, la CPU y la memoria por proceso y las conexiones a la base.

Conviene repetirla en la máquina de producción, antes de abrirla a clientes, y después de cada cambio en workers, colas o envíos.

## Qué aguanta hoy

Segunda prueba de carga (noviembre de 2026), con la plataforma tal como está hoy: cuatro workers ([ADR-023](adr/ADR-023-colas-aisladas-y-degradacion.md)), cortacircuitos y reintento por caducidad ([ADR-024](adr/ADR-024-envio-saliente-por-caducidad.md)). Máquina: Intel i3-7020U, 2 núcleos y 4 hilos, 7,8 GB de RAM, es decir, **la mitad de la máquina objetivo** (4 vCPU y 8 GB) y con el generador de carga en la misma. Latencia de respuesta de extremo a extremo (mensaje del cliente a respuesta enviada):

| Escenario | Carga | p95 | Observaciones |
|---|---|---|---|
| 100 negocios | normal | 0,97 s | |
| 300 negocios | normal | 1,04 s | |
| 300 negocios, Google degradado | normal | 2,9 s | `bus` no se ve afectado; 0 mensajes sin respuesta |
| 500 negocios | 13,7 mensajes/s | 3,4 s | |
| 700 negocios | 14,1 mensajes/s | 4,3 s | |
| 700 negocios | 17 mensajes/s | 32 s | Saturación: la cola crece, pero sin pérdidas |
| 300 negocios, Meta caído 5 min | normal | n/d | 0 mensajes perdidos, 0 duplicados; entregas hasta 6 min tarde; 3 quedaron `unknown` para la conciliación (ADR-026) |

- **Techo actual en esta máquina: unos 700 negocios a 14 mensajes/s.** El cuello de botella es `worker-outbound` (un solo proceso, limitado por el GIL) y, después, la CPU. El siguiente paso es separar la salida por proveedor o poner más procesos de salida (ver «Mejoras futuras»). La API del panel responde con p95 ≤ 0,6 s con la carga encima.
- **Caída de Meta de 5 minutos:** sin pérdidas ni duplicados. La prueba destapó tres defectos, corregidos después: una alerta por negocio en vez de una sola (97 alertas `health:whatsapp_unavailable` con 300 negocios; con Google degradado, unas 150 alertas en minutos), un arranque en frío de `ops_check` de 581 s con 700 negocios (sus comprobaciones de salud corrían en el hueco de un worker de salida y todas vencían a la vez) y una avalancha al volver el proveedor (unos 200 envíos liberados en el mismo instante: durante ~100 s todas las respuestas, también las de Telegram, tardaron 10-12 s). Ver [alertas](../referencia/alertas.md), [observabilidad](observabilidad.md) y [cola y workers](cola-y-workers.md).
- **Medida anterior (antes de ADR-023), para comparar:** con `worker-inbound` y `worker-outbound` de concurrencia 2, 100 negocios daban p95 3,2 s, 200 daban 9,6 s, 300 daban 114 s (71 % de respuestas de más de 30 s) y con 500 solo el 31 % recibía respuesta en la ventana; con Google lento, 100 negocios daban p95 387 s y 486 mensajes sin respuesta. El límite eran las ranuras de los workers, no la CPU.
- **Coste por mensaje:** unos 250 ms de CPU entre la app y PostgreSQL, 72 sentencias SQL y 20 transacciones. Con un millón de filas en las tablas calientes, las consultas siguen entre 0,1 y 0,6 ms.
- **Base de datos:** unos 4 KB de configuración por negocio. `inbound_event` ocupa unos 412 MB por millón de filas y `outbound_message` unos 523 MB, de ahí la importancia de la retención.
- **Lo que ya está bien:** RLS no se rompe; una caída de la base, un webhook duplicado o desordenado o un worker muerto no pierden ni duplican mensajes; no hay reservas dobles con workers concurrentes; backup, restauración y rotación de claves funcionan.

## Lo que limita al crecer, por orden de aparición

| A partir de | Qué se rompe | Por qué |
|---|---|---|
| ~150 negocios (arquitectura anterior) | Latencia de respuesta | Ranuras de los workers: **resuelto** con los cuatro workers (ADR-023), 700 negocios con p95 4,3 s |
| ~700 negocios o ~15 mensajes/s (en 2 núcleos) | Cola de salida y CPU | `worker-outbound` es un solo proceso (GIL) con una llamada a Meta o Telegram por mensaje; a 17 mensajes/s la cola crece (p95 32 s) sin perder nada. Hacen falta más procesos de salida (o separarlos por proveedor), no más hilos |
| ~500 | Memoria de los workers | El registro de negocios vive entero en cada proceso; el límite de 384 MB por worker de `compose.prod.yaml` no da para miles |
| ~1.000 | Recarga del registro | **Resuelto**: la reconstrucción completa (3,8 s con 300 negocios, 12 s con 1.000, 40 s con 3.000, 342 MB) ya no detiene peticiones ni trabajos, y además solo ocurre en la primera carga: cada guardado recarga de forma **incremental** (unos 13 ms de CPU por negocio modificado y por proceso, y la memoria no se duplica porque las instantáneas comparten los negocios sin cambios; ADR-030). Queda la memoria del registro entero en cada proceso, ligada al registro bajo demanda |
| ~1.000 | Alta de negocios | El coste de crear un negocio crece de forma cuadrática (3,4 s con 300) |
| ~1.000 | `redact()` de los logs | **Resuelto**: índice de secretos construido una vez por registro; coste por línea independiente del número de negocios (antes 5 ms con 300 y 60 ms con 3.000) |
| ~5.000 salones | Cuota de Google Calendar | 600 peticiones por minuto por usuario, y la cuenta de servicio única cuenta como un usuario |

## Límites de los servicios externos

| Servicio | Límite que importa | Consecuencia |
|---|---|---|
| Google Calendar | 600 peticiones/min por usuario (la cuenta de servicio es uno), 10.000/min por proyecto | 1.000 salones son unas 90/min de media y unas 300 en pico: cabe. Con unos 5.000 hay que pasar a notificaciones push (`events.watch`) o a OAuth por negocio. Google ha anunciado cobro por exceso de cuota «más adelante en 2026» |
| WhatsApp Cloud API | 80 mensajes/s por número; nivel de mensajería por portfolio desde octubre de 2025, empezando en 250 conversaciones iniciadas por el negocio | Por negocio sobra. Meta reintenta webhooks hasta 7 días |
| WhatsApp, altas | Unos 10 números nuevos por semana sin verificar el negocio, unos 200 verificado | Es el límite real del ritmo de altas: verificar el Business Manager antes de crecer |
| WhatsApp, coste | Posible cobro de los mensajes de servicio desde el 1-10-2026 (la documentación de Meta se contradice) | Verificar antes de fijar precios |
| Telegram | 30 mensajes/s por bot, 1/s por chat; las actualizaciones se guardan 24 h | Con un bot por negocio no limita, salvo en el bot de avisos (necesita su limitador). BotFather limita los bots por cuenta (unos 20, no oficial): cada negocio crea el suyo |
| Caídas | Meta tuvo caídas de unas 11,7 h (19-05-2026) y 5,5 h (09-11-2026) | La salida debe aguantar horas sin perder respuestas ni recordatorios en silencio ([ADR-024](adr/ADR-024-envio-saliente-por-caducidad.md)) |

## Servidor y proveedor

- **Proveedor:** VPS europea (Hetzner u OVH): los datos se quedan en la UE y cuesta 3-5 veces menos que GCP o AWS. Evitar instancias con CPU «a ráfagas» (t3, e2).
- **Hoy:** producción arrancó el 2026-11-24 en 2 vCPU y 4 GB, con los negocios de demo y un cliente real (pico medido de ~1,15 GiB con 5 negocios). Se amplía a 4 vCPU y 8 GB al sumar más clientes reales, o antes si salta `memory_high` ([ADR-005](adr/ADR-005-vps-docker-compose.md#proveedor-y-tamano-2026-11)). Las cifras de memoria y de PostgreSQL de abajo son las de esa máquina objetivo.
- **Para clientes reales:** 4 vCPU y 8 GB (mejor 16 GB o vCPU dedicadas). La segunda prueba de carga midió 700 negocios con p95 4,3 s en una máquina de 2 núcleos y 4 hilos, así que en 4 vCPU hay margen de sobra para los primeros cientos; el siguiente paso es más procesos de salida.
- **Memoria (8 GB):** los `mem_limit` de `compose.prod.yaml` suman **5.760 MB**: caddy 128, `web` 640, `web-panel` 512, cuatro workers a 384 (1.536), `panel` 64, `db` 2.560 y VictoriaLogs 320. Quedan unos 2,2 GB para el núcleo, la caché de páginas y el cojín de swap. 8 GB es el mínimo razonable.
- **PostgreSQL ajustado a 4 vCPU y 8 GB:** `shared_buffers=1GB` (≈ 1/8 de la RAM; el resto lo aprovecha la caché del sistema, de ahí `effective_cache_size=4GB`), `work_mem=8MB`, `maintenance_work_mem=256MB`, `random_page_cost=1.1` y `effective_io_concurrency=200` (SSD), `wal_compression=on`, `checkpoint_completion_target=0.9`, `max_wal_size=2GB`, `max_connections=200` (el peor caso de las conexiones de la aplicación es de unas 102: 92 más la conexión fija del hilo refrescador de cada proceso que sondea la configuración, [ADR-030](adr/ADR-030-registro-siempre-al-dia.md)) y `shm_size=512mb`. El registro de consultas lentas (`log_min_duration_statement`) está **apagado**: Django enlaza los parámetros en el cliente, así que la sentencia registrada llevaría teléfonos o nombres, y los logs no pueden llevar datos personales. Para activarlo hace falta antes `server_side_binding` en la conexión de Django. Con una máquina de otro tamaño, hay que revisar estas cifras y la suma de `mem_limit`.
- **Disco y reloj:** la alerta de disco salta al 80 % (aviso) y al 95 % (crítica) y mide `/` (donde viven Docker, el volumen de PostgreSQL y los temporales del backup) y `var/state/ops`; el reloj lo mantiene `systemd-timesyncd`, que el instalador deja activo.
- **App y base de datos juntas** hasta que una medición muestre competencia de CPU o disco entre ellas, o haga falta recuperar en minutos.
- **GCP o AWS** solo si un cliente lo exige. Su ventaja real sería PostgreSQL gestionado, y Cloud SQL y RDS probablemente no conceden `BYPASSRLS` (sin confirmar), que necesita `fp_owner`. La alternativa sería una política por tabla `TO fp_owner USING (true)`, con su ADR y aprobación. Cloud Run no sirve para los workers y AWS cobra cada IPv4.

### Portabilidad

| Cambio | Dificultad | Qué hace falta |
|---|---|---|
| Otra VPS Ubuntu 24.04 x86 | Fácil (medio día a un día) | `server-migrate.sh`, ver [traslado](../procedimientos/traslado.md) |
| VM en GCP o AWS | Media | Cortafuegos del proveedor, IP fija, `--operator-key`, `AllowUsers` |
| PostgreSQL gestionado | Difícil | `ensure-env.sh` fija el host `db`; `init-roles.sh`, backup y restauración usan `docker exec db`; `BYPASSRLS` |
| Servidor ARM | No soportado | Imágenes multi-arquitectura en CI |

Para no atarse: DNS en un proveedor independiente del servidor, backups en otro proveedor (ADR-021) y un ensayo de restauración en un proveedor distinto al menos una vez.

## Etapas de crecimiento

| Etapa | Negocios | Infraestructura | Cambios |
|---|---|---|---|
| 1 | hasta ~50 | Una VPS de 4 vCPU y 8 GB | Hecho: las mejoras de resiliencia y capacidad del resumen |
| 2 | 50-100 | La misma | Recuperación a un instante (PITR), menos SQL por mensaje, altas lineales, prueba de carga repetida en la máquina de producción |
| 3 | 100-400 | La misma, quizá 16 GB | Salida separada por proveedor o más procesos de salida |
| 4 | 400-1.000 | 8 vCPU dedicadas, 16-32 GB; quizá base de datos en otra VPS con réplica | Registro bajo demanda, limitadores compartidos, PgBouncer en modo sesión |
| 5 | 1.000-5.000 | Varias VPS (Swarm o similar) | Limitadores y estado de operación en la base, Google por push u OAuth |
| 6 | miles | Kubernetes con KEDA | Autoescalado de workers por profundidad de cola |

Kubernetes no compensa antes de la etapa 6: añade operación sin resolver ninguno de los límites anteriores, que son de código.

## Cuándo dar el siguiente paso

El número de negocios es solo orientativo: dos negocios pueden diferir mucho en tráfico. Lo que decide es lo que la plataforma ya mide. Cada señal sostenida durante días en hora punta, no un pico aislado, indica una acción:

| Señal (dónde se ve) | Umbral | Qué hacer |
|---|---|---|
| Mensajes por segundo en hora punta (panel, resumen) | > 8-10 sostenido (el techo medido en 2 núcleos es ~14) | Preparar la etapa siguiente: salida por proveedor y repetir la prueba de carga |
| Edad del trabajo más antiguo de `outbound` (panel, sistema; alerta `queue_lag:outbound`) | > 30 s en hora punta, o la alerta salta más de una vez por semana | Más procesos de salida o separarla por proveedor |
| CPU de `worker-outbound` (`docker stats`) | > 60 % de un núcleo de media en hora punta | Lo mismo: el GIL limita a un núcleo por proceso |
| `inbound_delay` o espera de `inbound_ext` (alertas, panel) | Salta fuera de una caída de Google | Revisar CPU de la máquina y concurrencia de `worker-calendar` |
| CPU total de la VPS | > 70 % de media en hora punta | Subir de máquina (vCPU dedicadas) o sacar PostgreSQL a otra |
| Memoria de un worker (`docker stats`) | > 300 MB de los 384 MB de su `mem_limit` | Subir el límite y planificar el registro bajo demanda |
| Conexiones a PostgreSQL | > 150 de 200 | PgBouncer en modo sesión o revisar pools |
| Disco (alerta `disk`) | > 80 % | Revisar retención y tamaño de backups locales; ampliar disco |
| Tamaño de `inbound_event` / `outbound_message` | > 10 millones de filas | Revisar plazos de retención y los índices de las consultas del panel |
| Peticiones a Google Calendar | > 300/min sostenido (la cuota es 600/min) | Notificaciones push (`events.watch`) u OAuth por negocio |
| Altas de WhatsApp | > 10 números por semana | Verificar el negocio en Meta Business |

Antes de cada salto de etapa: repetir la prueba de carga (ver [Cómo repetir la prueba](#como-repetir-la-prueba)) con el doble del tráfico real medido.

## Mejoras futuras

Lo que no hace falta para los primeros 50 negocios, con su motivo y cuándo abordarlo. El orden dentro de cada bloque es el recomendado; cada una se aborda cuando lo pida una de las señales de arriba.

### Para llegar a 100 negocios

- **Recuperación a un instante (PITR).** Hoy el backup es horario (ADR-021): se puede perder hasta una hora. Con archivado continuo del WAL (pgBackRest o WAL-G) a otro proveedor, la pérdida máxima baja a unos 15 minutos y la restauración, a unas 2 horas. Requiere ADR y aprobación (infraestructura).
- **Menos SQL por mensaje.** Medir con `pg_stat_statements` y quitar las 5 consultas más caras de las 72 por mensaje.
- **Altas de negocio lineales.** Quitar el coste cuadrático de crear un negocio.
- **Prueba de carga repetida** en la máquina objetivo (4 vCPU) y con el generador fuera de ella.

### Para pasar de 100

- **Más procesos de salida.** Escalar `worker-outbound` en procesos, no en hilos, para no depender de un solo GIL; la prueba de 700 negocios lo señala como el siguiente cuello. Lo natural es separar la salida por proveedor (un worker para WhatsApp y otro para Telegram), lo que además impide que una caída de Meta retrase a Telegram. Requiere el limitador compartido de más abajo.
- **Registro bajo demanda.** Cargar cada negocio cuando se usa, con caché, en vez del registro entero en cada proceso. Necesario antes de unos 1.000 negocios por memoria; la recarga ya no bloquea ni es proporcional al número de negocios (instantánea anterior y recarga incremental).
- **PostgreSQL en su propia máquina** con réplica en streaming; **PgBouncer en modo sesión** (el modo transacción rompe `LISTEN/NOTIFY` y los candados consultivos de Procrastinate) solo cuando `max_connections` sea un problema medido.
- **Imágenes multi-arquitectura** (amd64 y arm64) para poder usar servidores ARM, más baratos.

### Resiliencia avanzada (cuando una medición lo pida)

- **Estado compartido de proveedores.** Una tabla `provider_health` con sonda de solo lectura, en vez de un corte por proceso. El prototipo redujo de 5 a 30 veces las llamadas a Meta durante una caída, pero un corte por proceso con alerta única cubre la mayoría de casos.
- **Limitador de envíos en PostgreSQL** (cubo de tokens compartido entre procesos), necesario cuando haya varios procesos de salida. Hoy el bot de avisos tiene un limitador en memoria (`runtime/ratelimit.py`: 25 mensajes/s y 1/s por chat), válido solo con un proceso de salida.
- **Caché corta de disponibilidad y reutilización del cliente de Google** por hilo. Ahorros pequeños medidos (12-25 ms de CPU por mensaje). Las prioridades de cola ya existen: las respuestas van antes que los recordatorios.
- **Avisos agrupados al dueño** y plantilla de utilidad como alternativa cuando un recordatorio cae fuera de la ventana de 24 h.
- **Aviso visible al usuario** que supera el límite de 20 mensajes por minuto, que hoy se ignora en silencio.

### Para miles de negocios

- **Google Calendar por push** (`events.watch`) o con OAuth por negocio, para salir de la cuota de una sola cuenta de servicio.
- **Varias VPS** con los workers repartidos; antes, los limitadores en memoria y el estado de operación deben pasar a la base.
- **Kubernetes con KEDA**, escalando por la edad del trabajo más antiguo de cada cola.

## Pendiente de verificar

- Si Cloud SQL y RDS permiten `BYPASSRLS` (probar con una instancia mínima antes de decidir un gestionado).
- Si Meta cobra los mensajes de servicio desde el 1-10-2026.
- El techo real con las mejoras de 50 negocios en una máquina limpia de 4 vCPU.
