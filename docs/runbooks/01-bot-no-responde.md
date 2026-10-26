# 1. El bot no responde a nadie

**Síntoma:** los dos packs dejan de contestar. **Diagnóstico:** consulta `/health`, el
estado de Compose y los últimos logs; anota hora y SHA sin copiar payloads ni ids de
clientes. Un 502 público suele indicar que `web` no está sano; un 503 de `/health`
indica fallo de BD. Si `web` responde pero la cola crece, sigue el runbook 3.

**Pasos:** desde `/srv/flowpilot`, usa `docker compose -p flowpilot -f compose.prod.yaml ps`
y `docker compose -p flowpilot -f compose.prod.yaml logs --tail=100 web worker db`.
Comprueba espacio con `df -h` y estado de la base con
`docker compose -p flowpilot -f compose.prod.yaml exec db pg_isready`.
Si el fallo empezó con un despliegue, sigue el runbook 7. Reinicia solo el servicio
averiado después de identificarlo; si la BD está caída, no fuerces reenvíos.

**Verificación:** `/health` vuelve a 200, el worker completa su latido, una consulta
del bot de pruebas termina y el backlog deja de crecer. Registra causa y duración.
