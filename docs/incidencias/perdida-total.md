# Pérdida total de la máquina

**Síntoma:** la VPS no responde, el proveedor confirma su pérdida o hay que
recuperarse en otra máquina sin acceso a la original. **Diagnóstico:** confirma que
no hay forma de recuperar la máquina original (reinicio, consola del proveedor) antes
de tratar esto como pérdida total; si solo necesitas ampliar recursos en el mismo
proveedor, no sigas este procedimiento; para un traslado planificado, ver `docs/procedimientos/servidor.md` (sección «Traslado a otro servidor») y ADR-012.

**Por qué no basta con restaurar y arrancar:** el snapshot más reciente tiene, como
mucho, una hora de antigüedad (el backup es horario), pero no cero. Todo lo ocurrido entre ese snapshot
y la pérdida de la máquina puede estar duplicado o ser irrecuperable:

- Un mensaje de WhatsApp o Telegram recibido después del snapshot y ya respondido no
  queda registrado; al volver a entrar (reintento del canal o el propio cliente)
  puede generar una respuesta duplicada o confundida con el estado anterior.
- Una cita de `salon` creada o movida en Google Calendar después del snapshot **no
  tiene fila en la base de datos restaurada**: el bot no sabe que existe y puede
  ofrecer ese hueco como libre a otro cliente.
- Un aviso al dueño o una alerta ya resuelta antes de la pérdida puede reabrirse sin
  que haya nada nuevo que resolver.

**Pasos:**

1. Sigue [restauración y simulacro trimestral](../procedimientos/restaurar.md) en la
   máquina nueva: `install-vm.sh --restore-target` (deja el marcador `bootstrap-complete`), `restore.sh --confirm-empty-target` (no arranca los
   workers por defecto) y verificación de `/health` y conteos por tenant.
2. **Antes de arrancar los workers** (`deploy/scripts/compose.sh up -d
   worker-inbound worker-outbound`, ya que `restore.sh` se niega a repetirse sobre
   un `var/.deployed-sha` ya restaurado), revisa a mano, por negocio activo:
   - El calendario de Google de cada tenant de `salon` contra las citas que la BD
     restaurada conoce, en la ventana entre el snapshot y la pérdida. Una cita en
     Google sin fila correspondiente necesita que alguien la dé de alta a mano
     (`docs/referencia/comandos.md`) o la elimine si ya no es válida, antes de que
     el bot vuelva a ofrecer ese hueco.
   - Alertas (`ops_alert`) que el panel muestre como abiertas pero que ya se
     resolvieron antes de la pérdida: resuélvelas a mano si corresponde.
   - Si el proveedor de canal (Meta, Telegram) conserva mensajes sin confirmar
     entrega de antes de la pérdida, espera su reintento natural en vez de
     reenviar nada a mano: un reenvío manual sin saber qué se procesó ya puede
     duplicar una respuesta (regla general: ningún efecto externo se reintenta a
     ciegas si es ambiguo, `CLAUDE.md`).
3. Arranca los workers. A partir de aquí, el bot vuelve a responder y el barrido de
   calendario (`calendar_sweep`) vuelve a correr con lo que la revisión del paso 2
   dejó corregido.
4. Si cambia la IP o el dominio, sigue también los pasos de DNS/certificados del
   traslado planificado (`docs/procedimientos/servidor.md`) en lo que aplique.

**Verificación:** igual que un simulacro de restauración
(`docs/procedimientos/restaurar.md`): `/health` 200, conteos por tenant y un flujo
por el bot de demo, más la revisión manual del paso 2 anotada (qué se encontró y qué
se corrigió) antes de dar el incidente por cerrado.
