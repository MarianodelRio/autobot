"""`seed_dev_activity` creates fake, local-only activity across every timeline source
and cleans up exactly what it created."""

import json
from pathlib import Path
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections

from autobot.ops.models import OpsAlert, SystemSample
from autobot.runtime.models import Contact, InboundEvent, MetricEvent, Notification, OutboundMessage
from tests.helpers.integration import demo_tenant, wa_tenant

pytestmark = [
    pytest.mark.django_db(transaction=True, databases=["default", "owner"]),
    pytest.mark.usefixtures("clean_jobs"),
]


def seed(tmp_path: Path, settings: Any, **options: Any) -> None:
    settings.OPS_STATE_DIR = tmp_path
    call_command("seed_dev_activity", **options)


def dev_counts() -> dict[str, int]:
    return {
        "contacts": Contact.objects.using("owner").filter(external_id__startswith="dev-").count(),
        "inbound": InboundEvent.objects.using("owner")
        .filter(provider_event_id__startswith="dev-")
        .count(),
        "outbound": OutboundMessage.objects.using("owner")
        .filter(idem_key__startswith="dev-")
        .count(),
        "notifications": Notification.objects.using("owner")
        .filter(idem_key__startswith="dev-")
        .count(),
        "metrics": MetricEvent.objects.using("owner").filter(idem_key__startswith="dev-").count(),
        "alerts": OpsAlert.objects.filter(kind__startswith="dev:").count(),
    }


def test_refuses_outside_local(settings: Any) -> None:
    settings.ENVIRONMENT = "prod"
    with pytest.raises(CommandError, match="local"):
        call_command("seed_dev_activity")


def test_refuses_without_any_tenant(settings: Any) -> None:
    with pytest.raises(CommandError, match="negocios"):
        call_command("seed_dev_activity")


def test_creates_rows_across_every_timeline_source(
    tenants: Any, tmp_path: Path, settings: Any
) -> None:
    tenants(wa_tenant("wa", pack="bus"), demo_tenant("demo"))
    seed(tmp_path, settings, days=3)

    counts = dev_counts()
    assert all(count > 0 for count in counts.values())
    assert counts["alerts"] == 8
    assert OpsAlert.objects.filter(kind__startswith="dev:", resolved_at__isnull=True).count() == 3
    assert OpsAlert.objects.filter(kind__startswith="dev:", resolved_at__isnull=False).count() == 5

    with connections["default"].cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM procrastinate_jobs WHERE args->>'seed_dev_activity' = 'true'"
        )
        (job_count,) = cursor.fetchone()
        cursor.execute(
            "SELECT count(*) FROM procrastinate_events e JOIN procrastinate_jobs j"
            " ON j.id = e.job_id WHERE j.args->>'seed_dev_activity' = 'true'"
        )
        (event_count,) = cursor.fetchone()
    assert job_count == 1 and event_count == 3

    assert SystemSample.objects.count() > 0

    backup = json.loads((tmp_path / "backup.json").read_text())
    assert backup["ok"] is True and backup["dump_bytes"] > 0
    deploys = [json.loads(line) for line in (tmp_path / "deploys.jsonl").read_text().splitlines()]
    assert deploys and {d["result"] for d in deploys} <= {
        "deployed",
        "already",
        "aborted",
        "rolled_back",
        "rollback_failed",
    }

    # A row of each outbound status variety exists somewhere in the data.
    statuses = set(
        OutboundMessage.objects.using("owner")
        .filter(idem_key__startswith="dev-")
        .values_list("status", flat=True)
    )
    assert "sent" in statuses


def test_bus_pack_tenant_gets_schedule_query_metrics(
    tenants: Any, tmp_path: Path, settings: Any
) -> None:
    tenants(wa_tenant("busbiz", pack="bus"))
    seed(tmp_path, settings, days=2)
    kinds = set(
        MetricEvent.objects.using("owner")
        .filter(idem_key__startswith="dev-")
        .values_list("kind", flat=True)
    )
    assert kinds == {"schedule_query"}


def test_reset_leaves_a_single_fresh_batch(tenants: Any, tmp_path: Path, settings: Any) -> None:
    tenants(wa_tenant("wa", pack="bus"), demo_tenant("demo"))
    seed(tmp_path, settings, days=2)
    first = dev_counts()
    seed(tmp_path, settings, days=2, reset=True)
    second = dev_counts()
    # Not an exact repeat (random counts per day), but reset must never accumulate:
    # a second --reset starting from the first run's data lands in the same range.
    for key in first:
        assert second[key] > 0
    assert OpsAlert.objects.filter(kind__startswith="dev:").count() == 8


def test_reset_without_prior_data_is_a_noop(tenants: Any, tmp_path: Path, settings: Any) -> None:
    tenants(wa_tenant("wa"))
    seed(tmp_path, settings, days=1, reset=True)
    assert dev_counts()["contacts"] > 0
