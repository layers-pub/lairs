# Resolving and slicing media

Layers annotations anchor into text, tokens, audio, video, and
time-series signals. The media layer turns a media record into a byte
handle, dispatches an annotation's anchor to the slice it points at, and
decodes and slices each modality. The byte-arithmetic and interpolation
paths are pure Python. The audio, video, and neural *decoders* are
optional extras, imported lazily, so importing the media modules never
pulls in a heavy dependency.

For full signatures see the [media reference](../reference/media.md). For
how anchors unify the modalities, see [Anchors](../concepts/anchors-and-modality.md).

## Resolve a media record to bytes

`resolve_media` turns a `media.media` record into a `MediaHandle`,
dispatching on whether the record carries a `blob` or an `externalUri`.
The handle is a model holding typed metadata (`cid`, `mime_type`,
`modality`, optional `duration_ms`, optional `external_uri`) with the
raw bytes in an opaque `data` field.

Transport and cache are not implemented here: they are injected through
the `BlobFetcher`, `UriFetcher`, and `BlobCache` ports. The
[ATProto blob client](reading-pds.md) satisfies the fetcher shape and the
[store's blob cache](store.md) satisfies the cache shape:

```python
from lairs.atproto.blobs import BlobClient
from lairs.store.blobcache import BlobCache
from lairs.media.resolve import resolve_media

with BlobClient(pds_endpoint) as fetcher:
    handle = resolve_media(
        media_record,
        did=repo_did,
        blob_fetcher=fetcher,
        cache=BlobCache(cache_root),
    )
print(handle.modality, handle.mime_type, len(handle.data))
```

Resolution is lazy and cache-first: a cached payload is returned
directly. Otherwise, when a matching fetcher is supplied, the bytes are
fetched and cached. With no fetcher the handle is metadata-only (`data`
is empty), so a caller can decide when to fetch. A record carrying
neither a blob nor an external URI raises `ValueError`. The dispatch
reads both camelCase lexicon names and snake_case generated names, so it
works against the generated record models without depending on a
concrete type.

## Resolve an anchor to a slice

`resolve_anchor` is the single entry point the dataset layer calls for
the data an annotation points at. It accepts the `anchor` wrapper (or a
variant model directly) and the target the anchor selects into, and
dispatches on the anchor kind:

```python
from lairs.media.anchors import resolve_anchor

snippet = resolve_anchor(anchor, expression.text)   # text span -> str
```

The target type determines what comes back, and a mismatch raises
`TypeError`:

- a byte-span anchor over a `str` target returns the UTF-8 text slice.
- a token-ref (or token-ref-sequence) anchor over a `tuple[str, ...]`
  target returns the referenced tokens.
- a temporal-span anchor over an `AudioBuffer` or `SignalBuffer` returns
  the corresponding window.
- a bounding-box anchor over a `VideoFrame` returns the cropped frame.
- a spatio-temporal anchor over a `VideoFrame` interpolates its keyframes
  to the frame and returns the cropped frame.

The set variant on the wrapper is found by probing its fields. When an
anchor is passed as a bare variant model, its kind is inferred from the
fields it carries, and an undeterminable kind raises `ValueError`.

## Decode and slice audio

`decode_audio` decodes a resolved `MediaHandle` into an `AudioBuffer`
whose interleaved samples live in an opaque field. Decoding uses
`soundfile`, the `lairs[audio]` extra, imported lazily. A missing extra
raises `ModuleNotFoundError`, and an empty handle raises `ValueError`:

```python
from lairs.media.audio import decode_audio, slice_by_temporal

buffer = decode_audio(handle)              # requires lairs[audio]
window = slice_by_temporal(buffer, 1000, 2500)
```

The slicing is rate-aware and pure Python, with no extra needed.
`ms_to_sample` and `sample_to_ms` convert between millisecond offsets and
per-channel sample indices (negative offsets or a non-positive sample
rate raise `ValueError`). `slice_by_temporal` uses them to cut the
interleaved payload, and a reversed span raises `ValueError`.
`forced_alignment_segments` lazily yields `(label, AudioBuffer)` pairs
for a sequence of `(start_ms, end_ms, label)` triples from an aligned
layer.

## Decode and slice video

`frame_at_ms` decodes the frame nearest a time into a `VideoFrame` whose
pixels live in an opaque field. Decoding uses `av`, the `lairs[video]`
extra, imported lazily. A missing extra raises `ModuleNotFoundError`, and
an empty handle or negative time raises `ValueError`:

```python
from lairs.media.video import crop_to_bbox, frame_at_ms, interpolate_box

frame = frame_at_ms(handle, 4000)          # requires lairs[video]
```

The box math is pure Python. `crop_to_bbox` crops a frame to a
`BoundingBox` by slicing the row-major RGB payload, and a box outside the
frame bounds raises `ValueError`. `interpolate_box` resolves the box at a
time by interpolating an ordered sequence of `Keyframe`s, with `linear`,
`step`, or `cubic` modes. Times before the first or after the last
keyframe clamp to the nearest box, and an empty keyframe sequence raises
`ValueError`. Spatio-temporal anchor resolution chains these: it
interpolates the keyframes to the target frame, then crops.

## Decode and slice neural signals

`decode_signal` decodes a resolved handle into a `SignalBuffer` carrying
per-channel samples in an opaque field, aligned with ordered channel
labels. Decoding uses `mne`, the `lairs[neural]` extra, imported lazily
(the bytes are written to a temporary file because `mne` readers operate
on paths). A missing extra raises `ModuleNotFoundError`, and an empty
handle raises `ValueError`:

```python
from lairs.media.neural import decode_signal, select_channels, window_by_temporal

signal = decode_signal(handle)             # requires lairs[neural]
window = window_by_temporal(signal, 200, 800)
subset = select_channels(window, ["Cz", "Pz"])
```

The windowing is rate-aware and pure Python. `ms_to_sample` converts a
millisecond offset to a sample index for a float sample rate.
`window_by_temporal` slices every channel to the same window (a reversed
span raises `ValueError`). `select_channels` keeps a subset of channels
in the requested order (an unknown label raises `KeyError`). And
`align_events_to_windows` lazily yields `(label, SignalBuffer)` pairs for
a sequence of `(start_ms, end_ms, label)` event triples.

## See also

- [Media reference](../reference/media.md) for full handle, buffer, and
  slicing signatures.
- [Anchors](../concepts/anchors-and-modality.md) for the anchor model that unifies the
  modalities.
- [Working with the store](store.md) for the blob cache the media layer
  resolves through.
