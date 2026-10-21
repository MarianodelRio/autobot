# Fixtures de Telegram

Updates y respuestas de la Bot API de Telegram para los tests de contrato del adaptador (`tests/contract/test_telegram.py`).

**Procedencia:** siguen la forma de los objetos documentados en la [Bot API](https://core.telegram.org/bots/api) (`Update`, `Message`, `CallbackQuery` y las respuestas de error con `error_code`, `description` y `parameters.retry_after`). Los ids, nombres y textos son ficticios.

Cuando exista el bot de desarrollo (M-3.1), se pueden sustituir por updates grabados con `telegram_poll`, anonimizando ids y nombres.
