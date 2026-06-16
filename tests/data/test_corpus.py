"""Unit and integration tests for lairs.data.corpus."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from lairs.atproto.pds import RecordEnvelope
from lairs.data import corpus
from lairs.data.corpus import (
    Corpus,
    ExpressionWithAnnotations,
    ExpressionWithMedia,
    ExpressionWithSegmentation,
    load_corpus,
)
from lairs.records._generated.annotation import AnnotationLayer
from lairs.records._generated.expression import Expression
from lairs.records._generated.media import Media
from lairs.records._generated.segmentation import Segmentation

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    import didactic.api as dx

_NOW = datetime(2024, 1, 1, tzinfo=UTC)

_AUTH = "did:plc:abc"
_E1 = f"at://{_AUTH}/pub.layers.expression.expression/e1"
_E2 = f"at://{_AUTH}/pub.layers.expression.expression/e2"
_L1 = f"at://{_AUTH}/pub.layers.annotation.annotationLayer/l1"
_L2 = f"at://{_AUTH}/pub.layers.annotation.annotationLayer/l2"
_M1 = f"at://{_AUTH}/pub.layers.media.media/m1"
_S1 = f"at://{_AUTH}/pub.layers.segmentation.segmentation/s1"
_C1 = f"at://{_AUTH}/pub.layers.corpus.corpus/c1"


def _expr(doc_id: str, *, media_ref: str | None = None) -> Expression:
    """Build a minimal expression record."""
    return Expression(
        id=doc_id,
        kind="document",
        createdAt=_NOW,
        text=doc_id,
        mediaRef=media_ref,
    )


def _layer(
    expr_uri: str, *, kind: str = "token-tag", subkind: str | None = None
) -> AnnotationLayer:
    """Build a minimal annotation layer targeting an expression."""
    return AnnotationLayer(
        kind=kind,
        subkind=subkind,
        expression=expr_uri,
        createdAt=_NOW,
        annotations=(),
    )


def _seg(expr_uri: str) -> Segmentation:
    """Build a minimal segmentation targeting an expression."""
    return Segmentation(expression=expr_uri, createdAt=_NOW, tokenizations=())


def _populated() -> Corpus:
    """Build a corpus with two expressions and a graph of related records."""
    c = Corpus.new(uri=_C1)
    c.add_expression(_E1, _expr("d1", media_ref=_M1))
    c.add_expression(_E2, _expr("d2"))
    c.add_annotation_layer(_L1, _layer(_E1, subkind="pos"))
    c.add_annotation_layer(_L2, _layer(_E1, subkind="ner"))
    c.add_record(_M1, Media(kind="audio", createdAt=_NOW))
    c.add_record(_S1, _seg(_E1))
    return c


def test_exports() -> None:
    assert set(corpus.__all__) == {
        "Corpus",
        "ExpressionWithAnnotations",
        "ExpressionWithMedia",
        "ExpressionWithSegmentation",
        "load_corpus",
    }


def test_empty_corpus_has_no_expressions() -> None:
    assert len(Corpus.new().expressions) == 0


def test_expressions_dataset() -> None:
    c = _populated()
    ds = c.expressions
    assert len(ds) == 2
    assert {record.id for record in ds} == {"d1", "d2"}
    assert "id" in ds.features.names()


def test_expression_uris() -> None:
    c = _populated()
    assert set(c.expression_uris()) == {_E1, _E2}


def test_annotation_layers_unfiltered() -> None:
    c = _populated()
    assert len(c.annotation_layers()) == 2


def test_annotation_layers_filtered_by_subkind() -> None:
    c = _populated()
    pos = list(c.annotation_layers(subkind="pos"))
    assert len(pos) == 1
    assert pos[0].subkind == "pos"
    assert len(c.annotation_layers(subkind="missing")) == 0


def test_annotation_layers_filtered_by_kind() -> None:
    c = _populated()
    assert len(c.annotation_layers(kind="token-tag")) == 2
    assert len(c.annotation_layers(kind="other")) == 0


def test_with_annotations_groups_per_expression() -> None:
    c = _populated()
    rows = list(c.with_annotations())
    assert all(isinstance(row, ExpressionWithAnnotations) for row in rows)
    by_uri = {row.uri: row for row in rows}
    assert len(by_uri[_E1].annotation_layers) == 2
    # an expression with no layers still appears, with an empty group.
    assert by_uri[_E2].annotation_layers == ()


def test_with_media_resolves_ref() -> None:
    c = _populated()
    rows = list(c.with_media())
    assert all(isinstance(row, ExpressionWithMedia) for row in rows)
    by_uri = {row.uri: row for row in rows}
    assert by_uri[_E1].media is not None
    assert by_uri[_E1].media.kind == "audio"
    # an expression without a media ref resolves to None.
    assert by_uri[_E2].media is None


def test_with_media_missing_target_is_none() -> None:
    c = Corpus.new()
    c.add_expression(_E1, _expr("d1", media_ref=_M1))
    rows = list(c.with_media())
    assert rows[0].media is None


def test_with_segmentation_groups_per_expression() -> None:
    c = _populated()
    rows = list(c.with_segmentation())
    assert all(isinstance(row, ExpressionWithSegmentation) for row in rows)
    by_uri = {row.uri: row for row in rows}
    assert len(by_uri[_E1].segmentations) == 1
    assert by_uri[_E2].segmentations == ()


def test_segmentations_and_media_datasets() -> None:
    c = _populated()
    assert len(c.segmentations()) == 1
    assert len(c.media()) == 1


def test_materialize_writes_views(tmp_path: Path) -> None:
    c = _populated()
    out = tmp_path / "views"
    written = c.materialize(out)
    names = {path.name for path in written}
    assert names == {"expressions.parquet", "annotations.parquet"}
    assert all(path.exists() for path in written)


def test_save_to_repo_commits(tmp_path: Path) -> None:
    c = _populated()
    rev = c.save_to_repo(tmp_path / "repo")
    assert isinstance(rev, str)
    assert rev != ""


class _FakePds:
    """A fake PDS client returning canned envelopes per collection."""

    def __init__(self, by_collection: dict[str, list[RecordEnvelope]]) -> None:
        self._by = by_collection

    def list_records(
        self,
        repo: str,
        collection: str,
        *,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Iterator[RecordEnvelope]:
        """Yield the canned envelopes for a collection."""
        _ = (repo, limit, cursor)
        yield from self._by.get(collection, [])


def _envelope(uri: str, model: dx.Model) -> RecordEnvelope:
    """Build an envelope whose value is the model's JSON form."""
    return RecordEnvelope(uri=uri, cid="cid", value=json.loads(model.model_dump_json()))


