"""Generated record models and generated-safe view helpers.

The generated ``dx.Model`` modules live under :mod:`lairs.records._generated`.
This package re-exports the public model surface together with hand-written
behaviour over those models (for example :class:`~lairs.records.blobref.BlobRef`
and the view helpers).
"""

from __future__ import annotations

from lairs.records.blobref import BlobRef

__all__ = ["BlobRef"]
