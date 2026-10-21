# Fixtures de WhatsApp

Cuerpos de webhook de la WhatsApp Cloud API para los tests de contrato del adaptador (`tests/contract/test_whatsapp.py`).

**Procedencia:** siguen la forma de los ejemplos de la documentación oficial de Meta (mensajes de texto, `interactive`, botón de plantilla, BSUID con `from_user_id` y `contacts[].user_id`, estados con `pricing`, `biz_opaque_callback_data` y `errors`). Todavía no hay un número propio del que grabarlos. Los ids, teléfonos y nombres son ficticios.

Cuando haya un número de pruebas (M-4.1), se sustituyen por cuerpos grabados de verdad, anonimizando teléfonos, BSUID y nombres.
