"""Unit tests for lairs.data.snapshot."""

from __future__ import annotations

import gzip
import hashlib
from typing import TYPE_CHECKING

import httpx
import libipld
import pytest
from multiformats import CID, multihash

from lairs.atproto._car import record_cid
from lairs.atproto.pds import PdsClient
from lairs.data import snapshot
from lairs.data.snapshot import (
    PIN_FILE,
    PIN_RECORDS_FILE,
    DatasetPin,
    PinError,
    check_remote,
    pull_dataset,
    read_pin,
    read_pin_records,
    verify_pin,
)
from lairs.store.repository import Repository

if TYPE_CHECKING:
    from pathlib import Path

    from lairs.atproto._car import IpldValue

_ENDPOINT = "https://pds.example"
_STEM = "tb.eng.ud.example"
_CORPUS_DID = "did:plc:corpus"
_CATALOG_DID = "did:plc:catalog"
_EXPRESSION_DID = "did:plc:expression"
_ANNOTATION_DID = "did:plc:annotation"
_SEGMENTATION_DID = "did:plc:segmentation"
_ONTOLOGY_DID = "did:plc:ontology"
_CORPUS_URI = f"at://{_CORPUS_DID}/pub.layers.corpus.corpus/main"
_STAMP = "1970-01-01T00:00:00+00:00"


def _cid_bytes(value: IpldValue) -> bytes:
    """Compute the raw CIDv1 dag-cbor bytes for a block value."""
    raw = libipld.encode_dag_cbor(value)
    return bytes(CID("base32", 1, "dag-cbor", multihash.digest(raw, "sha2-256")))


def _varint(value: int) -> bytes:
    """Encode an unsigned integer as an LEB128 varint for CAR framing."""
    out = bytearray()
    while True:
        chunk = value & 0x7F
        value >>= 7
        if value:
            out.append(chunk | 0x80)
        else:
            out.append(chunk)
            return bytes(out)


def _shared_prefix(left: bytes, right: bytes) -> int:
    """Return the length of the common prefix of two keys."""
    shared = 0
    for one, other in zip(left, right, strict=False):
        if one != other:
            break
        shared += 1
    return shared


class _Account:
    """One fake PDS account: a handle, a revision, and its records by key."""

    def __init__(self, handle: str, records: dict[str, dict[str, IpldValue]]) -> None:
        self.handle = handle
        self.records = records
        self.rev = "3kaaa"

    def car(self, did: str) -> tuple[bytes, str]:
        """Return the account's repository archive and its commit CID."""
        entries: list[IpldValue] = []
        blocks: dict[bytes, IpldValue] = {}
        previous = b""
        for path in sorted(self.records):
            key = path.encode()
            value_cid = _cid_bytes(self.records[path])
            shared = _shared_prefix(previous, key)
            entries.append({"p": shared, "k": key[shared:], "v": value_cid, "t": None})
            blocks[value_cid] = self.records[path]
            previous = key
        node: dict[str, IpldValue] = {"l": None, "e": entries}
        node_cid = _cid_bytes(node)
        commit: dict[str, IpldValue] = {
            "version": 3,
            "did": did,
            "data": node_cid,
            "rev": self.rev,
            "prev": None,
        }
        commit_cid = _cid_bytes(commit)
        header = libipld.encode_dag_cbor({"roots": [commit_cid], "version": 1})
        car = bytearray(_varint(len(header)) + header)
        for cid, value in {commit_cid: commit, node_cid: node, **blocks}.items():
            section = cid + libipld.encode_dag_cbor(value)
            car += _varint(len(section)) + section
        return bytes(car), CID.decode(commit_cid).encode("base32")


