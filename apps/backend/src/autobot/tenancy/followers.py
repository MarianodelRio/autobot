"""Which configuration revision each live process has loaded (`config_follower`, ADR-030).

Read by the panel (Sistema screen, the «applied in N processes» confirmation) and by
`ops_check` (`config_stale`). A row is *alive* if its process wrote it in the last
`ALIVE_SECONDS` (it refreshes it every 15 s, and a clean exit deletes it); older rows are
ignored here and purged by `ops_check` after a day. A process is *behind* when the revision
it loaded is not the database's: also when the database went back to an older one."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import DatabaseError

from autobot.tenancy.models import ConfigFollower, ConfigRevision

ALIVE_SECONDS = 35
MAX_ROWS = 200  # a sane bound: the real number is under 50
PURGE_AFTER = timedelta(days=1)


@dataclass(frozen=True)
class Follower:
    service: str
    host: str
    pid: int
    revision: int
    started_at: datetime
    seen_at: datetime
    behind: bool
    last_error_at: datetime | None  # since when its checks fail, if they do


@dataclass(frozen=True)
class ConfigState:
    revision: int
    updated_at: datetime | None
    followers: list[Follower]


def read_state(now: datetime, alias: str = "default") -> ConfigState:
    """The database revision and the alive processes, with `behind` computed against it."""
    row = ConfigRevision.objects.using(alias).filter(pk=1).first()
    if row is None:
        raise DatabaseError("Configuration revision is missing")
    alive = ConfigFollower.objects.using(alias).filter(
        seen_at__gte=now - timedelta(seconds=ALIVE_SECONDS)
    )
    followers = [
        Follower(
            service=f.service,
            host=f.host,
            pid=f.pid,
            revision=f.revision,
            started_at=f.started_at,
            seen_at=f.seen_at,
            behind=f.revision != row.revision,
            last_error_at=f.last_error_at,
        )
        for f in alive.order_by("service", "host", "pid")[:MAX_ROWS]
    ]
    return ConfigState(revision=row.revision, updated_at=row.updated_at, followers=followers)


def purge_stale(now: datetime) -> int:
    """Delete the rows of processes not seen for a day (`ops_check`, as fp_app)."""
    deleted, _ = ConfigFollower.objects.filter(seen_at__lt=now - PURGE_AFTER).delete()
    return deleted
