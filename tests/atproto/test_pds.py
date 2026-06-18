"""Unit and integration tests for lairs.atproto.pds."""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

import didactic.api as dx
import httpx
import libipld
import pytest
from multiformats import CID, multihash

from lairs.atproto import pds
from lairs.atproto.pds import (
    PdsClient,
    RecordEnvelope,
    RepoDescription,
    _envelopes_from_blocks,
    _walk_mst,
    decode,
    decode_all,
    decode_repo_car,
)
from lairs.records._generated.expression import Expression

if TYPE_CHECKING:
    from collections.abc import Callable

    from conftest import PdsServer

    from lairs.atproto._car import IpldValue

_ENDPOINT = "https://pds.example"
_REPO = "did:plc:abc"
_COLLECTION = "pub.layers.expression.expression"


class _Toy(dx.Model):
    """A toy target model for decode tests."""

    text: str = dx.field(description="text")


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> PdsClient:
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    return PdsClient(_ENDPOINT, client)


def test_exports() -> None:
    assert set(pds.__all__) == {
        "PdsClient",
        "QueryParams",
        "RecordDecodeFailure",
        "RecordEnvelope",
        "RepoDescription",
        "decode",
        "decode_all",
        "decode_repo_car",
        "describe_repo",
        "get_record",
        "get_repo",
        "list_records",
    }


def test_get_record_returns_envelope() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/xrpc/com.atproto.repo.getRecord"
        assert request.url.params["repo"] == _REPO
        return httpx.Response(
            200,
            json={"uri": "at://x", "cid": "bafy", "value": {"text": "hi"}},
        )

    with _client(handler) as client:
        envelope = client.get_record(_REPO, _COLLECTION, "rkey")
    assert isinstance(envelope, RecordEnvelope)
    assert envelope.uri == "at://x"
    assert envelope.cid == "bafy"
    assert envelope.value == {"text": "hi"}


def test_decode_helper_validates_value() -> None:
    envelope = RecordEnvelope(uri="at://x", cid="bafy", value={"text": "hi"})
    decoded = decode(envelope, _Toy)
    assert isinstance(decoded, _Toy)
    assert decoded.text == "hi"


def test_decode_helper_raises_on_invalid() -> None:
    envelope = RecordEnvelope(uri="at://x", cid="bafy", value={"nope": 1})
    with pytest.raises(dx.ValidationError):
        decode(envelope, _Toy)


def test_decode_all_collects_failures() -> None:
    envelopes = [
        RecordEnvelope(uri="at://1", cid="c1", value={"text": "ok"}),
        RecordEnvelope(uri="at://2", cid="c2", value={"nope": 1}),
        RecordEnvelope(uri="at://3", cid="c3", value={"text": "also"}),
    ]
    records, failures = decode_all(envelopes, _Toy)
    assert len(records) == 2
    assert len(failures) == 1
    assert all(isinstance(record, _Toy) for record in records)
    assert failures[0].uri == "at://2"
    assert failures[0].cid == "c2"
    assert failures[0].error


def test_decode_coerces_datetime_fields() -> None:
    # regression: dict-path model_validate raises a bare AssertionError on
    # datetime strings; the json path coerces them, so records carrying a
    # createdAt (every pub.layers record does) decode cleanly.
    envelope = RecordEnvelope(
        uri="at://x",
        cid="bafy",
        value={
            "id": "00000000-0000-0000-0000-000000000000",
            "text": "hi",
            "kind": "sentence",
            "createdAt": "2026-06-16T00:00:00Z",
        },
    )
    assert decode(envelope, Expression).text == "hi"
    records, failures = decode_all([envelope], Expression)
    assert len(records) == 1
    assert not failures


def test_decode_strips_type_discriminator() -> None:
    # real PDS records carry a $type the generated models do not declare.
    envelope = RecordEnvelope(
        uri="at://x",
        cid="bafy",
        value={"$type": "pub.layers.x", "text": "hi"},
    )
    assert decode(envelope, _Toy).text == "hi"


