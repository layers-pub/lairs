"""Unit tests for lairs.data.media."""

from __future__ import annotations

from datetime import UTC, datetime

from lairs.data import media as media_mod
from lairs.data.media import (
    SIGNAL_KINDS,
    event_channel_ref,
    event_layer_uri,
    is_externally_carried,
    media_by_kind,
    resolve_event_layer,
    signal_channels_table,
    signal_media,
    signal_sensors_table,
)
from lairs.records._generated.annotation import AnnotationLayer
from lairs.records._generated.defs import ObjectRef, Uuid
from lairs.records._generated.media import (
    Media,
    SensorSpec,
    SignalChannel,
    SignalInfo,
)
from lairs.store.pool import ModelPool

_NOW = datetime(2024, 1, 1, tzinfo=UTC)
_LAYER_URI = "at://did:plc:x/pub.layers.annotation.annotationLayer/e"
_MEDIA_URI = "at://did:plc:x/pub.layers.media.media/m"


def _signal_info() -> SignalInfo:
    return SignalInfo(
        modality="eeg",
        samplingFrequencyMilliHz=256000,
        channels=(
            SignalChannel(
                name="Cz", type="EEG", uuid=Uuid(value="c1"), unit="microvolt"
            ),
            SignalChannel(
                name="Pz", type="EEG", uuid=Uuid(value="c2"), unit="microvolt"
            ),
        ),
        sensors=(
            SensorSpec(
                name="Cz", type="electrode", uuid=Uuid(value="s1"), xNanometres=100
            ),
        ),
        eventLayerRef=_LAYER_URI,
        eventChannel=ObjectRef(recordRef=_MEDIA_URI, objectId=Uuid(value="c1")),
    )


def _signal_media() -> Media:
    return Media(
        kind="signal",
        createdAt=_NOW,
        signal=_signal_info(),
        externalUri="https://x/eeg.edf",
    )


def test_signal_kinds_are_carrier_slugs() -> None:
    assert frozenset({"signal", "motion", "volume"}) == SIGNAL_KINDS


def test_signal_media_filters_carrier_kinds() -> None:
    items = [
        _signal_media(),
        Media(kind="audio", createdAt=_NOW),
        Media(kind="motion", createdAt=_NOW),
        Media(kind="video", createdAt=_NOW),
    ]
    kept = signal_media(items)
    assert {m.kind for m in kept} == {"signal", "motion"}


def test_media_by_kind() -> None:
    items = [_signal_media(), Media(kind="audio", createdAt=_NOW)]
    assert len(media_by_kind(items, "audio")) == 1
    assert len(media_by_kind(items, "signal")) == 1
    assert len(media_by_kind(items, "video")) == 0


def test_is_externally_carried() -> None:
    external = _signal_media()  # blob is None, externalUri set
    assert is_externally_carried(external) is True
    # no blob and no external URI is not "externally carried".
    assert is_externally_carried(Media(kind="signal", createdAt=_NOW)) is False


def test_event_layer_and_channel_refs() -> None:
    media = _signal_media()
    assert event_layer_uri(media) == _LAYER_URI
    assert event_channel_ref(media) == _MEDIA_URI
    # a medium with no signal block has neither.
    bare = Media(kind="audio", createdAt=_NOW)
    assert event_layer_uri(bare) is None
    assert event_channel_ref(bare) is None


def test_resolve_event_layer_through_pool() -> None:
    media = _signal_media()
    layer = AnnotationLayer(
        kind="tier",
        createdAt=_NOW,
        expression="at://did:plc:x/pub.layers.expression.expression/x",
        annotations=(),
    )
    pool = ModelPool()
    pool.add(_LAYER_URI, layer)
    resolved = resolve_event_layer(media, pool)
    assert resolved is not None
    assert resolved.kind == "tier"
    # an unpopulated pool resolves to None rather than raising.
    assert resolve_event_layer(media, ModelPool()) is None


def test_signal_channels_table_explodes_channels() -> None:
    table = signal_channels_table([(_MEDIA_URI, _signal_media())])
    assert table.num_rows == 2
    columns = set(table.column_names)
    assert {"media_uri", "channel_index", "name", "type", "unit"} <= columns
    names = table.column("name").to_pylist()
    assert names == ["Cz", "Pz"]


def test_signal_sensors_table_explodes_sensors() -> None:
    table = signal_sensors_table([(_MEDIA_URI, _signal_media())])
    assert table.num_rows == 1
    columns = set(table.column_names)
    assert {"media_uri", "sensor_index", "name", "type"} <= columns
    assert table.column("name").to_pylist() == ["Cz"]


def test_signal_tables_skip_media_without_signal_block() -> None:
    table = signal_channels_table([(_MEDIA_URI, Media(kind="audio", createdAt=_NOW))])
    assert table.num_rows == 0


def test_exports() -> None:
    assert set(media_mod.__all__) == {
        "SIGNAL_KINDS",
        "event_channel_ref",
        "event_layer_uri",
        "is_externally_carried",
        "media_by_kind",
        "resolve_event_layer",
        "signal_channels_table",
        "signal_media",
        "signal_sensors_table",
    }
