"""Phone-number normalisation shared by the platform and the packs."""

import re


def phone_key(value: str | None) -> str:
    """Digits only; a bare 9-digit (Spanish) number gets the 34 prefix, so '600 11 22 33',
    '+34600112233' and '34600112233' compare equal."""
    digits = re.sub(r"\D", "", value or "")
    return "34" + digits if len(digits) == 9 else digits