def test_list_records_paginates_lazily() -> None:
    pages = {
        None: {
            "records": [
                {"uri": "at://1", "cid": "c1", "value": {"text": "a"}},
                {"uri": "at://2", "cid": "c2", "value": {"text": "b"}},
            ],
            "cursor": "page2",
        },
        "page2": {
            "records": [
                {"uri": "at://3", "cid": "c3", "value": {"text": "c"}},
            ],
        },
    }
    seen_cursors: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("cursor")
        seen_cursors.append(cursor)
        return httpx.Response(200, json=pages[cursor])

    with _client(handler) as client:
        envelopes = list(client.list_records(_REPO, _COLLECTION))
    assert [e.uri for e in envelopes] == ["at://1", "at://2", "at://3"]
    assert seen_cursors == [None, "page2"]


def test_list_records_stops_on_empty_cursor() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "records": [{"uri": "at://1", "cid": "c1", "value": {}}],
                "cursor": "",
            },
        )

    with _client(handler) as client:
        envelopes = list(client.list_records(_REPO, _COLLECTION))
    assert len(envelopes) == 1


def test_list_records_is_lazy_iterator() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        cursor = request.url.params.get("cursor")
        if cursor is None:
            return httpx.Response(
                200,
                json={
                    "records": [{"uri": "at://1", "cid": "c1", "value": {}}],
                    "cursor": "next",
                },
            )
        return httpx.Response(
            200,
            json={"records": [{"uri": "at://2", "cid": "c2", "value": {}}]},
        )

    with _client(handler) as client:
        iterator = client.list_records(_REPO, _COLLECTION)
        first = next(iterator)
        # only the first page should have been fetched so far.
        assert calls["n"] == 1
        assert first.uri == "at://1"
        rest = list(iterator)
    assert calls["n"] == 2
    assert [e.uri for e in rest] == ["at://2"]


def test_get_record_raises_on_error_status() -> None:
    with (
        _client(lambda _r: httpx.Response(500)) as client,
        pytest.raises(httpx.HTTPStatusError),
    ):
        client.get_record(_REPO, _COLLECTION, "rkey")


_REPO_DID = "did:plc:repotest"


def _cid_bytes(value: IpldValue) -> bytes:
    """Compute the raw CIDv1 dag-cbor bytes for a block value."""
    raw = libipld.encode_dag_cbor(value)
    return bytes(CID("base32", 1, "dag-cbor", multihash.digest(raw, "sha2-256")))


def _cid_str(value: IpldValue) -> str:
    """Compute the base32 CID string for a block value."""
    return CID.decode(_cid_bytes(value)).encode("base32")


def _expression_record(text: str) -> dict[str, IpldValue]:
    """Build an expression-shaped record value."""
    return {
        "$type": _COLLECTION,
        "id": "00000000-0000-0000-0000-000000000000",
        "text": text,
        "kind": "sentence",
        "createdAt": "2026-06-16T00:00:00Z",
    }


def _mst_entry(
    previous: bytes,
    key: bytes,
    value_cid: bytes,
    right: bytes | None = None,
) -> dict[str, IpldValue]:
    """Build a prefix-compressed MST entry relative to the previous key."""
    shared = 0
    for left, current in zip(previous, key, strict=False):
        if left != current:
            break
        shared += 1
    return {"p": shared, "k": key[shared:], "v": value_cid, "t": right}


def test_get_repo_car_fetches_raw_bytes() -> None:
    payload = b"\x00car-archive-bytes"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/xrpc/com.atproto.sync.getRepo"
        assert request.url.params["did"] == _REPO
        return httpx.Response(200, content=payload)

    with _client(handler) as client:
        assert client.get_repo_car(_REPO) == payload


def test_get_repo_car_raises_on_error_status() -> None:
    with (
        _client(lambda _r: httpx.Response(404)) as client,
        pytest.raises(httpx.HTTPStatusError),
    ):
        client.get_repo_car(_REPO)


def test_describe_repo_maps_camelcase_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/xrpc/com.atproto.repo.describeRepo"
        assert request.url.params["repo"] == _REPO
        return httpx.Response(
            200,
            json={
                "did": _REPO,
                "handle": "alice.test",
                "handleIsCorrect": True,
                "collections": [_COLLECTION, "pub.layers.corpus.corpus", 7],
                "didDoc": {"id": _REPO},
            },
        )

    with _client(handler) as client:
        description = client.describe_repo(_REPO)
    assert isinstance(description, RepoDescription)
    assert description.did == _REPO
    assert description.handle == "alice.test"
    assert description.handle_is_correct is True
    # the integer collection entry is dropped defensively.
    assert description.collections == (_COLLECTION, "pub.layers.corpus.corpus")
    assert description.did_doc == {"id": _REPO}


