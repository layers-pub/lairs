"""Unit tests for lairs._codegen.emit."""

from __future__ import annotations

import pytest

from lairs._codegen import emit


def test_exports() -> None:
    assert set(emit.__all__) == {"emit_module"}


def test_emit_module_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        emit.emit_module([], manifest_hash="deadbeef")
