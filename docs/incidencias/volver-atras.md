# Volver atrás un despliegue

**Síntoma:** un SHA nuevo rompe `/health` o el flujo tras desplegar. **Diagnóstico:**
consulta `var/.deployed-sha`, logs de `web`/`worker` y el resultado de `deploy.yml`.
El script revierte automáticamente si `/health` no queda sano en 60 s o si el
`worker` se para o se reinicia en sus primeros ~10 s. Si falla antes de cambiar la
imagen (pull, migración o la validación de configuración), mantiene la imagen anterior, devuelve el
repositorio al SHA anterior y avisa con `deploy_aborted`. Comprueba si el aviso a
ops llegó.

**Pasos:** si la reversión automática falló, un operador autorizado ejecuta
`make rollback`: lee del servidor el `previous` del último despliegue correcto
(`var/state/ops/deploys.jsonl`), pide confirmación y lo vuelve a desplegar con
`make deploy SHA=<previous>`. Para un SHA concreto en vez del anterior automático,
`make deploy SHA=<sha-completo>` (comprueba antes que su CI está en verde) y aprueba
el job en el entorno `production`. No reviertas migraciones: deben ser compatibles
hacia atrás. Si la causa fue una configuración de tenant, publica una versión anterior
desde el historial del panel (`POST /tenants/{slug}/rollback`) o con `tenant_config
import`; no hace falta un SHA nuevo. No cambies webhooks de canales reales sin
autorización.

**Verificación:** `var/.deployed-sha` coincide con el SHA sano, `/health` devuelve
200, la cola continúa y una consulta por el bot de demo funciona.

La configuración de negocios no vuelve atrás al desplegar otra imagen: está versionada
en PostgreSQL. Para recuperarla se publica una versión anterior desde el historial del
panel (`POST /tenants/{slug}/rollback`) o se importa un documento exportado con
`tenant_config import <dir> --comment "Recuperación"`, conservando identidad y estado.
