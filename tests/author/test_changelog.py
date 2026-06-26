"""Unit tests for lairs.author.changelog."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import didactic.api as dx
import pytest

from lairs.author import changelog
from lairs.records import changelog as records_changelog
from lairs.store.repository import RecordDiff, Repository

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from lairs._types import JsonValue
    from lairs.author.changelog import BumpLevel, FieldChange

_SemVer = records_changelog.SemanticVersion
_EXPR_NSID = "pub.layers.expression.expression"
_EXPR_URI = f"at://did:plc:abc/{_EXPR_NSID}/e1"


class _Expr(dx.Model):
    """A throwaway expression-like record for changelog tests."""

    text: str
    lang: str | None = None


def _change(path: str, kind: str) -> FieldChange:
    """Build a field change with just a path and kind, for classifier tests."""
    return changelog.FieldChange(field_path=path, change_type=kind)


def test_exports() -> None:
    assert set(changelog.__all__) == {
        "BumpClassifier",
        "BumpLevel",
        "ComponentChange",
        "DefaultBumpClassifier",
        "FieldChange",
        "FieldDiff",
        "build_aggregate_entry",
        "build_entry",
        "bump_version",
        "diff_fields",
        "diff_record",
        "generate_changelog",
    }


# field-level diff ----------------------------------------------------------


def test_diff_fields_reports_scalar_change() -> None:
    changes = changelog.diff_fields({"text": "hi"}, {"text": "bye"})
    assert len(changes) == 1
    assert changes[0].field_path == "text"
    assert changes[0].change_type == "changed"
    assert changes[0].previous_value == "hi"
    assert changes[0].new_value == "bye"


def test_diff_fields_reports_added_and_removed_keys() -> None:
    changes = changelog.diff_fields({"a": 1}, {"b": 2})
    by_path = {c.field_path: c for c in changes}
    assert by_path["a"].change_type == "removed"
    assert by_path["a"].previous_value == "1"
    assert by_path["a"].new_value is None
    assert by_path["b"].change_type == "added"
    assert by_path["b"].new_value == "2"
    assert by_path["b"].previous_value is None


def test_diff_fields_recurses_into_nested_objects() -> None:
    changes = changelog.diff_fields({"meta": {"a": 1}}, {"meta": {"a": 2}})
    assert len(changes) == 1
    assert changes[0].field_path == "meta/a"
    assert changes[0].change_type == "changed"


def test_diff_fields_reports_changed_list_element() -> None:
    changes = changelog.diff_fields(
        {"items": [{"label": "x"}, {"label": "y"}]},
        {"items": [{"label": "x"}, {"label": "z"}]},
    )
    assert len(changes) == 1
    assert changes[0].field_path == "items/1/label"
    assert changes[0].previous_value == "y"
    assert changes[0].new_value == "z"


def test_diff_fields_reports_list_growth_and_shrink() -> None:
    grown = changelog.diff_fields({"xs": [1]}, {"xs": [1, 2]})
    assert grown[0].field_path == "xs/1"
    assert grown[0].change_type == "added"
    shrunk = changelog.diff_fields({"xs": [1, 2]}, {"xs": [1]})
    assert shrunk[0].field_path == "xs/1"
    assert shrunk[0].change_type == "removed"


def test_diff_fields_renders_container_value_as_compact_json() -> None:
    # a scalar replaced by an object is a type-mismatch scalar change; the
    # object is rendered as compact, key-sorted JSON.
    changes = changelog.diff_fields({"a": 1}, {"a": {"y": 2, "x": 1}})
    assert changes[0].change_type == "changed"
    assert changes[0].previous_value == "1"
    assert changes[0].new_value == '{"x":1,"y":2}'


def test_diff_fields_identical_values_yield_no_changes() -> None:
    assert changelog.diff_fields({"a": 1, "b": [1, 2]}, {"a": 1, "b": [1, 2]}) == ()


def test_diff_fields_truncates_long_value() -> None:
    changes = changelog.diff_fields({"text": "a"}, {"text": "b" * 5000})
    assert changes[0].new_value is not None
    assert len(changes[0].new_value) == 1000
    assert changes[0].new_value.endswith("...")


def test_diff_fields_truncates_long_path_keeping_leaf() -> None:
    changes = changelog.diff_fields({}, {"k" * 300: 1})
    assert len(changes[0].field_path) == 200
    assert changes[0].field_path.startswith("...")
    assert changes[0].field_path.endswith("k")


# record-level diff ---------------------------------------------------------


def test_diff_record_classifies_each_case() -> None:
    assert changelog.diff_record(None, {"a": 1}).record_change == "added"
    assert changelog.diff_record({"a": 1}, None).record_change == "removed"
    assert changelog.diff_record({"a": 1}, {"a": 1}).record_change == "unchanged"
    assert changelog.diff_record(None, None).record_change == "unchanged"
    changed = changelog.diff_record({"a": 1}, {"a": 2})
    assert changed.record_change == "changed"
    assert len(changed.changes) == 1


# bump classifier -----------------------------------------------------------


def test_default_classifier_value_only_is_patch() -> None:
    classifier = changelog.DefaultBumpClassifier()
    diff = RecordDiff(changed=(_EXPR_URI,))
    field_changes = {_EXPR_URI: (_change("text", "changed"),)}
    assert classifier.classify(diff, field_changes) == "patch"


def test_default_classifier_addition_is_minor() -> None:
    classifier = changelog.DefaultBumpClassifier()
    assert classifier.classify(RecordDiff(added=(_EXPR_URI,)), {}) == "minor"
    added_field = {_EXPR_URI: (_change("lang", "added"),)}
    assert classifier.classify(RecordDiff(changed=(_EXPR_URI,)), added_field) == "minor"


def test_default_classifier_removal_is_major() -> None:
    classifier = changelog.DefaultBumpClassifier()
    assert classifier.classify(RecordDiff(removed=(_EXPR_URI,)), {}) == "major"
    removed_field = {_EXPR_URI: (_change("lang", "removed"),)}
    assert (
        classifier.classify(RecordDiff(changed=(_EXPR_URI,)), removed_field) == "major"
    )


def test_default_classifier_identity_change_is_major() -> None:
    classifier = changelog.DefaultBumpClassifier()
    identity = {_EXPR_URI: (_change("tokens/0/localId", "changed"),)}
    assert classifier.classify(RecordDiff(changed=(_EXPR_URI,)), identity) == "major"


def test_default_classifier_removal_outranks_addition() -> None:
    classifier = changelog.DefaultBumpClassifier()
    mixed = {_EXPR_URI: (_change("a", "added"), _change("b", "removed"))}
    assert classifier.classify(RecordDiff(added=(_EXPR_URI,)), mixed) == "major"


def test_default_classifier_is_a_bump_classifier() -> None:
    assert isinstance(changelog.DefaultBumpClassifier(), changelog.BumpClassifier)


# version bump --------------------------------------------------------------


def test_bump_version_from_a_previous_version() -> None:
    previous = _SemVer(major=1, minor=4, patch=2)
    assert changelog.bump_version(previous, "major") == _SemVer(
        major=2, minor=0, patch=0
    )
    assert changelog.bump_version(previous, "minor") == _SemVer(
        major=1, minor=5, patch=0
    )
    assert changelog.bump_version(previous, "patch") == _SemVer(
        major=1, minor=4, patch=3
    )


def test_bump_version_from_none_starts_at_zero() -> None:
    assert changelog.bump_version(None, "minor") == _SemVer(major=0, minor=1, patch=0)
    assert changelog.bump_version(None, "major") == _SemVer(major=1, minor=0, patch=0)


# entry assembly ------------------------------------------------------------


def test_build_entry_for_a_value_change() -> None:
    field_diff = changelog.diff_record({"text": "one"}, {"text": "two"})
    entry = changelog.build_entry(
        subject=_EXPR_URI,
        subject_collection=_EXPR_NSID,
        field_diff=field_diff,
        previous_version=_SemVer(major=1, minor=4, patch=2),
        created_at=datetime(2026, 6, 25, tzinfo=UTC),
    )
    assert entry.version == _SemVer(major=1, minor=4, patch=3)
    assert entry.previousVersion == _SemVer(major=1, minor=4, patch=2)
    assert entry.subject == _EXPR_URI
    assert entry.subjectCollection == _EXPR_NSID
    assert len(entry.sections) == 1
    assert entry.sections[0].category == "text"
    assert entry.sections[0].items[0].fieldPath == "text"
    assert len(entry.summary) <= 500


def test_build_entry_for_an_unchanged_record_does_not_bump() -> None:
    field_diff = changelog.diff_record({"text": "same"}, {"text": "same"})
    previous = _SemVer(major=2, minor=1, patch=0)
    entry = changelog.build_entry(
        subject=_EXPR_URI,
        subject_collection=_EXPR_NSID,
        field_diff=field_diff,
        previous_version=previous,
    )
    assert entry.version == previous
    assert entry.sections == ()


def test_build_entry_added_record_uses_a_single_item() -> None:
    field_diff = changelog.diff_record(None, {"text": "new"})
    entry = changelog.build_entry(
        subject=_EXPR_URI,
        subject_collection=_EXPR_NSID,
        field_diff=field_diff,
    )
    assert entry.version == _SemVer(major=0, minor=1, patch=0)
    assert entry.previousVersion is None
    assert len(entry.sections[0].items) == 1
    assert entry.sections[0].items[0].changeType == "added"


def test_build_entry_honours_a_custom_classifier() -> None:
    class _AlwaysMajor:
        def classify(
            self,
            diff: RecordDiff,
            field_changes: Mapping[str, tuple[FieldChange, ...]],
        ) -> BumpLevel:
            del diff, field_changes
            return "major"

    field_diff = changelog.diff_record({"text": "one"}, {"text": "two"})
    entry = changelog.build_entry(
        subject=_EXPR_URI,
        subject_collection=_EXPR_NSID,
        field_diff=field_diff,
        classifier=_AlwaysMajor(),
    )
    assert entry.version == _SemVer(major=1, minor=0, patch=0)


def test_build_entry_uses_a_supplied_summary() -> None:
    field_diff = changelog.diff_record({"text": "one"}, {"text": "two"})
    entry = changelog.build_entry(
        subject=_EXPR_URI,
        subject_collection=_EXPR_NSID,
        field_diff=field_diff,
        summary="hand-written summary",
    )
    assert entry.summary == "hand-written summary"


# generate_changelog over a repository --------------------------------------


def test_generate_changelog_for_an_added_subject(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")
    repo.save(_EXPR_URI, _Expr(text="new"))
    head = repo.commit("head snapshot")
    entry = changelog.generate_changelog(
        repo,
        None,
        head,
        subject=_EXPR_URI,
        subject_collection=_EXPR_NSID,
    )
    assert entry.version == _SemVer(major=0, minor=1, patch=0)
    assert entry.sections[0].items[0].changeType == "added"


def test_generate_changelog_for_a_removed_subject(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")
    repo.save(_EXPR_URI, _Expr(text="gone"))
    base = repo.commit("base snapshot")
    repo.forget(_EXPR_URI)
    head = repo.commit("head snapshot")
    entry = changelog.generate_changelog(
        repo,
        base,
        head,
        subject=_EXPR_URI,
        subject_collection=_EXPR_NSID,
        previous_version=_SemVer(major=1, minor=2, patch=3),
    )
    assert entry.version == _SemVer(major=2, minor=0, patch=0)


def test_generate_changelog_for_a_value_change_is_monotonic(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")
    repo.save(_EXPR_URI, _Expr(text="one"))
    base = repo.commit("base snapshot")
    repo.save(_EXPR_URI, _Expr(text="two"))
    head = repo.commit("head snapshot")
    entry = changelog.generate_changelog(
        repo,
        base,
        head,
        subject=_EXPR_URI,
        subject_collection=_EXPR_NSID,
        previous_version=_SemVer(major=1, minor=4, patch=2),
    )
    assert entry.version == _SemVer(major=1, minor=4, patch=3)


def test_generate_changelog_absent_in_both_revisions_raises(tmp_path: Path) -> None:
    repo = Repository.init(tmp_path / "repo")
    repo.save(_EXPR_URI, _Expr(text="present"))
    base = repo.commit("base snapshot")
    repo.save(_EXPR_URI, _Expr(text="still here"))
    head = repo.commit("head snapshot")
    missing = f"at://did:plc:abc/{_EXPR_NSID}/missing"
    with pytest.raises(ValueError, match="absent in both"):
        changelog.generate_changelog(
            repo,
            base,
            head,
            subject=missing,
            subject_collection=_EXPR_NSID,
        )


# aggregate per-dataset entries ---------------------------------------------


_CORPUS_NSID = "pub.layers.corpus.corpus"
_ONTOLOGY_NSID = "pub.layers.ontology.ontology"
_DATASET_URI = f"at://did:plc:abc/{_CORPUS_NSID}/uds"


def _component(
    uri: str,
    collection: str,
    old: JsonValue,
    new: JsonValue,
) -> changelog.ComponentChange:
    """Build a component change from a record's old and new values."""
    return changelog.ComponentChange(
        uri=uri,
        collection=collection,
        field_diff=changelog.diff_record(old, new),
    )


