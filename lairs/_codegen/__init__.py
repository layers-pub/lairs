"""Codegen pipeline that turns vendored lexicons into generated models.

The pipeline parses each lexicon into a panproto ``Schema``, walks it into
didactic spec dicts, builds models, and emits Python module text.
"""

from __future__ import annotations

__all__: list[str] = []
