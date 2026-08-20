"""The acquisition surface: sessions joined to participants and media.

An :class:`Acquisition` exposes the records of a behavioural, speech, or neural
study, produced by a dataset's catalogue collection: acquisition sessions, the
participants they recorded, and the media streams they captured. The graph is
held in a :class:`lairs.store.pool.ModelPool` keyed by AT-URI, so cross-refs (a
session's ``participantRefs``, a medium's ``sessionRef`` and ``stream``) resolve
to model instances. The join helpers walk those refs to group related records per
session.

De-identification is by construction upstream: a ``pub.layers.acquisition.participant``
record carries no name, e-mail, DID, or date of birth, because Layers records live
in public PDSes and are broadcast on the firehose, and each carries a required
consent declaration. This surface only reads and joins those records; it adds no
re-identification, never fetches blob bytes, and honours the index's mute path the
same way the corpus surface does.

Loading enumerates the given URI's authority for acquisition sessions,
participants, and media, then follows every AT-URI reference across account
boundaries: a session references its participants (and its experiment protocol),
so those are pulled in even when they live in separate per-namespace accounts.
This mirrors :func:`lairs.data.corpus.load_corpus` and keys the load on its own
NSID map, so an acquisition load never enumerates a corpus's expressions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import didactic.api as dx

from lairs.data._loader import load_graph
from lairs.data.dataset import Dataset
from lairs.records._generated import acquisition as acquisition_records
from lairs.records._generated import media as media_records
from lairs.store.pool import ModelPool

if TYPE_CHECKING:
    from collections.abc import Iterator

    from lairs.atproto.pds import PdsClient
    from lairs.data._loader import PdsSource

__all__ = [
    "Acquisition",
    "SessionWithMedia",
    "SessionWithParticipants",
    "load_acquisition",
]

# the collection NSIDs the acquisition surface joins over.
_SESSION_NSID = "pub.layers.acquisition.session"
_PARTICIPANT_NSID = "pub.layers.acquisition.participant"
_MEDIA_NSID = "pub.layers.media.media"

# the record model class for each acquisition collection NSID.
_NSID_MODELS: dict[str, type[dx.Model]] = {
    _SESSION_NSID: acquisition_records.Session,
    _PARTICIPANT_NSID: acquisition_records.Participant,
    _MEDIA_NSID: media_records.Media,
}

# the recognised load sources, mirroring load_corpus.
_SOURCE_PDS = "pds"
_SOURCE_APPVIEW = "appview"
_SOURCE_AUTO = "auto"
_VALID_SOURCES = frozenset({_SOURCE_PDS, _SOURCE_APPVIEW, _SOURCE_AUTO})


class SessionWithParticipants(dx.Model):
    """A session joined to the participants it recorded.

    Attributes
    ----------
    session : pub.layers.acquisition.Session
        The session record.
    uri : str
        The AT-URI of the session.
    participants : tuple of pub.layers.acquisition.Participant
        The participant records the session's ``participantRefs`` resolve to.
    """

    session: acquisition_records.Session = dx.field(
        description="the joined session record",
    )
    uri: str = dx.field(description="AT-URI of the session")
    participants: tuple[acquisition_records.Participant, ...] = dx.field(
        default_factory=tuple,
        description="participants the session's participantRefs resolve to",
    )


class SessionWithMedia(dx.Model):
    """A session joined to the media streams it captured.

    Attributes
    ----------
    session : pub.layers.acquisition.Session
        The session record.
    uri : str
        The AT-URI of the session.
    media : tuple of pub.layers.media.Media
        The media records whose ``sessionRef`` or ``stream`` points at this
        session.
    """

    session: acquisition_records.Session = dx.field(
        description="the joined session record",
    )
    uri: str = dx.field(description="AT-URI of the session")
    media: tuple[media_records.Media, ...] = dx.field(
        default_factory=tuple,
        description="media whose sessionRef or stream points at this session",
    )


def _stream_target(media: media_records.Media) -> str | None:
    """Return the session AT-URI a medium's ``stream`` objectRef names, if any."""
    stream = media.stream
    if stream is None:
        return None
    return stream.recordRef


