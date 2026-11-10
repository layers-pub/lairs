"""Dataset-level pull and pin: one resumable snapshot of a whole dataset.

A published Layers dataset is spread over several accounts, one per record
type: a corpus account, an expression account, and (for annotated data)
segmentation, annotation, and alignment accounts, all sharing one handle stem.
A PDS serves only the current state of each account, so a reproducible analysis
has to pin the exact records it read. This module does both jobs in one step.

:func:`pull_dataset` resolves the accounts a corpus depends on, fetches each as
one repository archive, stages its records into a local
:class:`~lairs.store.repository.Repository` exactly as served, and commits one
snapshot per account. It is resumable: an account already pulled at its current
commit is skipped, so an interrupted run continues where it stopped.

The result is a :class:`DatasetPin`, written next to the records as
``lairs-pin.json`` with a record listing in ``lairs-pin.records.tsv.gz``. The
pin names the corpus, each account's signed commit, every record's CID, and a
content hash over all of them. :func:`verify_pin` checks a local snapshot
against its pin offline, by recomputing each record's CID from the stored value,
and :func:`check_remote` reports which accounts have moved upstream since.
"""

from __future__ import annotations

import gzip
import hashlib
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003  (runtime: public signatures)
from typing import TYPE_CHECKING

import didactic.api as dx
import httpx
import panproto

from lairs._aturi import authority_of, nsid_of
from lairs.atproto._car import record_cid
from lairs.atproto.pds import (
    PdsClient,
    iter_repo_car_records,
    read_repo_car_commit,
)
from lairs.store.repository import Repository

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping

    from lairs._types import JsonValue

__all__ = [
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
]

PIN_FILE = "lairs-pin.json"
"""The file name of the pin manifest inside a pulled dataset directory."""

PIN_RECORDS_FILE = "lairs-pin.records.tsv.gz"
"""The file name of the pinned ``AT-URI <tab> CID`` record listing."""

PIN_VERSION = 1
"""The pin manifest format version this module reads and writes."""

# the working subdirectory that holds a repository archive while it is ingested.
_SCRATCH_DIR = ".lairs-pull"

# the account roles a pin records.
_ROLE_CORPUS = "corpus"
_ROLE_CATALOG = "catalog"
_ROLE_REFERENCE = "reference"

# the second NSID segment of every pub.layers record collection. a dataset's
# record-type accounts are named ``<namespace>.<stem>`` after these.
_NAMESPACES: tuple[str, ...] = (
    "alignment",
    "annotation",
    "changelog",
    "corpus",
    "eprint",
    "expression",
    "graph",
    "judgment",
    "media",
    "ontology",
    "persona",
    "resource",
    "segmentation",
)

# the collections whose records are the data a corpus is made of. a reference
# to one of these is always followed, so the expressions a corpus cites are
# pulled even when they live under another dataset's handle stem.
_CORE_COLLECTIONS = frozenset(
    {
        "pub.layers.corpus.corpus",
        "pub.layers.expression.expression",
        "pub.layers.media.media",
    },
)

# the collections whose records are scanned for references on every pull. they
# are small, and between them they name every expression a corpus holds.
_SCANNED_COLLECTIONS = frozenset(
    {
        "pub.layers.catalog.collection",
        "pub.layers.catalog.membership",
        "pub.layers.corpus.corpus",
        "pub.layers.corpus.membership",
        "pub.layers.expression.expression",
        "pub.layers.media.media",
    },
)

_AT_PREFIX = "at://"
_MIN_URI_PARTS = 2


class PinError(RuntimeError):
    """A dataset could not be pulled, or a pin could not be read."""


class CollectionCount(dx.Model):
    """The number of records one account holds in one collection.

    Attributes
    ----------
    nsid : str
        The collection NSID.
    count : int
        The number of records pinned in that collection.
    """

    nsid: str = dx.field(description="the collection NSID")
    count: int = dx.field(description="records pinned in the collection")


