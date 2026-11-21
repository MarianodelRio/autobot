"""Queue locks are keyed hashes: stable for a given platform key, useless without it."""

import hashlib
import hmac
import uuid

from django.test import override_settings

from autobot.runtime.locks import (
    contact_hash,
    conversation_lock,
    demo_user_lock,
    owner_chat_lock,
)

TENANT = uuid.UUID("01920000-0000-7000-8000-00000000000a")


def test_the_hash_is_keyed_not_a_bare_sha256() -> None:
    plain = hashlib.sha256(f"{TENANT}\x00main\x0034600000001".encode()).hexdigest()[:16]
    assert contact_hash(TENANT, "main", "34600000001") != plain
    with override_settings(SECRET_KEY="another-platform-key"):
        other = contact_hash(TENANT, "main", "34600000001")
    assert other != contact_hash(TENANT, "main", "34600000001")


def test_the_locks_keep_their_shape_and_hide_the_identifier() -> None:
    assert len(conversation_lock(TENANT, "main", "1")) == len("conv:") + 16
    assert demo_user_lock("demo_tg", "1").startswith("demo:")
    assert owner_chat_lock(5).startswith("ownerchat:")
    # Different namespaces never collide for the same raw id.
    assert demo_user_lock("main", "5") != owner_chat_lock(5)


def test_the_hash_is_stable_across_processes() -> None:
    """A golden value: the same key and parts give the same lock in every process (web and
    workers), so a release that changed the derivation would fail here. It is also
    recomputed with the standard library alone, independently of the module."""
    key = "fixed-key-for-the-test"
    with override_settings(SECRET_KEY=key):
        assert contact_hash(TENANT, "main", "1") == "21dfc1fab1da6eec"
    derived = hmac.new(key.encode(), b"autobot.queue-lock.v1", hashlib.sha256).digest()
    message = "\x00".join([str(TENANT), "main", "1"]).encode()
    assert hmac.new(derived, message, hashlib.sha256).hexdigest()[:16] == "21dfc1fab1da6eec"
