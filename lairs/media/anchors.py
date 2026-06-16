"""Unified anchor resolution over all anchor kinds.

``resolve_anchor`` dispatches over byte spans, token refs, temporal spans,
bounding boxes, and spatio-temporal anchors, returning the corresponding slice
or view of the right target (text, tokens, audio, video frame, or signal). It
is the single API the dataset layer calls for the data an annotation points
at.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import didactic.api as dx

    from lairs.media.audio import AudioBuffer
    from lairs.media.neural import SignalBuffer
    from lairs.media.video import VideoFrame

__all__ = ["AnchorTarget", "resolve_anchor"]

type AnchorTarget = "str | tuple[str, ...] | AudioBuffer | VideoFrame | SignalBuffer"
"""The kinds of slice an anchor can resolve to across the supported targets."""


def resolve_anchor(anchor: dx.Model, target: dx.Model) -> AnchorTarget:
    """Resolve an anchor to the slice of the target it points at.

    Parameters
    ----------
    anchor : didactic.Model
        An ``anchor`` union instance.
    target : didactic.Model
        The record whose data the anchor selects into (expression, media).

    Returns
    -------
    AnchorTarget
        The resolved slice or view, dispatched on the anchor kind.

    Raises
    ------
    NotImplementedError
        Always, until the media layer lands.
    """
    raise NotImplementedError
