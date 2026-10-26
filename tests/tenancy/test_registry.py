"""Tenant registry."""

import dataclasses
import logging
from pathlib import Path
from typing import Any

import pytest
import yaml

from flowpilot.tenancy.registry import Registry, load_registry
from tests.tenancy.helpers import (
    PACKS,
    TG_SECRETS,
    WA_SECRETS,
    phone_number_id,
    tenant_yaml,
    write_secrets,
    write_tenants,
)
from tests.toy_pack import pack as toy


def load(
    tmp_path: Path,
    *docs: dict[str, Any],
    secrets: dict[str, Any] | None = None,
    raw: dict[str, str] | None = None,
    packs: dict[str, Any] = PACKS,
) -> Registry:
    tenants = write_tenants(tmp_path, *docs, raw=raw)
    secrets_file = write_secrets(tmp_path, secrets) if secrets is not None else None
    return load_registry(tenants, secrets_file, packs)


# ── A healthy tenant ──────────────────────────────────────────────────────


def test_valid_tenant_is_loaded_and_indexed(tmp_path: Path) -> None:
    doc = tenant_yaml("dm-barber")
    registry = load(tmp_path, doc, secrets={"dm-barber": WA_SECRETS})
    (t,) = registry.tenants
    assert registry.problems == {}
    assert not t.is_degraded and t.main_enabled
    assert t.info.slug == "dm-barber" and t.info.timezone.key == "Europe/Madrid"
    assert registry.by_slug["dm-barber"] is t
    assert registry.tenant(t.id) is t
    assert registry.by_public_id[("whatsapp", doc["channel"]["public_id"])] is t
    assert registry.by_phone_number_id[phone_number_id("dm-barber")] is t
    assert t.config == toy.ToyConfig()


def test_pack_config_is_validated_with_its_schema(tmp_path: Path) -> None:
    registry = load(tmp_path, tenant_yaml("a", config={"greeting": "Buenas"}))
    assert registry.tenants[0].config == toy.ToyConfig(greeting="Buenas")


def test_load_data_receives_the_tenant_directory(tmp_path: Path) -> None:
    seen: list[Any] = []

    def load_data(info: Any, config: Any, path: Path) -> object:
        seen.append((info.slug, path.name))
        return {"rows": 3}

    packs = {"toy": dataclasses.replace(toy.pack, load_data=load_data)}
    registry = load(tmp_path, tenant_yaml("bus-a"), packs=packs)
    assert seen == [("bus-a", "bus-a")]
    assert registry.tenants[0].data == {"rows": 3}


def test_telegram_tenant(tmp_path: Path) -> None:
    doc = tenant_yaml(
        "tg",
        channel={"type": "telegram", "public_id": "tgpublic0001", "bot_username": "tg_bot"},
        testers={"telegram": [5], "main": [123456789]},
    )
    registry = load(tmp_path, doc, secrets={"tg": TG_SECRETS})
    (t,) = registry.tenants
    assert t.main_enabled
    assert t.file.testers.main == ["123456789"]
    assert registry.by_public_id[("telegram", "tgpublic0001")] is t


# ── Main channel disabled: missing secrets or ids ────────────────────────


def test_missing_secrets_disable_only_the_main_channel(tmp_path: Path) -> None:
    registry = load(tmp_path, tenant_yaml("a"), tenant_yaml("b"), secrets={"a": WA_SECRETS})
    a, b = registry.tenants
    assert a.main_enabled
    assert not b.main_enabled and not b.is_degraded
    assert b.main_disabled == ["no secrets in secrets.yaml"]


def test_no_secrets_file_disables_every_main_channel(tmp_path: Path) -> None:
    registry = load(tmp_path, tenant_yaml("a"))
    assert not registry.tenants[0].main_enabled
    assert registry.problems == {}  # CI has no secrets: that is not a tenant problem


@pytest.mark.parametrize(
    ("secrets", "problem"),
    [
        ({"app_secret": "x", "access_token": "y"}, "verify_token"),
        ({**WA_SECRETS, "extra": "z"}, "extra"),
    ],
)
def test_incomplete_secrets_disable_the_main_channel(
    tmp_path: Path, secrets: dict[str, str], problem: str
) -> None:
    (t,) = load(tmp_path, tenant_yaml("a"), secrets={"a": secrets}).tenants
    assert not t.main_enabled
    assert problem in t.main_disabled[0]


def test_telegram_webhook_secret_needs_32_characters(tmp_path: Path) -> None:
    doc = tenant_yaml(
        "tg",
        channel={"type": "telegram", "public_id": "tgpublic0001", "bot_username": "tenant_bot"},
        testers={},
    )
    secrets = {"tg": {**TG_SECRETS, "webhook_secret": "short"}}
    assert not load(tmp_path, doc, secrets=secrets).tenants[0].main_enabled


def test_missing_meta_ids_disable_the_main_channel(tmp_path: Path) -> None:
    doc = tenant_yaml("a", channel={"type": "whatsapp", "public_id": "apublic00001"})
    (t,) = load(tmp_path, doc, secrets={"a": WA_SECRETS}).tenants
    assert t.main_disabled == ["whatsapp channel ids are missing"]
    assert not t.is_degraded


