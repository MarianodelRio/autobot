# 2. Un negocio o canal no responde

**Síntoma:** otros negocios funcionan, pero uno no responde en su canal `main`.
**Diagnóstico:** ejecuta `docker compose -p autobot -f compose.prod.yaml exec web
python manage.py tenant_health <slug>` desde `/srv/autobot` y revisa si figura
`onboarding`, `paused`, `offboarded` o `degraded`. Compara `public_id`, ids de canal y
secretos con la configuración aprobada; no muestres valores de secretos en pantalla
compartida ni tickets. En `onboarding`, `main` solo acepta testers declarados.

**Pasos:** comprueba el webhook y los permisos del canal con la persona responsable.
Corrige YAML o fichero de secretos mediante el procedimiento aprobado, valida
`make check` y despliega un SHA nuevo. Un tenant degradado no debe arrastrar a otros.
Cambiar el webhook o activar `main` necesita aprobación humana. Si en vez de un negocio
real falla el bot de demo, revisa sus variables `DEMO_TELEGRAM_*`/`DEMO_WHATSAPP_*`.

**Verificación:** `tenant_health` no reporta problemas, un tester autorizado recibe
una respuesta y otro negocio sigue funcionando.
