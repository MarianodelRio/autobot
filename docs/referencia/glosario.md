# Glosario

Vocabulario de Autobot en orden alfabético, con una o dos líneas por término y un enlace a la
página donde se explica. Léelo cuando un nombre del código o de la documentación no te suene.

**Alerta.** Nombre anterior de la incidencia; hoy, el aviso por Telegram de una incidencia
🔴 o 🟠 al abrirse. [Alertas](alertas.md).

**Auditoría.** Registro de las escrituras del panel y de los comandos de operación.
[Auditoría](auditoria.md).

**Barrida (barrido).** Trabajo que busca cosas atascadas o pendientes sin que nadie las
avise. Hay barridos de la plataforma (envíos y eventos sin trabajo, en `ops_check`) y de pack
(`calendar_sweep` de `salon`). [Cola y workers](../arquitectura/cola-y-workers.md).

**Biblioteca (de conjuntos de datos).** Almacén de datasets de un pack, independiente de
cualquier cliente (`dataset_library`, ADR-013). El cliente recibe una copia de la entrada
elegida, nunca una referencia viva. [Config y registro](../arquitectura/config-y-registro.md).

**Bot de avisos.** Bot de Telegram de la plataforma que avisa a los dueños de su negocio y
al chat de operación, y atiende su menú. También se llama bot de dueños.
[Bot de dueños](../arquitectura/bot-de-duenos.md).

**Bot de demo.** Bot que enseña los packs por Telegram y WhatsApp sobre negocios de demo.
[Bot de demo](../arquitectura/bot-de-demo.md).

**Canal.** Medio por el que habla un cliente final: WhatsApp o Telegram. Sus diferencias
viven solo en los adaptadores. `main` es el canal real de un negocio; `demo_tg` y `demo_wa`
son los de las puertas de demo. [Canales](../arquitectura/canales.md).

**Caso.** Envío, trabajo o aviso afectado por una incidencia. Se calcula en vivo desde su
tabla y nunca se copia a `ops_alert`. [Alertas](alertas.md).

**Cola.** Cola de trabajos Procrastinate sobre PostgreSQL, con colas `inbound`, `inbound_ext`, `outbound`,
`periodic` y `ops`. Los trabajos solo llevan ids. [Cola y workers](../arquitectura/cola-y-workers.md).

**Condición.** Incidencia que dice «está mal ahora» (un contenedor caído, una cola
atrasada): se cierra sola cuando desaparece la causa. [Alertas](alertas.md).

**Contacto.** Persona que escribe a un negocio por un canal. Un dato de cliente con
`tenant_id` y RLS. [Tenants y RLS](../arquitectura/tenants-y-rls.md).

**Dataset.** Conjunto de datos versionado de un negocio que no es configuración (hoy, los
horarios de `bus`). [Config y registro](../arquitectura/config-y-registro.md).

**Degradado.** Negocio cuya configuración o secretos no se pueden cargar: no atiende y
alerta. [Estados de negocio](estados-de-negocio.md).

**Demo.** Negocio de demostración creado desde la plantilla de un pack y accesible por las
puertas de demo. [Bot de demo](../arquitectura/bot-de-demo.md).

**`discarded`.** Estado final de un envío `unknown` que una persona decidió no enviar («Descartar»). No se reenvía, la
conciliación lo ignora y no cuenta como fallo; solo un estado de entrega del proveedor que demuestre la entrega lo
pasa a `sent`. [ADR-031](../arquitectura/adr/ADR-031-incidencias-como-bandeja.md).

**Dueño.** Persona que lleva un negocio cliente. Se vincula al bot de avisos con un enlace de
un solo uso (`owner_invite`). [Bot de dueños](../arquitectura/bot-de-duenos.md).

**Efecto.** Cualquier acción hacia fuera (enviar un mensaje, escribir en Calendar). Debe ser
idempotente y se anota en un diario. [Efectos e idempotencia](../arquitectura/efectos-e-idempotencia.md).

