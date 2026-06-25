"""Unit and integration tests for lairs.author.publish."""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
import libipld
import pytest
from multiformats import CID, multihash

from lairs.atproto.pds import PdsClient, decode
from lairs.author import publish
from lairs.records._generated.expression import Expression
from lairs.records._generated.media import Media
from lairs.records.blobref import BlobRef
from lairs.store.repository import Repository

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from conftest import PdsServer


def _mock_client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    """Return an httpx client backed by a mock transport."""
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_exports() -> None:
    assert set(publish.__all__) == {
        "PublishPlan",
        "WriteClient",
        "WriteOp",
        "WriteResult",
        "apply_writes",
        "collection_of",
        "order_writes",
        "publish",
        "pull",
    }


# helpers ------------------------------------------------------------------


def test_collection_of_extracts_nsid() -> None:
    uri = "at://did:plc:abc/pub.layers.media.media/m1"
    assert publish.collection_of(uri) == "pub.layers.media.media"


def test_collection_of_handles_short_uri() -> None:
    assert publish.collection_of("at://did:plc:abc") == ""


def test_content_address_changes_with_bytes() -> None:
    assert publish.content_address(b"a") != publish.content_address(b"b")


# dependency ordering ------------------------------------------------------


def _op(collection: str, rkey: str) -> publish.WriteOp:
    return publish.WriteOp(
        action="create",
        collection=collection,
        rkey=rkey,
        uri=f"at://did/{collection}/{rkey}",
    )


def test_order_writes_publishes_targets_before_referrers() -> None:
    ordered = publish.order_writes(
        [
            _op("pub.layers.annotation.annotationLayer", "a"),
            _op("pub.layers.segmentation.segmentation", "s"),
            _op("pub.layers.expression.expression", "e"),
            _op("pub.layers.media.media", "m"),
        ],
    )
    collections = [op.collection for op in ordered]
    assert collections == [
        "pub.layers.media.media",
        "pub.layers.expression.expression",
        "pub.layers.segmentation.segmentation",
        "pub.layers.annotation.annotationLayer",
    ]


def test_plan_ordered_writes_deletes_referrers_first() -> None:
    plan = publish.PublishPlan(
        repo="did:plc:me",
        revision="r",
        creates=(_op("pub.layers.expression.expression", "e"),),
        deletes=(
            publish.WriteOp(
                action="delete",
                collection="pub.layers.media.media",
                rkey="m",
                uri="at://did/pub.layers.media.media/m",
            ),
            publish.WriteOp(
                action="delete",
                collection="pub.layers.annotation.annotationLayer",
                rkey="a",
                uri="at://did/pub.layers.annotation.annotationLayer/a",
            ),
        ),
    )
    actions = [(op.action, op.collection) for op in plan.ordered_writes()]
    # deletes come first, referrer (annotationLayer) before target (media).
    assert actions[0] == ("delete", "pub.layers.annotation.annotationLayer")
    assert actions[1] == ("delete", "pub.layers.media.media")
    assert actions[2] == ("create", "pub.layers.expression.expression")


def test_empty_plan_reports_empty() -> None:
    assert publish.PublishPlan(repo="d", revision="r").is_empty()
    assert not publish.PublishPlan(
        repo="d",
        revision="r",
        creates=(_op("pub.layers.media.media", "m"),),
    ).is_empty()


# write client -------------------------------------------------------------


def test_upload_blob_returns_pds_blob_and_is_idempotent() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(
            200,
            json={"blob": {"$type": "blob", "ref": {"$link": "cidX"}}},
        )

    with publish.WriteClient(
        "https://pds.example",
        "did:plc:me",
        _mock_client(handler),
    ) as client:
        first = client.upload_blob(b"audio-bytes", "audio/wav")
        second = client.upload_blob(b"audio-bytes", "audio/wav")

    assert first == second
    # the same bytes upload once; the second call reuses the cached reference.
    assert sum(1 for path in calls if path.endswith("uploadBlob")) == 1


def test_upload_blob_raises_when_response_lacks_blob() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        # a 200 response with no usable 'blob' object must not be cached or
        # returned as a (None) reference.
        return httpx.Response(200, json={"ok": True})

    with (
        publish.WriteClient(
            "https://pds.example",
            "did:plc:me",
            _mock_client(handler),
        ) as client,
        pytest.raises(publish.WriteError),
    ):
        client.upload_blob(b"audio-bytes", "audio/wav")