class AccountPin(dx.Model):
    """The pinned state of one account of a dataset.

    Attributes
    ----------
    did : str
        The account's DID.
    handle : str or None
        The account's handle when it was pulled, if the PDS reported one.
    role : str
        Why the account belongs to the dataset: ``corpus`` (it holds the corpus
        record), ``catalog`` (the dataset's base account), a record-type
        namespace such as ``expression`` or ``annotation`` (a sibling account
        under the dataset's handle stem), or ``reference`` (an account a pulled
        record cites).
    commit : str
        The CID of the account's signed commit when it was pulled.
    rev : str
        The revision of that commit.
    data : str
        The CID of the Merkle search tree root that commit signs.
    record_count : int
        The number of records pinned from the account.
    collections : tuple of CollectionCount
        The record count per collection, sorted by NSID.
    records_sha256 : str
        The SHA-256 of the account's sorted ``AT-URI <tab> CID`` lines.
    revision : str or None
        The local repository revision that holds the account's records, or
        ``None`` for an account with no records.
    """

    did: str = dx.field(description="the account's DID")
    handle: str | None = dx.field(default=None, description="the account's handle")
    role: str = dx.field(description="why the account belongs to the dataset")
    commit: str = dx.field(description="CID of the account's signed commit")
    rev: str = dx.field(description="revision of the signed commit")
    data: str = dx.field(description="CID of the Merkle search tree root")
    record_count: int = dx.field(description="records pinned from the account")
    collections: tuple[dx.Embed[CollectionCount], ...] = dx.field(
        default=(),
        description="record count per collection, sorted by NSID",
    )
    records_sha256: str = dx.field(
        description="SHA-256 of the sorted AT-URI and CID lines",
    )
    revision: str | None = dx.field(
        default=None,
        description="local repository revision holding the records",
    )


class DatasetPin(dx.Model):
    """A pin of one dataset: what was pulled, from where, at which commits.

    Attributes
    ----------
    pin_version : int
        The manifest format version.
    corpus_uri : str
        The corpus AT-URI the dataset was resolved from, in DID form.
    endpoint : str
        The base URL of the PDS the dataset was pulled from.
    with_annotations : bool
        Whether the dataset's sibling record-type accounts were pulled.
    with_references : bool
        Whether every account a pulled record cites was pulled.
    complete : bool
        Whether every resolved account was pulled. A pin written by an
        interrupted run is not complete and carries no content hash.
    accounts : tuple of AccountPin
        The pinned accounts, in the order they were pulled.
    external_refs : tuple of str
        The DIDs or handles that pulled records cite but that were not pulled.
    record_count : int
        The total number of pinned records.
    content_sha256 : str or None
        The SHA-256 over every account's ``DID <tab> records_sha256`` line,
        sorted by DID. Because a record's CID is the hash of its content, this
        one value fixes the content of the whole dataset.
    revision : str or None
        The local repository revision of the complete snapshot.
    created_at : str
        When the pin was last written, as an ISO 8601 UTC timestamp.
    """

    pin_version: int = dx.field(default=PIN_VERSION, description="manifest version")
    corpus_uri: str = dx.field(description="the corpus AT-URI, in DID form")
    endpoint: str = dx.field(description="base URL of the PDS pulled from")
    with_annotations: bool = dx.field(
        default=False,
        description="whether sibling record-type accounts were pulled",
    )
    with_references: bool = dx.field(
        default=False,
        description="whether every cited account was pulled",
    )
    complete: bool = dx.field(
        default=False,
        description="whether every resolved account was pulled",
    )
    accounts: tuple[dx.Embed[AccountPin], ...] = dx.field(
        default=(),
        description="the pinned accounts, in pull order",
    )
    external_refs: tuple[str, ...] = dx.field(
        default=(),
        description="cited authorities that were not pulled",
    )
    record_count: int = dx.field(default=0, description="total pinned records")
    content_sha256: str | None = dx.field(
        default=None,
        description="SHA-256 over the per-account record digests",
    )
    revision: str | None = dx.field(
        default=None,
        description="local repository revision of the complete snapshot",
    )
    created_at: str = dx.field(description="ISO 8601 UTC time the pin was written")