class _FakePds:
    """A fake PDS serving the XRPC methods a dataset pull uses."""

    def __init__(self, accounts: dict[str, _Account]) -> None:
        self.accounts = accounts
        self.fetched: list[str] = []
        self.failing: set[str] = set()

    def client(self) -> PdsClient:
        """Return a PDS client wired to this fake."""
        transport = httpx.MockTransport(self._handle)
        return PdsClient(_ENDPOINT, httpx.Client(transport=transport))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.removeprefix("/xrpc/")
        params = request.url.params
        if method == "com.atproto.identity.resolveHandle":
            return self._resolve_handle(params["handle"])
        if method == "com.atproto.repo.describeRepo":
            return self._describe(params["repo"])
        return self._sync(method, params["did"])

    def _resolve_handle(self, handle: str) -> httpx.Response:
        for did, account in self.accounts.items():
            if account.handle == handle:
                return httpx.Response(200, json={"did": did})
        return httpx.Response(400, json={"error": "InvalidRequest"})

    def _describe(self, did: str) -> httpx.Response:
        account = self.accounts.get(did)
        if account is None:
            return httpx.Response(400, json={"error": "RepoNotFound"})
        return httpx.Response(200, json={"handle": account.handle})

    def _sync(self, method: str, did: str) -> httpx.Response:
        account = self.accounts.get(did)
        if account is None:
            return httpx.Response(400, json={"error": "RepoNotFound"})
        car, commit = account.car(did)
        if method == "com.atproto.sync.getLatestCommit":
            return httpx.Response(200, json={"cid": commit, "rev": account.rev})
        if did in self.failing:
            return httpx.Response(503)
        self.fetched.append(did)
        return httpx.Response(200, content=car)


def _expression(text: str, parent: str | None = None) -> dict[str, IpldValue]:
    """Build a wire-shaped expression record, explicit nulls included."""
    return {
        "$type": "pub.layers.expression.expression",
        "id": text,
        "kind": "sentence",
        "text": f"{text} naïve 中文",
        "parentRef": parent,
        "languages": [],
        "metadata": None,
        "createdAt": _STAMP,
    }


def _membership(expression: str, ordinal: int) -> dict[str, IpldValue]:
    """Build a wire-shaped corpus membership record."""
    return {
        "$type": "pub.layers.corpus.membership",
        "corpusRef": _CORPUS_URI,
        "expressionRef": expression,
        "ordinal": ordinal,
        "split": None,
        "createdAt": _STAMP,
    }


def _expression_uri(rkey: str) -> str:
    """Return the AT-URI of an expression in the fake expression account."""
    return f"at://{_EXPRESSION_DID}/pub.layers.expression.expression/{rkey}"


def _dataset() -> _FakePds:
    """Build a fake dataset spread over corpus, catalog, and data accounts."""
    ontology_uri = f"at://{_ONTOLOGY_DID}/pub.layers.ontology.ontology/upos"
    doc_uri = _expression_uri("doc")
    accounts = {
        _CORPUS_DID: _Account(
            f"corpus.{_STEM}",
            {
                "pub.layers.corpus.corpus/main": {
                    "$type": "pub.layers.corpus.corpus",
                    "name": "tb",
                    "ontologyRefs": [ontology_uri],
                    "createdAt": _STAMP,
                },
                "pub.layers.corpus.membership/m1": _membership(
                    _expression_uri("s1"), 0
                ),
                "pub.layers.corpus.membership/m2": _membership(
                    _expression_uri("s2"), 1
                ),
            },
        ),
        _CATALOG_DID: _Account(
            _STEM,
            {
                "pub.layers.catalog.collection/top": {
                    "$type": "pub.layers.catalog.collection",
                    "name": "tb",
                    "createdAt": _STAMP,
                },
            },
        ),
        _EXPRESSION_DID: _Account(
            f"expression.{_STEM}",
            {
                "pub.layers.expression.expression/doc": {
                    "$type": "pub.layers.expression.expression",
                    "id": "doc",
                    "kind": "document",
                    "createdAt": _STAMP,
                },
                "pub.layers.expression.expression/s1": _expression("s1", doc_uri),
                "pub.layers.expression.expression/s2": _expression("s2", doc_uri),
            },
        ),
        _ANNOTATION_DID: _Account(
            f"annotation.{_STEM}",
            {
                "pub.layers.annotation.annotationLayer/a1": {
                    "$type": "pub.layers.annotation.annotationLayer",
                    "expression": _expression_uri("s1"),
                    "kind": "token-tag",
                    "ontologyRef": ontology_uri,
                    "annotations": [{"label": "NOUN", "tokenIndex": 0, "value": None}],
                    "createdAt": _STAMP,
                },
            },
        ),
        _SEGMENTATION_DID: _Account(f"segmentation.{_STEM}", {}),
        _ONTOLOGY_DID: _Account(
            "upos.ud.example",
            {
                "pub.layers.ontology.ontology/upos": {
                    "$type": "pub.layers.ontology.ontology",
                    "name": "upos",
                    "createdAt": _STAMP,
                },
            },
        ),
    }
    return _FakePds(accounts)