def test_component_change_carries_uri_collection_and_diff() -> None:
    component = changelog.ComponentChange(
        uri=f"at://d/{_ONTOLOGY_NSID}/o1",
        collection=_ONTOLOGY_NSID,
        field_diff=changelog.diff_record({"a": 1}, {"a": 2}),
    )
    assert component.uri.endswith("/o1")
    assert component.collection == _ONTOLOGY_NSID
    assert component.field_diff.record_change == "changed"


def test_build_aggregate_entry_groups_components_by_category() -> None:
    components = [
        _component(f"at://d/{_CORPUS_NSID}/c1", _CORPUS_NSID, None, {"name": "new"}),
        _component(
            f"at://d/{_ONTOLOGY_NSID}/o1",
            _ONTOLOGY_NSID,
            {"gloss": "a"},
            {"gloss": "a", "pos": "n"},
        ),
    ]
    entry = changelog.build_aggregate_entry(
        subject=_DATASET_URI,
        subject_collection=_CORPUS_NSID,
        components=components,
    )
    assert [s.category for s in entry.sections] == ["corpus", "ontology"]
    assert entry.subject == _DATASET_URI
    assert entry.subjectCollection == _CORPUS_NSID


def test_build_aggregate_entry_summarizes_many_records_with_count_and_cap() -> None:
    components = [
        _component(
            f"at://d/{_ONTOLOGY_NSID}/n{i}",
            _ONTOLOGY_NSID,
            {"gloss": "a"},
            {"gloss": "a", "pos": "n"},
        )
        for i in range(25)
    ]
    entry = changelog.build_aggregate_entry(
        subject=_DATASET_URI,
        subject_collection=_CORPUS_NSID,
        components=components,
        targets_per_item=3,
    )
    assert len(entry.sections) == 1
    item = entry.sections[0].items[0]
    # the 25 records collapse to one item carrying the true count...
    assert "25" in item.description
    assert item.fieldPath == "pos"
    assert item.changeType == "added"
    # ...while the enumerated targets are bounded by the cap.
    assert item.targets is not None
    assert len(item.targets) == 3


