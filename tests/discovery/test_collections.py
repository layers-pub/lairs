"""Unit tests for lairs.discovery.collections."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from lairs.atproto.appview import AppviewClient
from lairs.atproto.pds import RecordEnvelope
from lairs.discovery.collections import list_collections
from lairs.discovery.models import CollectionFilter

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from lairs._types import JsonValue

_DID = "did:plc:x"
_COLLECTION_NSID = "pub.layers.catalog.collection"
_URI = f"at://{_DID}/{_COLLECTION_NSID}/a"


def _collection_value(
    *,
    name: str = "UD English-EWT",
    kind: str = "treebank",
    parent_ref: str | None = None,
) -> dict[str, JsonValue]:
    value: dict[str, JsonValue] = {
        "$type": _COLLECTION_NSID,
        "name": name,
        "kind": kind,
        "createdAt": "2026-06-18T00:00:00Z",
        "languages": ["en"],
    }
    if parent_ref is not None:
        value["parentRef"] = parent_ref
    return value


class _FakePds:
    """A fake PDS returning canned collection envelopes."""

    def __init__(self, envelopes: list[RecordEnvelope]) -> None:
        self._envelopes = envelopes

    def list_records(
        self,
        repo: str,
        collection: str,
        *,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Iterator[RecordEnvelope]:
        _ = (repo, limit, cursor)
        if collection == _COLLECTION_NSID:
            yield from self._envelopes

    def close(self) -> None:  # satisfies the client protocol the caller may close
        return


def _appview(handler: Callable[[httpx.Request], httpx.Response]) -> AppviewClient:
    return AppviewClient(
        "https://appview.example",
        httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_list_collections_pds_path() -> None:
    fake = _FakePds([RecordEnvelope(uri=_URI, cid="bafy", value=_collection_value())])
    rows = list_collections(_DID, source="pds", pds_client=fake)  # ty: ignore[invalid-argument-type]
    assert len(rows) == 1
    assert rows[0].name == "UD English-EWT"
    assert rows[0].kind == "treebank"
    assert rows[0].did == _DID


def test_list_collections_appview_path_pushes_facets() -> None:
    seen: dict[str, str | None] = {}

    parent = "at://did:plc:x/pub.layers.catalog.collection/parent"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/xrpc/pub.layers.catalog.listCollections"
        seen["repo"] = request.url.params.get("repo")
        seen["parentRef"] = request.url.params.get("parentRef")
        value = _collection_value(parent_ref=parent)
        return httpx.Response(
            200,
            json={"records": [{"uri": _URI, "cid": "bafy", "value": value}]},
        )

    with _appview(handler) as client:
        rows = list_collections(
            _DID,
            source="appview",
            filters=CollectionFilter(parent_ref=parent),
            appview_client=client,
        )
    assert seen == {"repo": _DID, "parentRef": parent}
    assert len(rows) == 1


def test_list_collections_client_side_filter_excludes() -> None:
    fake = _FakePds(
        [
            RecordEnvelope(
                uri=_URI,
                cid="bafy",
                value=_collection_value(kind="treebank"),
            ),
            RecordEnvelope(
                uri=f"at://{_DID}/{_COLLECTION_NSID}/b",
                cid="bafy2",
                value=_collection_value(name="A Lexicon", kind="lexicon"),
            ),
        ],
    )
    rows = list_collections(
        _DID,
        source="pds",
        filters=CollectionFilter(kind=("lexicon",)),
        pds_client=fake,  # ty: ignore[invalid-argument-type]
    )
    assert [row.name for row in rows] == ["A Lexicon"]


def test_list_collections_unknown_source_raises() -> None:
    with pytest.raises(ValueError, match="unknown source"):
        list_collections(_DID, source="bogus")
