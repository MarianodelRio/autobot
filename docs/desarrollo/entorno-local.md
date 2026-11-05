# Entorno local

Requisitos: [uv](https://docs.astral.sh/uv/) (instala Python 3.14 por su cuenta).

```bash
cd apps/backend && uv sync && cd -
make dev-bootstrap     # db, roles, migraciones, permisos, demos, web y worker
make check             # ruff, mypy, import-linter y tests contra la BD local
```

`web` escucha en `http://127.0.0.1:8000`. `make up` reconstruye y levanta los servicios
ya preparados; `make down` los para y `make shell` abre Django en `web`.
`make dev-bootstrap` se puede repetir: conserva las versiones existentes y los cambios
de los demos. `make dev-reset` exige escribir `RESET`, borra el volumen local y repite
el bootstrap, incluida la creación de la base de pruebas.

`make dev-activity` crea actividad falsa y realista (mensajes, respuestas, avisos,
alertas abiertas y resueltas, un trabajo fallido y muestras de sistema) para ver el
panel con datos; `--days` y `--reset` se pasan con
`docker compose exec web python manage.py seed_dev_activity --days 7 --reset`. Se
niega fuera de `local`.

La imagen local instala las dependencias de desarrollo (`INSTALL_DEV=true`); la de
producción mantiene `--no-dev`. El worker usa `watchfiles` y reinicia su proceso al
cambiar Python en `apps/backend/src/`, respetando el cierre del worker antes de
sustituirlo. En local, `.env` es opcional. Si se necesita Calendar,
`GOOGLE_SERVICE_ACCOUNT_FILE` apunta al fichero local de la cuenta de servicio (ruta
relativa a `deploy/compose/`, por convención `../../var/google_sa.json`); vacío monta
`/dev/null` y no crea ninguna credencial. Los secretos de los canales se importan
cifrados a la BD.

Para importar un negocio: `make tenant-import DIR=<directorio> SECRETS=<yaml-privado>`
(`SECRETS` es opcional). `HOST` usa por defecto el alias SSH `autobot` de
`~/.ssh/config`; se puede cambiar con `HOST=<servidor>`.

`make status` muestra los servicios locales y `make logs SERVICE=worker` sigue sus logs
(sin `SERVICE`, los de todos los servicios). `make tenant-health SLUG=<slug>` comprueba
el negocio desde `web`; este último necesita las credenciales de los servicios que usa.

## QR público de un negocio

Para generar el QR sin contenedores, credenciales ni acceso de red:

```bash
uv run --project apps/backend python apps/backend/manage.py tenant_config export <slug> var/datos/<slug>
make qr FILE=var/datos/<slug>/document.yaml
make qr FILE=var/datos/<slug>/document.yaml ARGS="--output /ruta/qr.svg"
# Equivalente: PYTHONPATH=apps/backend/src uv run python -m tools.ops.qr var/datos/<slug>/document.yaml
```

El canal debe declarar `display_phone` internacional (WhatsApp) o `bot_username`
(Telegram). El QR apunta al canal del negocio y se guarda como SVG con fondo blanco,
apto para imprimir. Los archivos de `var/qr/` son generados y no se suben a git.

## Registro y configuración

El registro de web y worker se carga desde las versiones de PostgreSQL. Consulta
`config_revision` como máximo cada dos segundos y recarga cuando cambia; cada petición
y trabajo conserva el mismo registro durante su ejecución. Un fallo al comprobar la
revisión mantiene el último registro válido; `/health` responde 503 si no puede hacer
la primera carga.

La configuración y los secretos de negocio no se copian del repositorio ni se montan
desde un YAML. `tenant_config import/export/validate`, `tenant_dataset`, `seed_demos`
y `tenant_status` gestionan las versiones en PostgreSQL; ver
[comandos](../referencia/comandos.md). La publicación no requiere commits ni reinicios.

Las acciones de producción se ejecutan con `make prod-manage HOST=<servidor> CMD="..."`;
`TTY=1` permite confirmaciones interactivas. `make tenant-push HOST=<servidor> SLUG=<slug>`
transfiere el documento y los datasets de la BD local por SSH; `SECRETS=<yaml-privado>`
añade solo los secretos del slug seleccionado al tar temporal. Los exports ordinarios
no incluyen secretos. Nunca se versionan `var/tenants/` ni `var/datos/`.
