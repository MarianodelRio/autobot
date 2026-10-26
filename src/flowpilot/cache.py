"""Persistent operation cooldowns must survive cache capacity pressure."""

from datetime import datetime

from django.core.cache.backends.db import DatabaseCache
from django.db import connections
from django.db.backends.utils import CursorWrapper


class CooldownCache(DatabaseCache):
    """Keep Django's database cache API, but never evict unexpired cooldowns."""

    _table: str  # Initialized by DatabaseCache; absent from django-stubs.

    def _cull(self, db: str, cursor: CursorWrapper, now: datetime, num: int) -> None:
        connection = connections[db]
        table = connection.ops.quote_name(self._table)
        cursor.execute(
            f"DELETE FROM {table} WHERE expires < %s",
            [connection.ops.adapt_datetimefield_value(now)],
        )
