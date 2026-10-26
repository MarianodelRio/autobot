"""Text helpers shared by the packs. Ported from `_norm` and
`_strip_html` (Peluquería, `parser.py`) and `normalizar` (buscaBus, `formato.py`, without
its stop words, which stay in the bus pack)."""

import html
import re
import unicodedata


def fold(text: str) -> str:
    """Lowercase, without accents and stripped; punctuation is kept (`[cfg]`, `10:00`).
    Exactly Peluquería's `_norm`, for parsers that rely on punctuation."""
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn").strip()


def normalize(text: str) -> str:
    """`fold`, plus punctuation turned into spaces and spaces collapsed: the form used to
    compare free text (commands, names). Never shown to the user."""
    return " ".join(re.sub(r"[^a-z0-9]", " ", fold(text)).split())


def strip_html(text: str) -> str:
    """Remove the HTML that Google Calendar may add to descriptions edited by hand:
    block tags become newlines, the other tags are dropped and entities are decoded."""
    text = re.sub(r"<(?:br\s*/?>|/p>|/div>|/li>)", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text)
