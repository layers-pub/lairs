"""Unit and integration tests for lairs.data.corpus."""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
import pytest

from lairs.atproto.pds import PdsClient, RecordEnvelope, RecordNotFoundError
from lairs.data import corpus
from lairs.data.corpus import (
    Corpus,
    ExpressionWithAnnotations,
    ExpressionWithMedia,
    ExpressionWithSegmentation,
    load_corpus,
)
from lairs.records._generated.annotation import AnnotationLayer
from lairs.records._generated.corpus import Corpus as CorpusRecord
from lairs.records._generated.corpus import Membership
from lairs.records._generated.expression import Expression
from lairs.records._generated.media import Media
from lairs.records._generated.segmentation import Segmentation
from lairs.store.repository import Repository

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    import didactic.api as dx
    from conftest import PdsServer

_NOW = datetime(2024, 1, 1, tzinfo=UTC)

_AUTH = "did:plc:abc"
_E1 = f"at://{_AUTH}/pub.layers.expression.expression/e1"
_E2 = f"at://{_AUTH}/pub.layers.expression.expression/e2"
_L1 = f"at://{_AUTH}/pub.layers.annotation.annotationLayer/l1"
_L2 = f"at://{_AUTH}/pub.layers.annotation.annotationLayer/l2"
_M1 = f"at://{_AUTH}/pub.layers.media.media/m1"
_S1 = f"at://{_AUTH}/pub.layers.segmentation.segmentation/s1"
_C1 = f"at://{_AUTH}/pub.layers.corpus.corpus/c1"
_C2 = f"at://{_AUTH}/pub.layers.corpus.corpus/c2"
_MEM1 = f"at://{_AUTH}/pub.layers.corpus.membership/mem1"
_MEM2 = f"at://{_AUTH}/pub.layers.corpus.membership/mem2"


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


def _member(
    corpus_uri: str,
    expr_uri: str,
    *,
    split: str | None = None,
    ordinal: int | None = None,
) -> Membership:
    """Build a membership tying an expression to a corpus."""
    return Membership(
        corpusRef=corpus_uri,
        expressionRef=expr_uri,
        createdAt=_NOW,
        split=split,
        ordinal=ordinal,
    )


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
    media = by_uri[_E1].media
    assert media is not None
    assert media.kind == "audio"
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


def test_save_to_repo_round_trips_records(tmp_path: Path) -> None:
    c = _populated()
    repo_path = tmp_path / "repo"
    c.save_to_repo(repo_path)
    # the committed records read back from a freshly opened repository.
    repo = Repository.open(repo_path)
    expr = repo.load(_E1, Expression)
    assert isinstance(expr, Expression)
    assert expr.id == "d1"
    media = repo.load(_M1, Media)
    assert isinstance(media, Media)
    assert media.kind == "audio"


def test_materialize_leaves_no_repo_dir(tmp_path: Path) -> None:
    c = _populated()
    out = tmp_path / "views"
    c.materialize(out)
    # the throwaway repo lives in a temp dir, not the output directory.
    assert not (out / ".repo").exists()


# membership-scoped views ------------------------------------------------------


def _with_memberships() -> Corpus:
    """Build a corpus whose two expressions are bound by membership records."""
    c = Corpus.new(uri=_C1)
    c.add_expression(_E1, _expr("d1"))
    c.add_expression(_E2, _expr("d2"))
    c.add_membership(_MEM1, _member(_C1, _E1, split="train", ordinal=0))
    c.add_membership(_MEM2, _member(_C1, _E2, split="test", ordinal=1))
    return c


def test_expressions_restricted_to_members() -> None:
    c = Corpus.new(uri=_C1)
    c.add_expression(_E1, _expr("d1"))
    c.add_expression(_E2, _expr("d2"))
    # only e1 is a member of this corpus.
    c.add_membership(_MEM1, _member(_C1, _E1))
    assert {record.id for record in c.expressions} == {"d1"}
    assert c.expression_uris() == [_E1]


def test_expressions_ignore_other_corpus_memberships() -> None:
    c = Corpus.new(uri=_C1)
    c.add_expression(_E1, _expr("d1"))
    c.add_expression(_E2, _expr("d2"))
    # e1 belongs to this corpus; e2 belongs to a different corpus on the same
    # authority and must not surface here.
    c.add_membership(_MEM1, _member(_C1, _E1))
    c.add_membership(_MEM2, _member(_C2, _E2))
    assert {record.id for record in c.expressions} == {"d1"}


def test_expressions_unscoped_without_memberships() -> None:
    # a freshly authored corpus with no membership records treats every pooled
    # expression as a member.
    c = _populated()
    assert {record.id for record in c.expressions} == {"d1", "d2"}


