"""Test database setup (design.md §12.2).

fp_app cannot create databases or tables, so Django's usual test setup (create and migrate
through `default`) is replaced: the test database `test_<name>` already exists (created by
deploy/postgres/init-roles.sh with POSTGRES_TEST_DB), both aliases point to it with their
own roles, and the migrations run as fp_owner. Tests therefore query as fp_app, under RLS.
"""

from collections.abc import Iterator

import pytest
from django.conf import settings
from django.core.management import call_command
from django.db import connections
from pytest_django import DjangoDbBlocker


@pytest.fixture(scope="session")
def django_db_setup(django_db_blocker: DjangoDbBlocker) -> Iterator[None]:
    for alias in ("default", "owner"):
        name = settings.DATABASES[alias]["NAME"]
        test_name = f"test_{name}"
        connections[alias].close()
        connections[alias].settings_dict["NAME"] = test_name
        settings.DATABASES[alias]["NAME"] = test_name
    with django_db_blocker.unblock():
        call_command("migrate", database="owner", verbosity=0, interactive=False)
    yield
