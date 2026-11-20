"""Cleaning of what a provider sends, before it is stored as `jsonb`.

PostgreSQL's `jsonb` cannot hold the character NUL (`\\u0000`) nor a lone UTF-16
surrogate: saving a payload with one raises `DataError`, and since the provider then
retries the same body forever, one signed message would block that webhook for good.
`clean_payload` removes both from every string (keys included), so the adapters can
store exactly what they parse.
"""

import re
from typing import Any

# NUL, and a lone surrogate (what `json.loads` gives for `"\ud800"` without its pair).
_BAD = re.compile("[\x00\ud800-\udfff]")


def clean_text(text: str) -> str:
    """`text` without NUL; a lone surrogate becomes U+FFFD."""
    if not _BAD.search(text):
        return text
    return _BAD.sub(lambda m: "" if m.group() == "\x00" else "�", text)


def clean_payload[T](value: T) -> T:
    """`value` (parsed JSON) with every string cleaned by `clean_text`. Returns the same
    object when there is nothing to clean."""
    return _clean(value)  # type: ignore[no-any-return]


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, list):
        cleaned = [_clean(v) for v in value]
        return value if all(a is b for a, b in zip(cleaned, value, strict=True)) else cleaned
    if isinstance(value, dict):
        out = {_clean(k): _clean(v) for k, v in value.items()}
        same = len(out) == len(value) and all(
            k1 == k2 and out[k1] is value[k2] for k1, k2 in zip(out, value, strict=True)
        )
        return value if same else out
    return value
