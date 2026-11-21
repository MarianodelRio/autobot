"""Operator actions on a tenant that both the panel and the management commands run:
the Telegram webhook of a bot, the owner's invite link and disconnecting the owner.
Each one does the work, audits it under the caller's `actor` and raises `ActionError`
when it cannot be done; how that is shown (an `ApiError` or a `CommandError`) is up
to the caller. Never called inside a transaction (they reach Telegram)."""

from autobot.channels.telegram.registration import WebhookError, register_webhook, remove_webhook
from autobot.ops.audit import record, record_tenant
from autobot.owner.invites import InviteError, InviteLink, create_invite_link
from autobot.owner.links import unlink
from autobot.tenancy.registry import LoadedTenant


class ActionError(Exception):
    """The action could not be done; `str(error)` says why."""


def _audit_webhook(
    actor: str, action: str, summary: str, *, bot: str, tenant: LoadedTenant | None
) -> None:
    if tenant is not None:
        record_tenant(actor, action, tenant, summary)
    else:
        # `demo` and `notify` are platform bots, not tenants: no tenant_id.
        record(actor=actor, action=action, summary=summary, target_type="bot", target_id=bot)


def set_telegram_webhook(
    bot: str | None,
    *,
    actor: str,
    tenant: LoadedTenant | None = None,
    tenant_only: bool = False,
    summary: str = "Webhook de Telegram registrado",
) -> str:
    """Registers the webhook of `bot` (a tenant slug, `notify`, or None for the demo bot)
    and returns its url. `tenant` is the tenant owning the bot, if any; `tenant_only`
    means `bot` is always a tenant's own bot (the panel)."""
    try:
        url = register_webhook(bot, tenant_only=tenant_only)
    except (ValueError, WebhookError) as error:
        raise ActionError(str(error)) from None
    _audit_webhook(actor, "tenant.webhook_register", summary, bot=bot or "demo", tenant=tenant)
    return url


def delete_telegram_webhook(bot: str | None, *, actor: str, tenant: LoadedTenant | None) -> None:
    try:
        remove_webhook(bot)
    except (ValueError, WebhookError) as error:
        raise ActionError(str(error)) from None
    _audit_webhook(
        actor,
        "tenant.webhook_delete",
        "Webhook de Telegram eliminado",
        bot=bot or "demo",
        tenant=tenant,
    )


def create_owner_invite(tenant: LoadedTenant, *, actor: str) -> InviteLink:
    try:
        link = create_invite_link(tenant)
    except InviteError as error:
        raise ActionError(str(error)) from None
    record_tenant(actor, "tenant.owner_invite", tenant, "Enlace de invitación generado")
    return link


def unlink_owner(tenant: LoadedTenant, *, actor: str) -> bool:
    """Disconnects the owner's chat and clears any pending invite; True if a chat was
    connected."""
    had_chat = unlink(tenant.id)
    record_tenant(
        actor,
        "tenant.owner_unlink",
        tenant,
        "Dueño desconectado" if had_chat else "Invitación del dueño cancelada",
    )
    return had_chat
