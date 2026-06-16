"""Unit tests for lairs._codegen.pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from lairs._codegen import pipeline


def test_exports() -> None:
    assert set(pipeline.__all__) == {"check", "generate"}


def test_generate_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        pipeline.generate(Path("lexicons"), Path("out"))


def test_check_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        pipeline.check(Path("lexicons"), Path("out"))
