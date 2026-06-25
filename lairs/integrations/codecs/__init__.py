"""Format codecs: bidirectional converters between external formats and records.

This package defines the shared :class:`CorpusFragment` and
:class:`FragmentRecord` models (didactic models holding a batch of decoded
records) plus the optional codec adapters that bind to the
:class:`~lairs.integrations.ports.Codec` port.
"""

from __future__ import annotations

import didactic.api as dx

__all__ = ["CorpusFragment", "FragmentRecord"]


class FragmentRecord(dx.Model):
    """A single decoded record inside a corpus fragment.

    The record value is carried as a JSON string so a fragment is independent
    of any one generated namespace module and round-trips losslessly.

    Attributes
    ----------
    local_id : str
        The local identifier or AT-URI of the record within the fragment.
    nsid : str
        The record collection NSID (for example ``pub.layers.expression``).
    value_json : str
        The record value serialised as a JSON string.
    """

    local_id: str = dx.field(description="local identifier or AT-URI")
    nsid: str = dx.field(description="record collection NSID")
    value_json: str = dx.field(description="record value as a JSON string")


class CorpusFragment(dx.Model):
    """A batch of decoded records produced by a codec.

    A fragment is the pivot a codec decodes into and encodes from.

    Attributes
    ----------
    records : tuple of FragmentRecord, optional
        The decoded records.
    source : str or None, optional
        The originating format name, when known.
    """

    records: tuple[FragmentRecord, ...] = dx.field(
        default=(),
        description="the decoded records",
    )
    source: str | None = dx.field(
        default=None,
        description="originating format name, when known",
    )
