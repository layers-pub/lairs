"""Stable internal ports that integrations bind to.

Integrations are never in core. Each adapter binds to one of the small, stable
protocols defined here rather than reaching into lairs internals.

Every port is generic over its concrete payload and return types, so no method
ever returns ``Any`` or ``object``. Adapters bind a port to concrete didactic
models (records, corpus fragments, knowledge-base entities) and framework
objects (datasets, tables).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

__all__ = ["Codec", "Exporter", "KnowledgeBase", "StorageBackend"]


@runtime_checkable
class Codec[Fragment, Record](Protocol):
    """A bidirectional converter between an external format and lairs records.

    A codec translates an external annotation format's spans and labels into
    lairs anchors and one of the seven annotation kinds; lairs owns the rest.

    A codec is generic over the corpus-fragment model it produces and the
    record model it consumes, so neither method returns a widened type.
    """

    name: str

    def decode(self, src: str | bytes, *, into: Fragment | None = None) -> Fragment:
        """Decode an external source into a corpus fragment.

        Parameters
        ----------
        src : str or bytes
            The external source (path text or raw bytes) to decode.
        into : Fragment or None, optional
            An existing corpus fragment to extend, if any.

        Returns
        -------
        Fragment
            A corpus fragment of lairs records.
        """
        ...

    def encode(self, records: Iterable[Record]) -> bytes | str:
        """Encode lairs records into the external format.

        Parameters
        ----------
        records : collections.abc.Iterable
            The lairs records to encode.

        Returns
        -------
        bytes or str
            The encoded external representation.
        """
        ...


@runtime_checkable
class Exporter[View, Spec, T_co](Protocol):
    """A data-plane exporter that emits a framework-native dataset.

    An exporter consumes the flattened Arrow views plus the anchor resolver and
    produces a target-framework object (for example a ``datasets.Dataset`` or a
    ``torch.utils.data.Dataset``). It is generic over the view, the export
    specification, and the framework object it returns.
    """

    name: str

    def export(self, view: View, *, spec: Spec | None = None) -> T_co:
        """Export an Arrow view into a framework-native dataset.

        Parameters
        ----------
        view : View
            The Arrow view to export.
        spec : Spec or None, optional
            An optional export specification (task template, columns).

        Returns
        -------
        T_co
            A framework-native dataset object.
        """
        ...


@runtime_checkable
class KnowledgeBase[Entity, Candidate, Edge](Protocol):
    """A connector to an external knowledge base.

    Used to resolve, entity-link, reconcile, and enrich Layers records against
    external knowledge graphs and lexical resources. It is generic over the
    entity, candidate, and edge models it returns.
    """

    name: str

    def resolve(self, ref: str) -> Entity:
        """Resolve an identifier or URI to an entity.

        Parameters
        ----------
        ref : str
            The external identifier or URI to resolve.

        Returns
        -------
        Entity
            The resolved entity (label, aliases, types, description, sameAs).
        """
        ...

    def search(
        self,
        text: str,
        *,
        lang: str | None = None,
        types: Sequence[str] | None = None,
    ) -> list[Candidate]:
        """Search for candidate entities (entity linking / reconciliation).

        Parameters
        ----------
        text : str
            The surface text to link.
        lang : str or None, optional
            An optional language filter.
        types : collections.abc.Sequence or None, optional
            An optional set of type constraints.

        Returns
        -------
        list
            A ranked list of candidate entities.
        """
        ...

    def neighbors(self, ref: str, *, rels: Sequence[str] | None = None) -> list[Edge]:
        """Expand an entity's graph neighbourhood.

        Parameters
        ----------
        ref : str
            The external identifier or URI to expand.
        rels : collections.abc.Sequence or None, optional
            An optional set of relation filters.

        Returns
        -------
        list
            The neighbouring edges.
        """
        ...


@runtime_checkable
class StorageBackend(Protocol):
    """A pluggable storage backend for blobs and materialized views.

    Used to back the blob cache and Parquet views with local or remote storage
    (for example an fsspec filesystem over s3, gcs, or local disk).
    """

    name: str

    def read_bytes(self, key: str) -> bytes:
        """Read an object's bytes by key.

        Parameters
        ----------
        key : str
            The storage key to read.

        Returns
        -------
        bytes
            The object's bytes.
        """
        ...

    def write_bytes(self, key: str, data: bytes) -> None:
        """Write an object's bytes by key.

        Parameters
        ----------
        key : str
            The storage key to write.
        data : bytes
            The bytes to store.
        """
        ...

    def exists(self, key: str) -> bool:
        """Report whether a key exists.

        Parameters
        ----------
        key : str
            The storage key to test.

        Returns
        -------
        bool
            ``True`` if the key exists.
        """
        ...
