# Anchors and modality

An annotation is interpretable only with respect to what it points at.
Layers represents this pointer as an *anchor*. A single anchor model
covers text, tokens, audio, video, and time-series signals. The lexicons
define that model as an object with optional fields rather than a tagged
union, and lairs resolves those fields against each kind of target.

## The polymorphic anchor

The Layers `defs#anchor` is a single object with one optional field per
anchor variant:

- `textSpan`: a contiguous span by UTF-8 byte offsets.
- `tokenRef`: a single token, by tokenization UUID and index.
- `tokenRefSequence`: a possibly non-contiguous set of token indices.
- `temporalSpan`: a start and end in milliseconds, for audio or video.
- `spatioTemporalAnchor`: a temporal span plus keyframes, for tracking
  a region across video frames, with an interpolation mode.
- `pageAnchor`: a page number and region in a paged document.
- `externalTarget`: a web resource with a W3C selector.

The lexicon describes this as a polymorphic type where "at least one
anchoring field should be present" and "consumers dispatch on which
field(s) are populated." A consumer reads the anchor by checking which
variant field is set.

## Why an object, not a tagged union

lairs preserves the representation defined by the lexicons. The Layers
format contains exactly one formal `union` (the `selector` of
`externalTarget`, which does generate a `dx.TaggedUnion`).
The anchor is *not* a union. It is an object with optional fields. The
[generated-models](generated-models.md) page covers why that distinction
survives codegen. Here the question is why the format chose it.

An object with optional fields admits combinations a closed union forbids.
An anchor can carry both a `textSpan` and a `tokenRef` for the same
annotation (the byte span and its token-aligned equivalent) so a
consumer that works in bytes and a consumer that works in tokens both
find what they need without a conversion step. A closed tagged union
would force exactly one variant and lose that redundancy. The lexicon
treats anchoring as a set of optional, co-present coordinates rather than
a discriminated choice, and the cost is that dispatch is structural
(inspect which fields are set) rather than nominal (read a tag). lairs
accepts that cost on both sides: the codegen emits a plain model, and the
runtime dispatches by probing fields.

Two helpers use this structural dispatch. `anchor_kind` returns the name
of the set anchor field, checking the variant fields in lexicon priority
order. `flatten_anchor` projects whichever variant is set into a fixed
set of typed Arrow columns (`byte_start`, `token_index`, `t_start_ms`,
`bbox_x`, and so on). Both inspect the populated fields because the
anchor is an object, not a tag.

## One resolver, many targets

The dataset layer resolves all anchor variants through
`resolve_anchor(anchor, target)`. The function dispatches on the anchor
kind and returns the corresponding slice or view of the target:

- a `textSpan` against expression text returns the UTF-8 byte slice,
  decoded back to a string.
- a `tokenRef` or `tokenRefSequence` against a token tuple returns the
  referenced tokens.
- a `temporalSpan` against an audio buffer returns a rate-aware sample
  window, and against a signal buffer returns a multi-channel window.
- a `boundingBox` against a video frame returns the cropped frame.
- a `spatioTemporalAnchor` against a video frame interpolates the
  keyframed box (linear, step, or cubic) and crops to it, so an object
  track resolves to a dense box over its span. The interpolation uses the
  frame's `index` as the time argument, which stands in for the frame's
  temporal position rather than its millisecond timestamp.

Like the helpers above, the resolver uses structural dispatch. It unwraps
the anchor object to find its single set variant. Given a bare variant
model instead of the wrapper, it infers the kind from the model's fields
(a `byte_start` means a text span, a `token_index` means a token
reference, keyframes mean a spatio-temporal anchor, and so on). It also
accepts both the camelCase lexicon names and the snake_case generated
names, so callers may pass either a raw decoded value or a generated
model instance.

An anchor target is a string (text), a tuple of strings (tokens), an
audio buffer, a signal buffer, a video frame, or a bounding box, and the
resolver returns one of the same. A mismatch between the anchor kind and
the target type raises rather than guessing, as does an undeterminable
anchor kind. The modality decoders themselves (audio, video, neural) live
behind optional
extras and supply the buffer types and the slicing math. The resolver is
the layer that turns an anchor into the right call.

`resolve_media` supplies the targets that the anchor resolver slices. It
turns a media record (a `blob` or an `externalUri`) into a `MediaHandle`
holding the raw bytes plus typed metadata. Both are exported from
`lairs.media` alongside `resolve_anchor`. A handle's decoded bytes feed
the modality decoders, which produce the audio buffer, signal buffer, or
video frame against which an anchor resolves.

## One interface across modalities

A generic tabular dataset library does not by itself encode the
relationship between an annotation and the audio sample window or video
frame crop it refers to. The anchor supplies a uniform relation: every
annotation attaches through the same object, and one resolver turns that
anchor into a concrete slice. For resolution, each modality thus reduces
to (target) plus (anchor). The dataset API, Arrow flattening, and
integration adapters can bind to this resolver instead of five
modality-specific paths.

For the mechanics of decoding and slicing each modality, see the
[media guide](../guide/media.md). For how the resolver fits the
integration ports, see [integrations](integrations.md).
