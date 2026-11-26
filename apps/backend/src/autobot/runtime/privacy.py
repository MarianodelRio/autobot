"""Synchronous operator exports and erasure; never pass customer data to jobs."""

import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from uuid import UUID

from django.core.cache import cache
from django.core.management.base import CommandError
from django.db import connections, transaction
from django.db.models import Q, QuerySet

from autobot.ops import state as runtime_state
from autobot.ops.audit import record
from autobot.ops.models import AuditEvent, OpsAlert, PrivacySuppression
from autobot.runtime import suppressions
from autobot.runtime.models import (
    DEMO_CHANNELS,
    Channel,
    Contact,
    Conversation,
    DemoAccessGrant,
    DemoEvent,
    DemoSession,
    InboundEvent,
    MetricEvent,
    Notification,
    OutboundMessage,
    OwnerLink,
)
from autobot.tenancy.models import (
    ConfigRevision,
    Tenant,
    TenantDatasetVersion,
    TenantDocumentVersion,
    TenantSecret,
)

MODELS = (
    Contact,
    Conversation,
    InboundEvent,
    OutboundMessage,
    Notification,
    DemoSession,
    OwnerLink,
)


def tenant_for(slug: str) -> Tenant:
    tenant = Tenant.objects.using("owner").filter(slug=slug).first()
    if tenant is None:
        raise CommandError("Tenant desconocido.")
    return tenant


def contact_for(tenant: Tenant, external_id: str, channel: str | None) -> Contact:
    query = Contact.objects.using("owner").filter(tenant=tenant, external_id=external_id)
    if channel:
        query = query.filter(channel=channel)
    contacts = list(query[:2])
    if not contacts:
        raise CommandError("Contacto desconocido.")
    if len(contacts) > 1:
        raise CommandError("Identificador ambiguo: indique --channel main, demo_tg o demo_wa.")
    return contacts[0]


def _add(identities: set[str], value: object) -> None:
    if isinstance(value, str | int) and not isinstance(value, bool) and str(value):
        identities.add(str(value))


def _telegram_part(part: dict[str, Any], identities: set[str]) -> None:
    """Identity fields of one Telegram update member (`message`, `callback_query`,
    `my_chat_member`, `inline_query`, `message_reaction`, `pre_checkout_query`...):
    the sender (`from`, or `user` in reactions/poll answers/business connections), the
    private chat (its id is the person's), and a shared contact card."""
    for field in ("from", "user"):
        if isinstance(part.get(field), dict):
            _add(identities, part[field].get("id"))
    for holder in (part, part.get("message")):
        chat = holder.get("chat") if isinstance(holder, dict) else None
        if isinstance(chat, dict) and chat.get("type") == "private":
            _add(identities, chat.get("id"))
    card = part.get("contact")
    if isinstance(card, dict):
        _add(identities, card.get("user_id"))
        if isinstance(card.get("phone_number"), str):
            identities.add(card["phone_number"].lstrip("+"))


def _senders(payload: object) -> set[str]:
    """Extract only identity fields of stored Telegram and WhatsApp bodies.

    Telegram: every member of the update that is an object (`message`, `edited_message`,
    `callback_query`, `channel_post`, `my_chat_member`, `chat_member`, `inline_query`,
    `chosen_inline_result`, `pre_checkout_query`, `shipping_query`, `message_reaction`,
    `business_message`...), not a whitelist, so a new update type is covered too.
    WhatsApp: `messages[].from`, `contacts[].wa_id` and `statuses[].recipient_id`
    (plus their BSUID variants). Do not parse arbitrary message text, and do not log
    malformed/expired payloads.
    """
    if not isinstance(payload, dict):
        return set()
    identities: set[str] = set()
    for key, part in payload.items():
        if key != "entry" and isinstance(part, dict):
            _telegram_part(part, identities)
    entries = payload.get("entry")
    for entry in entries if isinstance(entries, list) else []:
        changes = entry.get("changes") if isinstance(entry, dict) else None
        for change in changes if isinstance(changes, list) else []:
            value = change.get("value") if isinstance(change, dict) else None
            if not isinstance(value, dict):
                continue
            for name, fields in (
                ("messages", ("from_user_id", "user_id", "from")),
                ("contacts", ("wa_id", "user_id")),
                ("statuses", ("recipient_id", "recipient_user_id")),
            ):
                items = value.get(name)
                for item in items if isinstance(items, list) else []:
                    if isinstance(item, dict):
                        for field in fields:
                            if isinstance(item.get(field), str):
                                identities.add(item[field])
    return identities


