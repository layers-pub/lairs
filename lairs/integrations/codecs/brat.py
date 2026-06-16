"""brat standoff format codec.

Converts between brat standoff annotation files and lairs records, binding to
the :class:`~lairs.integrations.ports.Codec` port. Requires the ``lairs[brat]``
extra at runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from lairs.integrations.codecs import CorpusFragment, FragmentRecord

__all__ = ["BratCodec"]


class BratCodec:
    """A bidirectional brat standoff codec."""

    name = "brat"

    def decode(
        self,
        src: str | bytes,
        *,
        into: CorpusFragment | None = None,
    ) -> CorpusFragment:
        """Decode brat standoff into a corpus fragment.

        Parameters
        ----------
        src : str or bytes
            The brat ``.ann`` source.
        into : lairs.integrations.codecs.CorpusFragment or None, optional
            An existing fragment to extend.

        Returns
        -------
        lairs.integrations.codecs.CorpusFragment
            The decoded fragment.

        Raises
        ------
        NotImplementedError
            Always, until the brat codec lands.
        """
        raise NotImplementedError

    def encode(self, records: Iterable[FragmentRecord]) -> str:
        """Encode records into brat standoff text.

        Parameters
        ----------
        records : collections.abc.Iterable of FragmentRecord
            The records to encode.

        Returns
        -------
        str
            The brat standoff representation.

        Raises
        ------
        NotImplementedError
            Always, until the brat codec lands.
        """
        raise NotImplementedError