def test_upload_blob_enforces_size_cap() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"blob": {}})

    with publish.WriteClient(
        "https://pds.example",
        "did:plc:me",
        _mock_client(handler),
    ) as client:
        oversized = b"\x00" * (publish.MAX_BLOB_SIZE + 1)
        with pytest.raises(publish.WriteError):
            client.upload_blob(oversized, "video/mp4")


def test_create_record_reports_created() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "uri": f"at://did:plc:me/{body['collection']}/auto",
                "cid": "cid1",
            },
        )

    with publish.WriteClient(
        "https://pds.example",
        "did:plc:me",
        _mock_client(handler),
    ) as client:
        result = client.create_record("pub.layers.media.media", {"kind": "audio"})

    assert result.status == "created"
    assert result.cid == "cid1"
    assert result.uri.endswith("/auto")


def test_put_record_upserts_at_rkey() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen["rkey"] = body["rkey"]
        return httpx.Response(
            200,
            json={
                "uri": f"at://did:plc:me/{body['collection']}/{body['rkey']}",
                "cid": "cid2",
            },
        )

    with publish.WriteClient(
        "https://pds.example",
        "did:plc:me",
        _mock_client(handler),
    ) as client:
        result = client.put_record(
            "pub.layers.expression.expression",
            "rk1",
            {"id": "x", "kind": "sentence"},
        )

    assert seen["rkey"] == "rk1"
    assert result.status == "updated"


def test_delete_record_reports_deleted() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    with publish.WriteClient(
        "https://pds.example",
        "did:plc:me",
        _mock_client(handler),
    ) as client:
        result = client.delete_record("pub.layers.media.media", "m1")

    assert result.status == "deleted"
    assert result.uri == "at://did:plc:me/pub.layers.media.media/m1"


def test_apply_writes_orders_and_reports_each_record() -> None:
    sent: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sent.append([op["collection"] for op in body["writes"]])
        return httpx.Response(200, json={"results": []})

    ops = [
        publish.WriteOp(
            action="create",
            collection="pub.layers.annotation.annotationLayer",
            rkey="a",
            uri="at://did:plc:me/pub.layers.annotation.annotationLayer/a",
            value={"kind": "token-tag"},
        ),
        publish.WriteOp(
            action="create",
            collection="pub.layers.expression.expression",
            rkey="e",
            uri="at://did:plc:me/pub.layers.expression.expression/e",
            value={"id": "x", "kind": "sentence"},
        ),
    ]
    with publish.WriteClient(
        "https://pds.example",
        "did:plc:me",
        _mock_client(handler),
    ) as client:
        results = client.apply_writes(ops)

    # one result per input write, expression ordered before the annotation.
    assert len(results) == 2
    assert sent[0][0] == "pub.layers.expression.expression"
    assert {r.status for r in results} == {"created"}


def test_apply_writes_chunks_large_batches() -> None:
    chunk_sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        chunk_sizes.append(len(body["writes"]))
        return httpx.Response(200, json={"results": []})

    ops = [
        publish.WriteOp(
            action="create",
            collection="pub.layers.expression.expression",
            rkey=f"e{i}",
            uri=f"at://did:plc:me/pub.layers.expression.expression/e{i}",
            value={"id": str(i), "kind": "sentence"},
        )
        for i in range(publish.APPLY_WRITES_CHUNK + 5)
    ]
    with publish.WriteClient(
        "https://pds.example",
        "did:plc:me",
        _mock_client(handler),
    ) as client:
        results = client.apply_writes(ops)

    assert len(results) == publish.APPLY_WRITES_CHUNK + 5
    assert chunk_sizes == [publish.APPLY_WRITES_CHUNK, 5]


