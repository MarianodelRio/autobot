# Fixtures del pack `bus`

`horarios_matcher/` contiene diez localidades sin líneas para probar el límite de candidatas y las localidades sin servicio. Su directorio `lineas/` debe existir vacío: `.gitkeep` lo conserva al clonar, porque el validador exige el directorio aunque no haya ficheros YAML.

`horarios_real/` es una copia congelada de los horarios reales de Autocares del 2026-10-08. Los tests (y las pruebas doradas del motor de consulta) se escribieron contra esos datos; congelarlos aquí evita que una actualización de horarios del negocio rompa los tests. El dataset vivo del tenant está en `tenants/autocares-ss/datasets/timetable/` y lo valida la puerta de CI de tenants.