def _pull(pds: _FakePds, into: Path, **options: bool) -> DatasetPin:
    """Pull the fake dataset into ``into`` with the given flags."""
    with pds.client() as client:
        return pull_dataset(
            _CORPUS_URI,
            into=into,
            client=client,
            endpoint=_ENDPOINT,
            with_annotations=options.get("with_annotations", False),
            with_references=options.get("with_references", False),
            refresh=options.get("refresh", False),
        )


def test_exports() -> None:
    assert set(snapshot.__all__) == {
        "PIN_FILE",
        "PIN_RECORDS_FILE",
        "AccountDrift",
        "AccountPin",
        "CollectionCount",
        "DatasetPin",
        "PinError",
        "PinVerification",
        "check_remote",
        "pull_dataset",
        "read_pin",
        "read_pin_records",
        "verify_pin",
    }


def test_pull_follows_the_corpus_to_its_data_accounts(tmp_path: Path) -> None:
    pds = _dataset()
    pin = _pull(pds, tmp_path / "tb")
    roles = {account.did: account.role for account in pin.accounts}
    # the corpus account, the base account under the same stem, and the account
    # the memberships cite for expressions; the annotations are not pulled.
    assert roles == {
        _CORPUS_DID: "corpus",
        _CATALOG_DID: "catalog",
        _EXPRESSION_DID: "reference",
    }
    assert pin.complete
    assert pin.corpus_uri == _CORPUS_URI
    assert pin.endpoint == _ENDPOINT
    assert pin.record_count == 3 + 1 + 3
    # the ontology the corpus cites is recorded as cited but not pulled.
    assert pin.external_refs == (_ONTOLOGY_DID,)
    corpus = pin.accounts[0]
    assert corpus.handle == f"corpus.{_STEM}"
    assert corpus.rev == "3kaaa"
    assert [(c.nsid, c.count) for c in corpus.collections] == [
        ("pub.layers.corpus.corpus", 1),
        ("pub.layers.corpus.membership", 2),
    ]
    assert read_pin(tmp_path / "tb") == pin


def test_pull_stores_records_exactly_as_served(tmp_path: Path) -> None:
    pds = _dataset()
    into = tmp_path / "tb"
    pin = _pull(pds, into)
    repo = Repository.open(into)
    assert pin.revision == repo.head()
    content = repo.content_at(pin.revision or "")
    uri = _expression_uri("s1")
    served = pds.accounts[_EXPRESSION_DID].records[
        "pub.layers.expression.expression/s1"
    ]
    # the wire discriminator, the explicit nulls, and non-ascii text survive.
    assert content[uri] == served
    listing = read_pin_records(into)
    assert set(listing) == set(content)
    assert listing[uri] == record_cid(content[uri])


