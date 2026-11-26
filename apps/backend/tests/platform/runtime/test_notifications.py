"""Notification delivery and incident pushes with PostgreSQL and simulated Telegram."""

import json
from datetime import timedelta
from typing import Any

import httpx
import pytest
from django.db import connections
from django.utils import timezone

from autobot.channels.adapters import TELEGRAM
from autobot.ops.models import OpsAlert
from autobot.runtime import notifications, process
from autobot.runtime.models import Notification, OwnerLink
from autobot.runtime.outbound import SendRetry
from autobot.runtime.ratelimit import SlotLimiter
from autobot.tenancy.registry import get_registry
from autobot.tenancy.tx import tenant_tx
from core.actions import NotifyOwner
from tests.helpers.integration import jobs, wa_tenant

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]


@pytest.fixture
def telegram(settings: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    settings.NOTIFY_BOT_TOKEN = "notification-token"
    settings.OPS_TELEGRAM_CHAT_ID = "-200"

    def setup(*answers: Any) -> list[httpx.Request]:
        seen = []
        queue = list(answers)

        def handler(request: httpx.Request) -> httpx.Response:
            assert not connections["default"].in_atomic_block
            seen.append(request)
            answer = queue.pop(0)
            if isinstance(answer, Exception):
                raise answer
            assert isinstance(answer, httpx.Response)
            return answer

        monkeypatch.setattr(
            TELEGRAM, "client", httpx.Client(transport=httpx.MockTransport(handler))
        )
        return seen

    return setup


def ok() -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})


def notice(channel: str = "main", idem: str = "notice") -> Notification:
    tenant = get_registry().by_slug["wa"]
    with tenant_tx(tenant.id):
        process._notify_owner(tenant, channel, NotifyOwner("booking", "Hola <dueño>", idem))
        return Notification.objects.get(idem_key=idem)


def send(row: Notification, **kwargs: Any) -> None:
    notifications.send_notification(row.tenant_id, row.id, **kwargs)


def reload(row: Notification) -> Notification:
    return Notification.objects.using("owner").get(id=row.id)


def owner() -> dict[str, Any]:
    return wa_tenant(owner={"notify": ["booking"]})


def link(slug: str = "wa", chat_id: int = 100) -> None:
    tenant = get_registry().by_slug[slug]
    OwnerLink.objects.create(tenant_id=tenant.id, chat_id=chat_id, linked_at=timezone.now())


def test_delivery_once_and_job(tenants: Any, telegram: Any) -> None:
    tenants(owner())
    link()
    seen = telegram(ok())
    row = notice()
    assert notice().id == row.id
    queued = jobs()
    assert len(queued) == 1
    name, lock, args, queue = queued[0]
    assert (name, lock, queue) == ("send_notification", f"owner:{row.tenant_id}", "outbound")
    assert args == {"tenant_id": str(row.tenant_id), "notification_id": str(row.id)}
    send(row)
    send(row)
    assert len(seen) == 1
    assert "botnotification-token/" in str(seen[0].url)
    body = json.loads(seen[0].content)
    assert body["chat_id"] == "100" and "&lt;dueño&gt;" in body["text"]
    assert reload(row).status == "sent" and reload(row).sent_at is not None


@pytest.mark.parametrize("channel", ["main", "demo_tg", "demo_wa"])
def test_notify_owner_reaches_the_owner_on_any_channel(
    tenants: Any, telegram: Any, channel: str
) -> None:
    """A demo tenant's owner is notified the same way as a real one (no "ops" audience
    survives: a demo channel is not special-cased)."""
    tenants(owner())
    link()
    seen = telegram(ok())
    row = notice(channel)
    send(row)
    body = json.loads(seen[0].content)
    assert row.audience == "owner" and body["chat_id"] == "100"


@pytest.mark.parametrize("config", [None, {"notify": []}])
def test_unsubscribed_only_logs(tenants: Any, telegram: Any, caplog: Any, config: Any) -> None:
    tenants(wa_tenant(owner=config))
    seen = telegram()
    tenant = get_registry().by_slug["wa"]
    with tenant_tx(tenant.id):
        process._notify_owner(tenant, "main", NotifyOwner("booking", "private", "n"))
    assert not Notification.objects.using("owner").exists() and not jobs() and not seen
    assert "only logged" in caplog.text and "private" not in caplog.text


