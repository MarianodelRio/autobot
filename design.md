# design.md — Diseño técnico de FlowPilot

> **Qué es este documento.** El diseño técnico completo de la plataforma: alcance, piezas, contratos entre módulos, los dos packs iniciales, datos, infraestructura, despliegue, operación y pruebas. Con él delante solo deberían quedar dudas de implementación (cómo escribir una función), no de diseño (dónde va, quién la llama, cómo se despliega).
>
> **Punto de partida.** No partimos de cero: hay dos bots en producción o casi, cada uno en su repositorio, que FlowPilot sustituye:
> - **`Peluqueria`** (DM Barber Shop): reservas por WhatsApp sobre Google Calendar. FastAPI + APScheduler, sin base de datos, en una VM de GCP.
> - **`buscaBus`** (Autocares San Sebastián): consulta de horarios de autobús por WhatsApp. Mismo esqueleto que Peluquería, horarios en YAML cargados en memoria.
>
> Este diseño parte de lo que esos dos bots **ya resuelven** (§4) y lleva a la parte común solo lo que de verdad se repite. Ningún requisito funcional de los dos bots se pierde sin estar listado como descartado o pospuesto (§4.4, §1.2).
>
> **Relación con otros documentos.** `IDEA.md` (el problema), `docs/adr/` (una página por decisión, enlazadas desde §0), `CLAUDE.md` (reglas de trabajo en el repo), `docs/glosario.md` (términos en lenguaje llano).
>
> **Convenciones.** **[DECIDIDO]**: no se discute salvo evidencia nueva. **[VERIFICAR]**: dato externo que hay que confirmar antes de usarlo. **[FUTURO]**: no se construye todavía; se indica cómo encajará.

---

## Índice

