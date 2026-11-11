"""Unit and integration tests for lairs.store.repository."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING

import didactic.api as dx
import panproto
import pytest

from lairs.records._generated.defs import ObjectRef
from lairs.records._generated.judgment import DecimalValue, Judgment
from lairs.store import repository
from lairs.store.repository import RecordDiff, Repository, Workspace

if TYPE_CHECKING:
    from collections.abc import Iterator

    from lairs._types import JsonValue


class _Expr(dx.Model):
    """A throwaway expression-like record for repository tests."""

    text: str


_EXPR_URI = "at://did:plc:abc/pub.layers.expression.expression/e1"
_MEDIA_URI = "at://did:plc:abc/pub.layers.media.media/m1"
_JUDGMENT_URI = "at://did:plc:abc/pub.layers.judgment.judgmentSet/j1"
# one committed fixture repository per panproto committed-data carrier: 0.71 and
# 0.72.1 committed source JSON, 0.74.3 commits canonical messagepack. all three
# hold the same save/update/forget history, so history reads must agree.
_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_FIXTURE_VERSIONS = ("0.71", "0.72.1", "0.74.3")
_FIXTURE_URI = "at://did:plc:abc/pub.layers.expression.expression/e1"
# the content_at result every fixture must produce at its three revisions.
_FIXTURE_HISTORY: tuple[dict[str, JsonValue], ...] = (
    {_FIXTURE_URI: {"text": "café"}},
    {_FIXTURE_URI: {"text": "naïve"}},
    {},
)


def _open_fixture(version: str, tmp_path: Path) -> tuple[Repository, list[str]]:
    """Copy a fixture repository into ``tmp_path`` and open it.

    Returns the opened repository and its ``[base, updated, deleted]`` commit
    ids, in history order.
    """
    target = tmp_path / f"panproto-{version}"
    shutil.copytree(_FIXTURES_DIR / f"panproto-{version}-repository", target)
    metadata = json.loads((target / "fixture.json").read_text(encoding="utf-8"))
    assert metadata["uri"] == _FIXTURE_URI
    revisions = [str(metadata[name]) for name in ("base", "updated", "deleted")]
    return Repository.open(target), revisions


def _stored_object(repo: Repository, object_id: str) -> Path:
    """Return the on-disk path of a stored panproto object."""
    return repo.path / ".panproto" / "objects" / object_id[:2] / object_id[2:]


def _as_stored_data(payload: bytes) -> bytes:
    """Return ``payload`` as panproto persists committed data bytes.

    panproto stores committed data bytes inside a messagepack data-set object
    as an array of unsigned integers, so a byte at or above 0x80 appears as a
    two-byte ``0xcc`` prefixed uint8 rather than as itself.
    """
    return b"".join(
        bytes([byte]) if byte < 0x80 else b"\xcc" + bytes([byte]) for byte in payload
    )


def _object_holding(repo: Repository, needle: bytes) -> Path:
    """Return the one non-commit stored object whose bytes contain ``needle``."""
    matches = [
        path
        for path in (repo.path / ".panproto" / "objects").rglob("*")
        if path.is_file()
        and needle in path.read_bytes()
        and not path.read_bytes().startswith(b"\x81\xa6Commit")
    ]
    assert len(matches) == 1
    return matches[0]


def _tamper(path: Path, old: bytes, new: bytes) -> None:
    """Rewrite one occurrence of ``old`` as the same-length ``new`` in place.

    A same-length substitution inside a string field keeps the object
    decodable, so the only thing that can reject it is the check of its
    identifier against the persisted bytes.
    """
    assert len(old) == len(new)
    payload = path.read_bytes()
    assert payload.count(old) == 1
    path.write_bytes(payload.replace(old, new))


def test_exports() -> None:
    assert set(repository.__all__) == {
        "STORE_LAYOUT_VERSION",
        "RecordDiff",
        "Repository",
        "Workspace",
    }


def test_record_diff_defaults_are_empty() -> None:
    diff = RecordDiff()
    assert diff.added == ()
    assert diff.removed == ()
    assert diff.changed == ()


def test_save_load_round_trip(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")
    repo.save(_EXPR_URI, _Expr(text="hello"))
    assert repo.staged_uris() == [_EXPR_URI]
    loaded = repo.load(_EXPR_URI, _Expr)
    assert isinstance(loaded, _Expr)
    assert loaded.text == "hello"
    assert repo.load_raw(_EXPR_URI) == {"text": "hello"}


def test_continuous_judgment_survives_commit_and_read(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")
    judgment = Judgment(
        item=ObjectRef(recordRef=_EXPR_URI),
        continuousValue=DecimalValue(coefficient=73, exponent=-2),
    )
    repo.save(_JUDGMENT_URI, judgment)
    revision = repo.commit("continuous judgment")

    reopened = Repository.open(tmp_path / "repo")
    assert reopened.load(_JUDGMENT_URI, Judgment) == judgment
    content = reopened.content_at(revision)[_JUDGMENT_URI]
    assert isinstance(content, dict)
    assert content["continuousValue"] == {"coefficient": 73, "exponent": -2}


def test_load_absent_uri_returns_none(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")
    assert repo.load(_EXPR_URI, _Expr) is None
    assert repo.load_raw(_EXPR_URI) is None


def test_tag_without_head_raises(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")
    with pytest.raises(ValueError, match="empty repository"):
        repo.tag("v1")


def test_schema_diff_reports_vertex_changes(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")

    class _ExprV2(dx.Model):
        text: str
        lang: str | None = None

    diff = repo.schema_diff(_Expr, _ExprV2)
    added = diff["added_vertices"]
    removed = diff["removed_vertices"]
    assert isinstance(added, list)
    assert isinstance(removed, list)
    assert "_ExprV2" in added
    assert "_Expr" in removed


def test_workspace_groups_by_nsid(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")
    repo.save(_EXPR_URI, _Expr(text="e"))
    repo.save(_MEDIA_URI, _Expr(text="m"))
    workspace = Workspace(repo)
    assert workspace.nsids() == [
        "pub.layers.expression.expression",
        "pub.layers.media.media",
    ]
    assert workspace.uris_of("pub.layers.expression.expression") == [_EXPR_URI]
    assert workspace.uris_of("pub.layers.media.media") == [_MEDIA_URI]
    assert workspace.uris_of("pub.layers.absent.absent") == []


@pytest.mark.integration
def test_commit_tag_round_trip_is_reproducible(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")
    repo.save(_EXPR_URI, _Expr(text="hello"))
    revision = repo.commit("initial snapshot")
    assert repo.head() == revision
    assert len(repo.log()) == 1

    repo.tag("v1")
    assert ("v1", revision) in repo.tags()
    assert repo.resolve("v1") == revision

    # the tagged revision pins the exact record value.
    reopened = Repository.open(tmp_path / "repo")
    assert reopened.load(_EXPR_URI, _Expr) == _Expr(text="hello")


@pytest.mark.integration
def test_diff_resolves_both_refs(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")
    repo.save(_EXPR_URI, _Expr(text="hello"))
    revision = repo.commit("snapshot")
    repo.tag("v1")
    diff = repo.diff("v1", revision)
    assert isinstance(diff, RecordDiff)


def test_committed_values_are_readable_at_revision(tmp_path: Path) -> None:
    # current panproto stores a canonical carrier, so the public decoded read is
    # the supported way to recover the source JSON value.
    repo = Repository.init(tmp_path / "repo")
    repo.save(_EXPR_URI, _Expr(text="café"))
    revision = repo.commit("snapshot")
    native = panproto.Repository.open(str(repo.path))
    assert native.decoded_data_at(revision) == [
        {
            "schema_id": native.decoded_data_at(revision)[0]["schema_id"],
            "records": [{"text": "café"}],
            "record_count": 1,
            "key": _EXPR_URI,
        },
    ]


def test_tag_uses_public_create_tag(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")
    repo.save(_EXPR_URI, _Expr(text="hello"))
    revision = repo.commit("snapshot")
    repo.tag("v0.1")
    assert ("v0.1", revision) in repo.tags()


def test_diff_across_revisions_reads_committed_data(tmp_path: Path) -> None:
    # diff folds data_at over each revision's ancestry, keyed by AT-URI, so a
    # changed value and an added record are both detected across two commits.
    repo = Repository.init(tmp_path / "repo")
    repo.save(_EXPR_URI, _Expr(text="one"))
    repo.save(_MEDIA_URI, _Expr(text="keep"))
    base = repo.commit("base snapshot")
    other = "at://did:plc:abc/pub.layers.expression.expression/e2"
    repo.save(_EXPR_URI, _Expr(text="one-changed"))
    repo.save(other, _Expr(text="new"))
    head = repo.commit("head snapshot")
    diff = repo.diff(base, head)
    assert diff.added == (other,)
    assert diff.changed == (_EXPR_URI,)
    assert diff.removed == ()


def test_state_at_folds_latest_value_over_linear_ancestry(tmp_path: Path) -> None:
    # the post-order ancestry fold lets the newest commit's value win across a
    # multi-commit linear history, not just a two-commit one.
    repo = Repository.init(tmp_path / "repo")
    repo.save(_EXPR_URI, _Expr(text="v1"))
    base = repo.commit("c1")
    repo.save(_EXPR_URI, _Expr(text="v2"))
    repo.commit("c2")
    repo.save(_EXPR_URI, _Expr(text="v3"))
    head = repo.commit("c3")
    diff = repo.diff(base, head)
    assert diff.changed == (_EXPR_URI,)
    assert repo._state_at(head) == {_EXPR_URI: {"text": "v3"}}


def test_safe_name_is_collision_free() -> None:
    # two AT-URIs that the old slash/colon substitution collapsed onto one stem
    # must now map to distinct file stems.
    colliding = "at://did_plc_a/c/r"
    real = "at://did:plc:a/c/r"
    assert repository._safe_name(colliding) != repository._safe_name(real)


def test_save_distinct_uris_do_not_overwrite(tmp_path: Path) -> None:
    # the two URIs below collide under a naive slash/colon encoding; each must
    # keep its own value on disk.
    repo = Repository.init(tmp_path / "repo")
    uri_a = "at://did:plc:a/c/r"
    uri_b = "at://did_plc_a/c/r"
    repo.save(uri_a, _Expr(text="value-a"))
    repo.save(uri_b, _Expr(text="value-b"))
    assert repo.load(uri_a, _Expr) == _Expr(text="value-a")
    assert repo.load(uri_b, _Expr) == _Expr(text="value-b")


def test_forget_removes_from_working_tree(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")
    repo.save(_EXPR_URI, _Expr(text="hello"))
    repo.forget(_EXPR_URI)
    assert repo.staged_uris() == []
    assert repo.load(_EXPR_URI, _Expr) is None
    assert repo.load_raw(_EXPR_URI) is None


def test_forget_absent_uri_raises(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")
    with pytest.raises(KeyError, match="not in the working tree"):
        repo.forget(_EXPR_URI)


def test_diff_reports_removed_after_forget(tmp_path: Path) -> None:
    # a record present at base and forgotten before head appears in removed; the
    # tombstone committed by forget drops it from the head state.
    repo = Repository.init(tmp_path / "repo")
    repo.save(_EXPR_URI, _Expr(text="one"))
    repo.save(_MEDIA_URI, _Expr(text="keep"))
    base = repo.commit("base snapshot")
    repo.forget(_EXPR_URI)
    head = repo.commit("head snapshot")
    diff = repo.diff(base, head)
    assert diff.removed == (_EXPR_URI,)
    assert diff.added == ()
    assert diff.changed == ()


def test_content_at_returns_decoded_values_keyed_by_uri(tmp_path: Path) -> None:
    # content_at returns source-JSON-equivalent values, keyed by AT-URI, so
    # callers never need to know the canonical committed-data carrier.
    repo = Repository.init(tmp_path / "repo")
    repo.save(_EXPR_URI, _Expr(text="café"))
    repo.save(_MEDIA_URI, _Expr(text="world"))
    revision = repo.commit("snapshot")
    content = repo.content_at(revision)
    assert content == {
        _EXPR_URI: {"text": "café"},
        _MEDIA_URI: {"text": "world"},
    }


def test_reopen_preserves_commit_identity_and_historical_content(
    tmp_path: Path,
) -> None:
    repo = Repository.init(tmp_path / "repo")
    repo.save(_EXPR_URI, _Expr(text="first"))
    base = repo.commit("base snapshot")
    repo.save(_EXPR_URI, _Expr(text="second"))
    head = repo.commit("head snapshot")
    repo.tag("v1", revision=base)

    reopened = Repository.open(tmp_path / "repo")

    assert reopened.resolve("v1") == base
    assert reopened.head() == head
    assert reopened.content_at(base) == {_EXPR_URI: {"text": "first"}}
    assert reopened.content_at(head) == {_EXPR_URI: {"text": "second"}}


def test_content_at_reflects_update_across_commits(tmp_path: Path) -> None:
    # the latest value wins, matching the byte-level fold behind diff.
    repo = Repository.init(tmp_path / "repo")
    repo.save(_EXPR_URI, _Expr(text="one"))
    repo.commit("base snapshot")
    repo.save(_EXPR_URI, _Expr(text="two"))
    head = repo.commit("head snapshot")
    assert repo.content_at(head) == {_EXPR_URI: {"text": "two"}}


def test_content_at_omits_tombstoned_record(tmp_path: Path) -> None:
    # a record forgotten before the revision is absent from the decoded state.
    repo = Repository.init(tmp_path / "repo")
    repo.save(_EXPR_URI, _Expr(text="gone"))
    repo.save(_MEDIA_URI, _Expr(text="keep"))
    repo.commit("base snapshot")
    repo.forget(_EXPR_URI)
    head = repo.commit("head snapshot")
    assert repo.content_at(head) == {_MEDIA_URI: {"text": "keep"}}


def test_content_at_unknown_ref_raises(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")
    repo.save(_EXPR_URI, _Expr(text="hello"))
    repo.commit("snapshot")
    with pytest.raises(panproto.VcsError, match="ref not found"):
        repo.content_at("not-a-real-ref")


@pytest.mark.parametrize("version", _FIXTURE_VERSIONS)
def test_historical_panproto_repository_keeps_ids_values_and_tombstones(
    version: str,
    tmp_path: Path,
) -> None:
    # a repository committed under an earlier panproto must read back exactly
    # as one committed under the current release: same commit ids resolve, the
    # same values come back at each revision, and the forgotten record is
    # absent at the tombstoned head rather than resurfacing.
    repo, (base, updated, deleted) = _open_fixture(version, tmp_path)

    assert repo.resolve(base) == base
    assert repo.resolve(updated) == updated
    assert repo.resolve(deleted) == deleted
    assert repo.head() == deleted
    assert [entry["id"] for entry in repo.log()] == [deleted, updated, base]
    assert repo.content_at(base) == _FIXTURE_HISTORY[0]
    assert repo.content_at(updated) == _FIXTURE_HISTORY[1]
    assert repo.content_at(deleted) == _FIXTURE_HISTORY[2]
    assert repo.diff(base, updated) == RecordDiff(changed=(_FIXTURE_URI,))
    assert repo.diff(updated, deleted) == RecordDiff(removed=(_FIXTURE_URI,))


@pytest.mark.parametrize("version", _FIXTURE_VERSIONS)
def test_content_at_returns_plain_json_values_for_every_carrier(
    version: str,
    tmp_path: Path,
) -> None:
    # downstream callers serialize content_at straight back to JSON, so the
    # values must be plain python json types whatever the committed carrier
    # was: never bytes, never panproto instances.
    repo, revisions = _open_fixture(version, tmp_path)
    for revision, expected in zip(revisions, _FIXTURE_HISTORY, strict=True):
        content = repo.content_at(revision)
        encoded = json.dumps(content, sort_keys=True)
        assert json.loads(encoded) == expected
        assert encoded == json.dumps(expected, sort_keys=True)


def test_fixture_carriers_differ_but_decode_identically(tmp_path: Path) -> None:
    # the point of pinning both fixtures: 0.72.1 committed the source json
    # bytes, 0.74.3 commits canonical messagepack, and content_at hides the
    # difference. this guards against a future carrier change going unnoticed.
    legacy, (legacy_base, _, _) = _open_fixture("0.72.1", tmp_path)
    current, (current_base, _, _) = _open_fixture("0.74.3", tmp_path)
    legacy_raw = legacy.inner.data_at(legacy_base)[0].data
    current_raw = current.inner.data_at(current_base)[0].data
    assert json.loads(legacy_raw) == {"text": "café"}
    with pytest.raises((json.JSONDecodeError, UnicodeDecodeError)):
        json.loads(current_raw)
    assert legacy.content_at(legacy_base) == current.content_at(current_base)


def test_content_at_rejects_a_tampered_committed_data_object(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")
    sentinel = "tamper-sentinel-data"
    repo.save(_EXPR_URI, _Expr(text=sentinel))
    revision = repo.commit("snapshot")
    target = _object_holding(repo, _as_stored_data(sentinel.encode()))
    _tamper(target, b"tamper-sentinel", b"tamper-sentinal")

    with pytest.raises(panproto.VcsError, match="corrupted"):
        repo.content_at(revision)


@pytest.mark.parametrize("version", _FIXTURE_VERSIONS)
def test_tampered_commit_object_fails_identifier_check(
    version: str,
    tmp_path: Path,
) -> None:
    # commit identifiers are checked against the persisted bytes, not against
    # a re-encoding of the decoded commit. this matters for the historical
    # fixtures, whose commit objects lack fields the current shape defaults:
    # re-encoding those would hash to a different id and the untampered
    # fixture test would fail, while a flipped stored byte must still fail.
    repo, (_, updated, deleted) = _open_fixture(version, tmp_path)
    _tamper(_stored_object(repo, updated), b"lairs@layers.pub", b"lairs@layers.puB")

    with pytest.raises(panproto.VcsError, match="corrupted: stored bytes hash"):
        repo.log()
    with pytest.raises(panproto.VcsError, match="corrupted: stored bytes hash"):
        repo.content_at(deleted)


@pytest.mark.parametrize("version", _FIXTURE_VERSIONS)
def test_tampered_data_object_fails_identifier_check(
    version: str,
    tmp_path: Path,
) -> None:
    # a corrupted data object poisons the revision that recorded it and every
    # descendant, since the ancestry fold reads it for both, while revisions
    # before it still read cleanly and commit traversal is unaffected.
    repo, (base, updated, deleted) = _open_fixture(version, tmp_path)
    stored = _as_stored_data("naïve".encode())
    _tamper(_object_holding(repo, stored), stored, _as_stored_data("naïvE".encode()))

    assert [entry["id"] for entry in repo.log()] == [deleted, updated, base]
    assert repo.content_at(base) == _FIXTURE_HISTORY[0]
    with pytest.raises(panproto.VcsError, match="corrupted: stored bytes hash"):
        repo.content_at(updated)
    with pytest.raises(panproto.VcsError, match="corrupted: stored bytes hash"):
        repo.content_at(deleted)


def test_keyed_committed_data_must_contain_one_record() -> None:
    dataset: dict[str, JsonValue] = {
        "key": _EXPR_URI,
        "records": [{"text": "one"}, {"text": "two"}],
    }
    with pytest.raises(panproto.VcsError, match="expected 1"):
        repository._keyed_record(dataset)


# bulk staging and the packed layout ---------------------------------------------

_PACKED_FIXTURE = _FIXTURES_DIR / "panproto-0.74.3-packed-repository"
_LAYER_URI = "at://did:plc:abc/pub.layers.annotation.annotationLayer/l1"
# a record as a PDS serves it: the wire ``$type``, explicit nulls, nested empty
# lists, non-ascii text, an integer beyond 64 bits, floats, and a dag-json link.
_RAW_LAYER: dict[str, JsonValue] = {
    "$type": "pub.layers.annotation.annotationLayer",
    "kind": "token-tag",
    "metadata": None,
    "annotations": [
        {"label": "NOUN", "childIds": [], "features": {"entries": []}},
        {"label": "VERB", "text": "\u00e7al\u0131\u015ft\u0131 🎉", "confidence": None},
    ],
    "rank": 18446744073709551617,
    "negative": -(2**70),
    "scores": [0.1, 1.0, -2.5e-08, 1e300],
    "source": {"$link": "bafyreigh2akiscaildcqabsyg3dfr6chu3fgpregiymsck7e7aqa4s52zy"},
    "zebra": "keys stay in the order given, not sorted",
    "alpha": {"nested": [[], {}, [None]]},
}
_PACKED_HISTORY: tuple[dict[str, JsonValue], ...] = (
    {
        "at://did:plc:abc/pub.layers.expression.expression/e1": {"text": "café"},
        "at://did:plc:abc/pub.layers.expression.expression/e2": {"text": "keep"},
    },
    {
        "at://did:plc:abc/pub.layers.annotation.annotationLayer/l1": {
            "$type": "pub.layers.annotation.annotationLayer",
            "kind": "token-tag",
            "metadata": None,
            "annotations": [
                {"label": "NOUN", "childIds": [], "features": {"entries": []}},
                {
                    "label": "VERB",
                    "text": "\u00e7al\u0131\u015ft\u0131",
                    "confidence": None,
                },
            ],
            "rank": 18446744073709551617,
            "scores": [0.1, 1.0, -2.5e-08],
            "source": {
                "$link": "bafyreigh2akiscaildcqabsyg3dfr6chu3fgpregiymsck7e7aqa4s52zy",
            },
        },
        "at://did:plc:abc/pub.layers.annotation.annotationLayer/l2": {
            "$type": "pub.layers.annotation.annotationLayer",
            "kind": "span",
            "annotations": [],
        },
        "at://did:plc:abc/pub.layers.expression.expression/e1": {"text": "café"},
        "at://did:plc:abc/pub.layers.expression.expression/e2": {"text": "keep"},
        "at://did:plc:abc/pub.layers.expression.expression/e3": {"text": "packed"},
    },
)


class _Other(dx.Model):
    """A second throwaway record type, for interleaving."""

    n: int
    label: str | None = None


def _uri(collection: str, index: int) -> str:
    return f"at://did:plc:abc/{collection}/r{index:05d}"


def _expr_records(count: int) -> list[tuple[str, dx.Model]]:
    return [
        (_uri("pub.layers.expression.expression", i), _Expr(text=f"t{i} é"))
        for i in range(count)
    ]


def _mixed_records(count: int) -> list[tuple[str, dx.Model]]:
    records: list[tuple[str, dx.Model]] = []
    for i in range(count):
        if i % 2:
            records.append((_uri("pub.layers.media.media", i), _Other(n=i)))
        else:
            records.append(
                (_uri("pub.layers.expression.expression", i), _Expr(text=f"t{i}")),
            )
    return records


class _CallCounter:
    """Count calls through a wrapped didactic repository method."""

    def __init__(self, name: str) -> None:
        self.calls = 0
        self._wrapped = getattr(dx.Repository, name)

    def __call__(
        self,
        repo: dx.Repository,
        *args: str | Path | type[dx.Model],
        **kwargs: str | None,
    ) -> None:
        self.calls += 1
        self._wrapped(repo, *args, **kwargs)


def _count(monkeypatch: pytest.MonkeyPatch, name: str) -> _CallCounter:
    # didactic's repository has slots, so the method is wrapped on the class;
    # a counting function (not a callable instance) binds as a method.
    counter = _CallCounter(name)

    def counted(
        repo: dx.Repository,
        *args: str | Path | type[dx.Model],
        **kwargs: str | None,
    ) -> None:
        counter(repo, *args, **kwargs)

    monkeypatch.setattr(dx.Repository, name, counted)
    return counter


def test_save_many_reads_back_as_save_does(tmp_path: Path) -> None:
    records = _mixed_records(20)
    records.append(
        (
            _JUDGMENT_URI,
            Judgment(
                item=ObjectRef(recordRef=_EXPR_URI),
                continuousValue=DecimalValue(coefficient=73, exponent=-2),
            ),
        ),
    )
    single = Repository.init(tmp_path / "single")
    for uri, model in records:
        single.save(uri, model)
    bulk = Repository.init(tmp_path / "bulk")
    assert bulk.save_many(records) == len(records)
    single_content = single.content_at(single.commit("per record"))
    bulk_content = bulk.content_at(bulk.commit("packed"))
    assert bulk_content == single_content
    assert json.dumps(bulk_content, sort_keys=True) == json.dumps(
        single_content,
        sort_keys=True,
    )
    assert bulk.staged_uris() == single.staged_uris()


def test_save_many_raw_is_lossless(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")
    assert repo.save_many_raw([(_LAYER_URI, _RAW_LAYER)]) == 1
    revision = repo.commit("raw snapshot")
    for reader in (repo, Repository.open(tmp_path / "repo")):
        stored = reader.content_at(revision)[_LAYER_URI]
        # same keys in the same order, same nulls, same numbers and types.
        assert json.dumps(stored, ensure_ascii=False) == json.dumps(
            _RAW_LAYER,
            ensure_ascii=False,
        )
        assert stored == _RAW_LAYER
        assert isinstance(stored, dict)
        assert isinstance(stored["rank"], int)
        assert reader.load_raw(_LAYER_URI) == _RAW_LAYER


def test_per_record_path_coerces_integers_beyond_64_bits(tmp_path: Path) -> None:
    # documents the one known divergence between the layouts: panproto's
    # schema-bound path turns an integer outside the 64-bit range into a float,
    # while the packed layout keeps it exact.
    class _Big(dx.Model):
        n: int

    repo = Repository.init(tmp_path / "repo")
    repo.save(_EXPR_URI, _Big(n=2**64 - 1))
    repo.save_many([(_MEDIA_URI, _Big(n=2**64 - 1))])
    content = repo.content_at(repo.commit("big"))
    assert content[_EXPR_URI] == {"n": float(2**64 - 1)}
    assert content[_MEDIA_URI] == {"n": 2**64 - 1}


def test_load_validates_a_raw_record_without_its_wire_type(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")
    raw: dict[str, JsonValue] = {"$type": "pub.layers.expression.expression"}
    raw["text"] = "hi"
    repo.save_many_raw([(_EXPR_URI, raw)])
    assert repo.load(_EXPR_URI, _Expr) == _Expr(text="hi")
    assert repo.load_raw(_EXPR_URI) == raw


def test_save_many_raw_stores_unknown_collections(tmp_path: Path) -> None:
    uri = "at://did:plc:abc/com.example.unknown/x"
    repo = Repository.init(tmp_path / "repo")
    repo.save_many_raw([(uri, {"$type": "com.example.unknown", "v": [1, 2]})])
    assert repo.content_at(repo.commit("unknown")) == {
        uri: {"$type": "com.example.unknown", "v": [1, 2]},
    }


def test_save_many_raw_rejects_non_finite_floats(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")
    with pytest.raises(ValueError, match="Out of range float"):
        repo.save_many_raw([(_EXPR_URI, {"x": float("nan")})])


def test_save_many_consumes_a_lazy_iterable(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")
    consumed: list[int] = []

    def records() -> Iterator[tuple[str, dx.Model]]:
        for i in range(10):
            consumed.append(i)
            yield _uri("pub.layers.expression.expression", i), _Expr(text=str(i))

    generator = records()
    assert consumed == []
    assert repo.save_many(generator, batch_size=3) == 10
    assert consumed == list(range(10))
    assert len(repo.content_at(repo.commit("lazy"))) == 10


def test_save_many_called_repeatedly_before_one_commit(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")
    first = _expr_records(5)
    second = [(_uri("pub.layers.media.media", i), _Other(n=i)) for i in range(4)]
    assert repo.save_many(first) == 5
    assert repo.save_many(second) == 4
    assert repo.save_many_raw([(_LAYER_URI, _RAW_LAYER)]) == 1
    revision = repo.commit("one commit")
    assert len(repo.log()) == 1
    content = repo.content_at(revision)
    assert len(content) == 10
    assert content[second[2][0]] == {"n": 2, "label": None}


def test_save_many_interleaves_model_types(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")
    records = _mixed_records(9)
    repo.save_many(records, batch_size=2)
    content = repo.content_at(repo.commit("mixed types"))
    assert content == {uri: json.loads(m.model_dump_json()) for uri, m in records}
    for uri, model in records:
        assert repo.load(uri, type(model)) == model


def test_save_many_keeps_the_later_value_of_a_repeated_uri(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")
    records: list[tuple[str, dx.Model]] = [
        (_EXPR_URI, _Expr(text="first")),
        (_MEDIA_URI, _Expr(text="other")),
        (_EXPR_URI, _Expr(text="second")),
    ]
    repo.save_many(records, batch_size=2)
    assert repo.load(_EXPR_URI, _Expr) == _Expr(text="second")
    assert repo.content_at(repo.commit("dup"))[_EXPR_URI] == {"text": "second"}


def test_save_many_of_nothing_stages_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = Repository.init(tmp_path / "repo")
    add_data = _count(monkeypatch, "add_data")
    assert repo.save_many([]) == 0
    assert repo.save_many_raw(iter(())) == 0
    assert add_data.calls == 0
    assert repo.staged_uris() == []
    assert not repo.inner.has_staged()


def test_save_many_rejects_a_non_positive_batch_size(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")
    with pytest.raises(ValueError, match="batch_size must be positive"):
        repo.save_many(_expr_records(1), batch_size=0)


def test_save_many_stages_what_it_consumed_before_an_error(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")

    def records() -> Iterator[tuple[str, dx.Model]]:
        yield from _expr_records(3)
        msg = "source failed"
        raise RuntimeError(msg)

    with pytest.raises(RuntimeError, match="source failed"):
        repo.save_many(records())
    assert len(repo.staged_uris()) == 3
    assert len(repo.content_at(repo.commit("partial"))) == 3


def test_native_staging_calls_scale_with_packs_not_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the per-record path made one native staging call per record, each costing
    # more as the staged set grew. the packed path must make one call per pack
    # and stage each schema once, however many records it is given.
    for count, expected_packs in ((200, 2), (2000, 16)):
        repo = Repository.init(tmp_path / f"repo-{count}")
        add_data = _count(monkeypatch, "add_data")
        add = _count(monkeypatch, "add")
        repo.save_many(_mixed_records(count), batch_size=128)
        assert add_data.calls == expected_packs
        assert add.calls == 1


def test_save_stages_an_unchanged_schema_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = Repository.init(tmp_path / "repo")
    add = _count(monkeypatch, "add")
    for uri, model in _expr_records(5):
        repo.save(uri, model)
    assert add.calls == 1
    repo.save(_MEDIA_URI, _Other(n=1))
    repo.save(_EXPR_URI, _Expr(text="back"))
    assert add.calls == 3


def test_save_journals_the_index_and_commit_compacts_it(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")
    for uri, model in _expr_records(3):
        repo.save(uri, model)
    repo.save_many(_expr_records(5)[3:])
    journal = repo.path / "index.log"
    assert journal.exists()
    assert not (repo.path / "index.json").exists()
    repo.commit("snapshot")
    assert not journal.exists()
    index = json.loads((repo.path / "index.json").read_text(encoding="utf-8"))
    assert sorted(index) == [uri for uri, _ in _expr_records(5)]
    assert Repository.open(repo.path).staged_uris() == sorted(index)


def test_index_journal_skips_a_torn_last_line(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")
    repo.save(_EXPR_URI, _Expr(text="kept"))
    with (repo.path / "index.log").open("a", encoding="utf-8") as journal:
        journal.write('{"uri": "at://did:plc:abc/c/torn", "lo')
    reopened = Repository.open(repo.path)
    assert reopened.staged_uris() == [_EXPR_URI]


def test_bulk_writes_survive_reopen_before_and_after_commit(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")
    records = _mixed_records(6)
    repo.save_many(records)
    repo.save_many_raw([(_LAYER_URI, _RAW_LAYER)])
    expected_uris = sorted([uri for uri, _ in records] + [_LAYER_URI])
    reopened = Repository.open(tmp_path / "repo")
    assert reopened.staged_uris() == expected_uris
    assert reopened.load(records[1][0], _Other) == records[1][1]
    revision = reopened.commit("after reopen")
    again = Repository.open(tmp_path / "repo")
    assert again.staged_uris() == expected_uris
    assert again.load_raw(_LAYER_URI) == _RAW_LAYER
    assert again.load(records[0][0], _Expr) == records[0][1]
    assert len(again.content_at(revision)) == len(expected_uris)
    assert Workspace(again).uris_of("pub.layers.media.media") == sorted(
        uri for uri, _ in records if "media" in uri
    )


def test_mixed_layout_history_updates_and_forgets_across_layouts(
    tmp_path: Path,
) -> None:
    repo = Repository.init(tmp_path / "repo")
    per_record = "at://did:plc:abc/pub.layers.expression.expression/p"
    packed = "at://did:plc:abc/pub.layers.expression.expression/k"
    doomed_per_record = "at://did:plc:abc/pub.layers.expression.expression/dp"
    doomed_packed = "at://did:plc:abc/pub.layers.expression.expression/dk"
    repo.save(per_record, _Expr(text="per-record v1"))
    repo.save(doomed_per_record, _Expr(text="doomed"))
    base = repo.commit("per-record base")
    repo.save_many(
        [(packed, _Expr(text="packed v1")), (doomed_packed, _Expr(text="doomed"))],
    )
    packed_rev = repo.commit("packed")
    # update each record through the other layout, and forget one of each.
    repo.save_many([(per_record, _Expr(text="per-record v2 packed"))])
    repo.save(packed, _Expr(text="packed v2 per-record"))
    repo.forget(doomed_per_record)
    repo.forget(doomed_packed)
    head = repo.commit("cross-layout edits")
    repo.tag("v1", revision=packed_rev)

    assert repo.content_at(head) == {
        per_record: {"text": "per-record v2 packed"},
        packed: {"text": "packed v2 per-record"},
    }
    assert repo.content_at("v1") == {
        per_record: {"text": "per-record v1"},
        doomed_per_record: {"text": "doomed"},
        packed: {"text": "packed v1"},
        doomed_packed: {"text": "doomed"},
    }
    assert repo.diff(base, packed_rev) == RecordDiff(
        added=tuple(sorted((packed, doomed_packed))),
    )
    assert repo.diff("v1", head) == RecordDiff(
        removed=tuple(sorted((doomed_per_record, doomed_packed))),
        changed=tuple(sorted((per_record, packed))),
    )
    assert repo.staged_uris() == sorted((per_record, packed))
    assert repo.load(per_record, _Expr) == _Expr(text="per-record v2 packed")
    assert repo.load(packed, _Expr) == _Expr(text="packed v2 per-record")
    assert repo.load(doomed_packed, _Expr) is None
    # a packed record written again in packed form after a per-record write.
    repo.save_many([(packed, _Expr(text="packed v3"))])
    assert repo.content_at(repo.commit("v3"))[packed] == {"text": "packed v3"}


def test_forget_of_a_packed_record_before_commit(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")
    repo.save(_MEDIA_URI, _Expr(text="anchor"))
    repo.commit("base")
    repo.save_many([(_EXPR_URI, _Expr(text="short-lived"))])
    repo.forget(_EXPR_URI)
    assert repo.load_raw(_EXPR_URI) is None
    assert repo.content_at(repo.commit("gone")) == {_MEDIA_URI: {"text": "anchor"}}


def test_init_marks_the_store_layout(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")
    marker = json.loads((repo.path / "layout.json").read_text(encoding="utf-8"))
    assert marker == {"layout": repository.STORE_LAYOUT_VERSION, "store": "lairs"}
    assert repo.layout_version() == repository.STORE_LAYOUT_VERSION == 2


def test_unmarked_repository_is_layout_one_until_written(tmp_path: Path) -> None:
    repo, (_, _, deleted) = _open_fixture("0.74.3", tmp_path)
    assert repo.layout_version() == 1
    repo.save_many([(_EXPR_URI, _Expr(text="upgraded"))])
    assert repo.layout_version() == 2
    head = repo.commit("packed over a layout-1 history")
    assert repo.content_at(deleted) == {}
    assert repo.content_at(head) == {_EXPR_URI: {"text": "upgraded"}}


def test_open_refuses_an_unknown_store_layout(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")
    (repo.path / "layout.json").write_text('{"layout": 3}', encoding="utf-8")
    with pytest.raises(panproto.VcsError, match="store layout 3"):
        Repository.open(repo.path)


def test_open_refuses_a_malformed_layout_marker(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")
    (repo.path / "layout.json").write_text('{"layout": "2"}', encoding="utf-8")
    with pytest.raises(panproto.VcsError, match="does not name a store layout"):
        Repository.open(repo.path)


def test_content_at_refuses_a_pack_of_an_unknown_layout(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")
    repo.save_many([(_EXPR_URI, _Expr(text="known"))])
    repo.commit("known layout")
    future = tmp_path / "future.json"
    future.write_text('{"layout": 3, "payload": "?"}', encoding="utf-8")
    repo.inner.add_data(future, key="lairs:pack:3:pub.layers.expression:0")
    revision = repo.commit("future layout")
    with pytest.raises(panproto.VcsError, match="store layout 3"):
        repo.content_at(revision)


def test_packed_fixture_reads_back_pinned_values(tmp_path: Path) -> None:
    # a store layout 2 repository committed by this release: a per-record base,
    # a packed commit of raw and model records, and cross-layout edits. the
    # pinned values guard the packed reader against silent drift.
    target = tmp_path / "packed"
    shutil.copytree(_PACKED_FIXTURE, target)
    metadata = json.loads((target / "fixture.json").read_text(encoding="utf-8"))
    base, packed, mixed = (str(metadata[k]) for k in ("base", "packed", "mixed"))
    repo = Repository.open(target)

    assert repo.layout_version() == 2
    assert [entry["id"] for entry in repo.log()] == [mixed, packed, base]
    assert repo.content_at(base) == _PACKED_HISTORY[0]
    assert repo.content_at(packed) == _PACKED_HISTORY[1]
    expected_mixed = dict(_PACKED_HISTORY[1])
    del expected_mixed["at://did:plc:abc/pub.layers.annotation.annotationLayer/l2"]
    expected_mixed["at://did:plc:abc/pub.layers.expression.expression/e1"] = {
        "text": "naïve",
    }
    expected_mixed["at://did:plc:abc/pub.layers.expression.expression/e3"] = {
        "text": "per-record over packed",
    }
    assert repo.content_at(mixed) == expected_mixed
    layer = repo.content_at(packed)[_LAYER_URI]
    assert json.dumps(layer, ensure_ascii=False) == json.dumps(
        _PACKED_HISTORY[1][_LAYER_URI],
        ensure_ascii=False,
    )
    assert repo.diff(packed, mixed) == RecordDiff(
        removed=("at://did:plc:abc/pub.layers.annotation.annotationLayer/l2",),
        changed=(
            "at://did:plc:abc/pub.layers.expression.expression/e1",
            "at://did:plc:abc/pub.layers.expression.expression/e3",
        ),
    )
    assert repo.staged_uris() == sorted(expected_mixed)
    assert repo.load_raw(_LAYER_URI) == _PACKED_HISTORY[1][_LAYER_URI]


def test_content_at_of_a_large_packed_snapshot_is_linear(tmp_path: Path) -> None:
    # reading folds each pack once, so ten times the records costs about ten
    # times as long. the bound is generous, so only a quadratic read fails it.
    timings: list[float] = []
    for count in (500, 5000):
        repo = Repository.init(tmp_path / f"repo-{count}")
        repo.save_many_raw(
            (_uri("pub.layers.expression.expression", i), {"text": f"t{i}"})
            for i in range(count)
        )
        revision = repo.commit("snapshot")
        start = time.perf_counter()
        assert len(repo.content_at(revision)) == count
        timings.append(max(time.perf_counter() - start, 1e-3))
    assert timings[1] < timings[0] * 40
