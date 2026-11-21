# Traslado a otro servidor

Cómo mover todo el despliegue a otra VPS con `make server-migrate`: cambiar de proveedor o
ampliar la máquina cuando el proveedor no permite hacerlo sobre la misma (si lo permite,
basta un reinicio y no hace falta nada de esto). Si en cambio se ha perdido la máquina
original, ver [../incidencias/perdida-total.md](../incidencias/perdida-total.md).
Decisión: ADR-012.

!!! warning "Aprobaciones"
    Es un cambio de infraestructura sobre datos de producción: requiere aprobación humana
    explícita, la ejecuta una persona y `server-migrate.sh` pide confirmación antes de cada
    paso destructivo o visible desde fuera. Ningún agente lo ejecuta.

## Objetivo, cuándo y requisitos

- **Objetivo:** que el mismo dominio, la misma base de datos y el mismo repositorio de
  copias pasen a una máquina nueva, con un corte corto y sin perder datos (salvo los logs
  técnicos).
- **Cuándo:** cambio de proveedor o de máquina planificado.
- **Requisitos:**
    - La máquina destino (`TO`) preparada con `sudo deploy/scripts/install-vm.sh
      --restore-target` **dentro de ella** ([servidor.md](servidor.md)): usuarios, Docker,
      timers, SSH endurecido y el marcador `bootstrap-complete`, pero sin `.env` ni
      despliegue. Ese script imprime la clave de CI propia de `TO`.
    - `FROM` y `TO` como alias de `~/.ssh/config` (o IP) accesibles como `deploy@` y
      `admin@` con tu clave de operación.
    - `var/server.env` en el portátil con `PUBLIC_HOST` (plantilla
      `deploy/env/server.env.example`).
    - `gh` autenticado (opcional: sin él, el script pide hacer a mano lo de GitHub).
    - Fuera del backup, en tu gestor de contraseñas: la contraseña de restic, las claves S3
      y las claves SSH.

**Qué viaja en el backup:** base de datos, `.env` (con la clave de cifrado),
`google_sa.json`, `.deployed-sha`, el `Caddyfile`, el estado y los certificados de Caddy
(`var/state/caddy-*`) y `deploys.jsonl`.

## Pasos

Antes de empezar: 24 horas antes, baja el TTL del DNS de `PUBLIC_HOST` a 60-300 s.

Desde el portátil, en la raíz del repo:

```bash
make server-migrate FROM=<origen> TO=<destino>
```

Ejecuta los pasos en orden; cada uno puede repetirse sola con `ONLY=<paso>`.

1. **`rehearse`** (ensayo): en `TO`, restaura el último snapshot solo con la base de datos
   (`AUTOBOT_RESTORE_DB_ONLY=true`), imprime los conteos de contactos por negocio de
   `FROM` y de `TO` para que los compares a mano, y borra el volumen del ensayo
   (`compose.sh down -v`). Se niega si `TO` ya tiene un despliegue o es la misma máquina
   que `FROM`.
2. **`freeze`** (corte en el origen, pide confirmación; el tráfico real se para aquí):
    1. Crea `var/.frozen` en `FROM` (`deploy.sh` y `restore.sh` lo respetan).
    2. Desactiva el workflow `deploy.yml` (`gh workflow disable`).
    3. Para el timer de backup (como `admin`) y los servicios `worker-inbound`,
       `worker-outbound`, `web`, `panel` y `caddy`.
    4. Hace un backup final y guarda el id del snapshot en `var/.server-migrate-snapshot`
       del portátil.
3. **`cutover`**: en `TO`, restaura **ese snapshot concreto** (`AUTOBOT_RESTORE_SNAPSHOT`,
   nunca `latest`), con `DEPLOY_UID`, roles, permisos y certificados nuevos para esa
   máquina; levanta todo menos los workers y comprueba
   `https://<PUBLIC_HOST>/health` con `curl --resolve` contra la propia `TO`. Verifica a
   mano antes de seguir.
4. **`start-destination`**: comprueba que `FROM` no tiene ningún contenedor de aplicación en
   marcha (si no, se niega: evitaría envíos duplicados), pide confirmación y arranca los
   workers de `TO` con `compose.sh up -d worker-inbound worker-outbound`. Después, **cambia
   el DNS a mano** de `PUBLIC_HOST` a `TO`.
5. **`finish`**: pone en GitHub `DEPLOY_HOST`, `DEPLOY_KNOWN_HOSTS` y `DEPLOY_SSH_KEY` (la
   clave de CI de `TO`, que sustituye a la de `FROM`), reactiva `deploy.yml` y arranca el
   timer de backup de `TO`. Sin `gh`, hazlo a mano.
6. Conserva `FROM` parado, con `var/.frozen`, durante 7 días y luego dala de baja.

## Verificación

- Los conteos de `rehearse` coinciden entre `FROM` y `TO`.
- `/health` de `PUBLIC_HOST` devuelve 200 sobre `TO` tras el cambio de DNS y el bot de demo
  responde.
- `make backup-now HOST=<destino>` termina bien y `deploys.jsonl` se conserva.
- Un despliegue de prueba por [despliegue.md](despliegue.md) llega a `TO` (con el workflow
  reactivado).

Corte estimado (sin medir todavía): 15-30 minutos más el TTL del DNS. Con el mismo dominio
no hay que tocar los webhooks.

## Dónde está el código

`deploy/scripts/server-migrate.sh`, `deploy/scripts/restore.sh`,
`deploy/scripts/install-vm.sh` (`--restore-target`), `Makefile` (`server-migrate`).
