"""CoNLL-U format codec.

Converts between CoNLL-U (Universal Dependencies) and lairs records, binding
to the :class:`~lairs.integrations.ports.Codec` port. Requires the
``lairs[conllu]`` extra at runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from lairs.integrations.codecs import CorpusFragment, FragmentRecord

__all__ = ["ConlluCodec"]


class ConlluCodec:
    """A bidirectional CoNLL-U codec."""

    name = "conllu"

    def decode(
        self,
        src: str | bytes,
        *,
        into: CorpusFragment | None = None,
    ) -> CorpusFragment:
        """Decode CoNLL-U text into a corpus fragment.

        Parameters
        ----------
        src : str or bytes
            The CoNLL-U source.
        into : lairs.integrations.codecs.CorpusFragment or None, optional
            An existing fragment to extend.

        Returns
        -------
        lairs.integrations.codecs.CorpusFragment
            The decoded fragment.

        Raises
        ------
        NotImplementedError
            Always, until the CoNLL-U codec lands.
        """
        raise NotImplementedError

    def encode(self, records: Iterable[FragmentRecord]) -> str:
        """Encode records into CoNLL-U text.

        Parameters
        ----------
        records : collections.abc.Iterable of FragmentRecord
            The records to encode.

        Returns
        -------
        str
            The CoNLL-U representation.

        Raises
        ------
        NotImplementedError
            Always, until the CoNLL-U codec lands.
        """
        raise NotImplementedError
