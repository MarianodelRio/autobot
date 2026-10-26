# 7. Volver atrás un despliegue

**Síntoma:** un SHA nuevo rompe `/health` o el flujo tras desplegar. **Diagnóstico:**
consulta `.deployed-sha`, logs de `web`/`worker` y el resultado de `deploy.yml`.
El script revierte automáticamente si `/health` no queda sano en 60 s o si el
`worker` se para o se reinicia en sus primeros ~10 s. Si falla antes de cambiar la
imagen (pull, migración o `sync_tenants`), mantiene la imagen anterior, devuelve el
repositorio al SHA anterior y avisa con `deploy_aborted`. Comprueba si el aviso a
ops llegó.

**Pasos:** si la reversión automática falló, un operador autorizado despliega el
SHA anterior publicado mediante `make deploy SHA=<sha-completo>` y aprueba el job
en el entorno `production`. No reviertas migraciones: deben ser compatibles hacia
atrás. Si la causa fue una configuración de tenant, corrige YAML y crea un SHA nuevo.
No cambies webhooks de canales reales sin autorización.

**Verificación:** `.deployed-sha` coincide con el SHA sano, `/health` devuelve 200,
la cola continúa y una consulta del bot de pruebas funciona.
