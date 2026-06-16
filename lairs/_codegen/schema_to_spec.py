"""Walk a panproto Schema into didactic spec dicts.

The Schema retains union discriminators, refined value types, the
reference-versus-containment edge distinction, defaults, and descriptions,
all of which the lossy ``theory_of`` path would drop. This module performs the
substantive mapping.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from panproto import Schema

    from lairs._types import JsonValue

__all__ = ["schema_to_specs"]


def schema_to_specs(schema: Schema) -> Sequence[dict[str, JsonValue]]:
    """Map a parsed Schema to a sequence of didactic spec dicts.

    Parameters
    ----------
    schema : panproto.Schema
        A Schema parsed from a lexicon document under the atproto protocol.

    Returns
    -------
    collections.abc.Sequence of dict
        Spec dicts carrying discriminators, ref/embed distinctions, refined
        types, and constraints, ready for ``didactic.models_from_specs``.

    Raises
    ------
    NotImplementedError
        Always, until the codegen pipeline lands.
    """
    raise NotImplementedError
