# ADR-003 — Packs con máquina de estados propia

**Estado:** aceptada

## Contexto

Hay dos negocios reales con flujos muy distintos: reservas sobre Google Calendar (peluquería) y consulta de horarios con datos estructurados (autobuses). Las dos conversaciones se resuelven bien con una máquina de estados explícita. Cada negocio tiene un canal de producción (WhatsApp o Telegram) y todos se prueban desde un bot de Telegram compartido; las conversaciones deben funcionar igual en todos ellos.

## Decisión

- Cada tipo de negocio es un **pack** en `packs/<nombre>/`: esquema de config (pydantic), **su propia máquina de estados** (`handle_message(ctx, msg) -> PackResult`), sus textos, sus periódicas y sus tests.
- El pack recibe un `PackContext` (tenant, config, datos cargados, contacto, estado, reloj, puertos externos como `calendar`, candados, claves idempotentes) y devuelve respuestas, nuevo estado y acciones. **Nunca toca la BD ni las APIs directamente.**
- La plataforma resuelve lo común: caducidad del estado, versión del estado, comandos globales (`menu`, `baja`), mensajes no soportados, recuperación ante errores, plan de envío y límites comunes de mensajes.
- Los packs no conocen el canal: construyen respuestas comunes (texto, botones, lista) dentro de los límites más estrictos de WhatsApp y Telegram, y cada adaptador de canal las traduce.
- **Utilidades comunes, no framework**: `core/ui`, `core/text`, `core/dates`, `core/whatsapp_limits`. Solo entra en `core` lo que usan los dos packs.
- Registro explícito de packs (`packs/registry.py`), sin descubrimiento automático.

## Alternativas consideradas

- **Motor genérico de recorridos y bloques**: mucha maquinaria para dos flujos que no comparten pasos; obligaría a reescribir dos bots que ya funcionan.
- **Recetas YAML / DSL por tenant**: tienden a convertirse en un lenguaje de programación sin herramientas.

## Consecuencias

- La lógica de cada negocio queda separada del pegamento con la plataforma.
- Los packs se prueban sin BD con un arnés de conversación en pytest.
- Variaciones entre negocios del mismo pack se resuelven con opciones de config.

## Cuándo revisarla

- Un tercer pack repite pasos de otro (elegir día, elegir de una lista paginada, confirmar): ese paso se extrae a `core` como función reutilizable.
- La misma variación aparece en tres negocios y la config no la cubre.