def test_pull_with_annotations_adds_the_sibling_accounts(tmp_path: Path) -> None:
    pin = _pull(_dataset(), tmp_path / "tb", with_annotations=True)
    roles = {account.did: account.role for account in pin.accounts}
    assert roles[_ANNOTATION_DID] == "annotation"
    assert roles[_SEGMENTATION_DID] == "segmentation"
    # a sibling found by handle keeps its namespace role even though the corpus
    # also cites it.
    assert roles[_EXPRESSION_DID] == "expression"
    assert _ONTOLOGY_DID not in roles
    empty = next(a for a in pin.accounts if a.did == _SEGMENTATION_DID)
    assert empty.record_count == 0
    assert empty.revision is None
    assert verify_pin(tmp_path / "tb").ok


def test_pull_with_references_adds_every_cited_account(tmp_path: Path) -> None:
    pin = _pull(
        _dataset(),
        tmp_path / "tb",
        with_annotations=True,
        with_references=True,
    )
    roles = {account.did: account.role for account in pin.accounts}
    assert roles[_ONTOLOGY_DID] == "reference"
    assert pin.external_refs == ()
    assert pin.with_references


def test_pull_resolves_a_handle_authority(tmp_path: Path) -> None:
    pds = _dataset()
    uri = f"at://corpus.{_STEM}/pub.layers.corpus.corpus/main"
    with pds.client() as client:
        pin = pull_dataset(uri, into=tmp_path / "tb", client=client, endpoint=_ENDPOINT)
    assert pin.corpus_uri == _CORPUS_URI


def test_pull_rejects_an_unresolvable_authority(tmp_path: Path) -> None:
    pds = _dataset()
    with pds.client() as client, pytest.raises(PinError, match="cannot resolve"):
        pull_dataset(
            "at://nobody.example/pub.layers.corpus.corpus/main",
            into=tmp_path / "tb",
            client=client,
            endpoint=_ENDPOINT,
        )


def test_pull_without_the_handle_convention_follows_references(
    tmp_path: Path,
) -> None:
    pds = _dataset()
    pds.accounts[_CORPUS_DID].handle = "treebank.example"
    pin = _pull(pds, tmp_path / "tb", with_annotations=True)
    # no stem to derive siblings from, so only cited data accounts are added.
    assert {account.did for account in pin.accounts} == {_CORPUS_DID, _EXPRESSION_DID}


def test_pull_is_deterministic_and_skips_current_accounts(tmp_path: Path) -> None:
    pds = _dataset()
    first = _pull(pds, tmp_path / "a")
    assert sorted(pds.fetched) == sorted([_CORPUS_DID, _CATALOG_DID, _EXPRESSION_DID])
    other = _pull(_dataset(), tmp_path / "b")
    assert other.content_sha256 == first.content_sha256
    assert (tmp_path / "a" / PIN_RECORDS_FILE).read_bytes() == (
        tmp_path / "b" / PIN_RECORDS_FILE
    ).read_bytes()
    pds.fetched.clear()
    again = _pull(pds, tmp_path / "a")
    # nothing moved upstream, so no archive is fetched and the pin is unchanged.
    assert pds.fetched == []
    assert again.content_sha256 == first.content_sha256
    assert again.revision == first.revision
    assert again.external_refs == first.external_refs
    pds.fetched.clear()
    _pull(pds, tmp_path / "a", refresh=True)
    assert len(pds.fetched) == len(first.accounts)
    assert verify_pin(tmp_path / "a").ok


def test_interrupted_pull_resumes_where_it_stopped(tmp_path: Path) -> None:
    pds = _dataset()
    into = tmp_path / "tb"
    pds.failing.add(_EXPRESSION_DID)
    with pytest.raises(httpx.HTTPStatusError):
        _pull(pds, into)
    partial = read_pin(into)
    assert partial is not None
    assert not partial.complete
    assert partial.content_sha256 is None
    assert {a.did for a in partial.accounts} == {_CORPUS_DID, _CATALOG_DID}
    with pytest.raises(PinError, match="not complete"):
        verify_pin(into)
    # no half-written archive is left behind.
    assert not list(into.rglob("*.part"))
    pds.failing.clear()
    pds.fetched.clear()
    pin = _pull(pds, into)
    assert pds.fetched == [_EXPRESSION_DID]
    assert pin.complete
    assert pin.content_sha256 == _pull(_dataset(), tmp_path / "fresh").content_sha256
    assert verify_pin(into).ok


