"""Demo invite codes (D5): list, create and revoke, with the QR/link each one needs
for a person to redeem it on the demo door's Telegram bot."""

from datetime import datetime
from typing import Any
from uuid import UUID

from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Field, Router, Schema

from autobot.panel.errors import ApiError
from autobot.panel.services import demo_invites
from autobot.runtime.models import DemoInvite

router = Router(tags=["demo-invites"])


class DemoInviteOut(Schema):
    id: UUID
    code: str
    note: str
    max_uses: int
    uses: int
    grants: int
    expires_at: datetime | None
    revoked_at: datetime | None
    created_by: str
    created_at: datetime
    telegram_link: str | None
    qr_svg: str | None


class DemoInviteCreate(Schema):
    note: str = ""
    max_uses: int = Field(1, ge=1, le=1000)
    # None: never expires. The field is required (no default) so the panel always
    # states its choice explicitly, rather than silently falling back to one.
    expires_in_days: int | None = Field(ge=1, le=365)


def _out(invite: DemoInvite) -> dict[str, Any]:
    return {
        "id": invite.id,
        "code": invite.code,
        "note": invite.note,
        "max_uses": invite.max_uses,
        "uses": invite.uses,
        "grants": demo_invites.grant_count(invite),
        "expires_at": invite.expires_at,
        "revoked_at": invite.revoked_at,
        "created_by": invite.created_by,
        "created_at": invite.created_at,
        "telegram_link": demo_invites.telegram_link(invite.code),
        "qr_svg": demo_invites.qr_svg(invite.code),
    }


@router.get("/demo/invites", response=list[DemoInviteOut])
def list_invites(request: HttpRequest) -> list[dict[str, Any]]:
    invites = DemoInvite.objects.using("owner").order_by("-created_at")
    return [_out(invite) for invite in invites]


@router.post("/demo/invites", response=DemoInviteOut)
def create(request: HttpRequest, payload: DemoInviteCreate) -> dict[str, Any]:
    invite = demo_invites.create_invite(
        note=payload.note.strip(),
        max_uses=payload.max_uses,
        expires_in_days=payload.expires_in_days,
        actor=request.user.username,
    )
    return _out(invite)


@router.post("/demo/invites/{id}/revoke", response=DemoInviteOut)
def revoke(request: HttpRequest, id: UUID) -> dict[str, Any]:
    invite = get_object_or_404(DemoInvite.objects.using("owner"), pk=id)
    if invite.revoked_at is not None:
        raise ApiError("conflict", "La invitación ya está revocada.", 409)
    demo_invites.revoke_invite(invite, actor=request.user.username)
    invite.refresh_from_db(using="owner")
    return _out(invite)
