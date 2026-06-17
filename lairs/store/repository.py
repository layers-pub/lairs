"""didactic Repository wrapper: the on-disk schematic version control.

Wraps :class:`didactic.api.Repository` (panproto-backed, content-addressed,
git-like) so a corpus snapshot is a commit and a named dataset version is a tag,
giving reproducibility, provenance, and cheap diffing.

``add`` stages a Model class (or a ``panproto.Schema``) and records the
structural schema, while ``add_data`` stages a record's value as committed data
keyed by AT-URI and associated with that schema. lairs writes each record's
value as JSON under ``records/``, stages it as committed data under its AT-URI,
and stages the record type's Model schema alongside it, so one commit captures
both. A corpus snapshot is a single commit; the values committed at a revision
are read back through ``data_at`` under their AT-URI keys, so a tag pins an
exact, byte-reproducible set of values, and a revision-to-revision diff compares
the values folded over each revision's commit ancestry.

didactic 0.9.0 exposes tag creation (``create_tag`` and friends), the
committed-data write (``add_data``), and the committed-data read (``data_at``)
on the public Repository surface, all of which this wrapper uses directly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import didactic.api as dx
import panproto

if TYPE_CHECKING:
    from lairs._types import JsonValue

__all__ = ["RecordDiff", "Repository", "Workspace"]

# the working-tree subdirectory holding content-addressed record values.
_RECORDS_DIR = "records"
# the working-tree file holding the AT-URI -> record metadata index.
_INDEX_FILE = "index.json"
# the default commit author when a caller does not supply one.
_DEFAULT_AUTHOR = "lairs <lairs@layers.pub>"


def _nsid_of(uri: str) -> str:
    """Return the collection NSID embedded in an AT-URI.

    An AT-URI has the form ``at://<authority>/<collection>/<rkey>``. The
    collection segment is the lexicon NSID (for example
    ``pub.layers.expression.expression``), which lairs uses to group records by
    type. When the URI has no collection segment the empty string is returned.

    Parameters
    ----------
    uri : str
        The AT-URI to parse.

    Returns
    -------
    str
        The collection NSID, or the empty string when none is present.
    """
    body = uri.removeprefix("at://")
    parts = body.split("/")
    minimum_parts_with_collection = 2
    if len(parts) >= minimum_parts_with_collection:
        return parts[1]
    return ""


def _safe_name(uri: str) -> str:
    """Return a filesystem-safe file stem for an AT-URI.

    Parameters
    ----------
    uri : str
        The AT-URI to encode.

    Returns
    -------
    str
        A reversible-enough, slash-free stem suitable for a file name.
    """
    return uri.replace("at://", "").replace("/", "__").replace(":", "_")


class RecordDiff(dx.Model):
    """A structural diff of the record set between two revisions.

    Parameters
    ----------
    added : tuple of str
        AT-URIs present at the head revision but not the base revision.
    removed : tuple of str
        AT-URIs present at the base revision but not the head revision.
    changed : tuple of str
        AT-URIs present in both revisions whose stored value differs.
    """

    added: tuple[str, ...] = dx.field(
        default_factory=tuple,
        description="AT-URIs added between base and head",
    )
    removed: tuple[str, ...] = dx.field(
        default_factory=tuple,
        description="AT-URIs removed between base and head",
    )
    changed: tuple[str, ...] = dx.field(
        default_factory=tuple,
        description="AT-URIs whose value changed between base and head",
    )


class Repository:
    """A wrapper over a didactic Repository for Layers records.

    The repository is created on disk with :meth:`init` or reopened with
    :meth:`open`; the constructor takes an already-open inner handle and is
    mostly for internal use.

    Parameters
    ----------
    inner : didactic.api.Repository
        An already-open didactic repository handle.

    Attributes
    ----------
    inner : didactic.api.Repository
        The wrapped didactic repository.
    path : pathlib.Path
        The repository working directory.
    """

    def __init__(self, inner: dx.Repository) -> None:
        self.inner = inner
        self.path = Path(inner.working_dir)

    @classmethod
    def init(cls, path: Path) -> Repository:
        """Initialise a new repository at ``path``.

        Parameters
        ----------
        path : pathlib.Path
            Directory in which to create the repository.

        Returns
        -------
        Repository
            A handle to the newly initialised repository.
        """
        path.mkdir(parents=True, exist_ok=True)
        return cls(dx.Repository.init(path))

    @classmethod
    def open(cls, path: Path) -> Repository:
        """Open an existing repository at ``path``.

        Parameters
        ----------
        path : pathlib.Path
            Directory containing an existing repository.

        Returns
        -------
        Repository
            A handle to the existing repository.
        """
        return cls(dx.Repository.open(path))

    # working-tree record store ------------------------------------------------

    def _records_dir(self) -> Path:
        """Return the working-tree records directory, creating it if needed."""
        records = self.path / _RECORDS_DIR
        records.mkdir(parents=True, exist_ok=True)
        return records

    def _index_path(self) -> Path:
        """Return the path to the working-tree AT-URI index file."""
        return self.path / _INDEX_FILE

    def _read_index(self) -> dict[str, str]:
        """Return the AT-URI -> record-file-stem index from the working tree."""
        index_path = self._index_path()
        if not index_path.exists():
            return {}
        loaded = json.loads(index_path.read_text(encoding="utf-8"))
        return {str(key): str(value) for key, value in loaded.items()}

    def _write_index(self, index: dict[str, str]) -> None:
        """Write the AT-URI -> record-file-stem index to the working tree."""
        self._index_path().write_text(
            json.dumps(index, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def save(self, uri: str, model: dx.Model) -> None:
        """Stage a record value and its schema for the next commit.

        The record value is written as JSON into the working tree, indexed by its
        AT-URI, and staged as committed data so a revision pins the exact value.
        The record type's Model schema is staged alongside it, so the commit
        captures both the data and its structure.

        Parameters
        ----------
        uri : str
            The AT-URI of the record.
        model : didactic.api.Model
            The record value to persist.
        """
        stem = _safe_name(uri)
        record_path = self._records_dir() / f"{stem}.json"
        record_path.write_text(model.model_dump_json(), encoding="utf-8")
        index = self._read_index()
        index[uri] = stem
        self._write_index(index)
        try:
            self.inner.add(type(model))
        except panproto.VcsError as exc:
            # re-staging a record type whose schema is already committed and
            # unchanged is a no-op for the schema VCS. the staged record value is
            # the real change the commit captures.
            if "no changes detected" not in str(exc):
                raise
        # stage the value as committed data keyed by AT-URI, so a revision pins
        # the exact value and data_at reads it back under that key.
        self.inner.add_data(str(record_path), key=uri)

    def staged_uris(self) -> list[str]:
        """Return the AT-URIs currently present in the working tree.

        Returns
        -------
        list of str
            The AT-URIs of records written to the working tree, sorted.
        """
        return sorted(self._read_index())

    def load(self, uri: str, model_cls: type[dx.Model]) -> dx.Model | None:
        """Load a record value from the working tree by AT-URI.

        Parameters
        ----------
        uri : str
            The AT-URI of the record to load.
        model_cls : type of didactic.api.Model
            The Model class to validate the stored JSON against.

        Returns
        -------
        didactic.api.Model or None
            The validated model, or ``None`` when the AT-URI is not stored.
        """
        index = self._read_index()
        stem = index.get(uri)
        if stem is None:
            return None
        record_path = self._records_dir() / f"{stem}.json"
        if not record_path.exists():
            return None
        return model_cls.model_validate_json(record_path.read_text(encoding="utf-8"))

    def load_raw(self, uri: str) -> JsonValue | None:
        """Load a stored record value as raw JSON by AT-URI.

        Parameters
        ----------
        uri : str
            The AT-URI of the record to load.

        Returns
        -------
        JsonValue or None
            The decoded JSON value, or ``None`` when the AT-URI is not stored.
        """
        index = self._read_index()
        stem = index.get(uri)
        if stem is None:
            return None
        record_path = self._records_dir() / f"{stem}.json"
        if not record_path.exists():
            return None
        decoded: JsonValue = json.loads(record_path.read_text(encoding="utf-8"))
        return decoded

    # version control ----------------------------------------------------------

    def commit(self, message: str, *, author: str = _DEFAULT_AUTHOR) -> str:
        """Commit the staged records as a corpus snapshot.

        Parameters
        ----------
        message : str
            The commit message.
        author : str, optional
            The commit author, in conventional ``"Name <email>"`` form.

        Returns
        -------
        str
            The new revision identifier.
        """
        return self.inner.commit(message, author=author)

    def head(self) -> str | None:
        """Return the current head revision, or ``None`` for an empty repository.

        Returns
        -------
        str or None
            The head commit id, or ``None`` when there are no commits yet.
        """
        return self.inner.head()

    def log(self) -> list[dict[str, JsonValue]]:
        """Return the commit log, newest first.

        Returns
        -------
        list of dict
            One commit-record dict per commit, newest first.
        """
        return [dict(entry) for entry in self.inner.log()]

    def tag(self, name: str, *, revision: str | None = None) -> None:
        """Tag a revision as a named dataset version.

        A tag pins the exact record values committed at the revision, giving a
        reproducible named version.

        Parameters
        ----------
        name : str
            The tag name.
        revision : str or None, optional
            The revision to tag; defaults to the current head.

        Raises
        ------
        ValueError
            If no revision is given and the repository has no commits.
        """
        target = revision if revision is not None else self.head()
        if target is None:
            msg = "cannot tag an empty repository with no head revision"
            raise ValueError(msg)
        self.inner.create_tag(name, target)

    def tags(self) -> list[tuple[str, str]]:
        """Return the list of tags.

        Returns
        -------
        list of (str, str)
            One ``(name, target_revision)`` pair per tag.
        """
        return self.inner.list_tags()

    def resolve(self, ref: str) -> str:
        """Resolve a ref expression to a commit id.

        Parameters
        ----------
        ref : str
            A branch name, tag name, or commit-id prefix.

        Returns
        -------
        str
            The full commit id.
        """
        return self.inner.resolve_ref(ref)

    def diff(self, base: str, head: str) -> RecordDiff:
        """Diff the committed record values between two revisions.

        The value set committed at each revision is reconstructed from the
        committed data read with ``data_at``, keyed by AT-URI, and the two sets
        are compared by content.

        Parameters
        ----------
        base : str
            The base revision (ref expression).
        head : str
            The head revision (ref expression).

        Returns
        -------
        RecordDiff
            The added, removed, and changed AT-URIs between the revisions.
        """
        base_state = self._state_at(base)
        head_state = self._state_at(head)
        base_uris = set(base_state)
        head_uris = set(head_state)
        added = tuple(sorted(head_uris - base_uris))
        removed = tuple(sorted(base_uris - head_uris))
        changed = tuple(
            sorted(
                uri
                for uri in base_uris & head_uris
                if base_state[uri] != head_state[uri]
            ),
        )
        return RecordDiff(added=added, removed=removed, changed=changed)

    def _state_at(self, ref: str) -> dict[str, bytes]:
        """Reconstruct the committed record values at a revision, keyed by AT-URI.

        Committed data is recorded per commit, so the value set at ``ref`` is the
        fold of ``data_at`` over the revision's ancestry, oldest commit first,
        with the latest value for each AT-URI winning.

        Parameters
        ----------
        ref : str
            The revision to read (ref expression).

        Returns
        -------
        dict of str to bytes
            The committed record values at the revision, keyed by AT-URI.
        """
        target = self.resolve(ref)
        entries = {str(entry["id"]): entry for entry in self.log()}
        # post-order over the ancestry: each commit is appended after its
        # parents, so folding in this order lets a descendant's value win over an
        # ancestor's. this is ordered by the commit graph, not by timestamp,
        # which can tie for commits made in the same second.
        order: list[str] = []
        visited: set[str] = set()
        stack: list[tuple[str, bool]] = [(target, False)]
        while stack:
            cid, processed = stack.pop()
            if processed:
                order.append(cid)
                continue
            entry = entries.get(cid)
            if entry is None or cid in visited:
                continue
            visited.add(cid)
            stack.append((cid, True))
            parents = entry.get("parents")
            if isinstance(parents, list):
                stack.extend((str(parent), False) for parent in parents)
        state: dict[str, bytes] = {}
        for cid in order:
            for dataset in self.inner.data_at(cid):
                if dataset.key is not None:
                    state[dataset.key] = dataset.data
        return state

    def schema_diff(
        self,
        old: type[dx.Model],
        new: type[dx.Model],
    ) -> dict[str, JsonValue]:
        """Compute a structural diff between two record-type schemas.

        This wraps :func:`didactic.api.diff`, which compares two Model *classes*
        (for example two generated record types across a Layers version bump),
        not two revisions of the same record's values.

        Parameters
        ----------
        old : type of didactic.api.Model
            The base schema class.
        new : type of didactic.api.Model
            The head schema class.

        Returns
        -------
        dict
            The structural schema diff.
        """
        return dict(dx.diff(old, new))


class Workspace:
    """A record-type-aware grouping over a :class:`Repository`.

    Indexes the AT-URIs in a repository by their collection NSID so that
    per-record-type listing and history are cheap, mirroring the way a corpus is
    a graph of many record types.

    Parameters
    ----------
    repository : Repository
        The repository to index.

    Attributes
    ----------
    repository : Repository
        The wrapped repository.
    """

    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def by_nsid(self) -> dict[str, list[str]]:
        """Group the working-tree AT-URIs by collection NSID.

        Returns
        -------
        dict of str to list of str
            A mapping from collection NSID to the sorted AT-URIs of that type.
        """
        grouped: dict[str, list[str]] = {}
        for uri in self.repository.staged_uris():
            grouped.setdefault(_nsid_of(uri), []).append(uri)
        for uris in grouped.values():
            uris.sort()
        return grouped

    def nsids(self) -> list[str]:
        """Return the collection NSIDs present in the workspace.

        Returns
        -------
        list of str
            The distinct collection NSIDs, sorted.
        """
        return sorted(self.by_nsid())

    def uris_of(self, nsid: str) -> list[str]:
        """Return the AT-URIs of records of a given collection NSID.

        Parameters
        ----------
        nsid : str
            The collection NSID to select.

        Returns
        -------
        list of str
            The sorted AT-URIs of that record type.
        """
        return self.by_nsid().get(nsid, [])