def test_pull_picks_up_upstream_changes(tmp_path: Path) -> None:
    pds = _dataset()
    into = tmp_path / "tb"
    first = _pull(pds, into)
    expressions = pds.accounts[_EXPRESSION_DID]
    expressions.records["pub.layers.expression.expression/s1"] = _expression("s1b")
    del expressions.records["pub.layers.expression.expression/s2"]
    expressions.rev = "3kbbb"
    with pds.client() as client:
        drift = {entry.did: entry for entry in check_remote(first, client)}
    assert drift[_EXPRESSION_DID].moved
    assert not drift[_CORPUS_DID].moved
    assert drift[_CORPUS_DID].remote_commit == drift[_CORPUS_DID].pinned_commit
    pds.fetched.clear()
    second = _pull(pds, into)
    assert pds.fetched == [_EXPRESSION_DID]
    assert second.content_sha256 != first.content_sha256
    assert second.record_count == first.record_count - 1
    content = Repository.open(into).content_at(second.revision or "")
    assert _expression_uri("s2") not in content
    assert _expression_uri("s2") not in read_pin_records(into)
    assert content[_expression_uri("s1")] == _expression("s1b")
    assert verify_pin(into).ok
    # the earlier pin still names a readable revision of the same repository.
    earlier = Repository.open(into).content_at(first.revision or "")
    assert _expression_uri("s2") in earlier


def test_check_remote_reports_an_unreachable_account(tmp_path: Path) -> None:
    pds = _dataset()
    pin = _pull(pds, tmp_path / "tb")
    del pds.accounts[_CATALOG_DID]
    with pds.client() as client:
        drift = {entry.did: entry for entry in check_remote(pin, client)}
    assert drift[_CATALOG_DID].remote_commit is None
    assert drift[_CATALOG_DID].moved


def test_pull_refuses_a_directory_pinned_to_another_corpus(tmp_path: Path) -> None:
    pds = _dataset()
    into = tmp_path / "tb"
    _pull(pds, into)
    other = f"at://{_CORPUS_DID}/pub.layers.corpus.corpus/other"
    with pds.client() as client, pytest.raises(PinError, match="already pins"):
        pull_dataset(other, into=into, client=client, endpoint=_ENDPOINT)


def test_verify_detects_a_tampered_listing(tmp_path: Path) -> None:
    into = tmp_path / "tb"
    pin = _pull(_dataset(), into)
    listing = read_pin_records(into)
    uri = _expression_uri("s1")
    dropped = _expression_uri("s2")
    extra = f"at://{_EXPRESSION_DID}/pub.layers.expression.expression/ghost"
    tampered = {**listing, uri: record_cid({"text": "other"}), extra: listing[uri]}
    del tampered[dropped]
    with gzip.open(into / PIN_RECORDS_FILE, "wt", encoding="utf-8") as handle:
        handle.writelines(f"{key}\t{cid}\n" for key, cid in sorted(tampered.items()))
    result = verify_pin(into, pin=pin)
    assert not result.ok
    assert result.changed == (uri,)
    assert result.missing == (extra,)
    assert result.unexpected == (dropped,)
    # the stored records still match the pinned digests, so nothing else fails.
    assert result.problems == ()
    assert result.record_count == pin.record_count


