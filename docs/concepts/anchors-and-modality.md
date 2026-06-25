# Anchors and modality

An annotation is meaningless without knowing what it points at. In
Layers, the pointer is an *anchor*, and a single anchor model spans every
modality the format carries: text, tokens, audio, video, and
time-series signals. This page explains how the lexicons represent the
anchor, why that representation is an object with optional fields rather
than a tagged union, and how one resolver unifies slicing across all the
targets an anchor can select.

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

This is a deliberate representational choice in the lexicons, and lairs
mirrors it. The Layers format contains exactly one formal `union` (the
`selector` of `externalTarget`, which does generate a `dx.TaggedUnion`).
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

That structural dispatch shows up in two helpers. `anchor_kind` returns
the name of the set anchor field, checking the variant fields in lexicon
priority order. `flatten_anchor` projects whichever variant is set into a
fixed set of typed Arrow columns (`byte_start`, `token_index`,
`t_start_ms`, `bbox_x`, and so on). Both work by looking at which fields
are populated, because the anchor is an object, not a tag.

## One resolver, many targets

The point of a unified anchor model is a unified resolver.
`resolve_anchor(anchor, target)` is the single API the dataset layer
calls for "give me the data this annotation points at." It dispatches
over the anchor kind and returns the corresponding slice or view of
whatever target it is given:

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

The dispatch is structural, like the helpers above. The resolver unwraps
the anchor object to find its single set variant, and if it is handed a
bare variant model instead of the wrapper it infers the kind from the
fields the model carries (a `byte_start` means a text span, a
`token_index` means a token reference, keyframes mean a spatio-temporal
anchor, and so on). It also tolerates both the camelCase lexicon names
and the snake_case generated names, so it works whether it is given a raw
decoded value or a generated model instance.

The type signature reflects the breadth of targets. An anchor target is a
string (text), a tuple of strings (tokens), an audio buffer, a signal
buffer, a video frame, or a bounding box, and the resolver returns one of
the same. A mismatch between the anchor kind and the target type raises
rather than guessing, and an undeterminable anchor kind raises too. The
modality decoders themselves (audio, video, neural) live behind optional
extras and supply the buffer types and the slicing math. The resolver is
the layer that turns an anchor into the right call.

The targets the resolver slices come from `resolve_media`, the public
entry point that turns a media record (a `blob` or an `externalUri`) into
a `MediaHandle` holding the raw bytes plus typed metadata. Both are
exported from `lairs.media` alongside `resolve_anchor`. A handle's decoded
bytes feed the modality decoders that produce the audio buffer, signal
buffer, or video frame an anchor then resolves against.

## Why this is the unifying idea

Layers carries heavy, heterogeneous modalities, and a generic tabular
dataset library cannot express the relationship between an annotation and
the audio sample window or video frame crop it refers to. The anchor is
what makes that relationship uniform: every annotation, regardless of
modality, attaches through the same object, and one resolver turns it
into the concrete slice. Because every modality reduces to (target) plus
(anchor), the per-modality code stays small and the rest of the system
(the dataset API, the Arrow flattening, and the integration adapters)
binds to the single resolver rather than to five modality-specific paths.

For the mechanics of decoding and slicing each modality, see the
[media guide](../guide/media.md). For how the resolver fits the
integration ports, see [integrations](integrations.md).