def test_describe_repo_defaults_on_empty_body() -> None:
    with _client(lambda _r: httpx.Response(200, json=[])) as client:
        description = client.describe_repo(_REPO)
    assert description.did == ""
    assert description.handle == ""
    assert description.handle_is_correct is False
    assert description.collections == ()
    assert description.did_doc is None


def test_describe_repo_raises_on_error_status() -> None:
    with (
        _client(lambda _r: httpx.Response(500)) as client,
        pytest.raises(httpx.HTTPStatusError),
    ):
        client.describe_repo(_REPO)


def test_list_repos_paginates_dids() -> None:
    pages = {
        None: {"repos": [{"did": "did:plc:a"}, {"did": "did:plc:b"}], "cursor": "p2"},
        "p2": {"repos": [{"did": "did:plc:c"}]},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/xrpc/com.atproto.sync.listRepos"
        cursor = request.url.params.get("cursor")
        return httpx.Response(200, json=pages[cursor])

    with _client(handler) as client:
        dids = list(client.list_repos())
    assert dids == ["did:plc:a", "did:plc:b", "did:plc:c"]


def test_walk_mst_reconstructs_keys_in_order() -> None:
    # a three-node tree exercising prefix compression, a left subtree, and a
    # right subtree, so the in-order walk must interleave all three.
    cid_a0 = _cid_bytes(_expression_record("a0"))
    cid_b0 = _cid_bytes(_expression_record("b0"))
    cid_b0m = _cid_bytes(_expression_record("b0m"))
    cid_b1 = _cid_bytes(_expression_record("b1"))
    left_entries: list[IpldValue] = [_mst_entry(b"", b"col/a0", cid_a0)]
    left_node: dict[str, IpldValue] = {"l": None, "e": left_entries}
    mid_entries: list[IpldValue] = [_mst_entry(b"", b"col/b0m", cid_b0m)]
    mid_node: dict[str, IpldValue] = {"l": None, "e": mid_entries}
    left_cid = _cid_bytes(left_node)
    mid_cid = _cid_bytes(mid_node)
    root_entries: list[IpldValue] = [
        _mst_entry(b"", b"col/b0", cid_b0, right=mid_cid),
        _mst_entry(b"col/b0", b"col/b1", cid_b1),
    ]
    root_node: dict[str, IpldValue] = {"l": left_cid, "e": root_entries}
    root_cid = _cid_bytes(root_node)
    blocks: dict[bytes, IpldValue] = {
        left_cid: left_node,
        mid_cid: mid_node,
        root_cid: root_node,
    }
    walked = list(_walk_mst(blocks, root_cid))
    keys = [key.decode() for key, _ in walked]
    assert keys == ["col/a0", "col/b0", "col/b0m", "col/b1"]
    assert [cid for _, cid in walked] == [cid_a0, cid_b0, cid_b0m, cid_b1]


def test_envelopes_from_blocks_builds_decodable_envelopes() -> None:
    record_one = _expression_record("alpha")
    record_two = _expression_record("beta")
    cid_one = _cid_bytes(record_one)
    cid_two = _cid_bytes(record_two)
    entries: list[IpldValue] = [
        _mst_entry(b"", f"{_COLLECTION}/aaaaa".encode(), cid_one),
        _mst_entry(
            f"{_COLLECTION}/aaaaa".encode(), f"{_COLLECTION}/aaaab".encode(), cid_two
        ),
    ]
    node: dict[str, IpldValue] = {"l": None, "e": entries}
    node_cid = _cid_bytes(node)
    commit: dict[str, IpldValue] = {
        "version": 3,
        "did": _REPO_DID,
        "data": node_cid,
        "rev": "abc",
        "prev": None,
    }
    commit_cid = _cid_bytes(commit)
    roots: list[IpldValue] = [commit_cid]
    header: dict[str, IpldValue] = {"roots": roots, "version": 1}
    blocks: dict[bytes, IpldValue] = {
        commit_cid: commit,
        node_cid: node,
        cid_one: record_one,
        cid_two: record_two,
    }
    envelopes = _envelopes_from_blocks(header, blocks)
    assert [env.uri for env in envelopes] == [
        f"at://{_REPO_DID}/{_COLLECTION}/aaaaa",
        f"at://{_REPO_DID}/{_COLLECTION}/aaaab",
    ]
    assert [env.cid for env in envelopes] == [
        _cid_str(record_one),
        _cid_str(record_two),
    ]
    decoded = [decode(env, Expression) for env in envelopes]
    assert [record.text for record in decoded] == ["alpha", "beta"]


def test_envelopes_from_blocks_returns_empty_without_roots() -> None:
    assert _envelopes_from_blocks({"version": 1}, {}) == ()


def test_envelopes_from_blocks_returns_empty_on_non_object_header() -> None:
    assert _envelopes_from_blocks("not a header", {}) == ()


def test_module_list_records_drains_pages() -> None:
    transport = httpx.MockTransport(
        lambda _r: httpx.Response(
            200,
            json={"records": [{"uri": "at://1", "cid": "c1", "value": {}}]},
        ),
    )
    client = httpx.Client(transport=transport)
    with PdsClient(_ENDPOINT, client) as pds_client:
        envelopes = list(pds_client.list_records(_REPO, _COLLECTION))
    assert len(envelopes) == 1


@pytest.mark.integration
def test_get_record_live() -> None:
    # exercises a real PDS getRecord when opted in; skips otherwise.
    try:
        pds.get_record(
            _ENDPOINT,
            _REPO,
            "pub.layers.corpus.corpus",
            "rkey",
        )
    except httpx.HTTPError:
        pytest.skip("network unavailable for live pds getRecord")


@pytest.mark.integration
def test_pds_round_trip_live(pds_server: PdsServer) -> None:
    """Seed a record on a real PDS and read it back through the client."""
    value = {
        "$type": "pub.layers.expression.expression",
        "id": "11111111-1111-1111-1111-111111111111",
        "text": "the cat sat",
        "kind": "sentence",
        "createdAt": "2026-06-16T00:00:00Z",
    }
    headers = {"Authorization": f"Bearer {pds_server.access_jwt}"}
    with httpx.Client(headers=headers) as authed:
        created = authed.post(
            f"{pds_server.endpoint}/xrpc/com.atproto.repo.createRecord",
            json={
                "repo": pds_server.did,
                "collection": "pub.layers.expression.expression",
                "record": value,
            },
            timeout=30.0,
        )
        created.raise_for_status()
        uri = str(created.json()["uri"])
    rkey = uri.rsplit("/", 1)[-1]
    client = PdsClient(pds_server.endpoint)
    envelope = client.get_record(
        pds_server.did, "pub.layers.expression.expression", rkey
    )
    assert decode(envelope, Expression).text == "the cat sat"
    listed = list(
        client.list_records(pds_server.did, "pub.layers.expression.expression"),
    )
    assert any(env.uri == uri for env in listed)


def _seed_records(server: PdsServer, collection: str, count: int) -> None:
    """Create ``count`` records in ``collection`` on the live PDS."""
    headers = {"Authorization": f"Bearer {server.access_jwt}"}
    with httpx.Client(headers=headers) as authed:
        for index in range(count):
            response = authed.post(
                f"{server.endpoint}/xrpc/com.atproto.repo.createRecord",
                json={
                    "repo": server.did,
                    "collection": collection,
                    "record": {
                        "$type": collection,
                        "id": f"00000000-0000-0000-0000-{index:012d}",
                        "text": f"record {index}",
                        "kind": "sentence",
                        "createdAt": "2026-06-16T00:00:00Z",
                    },
                },
                timeout=30.0,
            )
            response.raise_for_status()


@pytest.mark.integration
def test_list_records_paginates_live(pds_server: PdsServer) -> None:
    # listRecords drains every page via cursor pagination, returning each
    # record exactly once across a page size smaller than the record count.
    collection = "pub.layers.test.page"
    count = 25
    _seed_records(pds_server, collection, count)
    client = PdsClient(pds_server.endpoint)
    seen = list(client.list_records(pds_server.did, collection, limit=10))
    assert len(seen) == count
    assert len({envelope.uri for envelope in seen}) == count


@pytest.mark.integration
def test_decode_all_over_real_records_live(pds_server: PdsServer) -> None:
    # every fetched record carries a $type; decode_all strips it and validates
    # all of them against the generated model with no failures.
    collection = "pub.layers.test.decode"
    _seed_records(pds_server, collection, 5)
    client = PdsClient(pds_server.endpoint)
    envelopes = list(client.list_records(pds_server.did, collection))
    records, failures = decode_all(envelopes, Expression)
    assert len(records) == 5
    assert not failures
    assert {record.text for record in records} == {f"record {i}" for i in range(5)}


@pytest.mark.integration
def test_get_record_missing_raises_live(pds_server: PdsServer) -> None:
    client = PdsClient(pds_server.endpoint)
    with pytest.raises(httpx.HTTPStatusError):
        client.get_record(
            pds_server.did, "pub.layers.expression.expression", "does-not-exist"
        )


@pytest.mark.integration
def test_describe_repo_live(pds_server: PdsServer) -> None:
    # seed a record then read the repo table of contents; the seeded collection
    # must appear without enumerating any records.
    collection = "pub.layers.test.describe"
    _seed_records(pds_server, collection, 1)
    client = PdsClient(pds_server.endpoint)
    description = client.describe_repo(pds_server.did)
    assert description.did == pds_server.did
    assert collection in description.collections


def _fresh_account(server: PdsServer) -> tuple[str, str]:
    """Create another throwaway account on the same PDS, returning did and jwt."""
    token = secrets.token_hex(8)
    response = httpx.post(
        f"{server.endpoint}/xrpc/com.atproto.server.createAccount",
        json={
            "handle": f"u{token}.test",
            "email": f"{token}@example.test",
            "password": secrets.token_hex(16),
        },
        timeout=30.0,
    )
    response.raise_for_status()
    body = response.json()
    return str(body["did"]), str(body["accessJwt"])


def _seed_account(
    endpoint: str,
    did: str,
    jwt: str,
    collection: str,
    count: int,
) -> list[str]:
    """Create ``count`` records in ``collection`` for ``did``, returning the uris."""
    headers = {"Authorization": f"Bearer {jwt}"}
    uris: list[str] = []
    with httpx.Client(headers=headers) as authed:
        for index in range(count):
            response = authed.post(
                f"{endpoint}/xrpc/com.atproto.repo.createRecord",
                json={
                    "repo": did,
                    "collection": collection,
                    "record": {
                        "$type": collection,
                        "id": f"00000000-0000-0000-0000-{index:012d}",
                        "text": f"record {index}",
                        "kind": "sentence",
                        "createdAt": "2026-06-16T00:00:00Z",
                    },
                },
                timeout=30.0,
            )
            response.raise_for_status()
            uris.append(str(response.json()["uri"]))
    return uris


@pytest.mark.integration
def test_get_repo_decodes_full_repository_live(pds_server: PdsServer) -> None:
    # get_repo recovers every record across collections in a single CAR fetch,
    # with CIDs identical to those the XRPC record endpoints report.
    did, jwt = _fresh_account(pds_server)
    seeded = [
        *_seed_account(pds_server.endpoint, did, jwt, _COLLECTION, 3),
        *_seed_account(pds_server.endpoint, did, jwt, "pub.layers.test.other", 2),
    ]
    client = PdsClient(pds_server.endpoint)
    envelopes = client.get_repo(did)
    assert {env.uri for env in envelopes} == set(seeded)
    listed = [
        *client.list_records(did, _COLLECTION),
        *client.list_records(did, "pub.layers.test.other"),
    ]
    assert {env.uri: env.cid for env in envelopes} == {
        env.uri: env.cid for env in listed
    }
    expressions = [env for env in envelopes if _COLLECTION in env.uri]
    records, failures = decode_all(expressions, Expression)
    assert not failures
    assert {record.text for record in records} == {f"record {i}" for i in range(3)}


@pytest.mark.integration
def test_decode_repo_car_matches_get_repo_live(pds_server: PdsServer) -> None:
    did, jwt = _fresh_account(pds_server)
    _seed_account(pds_server.endpoint, did, jwt, _COLLECTION, 4)
    client = PdsClient(pds_server.endpoint)
    car = client.get_repo_car(did)
    assert decode_repo_car(car) == client.get_repo(did)
