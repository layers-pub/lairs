"""Unit and integration tests for lairs.store.repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

import didactic.api as dx
import pytest

from lairs.store import repository
from lairs.store.repository import RecordDiff, Repository, Workspace

if TYPE_CHECKING:
    from pathlib import Path


class _Expr(dx.Model):
    """A throwaway expression-like record for repository tests."""

    text: str


_EXPR_URI = "at://did:plc:abc/pub.layers.expression.expression/e1"
_MEDIA_URI = "at://did:plc:abc/pub.layers.media.media/m1"


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
    # save stages the record value as committed data, so data_at returns it at
    # the revision. this backs the reproducibility guarantee.
    repo = Repository.init(tmp_path / "repo")
    repo.save(_EXPR_URI, _Expr(text="hello"))
    revision = repo.commit("snapshot")
    datasets = repo.inner.data_at(revision)
    assert len(datasets) == 1
    assert datasets[0].record_count == 1
    assert b"hello" in datasets[0].data


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
    # the reconstructed head state carries the latest value, not an ancestor's.
    state = repo._state_at(head)
    assert b"v3" in state[_EXPR_URI]
    assert b"v2" not in state[_EXPR_URI]


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