def test_safe_retry(tenants: Any, telegram: Any) -> None:
    tenants(owner())
    link()
    seen = telegram(httpx.Response(429, json={"parameters": {"retry_after": 7}}), ok())
    row = notice()
    with pytest.raises(SendRetry) as caught:
        send(row)
    assert caught.value.after_s == 7 and reload(row).status == "pending"
    send(row)
    assert reload(row).status == "sent" and len(seen) == 2


@pytest.mark.parametrize("code", [500, 503])
def test_5xx_is_ambiguous_never_retried(tenants: Any, telegram: Any, code: int) -> None:
    """Unlike 429, a 5xx is never retried blindly even if it carries `retry_after`."""
    tenants(owner())
    link()
    seen = telegram(httpx.Response(code, json={"parameters": {"retry_after": 7}}))
    row = notice()
    send(row)
    assert reload(row).status == "failed" and len(seen) == 1


@pytest.mark.parametrize("answer", [httpx.ReadTimeout("secret"), httpx.Response(403)])
def test_ambiguous_or_rejected_never_retried(tenants: Any, telegram: Any, answer: Any) -> None:
    tenants(owner())
    link()
    seen = telegram(answer)
    row = notice()
    send(row)
    send(row)
    assert len(seen) == 1 and reload(row).status == "failed"


def test_network_failure_is_retried_with_backoff_without_cap(tenants: Any, telegram: Any) -> None:
    """No connection was made: certainly not sent, so it is retried by time, however many
    attempts it already had."""
    tenants(owner())
    link()
    telegram(httpx.ConnectError("down"), ok())
    row = notice()
    with pytest.raises(SendRetry) as caught:
        send(row, attempts=40)
    assert caught.value.after_s is not None and 0 < caught.value.after_s <= 300
    assert reload(row).status == "pending"
    send(row, attempts=41)
    assert reload(row).status == "sent"


def test_stale_notice_expires_without_being_sent(tenants: Any, telegram: Any) -> None:
    tenants(owner())
    link()
    seen = telegram()
    row = notice()
    Notification.objects.using("owner").filter(id=row.id).update(
        created_at=timezone.now() - notifications.NOTICE_TTL - timedelta(seconds=1)
    )
    send(row)
    assert reload(row).status == "expired" and not seen
    send(row)  # terminal
    assert not seen


def test_retry_wait_never_goes_past_the_expiry(tenants: Any, telegram: Any) -> None:
    tenants(owner())
    link()
    telegram(httpx.Response(429, json={"parameters": {"retry_after": 3600}}))
    row = notice()
    Notification.objects.using("owner").filter(id=row.id).update(
        created_at=timezone.now() - notifications.NOTICE_TTL + timedelta(seconds=30)
    )
    with pytest.raises(SendRetry) as caught:
        send(row)
    assert caught.value.after_s is not None and caught.value.after_s <= 31