class PinVerification(dx.Model):
    """The outcome of checking a local snapshot against its pin.

    Attributes
    ----------
    ok : bool
        Whether the snapshot matches the pin exactly.
    record_count : int
        The number of records checked.
    missing : tuple of str
        Pinned AT-URIs absent from the snapshot.
    unexpected : tuple of str
        AT-URIs in the snapshot, under a pinned account, that the pin does not
        list.
    changed : tuple of str
        AT-URIs whose stored value no longer hashes to the pinned CID.
    problems : tuple of str
        Other mismatches (a digest or a count that disagrees with the pin).
    """

    ok: bool = dx.field(description="whether the snapshot matches the pin")
    record_count: int = dx.field(default=0, description="records checked")
    missing: tuple[str, ...] = dx.field(default=(), description="pinned but absent")
    unexpected: tuple[str, ...] = dx.field(
        default=(),
        description="present under a pinned account but not pinned",
    )
    changed: tuple[str, ...] = dx.field(
        default=(),
        description="stored value no longer hashes to the pinned CID",
    )
    problems: tuple[str, ...] = dx.field(default=(), description="other mismatches")


class AccountDrift(dx.Model):
    """How one pinned account compares with its current upstream state.

    Attributes
    ----------
    did : str
        The account's DID.
    handle : str or None
        The account's pinned handle.
    pinned_commit : str
        The commit CID the pin recorded.
    remote_commit : str or None
        The account's current commit CID, or ``None`` when the PDS did not
        report one (for instance because the account is gone).
    moved : bool
        Whether the account's current commit differs from the pinned one.
    """

    did: str = dx.field(description="the account's DID")
    handle: str | None = dx.field(default=None, description="the pinned handle")
    pinned_commit: str = dx.field(description="commit CID the pin recorded")
    remote_commit: str | None = dx.field(
        default=None,
        description="the account's current commit CID",
    )
    moved: bool = dx.field(description="whether the account moved upstream")


# record listing ---------------------------------------------------------------


def _line(uri: str, cid: str) -> str:
    """Return one ``AT-URI <tab> CID`` listing line."""
    return f"{uri}\t{cid}\n"


def _records_digest(records: Mapping[str, str]) -> str:
    """Return the SHA-256 of an account's sorted ``AT-URI <tab> CID`` lines.

    Parameters
    ----------
    records : collections.abc.Mapping of str to str
        The account's record CIDs, keyed by AT-URI.

    Returns
    -------
    str
        The hex digest.
    """
    digest = hashlib.sha256()
    for uri in sorted(records):
        digest.update(_line(uri, records[uri]).encode("utf-8"))
    return digest.hexdigest()


def _content_digest(accounts: tuple[AccountPin, ...]) -> str:
    """Return the dataset content hash over the per-account record digests.

    Parameters
    ----------
    accounts : tuple of AccountPin
        The pinned accounts.

    Returns
    -------
    str
        The hex SHA-256 of the ``DID <tab> records_sha256`` lines, sorted by
        DID.
    """
    digest = hashlib.sha256()
    for account in sorted(accounts, key=lambda pin: pin.did):
        digest.update(f"{account.did}\t{account.records_sha256}\n".encode())
    return digest.hexdigest()


def _collection_counts(uris: Mapping[str, str]) -> tuple[CollectionCount, ...]:
    """Tally an account's records per collection, sorted by NSID."""
    counts: dict[str, int] = {}
    for uri in uris:
        nsid = nsid_of(uri)
        counts[nsid] = counts.get(nsid, 0) + 1
    return tuple(
        CollectionCount(nsid=nsid, count=counts[nsid]) for nsid in sorted(counts)
    )


def read_pin_records(directory: Path) -> dict[str, str]:
    """Read the pinned record listing of a pulled dataset.

    Parameters
    ----------
    directory : pathlib.Path
        The pulled dataset directory.

    Returns
    -------
    dict of str to str
        Every pinned record's CID, keyed by AT-URI; empty when the directory
        has no listing.

    Raises
    ------
    PinError
        When the listing is unreadable or a line is malformed.
    """
    path = directory / PIN_RECORDS_FILE
    if not path.exists():
        return {}
    records: dict[str, str] = {}
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                uri, tab, cid = line.rstrip("\n").partition("\t")
                if not tab or not uri or not cid:
                    msg = f"malformed line in {path}: {line!r}"
                    raise PinError(msg)
                records[uri] = cid
    except (OSError, EOFError) as exc:
        msg = f"cannot read the pinned record listing {path}: {exc}"
        raise PinError(msg) from exc
    return records