def test_apply_writes_retries_per_record_on_batch_failure() -> None:
    calls = {"apply": 0, "put": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("applyWrites"):
            calls["apply"] += 1
            return httpx.Response(500, json={"error": "boom"})
        if path.endswith("putRecord"):
            calls["put"] += 1
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "uri": f"at://did:plc:me/{body['collection']}/{body['rkey']}",
                    "cid": "retry-cid",
                },
            )
        return httpx.Response(404)

    ops = [
        publish.WriteOp(
            action="create",
            collection="pub.layers.media.media",
            rkey="m",
            uri="at://did:plc:me/pub.layers.media.media/m",
            value={"kind": "audio"},
        ),
        publish.WriteOp(
            action="update",
            collection="pub.layers.expression.expression",
            rkey="e",
            uri="at://did:plc:me/pub.layers.expression.expression/e",
            value={"id": "x", "kind": "sentence"},
        ),
    ]
    with publish.WriteClient(
        "https://pds.example",
        "did:plc:me",
        _mock_client(handler),
    ) as client:
        results = client.apply_writes(ops)

    # the failed batch falls back to one idempotent putRecord per record.
    assert calls["apply"] == 1
    assert calls["put"] == 2
    assert {r.status for r in results} == {"updated"}


def test_post_rejects_non_object_body() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[1, 2, 3])

    with (
        publish.WriteClient(
            "https://pds.example",
            "did:plc:me",
            _mock_client(handler),
        ) as client,
        pytest.raises(publish.WriteError),
    ):
        client.create_record("pub.layers.media.media", {"kind": "audio"})


def test_apply_writes_populates_cids_from_results_array() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        # the PDS returns a results array aligned with the input writes.
        results = [
            {"$type": f"{publish._APPLY_WRITES_NSID}#createResult", "cid": f"cid-{i}"}
            for i, _ in enumerate(body["writes"])
        ]
        return httpx.Response(200, json={"results": results})

    ops = [
        publish.WriteOp(
            action="create",
            collection="pub.layers.expression.expression",
            rkey="e",
            uri="at://did:plc:me/pub.layers.expression.expression/e",
            value={"id": "x", "kind": "sentence"},
        ),
        publish.WriteOp(
            action="create",
            collection="pub.layers.annotation.annotationLayer",
            rkey="a",
            uri="at://did:plc:me/pub.layers.annotation.annotationLayer/a",
            value={"kind": "span"},
        ),
    ]
    with publish.WriteClient(
        "https://pds.example",
        "did:plc:me",
        _mock_client(handler),
    ) as client:
        results = client.apply_writes(ops)

    # the bulk path now carries the committed CID for each write, in order.
    assert [r.cid for r in results] == ["cid-0", "cid-1"]


def test_apply_writes_reports_deleted_on_batch_success() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": []})

    op = publish.WriteOp(
        action="delete",
        collection="pub.layers.media.media",
        rkey="m",
        uri="at://did:plc:me/pub.layers.media.media/m",
    )
    with publish.WriteClient(
        "https://pds.example",
        "did:plc:me",
        _mock_client(handler),
    ) as client:
        results = client.apply_writes([op])

    assert len(results) == 1
    assert results[0].status == "deleted"
    assert results[0].cid is None


def test_apply_writes_records_per_record_failure_reasons() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("applyWrites"):
            return httpx.Response(500, json={"error": "boom"})
        return httpx.Response(400, json={"error": "InvalidRecord"})

    ops = [
        publish.WriteOp(
            action="create",
            collection="pub.layers.media.media",
            rkey="m",
            uri="at://did:plc:me/pub.layers.media.media/m",
            value={"kind": "audio"},
        ),
    ]
    with publish.WriteClient(
        "https://pds.example",
        "did:plc:me",
        _mock_client(handler),
    ) as client:
        results = client.apply_writes(ops)

    assert len(results) == 1
    assert results[0].status == "failed"
    assert results[0].reason is not None


# plan / publish / pull ----------------------------------------------------


def _seed_repo(path: Path) -> tuple[Repository, str, str, str]:
    """Initialise a repo with one expression and one media record."""
    repo = Repository.init(path)
    now = datetime.now(UTC)
    expr_uri = "at://did:plc:me/pub.layers.expression.expression/e1"
    media_uri = "at://did:plc:me/pub.layers.media.media/m1"
    repo.save(
        expr_uri, Expression(id="doc-1", kind="sentence", createdAt=now, text="hi")
    )
    repo.save(media_uri, Media(kind="audio", createdAt=now))
    revision = repo.commit("seed")
    return repo, revision, expr_uri, media_uri


