# ADR-020 — La API del panel en un servicio propio, redes separadas y contenedores endurecidos

**Estado:** aceptada

## Contexto

Hasta ahora `web` atendía a la vez los webhooks públicos y la API del panel
([ADR-008](ADR-008-panel.md)), y por eso recibía `DB_OWNER_URL` y `DB_READONLY_URL`:
`fp_owner` tiene `BYPASSRLS`. El proceso más expuesto de la plataforma (el que recibe
tráfico de internet a través de Caddy) tenía por tanto en su entorno la credencial que se
salta el aislamiento entre negocios. `PanelGateMiddleware` y la cabecera `X-Autobot-Edge`
impedían llegar a la API desde fuera, pero una vulnerabilidad en cualquier ruta pública
habría dado acceso a esa credencial. Además, todos los contenedores compartían una única
red, de modo que Caddy alcanzaba PostgreSQL y VictoriaLogs sin necesidad, y ninguno de los
contenedores de la aplicación descartaba capacidades.

## Decisión

- **Dos servicios con la misma imagen.** `web` (público) atiende webhooks y `/health`; solo
  usa `fp_app` (`DB_OWNER_URL` y `DB_READONLY_URL` vacíos, igual que los workers). El nuevo
  `web-panel` sirve la API del panel (`/api/panel/`) con `fp_owner` y `fp_readonly`.
- **`web-panel` no es alcanzable desde fuera.** No publica ningún puerto y no está en la red
  `edge`: solo lo alcanza el contenedor `panel` (red `panel`). La Caddy interna del panel
  (`apps/panel/Caddyfile`) apunta a `web-panel:8000` para `/api/*` y para `forward_auth` de
  `/docs`; la Caddy pública sigue apuntando a `web:8000` con su lista cerrada de rutas.
  `PanelGateMiddleware` se mantiene como segunda barrera: `web` responde 404 a `/api/panel/`
  si llega la cabecera del borde y 503 si, sin ella, no tiene alias `owner`.
- **Los comandos de operación van a `web-panel`**, que es quien tiene `owner`:
  `deploy.sh` (`migrate`, `apply_grants`, `tenant_config validate`, `seed_demos`),
  `manage.sh`, `restore.sh` y `restore-test.sh`. Solo el aviso de operaciones de `deploy.sh`
  sigue usando `web`, que no necesita `owner`. El despliegue espera además a que `web-panel`
  esté sano (`wait_panel`), y `ops/containers.py` lo añade a los servicios esperados y a los
  que deben llevar la imagen del SHA desplegado.
- **En local sigue habiendo un único `web`** (con `owner` y `readonly`, como antes), con el
  alias de red `web-panel` para que la imagen del panel funcione con
  `docker compose --profile panel`. No hay Caddy ni borde público ni datos de clientes, y
  un segundo proceso ralentizaría el `--reload` y el proxy de Vite sin aportar seguridad.
- **Redes separadas** en `compose.prod.yaml`: `edge` (caddy, web), `panel` (panel,
  web-panel), `egress` (workers: su salida a Meta, Google y Telegram), `data` (db, web,
  web-panel, workers; `internal`, sin salida a internet) y `logs` (victorialogs y quien le
  escribe; `internal`). Caddy no alcanza `db` ni `victorialogs`; `db` y `victorialogs` no
  tienen salida a internet.
- **Contenedores endurecidos:** `cap_drop: [ALL]`, `no-new-privileges` y
  `tmpfs: /tmp:noexec,nosuid` en `web`, `web-panel`, workers, `panel` y `victorialogs`
  (que además pasa a `read_only`). `panel` conserva `NET_BIND_SERVICE`: el binario de Caddy
  lleva esa capacidad como atributo de fichero y, sin ella en el conjunto del contenedor,
  falla al ejecutarse (`operation not permitted`; comprobado con la imagen real).
  `victorialogs` sigue como root dentro del contenedor, pero sin capacidades, sin nuevos
  privilegios y con el sistema de ficheros de solo lectura: con un usuario sin privilegios
  no arranca (la imagen es `scratch`, sin `chown`, y el volumen con nombre se crea de root;
  comprobado el 2026-11-22). Pasar a un usuario sin privilegios exigiría migrar el volumen
  de producción; los logs no son críticos ni contienen datos de clientes, y se acepta el
  riesgo residual.
