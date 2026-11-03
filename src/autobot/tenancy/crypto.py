"""Encrypt channel secrets with the first key; decrypt with every configured key."""

import json
from collections.abc import Mapping
from typing import cast

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings


class SecretsUnreadable(Exception):
    def __init__(self) -> None:
        super().__init__("Channel secrets cannot be read")


def _cipher() -> MultiFernet:
    return MultiFernet([Fernet(key) for key in settings.SECRETS_ENCRYPTION_KEYS])


def encrypt(data: Mapping[str, str]) -> bytes:
    return _cipher().encrypt(json.dumps(dict(data), sort_keys=True, separators=(",", ":")).encode())


def decrypt(token: bytes) -> dict[str, str]:
    try:
        data = json.loads(_cipher().decrypt(token))
        if not isinstance(data, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in data.items()
        ):
            raise SecretsUnreadable() from None
        return cast(dict[str, str], data)
    except InvalidToken, ValueError, TypeError:
        raise SecretsUnreadable() from None