def test_build_aggregate_entry_targets_per_item_none_omits_targets() -> None:
    components = [
        _component(f"at://d/{_ONTOLOGY_NSID}/n{i}", _ONTOLOGY_NSID, {"a": 1}, {"a": 2})
        for i in range(5)
    ]
    entry = changelog.build_aggregate_entry(
        subject=_DATASET_URI,
        subject_collection=_CORPUS_NSID,
        components=components,
        targets_per_item=None,
    )
    assert entry.sections[0].items[0].targets == ()


def test_build_aggregate_entry_targets_point_at_components() -> None:
    uri = f"at://d/{_ONTOLOGY_NSID}/only"
    entry = changelog.build_aggregate_entry(
        subject=_DATASET_URI,
        subject_collection=_CORPUS_NSID,
        components=[_component(uri, _ONTOLOGY_NSID, {"a": 1}, {"a": 2})],
    )
    targets = entry.sections[0].items[0].targets
    assert targets is not None
    assert [t.recordRef for t in targets] == [uri]


def test_build_aggregate_entry_single_field_change_keeps_values() -> None:
    entry = changelog.build_aggregate_entry(
        subject=_DATASET_URI,
        subject_collection=_CORPUS_NSID,
        components=[
            _component(
                f"at://d/{_ONTOLOGY_NSID}/o1",
                _ONTOLOGY_NSID,
                {"gloss": "old"},
                {"gloss": "new"},
            ),
        ],
    )
    item = entry.sections[0].items[0]
    assert item.previousValue == "old"
    assert item.newValue == "new"


