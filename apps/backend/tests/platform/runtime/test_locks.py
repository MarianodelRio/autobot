"""Queue locks are keyed hashes: stable for a given platform key, useless without it."""

import hashlib
import os
import subprocess
import sys
import uuid
from pathlib import Path

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
    code = (
        "import django, uuid; django.setup();"
        "from autobot.runtime.locks import contact_hash;"
        f"print(contact_hash(uuid.UUID('{TENANT}'), 'main', '1'))"
    )
    src = str(Path(__file__).resolve().parents[3] / "src")
    env = {
        **os.environ,
        "DJANGO_SECRET_KEY": "fixed-key-for-the-test",
        "DJANGO_SETTINGS_MODULE": "config.settings_dev",
        "PYTHONPATH": src,
    }
    runs = {
        subprocess.run(
            [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True
        )
        .stdout.strip()
        .splitlines()[-1]
        for _ in range(2)
    }
    assert len(runs) == 1
    with override_settings(SECRET_KEY="fixed-key-for-the-test"):
        assert runs == {contact_hash(TENANT, "main", "1")}
