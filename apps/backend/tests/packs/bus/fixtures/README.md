# Fixtures del pack `bus`

Todas las fixtures de este directorio son inventadas, sin relación con la red de
ningún cliente real.

`horarios_ficticios/` es el dataset principal: una red de autobuses ficticia (comarca
inventada de "Valdehoz") que carga `conversation_harness.py` (`datos_demo()`) para los
tests de conversación e interfaz, y que usan directamente `test_query.py`, `test_loader.py`,
`test_matcher.py`, `test_formato.py`, `test_messages.py` y `test_calendario.py` en vez de
cargar `fixtures/horarios_real/` (que existió hasta 2026-11, con una copia congelada de los
horarios reales de un cliente, y se borró para que el repo no contenga datos de ningún
negocio real). Cubre, entre otros, a demanda, viernes lectivo, la condición
`solo_si_viajeros`, las tres temporadas públicas (invierno/verano/agosto), festivos
locales, ambigüedad de nombre (alias compartido "villagrande"), un nombre de parada con
coma y trayectos no vendibles.

`horarios_matcher/` contiene diez localidades sin líneas para probar el límite de candidatas y las localidades sin servicio. Su directorio `lineas/` debe existir vacío: `.gitkeep` lo conserva al clonar, porque el validador exige el directorio aunque no haya ficheros YAML.

`horarios_motor/`, `horarios_festivo_local/`, `horarios_pendientes/` y `horarios_cicloC/` son mezclas sintéticas pequeñas para casos especiales del motor de consulta y del validador (sin_datos, fusión de líneas, llegada/salida distinta, festivos locales por línea, localidades pendientes P15/P32).
