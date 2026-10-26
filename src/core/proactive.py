"""Proactive messages: notices the bot starts itself."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TemplateSpec:
    """Declared by a pack. `name` and `language` are used by WhatsApp; `text` (with
    `{1}`, `{2}`…) and the `buttons` titles by Telegram. `text` must match the template
    approved in Meta."""

    name: str
    language: str
    text: str
    buttons: list[str]


@dataclass(frozen=True)
class ProactiveMessage:
    template: TemplateSpec
    params: list[str]
    button_payloads: list[str]