def test_joins_respect_membership_scope() -> None:
    c = Corpus.new(uri=_C1)
    c.add_expression(_E1, _expr("d1", media_ref=_M1))
    c.add_expression(_E2, _expr("d2"))
    c.add_record(_M1, Media(kind="audio", createdAt=_NOW))
    c.add_annotation_layer(_L1, _layer(_E2))
    c.add_record(_S1, _seg(_E2))
    c.add_membership(_MEM1, _member(_C1, _E1))
    # only e1 is a member, so each join surfaces e1 alone.
    assert {row.uri for row in c.with_annotations()} == {_E1}
    assert {row.uri for row in c.with_media()} == {_E1}
    assert {row.uri for row in c.with_segmentation()} == {_E1}


def test_memberships_filtered_by_corpus_ref() -> None:
    c = Corpus.new(uri=_C1)
    c.add_membership(_MEM1, _member(_C1, _E1))
    c.add_membership(_MEM2, _member(_C2, _E2))
    members = list(c.memberships())
    assert len(members) == 1
    assert members[0].expressionRef == _E1


def test_corpus_record_accessor() -> None:
    c = Corpus.new(uri=_C1)
    assert c.corpus_record is None
    c.add_record(_C1, CorpusRecord(name="demo", createdAt=_NOW))
    record = c.corpus_record
    assert isinstance(record, CorpusRecord)
    assert record.name == "demo"


def test_corpus_record_is_none_without_uri() -> None:
    c = Corpus.new()
    assert c.corpus_record is None


def test_split_selects_expressions() -> None:
    c = _with_memberships()
    train = list(c.split("train"))
    assert [record.id for record in train] == ["d1"]
    test = list(c.split("test"))
    assert [record.id for record in test] == ["d2"]
    assert list(c.split("dev")) == []


def test_splits_lists_present_slugs() -> None:
    c = _with_memberships()
    assert c.splits() == ("test", "train")


class _FakePds:
    """A fake PDS client returning canned envelopes by collection and AT-URI."""

    def __init__(
        self,
        by_collection: dict[str, list[RecordEnvelope]],
        by_uri: dict[str, RecordEnvelope] | None = None,
    ) -> None:
        self._by = by_collection
        self._by_uri = by_uri if by_uri is not None else {}

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

    def get_record(self, repo: str, collection: str, rkey: str) -> RecordEnvelope:
        """Return the canned envelope for an AT-URI, or raise when absent."""
        uri = f"at://{repo}/{collection}/{rkey}"
        envelope = self._by_uri.get(uri)
        if envelope is None:
            msg = f"no record for {uri}"
            raise RecordNotFoundError(msg)
        return envelope


def _envelope(uri: str, model: dx.Model) -> RecordEnvelope:
    """Build an envelope whose value is the model's JSON form."""
    return RecordEnvelope(uri=uri, cid="cid", value=json.loads(model.model_dump_json()))


def _typed_envelope(uri: str, model: dx.Model, nsid: str) -> RecordEnvelope:
    """Build an envelope whose value carries the wire ``$type``, like a real PDS."""
    value = json.loads(model.model_dump_json())
    value["$type"] = nsid
    return RecordEnvelope(uri=uri, cid="cid", value=value)


# a second account, so refs from the corpus account cross an account boundary.
_XACCT = "did:plc:xyz"
_XE1 = f"at://{_XACCT}/pub.layers.expression.expression/xe1"
_XM1 = f"at://{_XACCT}/pub.layers.media.media/xm1"
_EXPR_NSID = "pub.layers.expression.expression"
_MEDIA_NSID = "pub.layers.media.media"
_CORPUS_NSID = "pub.layers.corpus.corpus"
_MEMBERSHIP_NSID = "pub.layers.corpus.membership"


def test_decode_envelope_strips_dollar_type() -> None:
    # a real PDS record carries a $type the generated model does not declare;
    # the loader must drop it rather than skip the record.
    envelope = _typed_envelope(_E1, _expr("d1"), _EXPR_NSID)
    decoded = corpus._decode_envelope(envelope)
    assert decoded is not None
    assert decoded[1].id == "d1"


def test_collection_of_extracts_nsid() -> None:
    assert corpus._collection_of(_E1) == _EXPR_NSID
    assert corpus._collection_of("at://did") == ""


def test_refs_of_collects_at_uri_fields() -> None:
    assert corpus._refs_of(_member(_C1, _E1, split="train")) == {_C1, _E1}


