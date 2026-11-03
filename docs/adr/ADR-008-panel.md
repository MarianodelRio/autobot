# ADR-008 — Panel interno: arquitectura, acceso y observabilidad

**Estado:** aceptada

## Contexto

El Django Admin deja de bastar: hace falta ver de un vistazo si todo va bien, cuánto se
usa la plataforma, y actuar sobre los negocios sin entrar por SSH ni por `manage.py` para
cada cosa. El diseño completo está en
[`docs/panel/DESIGN.md`](../panel/DESIGN.md); este ADR fija las decisiones de
arquitectura que no son triviales de deshacer.

## Decisión

- **Dos contenedores nuevos:** `panel` (Caddy interno, sirve una SPA estática con Vite y
  hace de proxy de `/api/` hacia `web:8000`) y `victorialogs` (almacén de logs, 31 días,
  solo red interna). `panel` escucha en `127.0.0.1:8080`; nada nuevo queda expuesto a
  internet (DESIGN §3.1, §10).
- **Mismo origen.** La SPA llama a `/api/panel/...` en el mismo origen que la sirve: sin
  CORS, con las cookies de sesión de Django funcionando tal cual. El Caddy público nunca
  reenvía `/api/`, y `PanelGateMiddleware` responde 404 si la petición llega con la
  cabecera `X-Autobot-Edge` que añade ese Caddy (DESIGN §3.2).
- **Acceso solo por túnel SSH** (`make panel-tunnel`), nunca directo ni por Tailscale.
- **API con django-ninja**, como subpaquete `autobot.panel` (no una app Django nueva), con
  esquemas Pydantic y OpenAPI generado; sin Swagger expuesto (DESIGN §6.1, §6.3).
- **Sesión con contraseña + TOTP** (`django_otp`), un único rol (solo la persona usa el
  panel), bloqueo por usuario tras 5 fallos en 15 min, sesión de 12 h, cookies con nombre
  propio y `Secure=False`: el tráfico va por el túnel SSH a `127.0.0.1`, nunca en claro
  por una red no confiable (DESIGN §6.2).
- **Enrutado de base de datos por modelo, no por petición.** `AuthDatabaseRouter` manda a
  `owner` (`fp_owner`, `BYPASSRLS`) los modelos de `auth`, `contenttypes`, `sessions`,
  `otp_totp` y `django_otp`; todo lo demás va a `default` (`fp_app`, con RLS). Los
  servicios del panel usan `.using("owner")` de forma explícita en las consultas que
  cruzan negocios. Cuando el panel llama a código de la plataforma (`build_summary`,
  `ops.health`, `tenant_tx`…), ese código corre igual que en el worker, con `default` y
  RLS, así que nunca puede mezclar datos de dos negocios (DESIGN §3.3). Desaparece el
  router por petición actual (`admin_db.py`).
- **Tercer rol de solo lectura, `fp_readonly`** (`LOGIN NOBYPASSRLS`, solo `SELECT`), para
  la consola SQL del panel. Siempre de solo lectura, con `READ ONLY`, `statement_timeout`
  y rollback forzado; admite únicamente una sentencia `SELECT`/`WITH … SELECT`/`VALUES`
  (sin `EXPLAIN`), ejecutada con cursor con nombre. Un selector "todos los clientes" o un
  cliente fija `app.tenant_id` o `app.readonly_all`; cada tabla con RLS añade una política
  `readonly_all` además de `tenant_isolation` (DESIGN §8.2).
- **Observabilidad sin piezas nuevas de monitorización:**
  - logs técnicos enviados por la propia app a VictoriaLogs (`VictoriaLogsHandler`, con el
    mismo filtro de privacidad que la consola), en vez de un colector aparte o el socket
    de Docker (DESIGN §7.3);
  - métricas de máquina leyendo `/proc/meminfo`, `/proc/stat` y `/proc/loadavg` dentro del
    contenedor `web`, en vez de un agente externo (DESIGN §7.4);
  - el bot de ops es un reflejo del panel: toda alerta que hoy manda a Telegram se
    persiste (`ops_alert`) y se ve en el panel; el panel nunca muestra menos que el bot
    (DESIGN §7.1, principio 3).
- **Fin del Django Admin** (DESIGN §11): el panel lo sustituye por completo; no convive
  con él.

## Alternativas consideradas

- **Next.js (o cualquier SSR) en vez de una SPA con Vite:** sin beneficio detrás de un
  login, y exige un runtime de Node en producción, con más RAM y más piezas que operar.
- **Desplegar la SPA en Vercel o similar:** rompería "acceso solo por túnel SSH" y
  añadiría una dependencia externa a algo que debe quedar privado.
- **Un BFF o API aparte de Django:** una capa más solo se justifica con varios frontends o
  varios backends, que no es el caso.
- **Beszel, Netdata o Prometheus para las métricas de máquina:** piezas adicionales que
  operar para un dato que `/proc` ya da dentro del contenedor.
- **Loki en vez de VictoriaLogs:** VictoriaLogs pide menos RAM a esta escala y acepta
  líneas JSON directamente por HTTP sin un colector.
- **Mantener el router de base de datos por petición (`admin_db.py`):** el enrutado por
  modelo es más simple de razonar y no depende de en qué vista se ejecuta el código.

## Consecuencias

- El panel añade dos contenedores y un tercer rol de base de datos, pero ninguna pieza de
  monitorización externa.
- Toda la lógica de negocio sigue en Django; el frontend nunca es la única barrera de
  validación ni de permisos (principio 2 de DESIGN).
- Un error en la consola SQL no puede escribir ni dejar una transacción abierta: lo impide
  el rol, no solo el código.
- El acceso al panel depende de que el túnel SSH exista; no hay versión móvil ni acceso
  sin él (fuera de alcance de la v1, DESIGN §14).

## Cuándo revisarla

- Si se necesita acceso sin túnel SSH (por ejemplo, para más de una persona operando desde
  sitios distintos), replantear la autenticación y `Secure=False`.
- Si el volumen de logs o de negocios crece lo bastante para que `/proc` o VictoriaLogs
  dejen de bastar, reconsiderar una pieza de monitorización dedicada.
