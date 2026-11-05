"""Encryption, key rotation, and errors never disclose channel credentials."""

import json

import pytest
from cryptography.fernet import Fernet
from pytest_django import Settings

from autobot.ops.logging import redact
from autobot.tenancy.crypto import SecretsUnreadable, decrypt, encrypt


def test_roundtrip_and_compact_sorted_json(settings: Settings) -> None:
    key = Fernet.generate_key().decode()
    settings.SECRETS_ENCRYPTION_KEYS = [key]
    data = {"z": "contraseña á", "a": "test-token"}
    token = encrypt(data)
    assert decrypt(token) == data
    assert (
        Fernet(key).decrypt(token)
        == json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    )
    assert b"test-token" not in token


def test_rotation(settings: Settings) -> None:
    a, b = (Fernet.generate_key().decode() for _ in range(2))
    settings.SECRETS_ENCRYPTION_KEYS = [a]
    old = encrypt({"bot_token": "private"})
    settings.SECRETS_ENCRYPTION_KEYS = [b, a]
    new = encrypt(decrypt(old))
    settings.SECRETS_ENCRYPTION_KEYS = [b]
    assert decrypt(new) == {"bot_token": "private"}
    with pytest.raises(SecretsUnreadable):
        decrypt(old)


def test_unreadable_token_has_fixed_message(settings: Settings) -> None:
    token = encrypt({"bot_token": "private"})
    corrupted = token[:-10] + b"AAAAAAAAAA"
    for bad in (
        corrupted,
        b"private-corrupt-token",
        Fernet(settings.SECRETS_ENCRYPTION_KEYS[0]).encrypt(b"[]"),
    ):
        with pytest.raises(SecretsUnreadable) as error:
            decrypt(bad)
        assert str(error.value) == "Channel secrets cannot be read"
        assert bad.decode() not in str(error.value)
        assert error.value.__suppress_context__


def test_all_encryption_keys_redacted(settings: Settings) -> None:
    keys = [Fernet.generate_key().decode() for _ in range(2)]
    settings.SECRETS_ENCRYPTION_KEYS = keys
    assert redact(" ".join(keys)) == "[REDACTED] [REDACTED]"