class Acquisition:
    """A graph of acquisition records joined by AT-URI cross-references.

    Parameters
    ----------
    pool : lairs.store.pool.ModelPool or None, optional
        A pre-populated pool of records keyed by AT-URI. When omitted an empty
        pool is created.
    uri : str or None, optional
        The AT-URI the acquisition was loaded from (a session or a collection).

    Attributes
    ----------
    pool : lairs.store.pool.ModelPool
        The AT-URI-keyed record graph.
    uri : str or None
        The AT-URI the acquisition was loaded from, if any.
    """

    def __init__(
        self,
        pool: ModelPool | None = None,
        *,
        uri: str | None = None,
    ) -> None:
        self.pool = pool if pool is not None else ModelPool()
        self.uri = uri

    @classmethod
    def new(cls, uri: str | None = None) -> Acquisition:
        """Create an empty acquisition surface for authoring.

        Parameters
        ----------
        uri : str or None, optional
            An AT-URI to associate with the surface.

        Returns
        -------
        Acquisition
            A new, empty acquisition surface.
        """
        return cls(uri=uri)

    def _sessions(self) -> Iterator[tuple[str, acquisition_records.Session]]:
        """Yield ``(uri, session)`` pairs for every session record in the pool."""
        for ref in self.pool.uris():
            model = self.pool.get(ref)
            if isinstance(model, acquisition_records.Session):
                yield ref, model

    def sessions(self) -> Dataset[acquisition_records.Session]:
        """Return a dataset of the acquisition sessions.

        Returns
        -------
        lairs.data.dataset.Dataset
            A dataset of session models, in pool order.
        """
        return Dataset(
            [model for _, model in self._sessions()],
            model=acquisition_records.Session,
        )

    def participants(self) -> Dataset[acquisition_records.Participant]:
        """Return a dataset of the study participants.

        Returns
        -------
        lairs.data.dataset.Dataset
            A dataset of participant models, in pool order.
        """
        records = [
            model
            for ref in self.pool.uris()
            if isinstance(
                (model := self.pool.get(ref)),
                acquisition_records.Participant,
            )
        ]
        return Dataset(records, model=acquisition_records.Participant)

    def media(self) -> Dataset[media_records.Media]:
        """Return a dataset of the session media records.

        Returns
        -------
        lairs.data.dataset.Dataset
            A dataset of media models, in pool order.
        """
        records = [
            model
            for ref in self.pool.uris()
            if isinstance((model := self.pool.get(ref)), media_records.Media)
        ]
        return Dataset(records, model=media_records.Media)

    def sessions_with_participants(self) -> Dataset[SessionWithParticipants]:
        """Join each session to the participants its ``participantRefs`` resolve to.

        A session's ``participantRefs`` are AT-URIs into (possibly separate)
        participant accounts; each is resolved through the pool. A ref that is not
        loaded is skipped, so a session with unresolved participants still appears
        with the participants that did resolve.

        Returns
        -------
        lairs.data.dataset.Dataset
            A dataset of session-and-participants join rows.
        """
        rows: list[SessionWithParticipants] = []
        for uri, session in self._sessions():
            participants: list[acquisition_records.Participant] = []
            for ref in session.participantRefs or ():
                target = self.pool.resolve(ref)
                if isinstance(target, acquisition_records.Participant):
                    participants.append(target)
            rows.append(
                SessionWithParticipants(
                    session=session,
                    uri=uri,
                    participants=tuple(participants),
                ),
            )
        return Dataset(rows, model=SessionWithParticipants)

    def sessions_with_media(self) -> Dataset[SessionWithMedia]:
        """Join each session to the media that stream it.

        A medium belongs to a session when its ``sessionRef`` equals the session
        AT-URI, or when its ``stream`` objectRef's ``recordRef`` does (a stream's
        ``objectId`` then names which of the session's ``streams`` it fills). The
        two are unioned, so a medium reachable by either link is attached once.

        Returns
        -------
        lairs.data.dataset.Dataset
            A dataset of session-and-media join rows.
        """
        grouped: dict[str, list[media_records.Media]] = {}
        for ref in self.pool.uris():
            model = self.pool.get(ref)
            if not isinstance(model, media_records.Media):
                continue
            targets = {model.sessionRef, _stream_target(model)}
            for session_uri in targets:
                if session_uri is not None:
                    grouped.setdefault(session_uri, []).append(model)
        rows = [
            SessionWithMedia(
                session=session,
                uri=uri,
                media=tuple(grouped.get(uri, ())),
            )
            for uri, session in self._sessions()
        ]
        return Dataset(rows, model=SessionWithMedia)

    def add_record(self, uri: str, record: dx.Model) -> None:
        """Add any acquisition record to the graph by AT-URI.

        Parameters
        ----------
        uri : str
            The AT-URI of the record.
        record : didactic.api.Model
            The record to add (a session, participant, or medium).
        """
        self.pool.add(uri, record)