def test_build_aggregate_entry_bumps_by_aggregate_level() -> None:
    base = _SemVer(major=1, minor=0, patch=0)
    patch = changelog.build_aggregate_entry(
        subject=_DATASET_URI,
        subject_collection=_CORPUS_NSID,
        components=[
            _component(
                f"at://d/{_ONTOLOGY_NSID}/o", _ONTOLOGY_NSID, {"a": 1}, {"a": 2}
            ),
        ],
        previous_version=base,
    )
    assert patch.version == _SemVer(major=1, minor=0, patch=1)
    minor = changelog.build_aggregate_entry(
        subject=_DATASET_URI,
        subject_collection=_CORPUS_NSID,
        components=[
            _component(f"at://d/{_ONTOLOGY_NSID}/o", _ONTOLOGY_NSID, None, {"a": 1}),
        ],
        previous_version=base,
    )
    assert minor.version == _SemVer(major=1, minor=1, patch=0)
    major = changelog.build_aggregate_entry(
        subject=_DATASET_URI,
        subject_collection=_CORPUS_NSID,
        components=[
            _component(f"at://d/{_ONTOLOGY_NSID}/o", _ONTOLOGY_NSID, {"a": 1}, None),
        ],
        previous_version=base,
    )
    assert major.version == _SemVer(major=2, minor=0, patch=0)


