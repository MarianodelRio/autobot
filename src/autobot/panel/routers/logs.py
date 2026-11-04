"""Filtered technical logs; no free-form LogsQL is accepted."""

from django.http import HttpRequest
from ninja import Query, Router

from autobot.panel.services.logs import LogFilters, LogsOut, query_logs

router = Router(tags=["logs"])


@router.get("/logs", response=LogsOut)
def logs(request: HttpRequest, filters: Query[LogFilters]) -> LogsOut:
    return query_logs(filters)