def _load_from_pds(
    uri: str,
    client: PdsSource,
    *,
    follow_refs: bool = True,
) -> Acquisition:
    """Load an acquisition graph from a PDS, following refs across accounts."""
    pool = load_graph(uri, _NSID_MODELS, client, follow_refs=follow_refs)
    return Acquisition(pool, uri=uri)


def load_acquisition(  # noqa: PLR0913  (the loader threads several optional knobs)
    uri: str,
    *,
    source: str = "auto",
    cache_dir: str | None = None,
    revision: str | None = None,
    pds_client: PdsClient | None = None,
    follow_refs: bool = True,
) -> Acquisition:
    """Load an acquisition graph by AT-URI from a PDS.

    Enumerates the AT-URI's authority for acquisition sessions, participants, and
    media, then follows every AT-URI reference across account boundaries,
    transitively, to pull in the participants a session records even when they
    live in separate per-namespace accounts. Pass a session AT-URI, or the
    acquisition-namespace account's AT-URI, whose authority hosts the session
    records. The ``pds`` source reads directly from a PDS; ``auto`` uses the
    injected PDS client. A client may be injected for testing without network
    setup.

    Parameters
    ----------
    uri : str
        The session (or acquisition-account) AT-URI whose authority is enumerated.
    source : str, optional
        The source to load from (``"pds"``, ``"appview"``, or ``"auto"``).
    cache_dir : str or None, optional
        A local cache directory (reserved; not yet used).
    revision : str or None, optional
        A revision to resolve (reserved; not yet used).
    pds_client : lairs.atproto.pds.PdsClient or None, optional
        An injected PDS client, required for the ``pds`` source.
    follow_refs : bool, optional
        Whether to follow AT-URI references across account boundaries. Defaults to
        ``True``.

    Returns
    -------
    Acquisition
        The loaded acquisition graph.

    Raises
    ------
    ValueError
        When ``source`` is not a recognised source value.
    NotImplementedError
        When the appview source is requested (no appview acquisition query yet),
        or the PDS source is requested without an injected client.
    """
    if source not in _VALID_SOURCES:
        valid = sorted(_VALID_SOURCES)
        msg = f"unknown acquisition source {source!r}; expected one of {valid}"
        raise ValueError(msg)
    _ = (cache_dir, revision)
    if source in {_SOURCE_PDS, _SOURCE_AUTO} and pds_client is not None:
        return _load_from_pds(uri, pds_client, follow_refs=follow_refs)
    if source == _SOURCE_APPVIEW:
        msg = "appview acquisition loading is not available; inject a pds_client"
        raise NotImplementedError(msg)
    msg = "acquisition loading needs an injected pds_client until discovery lands"
    raise NotImplementedError(msg)