def test_build_aggregate_entry_identity_break_is_major() -> None:
    entry = changelog.build_aggregate_entry(
        subject=_DATASET_URI,
        subject_collection=_CORPUS_NSID,
        components=[
            _component(
                f"at://d/{_ONTOLOGY_NSID}/o1",
                _ONTOLOGY_NSID,
                {"localId": "a"},
                {"localId": "b"},
            ),
        ],
        previous_version=_SemVer(major=1, minor=2, patch=3),
    )
    assert entry.version == _SemVer(major=2, minor=0, patch=0)


def test_build_aggregate_entry_is_idempotent_when_nothing_changed() -> None:
    previous = _SemVer(major=3, minor=1, patch=4)
    entry = changelog.build_aggregate_entry(
        subject=_DATASET_URI,
        subject_collection=_CORPUS_NSID,
        components=[
            _component(
                f"at://d/{_ONTOLOGY_NSID}/o", _ONTOLOGY_NSID, {"a": 1}, {"a": 1}
            ),
        ],
        previous_version=previous,
    )
    assert entry.version == previous
    assert entry.sections == ()


def test_build_aggregate_entry_no_components_does_not_bump() -> None:
    entry = changelog.build_aggregate_entry(
        subject=_DATASET_URI,
        subject_collection=_CORPUS_NSID,
        components=[],
        previous_version=_SemVer(major=2, minor=0, patch=0),
    )
    assert entry.version == _SemVer(major=2, minor=0, patch=0)
    assert entry.sections == ()
