"""Knowledge-base connectors for grounding, entity linking, and enrichment.

This package defines the shared knowledge-base value models (entity, candidate,
edge) as didactic models, plus the optional connector adapters that bind to the
:class:`~lairs.integrations.ports.KnowledgeBase` port.
"""

from __future__ import annotations

import didactic.api as dx

__all__ = ["Candidate", "Edge", "Entity"]


class Entity(dx.Model):
    """A resolved knowledge-base entity.

    Attributes
    ----------
    ref : str
        The canonical identifier or URI of the entity.
    label : str
        The primary label.
    aliases : tuple of str, optional
        Alternative surface forms.
    types : tuple of str, optional
        The entity's type identifiers.
    description : str or None, optional
        A short description, when available.
    same_as : tuple of str, optional
        Cross-references to the same entity in other knowledge bases.
    """

    ref: str = dx.field(description="canonical identifier or URI")
    label: str = dx.field(description="primary label")
    aliases: tuple[str, ...] = dx.field(default=(), description="alternative forms")
    types: tuple[str, ...] = dx.field(default=(), description="type identifiers")
    description: str | None = dx.field(default=None, description="short description")
    same_as: tuple[str, ...] = dx.field(
        default=(),
        description="cross-references to the same entity elsewhere",
    )


class Candidate(dx.Model):
    """A ranked entity-linking candidate.

    Attributes
    ----------
    ref : str
        The candidate identifier or URI.
    label : str
        The candidate label.
    score : float
        The ranking score.
    """

    ref: str = dx.field(description="candidate identifier or URI")
    label: str = dx.field(description="candidate label")
    score: float = dx.field(description="ranking score")


class Edge(dx.Model):
    """A directed edge in a knowledge-base neighbourhood.

    Attributes
    ----------
    source : str
        The source entity identifier or URI.
    relation : str
        The relation identifier.
    target : str
        The target entity identifier or URI.
    """

    source: str = dx.field(description="source entity identifier or URI")
    relation: str = dx.field(description="relation identifier")
    target: str = dx.field(description="target entity identifier or URI")