def contact_identities(contact: Contact) -> set[str]:
    identities = {contact.external_id}
    if contact.phone_e164:
        identities.add(contact.phone_e164.lstrip("+"))
    return identities


def contact_events(contact: Contact) -> set[UUID]:
    outbound = OutboundMessage.objects.using("owner").filter(
        tenant_id=contact.tenant_id, contact=contact
    )
    ids = set(outbound.exclude(inbound_event=None).values_list("inbound_event_id", flat=True))
    provider_ids = set(
        outbound.exclude(provider_message_id=None).values_list("provider_message_id", flat=True)
    )
    outbound_ids = {str(pk) for pk in outbound.values_list("id", flat=True)}
    identities = contact_identities(contact)
    events = InboundEvent.objects.using("owner").filter(
        tenant_id=contact.tenant_id, channel=contact.channel
    )
    for event in events.iterator(chunk_size=1000):
        if identities & _senders(event.payload):
            ids.add(event.id)
        # Delivery statuses also identify the outgoing message, even without a recipient.
        if isinstance(event.payload, dict):
            for entry in event.payload.get("entry", []):
                for change in entry.get("changes", []):
                    for status in change.get("value", {}).get("statuses", []):
                        if (
                            status.get("id") in provider_ids
                            or status.get("biz_opaque_callback_data") in outbound_ids
                        ):
                            ids.add(event.id)
    return ids


def demo_events(tenant_id: UUID, event_ids: set[UUID] | None = None) -> QuerySet[DemoEvent]:
    events = InboundEvent.objects.using("owner").filter(
        tenant_id=tenant_id, channel__in=DEMO_CHANNELS
    )
    if event_ids is not None:
        events = events.filter(id__in=event_ids)
    keys: set[tuple[str, str]] = set()
    for channel, provider_id in events.values_list("channel", "provider_event_id").iterator(
        chunk_size=1000
    ):
        keys.add((channel, provider_id.removeprefix("select:")))
    if not keys:
        return DemoEvent.objects.none()
    query = Q()
    for channel, raw in keys:
        query |= Q(channel=channel, provider_event_id=raw)
    return DemoEvent.objects.using("owner").filter(query)


class ExportTooLarge(Exception):
    """The export would exceed the byte cap given to `export_data`."""


class _Budget:
    """Bytes of JSON still allowed in one export; `None` is unlimited."""

    def __init__(self, limit: int | None) -> None:
        self.left = limit

    def rows(self, query: QuerySet[Any]) -> list[dict[str, Any]]:
        """The rows of `query`, read in chunks and measured as they come, so a huge export
        stops at the cap instead of filling memory first."""
        if self.left is None:
            return list(query.values())
        rows: list[dict[str, Any]] = []
        for row in query.values().iterator(chunk_size=200):
            self.left -= len(json.dumps(row, default=str, ensure_ascii=False).encode())
            if self.left < 0:
                raise ExportTooLarge
            rows.append(row)
        return rows


def export_data(
    tenant: Tenant, contact: Contact | None = None, *, max_bytes: int | None = None
) -> dict[str, Any]:
    """Everything stored about a tenant (or one contact), as JSON-able rows. With
    `max_bytes`, raises `ExportTooLarge` as soon as the rows' JSON would exceed it."""
    budget = _Budget(max_bytes)
    result: dict[str, Any] = {"tenant": tenant.slug, "data": {}}
    for model in MODELS:
        query: QuerySet[Any] = model.objects.using("owner").filter(tenant_id=tenant.id)
        if contact is not None:
            if model is Contact:
                query = query.filter(id=contact.id)
            elif model in (Conversation, OutboundMessage, Notification):
                query = query.filter(contact_id=contact.id)
            elif model is InboundEvent:
                query = query.filter(id__in=contact_events(contact))
            elif model is DemoSession and contact.channel in DEMO_CHANNELS:
                query = query.filter(
                    channel=contact.channel, external_id__in=contact_identities(contact)
                )
            else:
                query = query.none()
        result["data"][model._meta.db_table] = budget.rows(query)
    result["data"]["demo_event"] = (
        budget.rows(demo_events(tenant.id, contact_events(contact) if contact else None))
        if contact is None or contact.channel in DEMO_CHANNELS
        else []
    )
    if contact is not None and contact.channel in DEMO_CHANNELS:
        result["data"]["demo_access_grant"] = budget.rows(_grants(contact))
    return result


