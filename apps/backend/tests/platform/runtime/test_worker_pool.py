"""The worker's own psycopg pool is bounded from settings."""

from django.test import override_settings

from autobot.runtime.worker_pool import bounded_worker_connector, configure


def test_the_worker_connector_pool_is_bounded() -> None:
    with override_settings(WORKER_DB_POOL_MIN=1, WORKER_DB_POOL_MAX=5):
        connector = bounded_worker_connector()
    assert connector._pool_args["min_size"] == 1
    assert connector._pool_args["max_size"] == 5


def test_the_app_hands_out_the_bounded_connector() -> None:
    from autobot.runtime.jobs import app

    configure(app)
    connector = app.connector.get_worker_connector()  # type: ignore[attr-defined]
    assert connector._pool_args["max_size"] >= connector._pool_args["min_size"] >= 1
