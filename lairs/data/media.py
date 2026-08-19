"""Signal-media access over loaded ``pub.layers.media.media`` records.

Filters and joins over media records that carry sampled time series (EEG, MEG,
iEEG, fNIRS, EMG, eye-tracking, motion capture, articulography) rather than audio,
video, images, or documents. A signal-bearing medium is one whose ``kind`` names
a carrier that holds a sampled stream (``signal``, ``motion``, or ``volume``); its
per-channel and per-sensor tables live in the composable ``signal`` info block.

This module reads records the loaders already pulled into a pool; it never fetches
blob bytes. Signal containers (EDF, BDF, FIF, EEGLAB SET, BrainVision, SNIRF, NWB,
NIfTI, C3D) are large and frequently participant-identifiable, so they travel by
``externalUri`` with a ``contentDigest`` for integrity rather than as an inline
blob. The carriage helpers honour ``Media.blob is None`` and surface the external
carriage, so a consumer decides access without any byte fetch happening here.

The ``signal_channels_table`` and ``signal_sensors_table`` Arrow builders are
re-exported from :mod:`lairs.store.arrow`, where the flatten-to-typed-columns
boundary lives, so the channel and sensor montages materialize the same way the
expressions and annotations views do.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lairs.records._generated import annotation as annotation_records
from lairs.store.arrow import signal_channels_table, signal_sensors_table

if TYPE_CHECKING:
    from collections.abc import Iterable

    from lairs.records._generated import media as media_records
    from lairs.store.pool import ModelPool

__all__ = [
    "SIGNAL_KINDS",
    "event_channel_ref",
    "event_layer_uri",
    "is_externally_carried",
    "media_by_kind",
    "resolve_event_layer",
    "signal_channels_table",
    "signal_media",
    "signal_sensors_table",
]

SIGNAL_KINDS = frozenset({"signal", "motion", "volume"})
"""The media-kind slugs whose carrier holds a sampled time series.

``signal`` (EEG/MEG/iEEG/fNIRS/EMG/gaze), ``motion`` (motion capture and
articulography, which also carries a ``signal`` block), and ``volume``
(volumetric imaging). Audio, video, image, and document carry other modalities.
"""


def signal_media(
    media: Iterable[media_records.Media],
) -> tuple[media_records.Media, ...]:
    """Return the media whose carrier holds a sampled time series.

    A signal-bearing medium is one whose ``kind`` is in :data:`SIGNAL_KINDS`.
    ``kind`` names the carrier only; the instrument-level modality is named by
    ``signal.modality`` on the medium's signal info block.

    Parameters
    ----------
    media : collections.abc.Iterable of pub.layers.media.Media
        The media records to filter.

    Returns
    -------
    tuple of pub.layers.media.Media
        The signal-bearing media, in input order.
    """
    return tuple(item for item in media if item.kind in SIGNAL_KINDS)


def media_by_kind(
    media: Iterable[media_records.Media],
    kind: str,
) -> tuple[media_records.Media, ...]:
    """Return the media of one carrier kind.

    Parameters
    ----------
    media : collections.abc.Iterable of pub.layers.media.Media
        The media records to filter.
    kind : str
        The media-kind slug to keep (``signal``, ``motion``, ``volume``,
        ``audio``, ``video``, ``image``, ``document``, ...).

    Returns
    -------
    tuple of pub.layers.media.Media
        The media of that kind, in input order.
    """
    return tuple(item for item in media if item.kind == kind)


def is_externally_carried(media: media_records.Media) -> bool:
    """Return whether a medium's bytes travel by external URI rather than a blob.

    A signal container above the record size limit, or one that is
    participant-identifiable and access-gated, carries no inline ``blob`` and
    instead names its bytes through ``externalUri`` with a ``contentDigest`` for
    integrity. This helper answers "are the bytes external" without fetching them:
    it is true when the medium has no blob and does name an external URI.

    Parameters
    ----------
    media : pub.layers.media.Media
        The media record.

    Returns
    -------
    bool
        ``True`` when the medium has no inline blob and names an external URI.
    """
    return media.blob is None and media.externalUri is not None


def event_layer_uri(media: media_records.Media) -> str | None:
    """Return the AT-URI of a signal medium's decoded event layer, if any.

    A signal recording's trigger and stimulus-code stream is decoded into a
    ``pub.layers.annotation.annotationLayer`` of kind ``tier``, named by
    ``signal.eventLayerRef``. This is where BIDS ``events.tsv`` lands.

    Parameters
    ----------
    media : pub.layers.media.Media
        The media record.

    Returns
    -------
    str or None
        The event-layer AT-URI, or ``None`` when the medium carries no signal
        block or declares no event layer.
    """
    signal = media.signal
    if signal is None:
        return None
    return signal.eventLayerRef


def event_channel_ref(media: media_records.Media) -> str | None:
    """Return the AT-URI a signal medium's ``eventChannel`` objectRef names, if any.

    ``signal.eventChannel`` is an objectRef into this record's own ``channels``
    identifying the trigger or stimulus-code channel; its ``recordRef`` (when set)
    names the record the channel lives in.

    Parameters
    ----------
    media : pub.layers.media.Media
        The media record.

    Returns
    -------
    str or None
        The event-channel record AT-URI, or ``None`` when absent.
    """
    signal = media.signal
    if signal is None or signal.eventChannel is None:
        return None
    return signal.eventChannel.recordRef


def resolve_event_layer(
    media: media_records.Media,
    pool: ModelPool,
) -> annotation_records.AnnotationLayer | None:
    """Resolve a signal medium's event layer to its annotation-layer record.

    The medium's ``signal.eventLayerRef`` AT-URI is resolved through the pool; the
    result is the decoded ``pub.layers.annotation.annotationLayer`` when it is
    loaded, otherwise ``None``. No bytes are fetched.

    Parameters
    ----------
    media : pub.layers.media.Media
        The media record whose event layer to resolve.
    pool : lairs.store.pool.ModelPool
        The AT-URI-keyed record graph to resolve through.

    Returns
    -------
    pub.layers.annotation.AnnotationLayer or None
        The resolved event layer, or ``None`` when it is not loaded.
    """
    uri = event_layer_uri(media)
    if uri is None:
        return None
    target = pool.resolve(uri)
    if isinstance(target, annotation_records.AnnotationLayer):
        return target
    return None