def write_private(path: str, data: dict[str, Any]) -> None:
    """Exclusive creation prevents accidental disclosure through existing files/symlinks."""
    try:
        descriptor = os.open(Path(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(data, output, default=str, ensure_ascii=False)
            output.write("\n")
    except OSError:
        raise CommandError("No se pudo crear el archivo privado de exportación.") from None


def _grants(contact: Contact) -> QuerySet[DemoAccessGrant]:
    """The invite redemptions of this person on this demo door. The grant belongs to the
    platform, not to a tenant, and holds the identity (Telegram id, BSUID or phone)."""
    return DemoAccessGrant.objects.using("owner").filter(
        channel=contact.channel, external_id__in=contact_identities(contact)
    )


def _erase(contact: Contact) -> None:
    ids = contact_events(contact)
    demo = contact.channel in DEMO_CHANNELS
    if demo:
        demo_events(contact.tenant_id, ids).delete()
    InboundEvent.objects.using("owner").filter(tenant_id=contact.tenant_id, id__in=ids).delete()
    if demo:
        # The session and the invite grant are keyed by the identity; without the grant
        # the person must redeem a code again to talk to the demo (`DemoInvite.uses` is a
        # plain counter and keeps no identity, so it stays).
        DemoSession.objects.using("owner").filter(
            channel=contact.channel, external_id__in=contact_identities(contact)
        ).delete()
        _grants(contact).delete()
    Contact.objects.using("owner").filter(tenant_id=contact.tenant_id, id=contact.id).delete()


def forget(contact: Contact) -> None:
    """Erase a contact and write the suppression ledger row in the same transaction."""
    with transaction.atomic(using="owner"):
        suppressions.record(
            suppressions.FORGET,
            contact.tenant_id,
            contact_id=contact.id,
            channel=contact.channel,
            identities=contact_identities(contact),
        )
        _erase(contact)


def _erase_by_hashes(tenant_id: UUID, channel: str, hashes: set[str]) -> int:
    """Erase again what a restore brought back for a forgotten identity whose contact row
    is not in the snapshot: its events (by sender), demo session and invite grants."""

    def known(external_id: str) -> bool:
        return suppressions.identity_hash(channel, external_id) in hashes

    count = 0
    event_ids = {
        event.id
        for event in InboundEvent.objects.using("owner")
        .filter(tenant_id=tenant_id, channel=channel)
        .iterator(chunk_size=1000)
        if any(known(identity) for identity in _senders(event.payload))
    }
    if event_ids:
        if channel in DEMO_CHANNELS:
            demo_events(tenant_id, event_ids).delete()
        count += InboundEvent.objects.using("owner").filter(id__in=event_ids).delete()[0]
    if channel in DEMO_CHANNELS:
        for model in (DemoSession, DemoAccessGrant):
            rows = model.objects.using("owner").filter(channel=channel)
            stale = [row.pk for row in rows if known(row.external_id)]
            if stale:
                count += model.objects.using("owner").filter(pk__in=stale).delete()[0]
    return count


def reapply(entries: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Re-run the erasures of a suppression ledger (ADR-019) over a restored database.

    Idempotent: what is already gone is a no-op. Each entry is the dict of
    `suppressions.as_dict`. Rows missing from the table (restored from an older snapshot)
    are re-inserted, so the table is complete again. Returns counters, never data."""
    result = {"entries": 0, "contacts": 0, "tenants": 0, "other_rows": 0, "blocked": 0}
    seen: set[str] = set()
    for entry in sorted(entries, key=lambda item: (str(item["at"]), str(item["id"]))):
        if entry["id"] in seen:
            continue
        seen.add(entry["id"])
        result["entries"] += 1
        tenant_id = UUID(entry["tenant_id"])
        with transaction.atomic(using="owner"):
            PrivacySuppression.objects.using("owner").get_or_create(
                id=UUID(entry["id"]),
                defaults={
                    "at": entry["at"],
                    "kind": entry["kind"],
                    "tenant_id": tenant_id,
                    "contact_id": UUID(entry["contact_id"]) if entry["contact_id"] else None,
                    "channel": entry["channel"],
                    "identity_hashes": entry["identity_hashes"],
                },
            )
            if entry["kind"] == suppressions.PURGE:
                tenant = Tenant.objects.using("owner").filter(pk=tenant_id).first()
                if tenant is not None:
                    try:
                        _purge(tenant, actor="command:privacy_reapply", ledger=False)
                    except PurgeBlocked:
                        result["blocked"] += 1  # the transaction rolled back; run it again
                    else:
                        result["tenants"] += 1
                continue
            contact = None
            if entry["contact_id"]:
                contact = (
                    Contact.objects.using("owner")
                    .filter(tenant_id=tenant_id, id=UUID(entry["contact_id"]))
                    .first()
                )
            if contact is not None:
                _erase(contact)
                result["contacts"] += 1
            elif Tenant.objects.using("owner").filter(pk=tenant_id).exists():
                result["other_rows"] += _erase_by_hashes(
                    tenant_id, entry["channel"], set(entry["identity_hashes"])
                )
    return result


class PurgeBlocked(CommandError):
    """Raised when a job for this tenant is currently running; nothing is deleted."""


def purge(tenant: Tenant, *, actor: str = "command:tenant_purge") -> None:
    _purge(tenant, actor=actor, ledger=True)


def _purge(tenant: Tenant, *, actor: str, ledger: bool) -> None:
    """Erase everything the platform stores about `tenant` (ADR-011): every
    customer-data table, its secrets, document and dataset versions, its alerts,
    its audit history and its own row, freeing its slug. Only a sanitized
    `tenant.purge` audit entry (with `tenant_id=None`) survives, plus whatever
    VictoriaLogs and the backups still retain under their own retention."""
    with transaction.atomic(using="owner"):
        revision = ConfigRevision.objects.using("owner").select_for_update().get(pk=1)
        current = Tenant.objects.using("owner").get(pk=tenant.pk)
        # `ledger=False` is `reapply`: the ledger says it was purged, whatever the
        # restored row's status.
        if ledger and current.status != "offboarded":
            raise CommandError("Solo se puede purgar un negocio dado de baja (offboarded).")
        tenant_id = tenant.id
        slug = current.slug
        with connections["owner"].cursor() as cursor:
            cursor.execute(
                "SELECT status FROM procrastinate_jobs WHERE args->>'tenant_id' = %s "
                "AND status IN ('todo', 'doing') FOR UPDATE",
                [str(tenant_id)],
            )
            # Locking the 'todo' rows too: `procrastinate_fetch_job` uses FOR UPDATE
            # SKIP LOCKED, so no worker can start them until this transaction ends.
            if any(status == "doing" for (status,) in cursor.fetchall()):
                raise PurgeBlocked(
                    "Hay trabajos en curso para este negocio; inténtalo de nuevo en unos segundos."
                )
        if ledger:
            # The purge entry subsumes the tenant's earlier `forget` rows: drop them, so
            # no identity hash of an erased person outlives the tenant.
            PrivacySuppression.objects.using("owner").filter(tenant_id=tenant.id).delete()
            suppressions.record(suppressions.PURGE, tenant.id)
        demo_events(tenant_id).delete()
        for model in MODELS:
            model.objects.using("owner").filter(tenant_id=tenant_id).delete()
        MetricEvent.objects.using("owner").filter(tenant_id=tenant_id).delete()
        TenantSecret.objects.using("owner").filter(tenant_id=tenant_id).delete()
        TenantDatasetVersion.objects.using("owner").filter(tenant_id=tenant_id).delete()
        TenantDocumentVersion.objects.using("owner").filter(tenant_id=tenant_id).delete()
        OpsAlert.objects.using("owner").filter(tenant_id=tenant_id).delete()
        AuditEvent.objects.using("owner").filter(tenant_id=tenant_id).delete()
        with connections["owner"].cursor() as cursor:
            cursor.execute(
                "DELETE FROM procrastinate_jobs WHERE args->>'tenant_id' = %s "
                "AND status <> 'doing'",
                [str(tenant_id)],
            )
        Tenant.objects.using("owner").filter(pk=tenant.pk).delete()
        revision.revision += 1
        revision.save(using="owner", update_fields=["revision", "updated_at"])
        record(
            actor=actor,
            action="tenant.purge",
            tenant_id=None,
            target_type="tenant",
            target_id=str(tenant_id),
            summary=f"Negocio eliminado: {slug}",
            details={"slug": slug},
        )

        def _clear_cache() -> None:
            cache.delete(f"health:{tenant_id}")
            for channel in Channel:
                cache.delete(runtime_state.key(tenant_id, channel))

        transaction.on_commit(_clear_cache, using="owner")
