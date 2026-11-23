"""Demo invite codes: create, list and revoke them from the panel, and build
what it needs to print or scan as a QR. Always `.using("owner")` (CLAUDE.md): this is
panel-only, never written by the worker (which only reads/updates `uses` on
redemption, `autobot.channels.demo.invites`)."""

from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.utils import timezone

from autobot.channels.demo.invites import generate_code
from autobot.ops.audit import record
from autobot.panel.services.pagination import page
from autobot.runtime.models import DemoAccessGrant, DemoInvite
from tools.ops.qr import svg_markup

MAX_CODE_ATTEMPTS = 5


def telegram_link(code: str) -> str | None:
    """`None` without `DEMO_TELEGRAM_BOT_USERNAME` configured: the invite still works
    by code alone, but the panel cannot build a deep link or a QR for it."""
    username = settings.DEMO_TELEGRAM_BOT_USERNAME
    return f"https://t.me/{username}?start={code}" if username else None


def qr_svg(code: str) -> str | None:
    link = telegram_link(code)
    return svg_markup(link) if link else None


def create_invite(
    *, note: str, max_uses: int, expires_in_days: int | None, actor: str
) -> DemoInvite:
    expires_at = timezone.now() + timedelta(days=expires_in_days) if expires_in_days else None
    # The invite and its audit row commit together or not at all.
    with transaction.atomic(using="owner"):
        for _ in range(MAX_CODE_ATTEMPTS):
            try:
                with transaction.atomic(using="owner"):
                    invite = DemoInvite.objects.using("owner").create(
                        code=generate_code(),
                        note=note,
                        max_uses=max_uses,
                        expires_at=expires_at,
                        created_by=actor,
                    )
                break
            except IntegrityError:
                continue
        else:
            raise RuntimeError("No se pudo generar un código de invitación único.")
        record(
            actor=actor,
            action="demo_invite.create",
            summary=f"Crea invitación de demo «{note}»." if note else "Crea invitación de demo.",
            target_type="demo_invite",
            target_id=str(invite.id),
        )
    return invite


def revoke_invite(invite: DemoInvite, *, actor: str) -> None:
    with transaction.atomic(using="owner"):
        DemoInvite.objects.using("owner").filter(pk=invite.pk, revoked_at__isnull=True).update(
            revoked_at=timezone.now()
        )
        # Revoking withdraws the access already granted, not only future redemptions.
        DemoAccessGrant.objects.using("owner").filter(invite_id=invite.pk).delete()
        record(
            actor=actor,
            action="demo_invite.revoke",
            summary="Revoca invitación de demo.",
            target_type="demo_invite",
            target_id=str(invite.id),
        )


def list_invites(*, limit: int, cursor: str) -> tuple[list[DemoInvite], str | None]:
    """One keyset page (grants counted by a subquery, not one COUNT per row); no total:
    counting every invite for each page is what a cursor avoids."""
    grants = (
        DemoAccessGrant.objects.using("owner")
        .filter(invite_id=OuterRef("pk"))
        .order_by()
        .values("invite_id")
        .annotate(n=Count("pk"))
        .values("n")
    )
    queryset = DemoInvite.objects.using("owner").annotate(grant_total=Coalesce(Subquery(grants), 0))
    return page(queryset, field="created_at", cursor=cursor, limit=limit)


def grant_count(invite: DemoInvite) -> int:
    return DemoAccessGrant.objects.using("owner").filter(invite_id=invite.id).count()
