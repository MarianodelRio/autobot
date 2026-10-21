# design.md — Diseño técnico de FlowPilot

> **Qué es este documento.** La única fuente de verdad sobre el diseño de FlowPilot: alcance, componentes, responsabilidades, interfaces, datos, flujos, integraciones, configuración, despliegue y comportamiento ante errores.
>
> **Estado.** En fase de diseño: todavía no existe implementación. Todo lo descrito aquí es la especificación que se implementará.
>
> **Código de partida.** Los packs se construyen portando dos bots que ya funcionan, cada uno en su repositorio: `Peluqueria` (reservas por WhatsApp sobre Google Calendar) y `buscaBus` (horarios de autobús por WhatsApp). Cada sección indica qué se porta y de dónde.
>
> **Documentos relacionados.** `IDEA.md` (el problema), `docs/adr/` (decisiones principales), `docs/glosario.md` (términos en lenguaje llano).
>
> **Convención.** **[VERIFICAR]** marca un dato externo que hay que confirmar antes de usarlo.

---

## Índice

0. [Resumen](#0-resumen)
1. [Alcance y requisitos](#1-alcance-y-requisitos)
2. [Conceptos](#2-conceptos)
3. [Principios](#3-principios)
4. [Arquitectura](#4-arquitectura)
5. [Configuración y secretos](#5-configuración-y-secretos)
6. [Canales](#6-canales)
7. [Runtime de mensajes](#7-runtime-de-mensajes)
8. [Contrato de un pack](#8-contrato-de-un-pack)
9. [Pack `salon` (peluquería)](#9-pack-salon-peluquería)
10. [Pack `bus` (horarios de autobús)](#10-pack-bus-horarios-de-autobús)
11. [Avisos al dueño y alertas de operación](#11-avisos-al-dueño-y-alertas-de-operación)
12. [Datos](#12-datos)
13. [Seguridad](#13-seguridad)
14. [Infraestructura y despliegue](#14-infraestructura-y-despliegue)
15. [Observabilidad](#15-observabilidad)
16. [Operación](#16-operación)
17. [Pruebas](#17-pruebas)
18. [Pendiente de verificar](#18-pendiente-de-verificar)
19. [Documentación](#19-documentación)

---

### 0. Resumen

| Tema | Decisión |
|---|---|
| Plataforma | **Python 3.14 + Django 5.2 LTS + PostgreSQL 18 + Procrastinate 3.x** ([ADR-001](docs/adr/ADR-001-monolito-modular.md)) |
| Forma | Monolito modular; una imagen; procesos `web` y `worker` |
| Multitenant | Una base de datos; `tenant_id` en cada fila de cliente; **RLS** con dos roles (`fp_app`, `fp_owner`) ([ADR-002](docs/adr/ADR-002-multitenancy-rls.md)) |
| Lógica de negocio | **Packs** `salon` y `bus`, cada uno con su máquina de estados y su esquema de config ([ADR-003](docs/adr/ADR-003-packs.md)) |
| Entrada | Guardar primero, contestar 200, procesar después; "al menos una vez" + idempotencia ([ADR-004](docs/adr/ADR-004-entrada-idempotente.md)) |
| Canales | **Un canal de producción por negocio**: WhatsApp (su número) o Telegram (su bot). Además, **un bot de Telegram de pruebas** de la plataforma con selector de negocio. Un adaptador pequeño por tipo de canal; los packs no saben por qué canal hablan |
| Config | `tenants/<slug>/tenant.yaml` en git, validado con pydantic en CI y al arrancar |
| Secretos | Plataforma en `.env`; canal de cada negocio en `secrets.yaml`; los dos en el servidor, nunca en git |
| Integraciones | Google Calendar (pack `salon`), con una cuenta de servicio de la plataforma |
| Infraestructura | **Una VPS en la UE con Docker Compose**: `caddy`, `web`, `worker`, `db`. ~10–15 €/mes ([ADR-005](docs/adr/ADR-005-vps-docker-compose.md)) |
| Backups | `pg_dump` cada 6 h → restic → almacenamiento S3 de otro proveedor |
| Vigilancia | Logs JSON, Sentry, comprobación de operación cada 5 min → Telegram, latido externo y uptime externo |

---

### 1. Alcance y requisitos

#### 1.1 Dentro

- Plataforma para **5–10 negocios**, ampliable a **15** sin cambios de diseño.
- **Canales de conversación:** cada negocio tiene **un canal de producción**, WhatsApp Cloud API (la app de Meta es del negocio) o un bot de Telegram propio. Además, **un bot de Telegram de pruebas** de la plataforma permite probar cualquier negocio, eligiéndolo al empezar (§6.5). La misma lógica de pack sirve para todos.
- **Pack `salon`** (§9): reservar, ver, mover y cancelar citas sobre el Google Calendar del negocio; citas manuales del dueño con confirmación al cliente; recordatorios 24 h antes con confirmar o cancelar; cierres y horarios especiales con eventos `[CFG]`; evento especial con días propios; límite de citas por cliente.
- **Pack `bus`** (§10): consulta origen → destino → día con salidas directas; motor de horarios en memoria; matcher de pueblos que nunca adivina; fechas en formato cerrado; "ver pueblos por línea"; validador estricto de horarios y vista de revisión HTML/PDF para la empresa.
- **Avisos al dueño** por Telegram, opcionales por negocio (§11).
- **Operación para una persona:** alta y baja con comandos, alertas a Telegram, backups externos con restauración probada.

#### 1.2 Fuera de alcance

IA o lenguaje natural · más de un canal de producción por negocio · otros canales (email, Instagram, SMS) · formularios públicos · derivación a una persona dentro de la conversación (la opción "Contacto" muestra el teléfono del negocio) · panel de autoservicio para negocios · varios profesionales por peluquería, lista de espera, pagos · precios, incidencias y GTFS en `bus` · alta disponibilidad, autoescalado y entorno de staging.

#### 1.3 Requisitos no funcionales

| Requisito | Valor | Cómo se cumple |
|---|---|---|
| Escala | ≤ 15 negocios; ~1.000–5.000 mensajes/mes por negocio; picos de pocos mensajes por segundo en total | Un `worker` con concurrencia 4 |
| Latencia | Respuesta en 1–3 s | El webhook guarda y encola en < 100 ms; Procrastinate usa `LISTEN/NOTIFY` |
| Orden | Los mensajes de un contacto se procesan y se responden en orden | Candados por conversación en la cola (§7.5) |
| Disponibilidad | Se aceptan caídas ocasionales de minutos | Meta y Telegram reintentan los webhooks: un corte corto no pierde mensajes |
| Durabilidad | RPO ≤ 6 h, RTO ≤ 2 h | §14.4. La agenda vive en Google Calendar y los horarios en git |
| Coste | ~20 €/mes como máximo, sin contar APIs (Meta lo paga cada negocio en su cuenta) | §14.5 |
| Datos | Personales (teléfonos, nombres, citas); sin pagos ni datos de salud; en la UE | RLS, secretos fuera de la BD y de git, retención (§12.3) |

---

### 2. Conceptos

| Concepto | Qué es |
|---|---|
| **Tenant** (negocio) | Un negocio de la plataforma. Todo dato pertenece a uno |
| **Pack** | El programa de un tipo de negocio: conversación, reglas, esquema de config, periódicas y tests (`salon`, `bus`) |
| **Canal** | Vía por la que un contacto habla con un tenant. Cada tenant tiene su canal **`main`** (su número de WhatsApp o su bot de Telegram) y es accesible por el canal **`test`** (el bot de pruebas compartido) |
| **Bot de pruebas** | Bot de Telegram de la plataforma con el que el operador y las personas autorizadas de cada negocio eligen un negocio y prueban su pack |
| **Adaptador de canal** | Código que traduce entre un proveedor (Meta, Telegram) y los tipos comunes. Uno por tipo de canal |
| **Contacto** | Persona que escribe a un tenant por uno de sus canales (nunca "cliente": cliente = tenant) |
| **Conversación** | El estado de la charla de un contacto con un tenant (en qué paso está) |
| **Evento entrante** (`inbound_event`) | Un aviso de un proveedor ya guardado y pendiente de procesar: un mensaje, una pulsación de botón o un estado de entrega |
| **Mensaje saliente** (`outbound_message`) | Un mensaje que hay que enviar, guardado antes de enviarlo, con clave idempotente |
| **Respuesta** (reply) | Lo que el pack quiere decir en este turno: texto, botones o lista |
| **Acción** | Lo que el pack quiere que ocurra además de responder: enviar un aviso proactivo, avisar al dueño, marcar una baja |
| **Aviso proactivo** | Mensaje que el bot inicia sin que el contacto haya escrito (recordatorio, confirmación). En WhatsApp es una **plantilla** aprobada por Meta |
| **Evento de calendario** | Una cita o bloqueo en el Google Calendar del negocio (`gcal_id`) |
| **Barrido** | Tarea periódica por tenant que revisa datos externos y actúa con una clave estable por entidad |
| **Dataset** | Datos estructurados grandes de un tenant en ficheros con validador estricto (horarios de `bus`) |

---

### 3. Principios

1. **Simple antes que flexible.** Una máquina, una base de datos, una imagen, dos procesos de aplicación.
2. **Lo genérico en la plataforma, lo específico en los packs.** La plataforma no sabe qué es una cita ni un autobús; los packs no saben qué es WhatsApp ni Telegram. A `core/` solo sube lo que usan los dos packs.
3. **Lógica en código; datos de negocio en ficheros validados.** Precios, horarios, textos y datasets se cambian sin programar, con historial en git y validación en CI.
4. **Nada se pierde y nada se duplica.** Todo evento se guarda antes de procesarse; todo efecto externo es idempotente; nunca se reintenta a ciegas un envío ambiguo.
5. **Determinista.** El bot nunca adivina en silencio: o hay una respuesta única, o pregunta.
6. **Aislamiento entre negocios garantizado por la base de datos**, no solo por el código.
7. **Operable por una persona.** Lo que no se resuelve con un comando o una alerta clara, no se hace.

---

### 4. Arquitectura

#### 4.1 Vista general

```
                    ┌──────────────────────────── VPS (UE) ──────────────────────────────┐
 Meta (WhatsApp) ──►│ caddy :443 ─ /webhooks/*, /health ─► web (gunicorn) ──┐            │
 Telegram (bots) ──►│  (HTTPS automático)                                    ▼            │
                    │                                            ┌───────────────────┐    │
 Operador ─ SSH ───►│ 127.0.0.1:8000 ─► web /admin ─────────────►│ db: PostgreSQL 18 │    │
   (túnel)          │                                            │ datos + cola      │    │
                    │ worker (Procrastinate) ◄───────────────────┴───────────────────┘    │
                    │   ├─► Meta Graph API · Telegram Bot API (respuestas y avisos)       │
                    │   ├─► Google Calendar API (pack salon)                              │
                    │   ├─► Bot de avisos de Telegram (dueños y operador)                 │
                    │   └─► healthchecks.io (latido)                                      │
                    │ timer del host: backup ── restic ──► almacenamiento externo         │
                    └─────────────────────────────────────────────────────────────────────┘
```

#### 4.2 Procesos

Una sola imagen; cambia el comando.

| Servicio | Comando | Hace | No hace |
|---|---|---|---|
| `web` | `gunicorn config.wsgi --workers 2 --threads 4` | Webhooks de WhatsApp y Telegram, `/health`, Django Admin (solo accesible por túnel SSH) | Llamar a APIs externas ni ejecutar packs |
| `worker` | `manage.py procrastinate worker --concurrency 4` | Procesar eventos, ejecutar packs, enviar mensajes, periódicas, barridos, comprobaciones de operación | Atender HTTP |
| `db` | `postgres:18` | Datos y cola | Exponerse fuera de la red de Compose |
| `caddy` | `caddy:2` | TLS automático y proxy a `web` solo para las rutas públicas | — |

Las migraciones se ejecutan con `docker compose run --rm web manage.py migrate` antes de recrear los servicios (§14.6). Conexiones a la BD: ~8 de `web` + ~6 del `worker` de las 100 por defecto.

#### 4.3 La vida de un mensaje

1. El contacto escribe al canal `main` del negocio. El proveedor envía `POST /webhooks/<tipo>/<public_id>` (los mensajes del bot de pruebas pasan antes por su selector, §6.5).
2. **web** resuelve el tenant por la URL (registro en memoria, §5.4), verifica la autenticidad con el adaptador del canal, convierte el aviso en elementos (`parse`) y, por cada uno, **guarda** `inbound_event` (si ya existía, nada) y **encola** `process_event` con el candado de esa conversación. Contesta 200.
3. **worker** coge el trabajo. El candado garantiza que los mensajes de un mismo contacto se procesan de uno en uno y en orden de llegada.
4. **tx1** (transacción corta): carga evento, contacto y conversación.
5. **Sin transacción:** pasa el mensaje al pack con un `PackContext`. El pack devuelve respuestas, estado nuevo y acciones; si necesita Calendar, lo llama aquí.
6. **tx2:** guarda el estado, crea los `outbound_message` en orden y las acciones, marca el evento como hecho y encola los envíos (el trabajo solo existe si hay COMMIT).
7. **worker** (cola `outbound`) renderiza cada mensaje con el adaptador de su canal y lo envía.
8. En WhatsApp llegan después avisos de estado (entregado, leído, fallido, con precio) que actualizan `outbound_message`.

#### 4.4 Módulos y regla de dependencias

```
src/
  core/            Python puro, sin Django: tipos comunes (mensaje entrante, respuestas, acciones,
                   contrato de pack), límites comunes de mensajes, utilidades de interfaz, texto,
                   fechas y arnés de pruebas de conversación
  integrations/    Clientes de sistemas externos de negocio, sin Django: google_calendar/
  packs/           salon/, bus/ y registry.py (diccionario explícito de packs)
  flowpilot/       Django:
    tenancy/         registro de tenants (YAML → memoria), modelo Tenant, tenant_tx, secretos
    channels/        contrato de adaptador + whatsapp/ y telegram/ (verificación, parseo, render, envío)
                     + test_bot/ (selector de negocio del bot de pruebas)
    runtime/         modelos (InboundEvent, Contact, Conversation, OutboundMessage, Notification,
                     TestBotEvent, TestSession),
                     process_event, envíos, periódicas
    notify/          bot de avisos de Telegram (dueños y operador)
    ops/             /health, comprobación de operación, latido, retención, comandos de operación
    admin.py         Django Admin
    jobs.py          app de Procrastinate y registro de tareas
  config/          settings, urls, wsgi
```

Regla de dependencias (comprobada con `import-linter` en CI):

```
core           ──►  nada del proyecto
integrations   ──►  core
packs/*        ──►  core               (nunca Django, integrations, flowpilot ni otro pack)
flowpilot      ──►  core, integrations, packs.registry
```

Los packs acceden a sistemas externos mediante un `Protocol` propio (p. ej. `packs/salon/ports.py`); `flowpilot` les pasa la implementación de `integrations/`. Los tests de `core` y de los packs corren sin BD ni red.

#### 4.5 Repositorio

```
flowpilot/
├── pyproject.toml · uv.lock · manage.py · Dockerfile · Makefile · .env.example
├── compose.yaml · compose.prod.yaml · Caddyfile
├── README.md · IDEA.md · design.md · CLAUDE.md
├── src/                      §4.4 (tests unitarios y escenarios dentro de cada pack: packs/*/tests/)
├── tenants/<slug>/           tenant.yaml (§5.2) y datasets/ (solo bus)
├── tools/                    qr.py · bus_validar.py · bus_formatear.py · bus_revision.py ·
│                             migrate_salon_events.py
├── deploy/                   deploy.sh · backup.sh · restore.sh · systemd/ (timer de backup)
├── tests/                    integration/ · isolation/ · contract/ · fixtures/
├── docs/                     adr/ · packs/ · runbooks/ · glosario.md
└── .github/workflows/        ci.yml · deploy.yml
```

---

### 5. Configuración y secretos

#### 5.1 Qué vive dónde

| Dónde | Qué | Cómo se cambia |
|---|---|---|
| `src/` | Código, packs, plantillas declaradas, migraciones | Commit + CI + despliegue |
| `tenants/<slug>/` (git) | Identidad del tenant, canal `main` (ids no secretos), personas autorizadas para pruebas, pack, config de negocio, datasets | Commit + CI (valida todo) + despliegue |
| Google Calendar del negocio | Citas, bloqueos, cierres `[CFG]` (pack `salon`) | Lo gestiona el dueño; efecto inmediato |
| `secrets.yaml` (servidor) | Tokens y secretos del canal `main` de cada tenant | SSH + reinicio de `web` y `worker` |
| `.env` (servidor) | Secretos de plataforma y lo que cambia entre local y producción | SSH + reinicio |
| Base de datos | Contactos, conversaciones, eventos, mensajes y avisos | La aplicación |

Ningún fichero de `tenants/` contiene secretos ni datos personales de contactos. El repositorio es privado.

#### 5.2 `tenant.yaml`

```yaml
# tenants/dm-barber/tenant.yaml
id: 01929a4e-6b1c-7d3e-9f00-1a2b3c4d5e6f   # UUIDv7 fijo, generado en el alta
slug: dm-barber
name: DM Barber Shop
status: active                 # onboarding | active | paused | offboarded
timezone: Europe/Madrid
pack: salon

channel:                       # canal de producción (main): exactamente uno
  type: whatsapp               # whatsapp | telegram
  public_id: k3v9w2q8           # aleatorio; va en la URL del webhook
  app_id: "1234567890"          # solo whatsapp
  waba_id: "9876543210"         # solo whatsapp
  phone_number_id: "1122334455" # solo whatsapp
  display_phone: "+34 682 21 44 69"
  monthly_alert_threshold: 2000 # solo whatsapp: mensajes facturables/mes que disparan aviso (§15.3)
  # bot_username: dmbarber_bot  # solo telegram

testers:                        # opcional
  telegram: [123456789]         # ids de Telegram que pueden elegir este negocio en el bot de pruebas
  main: ["34600000001"]         # en onboarding, únicos ids que reciben respuesta por el canal main

owner:                          # opcional (§11)
  telegram_chat_id: 987654321
  notify: [booking_cancelled]

config:                         # validado con el esquema del pack (SalonConfig, §9.2)
  business_name: DM Barber Shop
  contact_phone: "+34 682 21 44 69"
  calendar_id: c_abc123@group.calendar.google.com
  services:
    corte: {name: Corte de pelo, price_eur: 10, duration_min: 30, client_presence_min: 30}
  # …
```

Validaciones comunes: slugs, ids y `public_id` únicos en todo el repositorio; campos obligatorios según `channel.type`; `phone_number_id` único entre tenants; `testers.telegram` con enteros y `testers.main` con ids del tipo del canal `main` (BSUID o teléfono en WhatsApp, entero en Telegram).

#### 5.3 Secretos

**`.env`** (servidor, `chmod 600`):

```text
ENVIRONMENT=local|prod
DJANGO_SECRET_KEY, DJANGO_ALLOWED_HOSTS=api.<dominio>,localhost
POSTGRES_PASSWORD                          (superusuario; solo el servicio db)
DB_APP_URL                                 (rol fp_app: web y worker)
DB_OWNER_URL                               (rol fp_owner: migraciones y admin; solo web)
GOOGLE_SERVICE_ACCOUNT_FILE=/run/secrets/google_sa.json
SECRETS_FILE=/run/secrets/secrets.yaml
WHATSAPP_GRAPH_VERSION=v23.0
TEST_BOT_TOKEN, TEST_BOT_WEBHOOK_SECRET    (bot de pruebas, §6.5; en local, un bot de desarrollo distinto)
TEST_BOT_OPERATORS                         (ids de Telegram del operador: ven todos los negocios)
NOTIFY_BOT_TOKEN, OPS_TELEGRAM_CHAT_ID     (bot de avisos, §11)
SENTRY_DSN, HEALTHCHECKS_PING_URL, LOG_LEVEL
```

**`secrets.yaml`** (servidor, `chmod 600`, montado de solo lectura en `web` y `worker`), con los secretos del canal `main` de cada tenant:

```yaml
dm-barber:                     # canal whatsapp
  app_secret: "…"              # verifica la firma de los webhooks
  access_token: "…"            # token permanente de System User
  verify_token: "…"            # verificación inicial del webhook de Meta
autocares-ss:                  # canal telegram
  bot_token: "…"
  webhook_secret: "…"          # secret_token de setWebhook (aleatorio, 32+ caracteres)
```

- Al arrancar, el registro (§5.4) comprueba que cada tenant tiene los secretos de su tipo de canal; si faltan, su canal `main` queda deshabilitado con alerta (el bot de pruebas sigue funcionando para ese tenant).
- El fichero de la cuenta de servicio de Google, `.env` y `secrets.yaml` entran en el backup cifrado de restic (§14.4) y tienen copia en el gestor de contraseñas del operador.
- **Google Calendar usa una cuenta de servicio de la plataforma**; cada negocio comparte su calendario con su email ("Hacer cambios en los eventos"). Alcance `calendar.events`.
- En local, `secrets.yaml` y `.env` viven en la raíz (ignorados por git); el bot de pruebas es un bot de desarrollo propio del operador.

#### 5.4 Registro de tenants

- Al arrancar, `web` y `worker` leen `tenants/*/tenant.yaml`, validan la parte común, la `config` con el esquema del pack y los secretos, cargan los datasets (`pack.load_data`) y construyen índices en memoria: `(tipo, public_id) → tenant`, `phone_number_id → tenant`, `slug → tenant`, tenants activos por pack y tenants visibles por cada id de Telegram en el bot de pruebas.
- **Un tenant inválido no afecta a los demás.** CI lo habría bloqueado (§17.3); si aun así falla al arrancar, queda `degraded`: sus eventos se guardan como `ignored`, los contactos reciben un texto genérico de plataforma ("Ahora mismo no puedo atenderte; inténtalo más tarde") y salta una alerta 🔴.
- **Estados:** `onboarding` (el canal `main` solo responde a `testers.main`), `active`, `paused` (el canal `main` guarda y no responde), `offboarded` (contesta 200 sin guardar). El bot de pruebas funciona en `onboarding`, `active` y `paused`.
- **`sync_tenants`** (tras `migrate`, §14.6) hace *upsert* de la tabla `tenant` (id, slug, name, pack, status, timezone) para las claves foráneas y RLS. Esa tabla es un reflejo y nunca se edita a mano.

---

### 6. Canales

#### 6.1 Tipos comunes (`core/`)

```python
@dataclass(frozen=True)
class IncomingMessage:                 # lo que recibe el pack
    type: Literal["text", "button", "unsupported"]   # button = botón, fila de lista o botón de aviso
    text: str | None
    payload: str | None                # id del botón o fila pulsada
    received_at: datetime

# Respuestas (core/replies.py)
Text(body: str)
Buttons(body: str, buttons: list[Button], header: str | None = None, footer: str | None = None)
List(body: str, button_label: str, sections: list[Section], header: str | None = None, footer: str | None = None)
Button(id: str, title: str)
Section(title: str | None, rows: list[Row])
Row(id: str, title: str, description: str | None = None)
```

**Límites comunes** (`core/limits.py`): el pack construye respuestas que caben en **los dos** canales, así que se aplica el más estricto de cada límite:

| Límite | Valor | Origen |
|---|---|---|
| Botones por mensaje | ≤ 3, título ≤ 20 caracteres | WhatsApp |
| Filas de lista | ≤ 10 en total, título ≤ 24, descripción ≤ 72 | WhatsApp |
| Cuerpo de un interactivo | ≤ 1.024 caracteres | WhatsApp |
| Texto | ≤ 4.096 caracteres | Ambos |
| `id` de botón o fila | ≤ 64 **bytes** | Telegram (`callback_data`) |

Formato de texto: texto plano con emojis y `*negrita*` (sintaxis de WhatsApp). El adaptador de Telegram la convierte (§6.4).

#### 6.2 Contrato de adaptador (`flowpilot/channels/base.py`)

```python
class ChannelAdapter(Protocol):
    type: Literal["whatsapp", "telegram"]

    def verify(self, request: HttpRequest, channel: Channel, secrets: ChannelSecrets) -> bool
    def parse(self, body: dict, channel: Channel) -> list[ParsedItem]
        # ParsedItem = InboundItem(provider_event_id, external_id, display_name, phone, message: IncomingMessage)
        #            | StatusItem(provider_event_id, outbound_ref, status, pricing_category, billable)
    def acknowledge(self, payload: dict, channel: Channel, secrets: ChannelSecrets) -> None
        # efectos inmediatos tras recibir (Telegram: answerCallbackQuery); en WhatsApp no hace nada
    def render(self, out: Reply | ProactiveMessage, channel: Channel) -> dict
    def send(self, rendered: dict, recipient: str, channel: Channel, secrets: ChannelSecrets,
             outbound_id: UUID) -> SendOutcome
        # SendOutcome = Sent(provider_message_id) | Rejected(reason, kind) | RetryLater(after_s) | Ambiguous(reason)
```

- `Channel` describe el canal concreto (tipo, bot o número, credenciales); para el canal `test` es el bot de pruebas.
- `ProactiveMessage(template: TemplateSpec, params: list[str], button_payloads: list[str])`: un aviso que el bot inicia (§6.3, §6.4).
- `TemplateSpec(name, language, text, buttons)` lo declara el pack: `name` y `language` sirven en WhatsApp; `text` (con `{1}`, `{2}`…) y los títulos de `buttons` sirven en Telegram. El texto debe coincidir con el de la plantilla aprobada en Meta.
- `Rejected.kind`: `auth` (token inválido o revocado), `recipient` (el contacto no puede recibir: bloqueó el bot, número inválido) u `other`.
- Las diferencias entre canales viven **solo** en los adaptadores. No hay más tipos de canal previstos.

#### 6.3 WhatsApp (`flowpilot/channels/whatsapp/`)

Se porta de `webhook.py` y `whatsapp.py` de Peluquería.

- **Conexión:** la app de Meta, la WABA y el número están en el Business Portfolio del negocio (el operador es administrador). El webhook se configura en la app con la URL `https://api.<dominio>/webhooks/whatsapp/<public_id>`. Una app y un número por negocio.
- **`GET` de verificación:** compara `hub.verify_token` con el del canal en tiempo constante y devuelve `hub.challenge`.
- **`verify`:** `X-Hub-Signature-256` = HMAC-SHA256 del cuerpo con `app_secret`, en tiempo constante.
- **`parse`:**
  - `value.metadata.phone_number_id` debe ser el del tenant; si no, el elemento se descarta y se registra.
  - Mensajes: `text`, `interactive.button_reply`, `interactive.list_reply` y `button` (botón de plantilla, con `button.payload`) → `IncomingMessage`; audio, imagen, documento, sticker, ubicación… → `unsupported`. Texto truncado a 4.096; ids de más de 64 bytes se descartan.
  - `external_id` = `user_id` (BSUID, `^[A-Z]{2}\.[A-Za-z0-9]{1,128}$`) si viene; si no, `from` (teléfono, 7–15 dígitos). `phone` solo si `from` es un teléfono. `display_name` de `contacts[].profile.name`.
  - Estados (`sent`, `delivered`, `read`, `failed`) → `StatusItem` con `biz_opaque_callback_data` como `outbound_ref` y su `pricing`.
  - `provider_event_id` = `wamid` en mensajes y `<wamid>:<status>` en estados.
- **`render`:** `Text` → `text`; `Buttons` → `interactive.button`; `List` → `interactive.list`; un texto seguido de un interactivo va en su cuerpo si caben juntos (§7.4). `ProactiveMessage` → `template` con `body` (parámetros) y botones `quick_reply` con sus `payload`.
- **`send`:** `POST https://graph.facebook.com/<versión>/<phone_number_id>/messages` con `biz_opaque_callback_data = outbound_id`, timeout 10 s, cliente `httpx` con *pool* de conexiones.

| Respuesta de Meta | `SendOutcome` |
|---|---|
| 2xx | `Sent(wamid)` |
| 401, o error OAuth 190 | `Rejected(kind=auth)` |
| 400 con error de destinatario (número no válido o fuera de WhatsApp) | `Rejected(kind=recipient)` |
| Otros 4xx salvo 429 | `Rejected(kind=other)` |
| 429, o 5xx con cuerpo de error JSON | `RetryLater` |
| Timeout, error de red, 502/504 sin cuerpo | `Ambiguous` |

- Nunca se registra el cuerpo de una respuesta 4xx (puede llevar datos personales).
- **Ventana de 24 h:** las respuestas siempre van dentro, porque contestan a un mensaje del contacto. Los avisos proactivos usan plantilla.
- **Costes:** desde el 1/10/2026 Meta cobra también los mensajes de servicio (respuestas dentro de la ventana) al precio *utility* del país ([página oficial](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/non-template-messages)); no se cuenta con ningún tramo gratuito. Tarifa de España [VERIFICAR en la cuenta de cada negocio]. Por eso se fusionan mensajes (§7.4) y `outbound_message` guarda `pricing_category` y `billable`.
- **Alta de un número:** SIM sin WhatsApp activo; Gmail y Business Portfolio del negocio; verificación de empresa (2–5 días hábiles, necesaria para el nombre visible); app tipo Business con WhatsApp; número registrado; app suscrita a la WABA (`POST /<WABA_ID>/subscribed_apps`); campo `messages` suscrito; System User con token permanente (`whatsapp_business_messaging`, `whatsapp_business_management`); plantillas del pack creadas (aprobación de 1 a 48 h).

#### 6.4 Telegram (`flowpilot/channels/telegram/`)

Se apoya en `tools/telegram_pruebas.py` de buscaBus (mapeo de listas y botones). El mismo adaptador sirve para el bot propio de un negocio (canal `main`) y para el bot de pruebas (§6.5); solo cambian el token y el enrutado.

- **Entrada en el servidor:** webhook registrado con `manage.py telegram_set_webhook <slug|test>` (`setWebhook` con `secret_token` y `allowed_updates = [message, callback_query]`). URL: `https://api.<dominio>/webhooks/telegram/<public_id>` para un bot de negocio y `https://api.<dominio>/webhooks/telegram-test` para el bot de pruebas.
- **Entrada en local:** `manage.py telegram_poll [<slug>]` hace *long polling* con `getUpdates` (por defecto, del bot de pruebas de desarrollo) y pasa cada update **por el mismo camino que el webhook**. No hace falta túnel ni dominio. Un mismo bot nunca se usa a la vez en local y en el servidor: Telegram no admite webhook y `getUpdates` simultáneos.
- **`verify`:** cabecera `X-Telegram-Bot-Api-Secret-Token` comparada en tiempo constante con el `webhook_secret` del bot.
- **`parse`:** solo chats privados (grupos y canales se ignoran). `message.text` → `text`; `callback_query.data` → `button` con ese `payload`; resto de tipos → `unsupported`. `external_id` = `from.id`; `display_name` = `first_name`; sin teléfono. `provider_event_id` = `update_id` (único por bot). Sin estados de entrega. `/start` llega como texto y el runtime lo trata como `menu` (§7.3).
- **`acknowledge`:** `answerCallbackQuery` del `callback_query`, para que el cliente deje de mostrar el botón "cargando". Lo llama el worker al empezar el evento; si falla, se registra y se sigue.
- **`render`:**
  - `Text` → `sendMessage`.
  - `Buttons` → `sendMessage` con `InlineKeyboardMarkup`, un botón por fila.
  - `List` → `sendMessage` con un botón inline por fila. La cabecera va como primera línea en negrita y el pie se descarta. Las descripciones de las filas se añaden al texto como `título: descripción`, porque los botones de Telegram no tienen descripción.
  - `ProactiveMessage` → `sendMessage` con `TemplateSpec.text` y sus parámetros, más los botones con sus `payload`. Telegram no tiene ventana de 24 h ni plantillas.
  - `*negrita*` se convierte a `<b>…</b>` con `parse_mode=HTML`, escapando el resto del texto.
- **`send`:** `POST https://api.telegram.org/bot<token>/sendMessage`, timeout 10 s.

| Respuesta de Telegram | `SendOutcome` |
|---|---|
| `ok: true` | `Sent(message_id)` |
| 401 | `Rejected(kind=auth)` |
| 403 (el usuario bloqueó el bot) | `Rejected(kind=recipient)` |
| Otros 4xx salvo 429 | `Rejected(kind=other)` |
| 429 (con `retry_after`) o 5xx | `RetryLater` |
| Timeout o error de red | `Ambiguous` |

#### 6.5 Bot de pruebas

Un único bot de Telegram de la plataforma (`TEST_BOT_TOKEN`) para probar cualquier negocio con su lógica real, sin WhatsApp. Lo usan el operador (`TEST_BOT_OPERATORS`, ve todos los negocios) y las personas de cada negocio listadas en `testers.telegram` (solo ven los suyos). Para un tenant, el bot de pruebas es su canal `test`: tiene contactos, conversaciones y mensajes propios, separados de los del canal `main`.

**Selector (`flowpilot/channels/test_bot/`):**

1. `web` recibe el update en `/webhooks/telegram-test`, lo verifica y lo guarda en `test_bot_event` (único por `update_id`). Encola `route_test_update(event_id)` con candado `tg:<hash del usuario>`. Contesta 200. Como no sabe aún el tenant, no escribe en tablas con RLS.
2. El worker decide:
   - Usuario sin permiso para ningún negocio → "No tienes acceso al bot de pruebas" y nada más.
   - `/start`, `/negocio`, o usuario sin negocio elegido → lista de los negocios que puede ver (nombre y pack), paginada con `core/ui.paginate`.
   - Botón `fp_select:<slug>` (con permiso comprobado) → guarda la elección en `test_session` y crea en ese tenant un `inbound_event` sintético (`channel='test'`, `provider_event_id = select:<update_id>`, payload con el usuario de Telegram y el texto `menu`) + `process_event`; el runtime lo procesa como siempre y el pack responde con su menú.
   - Cualquier otro update con negocio elegido → `inbound_event` en ese tenant (canal `test`, `provider_event_id = update_id`) + `process_event`, exactamente como un mensaje del canal `main`.
3. Las respuestas salen por el bot de pruebas porque el contacto pertenece al canal `test`. Los avisos proactivos (recordatorios de citas hechas desde el bot de pruebas) también.

- El primer mensaje tras elegir negocio indica cuál es ("🧪 Pruebas · DM Barber Shop. Escribe /negocio para cambiar").
- Un tenant `degraded` u `offboarded` no aparece en la lista; si estaba elegido, se responde que no está disponible y se vuelve a mostrar la lista.
- `test_session` guarda solo `(telegram_user_id, tenant_id, selected_at)`; `test_bot_event` guarda el update entrante y se borra a los 7 días.

#### 6.6 Contactos y canales

- Un contacto se identifica por `(tenant, canal, external_id)`, con canal `main` o `test`. La misma persona en el canal `main` y en el bot de pruebas son dos contactos distintos, con conversaciones distintas.
- Las respuestas y los avisos proactivos a un contacto salen siempre por su canal.
- Los avisos a un teléfono sin contacto previo (confirmación de citas manuales, §9.6) solo son posibles si el canal `main` del tenant es WhatsApp; si es Telegram, se registran y no se envían.

---

### 7. Runtime de mensajes

#### 7.1 Entrada

```
POST /webhooks/<tipo>/<public_id>                  (canal main de un tenant)
  1. tenant = registro[(tipo, public_id)]         no existe o canal deshabilitado → 404
  2. cuerpo ≤ 64 KB y JSON válido                  si no → 400
  3. adaptador.verify(...)                         falla → 401 sin guardar; cuenta para el límite por IP
  4. tenant offboarded                             → 200 sin guardar
  5. por cada elemento de adaptador.parse(...):
       status = ignored si el tenant está paused o degraded,
                o en onboarding y external_id no está en testers.main
       tenant_tx(tenant.id):
         INSERT inbound_event (channel='main', kind, provider_event_id, payload, status)
           ON CONFLICT (tenant_id, channel, provider_event_id) DO NOTHING
         si se insertó y status = pending:
           kind=message → defer process_event(tenant_id, event_id)  cola inbound, lock conv:<h>
           kind=status  → defer apply_status(tenant_id, event_id)   cola inbound, sin candado
       COMMIT
  6. 200 OK
```

- El bot de pruebas entra por `POST /webhooks/telegram-test` y pasa por el selector (§6.5), que acaba creando el mismo `inbound_event` con `channel='test'` y encolando el mismo `process_event`.
- `h` = primeros 16 caracteres hex de `sha256(tenant_id, canal, external_id)`. **Los candados nunca llevan teléfonos ni ids de usuario en claro**, porque la tabla de trabajos de Procrastinate no tiene RLS.
- Los webhooks no hacen ninguna llamada externa: solo leen el registro en memoria y escriben en la BD.

#### 7.2 `process_event`

```python
def process_event(tenant_id, event_id):                     # el trabajo recibe solo ids
    tenant = registry.tenant(tenant_id)
    with tenant_tx(tenant_id):                              # tx1: cargar
        event = InboundEvent.get(event_id)
        if event.status != "pending":
            return                                          # ya procesado (reintento tras COMMIT)
        channel = tenant.channel(event.channel)             # main del tenant, o el bot de pruebas
        item = channel.adapter.parse_one(event.payload)     # InboundItem
        contact = upsert_contact(tenant, event.channel, item)   # actualiza nombre y teléfono
        conv = load_or_create_conversation(contact)
        state = effective_state(conv, tenant.pack, now)     # caducidad y versión (§7.3)

    channel.adapter.acknowledge(event.payload, ...)        # Telegram: answerCallbackQuery (sin transacción)

    if rate_limited(contact):                               # > 20 mensajes en 60 s del mismo contacto
        result = PackResult(replies=[])                     # se guarda y no se responde
    elif (cmd := global_command(item.message)) is not None:
        result = run_global_command(cmd, tenant, contact)   # menu, baja, alta (§7.3)
    else:
        ctx = build_context(tenant, contact, state, event)  # sin transacción: aquí van las llamadas externas
        try:
            result = tenant.pack.handle_message(ctx, item.message)
        except TransientError:
            if job.is_last_attempt: result = recovery_result(tenant)    # texto de recuperación + estado {}
            else: raise                                     # Procrastinate reintenta
        except Exception:
            report_to_sentry()
            result = recovery_result(tenant)

    with tenant_tx(tenant_id):                              # tx2: persistir
        conv.save_state(result.state)
        msgs = plan_sends(result.replies, contact, channel, idem_prefix=f"reply:{event_id}")
        apply_actions(result.actions, tenant)               # SendProactive, NotifyOwner, UpdateContact
        event.mark_done()
        defer_sends(msgs)                                   # el trabajo solo existe si hay COMMIT
```

- **Transacciones cortas:** ninguna transacción queda abierta mientras se llama a Calendar, Meta o Telegram.
- **Texto de recuperación** (heredado de Peluquería): "Uy, ha habido un problema de conexión y puede que tu última acción no se completara. Escríbeme de nuevo y seguimos." El estado se reinicia y el evento queda `failed` con el error.
- **Reprocesar un evento es seguro:** si el worker muere entre tx1 y tx2, el reintento repite el pack; las escrituras en Calendar son idempotentes (§9.5) y las respuestas, como se crean en tx2, no se habían creado.
- `apply_status(tenant_id, event_id)`: busca el `outbound_message` por `outbound_ref` (o por `provider_message_id`) y actualiza estado, `pricing_category` y `billable`. Un `failed` de Meta sobre un mensaje `sent` lo pasa a `failed` con el código de error.

#### 7.3 Conversación

- Una fila de `conversation` por contacto, con `state` (JSON del pack), `state_version` y `last_inbound_at`.
- **Un solo escritor:** solo `process_event` escribe una conversación, y siempre con el candado `conv:<h>`. No hace falta control de versiones optimista.
- **Caducidad:** si han pasado más de `pack.conversation_timeout_min` (30) desde el último mensaje, el estado vuelve a `{}` y el pack empieza por su menú.
- **Versión del estado:** si `state_version` no coincide con `pack.state_version` (un despliegue cambió la forma del estado), se reinicia con "Perdona, he tenido que empezar de nuevo" y se registra.
- **Comandos globales** (los resuelve el runtime antes que el pack, sobre el texto normalizado):
  - `menu`, `menú`, `inicio`, `/start` → estado `{}` y el pack responde a un mensaje vacío con su menú.
  - `baja` → `contact.opt_out = true` (deja de recibir avisos proactivos) y confirmación. `alta` lo revierte.
- **Mensajes no soportados:** el pack recibe `IncomingMessage(type="unsupported")` y pide texto o botones.

#### 7.4 Salida

**`plan_sends`** (función pura en `core/limits.py`):

1. Fusiona los textos consecutivos de un turno en un solo mensaje.
2. Si un texto va seguido de botones o lista, lo mete en el cuerpo del interactivo, salvo que juntos superen 1.024 caracteres.
3. Comprueba los límites comunes (§6.1). Superarlos es un error de programación: en tests falla y en producción se trunca y se registra.
4. Crea un `outbound_message` por mensaje final, en orden (`seq`), con `idem_key = reply:<event_id>:<seq>`.

Fusionar reduce el coste en WhatsApp y el ruido en los dos canales.

**`send_message(tenant_id, outbound_id)`** (cola `outbound`, candado `out:<h>` para respetar el orden por contacto):

```
status = sent                → terminar
status = unknown | failed    → terminar (no se reenvía a ciegas)
status = sending             → el intento anterior se cortó a mitad → status = unknown; terminar
status = sending; attempts += 1; COMMIT
outcome = adaptador.send(adaptador.render(payload), ...)
  Sent        → sent, provider_message_id, sent_at
  Rejected    → failed, last_error; kind=auth → alerta 🔴; kind=recipient → contacto marcado unreachable
  RetryLater  → pending; reintento con backoff (máx. 5; después failed)
  Ambiguous   → unknown
```

- Un `unknown` o `failed` **no bloquea** los siguientes mensajes del contacto.
- WhatsApp: un estado posterior con ese `outbound_ref` pasa un `unknown` a `sent`. Los que siguen en `unknown` más de 10 min aparecen en el Admin con "Marcar enviado" y "Reenviar", y en la alerta de §15.3.
- Telegram no envía estados: un `unknown` queda así hasta que lo revise el operador.

#### 7.5 Colas, candados y reintentos

| Cola | Trabajos | Candado | Reintentos |
|---|---|---|---|
| `inbound` | `process_event`, `apply_status`, `route_test_update` | `conv:<h>` en `process_event`; `tg:<h>` en `route_test_update` | 3, backoff exponencial 2 s → 30 s, solo para `TransientError` |
| `outbound` | `send_message`, `send_notification` | `out:<h>` y `owner:<tenant>` | Según `SendOutcome` |
| `periodic` | `run_periodic`, `ops_check`, `retention_cleanup` | `queueing_lock` por nombre y tenant (nunca dos iguales pendientes) | 2 |

- El candado (`lock`) de Procrastinate garantiza que los trabajos con el mismo candado se ejecutan **de uno en uno y en orden de creación**. Así se ordenan los mensajes por conversación, sin candados propios.
- Un solo `worker` atiende las tres colas, que permiten ver qué se atasca.
- Los trabajos reciben solo ids: nunca datos personales en argumentos ni candados.
- Un trabajo que agota sus reintentos queda `failed` en Procrastinate, aparece en el Admin con "Reintentar" y dispara una alerta (§15.3).
- **Parada ordenada:** al desplegar, el `worker` recibe SIGTERM, deja de coger trabajos y termina los que tiene (`stop_grace_period: 60s`). Lo que se corta se reintenta, y todos los trabajos son idempotentes.

#### 7.6 Tareas periódicas y barridos

- Cada `Periodic` de un pack se registra como tarea periódica de Procrastinate. Al dispararse **reparte**: para cada tenant activo de ese pack encola `run_periodic(tenant_id, name, scheduled_at)` en `periodic`. Procrastinate garantiza que cada instante programado se encola una sola vez.
- `run_periodic` construye un `PackContext` sin contacto, ejecuta el handler sin transacción y, en una transacción, aplica sus acciones.
- **Barridos:** lo que depende de datos que cambia otra persona (citas que el dueño crea o mueve) no se programa entidad a entidad. Un barrido revisa la ventana relevante y actúa con una **clave estable** por entidad (`ctx.idem.stable("reminder:<gcal_id>:<start>")`), que se guarda como `idem_key` única en `outbound_message`. Si la cita se mueve, cambia `start` y le corresponde otro aviso; si no, el barrido la vuelve a ver y no repite.
- Un barrido con más retraso que su `max_delay_min` (60 por defecto) se descarta y se registra.

#### 7.7 Comportamiento ante fallos

| Fallo | Comportamiento |
|---|---|
| Aviso duplicado del proveedor | `ON CONFLICT DO NOTHING`; no se encola dos veces |
| `web` caída unos minutos (despliegue, reinicio) | Meta y Telegram reintentan; nada se pierde |
| `worker` muere a mitad de un evento | Procrastinate libera el trabajo y se reintenta desde tx1; idempotente |
| Pack lanza una excepción no prevista | Texto de recuperación al contacto, estado reiniciado, evento `failed`, Sentry |
| Calendar caído o lento en una conversación | 2 reintentos rápidos en el cliente → `TransientError` → reintento del trabajo (3) → texto de recuperación |
| Calendar caído al comprobar el límite de citas | Falla en abierto: se deja reservar (§9.1) |
| Calendar sin acceso (403/404) | `CalendarPermanentError` → texto "Ahora mismo no puedo consultar la agenda" + alerta 🔴 "revisar acceso al calendario" |
| Calendar caído en un barrido | El barrido falla y se reintenta en la siguiente pasada; las claves estables evitan duplicados |
| Envío con resultado ambiguo | `unknown`; no se reenvía; alerta si dura más de 10 min |
| Token de WhatsApp o Telegram revocado | `failed` con `kind=auth` + alerta 🔴 |
| Contacto que bloqueó el bot o número inválido | `failed`, contacto `unreachable` (no recibe avisos proactivos) |
| Dataset o config inválidos al arrancar | Tenant `degraded`, texto genérico a sus contactos, alerta 🔴; los demás tenants siguen |
| BD caída | `web` responde 503 (el proveedor reintenta); el `worker` se reconecta; latido externo → alerta |

---

### 8. Contrato de un pack

#### 8.1 Declaración

```python
# packs/salon/pack.py
pack = Pack(
    name="salon",
    config_schema=SalonConfig,
    state_version=1,
    conversation_timeout_min=30,
    handle_message=conversation.handle,             # (ctx, IncomingMessage) -> PackResult
    periodic=[Periodic("calendar_sweep", every_min=15, handler=sweep.run, max_delay_min=60)],
    needs_calendar=True,                             # el runtime le da ctx.calendar
    load_data=None,                                  # (tenant, config, path) -> objeto en memoria; bus lo usa
    health=health.check,                             # (ctx) -> list[HealthIssue]
    templates=[TEMPLATE_CONFIRMATION, TEMPLATE_REMINDER],   # TemplateSpec (§6.2)
)
```

```python
# packs/registry.py
PACKS = {p.name: p for p in (salon.pack, bus.pack)}   # explícito, sin descubrimiento automático
```

#### 8.2 Contexto y resultado

```python
@dataclass(frozen=True)
class PackContext:
    tenant: TenantInfo                  # id, slug, name, timezone
    config: BaseModel                   # config validada del pack
    data: object | None                 # lo que devolvió load_data
    contact: ContactInfo | None         # id, external_id, phone (puede ser None), display_name, opt_out
    state: Mapping[str, Any]            # estado actual (solo lectura)
    clock: Clock                        # now() en la zona del tenant; inyectable en tests
    calendar: CalendarPort | None       # solo si needs_calendar
    lock: Callable[[str], ContextManager]   # advisory lock de PostgreSQL por clave (§9.5)
    idem: IdemKeys                      # .event(name) ligada al evento actual; .stable(name) para barridos
    log: Logger                         # con tenant y event_id; enmascara teléfonos

@dataclass
class PackResult:
    replies: list[Reply] = field(default_factory=list)
    state: dict | None = None           # None = sin cambios; {} = reiniciar
    actions: list[Action] = field(default_factory=list)

# Acciones (core/actions.py)
SendProactive(to: ContactRef, template: TemplateSpec, params: list[str],
              button_payloads: list[str], idem_key: str)       # ContactRef(contact_id=…) | ContactRef(phone=…)
NotifyOwner(kind: str, text: str, idem_key: str)
UpdateContact(display_name: str | None = None, opt_out: bool | None = None)
```

- Un pack **nunca** toca la BD, los canales ni las APIs directamente: todo lo externo le llega por `ctx`.
- Los handlers periódicos reciben `ctx` con `contact=None` y `state={}`, y solo devuelven `actions`.
- `SendProactive` lo resuelve el runtime: busca contacto y canal (§6.5), descarta contactos con `opt_out` o `unreachable`, y crea un `outbound_message` de tipo `proactive` con su `idem_key`.

#### 8.3 Utilidades comunes (`core/`)

| Módulo | Contenido | Origen |
|---|---|---|
| `core/ui.py` | `trunc`, `button`, `row`, `section`, `buttons_msg`, `list_msg` (validan límites); `paginate(items, page, per_page=8, more_id, back_id)` | `interactive.py` de los dos bots |
| `core/text.py` | `normalize` (minúsculas, sin tildes, sin puntuación, espacios colapsados), `strip_html` | `parser.py` de Peluquería y `formato.py` de buscaBus |
| `core/dates.py` | `format_date_es`, `weekday_es`, `next_days`; zonas con `zoneinfo` | `slots.py` de Peluquería y `fechas.py` de buscaBus |
| `core/limits.py` | Límites comunes y `plan_sends` | — |
| `core/testing/` | Arnés de conversación (§17.2), reloj fijo, `FakeCalendar` | `conftest.py` de los dos bots |

A `core` solo entra lo que usan los dos packs.

#### 8.4 Requisitos de un pack

Esquema de config con valores por defecto · máquina de estados en `conversation.py` · textos en `messages.py` · `TemplateSpec` de cada aviso proactivo · escenarios de conversación (camino feliz de cada opción del menú y al menos tres caminos de error) · `docs/packs/<nombre>.md` · entrada en `packs/registry.py`.

---

### 9. Pack `salon` (peluquería)

Se porta de `Peluqueria`: `handlers/conversation.py` (máquina de estados), `services/calendar/` (consultas, escrituras y motor de huecos), `utils/parser.py`, `utils/slots.py`, `utils/messages.py`, los constructores de `utils/interactive.py`, las validaciones de `config.py` y sus tests.

#### 9.1 Conversación

Estados: `MENU`, `BOOK_SERVICE`, `BOOK_DAY`, `BOOK_PERIOD`, `BOOK_HOUR`, `BOOK_NAME`, `VIEW`, `CANCEL_SELECT`, `MOVE_SELECT`. El estado guarda `mode` (`book`, `move` o `event`), la selección en curso y los ids de las citas listadas.

| Opción del menú | Flujo |
|---|---|
| **Pedir cita** | Comprueba el límite de citas futuras (`max_active_bookings`; si Calendar falla, deja continuar) → servicio (lista de hasta 9 + volver) → día (solo días **con huecos** en `booking_window_days`, calculados con una sola lectura de Calendar por rango) → **mañana / tarde** si las horas no caben en una lista → hora → nombre (texto de hasta 100 caracteres; si ya se conoce, botón "Usar <nombre>") → crea la cita (§9.5) → confirmación con servicio, precio, día y hora |
| **Ver mis citas** | Citas futuras del contacto |
| **Mover cita** | Elegir cita → servicio → día → hora → **crea la nueva y después cancela la antigua**. Si la cancelación falla, la nueva se queda, se avisa al dueño (`move_cancel_failed`) y se registra |
| **Cancelar cita** | Elegir cita → cancelada al momento |
| **Cita {evento}** (solo con `special_event.active`) | Como Pedir cita, pero días y franjas salen de `special_event.days` |
| **Contacto** (solo si `info_text` no está vacío) | Texto de la config |

- **Texto libre** fuera del paso de nombre → vuelve al menú. Los interactivos llevan el pie "Cualquier texto te llevará de vuelta al menú principal".
- **Botones de avisos proactivos** (válidos en cualquier estado): `reminder_confirm:<gcal_id>`, `reminder_cancel:<gcal_id>`, `booking_cancel:<gcal_id>`. Antes de actuar se comprueba que **la cita es de ese contacto** (por `fp_contact`; en citas manuales, por teléfono). Si no lo es, se responde "No se encontró esa cita".
  - Confirmar → escribe `Estado: confirmada` en la descripción del evento (lo ve el dueño) y responde "¡Tu cita está confirmada! ✅".
  - Cancelar → cancela (idempotente), responde con el mensaje de cancelación y avisa al dueño si procede.
- **Hueco recién ocupado** (`SlotTaken`): "Ese horario ya no está disponible" y vuelve a ofrecer las horas libres de ese día.
- **Avisos al dueño** (`NotifyOwner`): `booking_created`, `booking_cancelled`, `booking_moved` y `move_cancel_failed`, con clave `ctx.idem.event("notify:<kind>")`.

#### 9.2 Config

```python
class Service(BaseModel):
    name: str = Field(max_length=24)
    price_eur: Decimal | None = None
    duration_min: int                       # ocupación del profesional: colisiones y duración del evento
    client_presence_min: int                # tiempo del cliente en el local: última hora ofrecible

class SpecialEvent(BaseModel):
    active: bool = False
    name: str = ""                          # "Navidad 2026" → opción "Cita Navidad 2026"
    days: dict[date, list[TimeRange]] = {}

class SalonConfig(BaseModel):
    business_name: str
    contact_phone: str
    calendar_id: str
    services: dict[str, Service]            # 1–9
    opening_hours: WeeklyHours              # {martes: ["10:00-14:00", "16:00-21:00"], …}; día ausente = cerrado
    slot_step_min: int = 30
    min_notice_min: int = 0
    booking_window_days: int = 21
    max_active_bookings: int = 5
    reminders_enabled: bool = False
    reminder_window_hours: tuple[int, int] = (23, 25)
    manual_confirmations_enabled: bool = False
    manual_confirmations_since: datetime | None = None    # solo citas manuales creadas después
    special_event: SpecialEvent = SpecialEvent()
    info_text: str = ""
    texts: SalonTexts = SalonTexts()        # textos sobrescribibles, con los de messages.py por defecto
```

Validaciones: franjas con formato `HH:MM` y sin solapes; `duration_min ≤ client_presence_min`; claves de servicio `^[a-z0-9_]+$` (van en `id` de botones); fechas del evento especial válidas; `manual_confirmations_since` obligatorio si `manual_confirmations_enabled`. La ventana de búsqueda de citas del contacto se deriva: `booking_window_days + 1`.

#### 9.3 Google Calendar

`CalendarPort` (en `packs/salon/ports.py`; implementación en `integrations/google_calendar/` con `google-api-python-client`):

```python
class CalendarPort(Protocol):
    def list_events(self, calendar_id, start: datetime, end: datetime) -> list[CalEvent]
    def get_event(self, calendar_id, gcal_id) -> CalEvent | None
    def insert_event(self, calendar_id, event: NewEvent, gcal_id: str) -> CalEvent     # 409 → get_event
    def patch_description(self, calendar_id, gcal_id, fields: dict[str, str]) -> CalEvent
    def cancel_event(self, calendar_id, gcal_id) -> None                               # ya cancelado = ok
    def list_contact_events(self, calendar_id, contact_id, phone, start, end) -> list[CalEvent]
    def check_access(self, calendar_id) -> None
# CalEvent: gcal_id, summary, description (texto sin HTML), start, end, all_day, created, status, private
```

- **Errores:** `CalendarTransientError` (red, timeout, 5xx, 429; el cliente hace 2 reintentos rápidos antes de lanzarlo) y `CalendarPermanentError` (403/404). Timeout de 10 s por llamada.
- **Lecturas por ventana:** `singleEvents=true`, `timeMin`/`timeMax`, paginación con tope de 10 páginas. Sin caché entre peticiones.
- **Siempre se comprueba el resultado de una escritura.**
- Zonas horarias: siempre `datetime` con zona (`tenant.timezone`). En eventos de día completo, `end.date` es exclusivo.

**Cita creada por el bot:**

```
summary:      Corte de pelo - Lucía García              (<Servicio> - <Nombre>)
description:  Nombre: Lucía García
              Telefono: +34600000001                    (solo si se conoce)
              Servicio: corte
              Estado: pendiente | confirmada
extendedProperties.private:  fp_contact=<contact.id>  fp_key=<clave idempotente>  fp_service=corte
id:           determinista (§9.5)
```

**Cómo se interpretan los eventos del calendario:**

- **`[CFG] CERRADO`** cierra el día; **`[CFG] VACACIONES`** cierra todo su rango; **`[CFG] HORARIO HH:MM-HH:MM`** fija el horario de ese día. Prioridad: cerrado o vacaciones, después horario especial, después horario semanal.
- **Cita del bot:** tiene `fp_key`.
- **Cita manual:** no tiene `fp_key` y lleva `Telefono:` en la descripción. El servicio sale del título `<Servicio> - <Nombre>`: se compara con el nombre o la clave de cada servicio (sin tildes ni mayúsculas) y gana el patrón más largo; se aceptan los alias heredados ("corte y barba" → `corte_barba`).
- **Bloqueo:** cualquier otro evento. Ocupa tiempo y no genera avisos.
- Las descripciones editadas a mano se limpian de HTML (`<br>`, `<p>`, entidades) antes de leer campos, de forma tolerante a mayúsculas, tildes y espacios.
- **Citas creadas por la versión anterior del bot:** llevan `WaId:` y `Telefono:` en la descripción y no tienen `extendedProperties`. `list_contact_events` y la comprobación de propiedad también aceptan coincidencia por `WaId:` (= `external_id`) o `Telefono:`. `tools/migrate_salon_events.py` les añade `fp_contact`, `fp_key` y `fp_service`.

#### 9.4 Huecos

`compute_slots(day, service, franjas, busy, now, rules) -> list[time]`, función pura en `packs/salon/slots.py`:

- Franjas del día: horario semanal, sustituido por `[CFG] HORARIO` o, en modo evento, por `special_event.days`. Un día con `[CFG] CERRADO` o dentro de unas `VACACIONES` no tiene franjas.
- Horas candidatas cada `slot_step_min` dentro de cada franja, siempre que `inicio + client_presence_min ≤ fin de la franja`.
- Se descartan las que solapan `[inicio, inicio + duration_min)` con un evento ocupado, con ±1 min de tolerancia.
- Si el día es hoy, se descartan las anteriores a `now + min_notice_min`.
- **Mañana / tarde:** si hay más de 8 horas, se parte por la pausa entre franjas (o a las 14:00 si es una franja continua).

#### 9.5 Reservar sin dobles reservas

El candado por conversación no impide que **dos contactos** cojan el mismo hueco a la vez, y Google Calendar admite solapes. Por eso:

1. `with ctx.lock(f"cal:{calendar_id}:{day}")`: advisory lock de sesión de PostgreSQL (`pg_try_advisory_lock` en bucle durante 10 s como máximo, en una conexión sin transacción abierta, liberado en `finally`). Si no se consigue en 10 s → `TransientError`.
2. `get_event(id determinista)`: si existe y no está cancelado → éxito (es un reintento de una reserva ya hecha).
3. Lee los eventos del día y comprueba que `[start, start + duration_min)` sigue libre; si no, `SlotTaken`.
4. `insert_event` con el id determinista. Un 409 → `get_event` y se devuelve esa cita.

**Id determinista:** `base32hex(sha256(f"{tenant_id}:{ctx.idem.event('booking')}"))[:32]`, en minúsculas (Google exige base32hex de 5 a 1.024 caracteres). Reprocesar el mismo evento produce el mismo id, así que la reserva nunca se duplica. Mover una cita usa `ctx.idem.event('move')` para la nueva; cancelar es idempotente.

Una cita que el dueño cree a mano en ese mismo segundo puede solaparse: se acepta.

#### 9.6 Barrido de Calendar (`calendar_sweep`, cada 15 min por tenant)

Una lectura de `[now, now + booking_window_days + 1]` con dos pasadas:

| Pasada | Condición | Acción |
|---|---|---|
| **Recordatorios** (si `reminders_enabled`) | Cita del bot o manual que empieza dentro de `reminder_window_hours` | `SendProactive(TEMPLATE_REMINDER, [fecha, hora], [reminder_confirm:<id>, reminder_cancel:<id>])` con clave `reminder:<gcal_id>:<start>` |
| **Confirmaciones de citas manuales** (si `manual_confirmations_enabled`) | Cita manual con `created ≥ manual_confirmations_since` que empieza en el futuro | `SendProactive(TEMPLATE_CONFIRMATION, [nombre, fecha, hora], [booking_cancel:<id>])` con clave `confirm:<gcal_id>`. Después escribe `Estado: pendiente` en la descripción si no lo tenía |

- **Destinatario:** en citas del bot, el contacto de `fp_contact` por su canal (§6.6). En citas manuales, el teléfono de la descripción por el canal `main` si es WhatsApp, creando el contacto si no existe; si el canal `main` es Telegram, se registra y no se envía.
- Las claves estables son únicas en `outbound_message`: aunque el barrido corra muchas veces, cada aviso sale una sola vez.

#### 9.7 Plantillas

| `TemplateSpec` | Nombre en Meta | Texto | Botones |
|---|---|---|---|
| `TEMPLATE_CONFIRMATION` | `confirmacion_cita` (Utility, `es_ES`) | "Hola {1}, tu cita ha sido confirmada para el {2} a las {3}. Si necesitas cancelarla, pulsa el botón." | Cancelar cita |
| `TEMPLATE_REMINDER` | `recordatorio_cita` (Utility, `es_ES`) | "Recuerda que tienes cita el {1} a las {2}. ¿Confirmas tu asistencia?" | Confirmar · Cancelar |

El operador crea las plantillas en el WhatsApp Manager de cada negocio. `pack.health` comprueba que están aprobadas y que el calendario es accesible.

#### 9.8 Escenarios obligatorios

Reserva completa · día sin huecos · mañana/tarde · `SlotTaken` · límite de citas · Calendar caído al pedir cita (falla en abierto) y al crear (texto de recuperación) · reintento de una reserva ya creada · `[CFG] CERRADO`, `VACACIONES` y `HORARIO` · servicio con presencia larga cerca del cierre · mover y cancelar · evento especial activo e inactivo · recordatorio una sola vez en dos barridos · confirmación de una cita manual (y ninguna para las anteriores a `manual_confirmations_since`) · botón de recordatorio sobre una cita ajena · `baja` → sin recordatorios · cita antigua con `WaId:` · la misma reserva completa por Telegram (canal `main` de tipo Telegram y bot de pruebas).

---

### 10. Pack `bus` (horarios de autobús)

Se porta de `buscaBus` casi tal cual: `services/horarios/` (modelo, formato, loader, query, calendario, diff, datos), `utils/matcher.py`, `utils/fechas.py`, `handlers/flujo.py`, `utils/messages.py`, sus constructores de listas, `tools/` y todos sus tests y fixtures. Cambia el pegamento: entra por `PackContext`, el estado se guarda en BD y los datos se cargan por tenant.

#### 10.1 Dataset de horarios

```
tenants/<slug>/datasets/timetable/
  paradas.yaml        localidades (id, nombre, alias, pendientes), paradas (código, nombre, localidad),
                      pares no vendibles
  observaciones.yaml  catálogo de observaciones (letra, tipo condición/aviso, ámbitos, texto exacto)
  calendario.yaml     vigencia, festivos generales y locales, periodo escolar, días sin servicio
  lineas/<id>.yaml    temporadas (cubren el año sin huecos ni solapes); tablas por temporada y clase
                      de día; viajes con horas (HH:MM o llegada>salida), observaciones y bus:<id>
```

El formato completo es el de `buscaBus/horarios/` y se documenta en `docs/packs/bus.md`.

- **Validador estricto** (`packs/bus/formato.py`, el mismo para herramientas, tests y carga). Cada error dice fichero, tabla, fila y motivo. Detectan, entre otros: paradas, letras u observaciones sin definir; horas que retroceden; temporadas con huecos o solapes; `bus:` incoherente; alias vacíos o repetidos; ids de línea mal formados; pendientes mal formados. Los avisos (posible mismo autobús no declarado, clases de día sin datos, pendientes abiertos) se listan sin bloquear. **Nada ambiguo pasa.**
- **`load_data`** convierte el dataset en objetos inmutables (`Localidad`, `Parada`, `Observacion`, `Linea`, `Temporada`, `Tabla`, `Viaje`, `Paso`), construye los índices (`localidad_paradas`, `localidad_viajes`, `festivos_por_linea`, `lineas_pueblos`) y el `Matcher`, y comprueba que existen los pueblos de `start_menu_towns`. Ocupa pocos MB por tenant.
- **Ciclo de actualización:**
  1. Se edita el fichero de la línea.
  2. `make bus-formatear TENANT=<slug>` y `make bus-validar TENANT=<slug>`.
  3. `make bus-revision TENANT=<slug>` genera `revision/<slug>/horarios.html` y `.pdf` (no se versionan), con los **cambios desde la versión publicada** en lenguaje de negocio.
  4. La empresa confirma.
  5. Commit, despliegue y `make bus-publicar TENANT=<slug>`, que crea el tag `datos/<slug>/AAAA-MM-DD`, la base del siguiente diff.
- Los cambios con fecha futura se publican el día que entran en vigor.

#### 10.2 Motor de consulta

Entrada `(origen, destino, fecha)`. Salida: salidas ordenadas con hora de salida (del `Paso` de origen), llegada (del `Paso` de destino), duración, parada y notas. Sin E/S.

0. Casos previos, en orden: par no vendible → `no_vendible`; ninguna línea conecta el par → `sin_trayecto`; día sin servicio en ninguna línea → `sin_servicio`; fecha fuera de vigencia → `sin_datos`.
1. Calendario de la fecha **para cada línea**: temporada; clase de día (laborable, sábado, domingo y festivos; un festivo local solo afecta a las líneas que pasan por esa localidad); lectivo; mes.
2. Filtra los viajes por línea, temporada, clase de día y condiciones (con ámbito de línea, de viaje o de una parada de un viaje).
3. Un viaje sirve si para en una parada del origen y, **más adelante en su orden**, en una del destino.
4. **Mismo autobús:** si dos líneas tienen las mismas horas para el par, se muestra una sola salida con las notas de ambas.
5. Ordena por hora de salida. Si la fecha es hoy, las salidas pasadas no se listan y se cuentan.
6. Si alguna línea implicada no tiene datos ese día, el resultado lo dice: **`sin_datos` nunca se presenta como "no hay servicio"**.
7. Nunca inventa trasbordos.

#### 10.3 Conversación

```
MENÚ        [🚌 Ver horarios] [ℹ️ Información]
ORIGEN      lista: start_menu_towns (8) + ✍️ Otro pueblo + ↩️ Volver al menú
DESTINO     solo alcanzables y vendibles desde el origen; si son ≤ 9, la lista completa;
            si no, los 8 más relevantes (Córdoba primero) + ✍️ Otro destino + ↩️ Cambiar origen
DÍA         7 días con "N salidas · de HH:MM a HH:MM" / "N salidas · próxima HH:MM" /
            "ya no quedan salidas hoy" / "sin servicio" / "horario no disponible"
            (prefijo "festivo · ", sufijo "· puede haber más") + 📅 Otra fecha
RESULTADO   [📅 Otro día] [🔄 Ver la vuelta] [🔍 Otra consulta]
```

Estados: `MENU`, `SEL_ORIGEN`, `SEL_DESTINO`, `SEL_DIA`, `RESULTADO`, `ESCRIBIR_ORIGEN`, `ESCRIBIR_DESTINO`, `ESCRIBIR_FECHA`, `CONFIRMAR_PUEBLO` y la navegación de líneas y pueblos.

- **Matcher:**
  - Normalización: la común, más quitar artículos y `de`/`del`, más quitar el relleno inicial (`desde`, `a`, `hacia`, `para`, `voy a`).
  - Orden de búsqueda: exacto, luego prefijo del nombre entero (≥ 3 letras), luego errata por Damerau-Levenshtein (≤ 1 hasta 5 letras, ≤ 2 si la palabra es más larga).
  - Resultado: una coincidencia → continúa (una errata se confirma con Sí/No); 2–3 → botones; 4–9 → lista; más de 9 → "Sé más concreto"; ninguna → "No conozco ese pueblo" + **Ver pueblos por línea**.
  - Un alias compartido (`villafranca`) **siempre pregunta**, aunque esté escrito con errata.
  - En el destino se busca entre todas las localidades, para responder "sin trayecto directo" en vez de "no conozco".
  - Dos pueblos en un mismo mensaje no se interpretan.
- **Ver pueblos por línea:** líneas (8 por página + "Más líneas" + volver), después los pueblos de la línea (8 + "Ver más" + "Volver a líneas"). En el destino solo se muestran líneas que salen del origen y pueblos alcanzables desde él.
- **Localidad pendiente:** "Algunos autobuses paran en X, a unos N minutos de Y, pero aún no tenemos su hora de paso." + `Usar Y` / `Otro pueblo`.
- **Fechas en formato cerrado** `día/mes[/año]`:
  - Separadores `/ - . espacio`; un año de 2 cifras es 20xx.
  - Sin lenguaje natural.
  - Sin año: si esa fecha ya pasó hace 30 días o menos → "Esa fecha ya ha pasado"; si no, se toma la próxima vez que llegue.
- **Resultado:**
  - Cabecera con trayecto, día y temporada (solo si todas las salidas son de una única temporada con nombre público) o festivo.
  - Una línea por salida: `HH:MM → HH:MM (1h 20)`, más la parada de salida.
  - Notas: la que afecta a todas las salidas va como `⚠️` al final; las que afectan solo a algunas llevan marcas ¹ ² ³.
  - Si supera 4.096 caracteres se corta en la última salida completa y se añade "…y N salidas más, llama al <teléfono>".
  - Día sin salidas → siguiente día con salidas en `next_day_search_days`, ofrecido en un botón.
  - 25/12 y 01/01 → "no hay servicio en ninguna línea" + teléfono y horario de oficina.
- **Información:** teléfono, horario de oficina por días (solo se muestra; el bot nunca calcula si está abierta) y los enlaces que no estén vacíos.
- **Textos no reconocidos** (pueblo o fecha): se registran con el texto normalizado y el paso, nunca con el identificador del contacto.
- Sin avisos proactivos ni periódicas.

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
    start_menu_towns: list[str] = Field(max_length=8)    # nombres de localidades del dataset
    next_day_search_days: int = 45
```

#### 10.5 Pruebas obligatorias

Se portan las de buscaBus (`test_formato`, `test_diff`, `test_formatear`, `test_revision`, `test_loader`, `test_query` con sus pruebas doradas, `test_calendario`, `test_matcher`, `test_fechas`, `test_conversation`, `test_interactive`).

Escenarios de conversación: consulta completa · Ver la vuelta · Otro día · día sin servicio con siguiente día · `sin_datos` · no vendible · sin trayecto · origen = destino · Villafranca (también con errata) · errata confirmada y rechazada · pueblos por línea con paginación · localidad pendiente · fecha pasada · 25/12 · hoy sin salidas restantes · fecha escrita inválida · resultado de más de 4.096 caracteres · consulta completa por Telegram (canal `main` de tipo Telegram y bot de pruebas).

---

### 11. Avisos al dueño y alertas de operación

Un **bot de avisos de la plataforma** (`NOTIFY_BOT_TOKEN`), distinto de los bots de canal y **solo de salida**: no tiene webhook ni recibe mensajes en producción.

- **`NotifyOwner(kind, text, idem_key)`:** si el tenant tiene `owner.telegram_chat_id` y `kind` está en `owner.notify`, se guarda en `notification` (única por `idem_key`) y se entrega con `send_notification` (cola `outbound`, candado `owner:<tenant>`, reintentos ante 429 y 5xx). Si no, solo se registra.
- **Vinculación:** `manage.py notify_link <slug>` genera un código; el dueño envía `/start <código>` al bot de avisos; el comando lee `getUpdates`, muestra su `chat_id` y el operador lo añade al `tenant.yaml`.
- **Alertas de operación:** las envía `ops_check` (§15.3) con el mismo bot al chat `OPS_TELEGRAM_CHAT_ID`. No pasan por `notification`: se deduplican con un enfriamiento de 30 min por tipo y tenant, guardado en la caché de Django en BD.

---

### 12. Datos

#### 12.1 Modelo

Las tablas con 🔒 llevan `tenant_id` y RLS. Claves primarias UUIDv7 (`uuid.uuid7()` de Python 3.14). Fechas en `timestamptz`. Las tablas padre tienen `UNIQUE(tenant_id, id)` y las hijas usan claves foráneas compuestas `(tenant_id, x_id)`, de modo que una fila de un tenant no puede apuntar a otra de otro.

```text
tenant 🔒*          id, slug, name, pack, status, timezone, synced_at       (reflejo de tenants/*.yaml)

contact 🔒          id, tenant_id, channel[main|test], external_id, phone_e164 NULL,
                    display_name, opt_out, opt_out_at, unreachable,
                    last_activity_at, created_at              UNIQUE(tenant_id, channel, external_id)
conversation 🔒     id, tenant_id, contact_id, state jsonb, state_version, last_inbound_at, updated_at
                                                              UNIQUE(tenant_id, contact_id)

inbound_event 🔒    id, tenant_id, channel[main|test], kind[message|status], provider_event_id, payload jsonb,
                    status[pending|done|failed|ignored], error, received_at, processed_at
                                                              UNIQUE(tenant_id, channel, provider_event_id)
outbound_message 🔒 id, tenant_id, contact_id, channel[main|test], idem_key, seq, kind[reply|proactive],
                    payload jsonb, status[pending|sending|sent|failed|unknown], attempts,
                    provider_message_id, pricing_category, billable, last_error,
                    inbound_event_id NULL, created_at, sent_at
                                                              UNIQUE(tenant_id, idem_key)
notification 🔒     id, tenant_id, idem_key, kind, text, status[pending|sent|failed], created_at, sent_at
                                                              UNIQUE(tenant_id, idem_key)
```

\* `tenant` tiene RLS sobre su propio `id`.

**Tablas del bot de pruebas** (de plataforma, sin `tenant_id` ni RLS, porque se escriben antes de saber el negocio; solo las usa el selector, §6.5):

```text
test_bot_event      id, update_id UNIQUE, payload jsonb, status[pending|done|failed], received_at
test_session        telegram_user_id PK, tenant_id, selected_at
```

- Además están las tablas de Procrastinate (sin `tenant_id` ni RLS; por eso los trabajos solo llevan ids) y las de Django (usuarios del Admin, sesiones, caché, `LogEntry`).
- No hay tablas de citas ni de horarios: las citas viven en Google Calendar y los horarios en git y en memoria.
- `payload` de `outbound_message` guarda la respuesta común (`Reply` o `ProactiveMessage` serializados), no el formato del proveedor: el adaptador la renderiza al enviar.

#### 12.2 Aislamiento (RLS)

| Rol | Lo usan | `BYPASSRLS` | Permisos |
|---|---|---|---|
| `fp_app` | `web` (webhooks) y `worker` | No | SELECT, INSERT, UPDATE y DELETE sobre las tablas de la aplicación y de Procrastinate |
| `fp_owner` | Migraciones, Django Admin y comandos de operación entre tenants (`purge_tenant`, `export_tenant`) | Sí | Dueño de las tablas |

```sql
ALTER TABLE contact ENABLE ROW LEVEL SECURITY;
ALTER TABLE contact FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON contact
  USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
```

- **El tenant solo se fija con `tenant_tx(tenant_id)`:** abre una transacción corta y ejecuta `set_config('app.tenant_id', …, true)` (equivale a `SET LOCAL`). Nunca se anida (`assert not connection.in_atomic_block`). Sin tenant fijado se leen 0 filas, de modo que un olvido falla de forma segura.
- `NULLIF(…, '')` es necesario: con conexiones persistentes, tras un `SET LOCAL` las transacciones siguientes ven `''` en lugar de NULL.
- Django tiene dos alias: `default` (`fp_app`) y `owner` (`fp_owner`). El Admin usa `owner` mediante una clase base de `ModelAdmin` (`using = "owner"`). Las URL `/admin/` solo se montan en `web` y Caddy no las expone (§13).
- Los trabajos que recorren tenants (repartos, retención, `ops_check`) obtienen la lista del registro en memoria y abren un `tenant_tx` por tenant.
- Las dos tablas del bot de pruebas no tienen RLS: `test_session` solo relaciona un usuario de Telegram con un tenant y `test_bot_event` solo la lee el selector, que no consulta datos de ningún tenant.
- **Test genérico de aislamiento** (obligatorio en CI): para cada modelo con `tenant_id` comprueba, con los tenants A y B, que A no lee, modifica, borra ni inserta filas de B, que no crea claves foráneas hacia B y que sin tenant fijado se leen 0 filas. Una tabla nueva sin política hace fallar el test.

#### 12.3 Retención

| Dato | Retención | Cómo |
|---|---|---|
| `inbound_event.payload`, `outbound_message.payload` | 30 días | `retention_cleanup` nocturno, por lotes de 1.000: vacía el payload y conserva los metadatos |
| Filas de `inbound_event` | 90 días | Borrado |
| `test_bot_event` | 7 días | Borrado |
| `test_session` | 30 días sin uso | Borrado |
| Filas de `outbound_message` y `notification` | 12 meses | Borrado |
| `conversation.state` caducado | Inmediato | Se vacía en el siguiente mensaje o en la limpieza nocturna |
| `contact` sin actividad | 12 meses | Borrado junto con su conversación y sus mensajes |
| Backups | 6 meses | Política de restic (§14.4) |
| Tenant dado de baja | ≤ 30 días | §16.2 |

Derechos RGPD: `manage.py export_contact <slug> <external_id>` y `manage.py forget_contact <slug> <external_id>`, que borra contacto, conversación, eventos y mensajes. Las citas del calendario pertenecen al negocio. Estos plazos se recogen en el contrato de encargo con cada negocio.

#### 12.4 Migraciones

- Siempre compatibles con la versión anterior del código (patrón *expand/contract*). Nunca en un solo paso: renombrar o borrar columnas en uso, añadir `NOT NULL` sin valor por defecto en tablas grandes, ni cambiar tipos de forma que se bloquee la tabla.
- CI: `makemigrations --check` y `django-migration-linter`.
- Las migraciones que tocan RLS, roles o borran datos requieren aprobación humana explícita.

---

### 13. Seguridad

| Punto | Protección |
|---|---|
| Webhooks | Autenticidad comprobada **antes de nada** y en tiempo constante (HMAC de Meta, `secret_token` de Telegram); cuerpo ≤ 64 KB; URL con `public_id` aleatorio; límite por IP solo de peticiones con firma inválida; validación de formatos de identificador |
| Superficie pública | Caddy solo enruta `/webhooks/whatsapp/*`, `/webhooks/telegram/*`, `/webhooks/telegram-test` y `/health`; todo lo demás, 404 |
| Admin | No se publica: `web` también escucha en `127.0.0.1:8000` y el operador entra con `ssh -L` (`make admin-tunnel`). Login de Django con 2FA (`django-otp`); cada cambio queda en `LogEntry` |
| Pruebas | El bot de pruebas solo atiende a `TEST_BOT_OPERATORS` y a los `testers.telegram` de cada negocio, y cada uno solo ve sus negocios. En `onboarding`, el canal `main` solo responde a `testers.main` |
| Servidor | SSH solo con clave, sin root; cortafuegos que solo abre 22, 80 y 443; `unattended-upgrades`; `fail2ban` en SSH |
| Base de datos | Sin puerto publicado; RLS con dos roles (§12.2) |
| Contenedores | Usuario no root; sistema de ficheros de solo lectura salvo `/tmp`; secretos montados de solo lectura |
| Secretos | Nunca en git, logs, imágenes, argumentos de trabajos ni respuestas HTTP (§5.3) |
| Logs | Filtro que enmascara tokens, cabeceras `Authorization` y teléfonos (solo los 4 últimos dígitos) |
| Dependencias | `uv.lock`, Dependabot, `pip-audit` en CI, imagen base actualizada cada mes |

---

### 14. Infraestructura y despliegue

#### 14.1 Máquina

- **VPS en la UE**: Hetzner Cloud (Núremberg, Falkenstein o Helsinki), 2 vCPU, 4 GB de RAM y 40 GB de disco [VERIFICAR plan y precio actuales].
- Ubuntu 24.04 LTS con Docker Engine y el plugin de Compose.
- Memoria estimada: PostgreSQL ~0,8 GB (`shared_buffers=512MB`), `web` ~0,3 GB, `worker` ~0,4 GB (datasets en memoria), Caddy ~0,05 GB.
- Dominio propio: `api.<dominio>` apunta a la IP fija de la VPS.

#### 14.2 Docker Compose

```yaml
# compose.prod.yaml (resumen)
x-app: &app
  image: ghcr.io/marianodelrio/flowpilot:${SHA}
  env_file: .env
  volumes: ["./secrets.yaml:/run/secrets/secrets.yaml:ro", "./google_sa.json:/run/secrets/google_sa.json:ro"]
  read_only: true
  tmpfs: [/tmp]
  restart: unless-stopped
  logging: {driver: json-file, options: {max-size: 20m, max-file: "5"}}

services:
  caddy:  image: caddy:2 · ports 80, 443 · volúmenes caddy_data, caddy_config · ./Caddyfile
  web:    <<: *app · command: gunicorn config.wsgi -b 0.0.0.0:8000 --workers 2 --threads 4
          ports: ["127.0.0.1:8000:8000"]    (solo para el túnel del Admin)
          healthcheck: GET /health
  worker: <<: *app · command: manage.py procrastinate worker --concurrency 4 · stop_grace_period: 60s
          environment: DB_OWNER_URL vacío (el worker no la necesita)
  db:     image: postgres:18 · volumen pgdata · sin ports · healthcheck pg_isready
          (shared_buffers 512MB, max_connections 100, log_min_duration_statement 1s)
```

`compose.yaml` (local): los mismos `web`, `worker` y `db`, con la imagen construida en local, código montado, `runserver` y recarga automática del worker; sin Caddy. En local se conversa con los packs mediante el bot de pruebas de desarrollo y `telegram_poll` (§6.4).

#### 14.3 Caddy

```
api.<dominio> {
    request_body { max_size 64KB }
    @public path /webhooks/whatsapp/* /webhooks/telegram/* /webhooks/telegram-test /health
    handle @public { reverse_proxy web:8000 }
    handle { respond 404 }
}
```

Caddy obtiene y renueva los certificados de Let's Encrypt. Django solo confía en `X-Forwarded-For` cuando viene de la red de Compose.

#### 14.4 Backups y restauración

| Qué | Cómo | Cuándo | Retención |
|---|---|---|---|
| PostgreSQL | `pg_dump -Fc` → `restic backup` a almacenamiento S3 de **otro proveedor** (Backblaze B2 o Cloudflare R2), cifrado por restic | Cada 6 h (timer de systemd en el host, `deploy/backup.sh`) | 7 diarias, 4 semanales, 6 mensuales |
| `.env`, `secrets.yaml`, `google_sa.json`, `Caddyfile` | En el mismo `restic backup` | Cada 6 h | Igual |
| Config y datasets | Git (GitHub) | Siempre | Indefinida |
| Contraseña de restic y credenciales del almacenamiento | Gestor de contraseñas del operador (no van en el backup) | — | — |

- El backup termina con un ping a healthchecks.io: si no llega en 7 h, salta una alerta.
- **`deploy/restore.sh`:** VPS nueva → Docker → clonar el repositorio → restaurar ficheros con restic → `pg_restore` → `docker compose up` → apuntar el DNS. Objetivo: menos de 2 h.
- **Simulacro trimestral:** restaurar el último backup en una VPS temporal o en local, comprobar los conteos por tenant y anotar el resultado y el tiempo (runbook 6).

#### 14.5 Costes [estimación; VERIFICAR precios]

| Pieza | €/mes |
|---|---:|
| VPS 2 vCPU / 4 GB | ~5–9 |
| Almacenamiento de backups (pocos GB) | ~0–1 |
| Dominio | ~1 |
| Sentry, healthchecks.io, UptimeRobot o Better Stack (planes gratuitos), GHCR y GitHub Actions (cuota gratuita) | 0 |
| **Total** | **~6–11** |

Quedan ~10 € de margen hasta el objetivo de 20 € para una VPS de 8 GB si hiciera falta. Fuera de la cifra: los mensajes de WhatsApp (los paga cada negocio en su cuenta de Meta). Telegram y la API de Google Calendar son gratuitos al volumen previsto.

#### 14.6 Despliegue

- **Imagen:** `Dockerfile` multi-etapa (dependencias con `uv` → imagen mínima con Python 3.14 y usuario no root). Incluye `src/` y `tenants/`, de modo que cada imagen es un estado coherente de código y config. La etiqueta es el SHA del commit; se publica en GHCR. Los estáticos del Admin se sirven con WhiteNoise.
- **CI** (`ci.yml`): en cada push a `main` ejecuta las puertas de §17.3 y, si pasan, construye y publica la imagen.
- **Despliegue** (`deploy.yml`, lanzado a mano con `workflow_dispatch`): `ssh deploy@vps "deploy/deploy.sh <sha>"`, con una clave SSH limitada a ese script:
  1. `docker compose pull`
  2. `docker compose run --rm web manage.py migrate && manage.py sync_tenants`. Si falla, se para aquí y no cambia nada.
  3. `docker compose up -d web worker`
  4. Espera a que `/health` devuelva 200 (máximo 60 s). Si no llega, `deploy.sh` vuelve a desplegar el SHA anterior y avisa a ops.
- Durante los segundos en que `web` se recrea, Caddy devuelve 502 y Meta y Telegram reintentan. El `worker` termina sus trabajos antes de parar.
- **Vuelta atrás:** volver a desplegar el SHA anterior. Las migraciones no se revierten, porque son compatibles hacia atrás.
- Se despliega preferiblemente fuera de las horas punta de los negocios (antes de las 9:00 o después de las 21:00).

#### 14.7 Crecimiento

| Señal | Acción |
|---|---|
| CPU o RAM > 70 % sostenido | Subir de plan la VPS (unos minutos de corte) |
| Trabajos de `inbound` esperando > 30 s | Subir la concurrencia del `worker` o añadir un segundo servicio `worker` |
| Los barridos retrasan las respuestas | Un servicio `worker` aparte con `--queues periodic` |
| Más de 15 negocios, o uno que dependa del servicio en horas críticas | PostgreSQL gestionado y varias VPS de aplicación con la misma imagen |

---

### 15. Observabilidad

#### 15.1 Logs

- JSON a la salida estándar, rotados por Docker. Se consultan con `make logs SERVICE=…`.
- Campos: `ts`, `level`, `msg`, `service`, `tenant`, `channel`, `event_id` (hace de `trace_id`: se propaga a envíos y llamadas a Calendar) y `job`.
- Sin datos sensibles (§13).

#### 15.2 Errores

Sentry (plan gratuito): excepciones de `web` y `worker` con `tenant` y `event_id`; la versión es el SHA desplegado.

#### 15.3 `ops_check` (cada 5 min, en el worker)

| Comprobación | Umbral | Gravedad |
|---|---|---|
| Trabajo más antiguo listo en `inbound` | > 2 min | 🔴 |
| Trabajos `failed` | ≥ 1 en 10 min | 🟠 |
| `outbound_message` en `failed`, o en `unknown` desde hace > 10 min | ≥ 1 | 🟠 |
| Envío rechazado por autenticación (token revocado) | 1 | 🔴 |
| Calendar sin acceso, o 3 errores seguidos de un tenant | 1 | 🔴 |
| Tenant `degraded`, o canal sin secretos | 1 | 🔴 |
| Barrido de un tenant sin completarse en > 1 h | 1 | 🟠 |
| `pack.health` y salud de canales (una vez al día): plantillas no aprobadas, token de WhatsApp inválido, `getWebhookInfo` de Telegram con errores | 1 | 🟡 / 🔴 |
| Mensajes facturables de WhatsApp del mes > `monthly_alert_threshold` | 1 | 🟡 |
| Disco > 85 % | 1 | 🟠 |

- Las alertas van al chat de ops (§11) y se repiten como mucho cada 30 min por tipo y tenant.
- Al terminar, `ops_check` envía un **latido a healthchecks.io**. Si el worker, la BD o la VPS caen, el latido deja de llegar y healthchecks.io avisa por email y Telegram, sin depender de la plataforma.
- **Uptime externo** (UptimeRobot o Better Stack) comprueba `https://api.<dominio>/health` cada 5 min. Detecta caídas de Caddy o `web`, fallos de DNS y la caducidad del certificado.
- **`/health`** devuelve 200 si hay conexión a la BD, junto con el número de tenants cargados y `degraded`. No llama a servicios externos.

#### 15.4 Panel

Una vista "Estado" en el Admin muestra:

- Colas: trabajos pendientes y antigüedad del más antiguo.
- Trabajos fallidos.
- Envíos en `unknown` o `failed`.
- Por tenant y canal: mensajes del mes (entrantes, salientes y facturables), último barrido, estado del tenant y resultado de `pack.health`.

---

### 16. Operación

#### 16.1 Alta de un negocio

1. `manage.py new_tenant <slug> --pack salon|bus` crea `tenants/<slug>/tenant.yaml` con `id`, `status: onboarding` y la config por defecto del pack.
2. Completar la config. En `bus`, añadir el dataset y pasar `make bus-validar`.
3. **Pruebas:** añadir a `testers.telegram` los ids de Telegram de las personas del negocio que vayan a probar.
4. **Canal `main`:**
   - WhatsApp: seguir el checklist de §6.3, declarar `channel` y añadir sus secretos a `secrets.yaml`.
   - Telegram: crear el bot con @BotFather a nombre del negocio, declarar `channel` y añadir `bot_token` y `webhook_secret` a `secrets.yaml`.
5. **Google Calendar** (`salon`): el negocio comparte su calendario con la cuenta de servicio y se pone el `calendar_id` en la config. Si el canal es WhatsApp, crear las plantillas del pack en el WhatsApp Manager.
6. **Avisos al dueño** (opcional): `manage.py notify_link <slug>`.
7. Commit y despliegue. Si el canal `main` es Telegram, `manage.py telegram_set_webhook <slug>`.
8. `manage.py tenant_health <slug>` en verde.
9. Pruebas con el negocio por el bot de pruebas y, por el canal `main`, con los ids de `testers.main`.
10. `status: active`, commit y despliegue. `tools/qr.py <slug>` genera el QR de `wa.me` para el local.

#### 16.2 Baja de un negocio

1. `status: offboarded` y despliegue: los webhooks se contestan con 200 sin guardar nada.
2. `manage.py export_tenant <slug>`, si se acordó con el negocio.
3. `manage.py purge_tenant <slug>` borra contactos, conversaciones, eventos, mensajes y avisos. Pide escribir el slug para confirmar.
4. Quitar su entrada de `secrets.yaml` y, si su canal es Telegram, `deleteWebhook` de su bot.
5. El negocio revoca el acceso del operador a su portfolio de Meta y deja de compartir el calendario.
6. Borrar `tenants/<slug>/`.

#### 16.3 Comandos (`Makefile`)

`make deploy SHA=…` · `make status` · `make logs SERVICE=…` · `make admin-tunnel` · `make backup-now` · `make restore-test` · `make shell` · `make tenant-health SLUG=…` · `make telegram-poll [SLUG=…]` · `make bus-validar | bus-formatear | bus-revision | bus-publicar TENANT=…`.

#### 16.4 Runbooks (`docs/runbooks/`)

1. El bot no responde a nadie.
2. El bot no responde a un negocio o a un canal.
3. La cola se acumula o falta el latido.
4. Google Calendar sin acceso o con errores.
5. Envíos en `unknown` o `failed`.
6. Restaurar la BD y simulacro trimestral.
7. Volver atrás un despliegue.
8. Incidente de seguridad o fuga de datos.
9. Rotar los secretos de un canal.
10. Actualizar los horarios de `bus`.
11. Mantenimiento periódico: versión de la Graph API (cada 6 meses), dependencias y CVE (mensual), reinicio de la VPS por parches del kernel (mensual), calidad del número y estado de las plantillas (trimestral).

---

### 17. Pruebas

#### 17.1 Tipos

| Tipo | Qué prueba | Necesita | Ejemplos |
|---|---|---|---|
| **Unitarias** | Funciones puras | Nada | `compute_slots`, lectura de `[CFG]` y de descripciones, `plan_sends`, motor de horarios, matcher, fechas, validador |
| **Escenarios** | Conversaciones completas de un pack | Nada (`FakeCalendar`, datasets de ejemplo, reloj fijo) | §9.8, §10.5 |
| **Adaptadores** | `parse`, `render` y clasificación de errores de cada canal contra **payloads reales grabados** | Fixtures JSON | Mensaje con BSUID, botón de plantilla, estado `failed`, `callback_query`, 403 de Telegram, 429 con `retry_after` |
| **Datos de tenants** | Todos los `tenant.yaml` y datasets validan | Ficheros del repositorio | Un precio mal escrito deja CI en rojo |
| **Integración** | Webhook → cola → worker → envío, con BD real | PostgreSQL | Aviso duplicado procesado una vez; dos mensajes del mismo contacto en orden; dos reservas del mismo hueco → un `SlotTaken`; reintento de una reserva creada → sin duplicado; barrido dos veces → un aviso; `unknown` no se reenvía; tenant `degraded` no afecta a otro; selector del bot de pruebas (usuario sin permiso, elegir negocio, cambiar con `/negocio`, negocio que deja de estar disponible) |
| **Aislamiento** | RLS en todas las tablas con `tenant_id` | PostgreSQL | §12.2 |
| **Contrato de Calendar** | Cliente contra respuestas grabadas | Fixtures | 409, paginación, eventos de día completo |
| **Migraciones** | No faltan y no son peligrosas | PostgreSQL | — |

#### 17.2 Arnés de conversación

Los escenarios se escriben en pytest. El arnés ejecuta el pack con el mismo runtime de conversación (comandos globales, caducidad y `plan_sends`) sin BD ni red, y puede simular cualquiera de los dos tipos de canal:

```python
def test_reserva_completa(salon):                     # tenant de ejemplo + FakeCalendar + reloj fijo
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
```

Cada respuesta se comprueba contra los límites comunes (§6.1) y se renderiza con los dos adaptadores, así que un pack que se sale de los límites falla en los tests.

#### 17.3 Puertas de CI (si fallan, no se publica imagen)

1. `ruff` + `mypy`.
2. `import-linter`.
3. Unitarias, escenarios, adaptadores y datos de tenants (sin BD).
4. Integración, aislamiento y contrato, con PostgreSQL 18 como servicio.
5. `makemigrations --check` + linter de migraciones.
6. `pip-audit`.
7. Construcción de la imagen.

---

### 18. Pendiente de verificar

| Tema | Qué falta |
|---|---|
| VPS | Plan y precio actuales del proveedor |
| Precio de los mensajes de WhatsApp | Tarifa real de los mensajes de servicio y de las plantillas *utility* en la cuenta de cada negocio |
| BSUID | Si se pueden enviar plantillas a un contacto identificado solo por BSUID. Si no, sus avisos proactivos se registran y no se envían |
| Graph API | Fecha de caducidad de `v23.0` |
| Google Calendar | Avisos de Google sobre cuotas o facturación de la API |
| Datos de `bus` | Preguntas abiertas a la empresa (P28 días especiales, P30 verano de Adamuz, P37), anotadas en el dataset |
| Identificar el bot como automático | Si la normativa lo exige a bots sin IA; bastaría con indicarlo en el texto del menú |

**Versiones verificadas (octubre de 2026):** Python 3.14 · Django 5.2 LTS (5.2.18, soporte hasta abril de 2028, compatible con 3.14) · PostgreSQL 18 · Procrastinate 3.10 (su CI prueba Python 3.14 con PostgreSQL 18) · psycopg 3.3 · pydantic 2.14 · google-api-python-client 2.x · httpx 0.28 · gunicorn · django-otp.

---

### 19. Documentación

- `README.md`: qué es, estado y cómo arrancar en local.
- `design.md`: este documento.
- `docs/adr/`: ADR-001 (monolito modular), ADR-002 (RLS), ADR-003 (packs), ADR-004 (entrada idempotente), ADR-005 (VPS con Docker Compose).
- `docs/packs/salon.md` y `docs/packs/bus.md`: qué hace cada pack, su config, sus plantillas y, en `bus`, el formato del dataset y su ciclo de actualización.
- `docs/runbooks/`: los de §16.4.
- `docs/glosario.md`: términos técnicos en lenguaje llano.