**Escenario.** Test de conversación de un pack que recorre su flujo y comprueba los límites
de canal. Obligatorio para cada pack. [Tests](../desarrollo/tests.md).

**Estado (de negocio).** Nivel de salud calculado por el panel: `ok`, `notice`, `warning`,
`critical` o `unknown`. [Estados de negocio](estados-de-negocio.md).

**Evento.** Incidencia que dice «pasó algo» (un envío rechazado, un trabajo fallido): se
cierra con «Lo he revisado» y un caso nuevo la reabre. [Alertas](alertas.md).

**`expired`.** Estado de un envío que pasó su `expires_at` (30 minutos una respuesta, hasta 24 h un
recordatorio) sin que el proveedor lo aceptara: no se envió ni se enviará. Una respuesta caducada se
sustituye por una disculpa; un recordatorio caducado puede revivirse; un aviso al dueño caduca a las 2 h, sin disculpa. No es un fallo.
[ADR-024](../arquitectura/adr/ADR-024-envio-saliente-por-caducidad.md).

**Idempotencia.** Repetir una operación no cambia su resultado. Es la base de la entrada de
eventos y de los efectos. [Efectos e idempotencia](../arquitectura/efectos-e-idempotencia.md).

**Incidencia.** Fila de `ops_alert`: un periodo abierto de una clave (`kind`) y un negocio,
con su naturaleza (condición o evento), severidad y casos (ADR-031). [Alertas](alertas.md).

**Marca de revisión.** Fecha que guarda «Lo he revisado» en un evento: los casos hasta ella
cuentan como revisados (`review_watermark`). [Alertas](alertas.md).

**Pack.** Módulo con la lógica de un tipo de negocio (`salon`, `bus`). La plataforma no sabe
qué es una cita ni un autobús. [Packs](../arquitectura/packs.md).

**Panel.** Aplicación interna de operación (`apps/panel/`), accesible solo por túnel SSH.
[Panel](../arquitectura/panel.md).

**Periodic.** Tarea periódica declarada por un pack (`Periodic`), que la plataforma ejecuta
por negocio y canal. [Packs](../arquitectura/packs.md).

**Plantilla.** Dos cosas distintas. De negocio: el documento inicial de un pack, del que sale
su demo (`packs/<pack>/template/`). De WhatsApp: mensaje proactivo aprobado por Meta
(`confirmacion_cita`). [Packs](../arquitectura/packs.md).

**Puerta.** Entrada de la plataforma para un bot de demo: una por canal (`demo_tg`,
`demo_wa`), con credenciales de la plataforma y no del negocio.
[Bot de demo](../arquitectura/bot-de-demo.md).

**Registro (registry).** Lista en memoria de los negocios cargados desde la base de datos,
con su pack, config y secretos. [Config y registro](../arquitectura/config-y-registro.md).

**RLS.** Seguridad a nivel de fila de PostgreSQL: cada fila de cliente lleva `tenant_id` y
solo es visible dentro de su `tenant_tx`. [Tenants y RLS](../arquitectura/tenants-y-rls.md).

**Tenant (negocio).** Un cliente de la plataforma: una empresa con su pack, su canal, su
configuración y sus datos. [Tenants y RLS](../arquitectura/tenants-y-rls.md).

**`tenant_tx`.** Única forma de fijar el tenant de una transacción para que RLS filtre.
Nunca se mantiene abierta durante llamadas externas.
[Tenants y RLS](../arquitectura/tenants-y-rls.md).

**`unknown`.** Resultado ambiguo de un envío: no se sabe si el proveedor lo entregó. Se
concilia con el estado de entrega y, sin evidencia tras 10 minutos, se reenvía una sola vez si su clase
admite duplicados (ADR-026); si no, lo resuelve una persona. [Envíos unknown](../incidencias/envios-unknown.md).

**Vida de un mensaje.** El recorrido de un mensaje entrante desde el webhook hasta la
respuesta. [Vida de un mensaje](../arquitectura/vida-de-un-mensaje.md).
