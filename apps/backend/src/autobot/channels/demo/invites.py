"""Invitation codes for the demo doors (ADR-006 amendment): a closed-list
alternative that does not need a person's Telegram id up front. The panel creates a
code, with a note, a use limit and an optional expiry
(`autobot.panel.services.demo_invites`); a QR or a `t.me/<bot>?start=<code>` link
carries it. Redeeming it — `/start <code>` on Telegram, or sending the code as the
whole message on WhatsApp, since its deep links prefill the body — grants that
identity the same access as `DEMO_TELEGRAM_USERS`/`DEMO_WHATSAPP_USERS`, without
touching the server's `.env`.

`doors.allowed()` checks the grant on every message (not just the one that redeemed
the code), so access survives after the code stops appearing in later messages.

Codes are 12 characters (about 59 bits) and a person who fails to redeem one
`MAX_FAILED_REDEEMS` times in an hour is not checked again until the hour passes
(worker/web memory): codes cannot be guessed by trying.
"""

import logging
import re
import secrets as random_secrets
import string

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from autobot.channels.base import InboundItem
from autobot.channels.demo.doors import Door
from autobot.channels.ratelimit import WindowLimiter
from autobot.runtime.models import Channel, DemoAccessGrant, DemoInvite

log = logging.getLogger(__name__)

# Avoids visually ambiguous characters (0/O, 1/I/L): read off a printed QR caption or
# typed by hand from one phone to another.
ALPHABET = "".join(c for c in string.ascii_uppercase + string.digits if c not in "0O1IL")
CODE_LENGTH = 12
# What a message must look like to be tried as a code: letters and digits only, at least
# 10 characters (a shorter code was never issued). Anything else is chat, not a guess.
MIN_CANDIDATE_LENGTH = 10
MAX_CANDIDATE_LENGTH = 32
CANDIDATE = re.compile(rf"[A-Za-z0-9]{{{MIN_CANDIDATE_LENGTH},{MAX_CANDIDATE_LENGTH}}}")
MAX_FAILED_REDEEMS = 5
failed_redeems = WindowLimiter(limit=MAX_FAILED_REDEEMS, window_s=3600)


def generate_code() -> str:
    return "".join(random_secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def candidate_code(door: Door, item: InboundItem) -> str | None:
    """The invite code `item`'s message might be redeeming, or None (also when what it
    carries cannot be a code)."""
    code = _raw_candidate(door, item)
    return code if code and CANDIDATE.fullmatch(code) else None


def _raw_candidate(door: Door, item: InboundItem) -> str | None:
    text = (item.message.text or "").strip()
    if not text:
        return None
    if door.channel == Channel.DEMO_TG:
        if text.split()[0].split("@")[0].lower() != "/start":
            return None
        rest = text.removeprefix(text.split()[0]).strip()
        return rest or None
    # WhatsApp has no /start: its deep link (wa.me/<n>?text=<code>) prefills the
    # whole message body with the code, so the message *is* the code.
    return text


def _identities(item: InboundItem) -> set[str]:
    identities = {item.external_id}
    if item.phone:
        identities.add(item.phone.removeprefix("+"))
    return identities


def redeem(door: Door, item: InboundItem) -> bool:
    """Grant `item`'s identity access if its message carries a valid, unused invite
    code. Idempotent: redeeming again with the same identity only refreshes the
    grant's expiry."""
    code = candidate_code(door, item)
    if not code:
        return False
    key = f"{door.channel}:{item.external_id}"
    if failed_redeems.blocked(key):
        log.warning("demo invite redemption refused: too many failed attempts")
        return False
    if _redeem(door, item, code):
        return True
    failed_redeems.record(key)
    return False


def _redeem(door: Door, item: InboundItem, code: str) -> bool:
    now = timezone.now()
    with transaction.atomic():
        invite = (
            DemoInvite.objects.select_for_update()
            .filter(code__iexact=code, revoked_at__isnull=True)
            .first()
        )
        if invite is None:
            return False
        if invite.expires_at is not None and invite.expires_at <= now:
            return False
        # Redeeming again with an identity this same invite already granted just
        # refreshes it: it must not also eat another one of max_uses.
        already_granted = DemoAccessGrant.objects.filter(
            channel=door.channel, external_id=item.external_id, invite_id=invite.id
        ).exists()
        if not already_granted and invite.uses >= invite.max_uses:
            return False
        if not already_granted:
            DemoInvite.objects.filter(pk=invite.pk).update(uses=F("uses") + 1)
        DemoAccessGrant.objects.update_or_create(
            channel=door.channel,
            external_id=item.external_id,
            defaults={"invite_id": invite.id, "granted_at": now, "expires_at": invite.expires_at},
        )
    log.info("demo invite code redeemed")
    return True


def has_grant(door: Door, item: InboundItem) -> bool:
    """Whether `item`'s identity already redeemed a still-valid invite."""
    now = timezone.now()
    return (
        DemoAccessGrant.objects.filter(channel=door.channel, external_id__in=_identities(item))
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .exists()
    )
