# Fixtures del pack `bus`

Portadas de `buscaBus/tests/fixtures/` sin cambios.

`horarios_real/` es una copia congelada de `buscaBus/horarios/` (commit `3125dba`, 2026-10-08). Los tests portados (y las pruebas doradas del motor de consulta, T-4.2) se escribieron contra esos datos; congelarlos aquí evita que una actualización de horarios del negocio rompa los tests. El dataset vivo del tenant está en `tenants/autocares-ss/datasets/timetable/` (T-4.6) y lo valida la puerta de CI de tenants.
