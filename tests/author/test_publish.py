"""Unit and integration tests for lairs.author.publish."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
import pytest

from lairs.author import publish
from lairs.records._generated.expression import Expression
from lairs.records._generated.media import Media
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


def test_deterministic_rkey_is_stable_and_order_independent() -> None:
    first = publish.deterministic_rkey({"a": 1, "b": 2})
    second = publish.deterministic_rkey({"b": 2, "a": 1})
    assert first == second
    assert len(first) == 24


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
def test_publish_dry_run_live() -> None:
    # exercises a real publish dry-run when opted in; skips otherwise.
    pytest.skip("publish requires a Repository and credentials")


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
