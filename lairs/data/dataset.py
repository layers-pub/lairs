"""HuggingFace-like dataset over generated record models.

A ``Dataset`` is a lazy, optionally streaming sequence of generated model
instances, with map and materialization helpers. It is generic over the model
type it yields so indexing and iteration are precisely typed.

The dataset is lazy by default: it holds a *source* that produces model
instances on demand, plus an optional chain of per-record transforms applied as
records flow through. Two source shapes are supported. An in-memory source wraps
a concrete tuple of models and supports random access and ``len``. A streaming
source wraps a zero-argument factory that returns a fresh iterator of models
(for example a PDS cursor or a repository scan); it has no length and no random
access until it is drained.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lairs.data.features import Features, features_of
from lairs.store.arrow import records_to_table

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Sequence

    import didactic.api as dx
    import pandas as pd
    import pyarrow as pa

__all__ = ["Dataset"]


class Dataset[ModelT: "dx.Model"]:
    """A lazy dataset of generated record models of one type.

    The dataset is generic over ``ModelT``, the model type it yields, so
    indexing and iteration are precisely typed rather than widened. A dataset is
    constructed from an in-memory tuple of records (the default and the form
    random access and ``len`` require) or from a streaming factory.

    Parameters
    ----------
    records : collections.abc.Sequence of ModelT or None, optional
        The in-memory records the dataset yields. Mutually exclusive with
        ``source``; when both are omitted the dataset is empty.
    model : type of ModelT or None, optional
        The model type the dataset yields. Required for an empty or streaming
        dataset so that :attr:`features` can be derived; inferred from the first
        record otherwise.
    source : collections.abc.Callable or None, optional
        A zero-argument factory returning a fresh iterator of records for a
        streaming dataset. Mutually exclusive with ``records``.
    """

    def __init__(
        self,
        records: Sequence[ModelT] | None = None,
        *,
        model: type[ModelT] | None = None,
        source: Callable[[], Iterator[ModelT]] | None = None,
    ) -> None:
        if records is not None and source is not None:
            msg = "pass either records or source, not both"
            raise ValueError(msg)
        self._records: tuple[ModelT, ...] | None = (
            tuple(records) if records is not None else None
        )
        self._source = source
        self._model = model

    @classmethod
    def streaming(
        cls,
        source: Callable[[], Iterator[ModelT]],
        *,
        model: type[ModelT],
    ) -> Dataset[ModelT]:
        """Build a streaming dataset from an iterator factory.

        A streaming dataset pulls records lazily from ``source`` and never
        materializes the whole collection in memory until a materializing call
        (for example :meth:`to_arrow`) drains it.

        Parameters
        ----------
        source : collections.abc.Callable
            A zero-argument factory returning a fresh iterator of records.
        model : type of ModelT
            The model type the stream yields, used to derive features.

        Returns
        -------
        Dataset
            A streaming dataset over the source.
        """
        return cls(source=source, model=model)

    @property
    def is_streaming(self) -> bool:
        """Return whether the dataset is backed by a streaming source.

        Returns
        -------
        bool
            ``True`` when the dataset pulls lazily and has no random access.
        """
        return self._source is not None

    def _resolved_model(self) -> type[ModelT]:
        """Return the model type, inferring it from records when needed.

        Returns
        -------
        type of ModelT
            The dataset's model type.

        Raises
        ------
        ValueError
            When the model type is neither supplied nor inferable.
        """
        if self._model is not None:
            return self._model
        if self._records:
            model = type(self._records[0])
            self._model = model
            return model
        msg = "cannot derive features for an empty dataset without a model type"
        raise ValueError(msg)

    def _iter_records(self) -> Iterator[ModelT]:
        """Yield every record from the backing source.

        Returns
        -------
        collections.abc.Iterator of ModelT
            The records, pulled lazily for a streaming source.
        """
        if self._source is not None:
            yield from self._source()
        elif self._records is not None:
            yield from self._records

    def __len__(self) -> int:
        """Return the number of records.

        Returns
        -------
        int
            The record count.

        Raises
        ------
        TypeError
            When the dataset is streaming and has no known length.
        """
        if self._records is None:
            msg = "a streaming dataset has no length; materialize it first"
            raise TypeError(msg)
        return len(self._records)

    def __getitem__(self, index: int) -> ModelT:
        """Return the record at an index.

        Parameters
        ----------
        index : int
            The zero-based record index.

        Returns
        -------
        ModelT
            The model instance at the index.

        Raises
        ------
        TypeError
            When the dataset is streaming and has no random access.
        IndexError
            When the index is out of range.
        """
        if self._records is None:
            msg = "a streaming dataset has no random access; materialize it first"
            raise TypeError(msg)
        return self._records[index]

    def __iter__(self) -> Iterator[ModelT]:
        """Iterate over the dataset one record at a time.

        Returns
        -------
        collections.abc.Iterator of ModelT
            The records, lazily for a streaming source.
        """
        return self._iter_records()

    @property
    def features(self) -> Features:
        """Return the dataset schema derived from the model.

        Returns
        -------
        lairs.data.features.Features
            The feature description for the dataset's model type.
        """
        return features_of(self._resolved_model())

    def iter(self, batch_size: int = 1) -> Iterator[tuple[ModelT, ...]]:
        """Iterate over the dataset in batches.

        Parameters
        ----------
        batch_size : int, optional
            The number of records per batch. The final batch may be smaller.

        Yields
        ------
        tuple of ModelT
            Successive batches of records.

        Raises
        ------
        ValueError
            When ``batch_size`` is not positive.
        """
        if batch_size < 1:
            msg = "batch_size must be a positive integer"
            raise ValueError(msg)
        batch: list[ModelT] = []
        for record in self._iter_records():
            batch.append(record)
            if len(batch) == batch_size:
                yield tuple(batch)
                batch = []
        if batch:
            yield tuple(batch)

    def map(
        self,
        fn: Callable[[ModelT], ModelT],
        *,
        model: type[ModelT] | None = None,
    ) -> Dataset[ModelT]:
        """Apply a lazy per-record transform.

        The transform is not applied eagerly: it is composed onto the dataset's
        source so it runs as records flow through a later iteration or
        materialization. The result preserves the source's laziness and
        streaming behaviour.

        This is strictly per-record. There is no ``batched`` mode that hands the
        callable a batch, because the transform signature is fixed to one record
        in and one record out; group the records yourself with :meth:`iter` when
        a batch view is needed.

        Parameters
        ----------
        fn : collections.abc.Callable
            The per-record transform mapping a model to a model.
        model : type of ModelT or None, optional
            The model type the transformed dataset yields. Defaults to this
            dataset's model type; supply it when the transform changes the
            feature shape and the new shape must be derivable.

        Returns
        -------
        Dataset
            A new lazy dataset with the transform applied.
        """
        result_model = model if model is not None else self._model

        def transformed() -> Iterator[ModelT]:
            for record in self._iter_records():
                yield fn(record)

        return Dataset(source=transformed, model=result_model)

    def map_batched(
        self,
        fn: Callable[[Sequence[ModelT]], Iterable[ModelT]],
        *,
        batch_size: int = 1000,
        model: type[ModelT] | None = None,
    ) -> Dataset[ModelT]:
        """Apply a lazy transform over batches of records.

        Unlike :meth:`map`, the callable receives a batch (a sequence of
        records) and returns an iterable of records, so a transform can add,
        drop, or reshape records across a batch (the HuggingFace
        ``map(batched=True)`` affordance). The transform is composed lazily onto
        the source and preserves streaming behaviour; the output record count
        need not match the input count.

        Parameters
        ----------
        fn : collections.abc.Callable
            The batch transform mapping a sequence of records to an iterable of
            records.
        batch_size : int, optional
            The number of records handed to ``fn`` per call. The final batch may
            be smaller.
        model : type of ModelT or None, optional
            The model type the transformed dataset yields. Defaults to this
            dataset's model type.

        Returns
        -------
        Dataset
            A new lazy dataset with the batch transform applied.

        Raises
        ------
        ValueError
            When ``batch_size`` is not positive.
        """
        if batch_size < 1:
            msg = "batch_size must be a positive integer"
            raise ValueError(msg)
        result_model = model if model is not None else self._model

        def transformed() -> Iterator[ModelT]:
            for batch in self.iter(batch_size=batch_size):
                yield from fn(batch)

        return Dataset(source=transformed, model=result_model)

    def filter(self, predicate: Callable[[ModelT], bool]) -> Dataset[ModelT]:
        """Filter the dataset by a per-record predicate, lazily.

        Parameters
        ----------
        predicate : collections.abc.Callable
            A predicate selecting which records to keep.

        Returns
        -------
        Dataset
            A new lazy dataset of the records for which ``predicate`` is true.
        """
        model = self._model

        def filtered() -> Iterator[ModelT]:
            for record in self._iter_records():
                if predicate(record):
                    yield record

        return Dataset(source=filtered, model=model)

    def take(self, count: int) -> Dataset[ModelT]:
        """Materialize the first ``count`` records into a new in-memory dataset.

        Parameters
        ----------
        count : int
            The number of records to take from the front.

        Returns
        -------
        Dataset
            An in-memory dataset of at most ``count`` records.
        """
        taken: list[ModelT] = []
        for record in self._iter_records():
            if len(taken) >= count:
                break
            taken.append(record)
        return Dataset(taken, model=self._model)

    def materialize(self) -> Dataset[ModelT]:
        """Drain the dataset into an in-memory dataset with random access.

        Returns
        -------
        Dataset
            An in-memory copy supporting ``len`` and indexing.
        """
        return Dataset(tuple(self._iter_records()), model=self._model)

    def to_arrow(self) -> pa.Table:
        """Materialize the dataset to an Arrow table.

        The table is the flattened columnar view produced by the store's Arrow
        machinery: scalar fields become columns and any ``anchor`` field is
        expanded into the typed anchor columns.

        This is a full materialization: a streaming dataset is drained and every
        row is buffered in memory while the table is built, so this should not be
        called on an unbounded stream without a bounding :meth:`take` first.

        Returns
        -------
        pyarrow.Table
            The materialized columnar view.
        """
        return records_to_table(self._iter_records())

    def to_pandas(self) -> pd.DataFrame:
        """Materialize the dataset to a pandas DataFrame.

        pandas is an optional dependency, resolved through pyarrow's
        :meth:`pyarrow.Table.to_pandas`, which raises a clear ``ImportError``
        when pandas is not installed. Like :meth:`to_arrow`, this is a full
        materialization that drains and buffers a streaming dataset.

        Returns
        -------
        pandas.DataFrame
            The materialized table as a DataFrame.

        Raises
        ------
        ImportError
            When pandas is not installed.
        """
        return self.to_arrow().to_pandas()

    @classmethod
    def from_iterable(
        cls,
        records: Iterable[ModelT],
        *,
        model: type[ModelT] | None = None,
    ) -> Dataset[ModelT]:
        """Build an in-memory dataset by draining an iterable of records.

        Parameters
        ----------
        records : collections.abc.Iterable of ModelT
            The records to collect.
        model : type of ModelT or None, optional
            The model type the dataset yields.

        Returns
        -------
        Dataset
            An in-memory dataset over the drained records.
        """
        return cls(tuple(records), model=model)
