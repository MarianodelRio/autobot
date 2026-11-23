"""Every database alias, and the worker's procrastinate pool built from it, carries the
libpq connect timeout and TCP keepalives (a half-dead network must not hang queries)."""

import pytest
from django.conf import settings
from django.db import connections
from procrastinate.contrib.django import utils


@pytest.mark.parametrize("alias", sorted(settings.DATABASES))
def test_every_alias_has_connect_timeout_and_keepalives(alias: str) -> None:
    options = settings.DATABASES[alias]["OPTIONS"]
    assert 0 < options["connect_timeout"] <= 10
    assert options["keepalives"] == 1
    assert (options["keepalives_idle"], options["keepalives_interval"]) == (30, 10)
    assert options["keepalives_count"] == 3


def test_the_worker_pool_gets_them_too() -> None:
    params = utils.connector_params("default")
    assert params["connect_timeout"] == settings.DATABASES["default"]["OPTIONS"]["connect_timeout"]
    assert params["keepalives_idle"] == 30
    assert connections["default"].settings_dict["OPTIONS"]["keepalives"] == 1