def test_plan_publish_creates_everything_for_empty_pds(tmp_path: Path) -> None:
    repo, revision, expr_uri, media_uri = _seed_repo(tmp_path)
    plan = publish.plan_publish(repo, revision, to="did:plc:me", pds_cids={})
    assert len(plan.creates) == 2
    assert not plan.updates
    assert not plan.deletes
    created = {op.uri for op in plan.creates}
    assert created == {expr_uri, media_uri}
    # creates carry the $type discriminator and are tier-ordered.
    media_op = next(op for op in plan.creates if op.uri == media_uri)
    assert isinstance(media_op.value, dict)
    assert media_op.value["$type"] == "pub.layers.media.media"
    assert plan.creates[0].collection == "pub.layers.media.media"


def test_plan_publish_diffs_updates_and_deletes(tmp_path: Path) -> None:
    repo, revision, expr_uri, media_uri = _seed_repo(tmp_path)
    local = publish._pds_state(repo, revision)
    pds = {
        media_uri: local[media_uri],
        expr_uri: "stale-cid",
        "at://did:plc:me/pub.layers.corpus.corpus/c1": "old",
    }
    plan = publish.plan_publish(repo, revision, to="did:plc:me", pds_cids=pds)
    assert not plan.creates
    assert [op.uri for op in plan.updates] == [expr_uri]
    assert [op.uri for op in plan.deletes] == [
        "at://did:plc:me/pub.layers.corpus.corpus/c1"
    ]


def test_record_cid_matches_pds_form_for_blob_record() -> None:
    # a blob-bearing record's locally computed CID must match the CID a PDS
    # computes over the DAG-CBOR it stores, so re-publishing it is a no-op.
    real_cid = "bafkreibvjvcv745gig4mvqs4hctx4zfkono4rjejm2ta6gtyzkqxfjeily"
    media = Media(
        kind="audio",
        createdAt=datetime(2026, 6, 16, tzinfo=UTC),
        blob=BlobRef(cid=real_cid, mime_type="audio/wav", size=12345),
    )
    raw = json.loads(media.model_dump_json())
    collection = "pub.layers.media.media"
    wire = publish._value_with_type(raw, collection)
    assert isinstance(wire, dict)
    # the lairs BlobRef form is rewritten to the ATProto blob wire form.
    blob = wire["blob"]
    assert isinstance(blob, dict)
    assert blob["$type"] == "blob"
    assert blob["ref"] == {"$link": real_cid}
    assert blob["mimeType"] == "audio/wav"
    assert blob["size"] == 12345

    local_cid = publish._record_cid(wire)

    # recompute the CID the way a PDS does: encode the wire form with the
    # cid-link as a real DAG-CBOR CID link, sha-256, dag-cbor codec.
    def _pds_form(node: object) -> object:
        if isinstance(node, dict):
            link = node.get("$link")
            if len(node) == 1 and isinstance(link, str):
                return bytes(CID.decode(link))
            return {key: _pds_form(item) for key, item in node.items()}
        if isinstance(node, list):
            return [_pds_form(item) for item in node]
        return node

    pds_bytes = libipld.encode_dag_cbor(_pds_form(wire))
    pds_cid = str(
        CID("base32", 1, "dag-cbor", multihash.digest(pds_bytes, "sha2-256")),
    )
    assert local_cid == pds_cid


def test_plan_publish_is_idempotent_for_blob_record(tmp_path: Path) -> None:
    # diffing a blob-bearing revision against a PDS state that reports the same
    # locally-computed CID yields an empty plan (the core of blob idempotency).
    repo = Repository.init(tmp_path)
    real_cid = "bafkreibvjvcv745gig4mvqs4hctx4zfkono4rjejm2ta6gtyzkqxfjeily"
    media_uri = "at://did:plc:me/pub.layers.media.media/m1"
    repo.save(
        media_uri,
        Media(
            kind="audio",
            createdAt=datetime(2026, 6, 16, tzinfo=UTC),
            blob=BlobRef(cid=real_cid, mime_type="audio/wav", size=12345),
        ),
    )
    revision = repo.commit("seed media")
    local = publish._pds_state(repo, revision)
    plan = publish.plan_publish(repo, revision, to="did:plc:me", pds_cids=local)
    assert plan.is_empty()


def test_fetch_pds_cids_raises_on_server_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        # the first collection enumerated returns a 5xx: the diff must abort
        # rather than treating the collection as empty.
        return httpx.Response(500, json={"error": "Internal"})

    with pytest.raises(publish.WriteError):
        publish._fetch_pds_cids(
            "did:plc:me",
            endpoint="https://pds.example",
            client=_mock_client(handler),
        )


