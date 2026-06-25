"""Storage layer.

In-memory model pool, didactic Repository wrapper, Arrow/Parquet materialized
views, and the content-addressed blob cache.
"""

from __future__ import annotations

from lairs.store.arrow import (
    annotations_table,
    expressions_table,
    flatten_anchor,
    materialize,
    records_to_table,
)
from lairs.store.blobcache import BlobCache, BlobCacheError
from lairs.store.pool import ModelPool
from lairs.store.repository import RecordDiff, Repository, Workspace

__all__ = [
    "BlobCache",
    "BlobCacheError",
    "ModelPool",
    "RecordDiff",
    "Repository",
    "Workspace",
    "annotations_table",
    "expressions_table",
    "flatten_anchor",
    "materialize",
    "records_to_table",
]