def test_load_corpus_from_pds_dispatch() -> None:
    fake = _FakePds(
        {
            "pub.layers.expression.expression": [
                _envelope(_E1, _expr("d1", media_ref=_M1)),
            ],
            "pub.layers.annotation.annotationLayer": [
                _envelope(_L1, _layer(_E1, subkind="pos")),
            ],
            "pub.layers.media.media": [
                _envelope(_M1, Media(kind="audio", createdAt=_NOW)),
            ],
        },
    )
    loaded = load_corpus(_C1, source="pds", pds_client=fake)  # type: ignore[arg-type]
    assert len(loaded.expressions) == 1
    assert loaded.expressions[0].id == "d1"
    assert len(loaded.annotation_layers()) == 1
    assert len(loaded.media()) == 1
    rows = list(loaded.with_media())
    assert rows[0].media is not None


def test_load_corpus_auto_uses_pds_client() -> None:
    fake = _FakePds(
        {
            "pub.layers.expression.expression": [_envelope(_E1, _expr("d1"))],
        },
    )
    loaded = load_corpus(_C1, source="auto", pds_client=fake)  # type: ignore[arg-type]
    assert len(loaded.expressions) == 1


def test_load_corpus_skips_undecodable_records() -> None:
    bad = RecordEnvelope(
        uri=_E1,
        cid="cid",
        value={"kind": "document"},  # missing required id and createdAt
    )
    fake = _FakePds({"pub.layers.expression.expression": [bad]})
    loaded = load_corpus(_C1, source="pds", pds_client=fake)  # type: ignore[arg-type]
    assert len(loaded.expressions) == 0


def test_load_corpus_rejects_unknown_source() -> None:
    with pytest.raises(ValueError, match="unknown corpus source"):
        load_corpus(_C1, source="bogus")


def test_load_corpus_appview_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        load_corpus(_C1, source="appview")


def test_load_corpus_without_client_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        load_corpus(_C1, source="auto")


@pytest.mark.integration
def test_load_corpus_live() -> None:
    # exercises a real corpus load when opted in; skips otherwise.
    try:
        load_corpus(_C1, source="auto")
    except NotImplementedError:
        pytest.skip("live corpus loading needs a real pds endpoint")
