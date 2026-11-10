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
are read back through Panproto's schema-aware ``decoded_data_at`` accessor under
their AT-URI keys, so a tag pins an exact, reproducible set of values, and a
revision-to-revision diff compares the values folded over each revision's commit
ancestry.

Removal is representable: ``forget`` stages a tombstone under a record's AT-URI,
which the ancestry fold drops, so a record present at a base revision can be
absent at a descendant head and a diff reports it in ``removed``.

Two committed-data layouts coexist and may be mixed in one history. The
per-record layout (store layout 1) is what ``save`` and ``forget`` write: one
data set per AT-URI. The packed layout (store layout 2) is what ``save_many``
and ``save_many_raw`` write: many records of one collection per data set, in the
format of :mod:`lairs.store._pack`, so a bulk ingest costs one native staging
call and one stored object per pack rather than per record. Reads fold both
layouts in commit and staging order, so a later write of a record wins whichever
layout either write used.

The working tree mirrors the staged values so ``load``, ``load_raw``, and
``staged_uris`` work without reading history. ``index.json`` maps each AT-URI to
its location, either a per-record file stem under ``records/`` or a position in a
pack file under ``records/packs/``. Index updates are appended to the
``index.log`` journal and folded into ``index.json`` on commit, so a write never
rereads or rewrites the whole index. ``layout.json`` records the store layout
version of the working tree; a repository marked with a newer version than this
lairs knows is refused on open.

didactic exposes tag creation (``create_tag`` and friends) and committed-data
writes (``add_data``). Panproto exposes schema-aware committed-data reads through
``decoded_data_at``. This wrapper uses those public Repository APIs directly.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

import didactic.api as dx
import panproto