def test_no_slot_defers_without_calling_telegram(
    tenants: Any, telegram: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenants(owner())
    link()
    seen = telegram(ok())
    clock = [0.0]
    limiter = SlotLimiter(
        rate_per_s=25, key_interval_s=30, clock=lambda: clock[0], sleep=lambda _: None
    )
    monkeypatch.setattr(notifications, "LIMITER", limiter)
    assert limiter.acquire("100") is None  # the chat just used its slot
    row = notice()
    with pytest.raises(SendRetry) as caught:
        send(row)
    assert caught.value.after_s is not None and 30 <= caught.value.after_s <= 31
    assert reload(row).status == "pending" and not seen
    clock[0] = 31.0
    send(row)
    assert reload(row).status == "sent" and len(seen) == 1


def test_crash_after_claim_never_resends(tenants: Any, telegram: Any) -> None:
    tenants(owner())
    link()
    seen = telegram(RuntimeError("interrupted"))
    row = notice()
    with pytest.raises(RuntimeError):
        send(row)
    send(row)
    assert len(seen) == 1 and reload(row).status == "failed"


def test_rls_wrong_tenant_does_not_send(tenants: Any, telegram: Any) -> None:
    tenants(owner(), wa_tenant("other"))
    link()
    seen = telegram()
    row = notice()
    notifications.send_notification(get_registry().by_slug["other"].id, row.id)
    assert not seen and reload(row).status == "pending"


def test_an_incident_is_pushed_once_when_it_opens(tenants: Any, telegram: Any) -> None:
    tenants(owner())
    seen = telegram(ok(), ok(), ok())
    tenant_id = get_registry().by_slug["wa"].id
    assert notifications.send_ops_alert("stuck", tenant_id, "Alerta")
    # Still open: never pushed again, however long it lasts (ADR-031: no 30-min repeat).
    assert not notifications.send_ops_alert("stuck", tenant_id, "Alerta")
    assert notifications.send_ops_alert("failed", tenant_id, "Alerta")
    assert notifications.send_ops_alert("stuck", None, "Alerta")
    assert len(seen) == 3 and not Notification.objects.using("owner").exists()


def test_unconfigured_does_not_send(tenants: Any, telegram: Any, settings: Any) -> None:
    tenants(owner())
    link()
    seen = telegram()
    settings.NOTIFY_BOT_TOKEN = ""
    row = notice()
    send(row)
    assert reload(row).status == "failed"
    assert not notifications.send_ops_alert("stuck", None, "alert") and not seen


def test_two_checks_opening_the_same_incident_push_it_once(telegram: Any) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    seen = telegram(ok(), ok())
    barrier = Barrier(2)

    def check() -> bool:
        try:
            barrier.wait(timeout=10)
            return notifications.send_ops_alert("concurrent", None, "🔴 Alerta")
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: check(), range(2))) == [False, True]
    assert len(seen) == 1


def alert(kind: str = "stuck", tenant_id: Any = None) -> OpsAlert:
    return OpsAlert.objects.using("owner").get(kind=kind, tenant_id=tenant_id)


def test_ops_alert_persists_and_is_not_repeated(telegram: Any) -> None:
    seen = telegram(ok())
    assert notifications.send_ops_alert("stuck", None, "🔴 Algo falla")
    row = alert()
    assert row.occurrences == 1 and row.severity == "critical" and row.auto_resolves
    assert row.last_delivery == "sent" and row.sent_count == 1 and row.resolved_at is None
    assert not notifications.send_ops_alert("stuck", None, "🔴 Algo falla, de nuevo")
    row = alert()
    assert row.occurrences == 2 and row.text == "🔴 Algo falla, de nuevo"
    assert row.last_delivery == "sent" and row.sent_count == 1
    assert len(seen) == 1


def test_ops_alert_unconfigured_is_persisted(settings: Any) -> None:
    settings.OPS_TELEGRAM_CHAT_ID = ""
    assert not notifications.send_ops_alert("stuck", None, "🟠 Algo raro")
    row = alert()
    assert row.last_delivery == "unconfigured" and row.sent_count == 1


def test_ops_alert_telegram_failure_is_persisted(telegram: Any) -> None:
    telegram(httpx.Response(403))
    assert not notifications.send_ops_alert("stuck", None, "🟠 Algo raro")
    row = alert()
    assert row.last_delivery == "failed" and row.sent_count == 1 and row.occurrences == 1


def test_a_notice_is_never_pushed(telegram: Any) -> None:
    seen = telegram()
    assert not notifications.send_ops_alert("stuck", None, "🟡 Algo menor")
    row = alert()
    assert row.severity == "notice" and row.last_delivery == "panel" and row.sent_count == 0
    assert not seen


def test_an_escalation_to_critical_always_pushes_and_to_warning_at_most_hourly(
    telegram: Any,
) -> None:
    seen = telegram(ok(), ok(), ok())
    assert not notifications.send_ops_alert("stuck", None, "🟡 Algo menor")
    assert notifications.send_ops_alert("stuck", None, "🟠 Algo peor")
    assert alert().severity == "warning"
    # Escalating to 🔴 within the hour still pushes: a critical one never waits.
    assert notifications.send_ops_alert("stuck", None, "🔴 Algo grave")
    assert alert().severity == "critical" and len(seen) == 2
    # Back down: the severity follows, without a push.
    assert not notifications.send_ops_alert("stuck", None, "🟡 Algo menor")
    assert alert().severity == "notice" and len(seen) == 2
    # Up to 🟠 again within the hour: updated, not pushed.
    assert not notifications.send_ops_alert("stuck", None, "🟠 Algo peor")
    assert alert().severity == "warning" and alert().last_delivery == "throttled"
    # An hour after the last push, an escalation to 🟠 is pushed again.
    OpsAlert.objects.using("owner").update(
        severity="notice", last_sent_at=timezone.now() - timedelta(hours=2)
    )
    assert notifications.send_ops_alert("stuck", None, "🟠 Algo peor")
    assert alert().last_delivery == "sent" and len(seen) == 3


