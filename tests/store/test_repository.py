"""Unit and integration tests for lairs.store.repository."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import didactic.api as dx
import panproto
import pytest

from lairs.store import repository
from lairs.store.repository import RecordDiff, Repository, Workspace

if TYPE_CHECKING:
    from lairs._types import JsonValue


class _Expr(dx.Model):
    """A throwaway expression-like record for repository tests."""

    text: str


_EXPR_URI = "at://did:plc:abc/pub.layers.expression.expression/e1"
_MEDIA_URI = "at://did:plc:abc/pub.layers.media.media/m1"
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
    assert set(repository.__all__) == {"RecordDiff", "Repository", "Workspace"}


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
