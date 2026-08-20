# Media

The media API handles resolution and anchor-aware slicing. `resolve_media`
resolves a media record to a media handle, fetching bytes lazily through
injected ports; decoding is a separate step. `resolve_anchor` dispatches an
anchor to the slice of the target it points at. The audio, video, and neural
decode paths require the matching `lairs[...]` extra at runtime, but the
millisecond-to-sample math, slicing, and box interpolation are pure Python.

## Resolution

Resolution dispatches on blob versus external URI and fetches lazily
through injected fetcher and cache ports.

::: lairs.media.resolve

## Anchors

Anchor resolution covers byte spans, token refs, temporal spans, bounding
boxes, and spatio-temporal anchors.

::: lairs.media.anchors

## Audio

Audio decoding and temporal-span slicing require the `lairs[audio]` extra
(`soundfile`).

::: lairs.media.audio

## Video

Video frame access, bounding-box cropping, and keyframe interpolation require
the `lairs[video]` extra (`av`).

::: lairs.media.video

## Neural

Multi-channel windowing for neural and sensor data requires the `lairs[neural]`
extra (`mne`).

::: lairs.media.neural