def test_fetch_pds_cids_treats_404_as_empty_collection() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        collection = request.url.params.get("collection")
        if collection == "pub.layers.expression.expression":
            return httpx.Response(
                200,
                json={
                    "records": [
                        {
                            "uri": "at://did:plc:me/pub.layers.expression.expression/e",
                            "cid": "cidE",
                            "value": {},
                        },
                    ],
                    "cursor": "",
                },
            )
        return httpx.Response(404, json={"error": "NotFound"})

    cids = publish._fetch_pds_cids(
        "did:plc:me",
        endpoint="https://pds.example",
        client=_mock_client(handler),
    )
    assert cids == {"at://did:plc:me/pub.layers.expression.expression/e": "cidE"}


def test_publish_requires_endpoint_for_live_run(tmp_path: Path) -> None:
    repo, revision, _expr_uri, _media_uri = _seed_repo(tmp_path)
    with pytest.raises(publish.WriteError):
        publish.publish(repo, revision, to="did:plc:me", dry_run=False)


def test_publish_dry_run_returns_plan_without_writing(tmp_path: Path) -> None:
    repo, revision, _expr_uri, _media_uri = _seed_repo(tmp_path)
    plan = publish.publish(repo, revision, to="did:plc:me", dry_run=True)
    assert plan.repo == "did:plc:me"
    assert plan.revision == revision
    # with no endpoint the pds is treated as empty, so all records create.
    assert len(plan.creates) == 2


def test_publish_live_applies_the_plan(tmp_path: Path) -> None:
    repo, revision, _expr_uri, _media_uri = _seed_repo(tmp_path)
    applied: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("listRecords"):
            return httpx.Response(200, json={"records": [], "cursor": ""})
        if path.endswith("applyWrites"):
            body = json.loads(request.content)
            applied.extend(op["collection"] for op in body["writes"])
            return httpx.Response(200, json={"results": []})
        return httpx.Response(404)

    plan = publish.publish(
        repo,
        revision,
        to="did:plc:me",
        endpoint="https://pds.example",
        client=_mock_client(handler),
        dry_run=False,
    )
    assert len(plan.creates) == 2
    # media (tier 0) applied before expression (tier 1).
    assert applied == ["pub.layers.media.media", "pub.layers.expression.expression"]


