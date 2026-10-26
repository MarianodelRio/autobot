# 5. Envíos `unknown` o `failed`

**Síntoma:** Admin → Estado muestra mensajes sin entrega confirmada. **Diagnóstico:**
busca el mensaje por su identificador interno y revisa estado, canal, intentos y
`unknown_at`. El Admin oculta payload, id del proveedor y último error por
privacidad. `unknown` puede significar que el proveedor aceptó el envío aunque
la conexión se cortase.

**Pasos:** comprueba por el panel del proveedor o con el destinatario si llegó.
Si llegó y lleva más de diez minutos en `unknown`, usa «Marcar enviado». Si no
llegó, lleva más de diez minutos en `unknown` y el payload y canal siguen
disponibles, usa «Reenviar» y confirma la posibilidad de duplicado. Estas
acciones no admiten mensajes `failed`: corrige su causa siguiendo el
procedimiento de canal o proveedor correspondiente. El `failed` permanente
queda registrado; corrige la causa para envíos futuros y comprueba con un
**nuevo envío autorizado** que el canal funciona. No reencoles el anterior,
edites filas SQL ni crees otra clave para el mismo efecto.

**Verificación:** para `unknown`, el mensaje queda en `sent` o tiene una nueva
entrega confirmada y Admin registra la resolución. Para `failed`, el registro
permanece en ese estado, mientras el nuevo envío autorizado confirma que la
causa se corrigió. Revisa que no se crearon duplicados.