0. [Resumen de decisiones](#0-resumen-de-decisiones)
1. [Alcance](#1-alcance)
2. [Conceptos clave](#2-conceptos-clave)
3. [Principios](#3-principios)
4. [Qué aportan los bots existentes: común frente a específico](#4-qué-aportan-los-bots-existentes-común-frente-a-específico)
5. [Arquitectura](#5-arquitectura)
6. [Tenants, configuración y secretos](#6-tenants-configuración-y-secretos)
7. [Runtime de mensajes](#7-runtime-de-mensajes)
8. [Contrato de un pack](#8-contrato-de-un-pack)
9. [Pack `salon` (peluquería)](#9-pack-salon-peluquería)
10. [Pack `bus` (horarios de autobús)](#10-pack-bus-horarios-de-autobús)
11. [WhatsApp](#11-whatsapp)
12. [Avisos al dueño y alertas de operación](#12-avisos-al-dueño-y-alertas-de-operación)
13. [Datos](#13-datos)
14. [Seguridad](#14-seguridad)
15. [Infraestructura: una VPS con Docker Compose](#15-infraestructura-una-vps-con-docker-compose)
16. [Construcción y despliegue](#16-construcción-y-despliegue)
17. [Observabilidad y alertas](#17-observabilidad-y-alertas)
18. [Operación](#18-operación)
19. [Pruebas](#19-pruebas)
20. [Forma de trabajo](#20-forma-de-trabajo)
21. [Plan de implementación y migración](#21-plan-de-implementación-y-migración)
22. [Pendiente de verificar y decisiones abiertas](#22-pendiente-de-verificar-y-decisiones-abiertas)
23. [Documentación](#23-documentación)

---

### 0. Resumen de decisiones

| # | Tema | Decisión | ADR |
|---|---|---|---|
| 1 | Lenguaje y framework | **Python 3.14 + Django 5.2 LTS** (soporte hasta abril de 2028) | [ADR-001](docs/adr/ADR-001-monolito-modular.md) |
| 2 | Forma de la aplicación | **Monolito modular**: una imagen, procesos `web`, `worker` y `admin` | [ADR-001](docs/adr/ADR-001-monolito-modular.md) |
| 3 | Cola | **Procrastinate 3.x** sobre el propio PostgreSQL; 3 colas (`inbound`, `outbound`, `periodic`) | [ADR-001](docs/adr/ADR-001-monolito-modular.md) |
| 4 | Multitenant | **Una base de datos PostgreSQL 18**, `tenant_id` en cada fila de cliente, **Row-Level Security** | [ADR-002](docs/adr/ADR-002-multitenancy-rls.md) |
| 5 | Lógica de negocio | **Packs en Python** (`salon`, `bus`), cada uno con su **máquina de estados** y su esquema de config; la plataforma no sabe qué es una peluquería | [ADR-003](docs/adr/ADR-003-packs.md) |
| 6 | Entrada | **Guardar primero, contestar 200, procesar después**; "al menos una vez" + idempotencia | [ADR-004](docs/adr/ADR-004-entrada-idempotente.md) |
| 7 | Config de tenant | **Ficheros YAML en el repositorio** (`tenants/<slug>/`), validados en CI y al arrancar. Datasets (horarios) igual | §6 |
| 8 | Secretos | Plataforma: `.env` en el servidor. Tenants: tabla `credential` **cifrada con Fernet** (clave en `.env`) | §6.4 |
| 9 | Canales | **Solo WhatsApp** (Cloud API, app de Meta del cliente). Telegram solo para avisos al dueño y alertas | §11, §12 |
| 10 | Integraciones | **Google Calendar** (cuenta de servicio de la plataforma). Sin registro genérico de conectores | §9.3 |
| 11 | IA | **Ninguna en la v1.** Todo determinista | §1.2 |
| 12 | Infraestructura | **Una VPS en la UE con Docker Compose**: `web`, `worker`, `admin`, `db` (PostgreSQL 18), `caddy`. ~15–20 €/mes | [ADR-005](docs/adr/ADR-005-vps-docker-compose.md) |
| 13 | Backups | `pg_dump` cada 6 h → **restic** → almacenamiento externo (otro proveedor), cifrado; simulacro trimestral | §15.4 |
| 14 | Despliegue | GitHub Actions: CI en cada PR; imagen en GHCR; **despliegue a prod manual** por SSH | §16 |
| 15 | Observabilidad | Logs JSON + Sentry + comprobación de operación cada 5 min → Telegram + latido externo (healthchecks.io) + uptime externo | §17 |
| 16 | Forma de trabajo | **Un solo agente** + revisión humana en cada PR. Sin framework de agentes | §20 |

**Qué cambia respecto al diseño anterior** (versión con AWS y tres packs):

| Antes | Ahora | Por qué |
|---|---|---|
| AWS: ECS Fargate, RDS, ALB, KMS, SSM, EventBridge, CloudWatch, CDK, dos cuentas | Una VPS con Docker Compose y Caddy | ~100 €/mes → ~15–20 €/mes; una persona opera menos piezas. La escala (≤15 negocios) no necesita autoescalado ni alta disponibilidad |
| Packs `salon`, `bus`, `gym` | `salon` y `bus` | `gym` no existe como negocio real; se lleva con él formularios públicos, email y SES |
| Motor genérico de recorridos (`Journeys`, `Step`, bloques versionados con `Params`) | Una máquina de estados por pack + utilidades comunes de interfaz | Los dos negocios reales tienen flujos muy distintos; los dos bots existentes ya usan máquina de estados y funcionan. La abstracción se añade cuando un tercer pack repita algo |
| Registro de conectores con categorías, manifests, bindings y circuit breaker | Un cliente de Google Calendar detrás de un `Protocol` del pack | Solo un pack usa un sistema externo |
| Config y datasets en BD, consola con subida de ficheros, `config_history`, `dataset_version` | YAML en git (`tenants/<slug>/`) | Es lo que ya hacen los dos bots; git da historial, diff, revisión y vuelta atrás gratis |
| Watch de Google Calendar (push, `syncToken`, renovación) | Barrido periódico cada 15 min | Peluquería ya funciona con barrido; sin endpoint público, sin renovaciones, sin 410 |
| `side_effect`, `send_intent`, `message`, `usage_daily`, `audit_event`, `console_action`… | `inbound_event`, `outbound_message`, `conversation`, `contact`, `credential`, `notification` | Menos tablas; la idempotencia de reservas la da el id de evento determinista de Calendar |
| Bedrock (FAQ con IA) | Pospuesto | Ningún bot existente usa IA; evita coste, proveedor y obligaciones del AI Act |
| Telegram como canal de clientes, bot del dueño con respuesta a derivaciones | Telegram solo de salida (avisos al dueño y a ops) | Canales adicionales y derivación a humano, pospuestos |
| Consola HTMX con simulador y alta guiada | Django Admin (solo por túnel SSH) + comandos `manage.py` | Un operador; nada de interfaz que mantener |
| dev-team (agentes, tareas, steering) | Un agente, ramas y PR | Pedido explícito |

---

### 1. Alcance

#### 1.1 Dentro de la v1

- **Plataforma multi-negocio** para **5–10 negocios** al empezar, ampliable a **15** sin cambios de diseño (§15.6).
- **Canal de clientes:** WhatsApp Cloud API, un número por negocio, con la app de Meta en el portfolio del propio negocio.
- **Pack `salon`**: todo lo que hace hoy el bot de Peluquería (§9): reservar, ver, mover y cancelar citas sobre el Google Calendar del negocio; citas manuales del dueño con confirmación por WhatsApp; recordatorios 24 h antes con confirmar/cancelar; cierres y horarios especiales con eventos `[CFG]`; evento especial con días propios; límite de citas por cliente.
- **Pack `bus`**: todo lo que hace hoy buscaBus (§10): consulta origen → destino → día con salidas directas, motor de horarios en memoria, matcher de pueblos que nunca adivina, fechas en formato cerrado, "ver pueblos por línea", validador estricto de horarios y vista de revisión HTML/PDF para la empresa.
- **Avisos al dueño** por Telegram, opcionales por negocio (§12).
- **Operación para una persona**: alta y baja de negocios con comandos, alertas a Telegram, backups externos probados.

#### 1.2 Fuera o pospuesto

| Pospuesto | Cuándo se revisa | Cómo encajará |
|---|---|---|
| Pack de gimnasio, formularios públicos, email (SES) | Un negocio real lo pida | Nuevo pack; formularios como una entrada más que crea `inbound_event` |
| IA (FAQ con knowledge) | Se mida que >10–15 % de los textos no se entienden, o un negocio lo pida | Interfaz `LLMPort` en `core`, proveedor UE; aviso de IA obligatorio (AI Act art. 50) en ese momento |
| Telegram, Instagram, email como canal de clientes | Un negocio lo pida | Un adaptador más con el contrato de §11; la conversación del pack no cambia |
| Derivación a humano con respuesta desde Telegram | Un negocio tenga a alguien atendiendo | Modo `human` en `conversation`; hoy "Contacto" muestra el teléfono del negocio |
| Portal o panel de autoservicio para negocios | El negocio necesite cambiar algo sin el operador más de una vez al mes | Config pasaría a BD con historial; hoy el dueño gestiona su agenda en Google Calendar |
| Varios profesionales por peluquería, lista de espera, pagos o señal | Un negocio lo pida | `staff_id` en `CalendarPort` (un calendario por profesional) |
| Precios, incidencias por línea, exportación GTFS en `bus` | Lleguen los datos de la empresa | Campos nuevos en el dataset y en el resultado |
| Escalado horizontal, alta disponibilidad, staging en la nube | >15 negocios o un negocio que dependa del servicio en horas críticas | §15.6 |
| WhatsApp Flows, Tech Provider / Embedded Signup | Volumen de altas que lo justifique | Modo `platform_app` (§11.1) |

#### 1.3 Requisitos no funcionales

| Requisito | Valor | Implicación |
|---|---|---|
| Escala | 5–10 negocios (15 sin cambios); ~1.000–5.000 mensajes/mes por negocio; picos de unos pocos mensajes por segundo en total | Un proceso `worker` con concurrencia 4 sobra con margen de >100×; sin autoescalado |
| Latencia | Respuesta al contacto en 1–3 s | Webhook guarda y encola en <100 ms; Procrastinate usa `LISTEN/NOTIFY` (sin sondeo) |
| Disponibilidad | Caídas de minutos ocasionales aceptables; no se promete 24/7 | Meta reintenta los webhooks durante horas: un corte corto no pierde mensajes |
| Durabilidad | RPO ≤ 6 h, RTO ≤ 2 h | Backups cada 6 h fuera de la VPS (§15.4). La agenda vive en Google Calendar y los horarios en git: lo que se perdería son conversaciones en curso |
| Coste de infraestructura | ~20 €/mes como objetivo, sin contar APIs (Meta lo paga cada negocio) | §15.5 |
| Datos | Personales (teléfonos, nombres, citas); sin pagos; sin datos de salud | RLS, cifrado de secretos, retención (§13.3), datos en la UE |

---

### 2. Conceptos clave

| Concepto | Qué es | Ejemplo |
|---|---|---|
| **Tenant** (negocio) | Un negocio que usa la plataforma. Todo dato pertenece a un tenant | DM Barber Shop |
| **Pack** | El programa para un tipo de negocio: conversación, reglas, esquema de config y tests | `salon`, `bus` |
| **Config** | Los datos de un tenant que usa su pack, validados con el esquema del pack | Servicios, precios, horario, textos, pueblos del menú |
| **Dataset** | Datos estructurados grandes de un tenant, en ficheros con validador estricto | Los horarios de una empresa de autobuses |
| **Contacto** | Persona que escribe al negocio por WhatsApp (nunca "cliente": cliente = tenant) | Lucía |
| **Conversación** | El estado de la charla de un contacto con un negocio (en qué paso está) | "Reservando: ha elegido corte, falta el día" |
| **Evento entrante** (`inbound_event`) | Un aviso de Meta ya guardado y pendiente de procesar: un mensaje o un cambio de estado de un envío | El mensaje "hola" de las 10:12 |
| **Evento de calendario** | Una cita o bloqueo en el Google Calendar del negocio (`gcal_id`); no confundir con evento entrante | La cita de Lucía del jueves a las 17:00 |
| **Mensaje saliente** (`outbound_message`) | Un mensaje que hay que enviar, guardado **antes** de enviarlo, con su clave idempotente | La lista de horas libres |
| **Respuesta** (reply) | Lo que el pack quiere decir al contacto en este turno | Texto, botones, lista |
| **Acción** | Lo que el pack quiere que ocurra además de responder | Enviar una plantilla, avisar al dueño, marcar baja |
| **Barrido** | Tarea periódica por tenant que revisa datos externos y actúa sobre lo que encuentra, con una clave estable por entidad | Recordatorios de citas cada 15 min |
| **Plantilla** | Mensaje aprobado por Meta, el único que se puede enviar fuera de la ventana de 24 h | `recordatorio_cita` |

---

### 3. Principios

1. **Simple antes que flexible.** Una máquina, una base de datos, una imagen. Se añade complejidad con un problema real delante, no antes.
2. **Lo genérico en la plataforma, lo específico en los packs.** La plataforma no sabe qué es una cita ni un autobús. Pero solo sube a la parte común lo que **ya se repite** en los dos packs (§4.3).
3. **Lógica en código; datos de negocio en ficheros validados.** Precios, horarios, textos y datasets se cambian sin programar, con revisión en git y validación en CI.
4. **Nada se pierde y nada se duplica.** Todo evento se guarda antes de procesarse y todo efecto externo es idempotente. Nunca se reintenta a ciegas un envío ambiguo.
5. **Determinista.** Horarios, disponibilidad y precios salen de datos. El bot nunca adivina en silencio: o hay una respuesta única, o pregunta.
6. **Aislamiento entre negocios garantizado por la base de datos** (RLS), no solo por el código.
7. **Diseñado para una persona.** Lo que no se puede operar fácilmente con un comando, no se hace.
8. **Portable.** Nada depende de un proveedor de nube: contenedores estándar, PostgreSQL estándar, backups en formato abierto.

---

### 4. Qué aportan los bots existentes: común frente a específico

#### 4.1 Peluquería (`~/Desktop/Peluqueria`)

FastAPI + APScheduler; Google Calendar es la única fuente de verdad; estado de conversación en memoria (30 min); 4.600 líneas con tests completos.

Funcionalidad que hay que conservar (detalle en §9):

- Menú: **Pedir cita · Ver mis citas · Mover cita · Cancelar cita** (+ **Cita {evento}** si hay evento especial activo).
- Reserva: servicio (≤ 9, con precio) → día (solo días con huecos, ventana de 21 días) → mañana/tarde si no caben las horas → hora → nombre → confirmación.
- Servicios con **dos duraciones**: `duracion_min` (ocupación del peluquero, colisiones) y `presencia_cliente_min` (última hora ofrecible antes del cierre).
- **Límite de 5 citas futuras** por cliente (falla en abierto si Calendar no responde).
- **Mover cita** = elegir cita → servicio → día → hora; **cancelar** = elegir cita → cancelada.
- **Citas manuales** del peluquero: título `<Servicio> - <Nombre>`, `Telefono: +34…` en la descripción → plantilla `confirmacion_cita` con botón Cancelar. Eventos sin teléfono solo bloquean horas.
- **Recordatorios** 23–25 h antes (plantilla `recordatorio_cita`, botones Confirmar/Cancelar); al confirmar se marca la cita como confirmada en Calendar.
- Eventos **`[CFG] CERRADO`**, **`[CFG] VACACIONES`**, **`[CFG] HORARIO HH:MM-HH:MM`**.
- **Evento especial** (`evento:` en config): nombre y días con franjas propias, opción extra en el menú.
- Interruptores `envios.recordatorios` y `envios.confirmaciones`.
- Defensas: HMAC de Meta, cuerpo ≤ 64 KB, validación del identificador, deduplicación, límite por IP y por teléfono, candado por teléfono, candado por hueco + "¿sigue libre?" antes de crear, limpieza de HTML en descripciones, verificación de que la cita de un botón de recordatorio pertenece a quien lo pulsa, enmascarado de teléfonos en logs, mensaje de recuperación si una respuesta no se entrega.
- **Identificador de contacto**: `user_id` (BSUID, `ES.xxxx`) si Meta lo envía; si no, `from` (teléfono). El teléfono puede no estar disponible.
- Operación: comandos de admin por WhatsApp (`/status`, `/help`, `/logs`, `/restart`), watchdog por cron (salud, RAM, disco, dominio, certificado, pico de errores), reinicio nocturno, generador de QR `wa.me`.

#### 4.2 Autobuses (`~/Desktop/buscaBus`)

FastAPI; horarios en YAML editados a mano en `horarios/`, validados y cargados en memoria; sin escrituras ni APIs externas por consulta; fases 1–4 implementadas, falta infraestructura y alta en Meta.

Funcionalidad que hay que conservar (detalle en §10):

- Menú **Ver horarios · Información**; flujo **origen → destino → día → resultado** con botones **Otro día · Ver la vuelta · Otra consulta**.
- Origen: 8 pueblos de la config + "Otro pueblo"; destino: solo los alcanzables (lista completa si son ≤ 9), sin pares no vendibles.
- Día: 7 días con **número de salidas** de ese trayecto y "Otra fecha" en **formato cerrado** `día/mes[/año]`.
- Resultado: salidas directas, **fusión del mismo autobús**, salidas ya pasadas si es hoy, notas con marcas numéricas, `sin_datos` ≠ `sin_servicio`, siguiente día con salidas, nunca trasbordos inventados, corte a 4.096 caracteres.
- **Matcher**: exacto → prefijo → errata (Damerau-Levenshtein), mínimo 3 letras, nunca adivina (Villafranca siempre pregunta), "Ver pueblos por línea" paginado, localidades pendientes con "Usar Y".
- **Validador estricto** con ~30 reglas (fichero, tabla, fila, motivo), herramientas `validar`, `formatear`, `revision` (HTML + PDF con cambios desde la versión publicada, en lenguaje de negocio).
- Calendario: festivos generales y locales por línea, periodo escolar, temporadas por línea, días sin servicio en ninguna línea.
- Textos no entendidos registrados **sin teléfono**.

#### 4.3 Matriz: qué es común y qué es de cada pack

| Pieza | Peluquería | Autobuses | Dónde va en FlowPilot |
|---|---|---|---|
| Webhook de Meta (HMAC, 64 KB, identificador, BSUID) | ✔ | copia | **Común** `flowpilot/whatsapp` |
| Envío a Meta (reintentos, 429, plantillas, errores) | ✔ | copia | **Común** `flowpilot/whatsapp` |
| Deduplicación de mensajes | memoria | memoria | **Común**, en BD (`UNIQUE`) |
| Candado por contacto y estado con caducidad de 30 min | memoria | memoria | **Común**, en BD + candado de Procrastinate (§7) |
| Límite por contacto e IP | ✔ | ✔ | **Común** |
| Enmascarado de teléfonos en logs | ✔ | ✔ | **Común** |
| Mensaje de recuperación ante error | ✔ | ✔ | **Común** (runtime) |
| Constructores de listas y botones con los límites de WhatsApp (`_trunc`, `_row`, listas ≤ 10 filas) | ✔ | copia + propios | **Común** `core/ui` (helpers); los constructores concretos, en cada pack |
| Listas paginadas (8 + "Más" + "Volver") | ✔ (horas) | ✔ (líneas, pueblos) | **Común** `core/ui.paginate` |
| Normalización de texto (minúsculas, sin tildes) | ✔ | ✔ (+ artículos) | **Común** `core/text.normalize`; el bus añade su capa (artículos, relleno) |
| Fechas en español ("jueves 9 de octubre") | ✔ | ✔ | **Común** `core/dates` |
| Config YAML validada al arrancar | ✔ | ✔ | **Común**: `tenants/<slug>/tenant.yaml` + esquema pydantic del pack |
| Máquina de estados de la conversación | ✔ | ✔ | **Cada pack** (son flujos distintos) |
| Textos al contacto | `messages.py` | `messages.py` | **Cada pack**, con textos sobrescribibles por config donde haga falta |
| Google Calendar, huecos, `[CFG]`, citas manuales | ✔ | — | Cliente común `integrations/google_calendar`; reglas en `packs/salon` |
| Barridos periódicos | 2 jobs | — | **Común** el mecanismo (§7.6); el barrido, en `packs/salon` |
| Horarios, motor, matcher, fechas cerradas, revisión | — | ✔ | `packs/bus` (se porta casi tal cual) |
| Salud | Calendar | datos cargados | **Común** `/health` + `pack.health()` por tenant |
| QR de `wa.me` | ✔ | — | **Común** `tools/qr.py` (cualquier tenant) |

Regla aplicada: **sube a común lo que está en los dos bots**. Lo que está en uno solo se queda en su pack aunque "podría servir a otros"; se mueve cuando aparezca el segundo uso.

#### 4.4 Qué se sustituye o se descarta

| De los bots actuales | En FlowPilot | Motivo |
|---|---|---|
| Estado en memoria, candados en memoria, dedup en memoria | PostgreSQL + candados de Procrastinate | Sobrevive a reinicios; varios procesos |
| APScheduler | Tareas periódicas de Procrastinate | Una sola pieza; sin trabajos duplicados |
| nginx + certbot + DuckDNS | Caddy (HTTPS automático) + dominio propio | Menos piezas; renovación sin scripts |
| systemd por bot, VM de GCP free tier | Docker Compose en una VPS | Un despliegue para todos los negocios |
| Comandos de admin por WhatsApp (`/status`, `/logs`, `/restart`) | Alertas en Telegram + `make status`/`make logs` por SSH + Django Admin | Ya no hay un número "del operador" por negocio |
| `watchdog.py` por cron, métricas en memoria, `/metrics` | Comprobación de operación cada 5 min + latido externo + uptime externo + Sentry (§17) | Funciona aunque la aplicación esté caída |
| Reinicio nocturno | — | No hay estado en memoria que limpiar |
| Estado en la descripción de Calendar (`Recordatorio: sí`, `Estado: confirmada` como marca de idempotencia) | Idempotencia en BD; Calendar solo guarda lo que el dueño debe ver (`Estado: confirmada`) | No depender de que el dueño no edite esos campos |
| Caché de huecos de 180 s | Una lectura por rango para la lista de días; sin caché entre peticiones | El volumen lo permite y evita huecos obsoletos |
| `tools/telegram_pruebas.py` (pruebas con negocio por Telegram) | Número de prueba de Meta (hasta 5 destinatarios) + `manage.py chat` | Sin canal extra que mantener |
| `pytz` (Peluquería) | `zoneinfo` | Ya decidido en buscaBus |

---

### 5. Arquitectura

#### 5.1 Vista general

```
                     ┌──────────────────────────── VPS (UE) ─────────────────────────────┐
  Meta (WhatsApp) ──►│ caddy :443  ── /webhooks/whatsapp/*, /health ──► web (gunicorn)   │
                     │  (HTTPS auto)                                       │             │
                     │                                                     ▼             │
                     │                                           ┌─────────────────┐     │
  Operador ── SSH ──►│ admin (Django Admin, 127.0.0.1) ─────────►│ db: PostgreSQL 18│    │
   (túnel)           │                                           │ datos + cola     │    │
                     │ worker (Procrastinate) ◄──────────────────┴─────────────────┘     │
                     │   ├─► Meta Graph API (envíos)                                     │
                     │   ├─► Google Calendar API (pack salon)                            │
                     │   ├─► Telegram Bot API (avisos al dueño, alertas)                 │
                     │   └─► healthchecks.io (latido)                                    │
                     │ backup (timer del host) ── restic ──► almacenamiento externo      │
                     └───────────────────────────────────────────────────────────────────┘
```

#### 5.2 Procesos

Todos usan **la misma imagen**; cambia el comando.

| Servicio | Comando | Responsabilidad | Lo que NO hace |
|---|---|---|---|
| `web` | `gunicorn config.wsgi --workers 2 --threads 4` | Webhooks de WhatsApp y `/health`. Verifica, guarda, encola y contesta 200 | Llamar a APIs externas, ejecutar packs, servir el admin (no tiene sus URLs ni las credenciales de BD con `BYPASSRLS`) |
| `worker` | `manage.py procrastinate worker --concurrency 4` | Procesar eventos, ejecutar packs, enviar mensajes, periódicas y barridos | Atender HTTP |
| `admin` | `gunicorn config.wsgi_admin` en `127.0.0.1:8081` | Django Admin para el operador (vía túnel SSH) | Exponerse a internet |
| `migrate` | `manage.py migrate && manage.py sync_tenants` | Tarea puntual en cada despliegue (§16) | — |
| `db` | `postgres:18` | Datos y cola | Exponerse fuera de la red de Compose |
| `caddy` | `caddy:2` | TLS automático (Let's Encrypt), proxy a `web`, solo rutas públicas | — |

**Conexiones a la BD:** `web` 8 (2 × 4 hilos) + `worker` ~6 (concurrencia 4 + escucha + periódicas) + `admin` 2 → **~16** de las 100 por defecto.

#### 5.3 La vida de un mensaje

1. El contacto escribe al WhatsApp del negocio. **Meta** envía `POST https://api.<dominio>/webhooks/whatsapp/<app_public_id>`.
2. **web** identifica la app por la URL (registro en memoria, §6.3), comprueba la firma HMAC con su `app_secret`, separa los elementos del aviso y, por cada uno, resuelve el tenant por `phone_number_id`, **guarda** `inbound_event` (si ya existía, no hace nada) y **encola** `process_event` con candado por contacto. Contesta **200** en <100 ms.
3. **worker** coge el trabajo. El candado `conv:<hash>` garantiza que dos mensajes del mismo contacto se procesan en orden, nunca a la vez.
4. **tx1** (transacción corta): carga evento, contacto y conversación.
5. **Sin transacción**: pasa el mensaje al pack con un `PackContext`. El pack decide respuestas, nuevo estado y acciones; si necesita Calendar, lo llama aquí.
6. **tx2**: guarda el estado nuevo (comprobando `conversation.version`), crea los `outbound_message` en orden y las acciones, marca el evento como hecho y encola los envíos (el trabajo solo existe si hay COMMIT).
7. **worker** (cola `outbound`) envía cada mensaje a Meta, guarda el `wamid` y lo marca enviado.
8. Más tarde llegan avisos de estado (entregado, leído, fallido, con precio): actualizan `outbound_message`.

Si algo falla a mitad, el trabajo se reintenta y la idempotencia (§7) evita duplicados.

#### 5.4 Módulos y regla de dependencias

```
src/
  core/            Python puro, SIN Django: tipos del contrato de pack, respuestas y acciones,
                   límites de WhatsApp y plan de envío, utilidades de interfaz, texto y fechas,
                   arnés de pruebas de conversación
  integrations/    Clientes de sistemas externos, SIN Django: google_calendar/
  packs/           salon/, bus/  + registry.py (diccionario explícito de packs)
  flowpilot/       Django:
     tenancy/        Tenant, registro de tenants (YAML → memoria), tenant_tx, credenciales
     whatsapp/       webhook, parser de avisos, cliente de envío
     runtime/        InboundEvent, Conversation, Contact, OutboundMessage, process_event, envíos
     notify/         Telegram (avisos al dueño y alertas de ops)
     ops/            /health, comprobación de operación, latido, retención
     admin_site/     Django Admin (solo en el servicio `admin`)
     jobs.py         app de Procrastinate y tareas
  config/          settings, urls (web), urls_admin (admin), wsgi
```

**Regla de dependencias [DECIDIDO]** (comprobada con `import-linter` en CI):

```
core           ──►  nada del proyecto
integrations   ──►  core
packs/*        ──►  core              (nunca Django, nunca integrations, nunca otro pack)
flowpilot      ──►  core, integrations, packs.registry
packs/A        ──X  packs/B
```

Los packs hablan con Calendar mediante un `Protocol` propio (`packs/salon/ports.py`); `flowpilot` le pasa la implementación de `integrations/google_calendar`. Así los tests de `core` y de los packs corren sin BD ni red.

#### 5.5 Estructura del repositorio

```
flowpilot/
├── pyproject.toml · uv.lock · manage.py · Dockerfile · Makefile · .env.example
├── compose.yaml                 servicios comunes (local y prod)
├── compose.prod.yaml            imagen de GHCR, caddy, límites de logs, reinicio automático
├── Caddyfile
├── README.md · IDEA.md · design.md · CLAUDE.md
├── src/                         §5.4
├── tenants/
│   └── <slug>/
│       ├── tenant.yaml          identidad, canal, pack y config (§6.2)
│       └── datasets/            solo packs con datasets (bus: timetable/)
├── tools/                       qr.py, bus_validar.py, bus_formatear.py, bus_revision.py,
│                                telegram_link.py, migrate_salon_events.py
├── deploy/                      deploy.sh, backup.sh, restore.sh, systemd/ (timer de backup)
├── tests/                       integration/ · isolation/ · contract/ · fixtures/
│                                (unit y escenarios viven junto a cada pack: packs/*/tests/)
├── docs/                        adr/ · packs/ · runbooks/ · glosario.md
└── .github/workflows/           ci.yml · deploy.yml
```

---

### 6. Tenants, configuración y secretos

#### 6.1 Qué vive dónde

| Dónde | Qué | Cómo se cambia | ¿Despliegue? |
|---|---|---|---|
| **Repositorio** (`src/`) | Código, packs, plantillas declaradas, migraciones | PR + CI + revisión | Sí |
| **Repositorio** (`tenants/<slug>/`) | Alta del tenant, ids de WhatsApp (no secretos), pack, **config de negocio**, **datasets** | PR + CI (valida todo) + revisión | Sí (~1 min, sin corte perceptible) |
| **Google Calendar del negocio** (pack `salon`) | Citas, bloqueos, cierres `[CFG]` | Lo hace el dueño | No |
| **Base de datos** | Contactos, conversaciones, eventos, mensajes, avisos, **credenciales cifradas** | Runtime; credenciales con `manage.py set_secret` | No |
| **`.env` del servidor** | Secretos de plataforma y lo que cambia entre local y prod | SSH (y copia en el gestor de contraseñas) | Reinicio |

**[DECIDIDO] Config y datasets en git.** Es como trabajan hoy los dos bots (`config.yaml`, `horarios/`) y el operador es una sola persona. Git da historial, diff, revisión, vuelta atrás y validación en CI. El precio es que un cambio de precio o de horario requiere desplegar, que en una VPS es un comando. Lo que el dueño cambia a menudo (cierres, vacaciones, horarios especiales de un día) no pasa por aquí: lo hace en su Google Calendar. Si algún día los negocios editan su config ellos mismos, se pasa a BD (§1.2).

Ningún fichero de `tenants/` contiene secretos ni datos personales de contactos. El repositorio es privado. Si más adelante colabora alguien que no deba ver datos de negocios, `tenants/` se mueve a un repositorio aparte montado en la imagen.

#### 6.2 `tenant.yaml`

```yaml
# tenants/dm-barber/tenant.yaml
id: 01929a4e-6b1c-7d3e-9f00-1a2b3c4d5e6f   # UUIDv7 fijo, generado en el alta (§18.1)
slug: dm-barber
name: DM Barber Shop
status: active                  # onboarding | active | paused | offboarded
timezone: Europe/Madrid
pack: salon

whatsapp:
  app_public_id: k3v9w2q8       # aleatorio; va en la URL del webhook
  app_id: "1234567890"
  waba_id: "9876543210"
  phone_number_id: "1122334455"
  display_phone: "+34 682 21 44 69"
  graph_version: v23.0          # opcional; por defecto WHATSAPP_GRAPH_VERSION

owner:                          # opcional (§12)
  telegram_chat_id: 123456789
  notify: [cancellation]        # tipos de aviso que quiere recibir

config:                         # validado con el esquema del pack (SalonConfig, §9.2)
  business_name: DM Barber Shop
  contact_phone: "+34 682 21 44 69"
  calendar_id: c_abc123@group.calendar.google.com
  services:
    corte: {name: Corte de pelo, price_eur: 10, duration_min: 30, client_presence_min: 30}
  # …
```

#### 6.3 Carga y validación

- **Registro de tenants** (`flowpilot/tenancy/registry.py`): al arrancar, cada proceso lee `tenants/*/tenant.yaml`, valida la parte común y la `config` con el esquema del pack, carga los datasets con `pack.load_data` (§8.1) y construye índices en memoria: `app_public_id → app`, `phone_number_id → tenant`, `slug → tenant`.
- **Un tenant inválido no tumba a los demás.** CI ya lo habría bloqueado (§19.3); si aun así falla al arrancar, ese tenant queda `degraded`: sus webhooks se guardan como `ignored`, se responde al contacto con un texto seguro de plataforma y salta una alerta 🔴 (§17.3).
- **`sync_tenants`** (en `migrate`, §16): hace *upsert* de la tabla `tenant` (id, slug, name, pack, status, timezone) para que las claves foráneas y RLS funcionen. La tabla es un reflejo: nunca se edita a mano.
- **Estados:** `onboarding` (solo el número de prueba del operador recibe respuesta), `active`, `paused` (se guarda y no se responde), `offboarded` (se contesta 200 sin guardar).

#### 6.4 Secretos

**Plataforma** (`.env` del servidor, `chmod 600`, copia en el gestor de contraseñas; nunca en git ni en la imagen):

```text
ENVIRONMENT=local|prod
DJANGO_SECRET_KEY, DJANGO_ALLOWED_HOSTS=api.<dominio>
POSTGRES_PASSWORD (superusuario, solo en db)
DB_OWNER_URL      (solo migrate)       DB_APP_URL (web, worker)      DB_ADMIN_URL (solo admin)
CREDENTIALS_KEYS  (claves Fernet separadas por comas; la primera cifra, todas descifran)
GOOGLE_SERVICE_ACCOUNT_FILE=/run/secrets/google_sa.json
WHATSAPP_GRAPH_VERSION=v23.0
TELEGRAM_BOT_TOKEN, OPS_TELEGRAM_CHAT_ID
SENTRY_DSN, HEALTHCHECKS_PING_URL, LOG_LEVEL
OPERATOR_TEST_WA_IDS (números del operador que reciben respuesta de tenants en onboarding)
RESTIC_REPOSITORY, RESTIC_PASSWORD, credenciales del almacenamiento de backups (solo en el host)
```

**Tenants** (tabla `credential`, cifrada con **Fernet**; `MultiFernet` para rotar la clave sin cortar):

| Nombre | Uso | Cómo se guarda |
|---|---|---|
| `whatsapp.app_secret` | Verificar la firma HMAC de los webhooks | Cifrado |
| `whatsapp.access_token` | Enviar mensajes (token permanente de System User) | Cifrado |
| `whatsapp.verify_token` | Verificación inicial del webhook (`hub.verify_token`) | **Hash** (solo se compara, en tiempo constante) |

- Se escriben con `manage.py set_secret <slug> <nombre>` (lee de la entrada estándar, nunca de argumentos ni del historial del shell).
- Se descifran en memoria y se cachean 5 min por proceso.
- Los backups contienen solo texto cifrado; la clave Fernet no está en ellos.
- **Google Calendar: una cuenta de servicio de la plataforma** [DECIDIDO]. Cada negocio comparte su calendario con su email ("Hacer cambios en los eventos"). Un solo fichero JSON que custodiar en lugar de uno por negocio. Su alcance es solo `calendar.events`.

---

### 7. Runtime de mensajes

#### 7.1 Entrada idempotente

```
POST /webhooks/whatsapp/<app_public_id>
  1. app = registro[app_public_id]                       no existe → 404
  2. cuerpo ≤ 64 KB y JSON                               si no → 400
  3. verificar X-Hub-Signature-256 (HMAC-SHA256 con app_secret, tiempo constante)
                                                         falla → 401, sin guardar; cuenta para el límite por IP
  4. por cada elemento de entry[].changes[].value:
       tenant = registro.por_phone_number_id(metadata.phone_number_id)
                                                         desconocido o de otra app → se registra y se ignora
       tenant offboarded → nada
       tenant paused / degraded / onboarding (y no es el número de prueba) → guardar con status=ignored
       tenant_tx(tenant.id):
         INSERT inbound_event (kind=message|status, provider_event_id, payload)
           ON CONFLICT (tenant_id, provider_event_id) DO NOTHING
         si se insertó y kind=message → defer process_event(tenant_id, event_id), cola inbound, lock conv:<h>
         si se insertó y kind=status  → defer apply_status(tenant_id, event_id), cola inbound, sin candado
       COMMIT
  5. 200 OK
```

- `provider_event_id`: `wamid` para mensajes; `<wamid>:<status>` para avisos de estado.
- `h` = `sha256(tenant_id, wa_id)` truncado a 16 hex. **El candado nunca lleva el teléfono**: la tabla de trabajos de Procrastinate no tiene RLS.
- `GET /webhooks/whatsapp/<app_public_id>`: verificación inicial de Meta (`hub.verify_token` contra su hash).
- **Límite por contacto** (en `process_event`): más de 20 mensajes en 60 s de un mismo contacto → se guardan y no se responde, con un log. Evita bucles y coste.

#### 7.2 `process_event`

```python
# flowpilot/runtime/process.py  (pseudocódigo)
def process_event(tenant_id, event_id):                    # el trabajo recibe solo ids
    tenant = registry.get(tenant_id)
    with tenant_tx(tenant_id):                             # tx1: cargar
        event = InboundEvent.get(event_id)
        if event.status != "pending":
            return                                         # ya procesado (reintento tras COMMIT)
        msg = parse_message(event.payload)                 # → InboundMessage (core)
        contact = upsert_contact(msg)                      # wa_id, teléfono si lo hay, nombre de perfil
        conv = load_or_create_conversation(contact)
        state = effective_state(conv, tenant.pack, now)    # caducidad y versión de estado (§7.3)

    if global_command(msg) is not None:                    # MENU, BAJA… (§7.3)
        result = run_global_command(...)
    else:
        ctx = build_context(tenant, contact, state, event)     # sin transacción: aquí van las llamadas externas
        try:
            result = tenant.pack.handle_message(ctx, msg)
        except TransientError:
            raise                                          # Procrastinate reintenta (3 veces, 2 s → 30 s)
        except Exception:
            report_to_sentry(); result = recovery_result(tenant)   # texto seguro + estado reiniciado

    with tenant_tx(tenant_id):                             # tx2: persistir
        if not conv.save_state(result.state, expected_version=conv.version):
            raise ConversationChanged                      # otro escritor se coló → reintento desde tx1
        msgs = plan_sends(result.replies, contact, idem=f"reply:{event_id}")   # §7.4
        apply_actions(result.actions)                      # SendTemplate, NotifyOwner, UpdateContact
        event.mark_done()
        defer_sends(msgs)                                  # el trabajo solo existe si hay COMMIT
```

- **[DECIDIDO] Transacciones cortas.** Ninguna transacción queda abierta mientras se llama a Calendar o a Meta.
- **Error tras el último reintento** de un `TransientError` (p. ej. Calendar caído): el runtime envía el texto de recuperación ("Uy, ha habido un problema de conexión…", heredado de Peluquería), reinicia el estado y marca el evento `failed`. El contacto nunca se queda sin respuesta.
- `apply_status(tenant_id, event_id)`: busca el `outbound_message` por `wamid` (o por `biz_opaque_callback_data`) y actualiza estado, `pricing_category` y `billable`. No pasa por el pack.

#### 7.3 Conversación

- **Una fila por contacto** en `conversation` con `state` (JSON del pack), `state_version`, `version` (bloqueo optimista) y `last_inbound_at`.
- **Caducidad [DECIDIDO]:** si han pasado más de `pack.conversation_timeout_min` (30 min, como hoy) desde el último mensaje, el estado vuelve a `{}` y el pack empieza por su menú.
- **Versión del estado:** cada pack declara `state_version`. Si el estado guardado tiene otra (tras un despliegue que cambia su forma), se reinicia con amabilidad ("Perdona, he tenido que empezar de nuevo") y se registra. Sustituye al versionado por bloque del diseño anterior.
- **Comandos globales** (los resuelve el runtime, antes que el pack; comparación tras normalizar):
  - `menu`, `menú`, `inicio` → estado `{}` y el pack muestra su menú.
  - `baja` → `contact.opt_out = true` (no recibe plantillas: recordatorios ni confirmaciones) y se le confirma. `alta` lo revierte.
- **Mensajes no soportados** (audio, imagen, sticker, ubicación): el pack recibe `InboundMessage(type="unsupported")` y responde pidiendo texto o botones (como hoy).

#### 7.4 Salida

**`plan_sends`** (en `core/whatsapp_limits.py`, función pura):

1. Fusionar los textos consecutivos de un turno en un mensaje.
2. Si un texto va seguido de botones o lista, meterlo en el cuerpo del interactivo salvo que superen 1.024 caracteres juntos.
3. Validar límites de WhatsApp: botones ≤ 3 (título ≤ 20), lista ≤ 10 filas en total (título ≤ 24, descripción ≤ 72), texto ≤ 4.096. **Un pack que los incumple es un error de programación**: en tests falla; en producción se trunca y se registra.
4. **Ventana de 24 h:** las respuestas siempre van dentro (responden a un mensaje del contacto). Las plantillas son lo único que se envía fuera.
5. Crear un `outbound_message` por mensaje final, en orden (`seq`), con `idem_key = reply:<event_id>:<seq>`.

La fusión es obligatoria: desde el 1/10/2026 Meta cobra los mensajes de servicio (§11.5); menos mensajes, menos coste para el negocio.

**`send_message(tenant_id, outbound_id)`** (cola `outbound`, candado `out:<h>` para mantener el orden por contacto):

```
status == sent                     → terminar
status == unknown                  → no reenviar (lo resuelve un aviso de estado o el operador)
status == sending                  → el intento anterior se cortó a mitad → status = unknown
status = sending; attempts += 1; COMMIT
POST /<phone_number_id>/messages  (con biz_opaque_callback_data = outbound_id)
  2xx                              → sent, wamid
  400–499 salvo 429                → failed, sin reintento; 401/190 → alerta "token caducado" (§17.3)
  429, o 5xx con cuerpo de error   → pending; reintento con backoff (Meta no lo aceptó)
  timeout, red, 502/504 sin cuerpo → unknown (no sabemos si se aceptó)
```

- Un `unknown` **no bloquea** los siguientes envíos del mismo contacto.
- Si después llega un aviso de estado con ese `biz_opaque_callback_data`, pasa solo a `sent`. Los que sigan en `unknown` tras 10 min aparecen en el Admin con "Marcar enviado" y "Reenviar".
- Nunca se registra el cuerpo de una respuesta 4xx de Meta (puede contener datos personales).

#### 7.5 Colas y trabajos

| Cola | Trabajos | Candado | Reintentos |
|---|---|---|---|
| `inbound` | `process_event`, `apply_status` | `conv:<h>` en `process_event`; ninguno en `apply_status` | 3, backoff exponencial 2 s → 30 s |
| `outbound` | `send_message` (respuestas y plantillas), `send_notification` | `out:<h>` (mensajes a contactos); `owner:<tenant>` (avisos) | Según el error (§7.4) |
| `periodic` | Barridos de packs, `ops_check`, `retention_cleanup` | `queueing_lock` con el nombre y el tenant (nunca dos iguales pendientes) | 2 |

- **Un solo `worker` atiende las tres colas.** Las colas existen para ver de un vistazo qué se atasca y para poder separar un worker el día que haga falta, sin tocar código.
- Los trabajos reciben **solo ids**, nunca datos personales en argumentos ni candados.
- Trabajo que agota reintentos → `failed` en Procrastinate → visible en el Admin (integración de Procrastinate con Django) con "Reintentar" → alerta (§17.3).
- **Parada ordenada:** al desplegar, el `worker` recibe SIGTERM, deja de coger trabajos y termina los suyos (`stop_grace_period: 60s`). Lo que se corte se reintenta: todos los trabajos son idempotentes.

#### 7.6 Tareas periódicas y barridos

- Cada `Periodic` de un pack (§8.1) se registra como tarea periódica de Procrastinate de plataforma, que **reparte**: para cada tenant activo de ese pack (del registro en memoria), encola un trabajo `run_periodic(tenant_id, name, scheduled_at)` en `periodic`. Nunca un trabajo gigante para todos los tenants.
- Las periódicas de Procrastinate ya garantizan que un instante programado se encola una sola vez aunque haya varios workers.
- **Barridos [DECIDIDO]:** lo que depende de datos que cambia otra persona (citas que el dueño crea o mueve en Calendar) no se programa como una tarea por entidad. Un barrido periódico mira la ventana relevante y actúa sobre lo que encuentra con una **clave estable** por entidad (`ctx.idem.stable("reminder:<gcal_id>:<start>")`), guardada como `idem_key` única en `outbound_message`. Si la cita se mueve, cambia `start` y le toca otro recordatorio; si no, el barrido la vuelve a ver y no repite.
- Un barrido que se retrasa más de su `max_delay_min` (por defecto 60) se descarta y se registra: un recordatorio con horas de retraso es peor que ninguno.

---

### 8. Contrato de un pack

#### 8.1 Declaración

```python
# packs/salon/pack.py
from core.packs import Pack, Periodic
from .config import SalonConfig
from . import conversation, sweep, health

pack = Pack(
    name="salon",
    config_schema=SalonConfig,
    state_version=1,
    conversation_timeout_min=30,
    handle_message=conversation.handle,          # (ctx, InboundMessage) -> PackResult
    periodic=[Periodic("calendar_sweep", every_min=15, handler=sweep.run, max_delay_min=60)],
    needs_calendar=True,                          # el runtime le da ctx.calendar
    load_data=None,                               # sin datasets
    health=health.check,                          # (ctx) -> list[HealthIssue]
    templates=[                                   # plantillas que el negocio debe tener aprobadas
        TemplateSpec("confirmacion_cita", "es_ES", params=3, buttons=["payload"]),
        TemplateSpec("recordatorio_cita", "es_ES", params=2, buttons=["payload", "payload"]),
    ],
)
```

```python
# packs/registry.py
from packs.salon.pack import pack as salon
from packs.bus.pack import pack as bus
PACKS = {p.name: p for p in (salon, bus)}         # explícito: sin descubrimiento automático
```

`load_data(tenant, config, path) -> object` (solo `bus`): lee `tenants/<slug>/datasets/`, **valida** y devuelve objetos inmutables en memoria. Lanza `DataError` con la lista de errores si algo no valida.

#### 8.2 Lo que recibe y lo que devuelve

```python
@dataclass(frozen=True)
class PackContext:
    tenant: TenantInfo                 # id, slug, name, timezone
    config: BaseModel                  # SalonConfig / BusConfig ya validada
    data: object | None                # lo que devolvió load_data (bus: Horarios + Matcher)
    contact: ContactInfo | None        # id, wa_id, phone (puede ser None), display_name, opt_out
    state: Mapping[str, Any]           # estado actual (solo lectura); el nuevo va en el resultado
    clock: Clock                       # now() con zona del tenant; inyectable en tests
    calendar: CalendarPort | None      # solo si needs_calendar (salon)
    lock: Callable[[str], ContextManager]   # advisory lock de PostgreSQL por clave (§9.5)
    idem: IdemKeys                     # .event(name) ligada al evento; .stable(name) para barridos
    log: Logger                        # con tenant y event_id; enmascara teléfonos

@dataclass
class PackResult:
    replies: list[Reply] = []          # Text | Buttons | List   (core/replies.py)
    state: dict | None = None          # None = sin cambios; {} = reiniciar
    actions: list[Action] = []

# Acciones (core/actions.py)
SendTemplate(to: ContactRef, template: str, params: list[str], button_payloads: list[str], idem_key: str)
NotifyOwner(kind: str, text: str, idem_key: str)        # §12
UpdateContact(display_name: str | None = None, opt_out: bool | None = None)
```

- `InboundMessage`: `type` (`text` | `button` | `list` | `unsupported`), `text`, `payload` (id del botón o fila; también el `payload` de botones de plantilla), `received_at`.
- Un pack **nunca toca la BD ni las APIs directamente**: todo lo externo le llega por `ctx`.
- Los periódicos reciben `(ctx)` con `contact=None` y `state={}`, y solo devuelven `actions`.

#### 8.3 Utilidades comunes (`core/`)

| Módulo | Qué ofrece | Origen |
|---|---|---|
| `core/ui.py` | `trunc`, `button`, `row`, `section`, `buttons_msg`, `list_msg` (validan límites); `paginate(items, page, per_page=8, more_id, back_id)` | `interactive.py` de los dos bots |
| `core/text.py` | `normalize` (minúsculas, sin tildes, sin puntuación, espacios), `strip_html` | `parser._norm` / `_strip_html` de Peluquería; base de `formato.normalizar` de buscaBus |
| `core/dates.py` | `format_date_es`, `weekday_es`, `next_days`, zona horaria con `zoneinfo` | `slots.format_date_es` de Peluquería, `fechas.py` de buscaBus |
| `core/whatsapp_limits.py` | Constantes de límites y `plan_sends` | Nuevo (ambos bots aplicaban los límites a mano) |
| `core/testing/` | Arnés de conversación (§19.2), reloj fijo, `FakeCalendar` | Nuevo, a partir de los `conftest.py` de los dos bots |

**Regla:** una utilidad entra en `core` cuando la usan los dos packs. Lo que usa uno solo vive en su pack.

#### 8.4 Cómo se añade un pack

1. `packs/<nombre>/`: `pack.py`, `config.py` (pydantic con valores por defecto), `conversation.py` (máquina de estados), `messages.py` (textos), `tests/` (unit + escenarios).
2. Si usa un sistema externo: un `Protocol` en `ports.py` y su cliente en `integrations/`.
3. Si usa datasets: `load_data` con validador estricto y datos de ejemplo en `tests/fixtures/`.
4. Plantillas declaradas en `templates`.
5. Entrada en `packs/registry.py` y `docs/packs/<nombre>.md`.
6. **Escenarios obligatorios:** camino feliz de cada opción del menú + al menos 3 caminos de error.

---

### 9. Pack `salon` (peluquería)

#### 9.1 Conversación

Estados (heredados de `conversation.py` de Peluquería): `MENU → BOOK_SERVICE → BOOK_DAY → BOOK_PERIOD → BOOK_HOUR → BOOK_NAME`, `VIEW`, `CANCEL_SELECT`, `MOVE_SELECT` (+ el mismo flujo de reserva en modo `move` o `event`).

| Opción del menú | Flujo |
|---|---|
| **Pedir cita** | Comprueba el límite de citas futuras (`max_active_bookings`, 5; si Calendar falla, **falla en abierto**) → servicio (lista ≤ 9 + volver) → día (lista de días **con huecos** en `booking_window_days`, una sola lectura de Calendar por rango) → si las horas del día no caben en una lista, **mañana / tarde** → hora → nombre (texto ≤ 100 caracteres; si ya se conoce, botón "Usar <nombre>") → crea la cita (§9.5) → confirmación con servicio, precio, día y hora |
| **Ver mis citas** | Citas futuras del contacto (`list_contact_events`) |
| **Mover cita** | Elegir cita → servicio → día → hora → **crea la nueva y después cancela la antigua** (si la cancelación falla, la nueva queda, se avisa al dueño y se registra) |
| **Cancelar cita** | Elegir cita → cancelada al momento → aviso al dueño si lo tiene activado |
| **Cita {evento}** (solo si `special_event.active`) | Igual que Pedir cita, pero los días y franjas salen de `special_event.days` en lugar del horario semanal |
| **Contacto** (opcional, si `info_text` no está vacío) | Texto de la config (dirección, teléfono) |

- **Texto libre** fuera del paso de nombre → vuelve al menú (como hoy; pie de los interactivos: "Cualquier texto te llevará de vuelta al menú principal").
- **Botones de plantillas** (en cualquier estado): `reminder_confirm:<gcal_id>`, `reminder_cancel:<gcal_id>`, `booking_cancel:<gcal_id>`. Antes de actuar se comprueba que **la cita pertenece al contacto** que pulsa (por `fp_contact` o, en citas manuales, por teléfono); si no, "No se encontró esa cita".
  - Confirmar → `Estado: confirmada` en la descripción del evento (lo ve el dueño) → "¡Tu cita está confirmada!".
  - Cancelar → cancela (idempotente) → mensaje de cancelación → aviso al dueño si procede.
- Un hueco que se acaba de ocupar (`SlotTaken`, §9.5) → "Ese horario ya no está disponible" + **vuelve a ofrecer las horas libres de ese día**.

#### 9.2 Config

```python
# packs/salon/config.py
class Service(BaseModel):
    name: str = Field(max_length=24)          # cabe en una fila de lista
    price_eur: Decimal | None = None
    duration_min: int                         # ocupación del profesional: colisiones y duración del evento
    client_presence_min: int                  # tiempo del cliente en el local: última hora ofrecible

class SpecialEvent(BaseModel):
    active: bool = False
    name: str = ""                            # "Navidad 2026" → opción "Cita Navidad 2026"
    days: dict[date, list[TimeRange]] = {}    # franjas propias por día

class SalonConfig(BaseModel):
    business_name: str
    contact_phone: str
    calendar_id: str
    services: dict[str, Service]              # máx. 9 (lista de WhatsApp con "volver")
    opening_hours: WeeklyHours                # {martes: ["10:00-14:00","16:00-21:00"], …}; día ausente = cerrado
    slot_step_min: int = 30
    min_notice_min: int = 0
    booking_window_days: int = 21
    max_active_bookings: int = 5
    reminders_enabled: bool = False           # envios.recordatorios
    reminder_window_hours: tuple[int, int] = (23, 25)
    manual_confirmations_enabled: bool = False   # envios.confirmaciones
    manual_confirmations_since: datetime | None = None   # solo citas manuales creadas después (evita avisar del histórico)
    special_event: SpecialEvent = SpecialEvent()
    info_text: str = ""
    texts: SalonTexts = SalonTexts()          # textos con valores por defecto (los de messages.py de hoy)
```

Validaciones (portadas de `config.py` de Peluquería): franjas sin solapes y con formato `HH:MM`, `duration_min ≤ client_presence_min`, ≤ 9 servicios, nombres ≤ 24 caracteres, días del evento especial con franjas válidas. La ventana de búsqueda de citas del contacto se deriva (`booking_window_days + 1`), así desaparece el `lookaheads_dias` que había que mantener a mano.

#### 9.3 Google Calendar como fuente de verdad

`CalendarPort` (en `packs/salon/ports.py`; implementación en `integrations/google_calendar/`):

```python
class CalendarPort(Protocol):
    def list_events(self, calendar_id, start: datetime, end: datetime) -> list[CalEvent]
    def get_event(self, calendar_id, gcal_id) -> CalEvent | None
    def insert_event(self, calendar_id, event: NewEvent, gcal_id: str) -> CalEvent      # 409 → get_event
    def patch_description(self, calendar_id, gcal_id, fields: dict[str, str]) -> CalEvent
    def cancel_event(self, calendar_id, gcal_id) -> None                                # ya cancelado = ok
    def list_contact_events(self, calendar_id, contact_id, start, end) -> list[CalEvent]
    def check_access(self, calendar_id) -> None
# CalEvent: gcal_id, summary, description (texto limpio), start, end, all_day, created,
#           status, private (extendedProperties.private)
```

- Errores: `CalendarTransientError` (red, timeout, 5xx, 429; el cliente hace 2 reintentos rápidos y después lo lanza para que reintente el trabajo) y `CalendarPermanentError` (403/404: calendario no compartido o borrado → alerta "revisar acceso al calendario").
- Timeout 10 s por llamada.

**Formato de una cita creada por el bot:**

```
summary:      Corte de pelo - Lucía García              (<Servicio> - <Nombre>, como hoy)
description:  Nombre: Lucía García
              Telefono: +34600000001                    (solo si se conoce)
              Servicio: corte
              Estado: pendiente | confirmada
extendedProperties.private:
              fp_contact = <contact.id>   fp_key = <clave idempotente>   fp_service = corte
id:           determinista (§9.5)
```

**Reglas de lectura** (portadas de `parser.py` y `queries.py`):

- `[CFG] CERRADO` → día cerrado; `[CFG] VACACIONES` → todo el rango cerrado; `[CFG] HORARIO HH:MM-HH:MM` → horario de ese día. Prioridad: cerrado/vacaciones > horario especial > horario semanal.
- Eventos sin teléfono ni `fp_contact` → **bloqueos**: ocupan tiempo, no generan avisos.
- **Citas manuales**: sin `fp_key`, con `Telefono:` en la descripción. El servicio se deduce del título `<Servicio> - <Nombre>` (nombre o clave del servicio, sin tildes ni mayúsculas, el patrón más largo gana; alias heredados como "corte y barba").
- Descripciones editadas a mano: limpiar HTML (`<br>`, `<p>`, entidades) antes de leer campos; tolerante a mayúsculas, tildes y espacios.
- Días completos: `end.date` es exclusivo (iterar `d < end`).
- Lecturas por ventana: `singleEvents=true`, `timeMin`/`timeMax`, paginación con tope.
- **Siempre comprobar el resultado de una escritura.**
- **Compatibilidad con citas existentes:** las citas que creó el bot actual llevan `WaId:` y `Telefono:` en la descripción pero no `extendedProperties`. `tools/migrate_salon_events.py` (una vez, en la migración, §21) les añade `fp_contact`/`fp_key`; mientras tanto, `list_contact_events` también acepta coincidencia por `WaId:` o `Telefono:` (como `_event_matches` hoy).

#### 9.4 Huecos

Función pura `compute_slots(day, service, rules, busy, closures, now) -> list[time]` en `packs/salon/slots.py` (de `utils/slots.py` y `services/calendar/engine.py`):

- Franjas del día: horario semanal, sustituido por `[CFG] HORARIO` o por `special_event.days` en modo evento.
- Candidatas cada `slot_step_min` dentro de cada franja, de modo que `inicio + client_presence_min ≤ fin de franja` (unas mechas de 60 min de profesional y 180 de presencia no se ofrecen a las 19:00 si se cierra a las 21:00).
- Descarta las que solapan `[inicio, inicio + duration_min)` con un evento ocupado (tolerancia de ±1 min, como hoy).
- Hoy: descarta las que empiezan antes de `now + min_notice_min`.
- Mañana/tarde: si hay más de 8 horas, se parte por la pausa de mediodía de la franja (o a las 14:00 si no hay pausa).

#### 9.5 Reservar sin dobles reservas

El candado por conversación no impide que **dos contactos** cojan el mismo hueco a la vez, y Google Calendar no impide solapes. **[DECIDIDO]**:

1. `with ctx.lock(f"cal:{calendar_id}:{day}")`: advisory lock de sesión de PostgreSQL (`pg_try_advisory_lock` en bucle, máx. 10 s, en una conexión sin transacción abierta, liberado en `finally`). Sin lock en 10 s → `TransientError`.
2. Dentro del lock: `get_event(id determinista)` → si existe y no está cancelado, **éxito** (es un reintento de una reserva ya hecha).
3. Leer los eventos del día y comprobar que `[start, start + duration_min)` sigue libre → si no, `SlotTaken`.
4. `insert_event` con el id determinista; un 409 → `get_event` y devolverlo.

- **Id determinista:** `base32hex(sha256(f"{tenant_id}:{ctx.idem.event('booking')}"))[:32]` en minúsculas (Google exige base32hex, 5–1024 caracteres). El mismo evento entrante reprocesado produce el mismo id: **no hace falta tabla de efectos**.
- No protege contra una cita que el dueño cree a mano en ese mismo segundo: aceptado (la ve y decide).

#### 9.6 Barrido de Calendar (`calendar_sweep`, cada 15 min por tenant)

Una lectura de `[now, now + booking_window_days + 1]` y dos pasadas:

| Pasada | Condición | Acción |
|---|---|---|
| **Recordatorios** (`reminders_enabled`) | Cita (del bot o manual con teléfono) que empieza dentro de `reminder_window_hours`; contacto sin `opt_out` | `SendTemplate("recordatorio_cita", [fecha, hora], payloads=[reminder_confirm:<id>, reminder_cancel:<id>])`, clave `reminder:<gcal_id>:<start>` |
| **Confirmaciones de citas manuales** (`manual_confirmations_enabled`) | Cita manual con teléfono, `created ≥ manual_confirmations_since`, que empieza en el futuro | `SendTemplate("confirmacion_cita", [nombre, fecha, hora], payloads=[booking_cancel:<id>])`, clave `confirm:<gcal_id>` |

- **Destinatario:** en citas del bot, el contacto de `fp_contact` (su `wa_id`); en citas manuales, el teléfono de la descripción (se crea el contacto si no existe).
- Las claves estables viven en `outbound_message.idem_key` (única por tenant): el barrido puede correr cien veces y cada aviso sale una vez.
- Tras enviar una confirmación manual, el barrido escribe `Estado: pendiente` en la descripción si no lo tenía (para que el dueño vea que se avisó).
- Contactos con `opt_out` no reciben plantillas.

#### 9.7 Plantillas

Las crea el operador en el WhatsApp Manager del negocio durante el alta (tardan de 1 a 48 h en aprobarse). Textos actuales:

| Nombre | Categoría | Cuerpo | Botones (respuesta rápida) |
|---|---|---|---|
| `confirmacion_cita` | Utility | "Hola {{1}}, tu cita ha sido confirmada para el {{2}} a las {{3}}. Si necesitas cancelarla, pulsa el botón." | Cancelar cita |
| `recordatorio_cita` | Utility | "Recuerda que tienes cita el {{1}} a las {{2}}. ¿Confirmas tu asistencia?" | Confirmar · Cancelar |

`pack.health()` comprueba en el arranque y cada día que las plantillas declaradas existen aprobadas en la WABA del negocio (llamada de lectura a la Graph API) y que el calendario es accesible.

#### 9.8 Escenarios obligatorios

Reserva completa · día sin huecos · mañana/tarde · `SlotTaken` (vuelve a ofrecer las horas del día) · límite de 5 citas · Calendar caído al pedir cita (falla en abierto) y al crear (mensaje de recuperación) · cierre `[CFG]` y vacaciones · horario especial · servicio con presencia larga cerca del cierre · mover cita · cancelar cita · evento especial activo e inactivo · recordatorio enviado una sola vez en dos barridos · confirmación de cita manual (y no de las anteriores a `manual_confirmations_since`) · botón de recordatorio sobre una cita ajena · `baja` → sin recordatorios · cita antigua con `WaId:` sin `extendedProperties`.

---

### 10. Pack `bus` (horarios de autobús)

Se porta el código de buscaBus casi tal cual: `services/horarios/` (modelo, formato, loader, query, calendario, diff, datos), `utils/matcher.py`, `utils/fechas.py`, `handlers/flujo.py`, `utils/messages.py`, sus constructores de `interactive.py`, `tools/` y sus tests. Cambia el pegamento: entra por `PackContext`, el estado se guarda en BD y los datos se cargan por tenant.

#### 10.1 Dataset `timetable`

```
tenants/<slug>/datasets/timetable/
  paradas.yaml          localidades (id, nombre, alias, pendientes) y paradas (código, nombre, localidad);
                        pares no vendibles
  observaciones.yaml    catálogo de observaciones (letra, tipo condición/aviso, ámbitos, texto exacto)
  calendario.yaml       vigencia, festivos generales y locales, periodo escolar, días sin servicio en ninguna línea
  lineas/<id>.yaml      temporadas (cubren el año sin huecos ni solapes), tablas por temporada y clase
                        de día, viajes con horas (HH:MM o llegada>salida), observaciones y `bus:<id>`
```

El formato es **exactamente el de `buscaBus/horarios/`** (su `design.md` §2.3 se copia a `docs/packs/bus.md`). Lo existente se mueve sin conversión.

- **Validador estricto** (`packs/bus/formato.py`, único para herramientas, tests y carga): las ~30 reglas actuales (parada, letra u observación sin definir; horas que retroceden; temporadas que no cubren el año; `bus:` incoherente; alias vacíos o repetidos; ids de línea; pendientes mal formados…). **Nada ambiguo pasa**: cada error dice fichero, tabla, fila y motivo; los avisos (posible mismo autobús no declarado, clases de día sin datos, pendientes abiertos) se listan sin bloquear.
- **`load_data`** convierte el dataset en objetos inmutables (`Localidad`, `Parada`, `Observacion`, `Linea`, `Temporada`, `Tabla`, `Viaje`, `Paso`) e índices (`localidad_paradas`, `localidad_viajes`, `festivos_por_linea`, `lineas_pueblos`) + el `Matcher`. Todo en memoria: unos MB por tenant.
- **Ciclo de actualización** (como hoy, por tenant):
  1. La empresa comunica un cambio → se edita la fila en `tenants/<slug>/datasets/timetable/lineas/…`.
  2. `make bus-formatear TENANT=<slug>` y `make bus-validar TENANT=<slug>`.
  3. `make bus-revision TENANT=<slug>` → `revision/<slug>/horarios.html` y `.pdf` (no se versionan) con **cambios desde la versión publicada** en lenguaje de negocio.
  4. La empresa confirma el PDF → PR → CI valida → merge → despliegue → `make bus-publicar TENANT=<slug>` crea el tag `datos/<slug>/AAAA-MM-DD` (base del próximo diff).
- Cambios con fecha futura no se modelan: se publican el día que entran en vigor.

#### 10.2 Motor de consulta

Entrada `(origen, destino, fecha)`; salida ordenada de salidas con hora de salida (del `Paso` de origen), llegada (del `Paso` de destino), duración, parada y notas. Sin E/S.

0. Casos previos, en este orden: par **no vendible** → `no_vendible`; ninguna línea conecta el par → `sin_trayecto`; día sin servicio en ninguna línea → `sin_servicio`; fecha fuera de vigencia → `sin_datos`.
1. Calendario de esa fecha **por línea**: temporada, clase de día (laborable / sábado / domingo y festivos, con festivos locales solo en las líneas que pasan por esa localidad), lectivo, mes.
2. Filtrar viajes por línea, temporada, clase de día y condiciones (con ámbito de línea, viaje o parada de un viaje).
3. Par válido: el viaje para en una parada del origen y, **más adelante en su orden**, en una del destino.
4. **Fusión del mismo autobús**: mismas horas del par en líneas distintas → una sola salida con las notas de ambas.
5. Orden por hora de salida; si es hoy, las ya pasadas no se listan y se cuentan ("hoy ya han salido N").
6. Si alguna línea implicada no tiene datos ese día, el resultado lo dice: **`sin_datos` nunca se presenta como "no hay servicio"**.
7. **Nunca inventa trasbordos.**

#### 10.3 Conversación

```
MENÚ [🚌 Ver horarios] [ℹ️ Información]
  → ORIGEN    lista: pueblos_menu_inicio (8) + ✍️ Otro pueblo + ↩️ Volver al menú
  → DESTINO   solo alcanzables desde el origen y vendibles; ≤ 9 → lista completa;
              si no, 8 más relevantes (Córdoba primero) + ✍️ Otro destino + ↩️ Cambiar origen
  → DÍA       7 días con "N salidas · de HH:MM a HH:MM" / "próxima HH:MM" / "sin servicio" /
              "horario no disponible" (+ "festivo · " y "· puede haber más") + 📅 Otra fecha
  → RESULTADO [📅 Otro día] [🔄 Ver la vuelta] [🔍 Otra consulta]
```

Estados: `MENU → SEL_ORIGEN → SEL_DESTINO → SEL_DIA → RESULTADO` + `ESCRIBIR_ORIGEN`, `ESCRIBIR_DESTINO`, `ESCRIBIR_FECHA`, `CONFIRMAR_PUEBLO`, más la navegación de líneas y pueblos.

- **Matcher** (normalización del bus: la común + sin artículos ni `de`/`del` + sin relleno inicial `desde`, `a`, `hacia`, `para`, `voy a`): exacto → prefijo del nombre entero (≥ 3 letras) → errata Damerau-Levenshtein (≤ 1 hasta 5 letras, ≤ 2 si es más larga). Única → continúa (una errata se **confirma** con Sí/No); 2–3 → botones; 4–9 → lista; >9 → "sé más concreto"; ninguna → "No conozco ese pueblo" + **Ver pueblos por línea**. Un alias compartido (`villafranca`) **siempre pregunta**. Se busca entre todas las localidades también en el destino (para responder "sin trayecto" y no "no conozco"). Dos pueblos en un mensaje no se interpretan.
- **Ver pueblos por línea**: líneas (8 por página + "Más líneas" + volver) → pueblos de la línea (8 + "Ver más" + "Volver a líneas"); en el destino, solo líneas que salen del origen y pueblos alcanzables.
- **Localidades pendientes**: "Algunos autobuses paran en X, a unos N minutos de Y, pero aún no tenemos su hora de paso." + `Usar Y` / `Otro pueblo`.
- **Fechas en formato cerrado** `día/mes[/año]` (separadores `/ - . espacio`; año de 2 cifras = 20xx). Nada de lenguaje natural ("mañana", "el viernes"). Sin año: si esa fecha pasó hace ≤ 30 días → "Esa fecha ya ha pasado"; si no, la próxima vez que llega.
- **Resultado**: cabecera con trayecto, día y temporada (solo si es una única temporada con nombre público) o festivo; salidas `HH:MM → HH:MM (1h 20)`; parada de salida; nota que afecta a todas como `⚠️` al final y las que afectan a algunas con marcas ¹ ² ³; corte a 4.096 caracteres con "…y N salidas más, llama al <teléfono>". Sin salidas → siguiente día con salidas en 45 días (con botón); 25/12 y 01/01 → "no hay servicio en ninguna línea" + teléfono y horario de oficina.
- **Información**: teléfono, horario de oficina por días (solo se muestra; el bot nunca calcula si está abierta) y enlaces no vacíos.
- Textos no reconocidos (pueblo o fecha) se registran con el **texto normalizado y el paso, nunca con el teléfono**.
- Sin IA. Sin plantillas. Sin periódicas.

#### 10.4 Config

```python
class OfficeHours(BaseModel):
    days: list[Weekday]
    ranges: list[TimeRange]

class BusConfig(BaseModel):
    business_name: str
    contact_phone: str
    office_hours: list[OfficeHours] = []
    links: dict[Literal["web", "compra_online", "bonos", "pdf_horarios"], HttpUrl] = {}
    start_menu_towns: list[str] = Field(max_length=8)     # nombres de localidades; deben existir en el dataset
    next_day_search_days: int = 45
```

`load_data` comprueba además que cada pueblo de `start_menu_towns` existe en el dataset.

#### 10.5 Escenarios obligatorios

Las pruebas actuales de buscaBus se portan (`test_formato`, `test_diff`, `test_formatear`, `test_revision`, `test_loader`, `test_query` con sus pruebas doradas, `test_calendario`, `test_matcher`, `test_fechas`, `test_conversation`, `test_interactive`) con sus fixtures. Escenarios de conversación: consulta completa · "Ver la vuelta" · "Otro día" · día sin servicio con siguiente día · `sin_datos` · no vendible · sin trayecto directo · origen = destino · Villafranca (también con errata) · errata confirmada y rechazada · ver pueblos por línea con paginación · localidad pendiente · fecha pasada · 25/12 · hoy sin salidas restantes · "Otra fecha" con texto inválido · resultado de más de 4.096 caracteres.

---

### 11. WhatsApp

#### 11.1 Modo de conexión

**`client_app` [DECIDIDO]:** la app de Meta, la WABA y el número están **en el Business Portfolio del negocio**; el operador es administrador y hace el alta. El coste de Meta lo paga el negocio con su tarjeta. Así lo hacen hoy los dos bots.

Meta configura el webhook **por app**: la URL lleva el `app_public_id` (para elegir el `app_secret`) y el tenant se resuelve por `metadata.phone_number_id`, comprobando que el número pertenece a esa app.

[FUTURO] `platform_app` (Tech Provider + Embedded Signup): una app de plataforma, una URL para todos; cambia solo el enrutado.

**Checklist de alta** (de los README de los dos bots):

1. **SIM del negocio** con un número que no tenga WhatsApp activo (si lo tiene, darlo de baja antes).
2. **Gmail del negocio** (a su nombre).
3. **Business Portfolio** del negocio, con el operador como administrador. **Verificación de empresa** cuanto antes (2–5 días hábiles; necesaria para el nombre visible, que no se aprueba sin web activa).
4. **App** de Meta tipo Business en ese portfolio, con el producto WhatsApp.
5. Número registrado y verificado; app suscrita a la WABA (`POST /<WABA_ID>/subscribed_apps`); webhook `https://api.<dominio>/webhooks/whatsapp/<app_public_id>` con su `verify_token`; campo `messages` suscrito.
6. **System User** con **token permanente** (`whatsapp_business_messaging` y `whatsapp_business_management`). El token temporal caduca en 24 h: nunca en producción.
7. **Plantillas** del pack creadas pronto (1–48 h).

#### 11.2 Entrada

- Elementos de `value.messages[]`: `text`, `interactive.button_reply`, `interactive.list_reply`, `button` (respuesta a un botón de plantilla, con `button.payload`) y el resto (`audio`, `image`, `document`, `sticker`, `location`…) como `unsupported`.
- Elementos de `value.statuses[]`: `sent`, `delivered`, `read`, `failed`, con `pricing` y `biz_opaque_callback_data`.
- **Identidad del contacto:** `wa_id` = `user_id` (BSUID, formato `^[A-Z]{2}\.[A-Za-z0-9]{1,128}$`) si viene; si no, `from` (teléfono, 7–15 dígitos). `phone_e164` solo si `from` es un teléfono. Validación de formatos como en `webhook.py` de Peluquería.
- Límites de entrada (de Peluquería): texto truncado a 4.096; id interactivo ≤ 256 (si no, se ignora).

#### 11.3 Salida

- `POST https://graph.facebook.com/<versión>/<phone_number_id>/messages`; la versión va en configuración, nunca en el código (hoy `v23.0`; [VERIFICAR] su fecha de caducidad, previsiblemente 2027).
- Tipos: `text`, `interactive` (`button`, `list`), `template`.
- Todo envío lleva `biz_opaque_callback_data = outbound_id`.
- Cliente `httpx` con *pool* de conexiones, timeout 10 s; reintentos y estados según §7.4.

#### 11.4 Límites de mensajes de Meta

Los límites de Meta se aplican a contactos únicos **fuera de la ventana de atención** en 24 h. Las respuestas no cuentan; solo las plantillas (recordatorios y confirmaciones). Con los volúmenes de una peluquería, el límite inicial de una cuenta nueva no es un problema.

#### 11.5 Costes

Desde el **1/10/2026**, Meta cobra por mensaje también los **mensajes de servicio** (respuestas dentro de la ventana), al precio de la categoría *utility* del país ([página oficial](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/non-template-messages)). El tramo gratuito de 1.000 mensajes al mes que citan algunos blogs **no aparece en la documentación oficial: no se cuenta con él**. La tarifa de España (~0,017 €/mensaje según proveedores) [VERIFICAR en la cuenta de cada negocio].

Consecuencias de diseño:

- Fusión de mensajes obligatoria (§7.4) y flujos con pocos turnos.
- `outbound_message` guarda `pricing_category` y `billable` de los avisos de estado; el Admin muestra mensajes facturables por tenant y mes.
- **Alerta 🟡** cuando un tenant supera el umbral mensual que tenga configurado (`whatsapp.monthly_alert_threshold`, por defecto 2.000), para avisar al negocio antes de la factura.
- Palancas ya identificadas en buscaBus si el coste aprieta: fusionar el menú con la primera pregunta, recordar el último pueblo, aceptar "Pozoblanco a Córdoba" en un mensaje. Ninguna en la v1.

---

### 12. Avisos al dueño y alertas de operación

> **En pocas palabras.** Un único bot de Telegram de la plataforma, **solo de salida**. Lo usan los packs para avisar al dueño (opcional) y la plataforma para avisar al operador de problemas. No tiene webhook: no hay endpoint público que proteger.

- **`NotifyOwner(kind, text, idem_key)`**: si el tenant tiene `owner.telegram_chat_id` y `kind` está en `owner.notify`, se guarda en `notification` (único por `idem_key`) y se entrega por la cola `outbound`. Si no, se registra y no se envía.
- Tipos que emite `salon`: `booking_created`, `booking_cancelled`, `booking_moved`, `move_cancel_failed`. `bus` no emite ninguno.
- **Vinculación:** `manage.py telegram_link <slug>` genera un código; el dueño envía `/start <código>` al bot; el comando lee `getUpdates`, muestra su `chat_id` y el operador lo añade al `tenant.yaml`. (El bot no tiene webhook, así que `getUpdates` está disponible.)
- **Alertas de operación**: mismo bot, al chat `OPS_TELEGRAM_CHAT_ID`, enviadas por `ops_check` (§17.3). No pasan por la tabla `notification` (pueden ser de plataforma, sin tenant); se deduplican con un enfriamiento de 30 min por tipo en la caché de Django (en BD).
- [FUTURO] Comandos del dueño (`/vacaciones`, `/bloquear`), respuesta a derivaciones.

---

### 13. Datos

#### 13.1 Modelo

Tablas con 🔒 llevan `tenant_id` y RLS. Claves primarias **UUIDv7** (`uuidv7()` de PostgreSQL 18). Fechas `timestamptz`. Las tablas padre tienen `UNIQUE(tenant_id, id)` y las hijas usan **claves foráneas compuestas** `(tenant_id, x_id)`: es imposible que un mensaje de A apunte a un contacto de B.

```text
tenant 🔒*        id, slug, name, pack, status, timezone, synced_at          (reflejo de tenants/*.yaml)
credential 🔒     id, tenant_id, name, ciphertext, created_at, rotated_at    UNIQUE(tenant_id, name)

contact 🔒        id, tenant_id, wa_id, phone_e164 NULL, display_name, opt_out, opt_out_at,
                  last_activity_at, created_at                               UNIQUE(tenant_id, wa_id)
conversation 🔒   id, tenant_id, contact_id, state jsonb, state_version, version,
                  last_inbound_at, updated_at                                UNIQUE(tenant_id, contact_id)

inbound_event 🔒  id, tenant_id, provider_event_id, kind[message|status], payload jsonb,
                  status[pending|done|failed|ignored], error, received_at, processed_at
                                                                             UNIQUE(tenant_id, provider_event_id)
outbound_message 🔒  id, tenant_id, contact_id, idem_key, seq, kind[text|interactive|template],
                  payload jsonb, status[pending|sending|sent|failed|unknown], attempts, wamid,
                  pricing_category, billable, last_error, inbound_event_id NULL, created_at, sent_at
                                                                             UNIQUE(tenant_id, idem_key)
notification 🔒   id, tenant_id, idem_key, kind, text, status[pending|sent|failed], created_at, sent_at
                                                                             UNIQUE(tenant_id, idem_key)
```

\* `tenant` tiene RLS sobre su propio `id`.

Más las tablas de Procrastinate (sin `tenant_id` ni RLS: por eso los trabajos solo llevan ids) y las de Django (usuarios del Admin, sesiones, caché, `LogEntry`).

**No hay tablas de citas ni de horarios:** las citas viven en Google Calendar; los horarios, en git y en memoria. Si un pack necesita tablas propias algún día, irán en `flowpilot/` con `tenant_id`, RLS y acceso desde el pack por un `Protocol` en `ctx` (como `calendar`).

#### 13.2 Aislamiento entre negocios (RLS)

| Rol de PostgreSQL | Lo usa | `BYPASSRLS` | Permisos |
|---|---|---|---|
| `fp_owner` | `migrate` | — (dueño de las tablas) | DDL |
| `fp_app` | `web`, `worker` | **No** | SELECT/INSERT/UPDATE/DELETE |
| `fp_admin` | `admin` (solo accesible por túnel SSH) | **Sí** | SELECT/INSERT/UPDATE/DELETE |

```sql
ALTER TABLE contact ENABLE ROW LEVEL SECURITY;
ALTER TABLE contact FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON contact
  USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
```

- `NULLIF(…, '')` es necesario: con conexiones persistentes, tras un `SET LOCAL` las transacciones siguientes ven `''` (no NULL), y `''::uuid` daría error en lugar de "0 filas".
- **El tenant solo se fija con `tenant_tx(tenant_id)`**: abre una transacción corta y ejecuta `set_config('app.tenant_id', …, true)` (= `SET LOCAL`). Nunca se anida (`assert not connection.in_atomic_block`). Sin tenant fijado se ven 0 filas: si alguien lo olvida, falla de forma segura.
- **Ya no hacen falta funciones `SECURITY DEFINER`**: el enrutado de webhooks y la lista de tenants salen del registro en memoria (§6.3), no de la BD.
- El servicio `admin` usa `DB_ADMIN_URL` (`fp_admin`); `web` y `worker` no tienen esa URL. Es la única puerta para ver datos de varios tenants a la vez.
- **Test genérico de aislamiento** (bloquea el merge): recorre todas las tablas con `tenant_id` y comprueba, con tenants A y B, que A no lee, modifica, borra ni inserta filas de B, ni crea FKs hacia B, y que sin tenant se leen 0 filas. Una tabla nueva sin política hace fallar el test.

#### 13.3 Retención [DECIDIDO inicialmente; se ajusta en el contrato de encargo de cada negocio]

| Dato | Retención | Cómo |
|---|---|---|
| `inbound_event.payload` | 30 días | `retention_cleanup` nocturno, por lotes de 1.000: vacía el payload, conserva metadatos |
| Filas de `inbound_event` | 90 días | Borrado |
| `outbound_message.payload` | 30 días | Se vacía |
| Filas de `outbound_message`, `notification` | 12 meses | Borrado (las claves de barridos ya no sirven pasado ese plazo) |
| `conversation.state` | Al caducar (30 min) | El estado caducado se vacía en el siguiente mensaje o en la limpieza nocturna |
| `contact` | 12 meses sin actividad | Borrado (con su conversación y sus mensajes) |
| Backups | 6 meses (copias mensuales) | Política de restic (§15.4); se informa en el contrato |
| Tenant dado de baja | Exportación + borrado en ≤ 30 días | §18.2 |

Derechos RGPD: `manage.py export_contact <slug> <wa_id|teléfono>` y `forget_contact` (borra contacto, conversación, eventos y mensajes; las citas del calendario son del negocio).

#### 13.4 Migraciones

- Siempre **compatibles con la versión anterior** del código (expand → desplegar → contract en otro despliegue). Prohibido en un paso: renombrar o borrar columnas en uso, `NOT NULL` sin valor por defecto en tablas grandes, cambios de tipo que bloqueen la tabla.
- CI: `makemigrations --check` + `django-migration-linter`.
- **Las migraciones que tocan RLS, roles o borran datos requieren aprobación humana explícita.**

---

### 14. Seguridad

| Punto | Protección |
|---|---|
| Webhooks de WhatsApp | Firma HMAC-SHA256 **antes de nada**, en tiempo constante; cuerpo ≤ 64 KB; URL con `app_public_id` aleatorio (nunca ids internos); límite por IP solo de peticiones con firma inválida (Meta envía desde IPs compartidas); validación de formatos de identificador |
| Superficie pública | Caddy solo enruta `/webhooks/whatsapp/*` y `/health`; todo lo demás, 404. El Admin no está publicado: escucha en `127.0.0.1` y se usa con `ssh -L` (`make admin-tunnel`) |
| Admin | Login de Django con contraseña fuerte + 2FA (`django-otp`), aunque solo sea accesible por túnel; cada cambio queda en `LogEntry` |
| Servidor | Acceso SSH solo con clave; sin contraseña ni root directo; cortafuegos que solo abre 22, 80 y 443; actualizaciones de seguridad automáticas (`unattended-upgrades`); `fail2ban` en SSH |
| Base de datos | Sin puerto publicado (solo red interna de Compose); tres roles con mínimo privilegio (§13.2) |
| Contenedores | Usuario no root; sistema de ficheros de solo lectura salvo `/tmp`; sin socket de Docker montado |
| Secretos | §6.4. Nunca en git, logs, imágenes, argumentos de trabajos ni respuestas HTTP |
| Logs | Filtro que enmascara tokens, cabecera `Authorization` y teléfonos (últimos 4 dígitos) |
| Dependencias | `uv.lock`; Dependabot; `pip-audit` en CI; imagen base actualizada mensualmente |
| Datos de salud | Fuera del alcance: no se piden en ninguna conversación |

**Datos que cruzan cada frontera:**

| Frontera | Qué cruza | Protección |
|---|---|---|
| Internet → `web` | Avisos de Meta (mensajes, estados) | Firma verificada antes de guardar; tenant por `phone_number_id` |
| `web` → cola | Solo ids (`tenant_id`, `event_id`) y candados con hash | — |
| Cola → `worker` → BD | Datos del tenant | `tenant_tx` + RLS |
| `worker` → Meta / Google / Telegram | Solo lo necesario para el envío o la cita | Credenciales descifradas solo en memoria; HTTPS |
| Operador → `admin` | Todo | Túnel SSH + login + 2FA |
| VPS → backups | Volcado de la BD | Cifrado por restic antes de salir; credenciales solo en el host |

---

### 15. Infraestructura: una VPS con Docker Compose

> **En pocas palabras.** Una máquina virtual en un proveedor europeo ejecuta todo con Docker Compose: la web, el worker, el admin, PostgreSQL y Caddy (que pone el HTTPS solo). Copias de seguridad cifradas cada 6 horas a otro proveedor. Cuesta unos 15–20 € al mes y se recrea desde cero en menos de 2 horas con un script.

#### 15.1 Máquina

- **Proveedor [DECIDIDO, precio VERIFICAR]:** Hetzner Cloud, ubicación UE (Núremberg, Falkenstein o Helsinki). Plan con **2 vCPU, 4 GB de RAM y 40 GB de disco** (familia CX/CAX). Alternativas equivalentes: OVHcloud, IONOS (tiene centro de datos en España si un cliente exige datos en España), Scaleway.
- **Sistema:** Ubuntu 24.04 LTS (soporte hasta 2029), Docker Engine + plugin Compose.
- **Reparto de memoria estimado:** PostgreSQL ~0,8 GB (`shared_buffers=512MB`), `web` ~0,3 GB, `worker` ~0,4 GB (datasets en memoria), `admin` ~0,2 GB, Caddy ~0,05 GB. Sobra la mitad.
- **Dominio propio** (~10–15 €/año): `api.<dominio>` apunta a la IP fija de la VPS. Sustituye a DuckDNS.
- **Instantáneas del proveedor** (backup diario de la VM, +20 % del precio): segunda red de seguridad para recuperar la máquina entera; no sustituye a §15.4.

#### 15.2 Servicios de Compose

```yaml
# compose.prod.yaml (resumen)
services:
  caddy:   image: caddy:2 · ports 80, 443 · volúmenes caddy_data, caddy_config · Caddyfile
  web:     image: ghcr.io/marianodelrio/flowpilot:<sha> · command: gunicorn … · env_file .env (sin DB_ADMIN_URL ni DB_OWNER_URL)
           healthcheck: GET /health
  worker:  misma imagen · command: manage.py procrastinate worker … · stop_grace_period: 60s
  admin:   misma imagen · command: gunicorn config.wsgi_admin … · ports "127.0.0.1:8081:8081"
  migrate: misma imagen · profiles: [deploy] · command: migrate + sync_tenants
  db:      image: postgres:18 · volumen pgdata · sin ports · healthcheck pg_isready
           config: shared_buffers 512MB, max_connections 100, log_min_duration_statement 1s
x-common: restart: unless-stopped · logging json-file max-size 20m, max-file 5 · read_only + tmpfs /tmp
```

`compose.yaml` (local) usa los mismos servicios con la imagen construida en local, `runserver` y el worker con recarga automática, y sin Caddy.

#### 15.3 Caddy

```
api.<dominio> {
    encode gzip
    @public path /webhooks/whatsapp/* /health
    handle @public { reverse_proxy web:8000 }
    handle { respond 404 }
    request_body { max_size 64KB }
}
```

- Certificados de Let's Encrypt automáticos y renovados por Caddy.
- `X-Forwarded-For` lo pone Caddy; Django confía solo en él (`TRUSTED_PROXIES` = red de Compose) para el límite por IP.

#### 15.4 Backups y restauración

| Qué | Cómo | Cuándo | Retención |
|---|---|---|---|
| PostgreSQL | `pg_dump -Fc` (desde el contenedor `db`) → `restic backup` → **almacenamiento S3 compatible de otro proveedor** (Backblaze B2 o Cloudflare R2), cifrado por restic | Cada 6 h (timer de systemd en el host, `deploy/backup.sh`) | 7 diarias, 4 semanales, 6 mensuales (`restic forget --prune`) |
| `.env` y JSON de Google | Copia en el gestor de contraseñas del operador | Al cambiar | — |
| Config y datasets | Git (GitHub) | Siempre | Indefinida |
| VM completa | Instantánea diaria del proveedor | Diaria | 7 |

- El backup termina con un ping a healthchecks.io (`/backup`): si no llega en 7 h, alerta (un backup que falla en silencio no existe).
- **`deploy/restore.sh <snapshot>`**: VPS nueva → Docker → clonar repo → `.env` → `restic restore` → `pg_restore` → `docker compose up` → cambiar DNS. Objetivo **RTO ≤ 2 h**.
- **Simulacro trimestral** (runbook): restaurar el último backup en una VPS temporal (o en local), comprobar conteos por tenant, borrarla y anotar el resultado y el tiempo.
- **RPO ≤ 6 h.** Lo que se puede perder son conversaciones en curso y registros: las citas están en Google Calendar y los horarios en git.

#### 15.5 Costes [ESTIMACIÓN; VERIFICAR precios actuales]

| Pieza | €/mes |
|---|---:|
| VPS 2 vCPU / 4 GB / 40 GB (Hetzner) | ~5–9 |
| Instantáneas del proveedor (+20 %) | ~1–2 |
| Almacenamiento de backups (B2 o R2, pocos GB) | ~0–1 |
| Dominio | ~1 |
| Sentry (plan gratuito), healthchecks.io (gratuito), UptimeRobot o Better Stack (gratuito), GitHub (GHCR y Actions en repo privado, cuota gratuita) | 0 |
| **Total** | **~8–13 €/mes**; con una VPS de 8 GB, ~15–20 €/mes |

Fuera de la cifra: mensajes de WhatsApp (los paga cada negocio en su cuenta de Meta, §11.5); Google Calendar API (gratuita al volumen previsto, [VERIFICAR] anuncios de Google sobre cuotas).

#### 15.6 Cómo evoluciona sin rediseñar

| Señal | Acción | Esfuerzo |
|---|---|---|
| CPU o RAM > 70 % sostenido | Subir de plan la VPS (reinicio de minutos) | Bajo |
| Cola `inbound` con trabajos esperando > 30 s | Subir la concurrencia del worker o añadir un segundo servicio `worker` | Config |
| Barridos retrasan respuestas | `worker-periodic` aparte con `--queues periodic` | Config |
| >15–20 tenants, o un negocio que dependa del servicio en horas críticas | PostgreSQL gestionado (con réplica y PITR) + 2 VPS de aplicación detrás de un balanceador. La aplicación no cambia: es la misma imagen | Proyecto acotado |
| Datos obligatoriamente en España | Mover a IONOS (Logroño) u otro proveedor con centro en España: es una restauración (§15.4) | Bajo |

---

### 16. Construcción y despliegue

#### 16.1 La imagen

- Un `Dockerfile` multi-etapa: dependencias con `uv` → imagen final mínima con Python 3.14, usuario no root.
- Incluye `src/` y `tenants/` (la config va con el código: una versión de imagen = un estado coherente de código y datos).
- Etiqueta = SHA del commit. Se publica en **GHCR** (registro de GitHub).
- Estáticos del Admin con WhiteNoise.

#### 16.2 Pipeline (GitHub Actions)

```
on: pull_request      → ci.yml: puertas de §19.3

on: push a main       → ci.yml + build: imagen → GHCR (tag = sha)

on: workflow_dispatch (environment "production" con aprobación) → deploy.yml:
  1. ssh deploy@vps "deploy/deploy.sh <sha>"   (clave SSH de despliegue limitada a ese script)
       a. docker compose pull
       b. docker compose run --rm migrate          (migrate + sync_tenants; si falla, se para aquí)
       c. docker compose up -d web worker admin    (recrea solo lo que cambia)
       d. esperar /health = 200 (máx. 60 s)
       e. smoke: manage.py smoke (una conversación por el tenant interno `smoke`, pack bus,
          dataset de ejemplo, envío simulado); sale con 0/1
  2. si d o e fallan → deploy.sh redespliega el SHA anterior y avisa a ops
```

#### 16.3 Corte durante el despliegue

- `web` se recrea en unos segundos. Durante ese hueco Caddy devuelve 502 y **Meta reintenta** el webhook: no se pierde nada (§1.3). Si algún día molesta, dos réplicas de `web` con Caddy balanceando eliminan el hueco.
- `worker` termina sus trabajos (§7.5).
- **Migraciones antes** de recrear los servicios; como son compatibles hacia atrás (§13.4), el código viejo sigue funcionando mientras tanto.
- **Preferiblemente fuera de horas punta** de los negocios (antes de las 9:00 o después de las 21:00).

#### 16.4 Vuelta atrás

- Automática si fallan `/health` o el smoke (§16.2).
- Manual: `deploy.yml` con el SHA anterior. Las migraciones no se revierten (expand/contract).
- Datos: restauración (§15.4), solo en caso de corrupción.

**Tenant `smoke`:** `tenants/_smoke/tenant.yaml`, pack `bus`, dataset mínimo, número ficticio; excluido de periódicas, avisos y alertas; nunca envía nada a Meta (su `phone_number_id` está marcado como simulado y `send_message` lo detecta).

---

### 17. Observabilidad y alertas

#### 17.1 Logs

- **JSON a la salida estándar**, rotados por Docker (`json-file`, 5 × 20 MB por servicio). `make logs SERVICE=worker` y `docker compose logs` por SSH.
- Campos: `ts`, `level`, `msg`, `service`, `tenant`, `event_id` (= `trace_id`: el evento que originó todo; se propaga a envíos y llamadas a Calendar), `job`.
- Sin datos sensibles (§14).

#### 17.2 Errores

**Sentry** (plan gratuito): excepciones de `web` y `worker` con `tenant` y `event_id`, versión = SHA desplegado.

#### 17.3 `ops_check` (cada 5 min, en el worker)

| Comprobación | Umbral | Gravedad |
|---|---|---|
| Trabajo más antiguo listo en `inbound` | > 2 min | 🔴 |
| Trabajos `failed` | ≥ 1 en 10 min | 🟠 |
| `outbound_message` en `failed` o `unknown` (> 10 min) | ≥ 1 | 🟠 |
| Token de WhatsApp rechazado (401/190) | 1 | 🔴 (el negocio no puede responder) |
| Calendar sin acceso (`CalendarPermanentError`) o 3 errores seguidos | 1 | 🔴 |
| Tenant `degraded` (config o dataset que no carga) | 1 | 🔴 |
| Barrido de un tenant sin completarse en > 1 h | 1 | 🟠 |
| Plantilla declarada no aprobada (comprobación diaria de `pack.health`) | 1 | 🟡 |
| Mensajes facturables del mes > umbral del tenant | 1 | 🟡 |
| Disco > 85 %, conexiones de BD > 80 | 1 | 🟠 |

- Las alertas van al chat de ops de Telegram con enfriamiento de 30 min por tipo y tenant (§12).
- Al terminar, `ops_check` hace **ping a healthchecks.io** (latido). **Si el worker, la BD o la VPS caen, el latido deja de llegar y healthchecks.io avisa** (email y Telegram) sin depender de la plataforma.
- **Uptime externo** (UptimeRobot o Better Stack) contra `https://api.<dominio>/health` cada 5 min: detecta caídas de Caddy o `web`, DNS y caducidad del certificado.
- `/health`: 200 si el proceso responde y hay conexión a la BD; incluye el número de tenants cargados y `degraded`. No llama a servicios externos.

#### 17.4 Panel

Una vista del Admin ("Estado") con: colas (pendientes y antigüedad), trabajos fallidos, envíos `unknown`/`failed`, por tenant: mensajes del mes (entrantes, salientes, facturables), último barrido, estado (`ok`/`degraded`) y resultado de `pack.health`. Sin Prometheus ni Grafana.

---

### 18. Operación

#### 18.1 Alta de un tenant

1. `manage.py new_tenant <slug> --pack salon|bus` → crea `tenants/<slug>/tenant.yaml` con `id` UUIDv7, `app_public_id` aleatorio, `status: onboarding` y la config por defecto del pack.
2. Rellenar la config (y, en `bus`, copiar o crear el dataset y pasar `make bus-validar`).
3. **WhatsApp**: checklist §11.1 → ids en `tenant.yaml` → `manage.py set_secret <slug> whatsapp.app_secret`, `whatsapp.access_token`, `whatsapp.verify_token` → webhook configurado en Meta.
4. **Google Calendar** (`salon`): el negocio comparte su calendario con el email de la cuenta de servicio ("Hacer cambios en los eventos") → `calendar_id` en la config.
5. Plantillas del pack creadas en el WhatsApp Manager.
6. **Avisos al dueño** (opcional): `manage.py telegram_link <slug>` → `chat_id` en `tenant.yaml`.
7. PR → CI → merge → despliegue.
8. `manage.py tenant_health <slug>` en verde (credenciales, plantillas, calendario, dataset).
9. Prueba con `manage.py chat <slug>` y desde el número de prueba del operador (en `onboarding` solo él recibe respuesta) → prueba con el dueño.
10. `status: active` → PR → despliegue. `tools/qr.py <slug>` genera el QR de `wa.me` para el local.

#### 18.2 Baja de un tenant

1. `status: offboarded` → despliegue: los webhooks se contestan 200 sin guardar nada.
2. `manage.py export_tenant <slug>` si se acordó con el negocio (zip local, entregado por canal seguro).
3. `manage.py purge_tenant <slug>`: borra contactos, conversaciones, eventos, mensajes, avisos y credenciales (con confirmación escrita del slug).
4. Checklist manual: el negocio revoca el acceso del operador a su portfolio de Meta y deja de compartir el calendario.
5. Borrar `tenants/<slug>/` en un PR posterior (queda en el historial de git).

#### 18.3 Comandos de operación (`Makefile`)

`make deploy SHA=…` · `make status` (servicios y `/health`) · `make logs SERVICE=…` · `make admin-tunnel` · `make backup-now` · `make restore-test` · `make shell` · `make tenant-health SLUG=…` · `make bus-validar|bus-formatear|bus-revision|bus-publicar TENANT=…`.

#### 18.4 Runbooks (`docs/runbooks/`)

1. El bot no responde a nadie (Caddy, `web`, worker, BD).
2. El bot no responde a un negocio (token caducado, webhook desconfigurado, tenant `degraded`, calidad del número).
3. La cola se acumula o falta el latido.
4. Google Calendar sin acceso o con errores.
5. Envíos en `unknown` o `failed`.
6. Restaurar la BD y simulacro trimestral.
7. Vuelta atrás de un despliegue.
8. Incidente de seguridad o fuga de datos (pasos y plazos de aviso al negocio).
9. Rotar credenciales de un negocio o la clave Fernet.
10. Actualización de horarios de `bus` (ciclo §10.1).
11. Mantenimiento periódico: versión de la Graph API (cada 6 meses), dependencias y CVE (mensual), reinicio de la VPS para parches de kernel (mensual), calidad del número y plantillas (trimestral).

---

### 19. Pruebas

#### 19.1 Tipos

| Tipo | Qué prueba | Necesita | Ejemplos |
|---|---|---|---|
| **Unit** | Funciones puras | Nada | `compute_slots`, lector de `[CFG]` y descripciones, `plan_sends`, motor de horarios, matcher, fechas, validador |
| **Escenarios** | Conversaciones completas de un pack, como caja negra | Nada (`FakeCalendar`, datasets de ejemplo, reloj fijo) | §9.8, §10.5 |
| **Datos de tenants** | Todos los `tenants/*/tenant.yaml` y datasets validan | Ficheros del repo | Un precio mal escrito bloquea el merge |
| **Integración** | Webhook → cola → worker → envío, con BD real | PostgreSQL | Evento duplicado no se procesa dos veces; dos reservas simultáneas del mismo hueco → una `SlotTaken`; reintento de una reserva ya creada → éxito sin duplicar; barrido dos veces → un recordatorio; conversación modificada entre tx1 y tx2 → reintento; `unknown` no se reenvía |
| **Aislamiento** | RLS en todas las tablas con `tenant_id` | PostgreSQL | §13.2 |
| **Contrato** | Parser de avisos de Meta y cliente de Calendar contra **respuestas reales grabadas** | Fixtures JSON | Mensaje con BSUID, botón de plantilla, aviso `failed`, 409 de Calendar, paginación |
| **Migraciones** | No faltan ni son peligrosas | PostgreSQL | — |
| **Smoke** | Tras desplegar | Entorno desplegado | §16.2 |

#### 19.2 Arnés de conversación

Los escenarios se escriben en **pytest**, no en un formato propio:

```python
# packs/salon/tests/test_book.py
def test_reserva_completa(salon):                       # fixture: tenant de ejemplo + FakeCalendar + reloj
    salon.now("2026-10-05T10:00:00+02:00")
    salon.calendar.busy("2026-10-09", ["10:00-12:00"])
    salon.send("hola").expect(buttons=["Pedir cita", "Ver mis citas", "Mover cita"])
    salon.press("menu_book").expect(list_includes="Corte de pelo")
    salon.press("service_corte").expect(list_includes="Jueves 9 de octubre")
    salon.press("day_2026-10-09").expect(buttons=["Mañana", "Tarde"])
    salon.press("period_tarde").expect(list_includes="17:00")
    salon.press("hour_17:00").expect(text_contains="nombre")
    salon.send("Lucía").expect(text_contains="¡Tu cita está confirmada!")
    assert salon.calendar.created == [("2026-10-09T17:00", "corte", "Lucía")]
    assert salon.all_replies_within_whatsapp_limits()   # obligatorio en todo escenario
```

El arnés ejecuta el pack con el mismo `plan_sends` que producción y comprueba los límites de WhatsApp en cada respuesta: la lista de destinos de `bus` o de horas de `salon` se genera dinámicamente y es el fallo más fácil de cometer.

#### 19.3 Puertas de CI (bloquean el merge)

1. `ruff` + `mypy`.
2. `import-linter` (§5.4).
3. Unit + escenarios + datos de tenants (sin BD; rápidos).
4. Integración + aislamiento + contrato (PostgreSQL 18 como servicio de CI).
5. `makemigrations --check` + linter de migraciones.
6. `pip-audit`.
7. Construcción de la imagen.

---

### 20. Forma de trabajo

- **Un solo agente de programación** (Claude Code) con las reglas de `CLAUDE.md`; sin framework de agentes, tareas ni orquestación.
- Todo cambio, en una rama (`feat/…`, `fix/…`, `data/<slug>-…` para config y datasets) → PR con descripción en español → CI en verde → **revisión humana** → merge a `main`. `main` puede protegerse (ya no hay herramientas que escriban en ella directamente).
- El despliegue a producción lo lanza siempre una persona (§16.2).

**Requieren aprobación humana explícita, aunque CI esté en verde:** migraciones que tocan RLS, roles o borran datos; cambios en cifrado, secretos o verificación de firmas de webhooks; cambios en la infraestructura del servidor (Compose, Caddy, cortafuegos, backups); cualquier acción sobre datos de producción; activar el canal real de un negocio. **Ningún agente despliega a producción ni ejecuta comandos contra el servidor de producción.**

---

### 21. Plan de implementación y migración

| Fase | Contenido | Termina cuando |
|---|---|---|
| **F0 · Esqueleto** | Proyecto Django, `compose.yaml` local, settings, roles de BD, RLS + test de aislamiento, `tenant_tx`, registro de tenants, CI | CI en verde con el test de aislamiento |
| **F1 · Runtime** | Webhook, `inbound_event`, `process_event`, conversación, `plan_sends`, `send_message`, avisos de estado, comandos globales, arnés de pruebas, `manage.py chat` | Un pack de juguete conversa por el arnés y por el número de prueba de Meta |
| **F2 · Pack `bus`** | Portar `horarios/`, matcher, fechas, flujo, tools y tests de buscaBus; tenant de Autocares San Sebastián | Pasan todas las pruebas portadas + escenarios |
| **F3 · Pack `salon`** | Portar slots, parser, flujo, cliente de Calendar, barrido, plantillas; `FakeCalendar` | Escenarios de §9.8 en verde; prueba contra un calendario real de pruebas |
| **F4 · Producción** | VPS, Caddy, `compose.prod.yaml`, despliegue, backups + primer simulacro de restauración, `ops_check`, latido, uptime, Sentry, avisos al dueño | Simulacro de restauración hecho y alertas probadas |
| **F5 · Migración de los bots** | Ver abajo | Los dos negocios atendidos por FlowPilot; VM de GCP apagada |

**Migración de Peluquería (DM Barber Shop):**

1. El negocio comparte su calendario con la cuenta de servicio de la plataforma.
2. `tools/migrate_salon_events.py --dry-run` y después real: añade `fp_contact`/`fp_key`/`fp_service` a las citas futuras creadas por el bot actual (reconocibles por `WaId:`), creando sus contactos.
3. Config portada de `config.yaml` a `tenants/dm-barber/tenant.yaml` (mismo horario, servicios, evento especial, interruptores de envíos con su valor actual).
4. Secretos de la app de Meta existente con `set_secret`; las plantillas ya aprobadas se reutilizan.
5. En una hora valle: cambiar la URL del webhook en la app de Meta al de FlowPilot → probar → parar el servicio de la VM. La VM se conserva una semana apagada como vuelta atrás (volver a poner la URL antigua).

**Migración de buscaBus (Autocares San Sebastián):** aún no tiene alta en Meta. Se mueve `horarios/` a `tenants/<slug>/datasets/timetable/` y `config.yaml` a la config del tenant, se crea el tag `datos/<slug>/…` equivalente al último publicado y el alta en Meta se hace directamente contra FlowPilot. Las preguntas abiertas a negocio (P28, P30, P37) siguen documentadas en los comentarios del dataset.

---

### 22. Pendiente de verificar y decisiones abiertas

| # | Tema | Qué falta | Cuándo |
|---|---|---|---|
| 1 | Proveedor y plan de VPS | [VERIFICAR] precio actual y plan exacto; decidir si algún cliente exige datos en España | F4 |
| 2 | Precio de los mensajes de servicio en España | [VERIFICAR] tarifa real en la cuenta de cada negocio (§11.5) | Antes de activar cada negocio |
| 3 | BSUID / nombres de usuario de WhatsApp | [VERIFICAR] que se pueden enviar plantillas a un contacto identificado solo por BSUID (sin teléfono); si no, los recordatorios a esos contactos no salen y se registra | F3 |
| 4 | Versión de la Graph API | [VERIFICAR] fecha de caducidad de `v23.0` | Cada 6 meses (runbook 11) |
| 5 | Cuotas de Google Calendar API | [VERIFICAR] anuncios de Google sobre facturación de cuota; al volumen previsto, impacto nulo | Anual |
| 6 | Aviso de IA (AI Act art. 50) | No aplica mientras no haya IA; [VERIFICAR] si se exige identificar bots deterministas (bastaría con "asistente automático" en el texto del menú) | Antes de añadir IA |
| 7 | Retención definitiva | Ajustar §13.3 al contrato de encargo firmado con cada negocio | Antes del primer negocio de pago |
| 8 | Datos de `bus` | P28 (días especiales; antes del 24/12), P30 (verano de Adamuz), P37 (informativo) | Con la empresa |
| 9 | Precios en `bus` | Formato de los datos de precios (por línea o por tramo) | Cuando la empresa los envíe |

**Cerrado:**

| Tema | Decisión |
|---|---|
| Versiones | Python 3.14 · Django 5.2 LTS (migrar a 6.2 LTS tras abril de 2027) · PostgreSQL 18 · Procrastinate 3.x |
| Infraestructura | VPS + Docker Compose (sustituye a AWS) |
| Alcance de packs | `salon` y `bus`; `gym` fuera |
| IA | Fuera de la v1 |
| Fechas en `bus` | Formato cerrado `día/mes[/año]`, sin lenguaje natural |
| Calendar | Barrido cada 15 min, sin watch |

---

### 23. Documentación

- `README.md`: qué es, estado y cómo arrancar en local.
- `design.md`: este documento.
- `CLAUDE.md`: reglas para trabajar en el repo (agente y personas).
- `docs/adr/`: ADR-001 (monolito modular), ADR-002 (RLS), ADR-003 (packs), ADR-004 (entrada idempotente), ADR-005 (VPS + Docker Compose).
- `docs/packs/salon.md` y `docs/packs/bus.md`: qué hace cada pack, su config, sus plantillas y (en `bus`) el formato completo del dataset y su ciclo de actualización.
- `docs/runbooks/`: §18.4.
- `docs/glosario.md`: términos técnicos en lenguaje llano.