def test_ops_alert_informational_is_saved_already_resolved(telegram: Any) -> None:
    seen = telegram(ok(), ok(), ok())
    assert notifications.send_ops_alert(
        "deploy_success", None, "🟢 Desplegado bien", informational=True
    )
    row = alert("deploy_success")
    assert row.resolved_at is not None and row.resolved_by == "info"
    assert row.severity == "info" and len(seen) == 1
    # A one-off notice: a second one sends right away.
    assert notifications.send_ops_alert(
        "deploy_success", None, "🟢 Desplegado bien", informational=True
    )
    assert len(seen) == 2
    assert OpsAlert.objects.using("owner").filter(kind="deploy_success").count() == 2
    # A kind the registry declares informational is born resolved without the flag.
    assert notifications.send_ops_alert("deploy_ok", None, "🟢 Desplegado abc")
    assert alert("deploy_ok").resolved_by == "info"


def test_an_event_stays_open_and_counts_each_case(telegram: Any) -> None:
    from autobot.ops.incidents import BOOTSTRAP

    seen = telegram(ok(), ok())
    before = timezone.now()
    assert notifications.send_ops_alert("deploy_aborted", None, "🔴 Despliegue abortado")
    # Each failed deploy matters: pushed on every new case, never throttled (ADR-031).
    assert notifications.send_ops_alert("deploy_aborted", None, "🔴 Despliegue abortado")
    row = alert("deploy_aborted")
    assert not row.auto_resolves and row.case_count == 2 and row.last_case_at is not None
    # No previous review: only the last 24 h count.
    assert row.review_watermark is not None
    assert abs((row.review_watermark - (before - BOOTSTRAP)).total_seconds()) < 60
    assert len(seen) == 2


def test_a_reviewed_deploy_rollback_pushes_again_on_the_next_one(telegram: Any) -> None:
    from autobot.ops.incidents import review

    seen = telegram(ok(), ok())
    assert notifications.send_ops_alert("deploy_rollback", None, "🔴 Despliegue revertido")
    assert review(alert("deploy_rollback").id, actor="ana").ok
    # Minutes later, another rollback: a new period, pushed (not throttled).
    assert notifications.send_ops_alert("deploy_rollback", None, "🔴 Despliegue revertido")
    reopened = OpsAlert.objects.using("owner").get(kind="deploy_rollback", resolved_at=None)
    assert reopened.last_delivery == "sent" and len(seen) == 2


def test_a_reopened_event_pushes_at_most_once_an_hour(telegram: Any) -> None:
    from autobot.ops.incidents import review

    seen = telegram(ok(), ok())
    kind = "failed_job:ops_check"
    last = timezone.now() - timedelta(minutes=1)
    assert notifications.send_ops_alert(
        kind, None, "🟠 Fallos (1).", case_count=1, last_case_at=last
    )
    first = alert(kind)
    assert review(first.id, actor="ana").ok
    first.refresh_from_db(using="owner")
    assert first.resolved_by == "ana" and first.review_watermark == last
    # A case after the review: a new open period that inherits the watermark, not pushed
    # again within the hour.
    assert not notifications.send_ops_alert(kind, None, "🟠 Fallos (1).", case_count=1)
    second = OpsAlert.objects.using("owner").get(kind=kind, resolved_at__isnull=True)
    assert second.id != first.id and second.review_watermark == last
    assert second.last_delivery == "throttled" and len(seen) == 1
    # An hour later, the next reopening is pushed.
    OpsAlert.objects.using("owner").filter(kind=kind).update(
        last_sent_at=timezone.now() - timedelta(hours=2)
    )
    assert review(second.id, actor="ana").ok
    assert notifications.send_ops_alert(kind, None, "🟠 Fallos (1).", case_count=1)
    assert len(seen) == 2


