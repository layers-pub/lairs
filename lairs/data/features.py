"""Dataset feature description derived from the generated models.

``Features`` is a didactic model describing a dataset's columnar schema, read
off the generated record model field specs so it always matches the lexicons.
The derivation maps each didactic field annotation to a dtype token, unwrapping
optionality, exploding tuples into sequence tokens, descending into nested
``dx.Embed`` structs, and marking opaque fields as a binary dtype.
"""

from __future__ import annotations

import types
import typing
from datetime import datetime
from typing import ForwardRef, TypeVar

import didactic.api as dx

__all__ = ["FeatureSpec", "Features", "dtype_of", "features_of"]

type _Annotation = (
    type
    | types.UnionType
    | types.GenericAlias
    | typing.TypeAliasType
    | TypeVar
    | ForwardRef
)
"""The shape of a didactic field annotation value.

A field spec's ``annotation`` is a type-expression value rather than a runtime
value, so it is one of the type-form members above. This mirrors didactic's own
``TypeForm | TypeVar | ForwardRef`` without depending on its private alias and
without resorting to ``Any``/``object``.
"""

# scalar python types mapped to their dtype token. the tokens follow the
# huggingface-style naming so downstream exporters can read them directly.
_SCALAR_TOKENS: dict[type, str] = {
    str: "string",
    bool: "bool",
    int: "int64",
    float: "float64",
    bytes: "binary",
    datetime: "timestamp",
}

# the dtype token used when a field carries an opaque payload (arrays, bytes).
_OPAQUE_TOKEN = "binary"  # noqa: S105

# the dtype token used when no more specific mapping applies.
_UNKNOWN_TOKEN = "string"  # noqa: S105


class FeatureSpec(dx.Model):
    """A single named feature and its dtype.

    Attributes
    ----------
    name : str
        The feature (column) name.
    dtype : str
        The feature dtype as a string token (for example ``"string"``).
    nullable : bool, optional
        Whether the feature admits null values.
    """

    name: str = dx.field(description="feature column name")
    dtype: str = dx.field(description="feature dtype token")
    nullable: bool = dx.field(
        default=True,
        description="whether the feature admits null values",
    )


class Features(dx.Model):
    """A dataset schema description as an ordered tuple of feature specs.

    Attributes
    ----------
    specs : tuple of FeatureSpec
        The ordered feature specifications.
    """

    specs: tuple[FeatureSpec, ...] = dx.field(
        default=(),
        description="ordered feature specifications",
    )

    def names(self) -> tuple[str, ...]:
        """Return the feature names in order.

        Returns
        -------
        tuple of str
            The ordered feature column names.
        """
        return tuple(spec.name for spec in self.specs)

    def get(self, name: str) -> FeatureSpec | None:
        """Return the spec for a feature name, or ``None`` when absent.

        Parameters
        ----------
        name : str
            The feature column name to look up.

        Returns
        -------
        FeatureSpec or None
            The matching spec, or ``None`` when no feature has that name.
        """
        for spec in self.specs:
            if spec.name == name:
                return spec
        return None


def _strip_optional(annotation: _Annotation) -> tuple[_Annotation, bool]:
    """Strip a trailing ``| None`` from an annotation.

    Parameters
    ----------
    annotation : _Annotation
        The field annotation to inspect.

    Returns
    -------
    tuple
        A ``(inner, optional)`` pair where ``inner`` is the annotation with any
        ``None`` member removed and ``optional`` reports whether ``None`` was a
        member.
    """
    origin = typing.get_origin(annotation)
    if origin is typing.Union or origin is types.UnionType:
        members = [arg for arg in typing.get_args(annotation) if arg is not type(None)]
        optional = len(members) != len(typing.get_args(annotation))
        if len(members) == 1:
            return members[0], optional
        # a non-trivial union (a tagged union expressed inline) collapses to a
        # struct token; the members are themselves models.
        return annotation, optional
    return annotation, False


def _embed_inner(annotation: _Annotation) -> type | None:
    """Return the inner type of a ``dx.Embed[...]`` annotation, else ``None``.

    Parameters
    ----------
    annotation : _Annotation
        The field annotation to inspect.

    Returns
    -------
    type or None
        The embedded type, or ``None`` when the annotation is not an ``Embed``.
    """
    if typing.get_origin(annotation) is dx.Embed:
        args = typing.get_args(annotation)
        if args:
            inner = args[0]
            return inner if isinstance(inner, type) else None
    return None


def _is_model(annotation: _Annotation) -> bool:
    """Return whether an annotation is a ``dx.Model`` subclass."""
    return isinstance(annotation, type) and issubclass(annotation, dx.Model)


def _scalar_token(annotation: _Annotation) -> str:
    """Return the scalar dtype token for a type, falling back to the default.

    Parameters
    ----------
    annotation : _Annotation
        A concrete type annotation to map.

    Returns
    -------
    str
        The matching scalar token, or the unknown-token fallback.
    """
    if isinstance(annotation, type):
        for scalar, token in _SCALAR_TOKENS.items():
            if issubclass(annotation, scalar):
                return token
    return _UNKNOWN_TOKEN


def dtype_of(annotation: _Annotation) -> str:
    """Map a didactic field annotation to a dtype token.

    The mapping unwraps optionality, turns tuples into ``sequence<...>`` tokens,
    descends through ``dx.Embed`` to its inner type, renders model-valued fields
    (including embeds and tagged unions) as ``struct``, and renders literals as
    ``string``. Unrecognised annotations fall back to ``string``.

    Parameters
    ----------
    annotation : _Annotation
        The field annotation from a model's field spec.

    Returns
    -------
    str
        The dtype token for the annotation.
    """
    inner, _ = _strip_optional(annotation)

    embed_inner = _embed_inner(inner)
    if embed_inner is not None:
        return "struct" if _is_model(embed_inner) else dtype_of(embed_inner)

    origin = typing.get_origin(inner)
    if origin is tuple or origin is list:
        args = typing.get_args(inner)
        element = args[0] if args else str
        return f"sequence<{dtype_of(element)}>"
    if origin is typing.Literal:
        return "string"
    if _is_model(inner):
        return "struct"
    return _scalar_token(inner)


def features_of(model: type[dx.Model]) -> Features:
    """Derive a :class:`Features` description from a model's field specs.

    The feature order matches the model's field-spec order. Each feature's dtype
    is mapped from the field annotation by :func:`dtype_of`, except that opaque
    fields are forced to a binary token. A feature is nullable when its field is
    not required or its annotation admits ``None``.

    Parameters
    ----------
    model : type of didactic.api.Model
        The generated record model to describe.

    Returns
    -------
    Features
        The derived feature description, one spec per model field.
    """
    specs: list[FeatureSpec] = []
    for name, spec in model.__field_specs__.items():
        _, optional = _strip_optional(spec.annotation)
        dtype = _OPAQUE_TOKEN if spec.is_opaque else dtype_of(spec.annotation)
        nullable = optional or not spec.is_required
        specs.append(FeatureSpec(name=name, dtype=dtype, nullable=nullable))
    return Features(specs=tuple(specs))
