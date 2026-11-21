# Plantilla de runbook

Formato único de los runbooks de esta carpeta. Léela antes de escribir o cambiar uno: quien está de guardia debe encontrar siempre las mismas secciones en el mismo orden.

!!! warning "Producción"
    Cualquier acción sobre datos de producción (borrar, exportar, reimportar, reenviar mensajes, cambiar configuración o secretos de un negocio real, activar o pausar un canal) requiere aprobación humana explícita. Un runbook describe cómo diagnosticar y arreglar; no sustituye esa aprobación.

## Convenciones

- Cada comando indica **dónde** se ejecuta (portátil o VPS) y **con qué usuario**.
- En la VPS se trabaja en `/srv/autobot` como `deploy`. Nunca `docker compose …` a pelo: falla porque falta `SHA` y `--env-file`. Se usa:
    - `deploy/scripts/compose.sh <args>` para cualquier orden de compose (`ps`, `logs`, `up -d`, `exec -T`).
    - `deploy/scripts/manage.sh <comando>` para `manage.py`. Hace `compose run --rm`: arranca un contenedor `web` nuevo y lo borra, no entra en el que está corriendo.
- Desde el portátil, los equivalentes son `make prod-compose HOST=<host> ARGS="…"` y `make prod-manage HOST=<host> CMD="…"` (añade `TTY=1` si el comando es interactivo).
- No copies payloads, teléfonos, ids de usuario ni secretos a tickets o chats.

## Estructura

````markdown
# Título: el problema, en una frase

## Síntoma
Qué se ve y qué alerta lo dispara (clave de `ops_alert` o aviso externo).

## Diagnóstico
1. Comprobación. Dónde se ejecuta y con qué usuario.

   ```bash
   deploy/scripts/compose.sh ps
   ```

   Qué resultado indica qué.

## Arreglo
1. Paso. Si necesita aprobación humana, se dice aquí.

## Verificación
Cómo se sabe que está resuelto (comando o pantalla y resultado esperado).

## Relacionado
Enlaces a otros runbooks, procedimientos y conceptos.
````

## Reglas

- Una causa por runbook; si hay ramas, se numeran dentro de Diagnóstico y Arreglo.
- Lo que explica cómo funciona algo va en `../arquitectura/`; aquí solo lo necesario para actuar.
- Los nombres de fichero no cambian: el panel enlaza cada alerta a su runbook (ver [índice](README.md)).