def test_a_review_is_only_for_an_open_event(telegram: Any) -> None:
    from autobot.ops.incidents import review

    telegram(ok(), ok())
    notifications.send_ops_alert("stuck", None, "🔴 Algo falla")
    assert not review(alert().id, actor="ana").ok  # a condition closes itself
    notifications.send_ops_alert("deploy_aborted", None, "🔴 Despliegue abortado")
    row = alert("deploy_aborted")
    assert review(row.id, actor="ana").ok
    assert not review(row.id, actor="ana").ok  # already closed


def test_an_undelivered_push_is_retried_hourly_until_it_goes_out(telegram: Any) -> None:
    seen = telegram(httpx.Response(403), ok())
    assert not notifications.send_ops_alert("stuck", None, "🔴 Algo falla")
    assert alert().last_delivery == "failed"
    assert notifications.retry_undelivered() == 0  # tried less than an hour ago
    OpsAlert.objects.using("owner").update(last_sent_at=timezone.now() - timedelta(hours=2))
    assert notifications.retry_undelivered() == 1
    row = alert()
    assert row.last_delivery == "sent" and row.sent_count == 2 and len(seen) == 2
    assert notifications.retry_undelivered() == 0


def test_a_notice_is_not_retried(telegram: Any) -> None:
    seen = telegram()
    notifications.send_ops_alert("stuck", None, "🟡 Algo menor")
    OpsAlert.objects.using("owner").update(last_delivery="failed", last_sent_at=None)
    assert notifications.retry_undelivered() == 0 and not seen


def test_a_condition_that_returns_opens_a_new_row_pushed_at_most_hourly(telegram: Any) -> None:
    seen = telegram(ok(), ok())
    assert notifications.send_ops_alert("stuck", None, "🔴 Algo falla")
    notifications.resolve_alert(alert(), by="auto")
    row = alert()
    assert row.resolved_at is not None and row.resolved_by == "auto"
    # A flapping condition: back within the hour, a new row but no push.
    assert not notifications.send_ops_alert("stuck", None, "🔴 Algo falla otra vez")
    reopened = OpsAlert.objects.using("owner").get(kind="stuck", resolved_at__isnull=True)
    assert reopened.last_delivery == "throttled" and len(seen) == 1
    notifications.resolve_alert(reopened, by="auto")
    # An hour after the last push, it is pushed again.
    OpsAlert.objects.using("owner").update(last_sent_at=timezone.now() - timedelta(hours=2))
    assert notifications.send_ops_alert("stuck", None, "🔴 Algo falla otra vez")
    assert len(seen) == 2
    open_rows = OpsAlert.objects.using("owner").filter(kind="stuck", resolved_at__isnull=True)
    assert open_rows.count() == 1


def test_resolve_alert_with_notify_sends_a_resolved_message(telegram: Any) -> None:
    seen = telegram(ok(), ok())
    notifications.send_ops_alert("stuck", None, "🔴 Algo falla")
    notifications.resolve_alert(alert(), by="auto", notify=True)
    assert len(seen) == 2
    body = json.loads(seen[-1].content)
    assert body["text"] == "✅ Resuelta: 🔴 Algo falla"


def test_resolve_alert_without_notify_sends_nothing_extra(telegram: Any) -> None:
    seen = telegram(ok())
    notifications.send_ops_alert("stuck", None, "🔴 Algo falla")
    notifications.resolve_alert(alert(), by="auto")  # notify defaults to False
    assert len(seen) == 1


def test_resolve_alert_notify_is_a_noop_without_a_configured_bot(settings: Any) -> None:
    settings.OPS_TELEGRAM_CHAT_ID = ""
    settings.NOTIFY_BOT_TOKEN = ""
    notifications.send_ops_alert("stuck", None, "🔴 Algo falla")
    notifications.resolve_alert(alert(), by="auto", notify=True)  # must not raise


# ── Owner without a linked chat (ADR-026) ────────────────────────────────


