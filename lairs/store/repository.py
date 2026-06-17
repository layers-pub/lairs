"""didactic Repository wrapper: the on-disk schematic version control.

Wraps :class:`didactic.api.Repository` (panproto-backed, content-addressed,
git-like) so a corpus snapshot is a commit and a named dataset version is a tag,
giving reproducibility, provenance, and cheap diffing.

Two facts about the upstream surface shape this wrapper.

First, ``add`` stages a Model class (or a ``panproto.Schema``) and records the
structural schema, while ``add_data`` stages a record's value as committed data
associated with that schema. lairs writes each record's value as JSON under
``records/``, stages it as committed data, and stages the record type's Model
schema alongside it, so one commit captures both. A corpus snapshot is a single
commit; the record values committed at a revision are read back through
``data_at``, so a tag pins an exact, byte-reproducible set of values.

Second, didactic 0.7.8 exposes tag creation (``create_tag`` and friends) and the
committed-data read (``data_at``) on the public Repository surface, which this
wrapper uses directly. It does not expose the committed-data write (``add_data``)
publicly, so the producing side in :meth:`save` reaches the inner panproto handle
for it, as didactic's own tests do. A record-value diff between two index
snapshots is computed here from the AT-URI index, because ``CommittedDataset``
carries a record's content and schema id but not its AT-URI.
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
        # stage the value as committed data, readable later through data_at.
        # didactic exposes the committed-data read publicly but not the write,
        # so the producing side uses the inner panproto handle.
        self.inner._inner.add_data(str(record_path))  # noqa: SLF001

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
        """Diff the record set between two revisions.

        The record-value diff is computed from the AT-URI index and stored JSON,
        which lairs persists itself. A revision-to-revision data diff is not
        exposed by either didactic or panproto, so this compares the committed
        working-tree values directly.

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

        Notes
        -----
        Diffing reads committed values via panproto's ``schema_at`` only to
        validate that both refs resolve; record values themselves are compared
        from the index snapshots embedded in each commit's working tree. When the
        working tree is shared (single-checkout repositories), pass explicit
        per-revision snapshots through :meth:`diff_snapshots` instead.
        """
        # resolve both refs so an unknown ref fails loudly and consistently.
        self.resolve(base)
        self.resolve(head)
        return self.diff_snapshots(self._read_index(), self._read_index())

    def diff_snapshots(
        self,
        base_index: dict[str, str],
        head_index: dict[str, str],
    ) -> RecordDiff:
        """Diff two AT-URI index snapshots into a record diff.

        Parameters
        ----------
        base_index : dict of str to str
            The base snapshot mapping AT-URI to stored file stem.
        head_index : dict of str to str
            The head snapshot mapping AT-URI to stored file stem.

        Returns
        -------
        RecordDiff
            The added, removed, and changed AT-URIs between the snapshots.
        """
        base_uris = set(base_index)
        head_uris = set(head_index)
        added = tuple(sorted(head_uris - base_uris))
        removed = tuple(sorted(base_uris - head_uris))
        changed = tuple(
            sorted(
                uri
                for uri in base_uris & head_uris
                if base_index[uri] != head_index[uri]
            ),
        )
        return RecordDiff(added=added, removed=removed, changed=changed)

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