def _write_pin_records(directory: Path, records: Mapping[str, str]) -> None:
    """Write the pinned record listing, sorted by AT-URI, atomically.

    The archive carries no timestamp or file name, so the same listing always
    produces the same bytes.

    Parameters
    ----------
    directory : pathlib.Path
        The pulled dataset directory.
    records : collections.abc.Mapping of str to str
        Every pinned record's CID, keyed by AT-URI.
    """
    path = directory / PIN_RECORDS_FILE
    partial = path.with_name(f"{path.name}.part")
    with (
        partial.open("wb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as handle,
    ):
        for uri in sorted(records):
            handle.write(_line(uri, records[uri]).encode("utf-8"))
    partial.replace(path)


# pin manifest -----------------------------------------------------------------


def read_pin(directory: Path) -> DatasetPin | None:
    """Read the pin manifest of a pulled dataset.

    Parameters
    ----------
    directory : pathlib.Path
        The pulled dataset directory.

    Returns
    -------
    DatasetPin or None
        The pin, or ``None`` when the directory has none.

    Raises
    ------
    PinError
        When the manifest is malformed or written by a newer format version.
    """
    path = directory / PIN_FILE
    if not path.exists():
        return None
    try:
        pin = DatasetPin.model_validate_json(path.read_text(encoding="utf-8"))
    except (dx.ValidationError, ValueError) as exc:
        msg = f"cannot read the pin manifest {path}: {exc}"
        raise PinError(msg) from exc
    if pin.pin_version != PIN_VERSION:
        msg = (
            f"pin manifest {path} has format version {pin.pin_version}; "
            f"this lairs reads version {PIN_VERSION}"
        )
        raise PinError(msg)
    return pin


def _write_pin(directory: Path, pin: DatasetPin) -> None:
    """Write the pin manifest atomically."""
    path = directory / PIN_FILE
    partial = path.with_name(f"{path.name}.part")
    partial.write_text(pin.model_dump_json(indent=2) + "\n", encoding="utf-8")
    partial.replace(path)


def _now() -> str:
    """Return the current UTC time as an ISO 8601 timestamp, to the second."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()


# account resolution -----------------------------------------------------------


def _resolve_authority(authority: str, client: PdsClient) -> str | None:
    """Resolve an AT-URI authority to a DID through the PDS.

    Parameters
    ----------
    authority : str
        A DID, or a handle the PDS can resolve.
    client : lairs.atproto.pds.PdsClient
        The PDS client.

    Returns
    -------
    str or None
        The DID, or ``None`` when the handle does not resolve.
    """
    if authority.startswith("did:"):
        return authority
    return client.resolve_handle(authority)


def _handle_of(did: str, client: PdsClient) -> str | None:
    """Return the handle the PDS reports for an account, if any."""
    try:
        handle = client.describe_repo(did).handle
    except httpx.HTTPError:
        return None
    return handle or None


def _stem_of(handle: str | None) -> str | None:
    """Return the dataset handle stem of a record-type account handle.

    A dataset's accounts are named ``[<namespace>.]<stem>``, where the
    namespace is the record type the account holds. The stem is therefore the
    handle with a leading record-type label removed.

    Parameters
    ----------
    handle : str or None
        The handle of one of the dataset's accounts.

    Returns
    -------
    str or None
        The stem, or ``None`` when the handle does not follow the convention.
    """
    if handle is None:
        return None
    label, dot, rest = handle.partition(".")
    if dot and label in _NAMESPACES and rest:
        return rest
    return None


def _collect_authorities(value: JsonValue, found: dict[str, set[str]]) -> None:
    """Collect the AT-URI authorities a JSON value cites, by cited collection.

    Parameters
    ----------
    value : JsonValue
        The value to scan.
    found : dict of str to set of str
        The accumulator, mapping each cited authority to the collections cited
        under it; updated in place.
    """
    if isinstance(value, str):
        if value.startswith(_AT_PREFIX):
            parts = value.removeprefix(_AT_PREFIX).split("/")
            if len(parts) >= _MIN_URI_PARTS and parts[0]:
                found.setdefault(parts[0], set()).add(parts[1])
    elif isinstance(value, dict):
        for item in value.values():
            if item is not None and not isinstance(item, (bool, int, float)):
                _collect_authorities(item, found)
    elif isinstance(value, (list, tuple)):
        for item in value:
            if item is not None and not isinstance(item, (bool, int, float)):
                _collect_authorities(item, found)


class _Plan:
    """The work list of a dataset pull: accounts to fetch and why.

    Parameters
    ----------
    with_references : bool
        Whether every cited account is queued, rather than only the accounts
        that hold the corpus's own data.

    Attributes
    ----------
    cited : dict of str to set of str
        Every authority a scanned record cites, with the collections cited
        under it.
    """

    def __init__(self, *, with_references: bool) -> None:
        self._with_references = with_references
        self._queue: list[tuple[str, str]] = []
        self._roles: dict[str, str] = {}
        self.cited: dict[str, set[str]] = {}

    def add(self, did: str, role: str) -> None:
        """Queue an account, keeping the first role it was given."""
        if did not in self._roles:
            self._roles[did] = role
            self._queue.append((did, role))

    def planned(self, did: str) -> bool:
        """Return whether an account is already queued or pulled."""
        return did in self._roles

    def pending(self) -> Iterator[tuple[str, str]]:
        """Yield queued ``(did, role)`` pairs, including ones queued meanwhile."""
        index = 0
        while index < len(self._queue):
            yield self._queue[index]
            index += 1

    def scans(self, uri: str) -> bool:
        """Return whether a record's references should be collected."""
        return self._with_references or nsid_of(uri) in _SCANNED_COLLECTIONS

    def follows(self, collections: set[str]) -> bool:
        """Return whether a cited authority should be pulled."""
        return self._with_references or bool(collections & _CORE_COLLECTIONS)


def _queue_cited(plan: _Plan, client: PdsClient) -> None:
    """Queue the cited authorities the plan follows, resolving handles."""
    for authority, collections in sorted(plan.cited.items()):
        if not plan.follows(collections):
            continue
        did = _resolve_authority(authority, client)
        if did is not None:
            plan.add(did, _ROLE_REFERENCE)


def _queue_siblings(plan: _Plan, stem: str, client: PdsClient) -> None:
    """Queue every record-type account under the dataset's handle stem."""
    for namespace in _NAMESPACES:
        did = client.resolve_handle(f"{namespace}.{stem}")
        if did is not None:
            plan.add(did, namespace)


def _external_refs(plan: _Plan, client: PdsClient) -> tuple[str, ...]:
    """Return the cited authorities that were not pulled, sorted."""
    external: set[str] = set()
    for authority in plan.cited:
        did = _resolve_authority(authority, client)
        if did is None or not plan.planned(did):
            external.add(authority)
    return tuple(sorted(external))


# ingest -----------------------------------------------------------------------


def _commit(repo: Repository, message: str) -> str | None:
    """Commit the staged records, tolerating a snapshot with nothing new.

    Parameters
    ----------
    repo : lairs.store.repository.Repository
        The repository to commit.
    message : str
        The commit message.

    Returns
    -------
    str or None
        The new revision, or the current head when the staged records equal
        what is already committed.
    """
    try:
        return repo.commit(message)
    except panproto.VcsError as exc:
        text = str(exc).lower()
        if "no changes" in text or "nothing" in text:
            return repo.head()
        raise


class _Ingest:
    """The shared state of one dataset pull, and the per-account ingest step.

    Parameters
    ----------
    repo : lairs.store.repository.Repository
        The repository to stage into.
    client : lairs.atproto.pds.PdsClient
        The PDS client.
    scratch : pathlib.Path
        The directory that holds an archive while it is ingested.
    plan : _Plan
        The pull plan, which collects the references the records cite.
    """

    def __init__(
        self,
        repo: Repository,
        client: PdsClient,
        scratch: Path,
        plan: _Plan,
    ) -> None:
        self.repo = repo
        self.client = client
        self.scratch = scratch
        self.plan = plan
        self._committed: tuple[str, dict[str, JsonValue]] | None = None

    def rescan(self, account: AccountPin) -> None:
        """Collect the references of an account pulled by an earlier run.

        A resumed pull skips the accounts it already holds, but the accounts
        those records cite still have to be resolved, so their references are
        read back from the committed snapshot. The snapshot is read once per
        head revision, not once per account.

        Parameters
        ----------
        account : AccountPin
            The account whose committed records are scanned.
        """
        head = self.repo.head()
        if head is None or account.record_count == 0:
            return
        if self._committed is None or self._committed[0] != head:
            self._committed = (head, self.repo.content_at(head))
        prefix = f"{_AT_PREFIX}{account.did}/"
        for uri, value in self._committed[1].items():
            if uri.startswith(prefix) and self.plan.scans(uri):
                _collect_authorities(value, self.plan.cited)

    def _staged(
        self,
        archive: Path,
        records: dict[str, str],
    ) -> Iterator[tuple[str, JsonValue]]:
        """Yield an archive's records for staging, noting CIDs and references."""
        for uri, cid, value in iter_repo_car_records(archive):
            records[uri] = cid
            if self.plan.scans(uri):
                _collect_authorities(value, self.plan.cited)
            yield uri, value

    def account(
        self,
        did: str,
        role: str,
        previous: Mapping[str, str],
    ) -> tuple[AccountPin, dict[str, str]]:
        """Fetch one account's archive and stage and commit its records.

        Parameters
        ----------
        did : str
            The account's DID.
        role : str
            Why the account belongs to the dataset.
        previous : collections.abc.Mapping of str to str
            The account's records as last pinned, used to remove records that
            are gone upstream.

        Returns
        -------
        tuple of (AccountPin, dict of str to str)
            The account's pin and its record CIDs keyed by AT-URI.

        Raises
        ------
        PinError
            When the archive carries no signed commit.
        """
        archive = self.scratch / f"{hashlib.sha256(did.encode()).hexdigest()}.car"
        self.client.download_repo_car(did, archive)
        records: dict[str, str] = {}
        try:
            commit = read_repo_car_commit(archive)
            if commit is None:
                msg = f"the repository archive of {did} carries no signed commit"
                raise PinError(msg)
            self.repo.save_many_raw(self._staged(archive, records))
        finally:
            archive.unlink(missing_ok=True)
        gone = [uri for uri in previous if uri not in records]
        for uri in gone:
            self.repo.forget(uri)
        handle = _handle_of(did, self.client)
        revision = (
            _commit(self.repo, f"pull {handle or did} at {commit.rev}")
            if records or gone
            else self.repo.head()
        )
        pin = AccountPin(
            did=did,
            handle=handle,
            role=role,
            commit=commit.cid,
            rev=commit.rev,
            data=commit.data,
            record_count=len(records),
            collections=_collection_counts(records),
            records_sha256=_records_digest(records),
            revision=revision if records else None,
        )
        return pin, records


def _reusable(
    did: str,
    prior: Mapping[str, AccountPin],
    client: PdsClient,
) -> AccountPin | None:
    """Return an account's prior pin when it is still current upstream.

    Parameters
    ----------
    did : str
        The account's DID.
    prior : collections.abc.Mapping of str to AccountPin
        The accounts an earlier run pinned, keyed by DID.
    client : lairs.atproto.pds.PdsClient
        The PDS client.

    Returns
    -------
    AccountPin or None
        The prior pin when the account's current commit equals the pinned one,
        else ``None``.
    """
    pinned = prior.get(did)
    if pinned is None:
        return None
    try:
        latest = client.get_latest_commit(did)
    except httpx.HTTPError:
        return None
    return pinned if latest.head == pinned.commit else None


def pull_dataset(  # noqa: PLR0913  (a pull threads several independent knobs)
    corpus_uri: str,
    *,
    into: Path,
    client: PdsClient,
    endpoint: str,
    with_annotations: bool = False,
    with_references: bool = False,
    refresh: bool = False,
    progress: Callable[[str], None] | None = None,
) -> DatasetPin:
    """Pull every account a corpus depends on into one pinned local snapshot.

    The corpus account is pulled first. The accounts that hold the corpus's own
    data are then followed from its records: the base catalog account under the
    same handle stem, and every account the corpus's memberships and
    expressions cite for an expression or media record. With
    ``with_annotations`` the dataset's other record-type accounts
    (segmentation, annotation, alignment, and the rest) are pulled too, found
    by the ``<namespace>.<stem>`` handle convention, since annotations point at
    expressions and are not reachable from the corpus by reference. With
    ``with_references`` every account any pulled record cites is pulled as
    well (ontologies, eprints).

    Each account is fetched as one repository archive, streamed to disk and
    read back one record at a time, staged exactly as served, and committed as
    its own snapshot. The pin manifest is rewritten after every account, so an
    interrupted run can be resumed by calling this again with the same
    arguments: an account whose pinned commit is still its current commit is
    not fetched again. ``refresh`` re-fetches every account regardless. An
    account that has moved upstream is re-pulled, and its records that are gone
    upstream are removed from the snapshot.

    All accounts are read from the one PDS ``client`` talks to.

    Parameters
    ----------
    corpus_uri : str
        The AT-URI of the ``pub.layers.corpus.corpus`` record. Its authority
        may be a DID or a handle.
    into : pathlib.Path
        The directory of the local repository to create or extend.
    client : lairs.atproto.pds.PdsClient
        The PDS client to read through.
    endpoint : str
        The base URL of that PDS, recorded in the pin.
    with_annotations : bool, optional
        Whether to pull the dataset's sibling record-type accounts.
    with_references : bool, optional
        Whether to pull every account a pulled record cites.
    refresh : bool, optional
        Whether to re-fetch accounts whose pinned commit is still current.
    progress : collections.abc.Callable or None, optional
        A sink for one-line progress messages.

    Returns
    -------
    DatasetPin
        The complete pin, as written to ``lairs-pin.json``.

    Raises
    ------
    PinError
        When the corpus authority does not resolve, an existing pin in ``into``
        belongs to a different corpus, or an archive is malformed.
    httpx.HTTPError
        When the PDS cannot be read. The pin written so far is kept, so the
        pull can be resumed.
    """
    report = progress if progress is not None else _silent
    corpus_did = _resolve_authority(authority_of(corpus_uri), client)
    if corpus_did is None:
        msg = f"cannot resolve the authority of {corpus_uri}"
        raise PinError(msg)
    canonical_uri = (
        _AT_PREFIX
        + corpus_did
        + corpus_uri.removeprefix(
            _AT_PREFIX + authority_of(corpus_uri),
        )
    )
    existing = read_pin(into)
    if existing is not None and existing.corpus_uri != canonical_uri:
        msg = (
            f"{into} already pins {existing.corpus_uri}; "
            "pull a different corpus into a different directory"
        )
        raise PinError(msg)
    repo = Repository.init(into)
    scratch = into / _SCRATCH_DIR
    listing = read_pin_records(into)
    prior = {} if existing is None else {pin.did: pin for pin in existing.accounts}
    plan = _Plan(with_references=with_references)
    plan.add(corpus_did, _ROLE_CORPUS)
    stem = _stem_of(_handle_of(corpus_did, client))
    if stem is not None:
        catalog_did = client.resolve_handle(stem)
        if catalog_did is not None:
            plan.add(catalog_did, _ROLE_CATALOG)
        if with_annotations:
            _queue_siblings(plan, stem, client)
    ingest = _Ingest(repo, client, scratch, plan)
    pinned: list[AccountPin] = []
    for did, role in plan.pending():
        prefix = f"{_AT_PREFIX}{did}/"
        reused = None if refresh else _reusable(did, prior, client)
        if reused is not None:
            report(f"up to date: {reused.handle or did} ({reused.record_count})")
            ingest.rescan(reused)
            account = reused
        else:
            report(f"pulling {did} ({role})")
            previous = {
                uri: cid for uri, cid in listing.items() if uri.startswith(prefix)
            }
            account, records = ingest.account(did, role, previous)
            for uri in previous:
                listing.pop(uri, None)
            listing.update(records)
            report(f"pulled {account.handle or did}: {account.record_count} record(s)")
        pinned.append(account)
        _write_pin_records(into, listing)
        _write_pin(
            into,
            DatasetPin(
                corpus_uri=canonical_uri,
                endpoint=endpoint,
                with_annotations=with_annotations,
                with_references=with_references,
                complete=False,
                accounts=tuple(pinned),
                record_count=sum(pin.record_count for pin in pinned),
                created_at=_now(),
            ),
        )
        _queue_cited(plan, client)
    if scratch.is_dir() and not any(scratch.iterdir()):
        scratch.rmdir()
    accounts = tuple(pinned)
    pin = DatasetPin(
        corpus_uri=canonical_uri,
        endpoint=endpoint,
        with_annotations=with_annotations,
        with_references=with_references,
        complete=True,
        accounts=accounts,
        external_refs=_external_refs(plan, client),
        record_count=sum(account.record_count for account in accounts),
        content_sha256=_content_digest(accounts),
        revision=repo.head(),
        created_at=_now(),
    )
    _write_pin(into, pin)
    return pin


def _silent(_message: str) -> None:
    """Discard a progress message."""


# verification -----------------------------------------------------------------


def verify_pin(directory: Path, *, pin: DatasetPin | None = None) -> PinVerification:
    """Check a pulled dataset against its pin, offline.

    The snapshot at the pinned revision is read from the local repository, the
    CID of every record is recomputed from its stored value, and the result is
    compared with the pinned listing, the per-account digests and counts, and
    the dataset content hash. No network access is made, so this proves that
    the local records are byte-for-byte the records that were pulled.

    Parameters
    ----------
    directory : pathlib.Path
        The pulled dataset directory.
    pin : DatasetPin or None, optional
        The pin to check against, for instance one kept under version control
        with an analysis. Defaults to the manifest in ``directory``.

    Returns
    -------
    PinVerification
        Whether the snapshot matches, with every mismatch found.

    Raises
    ------
    PinError
        When no pin is given and the directory has none, or the pin is not
        complete.
    """
    expected = pin if pin is not None else read_pin(directory)
    if expected is None:
        msg = f"{directory} has no {PIN_FILE}"
        raise PinError(msg)
    if not expected.complete or expected.revision is None:
        msg = "the pin is not complete; resume the pull before verifying"
        raise PinError(msg)
    listing = read_pin_records(directory)
    repo = Repository.open(directory)
    content = repo.content_at(expected.revision)
    prefixes = tuple(f"{_AT_PREFIX}{account.did}/" for account in expected.accounts)
    actual: dict[str, str] = {
        uri: record_cid(value)
        for uri, value in content.items()
        if uri.startswith(prefixes)
    }
    missing = sorted(uri for uri in listing if uri not in actual)
    unexpected = sorted(uri for uri in actual if uri not in listing)
    changed = sorted(
        uri for uri, cid in actual.items() if uri in listing and listing[uri] != cid
    )
    problems: list[str] = []
    for account, prefix in zip(expected.accounts, prefixes, strict=True):
        own = {uri: cid for uri, cid in actual.items() if uri.startswith(prefix)}
        if len(own) != account.record_count:
            problems.append(
                f"{account.did}: {len(own)} record(s) stored, "
                f"{account.record_count} pinned",
            )
        if _records_digest(own) != account.records_sha256:
            problems.append(f"{account.did}: record digest differs from the pin")
    if _content_digest(expected.accounts) != expected.content_sha256:
        problems.append("the pin's content hash does not match its account digests")
    ok = not (missing or unexpected or changed or problems)
    return PinVerification(
        ok=ok,
        record_count=len(actual),
        missing=tuple(missing),
        unexpected=tuple(unexpected),
        changed=tuple(changed),
        problems=tuple(problems),
    )


def check_remote(pin: DatasetPin, client: PdsClient) -> tuple[AccountDrift, ...]:
    """Compare each pinned account with its current upstream commit.

    This is the online counterpart of :func:`verify_pin`. It costs one small
    request per account and fetches no records.

    Parameters
    ----------
    pin : DatasetPin
        The pin to compare.
    client : lairs.atproto.pds.PdsClient
        A client for the PDS the dataset was pulled from.

    Returns
    -------
    tuple of AccountDrift
        One entry per pinned account, in pin order.
    """
    drift: list[AccountDrift] = []
    for account in pin.accounts:
        try:
            remote = client.get_latest_commit(account.did).head
        except httpx.HTTPError:
            remote = None
        drift.append(
            AccountDrift(
                did=account.did,
                handle=account.handle,
                pinned_commit=account.commit,
                remote_commit=remote,
                moved=remote != account.commit,
            ),
        )
    return tuple(drift)
