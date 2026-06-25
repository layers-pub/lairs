"""TensorFlow ``tf.data`` data-plane exporter.

Emits a ``tf.data.Dataset`` from an Arrow view, binding to the
:class:`~lairs.integrations.ports.Exporter` port. Requires the ``lairs[tf]``
extra at runtime; tensorflow is imported lazily so that importing this module,
deriving a feature spec from an Arrow schema, and running the unit tests never
require tensorflow to be installed.

The Arrow-schema to feature-spec derivation is pure and tensorflow-free: each
Arrow column maps to a :class:`TfFeatureSpec` carrying a stable dtype token (and
a flag for list-valued columns). Converting those tokens to concrete
``tf.dtypes.DType`` values, and building the ``tf.data.Dataset`` itself, are the
only steps that touch tensorflow, and they do so behind a lazy import.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import didactic.api as dx
import pyarrow as pa
import pyarrow.types as pat

if TYPE_CHECKING:
    import tensorflow as tf  # ty: ignore[unresolved-import]

type _FeedScalar = str | bytes | int | float | bool | None
"""A scalar Arrow value on its way into a tensorflow tensor.

``to_pylist`` yields ``str`` for string columns; the string path encodes each to
``bytes`` (tensorflow string tensors take ``bytes``) before it reaches a tensor.
"""

type _FeedValue = _FeedScalar | list[_FeedScalar]
"""A column value on its way into a tensorflow tensor.

