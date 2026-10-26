# 10. Actualizar horarios de `bus`

**Síntoma:** la empresa comunica cambios o el bot muestra un horario antiguo.
**Diagnóstico:** identifica línea, temporada, fecha de entrada en vigor y fuente
aprobada; consulta `docs/packs/bus.md` para el formato del dataset.

**Pasos:** edita solo `tenants/<slug>/datasets/timetable/`; ejecuta
`make bus-formatear TENANT=<slug>`, `make bus-validar TENANT=<slug>` y
`make bus-revision TENANT=<slug>`. Entrega el PDF a la empresa y conserva su
confirmación. Después de aprobar los cambios, haz commit y despliega el SHA.
Finalmente ejecuta `make bus-publicar TENANT=<slug>` y publica el tag indicado.
Si entra en vigor más adelante, prepara y revisa el commit, pero aplaza también
el despliegue y el tag hasta ese día: el pack lee el dataset desplegado al instante.

**Verificación:** el validador no da errores, la empresa confirma el PDF, el bot de
pruebas muestra el horario nuevo y el tag `datos/<slug>/fecha` apunta al commit
desplegado. La prueba real con la empresa sigue pendiente.
