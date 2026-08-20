"""Unit tests for lairs.data.collection."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from lairs.atproto.appview import AppviewClient
from lairs.atproto.pds import RecordEnvelope, RecordNotFoundError
from lairs.data import collection as collection_mod
from lairs.data.collection import Collection, load_collection
from lairs.records._generated.catalog import (
    Citation,
    ContentSummary,
    MemberRef,
    Membership,
)
from lairs.records._generated.catalog import (
    Collection as CollectionRecord,
)
from lairs.records._generated.defs import ObjectRef

if TYPE_CHECKING:
    from collections.abc import Iterator

    import didactic.api as dx
    import httpx

_NOW = datetime(2024, 1, 1, tzinfo=UTC)

_ROOT = "did:plc:root"
_CHILD = "did:plc:child"
_C_ROOT = f"at://{_ROOT}/pub.layers.catalog.collection/root"
_C_CHILD = f"at://{_CHILD}/pub.layers.catalog.collection/child"
_MEM_MEMBER = f"at://{_ROOT}/pub.layers.catalog.membership/m1"
_MEM_PRODUCE = f"at://{_CHILD}/pub.layers.catalog.membership/p1"
_CORPUS = "at://did:plc:corpusacct/pub.layers.corpus.corpus/c1"

_COLLECTION_NSID = "pub.layers.catalog.collection"
_MEMBERSHIP_NSID = "pub.layers.catalog.membership"


def _root_collection() -> CollectionRecord:
    return CollectionRecord(
        name="Universal Dependencies",
        kind="project",
        createdAt=_NOW,
        citation=Citation(creditPolicy="cite-children"),
        contents=(
            ContentSummary(
                produceCollection="pub.layers.expression.expression",
                count=16622,
                countSource="computed",
                unit="expression",
            ),
        ),
    )


def _child_collection() -> CollectionRecord:
    return CollectionRecord(
        name="UD English-EWT",
        kind="treebank",
        createdAt=_NOW,
        parentRef=_C_ROOT,
        rootRef=_C_ROOT,
        depth=1,
        citation=Citation(creditPolicy="cite-self"),
    )


def _member_edge() -> Membership:
    return Membership(
        catalogRef=_C_ROOT,
        createdAt=_NOW,
        member=MemberRef(
            ref=ObjectRef(recordRef=_C_CHILD),
            memberType=_COLLECTION_NSID,
        ),
        role="member",
    )


def _produce_edge() -> Membership:
    return Membership(
        catalogRef=_C_CHILD,
        createdAt=_NOW,
        member=MemberRef(
            ref=ObjectRef(recordRef=_CORPUS),
            memberType="pub.layers.corpus.corpus",
        ),
        role="produce",
    )


def _envelope(uri: str, model: dx.Model) -> RecordEnvelope:
    value = json.loads(model.model_dump_json())
    value["$type"] = uri.split("/")[-2]
    return RecordEnvelope(uri=uri, cid="cid", value=value)


class _FakePds:
    """A fake PDS returning canned envelopes by collection and AT-URI."""

    def __init__(
        self,
        by_collection: dict[str, list[RecordEnvelope]],
        by_uri: dict[str, RecordEnvelope] | None = None,
    ) -> None:
        self._by = by_collection
        self._by_uri = by_uri if by_uri is not None else {}
        self.fetched: list[str] = []

    def list_records(
        self,
        repo: str,
        collection: str,
        *,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Iterator[RecordEnvelope]:
        _ = (repo, limit, cursor)
        yield from self._by.get(collection, [])

    def get_record(self, repo: str, collection: str, rkey: str) -> RecordEnvelope:
        uri = f"at://{repo}/{collection}/{rkey}"
        self.fetched.append(uri)
        envelope = self._by_uri.get(uri)
        if envelope is None:
            msg = f"no record for {uri}"
            raise RecordNotFoundError(msg)
        return envelope


def _root_authority_fake() -> _FakePds:
    """Build a root account with the root collection and a cross-account edge."""
    return _FakePds(
        by_collection={
            _COLLECTION_NSID: [_envelope(_C_ROOT, _root_collection())],
            _MEMBERSHIP_NSID: [_envelope(_MEM_MEMBER, _member_edge())],
        },
        by_uri={_C_CHILD: _envelope(_C_CHILD, _child_collection())},
    )


def test_empty_collection_surface_has_no_children() -> None:
    surface = Collection.new(uri=_C_ROOT)
    assert len(surface.children()) == 0
    assert surface.collection_record is None
    assert surface.citation is None


def test_load_collection_follows_member_edge_across_accounts() -> None:
    fake = _root_authority_fake()
    loaded = load_collection(_C_ROOT, source="pds", pds_client=fake)  # ty: ignore[invalid-argument-type]
    record = loaded.collection_record
    assert record is not None
    assert record.name == "Universal Dependencies"
    # the child lives in a different account, reached by following the member edge.
    assert fake.fetched == [_C_CHILD]
    children = list(loaded.children())
    assert [child.name for child in children] == ["UD English-EWT"]
    assert [child.name for child in loaded.subtree()] == ["UD English-EWT"]


def test_load_collection_splits_member_and_produce_edges() -> None:
    # root holds a member edge; child holds a produce edge. Both are in one account
    # here so the surface pooled from either uri sees the relevant edges.
    fake = _FakePds(
        by_collection={
            _COLLECTION_NSID: [
                _envelope(_C_ROOT, _root_collection()),
                _envelope(_C_CHILD, _child_collection()),
            ],
            _MEMBERSHIP_NSID: [
                _envelope(_MEM_MEMBER, _member_edge()),
                _envelope(_MEM_PRODUCE, _produce_edge()),
            ],
        },
    )
    root = load_collection(_C_ROOT, source="pds", pds_client=fake)  # ty: ignore[invalid-argument-type]
    # the root's edges: one member edge, no produce edge (the produce edge's
    # catalogRef points at the child).
    assert [edge.role for edge in root.memberships()] == ["member"]
    assert len(root.members()) == 1
    assert len(root.produces()) == 0

    child = load_collection(_C_CHILD, source="pds", pds_client=fake)  # ty: ignore[invalid-argument-type]
    produces = list(child.produces())
    assert len(produces) == 1
    assert produces[0].member.memberType == "pub.layers.corpus.corpus"
    assert produces[0].member.ref.recordRef == _CORPUS


def test_load_collection_projects_contents_and_citation() -> None:
    fake = _root_authority_fake()
    loaded = load_collection(_C_ROOT, source="pds", pds_client=fake)  # ty: ignore[invalid-argument-type]
    contents = loaded.contents()
    assert len(contents) == 1
    assert contents[0].produceCollection == "pub.layers.expression.expression"
    assert contents[0].count == 16622
    citation = loaded.citation
    assert citation is not None
    assert citation.creditPolicy == "cite-children"


def test_load_collection_appview_path() -> None:
    import httpx  # noqa: PLC0415  (local import keeps the httpx dependency test-scoped)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/xrpc/pub.layers.catalog.getCollection":
            return httpx.Response(
                200,
                json={
                    "uri": _C_ROOT,
                    "cid": "bafy",
                    "value": json.loads(_root_collection().model_dump_json()),
                    "children": [
                        {
                            "uri": _C_CHILD,
                            "cid": "bafy2",
                            "value": json.loads(_child_collection().model_dump_json()),
                        },
                    ],
                },
            )
        if path == "/xrpc/pub.layers.catalog.listMembers":
            return httpx.Response(
                200,
                json={
                    "records": [
                        {
                            "uri": _MEM_MEMBER,
                            "cid": "bafy3",
                            "value": json.loads(_member_edge().model_dump_json()),
                        },
                    ],
                },
            )
        return httpx.Response(404, json={})

    client = AppviewClient(
        "https://appview.example",
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with client:
        loaded = load_collection(_C_ROOT, source="appview", appview_client=client)
    assert loaded.collection_record is not None
    assert [child.name for child in loaded.children()] == ["UD English-EWT"]
    assert [edge.role for edge in loaded.memberships()] == ["member"]


def test_load_collection_rejects_unknown_source() -> None:
    with pytest.raises(ValueError, match="unknown collection source"):
        load_collection(_C_ROOT, source="bogus")


def test_load_collection_without_client_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        load_collection(_C_ROOT, source="auto")


def test_load_collection_appview_requires_client() -> None:
    with pytest.raises(NotImplementedError):
        load_collection(_C_ROOT, source="appview")


def test_exports() -> None:
    assert set(collection_mod.__all__) == {"Collection", "load_collection"}
