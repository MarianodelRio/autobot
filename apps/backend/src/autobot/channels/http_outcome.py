"""What the Meta and Telegram adapters share when reading an HTTP answer. Their
`classify` differ (a 5xx is `RetryLater` for Meta, `Ambiguous` for Telegram) and stay
in each adapter."""

import math
from typing import Any

import httpx

MAX_RETRY_AFTER_S = 3600.0


def clamp_retry_after(seconds: float) -> float | None:
    """A provider's wait, or None if it is not a usable one (NaN, infinite, negative);
    never more than `MAX_RETRY_AFTER_S`."""
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return min(seconds, MAX_RETRY_AFTER_S)


def safe_json_dict(response: httpx.Response) -> dict[str, Any]:
    """The answer's JSON object, or `{}` if its body is not one."""
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}
