"""Generate changelog entries and a semantic version from a record diff.

A :class:`~lairs.records.changelog.Entry` records how one Layers record changed
between two revisions, and its :class:`~lairs.records.changelog.SemanticVersion`
captures the size of that change. lairs already owns every input the generation
needs: a :class:`~lairs.store.repository.Repository` holds both the prior and the
current record content (read with ``content_at``), so the changelog and its
version can be derived once here rather than reinvented by every publisher.

The work splits into three pieces. First, :func:`diff_fields` walks two record
values and emits a :class:`FieldChange` per differing field, with a slash-joined
``field_path`` and display-string old and new values. Second, a pluggable
:class:`BumpClassifier` maps the record-set diff and its field changes to a
``major``/``minor``/``patch`` bump level; :class:`DefaultBumpClassifier` is the
default policy. Third, :func:`build_entry` and :func:`generate_changelog` assemble
the :class:`~lairs.records.changelog.Entry`, grouping change items into sections
and bumping the version from the one supplied as ``previous_version``.

This generates only the Layers-representation version carried on the changelog
record. The free-form upstream ``version`` string on a corpus or resource, and any
policy decision about which record anchors a dataset, stay with the consumer.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

import didactic.api as dx

from lairs.records import changelog
from lairs.store.repository import RecordDiff

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from lairs._types import JsonValue
    from lairs.store.repository import Repository

__all__ = [
    "BumpClassifier",
    "BumpLevel",
    "DefaultBumpClassifier",
    "FieldChange",
    "FieldDiff",
    "build_entry",
    "bump_version",
    "diff_fields",
    "diff_record",
    "generate_changelog",
]

_ELLIPSIS = "..."
"""The marker appended (or prepended) when a value or path is truncated."""

_MAX_VALUE_LEN = 1000
"""The maximum length of a ``previousValue`` or ``newValue`` display string."""

_MAX_PATH_LEN = 200
"""The maximum length of a ``fieldPath``."""

_MAX_DESCRIPTION_LEN = 2000
"""The maximum length of a change item ``description``."""

_MAX_SUMMARY_LEN = 500
"""The maximum length of an entry ``summary``."""

_NAMESPACE_SEGMENT = 2
"""The dotted segment of a collection NSID holding the lexicon namespace."""

# leaf field names whose change breaks a record's identity or an inbound
# reference to it, so a change to one of them forces a major bump.
_IDENTITY_FIELDS = frozenset(
    {"id", "localId", "local_id", "rkey", "uuid", "tokenizationId"},
)

# lexicon namespace -> changelog section category. the namespace is the third
# dotted segment of a collection NSID (pub.layers.<namespace>.<name>).
_CATEGORY_BY_NAMESPACE: dict[str, str] = {
    "annotation": "annotations",
    "segmentation": "segmentation",
    "expression": "text",
    "ontology": "ontology",
    "persona": "ontology",
    "corpus": "corpus",
    "alignment": "alignment",
    "graph": "graph",
    "judgment": "experiment",
    "resource": "resource",
    "media": "media",
    "eprint": "provenance",
    "changelog": "other",
}

type BumpLevel = Literal["major", "minor", "patch"]
"""A semantic-version bump size: ``major``, ``minor``, or ``patch``."""


class FieldChange(dx.Model):
    """A single field-level change between two record values.

    Attributes
    ----------
    field_path : str
        The slash-delimited path to the changed field, for example
        ``"annotations/3/label"``.
    change_type : str
        The kind of field change: ``added``, ``changed``, or ``removed``.
    previous_value : str or None
        The previous value as a display string, when one applies.
    new_value : str or None
        The new value as a display string, when one applies.
    """

    field_path: str = dx.field(
        description="slash-delimited path to the changed field",
        extras={"maxLength": _MAX_PATH_LEN},
    )
    change_type: str = dx.field(
        description="field-level change kind: added, changed, or removed",
        extras={"knownValues": ("added", "changed", "removed")},
    )
    previous_value: str | None = dx.field(
        default=None,
        description="previous value as a display string",
        extras={"maxLength": _MAX_VALUE_LEN},
    )
    new_value: str | None = dx.field(
        default=None,
        description="new value as a display string",
        extras={"maxLength": _MAX_VALUE_LEN},
    )


class FieldDiff(dx.Model):
    """The record-level and field-level diff of one record across two revisions.

    Attributes
    ----------
    record_change : str
        The record-level change: ``added``, ``changed``, ``removed``, or
        ``unchanged``.
    changes : tuple of FieldChange
        The field-level changes; empty unless ``record_change`` is ``changed``.
    """

    record_change: str = dx.field(
        description="record-level change: added, changed, removed, or unchanged",
        extras={"knownValues": ("added", "changed", "removed", "unchanged")},
    )
    changes: tuple[dx.Embed[FieldChange], ...] = dx.field(
        default_factory=tuple,
        description="the field-level changes, empty unless the record changed",
    )


@runtime_checkable
class BumpClassifier(Protocol):
    """A pluggable policy mapping a record diff to a semantic-version bump level.

    A classifier sees the whole record-set diff and the per-record field changes,
    so a consumer can implement a dataset-level policy over many member records by
    reusing the same interface.
    """

    def classify(
        self,
        diff: RecordDiff,
        field_changes: Mapping[str, tuple[FieldChange, ...]],
    ) -> BumpLevel:
        """Return the bump level implied by a record diff and its field changes.

        Parameters
        ----------
        diff : lairs.store.repository.RecordDiff
            The added, removed, and changed AT-URIs between two revisions.
        field_changes : collections.abc.Mapping
            A mapping from AT-URI to the field changes computed for that record.

        Returns
        -------
        BumpLevel
            The implied bump size: ``major``, ``minor``, or ``patch``.
        """
        ...


def _is_identity_break(change: FieldChange) -> bool:
    """Return whether a changed field breaks a record's identity or a reference.

    Parameters
    ----------
    change : FieldChange
        The field change to inspect.

    Returns
    -------
    bool
        ``True`` when the change is a value change to an identity or reference
        field (the leaf segment of its path is in :data:`_IDENTITY_FIELDS`).
    """
    if change.change_type != "changed":
        return False
    leaf = change.field_path.rsplit("/", 1)[-1]
    return leaf in _IDENTITY_FIELDS


class DefaultBumpClassifier:
    """The default bump policy.

    The policy is, in order of precedence: ``major`` when a record is removed, a
    field or list element is removed, or an identity or reference field changes
    value; ``minor`` when a record is added or a field or list element is added;
    and ``patch`` when only existing field values change.
    """

    def classify(
        self,
        diff: RecordDiff,
        field_changes: Mapping[str, tuple[FieldChange, ...]],
    ) -> BumpLevel:
        """Return the bump level for a record diff and its field changes.

        Parameters
        ----------
        diff : lairs.store.repository.RecordDiff
            The added, removed, and changed AT-URIs between two revisions.
        field_changes : collections.abc.Mapping
            A mapping from AT-URI to the field changes computed for that record.

        Returns
        -------
        BumpLevel
            The bump size implied by the default policy.
        """
        all_changes = [
            change for changes in field_changes.values() for change in changes
        ]
        removed_field = any(change.change_type == "removed" for change in all_changes)
        identity_break = any(_is_identity_break(change) for change in all_changes)
        if diff.removed or removed_field or identity_break:
            return "major"
        added_field = any(change.change_type == "added" for change in all_changes)
        if diff.added or added_field:
            return "minor"
        return "patch"


_DEFAULT_CLASSIFIER: BumpClassifier = DefaultBumpClassifier()
"""The classifier used when a caller does not supply one."""


def _truncate(text: str, limit: int) -> str:
    """Truncate text to a length, marking the cut with a trailing ellipsis.

    Parameters
    ----------
    text : str
        The text to bound.
    limit : int
        The maximum length, including the ellipsis marker.

    Returns
    -------
    str
        The text, shortened from the right with a trailing ellipsis when it
        exceeds ``limit``.
    """
    if len(text) <= limit:
        return text
    return text[: limit - len(_ELLIPSIS)] + _ELLIPSIS


def _truncate_path(path: str) -> str:
    """Bound a field path, keeping the rightmost (leaf) portion.

    The leaf segment is the most informative part of a path, so an over-long
    path is shortened from the left with a leading ellipsis.

    Parameters
    ----------
    path : str
        The slash-delimited field path.

    Returns
    -------
    str
        The path, bounded to :data:`_MAX_PATH_LEN`.
    """
    if len(path) <= _MAX_PATH_LEN:
        return path
    return _ELLIPSIS + path[-(_MAX_PATH_LEN - len(_ELLIPSIS)) :]


def _render(value: JsonValue) -> str:
    """Render a JSON value as a bounded display string.

    Strings are used as-is; every other JSON value is rendered as compact,
    key-sorted JSON. The result is bounded to :data:`_MAX_VALUE_LEN`.

    Parameters
    ----------
    value : JsonValue
        The value to render.

    Returns
    -------
    str
        The bounded display string.
    """
    rendered = (
        value
        if isinstance(value, str)
        else json.dumps(value, sort_keys=True, separators=(",", ":"))
    )
    return _truncate(rendered, _MAX_VALUE_LEN)


def _diff_dicts(
    old: dict[str, JsonValue],
    new: dict[str, JsonValue],
    path: str,
) -> Iterator[FieldChange]:
    """Yield the field changes between two JSON objects.

    Parameters
    ----------
    old : dict
        The previous object.
    new : dict
        The current object.
    path : str
        The field path leading to these objects.

    Yields
    ------
    FieldChange
        One change per added, removed, or differing key, recursing into nested
        objects and lists.
    """
    for key in sorted(set(old) | set(new)):
        child = f"{path}/{key}" if path else key
        if key not in old:
            yield FieldChange(
                field_path=_truncate_path(child),
                change_type="added",
                new_value=_render(new[key]),
            )
        elif key not in new:
            yield FieldChange(
                field_path=_truncate_path(child),
                change_type="removed",
                previous_value=_render(old[key]),
            )
        else:
            yield from _diff_value(old[key], new[key], child)


def _diff_lists(
    old: list[JsonValue],
    new: list[JsonValue],
    path: str,
) -> Iterator[FieldChange]:
    """Yield the field changes between two JSON arrays, index-aligned.

    Elements are compared by position, so an insertion or reordering reports the
    trailing elements as changed rather than as a structural move; this is the
    intended default. A consumer that needs structural list diffing overrides the
    classifier or post-processes the changes.

    Parameters
    ----------
    old : list
        The previous array.
    new : list
        The current array.
    path : str
        The field path leading to these arrays.

    Yields
    ------
    FieldChange
        One change per added, removed, or differing element.
    """
    for index in range(max(len(old), len(new))):
        child = f"{path}/{index}"
        if index >= len(old):
            yield FieldChange(
                field_path=_truncate_path(child),
                change_type="added",
                new_value=_render(new[index]),
            )
        elif index >= len(new):
            yield FieldChange(
                field_path=_truncate_path(child),
                change_type="removed",
                previous_value=_render(old[index]),
            )
        else:
            yield from _diff_value(old[index], new[index], child)


def _diff_value(old: JsonValue, new: JsonValue, path: str) -> Iterator[FieldChange]:
    """Yield the field changes between two JSON values at a path.

    Equal values yield nothing. Two objects or two arrays recurse; any other
    differing pair (a scalar change or a type mismatch) yields a single
    ``changed`` field change.

    Parameters
    ----------
    old : JsonValue
        The previous value.
    new : JsonValue
        The current value.
    path : str
        The field path leading to these values.

    Yields
    ------
    FieldChange
        The changes implied by comparing the two values.
    """
    if old == new:
        return
    if isinstance(old, dict) and isinstance(new, dict):
        yield from _diff_dicts(old, new, path)
    elif isinstance(old, list) and isinstance(new, list):
        yield from _diff_lists(old, new, path)
    else:
        yield FieldChange(
            field_path=_truncate_path(path),
            change_type="changed",
            previous_value=_render(old),
            new_value=_render(new),
        )


def diff_fields(old: JsonValue, new: JsonValue) -> tuple[FieldChange, ...]:
    """Return the field-level changes between two record values.

    Parameters
    ----------
    old : JsonValue
        The previous record value.
    new : JsonValue
        The current record value.

    Returns
    -------
    tuple of FieldChange
        One change per added, removed, or differing field, with slash-joined
        field paths and bounded display values.
    """
    return tuple(_diff_value(old, new, ""))


def diff_record(old: JsonValue, new: JsonValue) -> FieldDiff:
    """Diff one record's value between two revisions.

    A record value is always an object, so ``None`` unambiguously means the
    record is absent at that revision: a record present only in ``new`` is
    ``added``, present only in ``old`` is ``removed``, present and equal in both
    is ``unchanged``, and present and differing is ``changed`` with its field
    changes.

    Parameters
    ----------
    old : JsonValue
        The record value at the base revision, or ``None`` when absent.
    new : JsonValue
        The record value at the head revision, or ``None`` when absent.

    Returns
    -------
    FieldDiff
        The record-level change and, when changed, the field-level changes.
    """
    if old is None and new is None:
        return FieldDiff(record_change="unchanged")
    if old is None:
        return FieldDiff(record_change="added")
    if new is None:
        return FieldDiff(record_change="removed")
    if old == new:
        return FieldDiff(record_change="unchanged")
    return FieldDiff(record_change="changed", changes=diff_fields(old, new))


def bump_version(
    previous: changelog.SemanticVersion | None,
    level: BumpLevel,
) -> changelog.SemanticVersion:
    """Bump a semantic version by a level.

    A ``major`` bump increments the major and resets minor and patch; a ``minor``
    bump increments the minor and resets patch; a ``patch`` bump increments the
    patch. A ``None`` previous version starts from ``0.0.0``, so a brand-new
    record classified ``minor`` becomes ``0.1.0``.

    Parameters
    ----------
    previous : lairs.records.changelog.SemanticVersion or None
        The version to bump from, or ``None`` to start from ``0.0.0``.
    level : BumpLevel
        The bump size.

    Returns
    -------
    lairs.records.changelog.SemanticVersion
        The bumped version.
    """
    base = (
        previous
        if previous is not None
        else changelog.SemanticVersion(major=0, minor=0, patch=0)
    )
    if level == "major":
        return changelog.SemanticVersion(major=base.major + 1, minor=0, patch=0)
    if level == "minor":
        return changelog.SemanticVersion(
            major=base.major,
            minor=base.minor + 1,
            patch=0,
        )
    return changelog.SemanticVersion(
        major=base.major,
        minor=base.minor,
        patch=base.patch + 1,
    )


def _category_for(collection: str) -> str:
    """Return the changelog section category for a collection NSID.

    Parameters
    ----------
    collection : str
        The subject record's collection NSID.

    Returns
    -------
    str
        The mapped category, or ``"other"`` when the namespace is unknown.
    """
    parts = collection.split(".")
    namespace = parts[_NAMESPACE_SEGMENT] if len(parts) > _NAMESPACE_SEGMENT else ""
    return _CATEGORY_BY_NAMESPACE.get(namespace, "other")


def _describe(change: FieldChange) -> str:
    """Return a one-line description for a field change.

    Parameters
    ----------
    change : FieldChange
        The field change to describe.

    Returns
    -------
    str
        A bounded ``"<Verb> <field_path>"`` description.
    """
    verbs = {"added": "Added", "changed": "Changed", "removed": "Removed"}
    verb = verbs.get(change.change_type, "Changed")
    return _truncate(f"{verb} {change.field_path}", _MAX_DESCRIPTION_LEN)


def _change_items(
    subject_collection: str,
    field_diff: FieldDiff,
) -> tuple[changelog.ChangeItem, ...]:
    """Build the changelog change items for a record's field diff.

    An added or removed record yields a single summarising item; a changed record
    yields one item per field change, carrying the path and display values.

    Parameters
    ----------
    subject_collection : str
        The subject record's collection NSID.
    field_diff : FieldDiff
        The record's diff.

    Returns
    -------
    tuple of lairs.records.changelog.ChangeItem
        The change items for the entry.
    """
    if field_diff.record_change == "added":
        return (
            changelog.ChangeItem(
                changeType="added",
                description=_truncate(
                    f"Added {subject_collection} record",
                    _MAX_DESCRIPTION_LEN,
                ),
            ),
        )
    if field_diff.record_change == "removed":
        return (
            changelog.ChangeItem(
                changeType="removed",
                description=_truncate(
                    f"Removed {subject_collection} record",
                    _MAX_DESCRIPTION_LEN,
                ),
            ),
        )
    return tuple(
        changelog.ChangeItem(
            changeType=change.change_type,
            description=_describe(change),
            fieldPath=change.field_path,
            previousValue=change.previous_value,
            newValue=change.new_value,
        )
        for change in field_diff.changes
    )


def _sections(
    subject_collection: str,
    items: tuple[changelog.ChangeItem, ...],
) -> tuple[changelog.ChangeSection, ...]:
    """Group change items into a single section for the subject's category.

    Parameters
    ----------
    subject_collection : str
        The subject record's collection NSID.
    items : tuple of lairs.records.changelog.ChangeItem
        The change items to group.

    Returns
    -------
    tuple of lairs.records.changelog.ChangeSection
        One section under the subject's category, or none when there are no
        items.
    """
    if not items:
        return ()
    return (
        changelog.ChangeSection(
            category=_category_for(subject_collection),
            items=items,
        ),
    )


def _summary(field_diff: FieldDiff, subject_collection: str) -> str:
    """Build a one-line summary for a record's diff.

    Parameters
    ----------
    field_diff : FieldDiff
        The record's diff.
    subject_collection : str
        The subject record's collection NSID.

    Returns
    -------
    str
        A bounded one-line summary.
    """
    if field_diff.record_change == "added":
        return _truncate(f"Added {subject_collection} record", _MAX_SUMMARY_LEN)
    if field_diff.record_change == "removed":
        return _truncate(f"Removed {subject_collection} record", _MAX_SUMMARY_LEN)
    count = len(field_diff.changes)
    noun = "field" if count == 1 else "fields"
    return _truncate(
        f"Changed {count} {noun} in {subject_collection} record",
        _MAX_SUMMARY_LEN,
    )


def _single_record_diff(subject: str, record_change: str) -> RecordDiff:
    """Build a one-record :class:`RecordDiff` from a record-level change.

    Parameters
    ----------
    subject : str
        The subject record's AT-URI.
    record_change : str
        The record-level change: ``added``, ``changed``, ``removed``, or
        ``unchanged``.

    Returns
    -------
    lairs.store.repository.RecordDiff
        A diff naming the subject in the matching bucket.
    """
    if record_change == "added":
        return RecordDiff(added=(subject,))
    if record_change == "removed":
        return RecordDiff(removed=(subject,))
    if record_change == "changed":
        return RecordDiff(changed=(subject,))
    return RecordDiff()


def build_entry(  # noqa: PLR0913  (each field of the entry is a distinct knob)
    *,
    subject: str,
    subject_collection: str,
    field_diff: FieldDiff,
    previous_version: changelog.SemanticVersion | None = None,
    classifier: BumpClassifier | None = None,
    created_at: datetime | None = None,
    summary: str | None = None,
) -> changelog.Entry:
    """Assemble a changelog entry from a record's field diff.

    The change items are grouped into a section under the subject's category, the
    bump level is taken from the classifier, and the version is bumped from
    ``previous_version``. A genuinely unchanged record does not bump: its version
    is ``previous_version`` and its sections are empty, so a re-run is idempotent.

    Parameters
    ----------
    subject : str
        The subject record's AT-URI.
    subject_collection : str
        The subject record's collection NSID.
    field_diff : FieldDiff
        The record's diff between two revisions.
    previous_version : lairs.records.changelog.SemanticVersion or None, optional
        The version the subject was last published at, written verbatim to
        ``previousVersion`` and bumped into ``version``.
    classifier : BumpClassifier or None, optional
        The bump policy; the default policy is used when omitted.
    created_at : datetime.datetime or None, optional
        The entry timestamp; the current UTC time is used when omitted.
    summary : str or None, optional
        A one-line summary; a generated summary is used when omitted.

    Returns
    -------
    lairs.records.changelog.Entry
        The assembled changelog entry.
    """
    resolved_classifier = classifier if classifier is not None else _DEFAULT_CLASSIFIER
    changes = tuple(field_diff.changes)
    is_noop = field_diff.record_change == "unchanged" and not changes
    if is_noop:
        version = previous_version
        sections: tuple[changelog.ChangeSection, ...] = ()
        default_summary = f"No changes to {subject_collection} record"
    else:
        record_diff = _single_record_diff(subject, field_diff.record_change)
        level = resolved_classifier.classify(record_diff, {subject: changes})
        version = bump_version(previous_version, level)
        sections = _sections(
            subject_collection, _change_items(subject_collection, field_diff)
        )
        default_summary = _summary(field_diff, subject_collection)
    resolved_summary = summary if summary is not None else default_summary
    return changelog.Entry(
        createdAt=created_at if created_at is not None else datetime.now(UTC),
        previousVersion=previous_version,
        sections=sections,
        subject=subject,
        subjectCollection=subject_collection,
        summary=_truncate(resolved_summary, _MAX_SUMMARY_LEN),
        version=version,
    )


def generate_changelog(  # noqa: PLR0913  (revisions plus entry-shaping knobs)
    repo: Repository,
    prev_revision: str | None,
    new_revision: str,
    *,
    subject: str,
    subject_collection: str,
    previous_version: changelog.SemanticVersion | None = None,
    classifier: BumpClassifier | None = None,
    created_at: datetime | None = None,
    summary: str | None = None,
) -> changelog.Entry:
    """Generate a changelog entry for a subject record across two revisions.

    The subject's content is read at each revision with
    :meth:`~lairs.store.repository.Repository.content_at`, diffed field by field,
    and assembled into a :class:`~lairs.records.changelog.Entry`. A ``None``
    ``prev_revision`` treats the base as empty, so an initial commit yields an
    ``added`` entry.

    Parameters
    ----------
    repo : lairs.store.repository.Repository
        The repository holding both revisions.
    prev_revision : str or None
        The base revision (ref expression), or ``None`` for an empty base.
    new_revision : str
        The head revision (ref expression).
    subject : str
        The AT-URI of the record to describe.
    subject_collection : str
        The subject record's collection NSID.
    previous_version : lairs.records.changelog.SemanticVersion or None, optional
        The version the subject was last published at.
    classifier : BumpClassifier or None, optional
        The bump policy; the default policy is used when omitted.
    created_at : datetime.datetime or None, optional
        The entry timestamp; the current UTC time is used when omitted.
    summary : str or None, optional
        A one-line summary; a generated summary is used when omitted.

    Returns
    -------
    lairs.records.changelog.Entry
        The generated changelog entry.

    Raises
    ------
    ValueError
        If the subject is absent in both revisions.
    """
    old = (
        repo.content_at(prev_revision).get(subject)
        if prev_revision is not None
        else None
    )
    new = repo.content_at(new_revision).get(subject)
    if old is None and new is None:
        msg = f"subject {subject} is absent in both revisions"
        raise ValueError(msg)
    field_diff = diff_record(old, new)
    return build_entry(
        subject=subject,
        subject_collection=subject_collection,
        field_diff=field_diff,
        previous_version=previous_version,
        classifier=classifier,
        created_at=created_at,
        summary=summary,
    )
