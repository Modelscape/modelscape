from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from modelscape.core.errors import MeasureError
from modelscape.core.identity import Identity
from modelscape.core.measurements import MeasureValue
from modelscape.core.observations import TargetOutput
from modelscape.measures.protocols import Embedder, Response
from modelscape.measures.text import levenshtein, normalize_text, word_set


@dataclass(frozen=True)
class NormalizedEditDistance:
    """Character-level Levenshtein distance divided by the length of the longer text."""

    normalize: bool = True

    @property
    def identity(self) -> Identity:
        return Identity(name="edit_distance", version="1", parameters={"normalize": self.normalize})

    async def compare(self, pairs: Sequence[tuple[Response, Response]]) -> Sequence[MeasureValue]:
        return [
            self._distance(self._text(start.output), self._text(end.output)) for start, end in pairs
        ]

    def _text(self, output: TargetOutput) -> str:
        text = output.as_text()
        return normalize_text(text) if self.normalize else text

    @staticmethod
    def _distance(left: str, right: str) -> MeasureValue:
        longest = max(len(left), len(right))
        if longest == 0:
            return MeasureValue(value=0.0)
        edits = levenshtein(left, right)
        return MeasureValue(value=edits / longest, details={"edits": edits})


@dataclass(frozen=True)
class TokenJaccardDistance:
    """One minus the Jaccard similarity of the case-folded word sets of two outputs."""

    @property
    def identity(self) -> Identity:
        return Identity(name="token_jaccard", version="1")

    async def compare(self, pairs: Sequence[tuple[Response, Response]]) -> Sequence[MeasureValue]:
        return [
            self._distance(word_set(start.output.as_text()), word_set(end.output.as_text()))
            for start, end in pairs
        ]

    @staticmethod
    def _distance(left: frozenset[str], right: frozenset[str]) -> MeasureValue:
        union = left | right
        if not union:
            return MeasureValue(value=0.0)
        return MeasureValue(value=1.0 - len(left & right) / len(union))


@dataclass(frozen=True)
class EmbeddingCosineDistance:
    """One minus the cosine similarity of output embeddings from an injected embedder.

    Each distinct text in a batch is embedded once.
    """

    embedder: Embedder

    @property
    def identity(self) -> Identity:
        return Identity(
            name="embedding_cosine",
            version="1",
            parameters={"embedder": self.embedder.identity.model_dump(mode="json")},
        )

    async def compare(self, pairs: Sequence[tuple[Response, Response]]) -> Sequence[MeasureValue]:
        if not pairs:
            return []
        texts = list(dict.fromkeys(item.output.as_text() for pair in pairs for item in pair))
        vectors = await self.embedder.embed(texts)
        if len(vectors) != len(texts):
            raise MeasureError(
                f"Embedder '{self.embedder.identity.name}' returned {len(vectors)} vectors "
                f"for {len(texts)} texts."
            )
        matrix = np.asarray(vectors, dtype=np.float64)
        norms = np.linalg.norm(matrix, axis=1)
        if np.any(norms == 0):
            raise MeasureError(f"Embedder '{self.embedder.identity.name}' returned a zero vector.")
        unit = matrix / norms[:, np.newaxis]
        position = {text: index for index, text in enumerate(texts)}
        return [
            MeasureValue(
                value=float(
                    np.clip(
                        1.0
                        - unit[position[start.output.as_text()]]
                        @ unit[position[end.output.as_text()]],
                        0.0,
                        2.0,
                    )
                )
            )
            for start, end in pairs
        ]