- **Prueba automática:** `apps/backend/tests/repo/test_compose_prod.py` falla si
  `compose.prod.yaml` publica un puerto que no sea `127.0.0.1` (salvo los 80/443 de Caddy),
  si `web`, los workers o `db` reciben credenciales equivocadas, si falta el endurecimiento
  o si Caddy se acerca a la base de datos. `make check-prod-config` repite estas
  comprobaciones sobre la configuración renderizada.
- **El host descarta lo que no sea 80/443 hacia puertos publicados.** UFW no filtra lo que
  publica Docker (el DNAT de Docker actúa antes). `autobot-docker-firewall.service` aplica
  en `DOCKER-USER` una regla que solo deja pasar conexiones con DNAT a contenedor cuyo
  puerto original sea 80 o 443. Es defensa en profundidad: hoy ningún otro puerto se
  publica fuera de `127.0.0.1`.

## Alternativas consideradas

- **Dejar un único `web` y confiar en `PanelGateMiddleware`:** la credencial `owner` seguiría
  en el entorno del proceso expuesto; la barrera es de aplicación, no de privilegio.
- **Montar la API del panel dentro de `panel` o como imagen distinta:** duplica imagen y
  dependencias para lo mismo; con la misma imagen y otro entorno el código y las pruebas
  son los mismos.
- **Quitar `owner` de `web` y conectar la API del panel a través de un túnel o un proxy de
  base de datos:** complejidad nueva sin ganar más aislamiento que el de un proceso aparte.
- **Un solo `web` también en local con dos servicios:** ver arriba, costaría más de lo que
  aporta.
- **`victorialogs` con usuario sin privilegios desde ya:** exige migrar el volumen existente
  (acción sobre datos de producción) para proteger datos poco sensibles.
- **Regla de `DOCKER-USER` por interfaz externa:** dependería de detectar el nombre de la
  interfaz; comparar el puerto original de la conexión no necesita saberlo.

## Consecuencias

- Un fallo en una ruta pública ya no entrega `fp_owner` ni `fp_readonly`; para llegar a la
  API del panel hay que comprometer antes `panel`/`web-panel` a través del túnel SSH.
- Un contenedor más (≈ 512 MB de límite de memoria). La VPS de 4 GB lo admite, pero conviene
  vigilar la memoria tras el primer despliegue.
- **El primer despliegue tras este cambio corta el servicio un minuto, aproximadamente:** al
  cambiar `db` de red, `up -d --wait db` la recrea (con su volumen) y el `web` anterior, que
  sigue en la red por defecto, pierde la base de datos hasta que el despliegue levanta el
  `web` nuevo; los canales reintentan los webhooks. Conviene lanzarlo en una hora tranquila.
  `deploy.sh` está preparado para el camino inverso: tras volver a un commit anterior al ADR
  (rollback o abort) usa los servicios que define ese compose (sin `web-panel`) y vuelve a
  alinear `db` con él antes de levantar nada.
- El primer despliegue tras este cambio recrea `web`, `panel` y crea `web-panel`;
  `--remove-orphans` no toca nada más. Si `web-panel` no llega a estar sano, el despliegue
  hace rollback como con cualquier otro servicio.
- Cualquier script o instrucción que ejecute `manage.py` con acceso a `owner` debe usar
  `web-panel` (`manage.sh` ya lo hace).
- La regla de `DOCKER-USER` no se ha podido probar en una VPS real al escribir este ADR
  (solo se ha comprobado la sintaxis y el script con `shellcheck`): se verifica en el primer
  despliegue con `iptables -S DOCKER-USER` y una petición HTTPS a `/health`.

## Cuándo revisarla

- Si la API del panel necesita servirse fuera del túnel SSH (otro acceso, otros usuarios):
  habría que revisar también la red `panel`.
- Si se despliega en varias máquinas, donde las redes de Compose dejan de bastar.
- Si la imagen de VictoriaLogs ofrece usuario sin privilegios con volumen preparado.
- Si Docker cambia el comportamiento de `DOCKER-USER` o se pasa a otro cortafuegos.

Actualiza [ADR-008](ADR-008-panel.md) (el proxy del panel va a `web-panel`, y la API ya no
corre dentro del proceso `web`) y [ADR-005](ADR-005-vps-docker-compose.md) (nuevo contenedor,
redes y endurecimiento).