def test_secret_values_never_reach_logs_or_messages(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    secrets = {
        "a": {"app_secret": "SUPER-SECRET-VALUE"},  # incomplete: reported
        "b": {**WA_SECRETS, "verify_token": ["LEAKED-IN-A-LIST"]},  # wrong type: reported
        "c": WA_SECRETS,  # valid: loaded
    }
    with caplog.at_level(logging.WARNING):
        registry = load(
            tmp_path, tenant_yaml("a"), tenant_yaml("b"), tenant_yaml("c"), secrets=secrets
        )
    text = caplog.text + repr(registry.tenants) + str(registry.tenants)
    for value in ("SUPER-SECRET-VALUE", "LEAKED-IN-A-LIST", *WA_SECRETS.values()):
        assert value not in text


# ── Degraded: one broken tenant does not affect the others ───────────────


def test_unknown_pack_degrades_the_tenant(tmp_path: Path) -> None:
    registry = load(tmp_path, tenant_yaml("a", pack="nope"), tenant_yaml("b"))
    a, b = registry.tenants
    assert a.degraded == ["unknown pack 'nope'"]
    assert not b.is_degraded
    assert registry.problems == {"a": ["unknown pack 'nope'"]}


def test_invalid_config_degrades_only_that_tenant(tmp_path: Path) -> None:
    registry = load(tmp_path, tenant_yaml("a", config={"greeting": 3}), tenant_yaml("b"))
    a, b = registry.tenants
    assert a.is_degraded and a.degraded[0].startswith("config: greeting")
    assert not b.is_degraded
    assert registry.by_public_id[("whatsapp", a.file.channel.public_id)] is a  # still routed


def test_failing_load_data_degrades_only_that_tenant(tmp_path: Path) -> None:
    def broken(info: Any, config: Any, path: Path) -> object:
        raise ValueError("bad dataset line 3")

    packs = {"toy": dataclasses.replace(toy.pack, load_data=broken)}
    registry = load(tmp_path, tenant_yaml("a"), packs=packs)
    assert registry.tenants[0].degraded == ["load_data failed: ValueError: bad dataset line 3"]


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"timezone": "Mars/Base"}, "timezone"),
        ({"status": "closed"}, "status"),
        ({"id": "00000000-0000-4000-8000-000000000000"}, "UUIDv7"),
        ({"surprise": 1}, "surprise"),
        ({"channel": {"type": "sms", "public_id": "abcdefgh"}}, "channel"),
        ({"channel": {"type": "whatsapp", "public_id": "UPPER-case"}}, "public_id"),
        (
            {"channel": {"type": "telegram", "public_id": "abcdefgh", "phone_number_id": "1"}},
            "phone_number_id",
        ),
        ({"testers": {"main": ["not-a-phone"]}}, "testers.main"),
        ({"testers": {"telegram": ["abc"]}}, "testers.telegram"),
    ],
)
def test_invalid_common_part_is_reported_and_others_load(
    tmp_path: Path, change: dict[str, Any], problem: str
) -> None:
    registry = load(tmp_path, tenant_yaml("bad", **change), tenant_yaml("good"))
    assert [t.slug for t in registry.tenants] == ["good"]
    assert problem in " ".join(registry.errors["bad"]) or problem in str(registry.errors)


def test_telegram_main_testers_must_be_user_ids(tmp_path: Path) -> None:
    doc = tenant_yaml(
        "tg",
        channel={"type": "telegram", "public_id": "tgpublic0001"},
        testers={"main": ["34600000001", "@someone"]},
    )
    assert "Telegram user id" in str(load(tmp_path, doc).errors["tg"])


def test_whatsapp_main_testers_accept_phones_and_bsuids(tmp_path: Path) -> None:
    doc = tenant_yaml("a", testers={"main": ["34600000001", "ES.AbC123"]})
    assert load(tmp_path, doc).problems == {}


def test_slug_must_match_its_directory(tmp_path: Path) -> None:
    doc = tenant_yaml("a")
    raw = {"other": yaml.safe_dump(doc)}
    registry = load(tmp_path, raw=raw)
    assert "does not match" in registry.errors["other"][0]


def test_unreadable_yaml_is_reported(tmp_path: Path) -> None:
    registry = load(tmp_path, tenant_yaml("good"), raw={"broken": "id: [unclosed"})
    assert registry.errors == {"broken": ["tenant.yaml cannot be read (ParserError)"]}
    assert [t.slug for t in registry.tenants] == ["good"]


def test_invalid_secrets_file_is_reported(tmp_path: Path) -> None:
    tenants = write_tenants(tmp_path, tenant_yaml("a"))
    (tmp_path / "secrets.yaml").write_text("a: [unclosed")
    registry = load_registry(tenants, tmp_path / "secrets.yaml", PACKS)
    assert registry.secrets_error == "cannot be read (ParserError)"
    assert registry.problems == {"secrets.yaml": ["cannot be read (ParserError)"]}
    assert not registry.tenants[0].main_enabled


