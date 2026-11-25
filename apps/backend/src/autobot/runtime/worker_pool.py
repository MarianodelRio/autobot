"""A bounded database pool for `procrastinate worker`.

The worker swaps the app's `DjangoConnector` for a `PsycopgConnector` whose pool (psycopg
default: 4 connections, `min_size` = `max_size`) is created outside Django's own
`CONN_MAX_AGE` handling. `configure` (settings: `PROCRASTINATE_ON_APP_READY`) makes
`get_worker_connector` return one sized by `WORKER_DB_POOL_MIN`/`WORKER_DB_POOL_MAX`
(default 1 and 6: the LISTEN connection, fetch, heartbeat and the finish of the
`--concurrency 2` jobs), so the worker's share of the connection budget is known.
"""

import sys
from typing import Any

from django.conf import settings
from procrastinate import App
from procrastinate.contrib.django import settings as procrastinate_settings
from procrastinate.contrib.django import utils
from procrastinate.contrib.django.django_connector import DjangoConnector
from procrastinate.psycopg_connector import PsycopgConnector


def bounded_worker_connector() -> PsycopgConnector:
    alias = procrastinate_settings.settings.DATABASE_ALIAS
    low = max(1, int(settings.WORKER_DB_POOL_MIN))
    high = max(low, int(settings.WORKER_DB_POOL_MAX))
    return PsycopgConnector(kwargs=utils.connector_params(alias), min_size=low, max_size=high)


def configure(app: App) -> None:
    # Only `manage.py procrastinate worker` preloads the registry; other commands and
    # the web process stay lazy (the web process warms up in `config/wsgi.py`).
    if sys.argv[1:3] == ["procrastinate", "worker"]:
        from autobot.tenancy.registry import warm_up_in_background

        warm_up_in_background(poll=True)
    connector: Any = app.connector
    if isinstance(connector, DjangoConnector):
        connector.get_worker_connector = bounded_worker_connector  # type: ignore[method-assign]