def test_pull_round_trips_records_into_a_repository(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    expr = Expression(id="doc-1", kind="sentence", createdAt=now, text="hi")
    expr_value = json.loads(expr.model_dump_json())
    expr_uri = "at://did:plc:them/pub.layers.expression.expression/e1"

    def handler(request: httpx.Request) -> httpx.Response:
        collection = request.url.params.get("collection")
        if request.url.path.endswith("listRecords"):
            if collection == "pub.layers.expression.expression":
                return httpx.Response(
                    200,
                    json={
                        "records": [
                            {"uri": expr_uri, "cid": "cidA", "value": expr_value},
                        ],
                        "cursor": "",
                    },
                )
            return httpx.Response(200, json={"records": [], "cursor": ""})
        return httpx.Response(404)

    repo = Repository.init(tmp_path)
    publish.pull(
        "did:plc:them",
        endpoint="https://pds.example",
        into=repo,
        client=_mock_client(handler),
    )
    assert repo.staged_uris() == [expr_uri]
    loaded = repo.load(expr_uri, Expression)
    assert loaded is not None
    assert loaded.text == "hi"


def test_pull_skips_invalid_records(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        collection = request.url.params.get("collection")
        if request.url.path.endswith("listRecords"):
            if collection == "pub.layers.expression.expression":
                return httpx.Response(
                    200,
                    json={
                        "records": [
                            {
                                "uri": "at://did:plc:them/pub.layers.expression.expression/bad",
                                "cid": "c",
                                "value": {"not": "an expression"},
                            },
                        ],
                        "cursor": "",
                    },
                )
            return httpx.Response(200, json={"records": [], "cursor": ""})
        return httpx.Response(404)

    repo = Repository.init(tmp_path)
    publish.pull(
        "did:plc:them",
        endpoint="https://pds.example",
        into=repo,
        client=_mock_client(handler),
    )
    assert repo.staged_uris() == []


def test_apply_writes_module_function() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": []})

    results = publish.apply_writes(
        "did:plc:me",
        [_op("pub.layers.media.media", "m")],
        endpoint="https://pds.example",
        client=_mock_client(handler),
    )
    assert len(results) == 1
    assert results[0].status == "created"


@pytest.mark.integration
def test_write_round_trip_live(pds_server: PdsServer) -> None:
    """Create a record through the write client and read it back from the PDS."""
    auth = {"Authorization": f"Bearer {pds_server.access_jwt}"}
    with httpx.Client(headers=auth) as authed:
        writer = publish.WriteClient(pds_server.endpoint, pds_server.did, authed)
        result = writer.create_record(
            "pub.layers.expression.expression",
            {
                "$type": "pub.layers.expression.expression",
                "id": "22222222-2222-2222-2222-222222222222",
                "text": "round trip",
                "kind": "sentence",
                "createdAt": "2026-06-16T00:00:00Z",
            },
        )
        assert result.status == "created"
        assert result.uri.startswith("at://")
        rkey = result.uri.rsplit("/", 1)[-1]
        read_back = authed.get(
            f"{pds_server.endpoint}/xrpc/com.atproto.repo.getRecord",
            params={
                "repo": pds_server.did,
                "collection": "pub.layers.expression.expression",
                "rkey": rkey,
            },
            timeout=30.0,
        )
        read_back.raise_for_status()
    assert read_back.json()["value"]["text"] == "round trip"


def _authed(server: PdsServer) -> httpx.Client:
    """Return an httpx client carrying the test account's bearer token."""
    return httpx.Client(headers={"Authorization": f"Bearer {server.access_jwt}"})


@pytest.mark.integration
def test_apply_writes_creates_all_records_live(pds_server: PdsServer) -> None:
    # a bulk applyWrites of several record types lands every record, and each
    # stored record carries the $type discriminator the write path must inject.
    token = pds_server.handle.split(".", 1)[0]
    expr_uri = f"at://{pds_server.did}/pub.layers.expression.expression/{token}e"
    media_uri = f"at://{pds_server.did}/pub.layers.media.media/{token}m"
    layer_uri = f"at://{pds_server.did}/pub.layers.annotation.annotationLayer/{token}l"
    writes = [
        # deliberately out of dependency order: the layer is listed first.
        publish.WriteOp(
            action="create",
            collection="pub.layers.annotation.annotationLayer",
            rkey=f"{token}l",
            uri=layer_uri,
            value={"kind": "span", "createdAt": "2026-06-16T00:00:00Z"},
        ),
        publish.WriteOp(
            action="create",
            collection="pub.layers.media.media",
            rkey=f"{token}m",
            uri=media_uri,
            value={"kind": "audio", "createdAt": "2026-06-16T00:00:00Z"},
        ),
        publish.WriteOp(
            action="create",
            collection="pub.layers.expression.expression",
            rkey=f"{token}e",
            uri=expr_uri,
            value={
                "id": "11111111-1111-1111-1111-111111111111",
                "text": "round trip",
                "kind": "sentence",
                "createdAt": "2026-06-16T00:00:00Z",
            },
        ),
    ]
    with _authed(pds_server) as client:
        writer = publish.WriteClient(pds_server.endpoint, pds_server.did, client)
        results = writer.apply_writes(writes)
        assert {r.status for r in results} == {"created"}
        reader = PdsClient(pds_server.endpoint, client)
        # every record is readable and carries $type == its collection.
        for collection, rkey in [
            ("pub.layers.expression.expression", f"{token}e"),
            ("pub.layers.media.media", f"{token}m"),
            ("pub.layers.annotation.annotationLayer", f"{token}l"),
        ]:
            envelope = reader.get_record(pds_server.did, collection, rkey)
            assert isinstance(envelope.value, dict)
            assert envelope.value["$type"] == collection
        # the expression decodes through the generated model.
        env = reader.get_record(
            pds_server.did, "pub.layers.expression.expression", f"{token}e"
        )
        assert decode(env, Expression).text == "round trip"


@pytest.mark.integration
def test_put_record_idempotent_live(pds_server: PdsServer) -> None:
    # putRecord on a deterministic rkey upserts rather than duplicating.
    collection = "pub.layers.expression.expression"
    rkey = pds_server.handle.split(".", 1)[0] + "idem"
    with _authed(pds_server) as client:
        writer = publish.WriteClient(pds_server.endpoint, pds_server.did, client)
        base = {
            "id": "22222222-2222-2222-2222-222222222222",
            "kind": "sentence",
            "createdAt": "2026-06-16T00:00:00Z",
        }
        writer.put_record(collection, rkey, {**base, "text": "first"})
        result = writer.put_record(collection, rkey, {**base, "text": "second"})
        assert result.status == "updated"
        reader = PdsClient(pds_server.endpoint, client)
        env = reader.get_record(pds_server.did, collection, rkey)
        assert isinstance(env.value, dict)
        assert env.value["text"] == "second"


@pytest.mark.integration
def test_delete_record_live(pds_server: PdsServer) -> None:
    collection = "pub.layers.expression.expression"
    rkey = pds_server.handle.split(".", 1)[0] + "del"
    with _authed(pds_server) as client:
        writer = publish.WriteClient(pds_server.endpoint, pds_server.did, client)
        writer.put_record(
            collection,
            rkey,
            {
                "id": "33333333-3333-3333-3333-333333333333",
                "text": "doomed",
                "kind": "sentence",
                "createdAt": "2026-06-16T00:00:00Z",
            },
        )
        result = writer.delete_record(collection, rkey)
        assert result.status == "deleted"
        reader = PdsClient(pds_server.endpoint, client)
        with pytest.raises(httpx.HTTPStatusError):
            reader.get_record(pds_server.did, collection, rkey)


@pytest.mark.integration
def test_write_requires_auth_live(pds_server: PdsServer) -> None:
    # an unauthenticated write is rejected by the PDS and surfaces as WriteError.
    with httpx.Client() as anon:
        writer = publish.WriteClient(pds_server.endpoint, pds_server.did, anon)
        with pytest.raises(publish.WriteError):
            writer.create_record(
                "pub.layers.expression.expression",
                {
                    "id": "55555555-5555-5555-5555-555555555555",
                    "text": "no auth",
                    "kind": "sentence",
                    "createdAt": "2026-06-16T00:00:00Z",
                },
            )


@pytest.mark.integration
def test_apply_writes_partial_failure_resumes_live(pds_server: PdsServer) -> None:
    # one op names an invalid collection, failing the batch. the retry path
    # upserts the valid ops idempotently and reports the bad one as failed.
    token = pds_server.handle.split(".", 1)[0]
    good = "pub.layers.expression.expression"
    base = {
        "id": "44444444-4444-4444-4444-444444444444",
        "kind": "sentence",
        "createdAt": "2026-06-16T00:00:00Z",
    }
    ok1 = f"at://{pds_server.did}/{good}/{token}ok1"
    ok2 = f"at://{pds_server.did}/{good}/{token}ok2"
    bad = "at://bad"
    writes = [
        publish.WriteOp(
            action="create",
            collection=good,
            rkey=f"{token}ok1",
            uri=ok1,
            value={**base, "text": "ok1"},
        ),
        publish.WriteOp(
            action="create",
            collection="not a valid nsid",
            rkey=f"{token}bad",
            uri=bad,
            value={**base, "text": "bad"},
        ),
        publish.WriteOp(
            action="create",
            collection=good,
            rkey=f"{token}ok2",
            uri=ok2,
            value={**base, "text": "ok2"},
        ),
    ]
    with _authed(pds_server) as client:
        writer = publish.WriteClient(pds_server.endpoint, pds_server.did, client)
        results = {result.uri: result for result in writer.apply_writes(writes)}
        assert results[ok1].status in {"created", "updated"}
        assert results[ok2].status in {"created", "updated"}
        assert results[bad].status == "failed"
        assert results[bad].reason
        reader = PdsClient(pds_server.endpoint, client)
        assert reader.get_record(pds_server.did, good, f"{token}ok1").value
        assert reader.get_record(pds_server.did, good, f"{token}ok2").value


def _fresh_account(server: PdsServer) -> tuple[str, str]:
    """Create a new empty account on the PDS, returning (did, access_jwt)."""
    token = secrets.token_hex(6)
    response = httpx.post(
        f"{server.endpoint}/xrpc/com.atproto.server.createAccount",
        json={
            "handle": f"pub{token}.test",
            "email": f"pub{token}@example.test",
            "password": secrets.token_hex(12),
        },
        timeout=30.0,
    )
    response.raise_for_status()
    body = response.json()
    return str(body["did"]), str(body["accessJwt"])


@pytest.mark.integration
def test_publish_creates_then_is_idempotent_live(
    pds_server: PdsServer,
    tmp_path: Path,
) -> None:
    # publish into a fresh empty account so the diff is isolated. the first
    # publish creates the record; re-publishing the unchanged revision is a
    # no-op because the locally computed CID matches the PDS's reported CID.
    did, jwt = _fresh_account(pds_server)
    repo = Repository.init(tmp_path / "pubrepo")
    collection = "pub.layers.expression.expression"
    uri = f"at://{did}/{collection}/rec1"
    repo.save(
        uri,
        Expression.model_validate_json(
            json.dumps(
                {
                    "id": "66666666-6666-6666-6666-666666666666",
                    "text": "publish me",
                    "kind": "sentence",
                    "createdAt": "2026-06-16T00:00:00Z",
                },
            ),
        ),
    )
    revision = repo.commit("initial", author="lairs <lairs@layers.pub>")
    with httpx.Client(headers={"Authorization": f"Bearer {jwt}"}) as client:
        first = publish.publish(
            repo,
            revision,
            to=did,
            endpoint=pds_server.endpoint,
            client=client,
            dry_run=False,
        )
        assert [op.uri for op in first.creates] == [uri]
        assert not first.updates
        assert not first.deletes
        reader = PdsClient(pds_server.endpoint, client)
        env = reader.get_record(did, collection, "rec1")
        assert decode(env, Expression).text == "publish me"
        # the unchanged revision re-publishes to an empty plan.
        again = publish.publish(
            repo,
            revision,
            to=did,
            endpoint=pds_server.endpoint,
            client=client,
            dry_run=True,
        )
        assert again.is_empty()


@pytest.mark.integration
def test_publish_blob_record_is_idempotent_live(
    pds_server: PdsServer,
    tmp_path: Path,
) -> None:
    # publishing a blob-bearing media record and re-publishing the unchanged
    # revision is a no-op: the locally computed CID, with the blob rewritten to
    # the ATProto wire form, matches the PDS-reported CID.
    did, jwt = _fresh_account(pds_server)
    collection = "pub.layers.media.media"
    uri = f"at://{did}/{collection}/media1"
    with httpx.Client(headers={"Authorization": f"Bearer {jwt}"}) as client:
        writer = publish.WriteClient(pds_server.endpoint, did, client)
        # upload real bytes; the PDS returns its blob reference object.
        raw_blob = writer.upload_blob(b"fake audio bytes" * 64, "audio/wav")
        assert isinstance(raw_blob, dict)
        ref = raw_blob["ref"]
        assert isinstance(ref, dict)
        blob_cid = ref["$link"]
        assert isinstance(blob_cid, str)
        size = raw_blob.get("size")
        repo = Repository.init(tmp_path / "blobrepo")
        repo.save(
            uri,
            Media(
                kind="audio",
                createdAt=datetime(2026, 6, 16, tzinfo=UTC),
                blob=BlobRef(
                    cid=blob_cid,
                    mime_type="audio/wav",
                    size=size if isinstance(size, int) else None,
                ),
            ),
        )
        revision = repo.commit("seed media", author="lairs <lairs@layers.pub>")
        first = publish.publish(
            repo,
            revision,
            to=did,
            endpoint=pds_server.endpoint,
            client=client,
            dry_run=False,
        )
        assert [op.uri for op in first.creates] == [uri]
        # the stored record carries the blob in ATProto wire form.
        reader = PdsClient(pds_server.endpoint, client)
        env = reader.get_record(did, collection, "media1")
        assert isinstance(env.value, dict)
        stored_blob = env.value["blob"]
        assert isinstance(stored_blob, dict)
        assert stored_blob["$type"] == "blob"
        ref = stored_blob["ref"]
        assert isinstance(ref, dict)
        assert ref["$link"] == blob_cid
        # re-publishing the unchanged revision is a no-op.
        again = publish.publish(
            repo,
            revision,
            to=did,
            endpoint=pds_server.endpoint,
            client=client,
            dry_run=True,
        )
        assert again.is_empty()
