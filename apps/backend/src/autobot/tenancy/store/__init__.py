"""The single, serialized and audited path for tenant configuration writes.

A package split by concern (`documents`, `datasets`, `channel_secrets`, `imports`,
`validate`, `revision`); this module is the facade the rest of the platform imports.
"""

from autobot.tenancy.store.channel_secrets import set_secrets
from autobot.tenancy.store.datasets import import_dataset
from autobot.tenancy.store.documents import (
    CONTENT_KEYS,
    change_status,
    create_tenant,
    new_document,
    publish,
    rollback,
)
from autobot.tenancy.store.errors import IDENTITY, StoreError
from autobot.tenancy.store.imports import import_source
from autobot.tenancy.store.validate import current_sources, find_source, lock

__all__ = [
    "CONTENT_KEYS",
    "IDENTITY",
    "StoreError",
    "change_status",
    "create_tenant",
    "current_sources",
    "find_source",
    "import_dataset",
    "import_source",
    "lock",
    "new_document",
    "publish",
    "rollback",
    "set_secrets",
]