def test_load_corpus_decodes_records_carrying_dollar_type() -> None:
    fake = _FakePds({_EXPR_NSID: [_typed_envelope(_E1, _expr("d1"), _EXPR_NSID)]})
    loaded = load_corpus(_C1, source="pds", pds_client=fake)  # ty: ignore[invalid-argument-type]
    assert [record.id for record in loaded.expressions] == ["d1"]


def _corpus_account_fake() -> _FakePds:
    """Build a fake whose corpus account references a cross-account expression."""
    return _FakePds(
        by_collection={
            _CORPUS_NSID: [
                _typed_envelope(
                    _C1,
                    CorpusRecord(name="demo", createdAt=_NOW),
                    _CORPUS_NSID,
                ),
            ],
            _MEMBERSHIP_NSID: [
                _typed_envelope(_MEM1, _member(_C1, _XE1), _MEMBERSHIP_NSID),
            ],
        },
        by_uri={_XE1: _typed_envelope(_XE1, _expr("d1"), _EXPR_NSID)},
    )


def test_load_corpus_follows_refs_across_accounts() -> None:
    fake = _corpus_account_fake()
    loaded = load_corpus(_C1, source="pds", pds_client=fake, follow_refs=True)  # ty: ignore[invalid-argument-type]
    assert [record.id for record in loaded.expressions] == ["d1"]


def test_load_corpus_without_follow_refs_keeps_to_own_account() -> None:
    fake = _corpus_account_fake()
    loaded = load_corpus(_C1, source="pds", pds_client=fake, follow_refs=False)  # ty: ignore[invalid-argument-type]
    assert len(loaded.expressions) == 0


def test_load_corpus_follows_refs_transitively() -> None:
    # the cross-account expression itself references a media record in that other
    # account; following refs reaches it two hops from the corpus.
    fake = _FakePds(
        by_collection={
            _MEMBERSHIP_NSID: [
                _typed_envelope(_MEM1, _member(_C1, _XE1), _MEMBERSHIP_NSID),
            ],
        },
        by_uri={
            _XE1: _typed_envelope(_XE1, _expr("d1", media_ref=_XM1), _EXPR_NSID),
            _XM1: _typed_envelope(
                _XM1,
                Media(kind="audio", createdAt=_NOW),
                _MEDIA_NSID,
            ),
        },
    )
    loaded = load_corpus(_C1, source="pds", pds_client=fake, follow_refs=True)  # ty: ignore[invalid-argument-type]
    assert len(loaded.expressions) == 1
    assert len(loaded.media()) == 1


def test_load_corpus_skips_dangling_ref() -> None:
    # the membership references an expression that does not resolve; following
    # refs skips it gracefully rather than raising.
    fake = _FakePds(
        by_collection={
            _MEMBERSHIP_NSID: [
                _typed_envelope(_MEM1, _member(_C1, _XE1), _MEMBERSHIP_NSID),
            ],
        },
    )
    loaded = load_corpus(_C1, source="pds", pds_client=fake, follow_refs=True)  # ty: ignore[invalid-argument-type]
    assert len(loaded.expressions) == 0


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
    loaded = load_corpus(_C1, source="pds", pds_client=fake)  # ty: ignore[invalid-argument-type]
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
    loaded = load_corpus(_C1, source="auto", pds_client=fake)  # ty: ignore[invalid-argument-type]
    assert len(loaded.expressions) == 1


def test_load_corpus_skips_undecodable_records() -> None:
    bad = RecordEnvelope(
        uri=_E1,
        cid="cid",
        value={"kind": "document"},  # missing required id and createdAt
    )
    fake = _FakePds({"pub.layers.expression.expression": [bad]})
    loaded = load_corpus(_C1, source="pds", pds_client=fake)  # ty: ignore[invalid-argument-type]
    assert len(loaded.expressions) == 0


def test_load_corpus_loads_memberships_and_corpus_record() -> None:
    fake = _FakePds(
        {
            "pub.layers.expression.expression": [
                _envelope(_E1, _expr("d1")),
                _envelope(_E2, _expr("d2")),
            ],
            "pub.layers.corpus.corpus": [
                _envelope(_C1, CorpusRecord(name="demo", createdAt=_NOW)),
            ],
            "pub.layers.corpus.membership": [
                _envelope(_MEM1, _member(_C1, _E1, split="train")),
                _envelope(_MEM2, _member(_C2, _E2, split="test")),
            ],
        },
    )
    loaded = load_corpus(_C1, source="pds", pds_client=fake)  # ty: ignore[invalid-argument-type]
    # only e1 is a member of c1; e2's membership points at c2.
    assert {record.id for record in loaded.expressions} == {"d1"}
    assert len(loaded.memberships()) == 1
    assert loaded.corpus_record is not None
    assert loaded.corpus_record.name == "demo"
    assert [record.id for record in loaded.split("train")] == ["d1"]


