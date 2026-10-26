# 2. Un negocio o canal no responde

**Síntoma:** otros negocios funcionan, pero uno no responde en `main` o `test`.
**Diagnóstico:** ejecuta `docker compose -p flowpilot -f compose.prod.yaml exec web
python manage.py tenant_health <slug>` desde `/srv/flowpilot` y revisa si figura
`onboarding`, `paused`, `offboarded` o `degraded`. Compara `public_id`, ids de canal y
secretos con la configuración aprobada; no muestres valores de secretos en pantalla
compartida ni tickets. En `onboarding`, `main` solo acepta testers declarados.

**Pasos:** si falla solo `test`, comprueba el bot de pruebas y los permisos del tester;
si falla solo `main`, comprueba el webhook y los permisos del canal con la persona
responsable. Corrige YAML o fichero de secretos mediante el procedimiento aprobado,
valida `make check` y despliega un SHA nuevo. Un tenant degradado no debe arrastrar a
otros. Cambiar el webhook o activar `main` necesita aprobación humana.

**Verificación:** `tenant_health` no reporta problemas, un tester autorizado recibe
una respuesta y otro negocio sigue funcionando.