# ── Repository-wide uniqueness ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", "01929a4e-6b1c-7d3e-9f00-1a2b3c4d5e6f"),
        ("public_id", "samepublic01"),
        ("phone_number_id", "1122334455"),
    ],
)
def test_repeated_keys_degrade_every_tenant_involved(
    tmp_path: Path, field: str, value: str
) -> None:
    def doc(slug: str) -> dict[str, Any]:
        d = tenant_yaml(slug)
        if field == "id":
            d["id"] = value
        else:
            d["channel"][field] = value
        return d

    registry = load(tmp_path, doc("a"), doc("b"), tenant_yaml("c"))
    a, b, c = registry.tenants
    assert a.degraded == [f"{field} repeated"] and b.degraded == [f"{field} repeated"]
    assert not c.is_degraded
    assert [t.slug for t in registry.by_public_id.values()] == ["c"]  # never routed
    assert a.ambiguous and b.ambiguous and not c.ambiguous


# ── Queries ──────────────────────────────────────────────────────────────


def test_visible_to_testers_and_operators(tmp_path: Path) -> None:
    registry = load(
        tmp_path,
        tenant_yaml("a", testers={"telegram": [111, 222]}),
        tenant_yaml("b", testers={"telegram": [222]}),
    )
    assert [t.slug for t in registry.visible_to(111, operators=[999])] == ["a"]
    assert [t.slug for t in registry.visible_to(222, operators=[999])] == ["a", "b"]
    assert registry.visible_to(333, operators=[999]) == []
    assert [t.slug for t in registry.visible_to(999, operators=[999])] == ["a", "b"]


def test_serving_excludes_degraded_and_offboarded(tmp_path: Path) -> None:
    registry = load(
        tmp_path,
        tenant_yaml("a"),
        tenant_yaml("b", status="offboarded"),
        tenant_yaml("c", pack="nope"),
        tenant_yaml("d", status="onboarding"),
    )
    assert [t.slug for t in registry.serving("toy")] == ["a", "d"]


def test_a_tenant_file_that_is_not_utf8_only_affects_itself(tmp_path: Path) -> None:
    tenants = write_tenants(tmp_path, tenant_yaml("good"))
    (tenants / "latin1").mkdir()
    (tenants / "latin1" / "tenant.yaml").write_bytes("name: Peluquería".encode("latin-1"))
    registry = load_registry(tenants, None, PACKS)
    assert registry.errors == {"latin1": ["tenant.yaml cannot be read (UnicodeDecodeError)"]}
    assert [t.slug for t in registry.tenants] == ["good"]


def test_an_unreadable_secrets_file_does_not_stop_the_tenants(tmp_path: Path) -> None:
    tenants = write_tenants(tmp_path, tenant_yaml("a"))
    secrets = write_secrets(tmp_path, {"a": WA_SECRETS})
    secrets.chmod(0)
    try:
        registry = load_registry(tenants, secrets, PACKS)
    finally:
        secrets.chmod(0o600)
    assert registry.secrets_error == "cannot be read (PermissionError)"
    assert [t.slug for t in registry.tenants] == ["a"]
    assert not registry.tenants[0].main_enabled


def test_a_directory_without_tenant_yaml_is_reported(tmp_path: Path) -> None:
    tenants = write_tenants(tmp_path, tenant_yaml("a"))
    (tenants / "typo").mkdir()
    (tenants / "typo" / "tenant.yml").write_text("id: x")
    assert load_registry(tenants, None, PACKS).errors == {"typo": ["no tenant.yaml"]}


def test_a_missing_tenants_directory_gives_an_empty_registry(tmp_path: Path) -> None:
    registry = load_registry(tmp_path / "nowhere", None, PACKS)
    assert registry.tenants == [] and registry.problems == {}


def test_secrets_for_unknown_tenants_are_warned_by_name_only(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        load(tmp_path, tenant_yaml("a"), secrets={"a": WA_SECRETS, "typo-slug": WA_SECRETS})
    assert "unknown tenants: typo-slug" in caplog.text
    assert WA_SECRETS["access_token"] not in caplog.text


@pytest.mark.parametrize(
    "channel",
    [
        {"type": "whatsapp", "public_id": "apublic00001", "phone_number_id": " "},
        {"type": "telegram", "public_id": "apublic00001", "bot_username": "@x"},
    ],
)
def test_channel_ids_have_a_format(tmp_path: Path, channel: dict[str, str]) -> None:
    assert "channel" in str(load(tmp_path, tenant_yaml("a", channel=channel)).errors["a"])


@pytest.mark.parametrize("text", ["1: {}", "true: {}", "- a\n- b"])
def test_secrets_file_must_map_slugs(tmp_path: Path, text: str) -> None:
    tenants = write_tenants(tmp_path, tenant_yaml("a"))
    (tmp_path / "secrets.yaml").write_text(text)
    registry = load_registry(tenants, tmp_path / "secrets.yaml", PACKS)
    assert registry.secrets_error == "must map each tenant slug to its secrets"
    assert [t.slug for t in registry.tenants] == ["a"]
