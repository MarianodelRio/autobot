"""`tenant_tx`: the only way to set the tenant for RLS."""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from django.db import connections, transaction

SET_TENANT = "SELECT set_config('app.tenant_id', %s, true)"


@contextmanager
def tenant_tx(tenant_id: UUID) -> Iterator[None]:
    """A short transaction on `default` (fp_app) in which only `tenant_id`'s rows exist.

    It cannot be nested (a durable atomic block): one transaction, one tenant. The setting
    is local to the transaction; on a successful exit it is also cleared, so code after
    the block sees no tenant even inside an outer test transaction (on errors the rollback
    undoes it).
    """
    with transaction.atomic(using="default", durable=True):
        with connections["default"].cursor() as cursor:
            cursor.execute(SET_TENANT, [str(tenant_id)])
        yield
        # On an error, or with the block marked for rollback, the rollback (even to a
        # savepoint) already undoes the local setting; a query would fail there.
        if not connections["default"].needs_rollback:
            with connections["default"].cursor() as cursor:
                cursor.execute(SET_TENANT, [""])
