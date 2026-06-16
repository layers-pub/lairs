"""Unit tests for lairs._types."""

from __future__ import annotations

import lairs._types as t


def test_exports() -> None:
    assert set(t.__all__) == {"JsonValue", "T", "T_co", "T_contra"}


def test_jsonvalue_accepts_scalars_and_containers() -> None:
    # JsonValue is a type alias; exercise representative shapes at runtime.
    value: t.JsonValue = {"a": [1, 2.0, "x", True, None], "b": {"c": 1}}
    assert value["a"][0] == 1
    assert value["b"]["c"] == 1


def test_typevars_are_distinct() -> None:
    assert t.T is not t.T_co
    assert t.T_co is not t.T_contra
    assert t.T_co.__covariant__ is True
    assert t.T_contra.__contravariant__ is True