def test_verify_detects_a_pin_that_disagrees_with_the_store(tmp_path: Path) -> None:
    into = tmp_path / "tb"
    pin = _pull(_dataset(), into)
    accounts = tuple(
        account.with_(record_count=account.record_count + 1, records_sha256="0" * 64)
        if account.did == _EXPRESSION_DID
        else account
        for account in pin.accounts
    )
    forged = pin.with_(accounts=accounts)
    result = verify_pin(into, pin=forged)
    assert not result.ok
    assert len(result.problems) == 3
    assert any("3 record(s) stored, 4 pinned" in problem for problem in result.problems)
    assert any("record digest differs" in problem for problem in result.problems)
    assert any("content hash" in problem for problem in result.problems)


def test_verify_needs_a_pin(tmp_path: Path) -> None:
    with pytest.raises(PinError, match="has no"):
        verify_pin(tmp_path)


def test_read_pin_accepts_a_file_and_rejects_bad_manifests(tmp_path: Path) -> None:
    into = tmp_path / "tb"
    pin = _pull(_dataset(), into)
    copy = tmp_path / "kept-with-the-analysis.json"
    copy.write_text((into / PIN_FILE).read_text(encoding="utf-8"), encoding="utf-8")
    assert read_pin(copy) == pin
    assert read_pin(tmp_path / "absent.json") is None
    assert read_pin(tmp_path) is None
    copy.write_text("{not json", encoding="utf-8")
    with pytest.raises(PinError, match="cannot read the pin manifest"):
        read_pin(copy)
    newer = pin.with_(pin_version=snapshot.PIN_VERSION + 1)
    copy.write_text(newer.model_dump_json(), encoding="utf-8")
    with pytest.raises(PinError, match="format version"):
        read_pin(copy)


def test_read_pin_records_rejects_a_malformed_listing(tmp_path: Path) -> None:
    assert read_pin_records(tmp_path) == {}
    with gzip.open(tmp_path / PIN_RECORDS_FILE, "wt", encoding="utf-8") as handle:
        handle.write("no-tab-here\n")
    with pytest.raises(PinError, match="malformed line"):
        read_pin_records(tmp_path)
    (tmp_path / PIN_RECORDS_FILE).write_bytes(b"not gzip")
    with pytest.raises(PinError, match="cannot read the pinned record listing"):
        read_pin_records(tmp_path)


def test_pull_rejects_an_archive_without_a_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pds = _dataset()
    monkeypatch.setattr(snapshot, "read_repo_car_commit", lambda _path: None)
    with pytest.raises(PinError, match="no signed commit"):
        _pull(pds, tmp_path / "tb")
    assert not list((tmp_path / "tb").rglob("*.car"))


def test_progress_reports_each_account(tmp_path: Path) -> None:
    pds = _dataset()
    lines: list[str] = []
    with pds.client() as client:
        pull_dataset(
            _CORPUS_URI,
            into=tmp_path / "tb",
            client=client,
            endpoint=_ENDPOINT,
            progress=lines.append,
        )
        pull_dataset(
            _CORPUS_URI,
            into=tmp_path / "tb",
            client=client,
            endpoint=_ENDPOINT,
            progress=lines.append,
        )
    assert f"pulling {_CORPUS_DID} (corpus)" in lines
    assert f"pulled corpus.{_STEM}: 3 record(s)" in lines
    assert f"up to date: corpus.{_STEM} (3)" in lines


def test_content_hash_is_the_digest_of_the_account_digests(tmp_path: Path) -> None:
    pin = _pull(_dataset(), tmp_path / "tb")
    digest = hashlib.sha256()
    for account in sorted(pin.accounts, key=lambda entry: entry.did):
        digest.update(f"{account.did}\t{account.records_sha256}\n".encode())
    assert pin.content_sha256 == digest.hexdigest()
    listing = read_pin_records(tmp_path / "tb")
    corpus = pin.accounts[0]
    own = hashlib.sha256()
    for uri in sorted(listing):
        if uri.startswith(f"at://{_CORPUS_DID}/"):
            own.update(f"{uri}\t{listing[uri]}\n".encode())
    assert corpus.records_sha256 == own.hexdigest()
