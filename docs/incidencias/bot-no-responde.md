# El bot no responde a nadie

**Síntoma:** los dos packs dejan de contestar. **Diagnóstico:** consulta `/health`, el
estado de Compose y los últimos logs; anota hora y SHA sin copiar payloads ni ids de
clientes. Un 502 público suele indicar que `web` no está sano; un 503 de `/health`
indica fallo de BD. Si `web` responde pero la cola crece, sigue [cola y latido](cola-y-latido.md).

**Pasos:** desde `/srv/autobot`, usa `docker compose ps`
y `docker compose logs --tail=100 web worker db`.
Comprueba espacio con `df -h` y estado de la base con
`docker compose exec db pg_isready`.
Si el fallo empezó con un despliegue, sigue [volver atrás un despliegue](volver-atras.md). Reinicia solo el servicio
averiado después de identificarlo; si la BD está caída, no fuerces reenvíos.

**Verificación:** `/health` vuelve a 200, el worker completa su latido, una consulta
por el bot de demo termina y el backlog deja de crecer. Registra causa y duración.

**Logs técnicos:** si `docker logs` no alcanza (rotan a los 100 MB), consulta la
pantalla Logs del panel (`make panel-tunnel`); VictoriaLogs no publica ningún puerto.
Su caída no afecta al bot: `web` y `worker` descartan los lotes que no pueden enviar y
sigue respondiendo con normalidad.
