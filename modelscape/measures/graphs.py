from __future__ import annotations

from collections.abc import Iterable

from pydantic import Field

from modelscape.core.serialization import FrozenModel
from modelscape.measures.text import normalize_text


class Edge(FrozenModel):
    """One claim: a labeled relation between two entities."""

    source: str = Field(min_length=1)
    relation: str = Field(min_length=1)
    target: str = Field(min_length=1)

    @property
    def key(self) -> tuple[str, str, str]:
        return (
            normalize_text(self.source),
            normalize_text(self.relation),
            normalize_text(self.target),
        )


class Graph(FrozenModel):
    """A response decomposed into claims: a set of labeled edges between entities."""

    edges: frozenset[Edge] = frozenset()

    @classmethod
    def of(cls, triples: Iterable[tuple[str, str, str]]) -> Graph:
        return cls(
            edges=frozenset(
                Edge(source=source, relation=relation, target=target)
                for source, relation, target in triples
            )
        )

    @property
    def keys(self) -> frozenset[tuple[str, str, str]]:
        return frozenset(edge.key for edge in self.edges)