Either a scalar or, for list-valued columns, a list of scalars.
"""

__all__ = [
    "TfDataExporter",
    "TfDataSpec",
    "TfFeatureSpec",
    "feature_specs_of",
    "token_of",
]

# arrow column tokens follow the tensorflow dtype names so the mapping to a
# concrete ``tf.dtypes.DType`` is a direct attribute lookup at runtime. the
# suppressions below are because these are dtype names, not secrets (S105).
_INT_TOKEN = "int64"  # noqa: S105
_FLOAT_TOKEN = "float32"  # noqa: S105
_DOUBLE_TOKEN = "float64"  # noqa: S105
_BOOL_TOKEN = "bool"  # noqa: S105
_STRING_TOKEN = "string"  # noqa: S105
# binary keeps its own token so binary bytes feed a tensorflow string tensor
# directly instead of being silently flattened to empty bytes like a non-string.
_BINARY_TOKEN = "binary"  # noqa: S105
_FALLBACK_TOKEN = "string"  # noqa: S105

# tokens whose values feed a tensorflow string tensor as ``bytes``: strings are
# utf-8 encoded and binary payloads pass through unchanged.
_BYTE_FEED_TOKENS: frozenset[str] = frozenset({_STRING_TOKEN, _BINARY_TOKEN})

# tokens that the lazy tensorflow bridge resolves to a dtype by attribute lookup
# (``getattr(tf, token)``). binary and any unknown token fall back to
# ``tf.string`` instead. kept as a frozenset so the pure derivation can be
# validated without tensorflow.
_KNOWN_TOKENS: frozenset[str] = frozenset(
    {_INT_TOKEN, _FLOAT_TOKEN, _DOUBLE_TOKEN, _BOOL_TOKEN, _STRING_TOKEN},
)


class TfFeatureSpec(dx.Model):
    """A single Arrow column described as a tensorflow feature.

    Attributes
    ----------
    name : str
        The column name.
    dtype : str
        The tensorflow dtype token (for example ``"int64"`` or ``"string"``).
    is_sequence : bool, optional
        Whether the column is list-valued (a ragged or variable-length feature),
        in which case ``dtype`` describes the list's element type.
    """

    name: str = dx.field(description="arrow column name")
    dtype: str = dx.field(description="tensorflow dtype token")
    is_sequence: bool = dx.field(
        default=False,
        description="whether the column is list-valued",
    )


class TfDataSpec(dx.Model):
    """Options that shape the emitted ``tf.data.Dataset``.

    Attributes
    ----------
    columns : tuple of str, optional
        The columns to keep, in order. An empty tuple keeps every column.
    batch_size : int or None, optional
        The batch size. When ``None`` the dataset is not batched.
    shuffle_buffer : int or None, optional
        The shuffle buffer size. When ``None`` the dataset is not shuffled.
    seed : int or None, optional
        The shuffle seed, used only when ``shuffle_buffer`` is set.
    drop_remainder : bool, optional
        Whether a trailing partial batch is dropped when batching.
    """

    columns: tuple[str, ...] = dx.field(
        default=(),
        description="columns to keep, in order; empty keeps all",
    )
    batch_size: int | None = dx.field(
        default=None,
        description="batch size; None leaves the dataset unbatched",
    )
    shuffle_buffer: int | None = dx.field(
        default=None,
        description="shuffle buffer size; None leaves the dataset unshuffled",
    )
    seed: int | None = dx.field(
        default=None,
        description="shuffle seed used when shuffle_buffer is set",
    )
    drop_remainder: bool = dx.field(
        default=False,
        description="whether to drop a trailing partial batch when batching",
    )


def token_of(arrow_type: pa.DataType) -> tuple[str, bool]:
    """Map an Arrow data type to a tensorflow dtype token and a sequence flag.

    The mapping is pure and tensorflow-free. List and large-list types are
    reported as sequences over their element token; every other type collapses to
    a scalar token. Unrecognised types fall back to the string token.

    Parameters
    ----------
    arrow_type : pyarrow.DataType
        The Arrow column type to map.

    Returns
    -------
    tuple of (str, bool)
        A ``(token, is_sequence)`` pair. ``token`` is a tensorflow dtype name
        and ``is_sequence`` reports whether the column is list-valued.
    """
    if pat.is_list(arrow_type) or pat.is_large_list(arrow_type):
        element_token, _ = token_of(arrow_type.value_type)
        return element_token, True
    return _scalar_token(arrow_type), False


def _scalar_token(arrow_type: pa.DataType) -> str:
    """Map a scalar Arrow data type to a tensorflow dtype token.

    Parameters
    ----------
    arrow_type : pyarrow.DataType
        The scalar Arrow type to map.

    Returns
    -------
    str
        The tensorflow dtype token, falling back to the string token.
    """
    if pat.is_boolean(arrow_type):
        return _BOOL_TOKEN
    if pat.is_integer(arrow_type):
        return _INT_TOKEN
    if pat.is_floating(arrow_type):
        # arrow float64 ("double") keeps full precision; narrower floats map to
        # the tensorflow default float token.
        return _DOUBLE_TOKEN if pat.is_float64(arrow_type) else _FLOAT_TOKEN
    if pat.is_string(arrow_type) or pat.is_large_string(arrow_type):
        return _STRING_TOKEN
    if pat.is_binary(arrow_type) or pat.is_large_binary(arrow_type):
        return _BINARY_TOKEN
    return _FALLBACK_TOKEN


def feature_specs_of(
    schema: pa.Schema,
    *,
    columns: tuple[str, ...] = (),
) -> tuple[TfFeatureSpec, ...]:
    """Derive the tensorflow feature specs for an Arrow schema.

    The derivation is pure and tensorflow-free. Each retained column becomes one
    :class:`TfFeatureSpec` carrying its dtype token and whether it is list-valued.

    Parameters
    ----------
    schema : pyarrow.Schema
        The Arrow schema to describe.
    columns : tuple of str, optional
        The columns to keep, in order. An empty tuple keeps every column in
        schema order. Names absent from the schema are skipped.

    Returns
    -------
    tuple of TfFeatureSpec
        One feature spec per retained column.
    """
    names = columns or tuple(schema.names)
    specs: list[TfFeatureSpec] = []
    for name in names:
        index = schema.get_field_index(name)
        if index < 0:
            continue
        token, is_sequence = token_of(schema.field(index).type)
        specs.append(TfFeatureSpec(name=name, dtype=token, is_sequence=is_sequence))
    return tuple(specs)


def _require_tensorflow() -> tf:
    """Import tensorflow lazily, raising a clear error when it is absent.

    Returns
    -------
    module
        The imported ``tensorflow`` module.

    Raises
    ------
    ImportError
        When tensorflow is not installed.
    """
    try:
        import tensorflow as tf  # ty: ignore[unresolved-import]  # noqa: PLC0415
    except ImportError as error:  # pragma: no cover - exercised only without tf
        message = (
            "the tfdata exporter requires tensorflow; install the optional "
            "dependency with `pip install lairs[tf]`"
        )
        raise ImportError(message) from error
    return tf


def _dtype_for(token: str, tf: tf) -> tf.dtypes.DType:
    """Resolve a dtype token to a concrete ``tf.dtypes.DType``.

    Parameters
    ----------
    token : str
        A tensorflow dtype token (for example ``"int64"``).
    tf : module
        The imported tensorflow module.

    Returns
    -------
    tf.dtypes.DType
        The resolved tensorflow dtype, defaulting to ``tf.string`` for unknown
        tokens.
    """
    if token not in _KNOWN_TOKENS:
        return tf.string
    return getattr(tf, token)


def _column_values(view: pa.Table, spec: TfFeatureSpec) -> list[_FeedValue]:
    """Return a column's python values, encoding strings as bytes for tensorflow.

    String and binary columns feed a tensorflow string tensor, so their values
    are returned as ``bytes`` (strings utf-8 encoded, binary passed through).
    Numeric columns are returned unchanged, but a numeric column carrying a null
    is rejected: ``tf.ragged.constant`` cannot convert a ``None`` to a numeric
    dtype and would otherwise raise an opaque framework error.

    Parameters
    ----------
    view : pyarrow.Table
        The Arrow view to read from.
    spec : TfFeatureSpec
        The feature spec for the column to read.

    Returns
    -------
    list
        The column's values as python objects suitable for a tensor.

    Raises
    ------
    ValueError
        When a numeric column carries a null value, which cannot be converted to
        the column's tensorflow dtype.
    """
    values: list[_FeedValue] = view.column(spec.name).to_pylist()
    if spec.dtype not in _BYTE_FEED_TOKENS:
        if any(value is None for value in values):
            msg = (
                f"numeric column {spec.name!r} carries a null value and cannot "
                f"be converted to a {spec.dtype} tensor; drop the column or fill "
                f"its nulls before exporting"
            )
            raise ValueError(msg)
        return values
    return [_as_bytes(value, is_sequence=spec.is_sequence) for value in values]


def _as_bytes(value: _FeedValue, *, is_sequence: bool) -> _FeedValue:
    """Encode a string or binary value (or list thereof) as tensorflow bytes.

    Strings arrive from ``to_pylist`` as ``str`` and binary as ``bytes``;
    tensorflow string tensors take ``bytes``, so each ``str`` is utf-8 encoded,
    each ``bytes`` value is kept, and absent values become ``b""``.

    Parameters
    ----------
    value : _FeedValue
        The value to encode.
    is_sequence : bool
        Whether the value is a list of scalars rather than a scalar.

    Returns
    -------
    _FeedValue
        The encoded value: bytes for a scalar, a list of bytes for a sequence.
    """
    if is_sequence and isinstance(value, list):
        return [_scalar_bytes(item) for item in value]
    return _scalar_bytes(value)


def _scalar_bytes(value: _FeedValue) -> bytes:
    """Encode one scalar string or binary value as tensorflow-ready bytes.

    Parameters
    ----------
    value : _FeedValue
        The scalar value to encode; a ``str`` is utf-8 encoded, a ``bytes`` (or
        ``bytearray``) value is kept, and anything else yields ``b""``.

    Returns
    -------
    bytes
        The encoded string or binary payload, or ``b""`` for an absent value.
    """
    if isinstance(value, str):
        return value.encode()
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    return b""


class TfDataExporter:
    """An exporter that emits a ``tf.data.Dataset`` from an Arrow view.

    The exporter binds to the generic
    :class:`~lairs.integrations.ports.Exporter` port with the Arrow ``Table`` as
    its view and :class:`TfDataSpec` as its specification. tensorflow is imported
    lazily inside :meth:`export`, so importing the module and deriving feature
    specs never require the ``lairs[tf]`` extra.
    """

    name = "tfdata"

    def export(
        self,
        view: pa.Table,
        *,
        spec: TfDataSpec | None = None,
    ) -> tf.data.Dataset:
        """Export an Arrow view to a ``tf.data.Dataset``.

        Each retained column becomes one tensor in a dictionary-structured
        dataset, keyed by column name. The optional spec selects and orders
        columns and toggles shuffling and batching.

        Parameters
        ----------
        view : pyarrow.Table
            The flattened Arrow view to export.
        spec : TfDataSpec or None, optional
            An optional export specification. When ``None`` every column is kept
            and the dataset is neither shuffled nor batched.

        Returns
        -------
        tf.data.Dataset
            A dictionary-structured dataset, one entry per retained column.

        Raises
        ------
        ImportError
            When tensorflow is not installed.
        """
        resolved = spec if spec is not None else TfDataSpec()
        tf = _require_tensorflow()
        specs = feature_specs_of(view.schema, columns=resolved.columns)
        tensors: dict[str, tf.Tensor] = {}
        for feature in specs:
            dtype = _dtype_for(feature.dtype, tf)
            tensors[feature.name] = tf.ragged.constant(
                _column_values(view, feature),
                dtype=dtype,
            )
        dataset = tf.data.Dataset.from_tensor_slices(tensors)
        return _apply_options(dataset, resolved)


def _apply_options(dataset: tf.data.Dataset, spec: TfDataSpec) -> tf.data.Dataset:
    """Apply the shuffle and batch options from a spec to a dataset.

    Parameters
    ----------
    dataset : tf.data.Dataset
        The dataset to transform.
    spec : TfDataSpec
        The options to apply.

    Returns
    -------
    tf.data.Dataset
        The transformed dataset.
    """
    if spec.shuffle_buffer is not None:
        dataset = dataset.shuffle(spec.shuffle_buffer, seed=spec.seed)
    if spec.batch_size is not None:
        dataset = dataset.batch(spec.batch_size, drop_remainder=spec.drop_remainder)
    return dataset
