"""Unit tests for lairs.store.pool."""

from __future__ import annotations

import didactic.api as dx

from lairs.store import pool


class _Expression(dx.Model):
    """A throwaway expression-like record for pool tests."""

    text: str
    parent: str | None = None


class _Layer(dx.Model):
    """A throwaway layer-like record holding nested references."""

    name: str
    targets: tuple[str, ...] = dx.field(default_factory=tuple)


_PARENT_URI = "at://did:plc:abc/pub.layers.expression.expression/parent"
_CHILD_URI = "at://did:plc:abc/pub.layers.expression.expression/child"
_LAYER_URI = "at://did:plc:abc/pub.layers.annotation.annotationLayer/layer"


def _populated_pool() -> pool.ModelPool:
    p = pool.ModelPool()
    p.add(_PARENT_URI, _Expression(text="parent"))
    p.add(_CHILD_URI, _Expression(text="child", parent=_PARENT_URI))
    p.add(_LAYER_URI, _Layer(name="pos", targets=(_PARENT_URI, _CHILD_URI)))
    return p


def test_exports() -> None:
    assert set(pool.__all__) == {"ModelPool"}


def test_add_indexes_by_uri() -> None:
    p = pool.ModelPool()
    expr = _Expression(text="hello")
    p.add(_CHILD_URI, expr)
    assert _CHILD_URI in p
    assert len(p) == 1
    assert p.get(_CHILD_URI) is expr
    assert p.uris() == [_CHILD_URI]
    assert p.models() == [expr]


def test_add_same_uri_replaces() -> None:
    p = pool.ModelPool()
    first = _Expression(text="first")
    second = _Expression(text="second")
    p.add(_CHILD_URI, first)
    p.add(_CHILD_URI, second)
    assert len(p) == 1
    assert p.get(_CHILD_URI) is second


def test_resolve_returns_target_model() -> None:
    p = _populated_pool()
    resolved = p.resolve(_PARENT_URI)
    assert isinstance(resolved, _Expression)
    assert resolved.text == "parent"


def test_resolve_degrades_gracefully_on_absent_target() -> None:
    p = _populated_pool()
    assert (
        p.resolve("at://did:plc:abc/pub.layers.expression.expression/missing") is None
    )


def test_refs_of_walks_scalar_and_nested_fields() -> None:
    p = _populated_pool()
    assert p.refs_of(_CHILD_URI) == [_PARENT_URI]
    assert p.refs_of(_LAYER_URI) == [_PARENT_URI, _CHILD_URI]


def test_refs_of_absent_record_is_empty() -> None:
    p = _populated_pool()
    assert p.refs_of("at://did:plc:abc/pub.layers.expression.expression/nope") == []


def test_backrefs_finds_referring_models() -> None:
    p = _populated_pool()
    referrers = p.backrefs(_PARENT_URI)
    texts = {getattr(m, "text", None) for m in referrers if isinstance(m, _Expression)}
    names = {getattr(m, "name", None) for m in referrers if isinstance(m, _Layer)}
    assert texts == {"child"}
    assert names == {"pos"}
    assert len(referrers) == 2


def test_backref_uris_lists_referring_uris() -> None:
    p = _populated_pool()
    assert p.backref_uris(_PARENT_URI) == [_CHILD_URI, _LAYER_URI]


def test_backrefs_work_for_absent_target() -> None:
    # a target not itself loaded still resolves inbound references.
    p = pool.ModelPool()
    p.add(_CHILD_URI, _Expression(text="child", parent=_PARENT_URI))
    assert p.backref_uris(_PARENT_URI) == [_CHILD_URI]


def test_record_does_not_reference_itself() -> None:
    p = pool.ModelPool()
    p.add(_CHILD_URI, _Expression(text="self", parent=_CHILD_URI))
    assert p.refs_of(_CHILD_URI) == []
    assert p.backref_uris(_CHILD_URI) == []
