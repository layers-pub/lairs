"""Unit tests for lairs.data.acquisition."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from lairs.atproto.pds import RecordEnvelope, RecordNotFoundError
from lairs.data import acquisition as acquisition_mod
from lairs.data.acquisition import Acquisition, load_acquisition
from lairs.records._generated.acquisition import (
    Consent,
    Participant,
    Session,
    Stream,
)
from lairs.records._generated.defs import ObjectRef, Uuid
from lairs.records._generated.media import Media

if TYPE_CHECKING:
    from collections.abc import Iterator

    import didactic.api as dx

_NOW = datetime(2024, 1, 1, tzinfo=UTC)

_ACQ = "did:plc:acq"
_PART = "did:plc:part"
_S1 = f"at://{_ACQ}/pub.layers.acquisition.session/s1"
_P1 = f"at://{_PART}/pub.layers.acquisition.participant/p1"
_M1 = f"at://{_ACQ}/pub.layers.media.media/m1"
_M2 = f"at://{_ACQ}/pub.layers.media.media/m2"
_STREAM_UUID = "11111111-1111-1111-1111-111111111111"

_SESSION_NSID = "pub.layers.acquisition.session"
_PARTICIPANT_NSID = "pub.layers.acquisition.participant"
_MEDIA_NSID = "pub.layers.media.media"


def _consent() -> Consent:
    return Consent(identifiability="deidentified", status="obtained", scope="public")


def _session() -> Session:
    return Session(
        sessionId="ses-01",
        createdAt=_NOW,
        streams=(Stream(uuid=Uuid(value=_STREAM_UUID)),),
        participantRefs=(_P1,),
        task="acceptability-judgment",
    )


def _participant() -> Participant:
    return Participant(participantId="sub-01", createdAt=_NOW, consent=_consent())


def _media_by_session_ref() -> Media:
    return Media(
        kind="signal", createdAt=_NOW, sessionRef=_S1, externalUri="https://x/eeg.edf"
    )


def _media_by_stream() -> Media:
    return Media(
        kind="signal",
        createdAt=_NOW,
        stream=ObjectRef(recordRef=_S1, objectId=Uuid(value=_STREAM_UUID)),
        externalUri="https://x/gaze.edf",
    )


def _envelope(uri: str, model: dx.Model) -> RecordEnvelope:
    value = json.loads(model.model_dump_json())
    value["$type"] = uri.split("/")[-2]
    return RecordEnvelope(uri=uri, cid="cid", value=value)


class _FakePds:
    """A fake PDS returning canned envelopes by collection and AT-URI."""

    def __init__(
        self,
        by_collection: dict[str, list[RecordEnvelope]],
        by_uri: dict[str, RecordEnvelope] | None = None,
    ) -> None:
        self._by = by_collection
        self._by_uri = by_uri if by_uri is not None else {}
        self.fetched: list[str] = []

    def list_records(
        self,
        repo: str,
        collection: str,
        *,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Iterator[RecordEnvelope]:
        _ = (repo, limit, cursor)
        yield from self._by.get(collection, [])

    def get_record(self, repo: str, collection: str, rkey: str) -> RecordEnvelope:
        uri = f"at://{repo}/{collection}/{rkey}"
        self.fetched.append(uri)
        envelope = self._by_uri.get(uri)
        if envelope is None:
            msg = f"no record for {uri}"
            raise RecordNotFoundError(msg)
        return envelope


def _acquisition_fake() -> _FakePds:
    return _FakePds(
        by_collection={
            _SESSION_NSID: [_envelope(_S1, _session())],
            _MEDIA_NSID: [
                _envelope(_M1, _media_by_session_ref()),
                _envelope(_M2, _media_by_stream()),
            ],
        },
        by_uri={_P1: _envelope(_P1, _participant())},
    )


def test_empty_acquisition_has_no_sessions() -> None:
    assert len(Acquisition.new().sessions()) == 0


def test_load_acquisition_joins_sessions_participants_and_media() -> None:
    fake = _acquisition_fake()
    acq = load_acquisition(_S1, source="pds", pds_client=fake)  # ty: ignore[invalid-argument-type]
    assert len(acq.sessions()) == 1
    # the participant lives in a separate account, reached by following participantRefs.
    assert fake.fetched == [_P1]
    assert len(acq.participants()) == 1
    assert len(acq.media()) == 2

    with_participants = list(acq.sessions_with_participants())
    assert len(with_participants) == 1
    assert [p.participantId for p in with_participants[0].participants] == ["sub-01"]


def test_sessions_with_media_unions_session_ref_and_stream() -> None:
    fake = _acquisition_fake()
    acq = load_acquisition(_S1, source="pds", pds_client=fake)  # ty: ignore[invalid-argument-type]
    rows = list(acq.sessions_with_media())
    assert len(rows) == 1
    # both the sessionRef-linked and the stream-linked media attach to the session.
    assert {m.externalUri for m in rows[0].media} == {
        "https://x/eeg.edf",
        "https://x/gaze.edf",
    }


def test_load_acquisition_never_fetches_blob_bytes() -> None:
    # the media travel by externalUri with no inline blob; the loader reads records
    # by AT-URI only and never touches a blob endpoint (the fake has none).
    fake = _acquisition_fake()
    acq = load_acquisition(_S1, source="pds", pds_client=fake)  # ty: ignore[invalid-argument-type]
    assert all(m.blob is None for m in acq.media())
    # only the cross-account participant record was fetched by URI; nothing else.
    assert fake.fetched == [_P1]


def test_participant_consent_state_is_exposed() -> None:
    # a withdrawal is expressed by deleting the record upstream; whatever consent
    # state is present, the loader surfaces it without re-identifying anything.
    fake = _acquisition_fake()
    acq = load_acquisition(_S1, source="pds", pds_client=fake)  # ty: ignore[invalid-argument-type]
    participant = next(iter(acq.participants()))
    assert participant.consent.status == "obtained"
    assert participant.consent.identifiability == "deidentified"


def test_load_acquisition_rejects_unknown_source() -> None:
    with pytest.raises(ValueError, match="unknown acquisition source"):
        load_acquisition(_S1, source="bogus")


def test_load_acquisition_appview_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        load_acquisition(_S1, source="appview")


def test_load_acquisition_without_client_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        load_acquisition(_S1, source="auto")


def test_exports() -> None:
    assert set(acquisition_mod.__all__) == {
        "Acquisition",
        "SessionWithMedia",
        "SessionWithParticipants",
        "load_acquisition",
    }
