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


def test_diff_snapshots_classifies_changes(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")
    diff = repo.diff_snapshots(
        {"keep": "h1", "drop": "h2", "edit": "h3"},
        {"keep": "h1", "edit": "h3x", "new": "h4"},
    )
    assert diff.added == ("new",)
    assert diff.removed == ("drop",)
    assert diff.changed == ("edit",)


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