def test_unlinked_owner_holds_the_notice_then_it_goes_out_on_link(
    tenants: Any, telegram: Any
) -> None:
    from autobot.owner import links

    tenants(owner())
    seen = telegram(ok())
    row = notice()
    send(row)
    assert reload(row).status == "held" and not seen

    code = links.new_invite(row.tenant_id)
    assert links.start_link(code, 100).status == "linked"
    assert reload(row).status == "pending"
    assert jobs()[-1][0] == "send_notification"
    send(row)
    assert reload(row).status == "sent" and len(seen) == 1


def test_stale_held_notices_expire_on_link_and_are_never_sent(tenants: Any, telegram: Any) -> None:
    from autobot.owner import links

    tenants(owner())
    seen = telegram()
    fresh, stale = notice(idem="fresh"), notice(idem="stale")
    send(fresh)
    send(stale)
    Notification.objects.using("owner").filter(id=stale.id).update(
        created_at=timezone.now() - notifications.NOTICE_TTL - timedelta(minutes=1)
    )
    code = links.new_invite(stale.tenant_id)
    assert links.start_link(code, 100).status == "linked"
    assert (reload(fresh).status, reload(stale).status) == ("pending", "expired")
    assert not seen
    assert notifications.release_held(stale.tenant_id) == 0  # idempotent


def test_an_undelivered_push_is_retried_when_unconfigured_but_never_once_resolved(
    telegram: Any, settings: Any
) -> None:
    seen = telegram(ok())
    settings.OPS_TELEGRAM_CHAT_ID = ""
    assert not notifications.send_ops_alert("stuck", None, "🔴 Algo falla")
    assert not notifications.send_ops_alert("other", None, "🔴 Otra cosa")
    assert {a.last_delivery for a in OpsAlert.objects.using("owner").all()} == {"unconfigured"}
    notifications.resolve_alert(alert("other"), by="auto")
    settings.OPS_TELEGRAM_CHAT_ID = "-200"
    OpsAlert.objects.using("owner").update(last_sent_at=timezone.now() - timedelta(hours=2))
    assert notifications.retry_undelivered() == 1  # only the open one
    assert alert().last_delivery == "sent" and alert("other").last_delivery == "unconfigured"
    assert len(seen) == 1


def test_an_event_reviewed_after_its_cases_were_counted_does_not_reopen(telegram: Any) -> None:
    """ops_check counted the cases, a person reviewed them, then ops_check syncs: the
    newest case is not after the watermark, so no new period opens."""
    from autobot.ops.incidents import review

    telegram(ok())
    kind = "failed_job:ops_check"
    last = timezone.now() - timedelta(minutes=1)
    notifications.send_ops_alert(kind, None, "🟠 Fallos (1).", case_count=1, last_case_at=last)
    assert review(alert(kind).id, actor="ana").ok
    assert not notifications.send_ops_alert(
        kind, None, "🟠 Fallos (1).", case_count=1, last_case_at=last
    )
    assert not OpsAlert.objects.using("owner").filter(kind=kind, resolved_at__isnull=True)


def test_a_legacy_open_row_turned_event_gets_the_panel_watermark() -> None:
    from autobot.ops.incidents import BOOTSTRAP

    first_seen = timezone.now() - timedelta(hours=3)
    OpsAlert.objects.create(
        kind="notification_failed",
        severity="warning",
        text="🟠 old",
        auto_resolves=True,  # from before ADR-031 made it an event
        first_seen_at=first_seen,
        last_delivery="sent",
    )
    notifications.send_ops_alert("notification_failed", None, "🟠 new", case_count=1)
    row = alert("notification_failed")
    assert not row.auto_resolves and row.review_watermark == first_seen - BOOTSTRAP


def test_a_notice_records_when_it_failed_and_clears_it_once_sent(
    tenants: Any, telegram: Any
) -> None:
    tenants(owner())
    link()
    telegram(httpx.Response(400, json={"ok": False, "description": "Bad Request"}))
    row = notice()
    send(row)
    failed = reload(row)
    assert failed.status == "failed" and failed.failed_at is not None
    telegram(ok())
    sent = notice(idem="second")
    send(sent)
    assert reload(sent).status == "sent" and reload(sent).failed_at is None
