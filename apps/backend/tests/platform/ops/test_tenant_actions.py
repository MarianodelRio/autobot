"""`ops.tenant_actions`, shared by the panel and the commands: what each action audits
and how it fails. The Telegram calls themselves are stubbed."""

from datetime import timedelta
from typing import Any
from unittest.mock import patch

import pytest
from django.core.management.base import CommandError
from django.utils import timezone

from autobot.channels.telegram.registration import WebhookError
from autobot.ops import tenant_actions
from autobot.ops.models import AuditEvent
from autobot.owner.invites import InviteError, InviteLink
from autobot.tenancy.registry import LoadedTenant, get_registry
from tests.helpers.integration import tg_tenant

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "owner"])


@pytest.fixture
def tenant(tenants: Any) -> LoadedTenant:
    tenants(tg_tenant("acme"))
    return get_registry().by_slug["acme"]


def events(action: str) -> list[AuditEvent]:
    return list(AuditEvent.objects.using("owner").filter(action=action))


def test_set_webhook_audits_under_the_tenant(tenant: LoadedTenant) -> None:
    with patch.object(tenant_actions, "register_webhook", return_value="https://x/hook") as reg:
        url = tenant_actions.set_telegram_webhook(
            "acme", actor="panel:ana", tenant=tenant, tenant_only=True
        )
    reg.assert_called_once_with("acme", tenant_only=True)
    assert url == "https://x/hook"
    (event,) = events("tenant.webhook_register")
    assert (event.actor, event.tenant_id, event.target_type) == ("panel:ana", tenant.id, "tenant")
    assert event.target_id == str(tenant.id)


@pytest.mark.parametrize(("bot", "name"), [(None, "demo"), ("notify", "notify")])
def test_set_webhook_of_a_platform_bot_has_no_tenant(bot: str | None, name: str) -> None:
    with patch.object(tenant_actions, "register_webhook", return_value="https://x/hook"):
        tenant_actions.set_telegram_webhook(bot, actor="command:x")
    (event,) = events("tenant.webhook_register")
    assert (event.tenant_id, event.target_type, event.target_id) == (None, "bot", name)


@pytest.mark.parametrize("error", [WebhookError("nope"), ValueError("bad bot")])
def test_set_webhook_failure_raises_and_is_not_audited(error: Exception) -> None:
    with (
        patch.object(tenant_actions, "register_webhook", side_effect=error),
        pytest.raises(tenant_actions.ActionError, match=str(error)),
    ):
        tenant_actions.set_telegram_webhook("acme", actor="command:x")
    assert not events("tenant.webhook_register")


def test_delete_webhook_audits_and_reports_failures(tenant: LoadedTenant) -> None:
    with patch.object(tenant_actions, "remove_webhook") as remove:
        tenant_actions.delete_telegram_webhook("acme", actor="command:x", tenant=tenant)
    remove.assert_called_once_with("acme")
    assert len(events("tenant.webhook_delete")) == 1
    with (
        patch.object(tenant_actions, "remove_webhook", side_effect=WebhookError("refused")),
        pytest.raises(tenant_actions.ActionError, match="refused"),
    ):
        tenant_actions.delete_telegram_webhook("acme", actor="command:x", tenant=tenant)
    assert len(events("tenant.webhook_delete")) == 1


def test_owner_invite_returns_the_link_and_audits_without_the_code(tenant: LoadedTenant) -> None:
    link = InviteLink(
        url="https://t.me/bot?start=SECRETCODE",
        expires_at=timezone.now() + timedelta(days=1),
        replaces_chat=False,
    )
    with patch.object(tenant_actions, "create_invite_link", return_value=link):
        assert tenant_actions.create_owner_invite(tenant, actor="panel:ana") is link
    (event,) = events("tenant.owner_invite")
    assert event.tenant_id == tenant.id
    assert "SECRETCODE" not in str(event.__dict__)


def test_owner_invite_failure_is_not_audited(tenant: LoadedTenant) -> None:
    with (
        patch.object(tenant_actions, "create_invite_link", side_effect=InviteError("Falta token")),
        pytest.raises(tenant_actions.ActionError, match="Falta token"),
    ):
        tenant_actions.create_owner_invite(tenant, actor="panel:ana")
    assert not events("tenant.owner_invite")


@pytest.mark.parametrize(
    ("had_chat", "summary"),
    [(True, "Dueño desconectado"), (False, "Invitación del dueño cancelada")],
)
def test_unlink_owner_audits_what_it_did(
    tenant: LoadedTenant, had_chat: bool, summary: str
) -> None:
    with patch.object(tenant_actions, "unlink", return_value=had_chat):
        assert tenant_actions.unlink_owner(tenant, actor="panel:ana") is had_chat
    (event,) = events("tenant.owner_unlink")
    assert event.summary == summary


def test_the_commands_turn_an_action_error_into_a_command_error(tenant: LoadedTenant) -> None:
    from django.core.management import call_command

    with (
        patch.object(tenant_actions, "register_webhook", side_effect=WebhookError("nope")),
        pytest.raises(CommandError, match="nope"),
    ):
        call_command("telegram_set_webhook", "acme")
    with pytest.raises(CommandError, match="Negocio desconocido"):
        call_command("owner_unlink", "ghost")
