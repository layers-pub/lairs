# Media

Media resolution and anchor-aware slicing. `resolve_media` decodes a
media record to a byte-carrying handle. `resolve_anchor` dispatches an
anchor to the slice of the target it points at. The audio, video, and
neural decode paths require the matching `lairs[...]` extra at runtime,
but the millisecond-to-sample math, slicing, and box interpolation are
pure Python.

## Resolution

Dispatches on blob versus external URI, fetching lazily through injected
fetcher and cache ports.

::: lairs.media.resolve

## Anchors

Unified anchor resolution over byte spans, token refs, temporal spans,
bounding boxes, and spatio-temporal anchors.

::: lairs.media.anchors

## Audio

Audio decoding and temporal-span slicing. The decode path requires the
`lairs[audio]` extra (`soundfile`).

::: lairs.media.audio

## Video

Video frame access, bounding-box cropping, and keyframe interpolation.
The decode path requires the `lairs[video]` extra (`av`).

::: lairs.media.video

## Neural

Multi-channel signal windowing for neural and sensor data. The decode
path requires the `lairs[neural]` extra (`mne`).

::: lairs.media.neural