def test_load_corpus_skips_non_dict_value() -> None:
    bad = RecordEnvelope(uri=_E1, cid="cid", value="not-a-record")
    fake = _FakePds({"pub.layers.expression.expression": [bad]})
    loaded = load_corpus(_C1, source="pds", pds_client=fake)  # ty: ignore[invalid-argument-type]
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
def test_load_corpus_from_pds_live(pds_server: PdsServer) -> None:
    # load a corpus end-to-end from a fresh account, so it is isolated from
    # records other tests write to the shared default account.
    did, jwt = _fresh_account(pds_server)
    uri = _put_live(
        pds_server,
        did,
        jwt,
        "pub.layers.corpus.corpus",
        "c1",
        {
            "$type": "pub.layers.corpus.corpus",
            "name": "live corpus",
            "createdAt": "2026-06-18T00:00:00Z",
            "domain": "biomedical",
        },
    )
    loaded = load_corpus(uri, source="pds", pds_client=PdsClient(pds_server.endpoint))
    assert isinstance(loaded, Corpus)
    # the real PDS record carries a $type; the loader must still decode it.
    assert loaded.corpus_record is not None
    assert loaded.corpus_record.name == "live corpus"
    # the fresh account holds only the corpus record, so no expressions.
    assert len(loaded.expressions) == 0


def _fresh_account(server: PdsServer) -> tuple[str, str]:
    """Create a new empty account on the PDS, returning (did, access_jwt)."""
    token = secrets.token_hex(6)
    response = httpx.post(
        f"{server.endpoint}/xrpc/com.atproto.server.createAccount",
        json={
            "handle": f"xc{token}.test",
            "email": f"xc{token}@example.test",
            "password": secrets.token_hex(12),
        },
        timeout=30.0,
    )
    response.raise_for_status()
    body = response.json()
    return str(body["did"]), str(body["accessJwt"])


def _put_live(  # noqa: PLR0913  (a put needs the repo, auth, and record path)
    server: PdsServer,
    did: str,
    jwt: str,
    collection: str,
    rkey: str,
    record: dict[str, str],
) -> str:
    """Upsert a record on the PDS and return its AT-URI."""
    httpx.post(
        f"{server.endpoint}/xrpc/com.atproto.repo.putRecord",
        headers={"Authorization": f"Bearer {jwt}"},
        json={"repo": did, "collection": collection, "rkey": rkey, "record": record},
        timeout=30.0,
    ).raise_for_status()
    return f"at://{did}/{collection}/{rkey}"


@pytest.mark.integration
def test_load_corpus_follows_refs_across_accounts_live(pds_server: PdsServer) -> None:
    # publish an expression to a second account, then a corpus and a membership
    # on the default account that references it; following refs across the
    # account boundary pulls the expression in, and disabling it does not.
    expr_did, expr_jwt = _fresh_account(pds_server)
    expr_uri = _put_live(
        pds_server,
        expr_did,
        expr_jwt,
        "pub.layers.expression.expression",
        "xe1",
        {
            "$type": "pub.layers.expression.expression",
            "id": "88888888-8888-8888-8888-888888888888",
            "kind": "sentence",
            "text": "cross-account text",
            "createdAt": "2026-06-18T00:00:00Z",
        },
    )
    corpus_uri = _put_live(
        pds_server,
        pds_server.did,
        pds_server.access_jwt,
        "pub.layers.corpus.corpus",
        "xcc",
        {
            "$type": "pub.layers.corpus.corpus",
            "name": "cross-account corpus",
            "createdAt": "2026-06-18T00:00:00Z",
        },
    )
    _put_live(
        pds_server,
        pds_server.did,
        pds_server.access_jwt,
        "pub.layers.corpus.membership",
        "xcm",
        {
            "$type": "pub.layers.corpus.membership",
            "corpusRef": corpus_uri,
            "expressionRef": expr_uri,
            "createdAt": "2026-06-18T00:00:00Z",
        },
    )
    with PdsClient(pds_server.endpoint) as client:
        followed = load_corpus(
            corpus_uri,
            source="pds",
            pds_client=client,
            follow_refs=True,
        )
        assert [record.text for record in followed.expressions] == [
            "cross-account text",
        ]
        local_only = load_corpus(
            corpus_uri,
            source="pds",
            pds_client=client,
            follow_refs=False,
        )
        assert len(local_only.expressions) == 0
