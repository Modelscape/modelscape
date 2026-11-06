from __future__ import annotations

from collections.abc import Sequence

import pytest

from modelscape import Prompt
from modelscape.core import Coordinate, Identity, MeasureError, TargetOutput, Variant
from modelscape.measures import (
    EmbeddingCosineDistance,
    ExactMatch,
    NormalizedEditDistance,
    Response,
    TokenJaccardDistance,
)


def variant(reference: str | float | None) -> Variant:
    return Variant.create(
        case_id="case",
        coordinate=Coordinate({"a": 0}),
        task={"q": "?"},
        attributes={"a": 0},
        reference=reference,
        prompt=Prompt.of("?"),
        steps=(),
    )


def text(value: str) -> TargetOutput:
    return TargetOutput(text=value)


def said(value: str, reference: str | float | None = None) -> Response:
    return Response(variant(reference), text(value))


async def test_exact_match_normalizes_by_default() -> None:
    scores = await ExactMatch().score([said("  paris ", "Paris"), said("Lyon", "Paris")])
    assert [score.value for score in scores] == [1.0, 0.0]
    strict = await ExactMatch(normalize=False).score([said("paris", "Paris")])
    assert strict[0].value == 0.0


async def test_metrics_require_references() -> None:
    with pytest.raises(MeasureError, match="needs a reference"):
        await ExactMatch().score([said("x", None)])


async def test_text_differences() -> None:
    pairs = [
        (said("The cat sat"), said("the cat  sat")),
        (said("abc"), said("abd")),
        (said(""), said("")),
    ]
    edits = await NormalizedEditDistance().compare(pairs)
    assert [value.value for value in edits] == pytest.approx([0.0, 1 / 3, 0.0])
    jaccard = await TokenJaccardDistance().compare([(said("a b c"), said("a b d")), *pairs])
    assert [value.value for value in jaccard] == pytest.approx([0.5, 0.0, 1.0, 0.0])


async def test_structured_outputs_compare_canonically() -> None:
    left = Response(variant(None), TargetOutput(structured={"b": 1, "a": 2}))
    right = Response(variant(None), TargetOutput(structured={"a": 2, "b": 1}))
    assert (await NormalizedEditDistance().compare([(left, right)]))[0].value == 0.0


class TableEmbedder:
    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self.vectors = vectors
        self.calls: list[list[str]] = []

    @property
    def identity(self) -> Identity:
        return Identity(name="table")

    async def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        self.calls.append(list(texts))
        return [self.vectors[item] for item in texts]


async def test_embedding_distance_embeds_each_text_once() -> None:
    embedder = TableEmbedder({"a": [1.0, 0.0], "b": [0.0, 1.0], "c": [1.0, 0.0]})
    measure = EmbeddingCosineDistance(embedder)
    values = await measure.compare(
        [(said("a"), said("b")), (said("a"), said("c")), (said("b"), said("a"))]
    )
    assert [value.value for value in values] == pytest.approx([1.0, 0.0, 1.0])
    assert embedder.calls == [["a", "b", "c"]]
    assert measure.identity.parameters["embedder"] == {
        "name": "table",
        "version": "1",
        "parameters": {},
    }


async def test_embedding_distance_rejects_degenerate_vectors() -> None:
    with pytest.raises(MeasureError, match="zero vector"):
        await EmbeddingCosineDistance(TableEmbedder({"a": [0.0, 0.0]})).compare(
            [(said("a"), said("a"))]
        )


async def test_embedding_distance_needs_one_vector_per_text() -> None:
    class Short(TableEmbedder):
        async def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
            return (await super().embed(texts))[:1]

    embedder = Short({"a": [1.0, 0.0], "b": [0.0, 1.0]})
    assert await EmbeddingCosineDistance(embedder).compare([]) == []
    assert embedder.calls == []
    with pytest.raises(MeasureError, match="returned 1 vectors for 2 texts"):
        await EmbeddingCosineDistance(embedder).compare([(said("a"), said("b"))])


def test_measure_identities_capture_parameters() -> None:
    assert ExactMatch().identity != ExactMatch(normalize=False).identity
    assert NormalizedEditDistance().identity != NormalizedEditDistance(normalize=False).identity