from lairs.records.blobref import normalize_blob_refs
from lairs.store._pack import (
    PACK_LAYOUT_VERSION,
    PackEnvelope,
    decode_entries,
    decode_lines,
    encode_pack,
    entry_line,
    is_pack_key,
    pack_version,
    raw_text,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from lairs._types import JsonValue

__all__ = ["STORE_LAYOUT_VERSION", "RecordDiff", "Repository", "Workspace"]

STORE_LAYOUT_VERSION = PACK_LAYOUT_VERSION
"""The newest store layout version this lairs reads and writes.

Layout 1 is the per-record layout, recognized by the absence of a
``layout.json`` marker. Layout 2 adds packed data sets and the journaled
working-tree index; it is a superset of layout 1, so a layout-1 repository is
upgraded in place on its first write.
"""

# the working-tree subdirectory holding content-addressed record values.
_RECORDS_DIR = "records"
# the working-tree subdirectory of ``records`` holding pack files.
_PACKS_DIR = "packs"
# the working-tree file holding the AT-URI -> record metadata index.
_INDEX_FILE = "index.json"
# the append-only journal of index updates since the last commit.
_JOURNAL_FILE = "index.log"
# the working-tree store layout marker.
_LAYOUT_FILE = "layout.json"
# the index-location prefix of a record held in a working-tree pack file.
_PACK_LOCATOR = "pack:"
# the default number of records per pack.
_DEFAULT_BATCH_SIZE = 4096
# the number of decoded working-tree packs kept in memory for ``load``.
_PACK_CACHE_SIZE = 8
# a pack payload entry is the pair ``[uri, value]``.
_PACK_ENTRY_ARITY = 2
# the default commit author when a caller does not supply one.
_DEFAULT_AUTHOR = "lairs <lairs@layers.pub>"
# the source-JSON payload that marks a record as deleted at a revision. panproto
# canonicalizes it on commit and decodes it before the ancestry fold sees it.
_TOMBSTONE_BYTES = b'{"$tombstone":true}'


def _is_tombstone(value: JsonValue) -> bool:
    """Return whether ``value`` is the semantic record-removal marker."""
    return isinstance(value, dict) and value == {"$tombstone": True}


def _keyed_record(dataset: dict[str, JsonValue]) -> tuple[str, JsonValue] | None:
    """Return the one keyed record in a decoded committed data set.

    Lairs stages one JSON record per AT-URI key. An unkeyed data set belongs to
    another Panproto client and is ignored; a keyed set that violates the
    one-record invariant is a malformed Lairs repository.
    """
    key = dataset.get("key")
    if key is None:
        return None
    if not isinstance(key, str):
        msg = "committed data set key is not a string"
        raise panproto.VcsError(msg)
    records = dataset.get("records")
    if not isinstance(records, list) or len(records) != 1:
        count = len(records) if isinstance(records, list) else "non-list"
        msg = f"committed data set for {key!r} contains {count} records; expected 1"
        raise panproto.VcsError(msg)
    return key, records[0]


def _dataset_entries(
    dataset: dict[str, JsonValue],
    revision: str,
) -> list[tuple[str, JsonValue]]:
    """Return the ``(uri, value)`` entries of one decoded committed data set.

    A per-record data set yields its one keyed record; a pack yields its
    entries in staging order; an unkeyed data set belongs to another Panproto
    client and yields nothing.

    Raises
    ------
    panproto.VcsError
        If the data set is a malformed Lairs data set, or a pack written under a
        store layout this lairs does not know.
    """
    key = dataset.get("key")
    if isinstance(key, str) and is_pack_key(key):
        pack_version(key)
        records = dataset.get("records")
        if not isinstance(records, list) or len(records) != 1:
            msg = f"committed pack {key!r} does not hold exactly one envelope"
            raise panproto.VcsError(msg)
        return decode_entries(
            records[0],
            where=f"committed pack {key!r} at {revision}",
        )
    keyed = _keyed_record(dataset)
    return [] if keyed is None else [keyed]


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
    """Return a collision-free filesystem-safe file stem for an AT-URI.

    The stem is the SHA-256 hex digest of the UTF-8 AT-URI, which is injective
    for distinct URIs and free of path separators or other reserved characters.
    The working-tree index maps each AT-URI back to its stem, so the stem need
    not be human-readable, and two distinct AT-URIs can never share a record
    file.

    Parameters
    ----------
    uri : str
        The AT-URI to encode.

    Returns
    -------
    str
        A slash-free, collision-free stem suitable for a file name.
    """
    return hashlib.sha256(uri.encode("utf-8")).hexdigest()


def _replay(index: dict[str, str], line: str) -> None:
    """Apply one index-journal line to ``index`` in place.

    A line that does not parse can only be the last one, cut short by an
    interruption while it was written, and it is skipped.
    """
    try:
        update: JsonValue = json.loads(line)
    except json.JSONDecodeError:
        return
    if not isinstance(update, dict):
        return
    uri = update.get("uri")
    location = update.get("loc")
    if not isinstance(uri, str):
        return
    if isinstance(location, str):
        index[uri] = location
    else:
        index.pop(uri, None)


class RecordDiff(dx.Model):
    """A structural diff of the record set between two revisions.

    Attributes
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

    A handle caches the working-tree index (revalidated against the files on
    disk on every read) and remembers which record schema it staged last, so
    one writer per repository at a time is assumed, as with any working tree.

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

    Raises
    ------
    panproto.VcsError
        If the working tree is marked with a store layout newer than
        :data:`STORE_LAYOUT_VERSION`.
    """

    def __init__(self, inner: dx.Repository) -> None:
        self.inner = inner
        self.path = Path(inner.working_dir)
        self._layout = self._read_layout()
        # didactic's wrapper does not yet surface panproto's schema-aware
        # committed-data read, so history reads go through a native handle on
        # the same store. both handles read refs and objects from disk on each
        # call, so commits made through ``inner`` are visible here.
        self._native = panproto.Repository.open(str(self.path))
        # the working-tree index, with the file signature it was read at.
        self._index: dict[str, str] = {}
        self._index_signature: tuple[int, ...] | None = None
        # the record class whose schema was staged (or committed) last through
        # this handle; re-staging it is a no-op that costs a theory build.
        self._active_schema: type[dx.Model] | None = None
        # decoded working-tree packs, most recently used last.
        self._pack_cache: dict[str, list[str]] = {}

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
        repo = cls(dx.Repository.init(path))
        repo._mark_layout()
        return repo

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

        Raises
        ------
        panproto.VcsError
            If the working tree is marked with a store layout newer than
            :data:`STORE_LAYOUT_VERSION`.
        """
        return cls(dx.Repository.open(path))

    # store layout -------------------------------------------------------------

    def _read_layout(self) -> int:
        """Return the working tree's store layout version, checking it."""
        marker = self.path / _LAYOUT_FILE
        if not marker.exists():
            return 1
        loaded: JsonValue = json.loads(marker.read_text(encoding="utf-8"))
        version = loaded.get("layout") if isinstance(loaded, dict) else None
        if not isinstance(version, int) or isinstance(version, bool):
            msg = f"{marker} does not name a store layout version"
            raise panproto.VcsError(msg)
        if version > STORE_LAYOUT_VERSION:
            msg = (
                f"{self.path} uses store layout {version}, but this lairs reads "
                f"layout {STORE_LAYOUT_VERSION} at most; upgrade lairs to open it"
            )
            raise panproto.VcsError(msg)
        return version

    def _mark_layout(self) -> None:
        """Mark the working tree with the current store layout version."""
        if self._layout == STORE_LAYOUT_VERSION:
            return
        marker = {"layout": STORE_LAYOUT_VERSION, "store": "lairs"}
        (self.path / _LAYOUT_FILE).write_text(
            json.dumps(marker, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self._layout = STORE_LAYOUT_VERSION

    def layout_version(self) -> int:
        """Return the store layout version of the working tree.

        A repository that only ever saw the per-record layout and was never
        written by a layout-2 lairs reports 1. Any write by this lairs, and
        :meth:`init`, marks the working tree with :data:`STORE_LAYOUT_VERSION`.

        Returns
        -------
        int
            The store layout version.
        """
        return self._layout

    # working-tree record store ------------------------------------------------

    def _records_dir(self) -> Path:
        """Return the working-tree records directory, creating it if needed."""
        records = self.path / _RECORDS_DIR
        records.mkdir(parents=True, exist_ok=True)
        return records

    def _packs_dir(self) -> Path:
        """Return the working-tree packs directory, creating it if needed."""
        packs = self._records_dir() / _PACKS_DIR
        packs.mkdir(parents=True, exist_ok=True)
        return packs

    def _index_path(self) -> Path:
        """Return the path to the working-tree AT-URI index file."""
        return self.path / _INDEX_FILE

    def _journal_path(self) -> Path:
        """Return the path to the working-tree index journal."""
        return self.path / _JOURNAL_FILE

    def _signature(self) -> tuple[int, ...]:
        """Return a cheap signature of the on-disk index and journal."""
        signature: list[int] = []
        for path in (self._index_path(), self._journal_path()):
            try:
                stat = path.stat()
            except FileNotFoundError:
                signature.extend((-1, -1))
            else:
                signature.extend((stat.st_mtime_ns, stat.st_size))
        return tuple(signature)

    def _read_index(self) -> dict[str, str]:
        """Return the AT-URI -> record location index of the working tree.

        The index is ``index.json`` with the ``index.log`` journal replayed over
        it. The result is cached and reused while neither file changes on disk.
        The returned mapping is shared with the cache and must not be mutated.
        """
        signature = self._signature()
        if signature == self._index_signature:
            return self._index
        index: dict[str, str] = {}
        index_path = self._index_path()
        if index_path.exists():
            loaded = json.loads(index_path.read_text(encoding="utf-8"))
            index = {str(key): str(value) for key, value in loaded.items()}
        journal_path = self._journal_path()
        if journal_path.exists():
            with journal_path.open(encoding="utf-8") as journal:
                for line in journal:
                    _replay(index, line)
        self._index = index
        self._index_signature = signature
        return index

    def _journal(self, updates: list[tuple[str, str | None]]) -> None:
        """Append index updates to the journal and to the cached index.

        Parameters
        ----------
        updates : list of (str, str or None)
            ``(uri, location)`` pairs in order; a ``None`` location removes the
            AT-URI from the index.
        """
        if not updates:
            return
        self._mark_layout()
        index = self._read_index()
        lines = [
            json.dumps({"uri": uri, "loc": loc}, ensure_ascii=False) + "\n"
            for uri, loc in updates
        ]
        with self._journal_path().open("a", encoding="utf-8") as journal:
            journal.writelines(lines)
        for uri, loc in updates:
            if loc is None:
                index.pop(uri, None)
            else:
                index[uri] = loc
        self._index_signature = self._signature()

    def _compact_index(self) -> None:
        """Fold the journal into ``index.json`` and remove the journal."""
        journal_path = self._journal_path()
        if not journal_path.exists():
            return
        index = self._read_index()
        index_path = self._index_path()
        partial = index_path.with_name(f"{_INDEX_FILE}.partial")
        partial.write_text(
            json.dumps(index, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        # the rename is atomic, and replaying the journal over the new index is
        # idempotent, so an interruption between the two steps loses nothing.
        partial.replace(index_path)
        journal_path.unlink()
        self._index_signature = self._signature()

    def _stage_schema(self, model_cls: type[dx.Model]) -> None:
        """Stage a record type's schema unless it is the one staged last."""
        if self._active_schema is model_cls:
            return
        try:
            self.inner.add(model_cls)
        except panproto.VcsError as exc:
            # re-staging a record type whose schema is already committed and
            # unchanged is a no-op for the schema VCS. the staged record value is
            # the real change the commit captures. didactic surfaces this as a
            # VcsError with no dedicated subtype, so it is discriminated by its
            # message; any other VcsError is a real failure and re-raised.
            if "no changes detected" not in str(exc).lower():
                raise
        self._active_schema = model_cls

    def save(self, uri: str, model: dx.Model) -> None:
        """Stage a record value and its schema for the next commit.

        The record value is written as JSON into the working tree, indexed by its
        AT-URI, and staged as committed data in the per-record layout, so a
        revision pins the exact value. The record type's Model schema is staged
        alongside it, so the commit captures both the data and its structure.

        Each call costs one native staging call, whose price grows with the
        number of data sets already staged for the commit, so ``save`` suits
        edits of a few records. Use :meth:`save_many` or :meth:`save_many_raw`
        to stage many records at once.

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
        self._journal([(uri, stem)])
        self._stage_schema(type(model))
        # stage the value as committed data keyed by AT-URI, so a revision pins
        # the exact value and decoded_data_at reads it back under that key.
        self.inner.add_data(str(record_path), key=uri)

    def save_many(
        self,
        records: Iterable[tuple[str, dx.Model]],
        *,
        batch_size: int = _DEFAULT_BATCH_SIZE,
    ) -> int:
        """Stage many (AT-URI, model) records for the next commit.

        Records are grouped by collection NSID and staged in the packed layout,
        ``batch_size`` records per pack, so staging costs one native call per
        pack rather than per record. The iterable is consumed lazily and only
        one partial pack per collection is held in memory. Records of different
        model types may be interleaved, and the method may be called several
        times before one :meth:`commit`. A record staged twice keeps its later
        value, as with :meth:`save`.

        Each value is stored as its ``model_dump_json`` text, so
        :meth:`content_at` returns the same JSON value that :meth:`save` would
        commit for it.

        Parameters
        ----------
        records : iterable of (str, didactic.api.Model)
            The ``(uri, model)`` pairs to stage.
        batch_size : int, optional
            The maximum number of records per pack.

        Returns
        -------
        int
            The number of records staged.

        Raises
        ------
        ValueError
            If ``batch_size`` is not positive.

        Notes
        -----
        If the iterable raises part way, the records it yielded before the
        error are still staged.
        """
        texts = ((uri, model.model_dump_json()) for uri, model in records)
        return self._stage_packed(texts, batch_size)

    def save_many_raw(
        self,
        records: Iterable[tuple[str, JsonValue]],
        *,
        batch_size: int = _DEFAULT_BATCH_SIZE,
    ) -> int:
        """Stage many (AT-URI, raw JSON record value) pairs for the next commit.

        The value is stored exactly as given, typically the record as a PDS
        serves it, with its ``$type``, explicit nulls, and DAG-JSON objects such
        as ``{"$link": ...}``. No model validation is done, and a record whose
        collection has no generated model is stored all the same.
        :meth:`content_at` and :meth:`load_raw` return the value unchanged: the
        same keys in the same order, the same nesting and list order, and the
        same numbers, including integers beyond 64 bits. :meth:`load` drops the
        wire ``$type`` and rewrites blob objects before validating.

        Staging is otherwise as in :meth:`save_many`.

        Parameters
        ----------
        records : iterable of (str, JsonValue)
            The ``(uri, value)`` pairs to stage.
        batch_size : int, optional
            The maximum number of records per pack.

        Returns
        -------
        int
            The number of records staged.

        Raises
        ------
        ValueError
            If ``batch_size`` is not positive or a value holds a non-finite
            float, which JSON cannot represent.
        """
        texts = ((uri, raw_text(value)) for uri, value in records)
        return self._stage_packed(texts, batch_size)

    def _stage_packed(self, texts: Iterable[tuple[str, str]], batch_size: int) -> int:
        """Stage ``(uri, json text)`` pairs as packs, one collection per pack."""
        if batch_size < 1:
            msg = f"batch_size must be positive, not {batch_size}"
            raise ValueError(msg)
        buffers: dict[str, list[tuple[str, str]]] = {}
        count = 0
        try:
            for uri, text in texts:
                nsid = _nsid_of(uri)
                buffer = buffers.setdefault(nsid, [])
                buffer.append((uri, entry_line(uri, text)))
                count += 1
                if len(buffer) >= batch_size:
                    self._flush_pack(nsid, buffers.pop(nsid))
        finally:
            # a uri always maps to one collection, so flushing the buffers in
            # any order keeps each uri's entries in staging order.
            while buffers:
                nsid, buffer = buffers.popitem()
                self._flush_pack(nsid, buffer)
        return count

    def _flush_pack(self, nsid: str, entries: list[tuple[str, str]]) -> None:
        """Write one pack to the working tree and stage it as committed data."""
        key, envelope = encode_pack(nsid, [line for _, line in entries])
        name = hashlib.sha256(envelope.encode("utf-8")).hexdigest()
        pack_path = self._packs_dir() / f"{name}.json"
        pack_path.write_text(envelope, encoding="utf-8")
        self._stage_schema(PackEnvelope)
        self.inner.add_data(str(pack_path), key=key)
        self._journal(
            [
                (uri, f"{_PACK_LOCATOR}{name}:{position}")
                for position, (uri, _) in enumerate(entries)
            ],
        )

    def forget(self, uri: str) -> None:
        """Stage a record's removal for the next commit.

        Removes the AT-URI from the working-tree index (and its JSON file, for a
        record saved per record), and stages a tombstone as committed data under
        the same key. The tombstone is folded by :meth:`_state_at`, so the record
        is absent from the reconstructed value set at the committed revision and
        a revision-to-revision :meth:`diff` reports it in ``removed``. A record
        staged through either layout is forgotten the same way.

        Staging a tombstone requires a schema to bind to, so the repository must
        already have at least one commit (the record's type schema was committed
        when it was first saved).

        Parameters
        ----------
        uri : str
            The AT-URI of the record to remove.

        Raises
        ------
        KeyError
            If the AT-URI is not present in the working tree.
        """
        location = self._read_index().get(uri)
        if location is None:
            msg = f"cannot forget a record not in the working tree: {uri}"
            raise KeyError(msg)
        if not location.startswith(_PACK_LOCATOR):
            (self._records_dir() / f"{location}.json").unlink(missing_ok=True)
        self._journal([(uri, None)])
        tombstone_path = self._records_dir() / f"{_safe_name(uri)}.tombstone.json"
        tombstone_path.write_bytes(_TOMBSTONE_BYTES)
        self.inner.add_data(str(tombstone_path), key=uri)

    def staged_uris(self) -> list[str]:
        """Return the AT-URIs currently present in the working tree.

        Returns
        -------
        list of str
            The AT-URIs of records written to the working tree, sorted.
        """
        return sorted(self._read_index())

    def _pack_lines(self, name: str) -> list[str]:
        """Return the payload lines of a working-tree pack, through a cache."""
        lines = self._pack_cache.pop(name, None)
        if lines is None:
            pack_path = self._records_dir() / _PACKS_DIR / f"{name}.json"
            envelope: JsonValue = json.loads(pack_path.read_text(encoding="utf-8"))
            lines = decode_lines(envelope, where=str(pack_path))
            if len(self._pack_cache) >= _PACK_CACHE_SIZE:
                self._pack_cache.pop(next(iter(self._pack_cache)))
        self._pack_cache[name] = lines
        return lines

    def _packed_value(self, location: str) -> JsonValue:
        """Return the value a working-tree pack holds at an index location."""
        name, _, position = location.removeprefix(_PACK_LOCATOR).rpartition(":")
        entry: JsonValue = json.loads(self._pack_lines(name)[int(position)])
        if not isinstance(entry, list) or len(entry) != _PACK_ENTRY_ARITY:
            msg = f"working-tree pack {name} holds a malformed entry"
            raise panproto.VcsError(msg)
        return entry[1]

    def load(self, uri: str, model_cls: type[dx.Model]) -> dx.Model | None:
        """Load a record value from the working tree by AT-URI.

        A raw record staged by :meth:`save_many_raw` is validated the way a PDS
        record is: the wire ``$type`` is dropped and blob objects are rewritten
        to :class:`~lairs.records.blobref.BlobRef` shape first.

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
        location = self._read_index().get(uri)
        if location is None:
            return None
        if location.startswith(_PACK_LOCATOR):
            value = self._packed_value(location)
            if isinstance(value, dict):
                value = {
                    key: normalize_blob_refs(item)
                    for key, item in value.items()
                    if key != "$type"
                }
            return model_cls.model_validate_json(json.dumps(value))
        record_path = self._records_dir() / f"{location}.json"
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
            A record staged by :meth:`save_many_raw` comes back unchanged.
        """
        location = self._read_index().get(uri)
        if location is None:
            return None
        if location.startswith(_PACK_LOCATOR):
            return self._packed_value(location)
        record_path = self._records_dir() / f"{location}.json"
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
        revision = self.inner.commit(message, author=author)
        self._compact_index()
        return revision

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
        schema-decoded committed data, keyed by AT-URI, and the two sets are
        compared by content.

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

    def content_at(self, ref: str) -> dict[str, JsonValue]:
        """Return the committed record values at a revision, keyed by AT-URI.

        Each value is the source-JSON-equivalent record content folded over the
        revision's commit ancestry, so a record removed by a tombstone at or
        before ``ref`` is absent. Panproto decodes both historical source JSON
        and current canonical committed data through the schema stored with the
        data set.

        Parameters
        ----------
        ref : str
            The revision to read (ref expression).

        Returns
        -------
        dict of str to JsonValue
            The decoded record values at the revision, keyed by AT-URI.
        """
        return self._state_at(ref)

    def _state_at(self, ref: str) -> dict[str, JsonValue]:
        """Reconstruct the committed record values at a revision, keyed by AT-URI.

        Committed data is recorded per commit, so the value set at ``ref`` is the
        fold of ``decoded_data_at`` over the revision's ancestry, oldest commit
        first, with the latest value for each AT-URI winning.

        Parameters
        ----------
        ref : str
            The revision to read (ref expression).

        Returns
        -------
        dict of str to JsonValue
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
        state: dict[str, JsonValue] = {}
        for cid in order:
            for dataset in self._native.decoded_data_at(cid):
                for key, record in _dataset_entries(dataset, cid):
                    if _is_tombstone(record):
                        state.pop(key, None)
                    else:
                        state[key] = record
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
