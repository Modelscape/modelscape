from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import KW_ONLY, dataclass, field
from typing import TypeAlias, cast

from pydantic import JsonValue

from modelscape.core.errors import MeasureError
from modelscape.core.identity import Identity
from modelscape.core.measurements import MeasureValue
from modelscape.core.observations import Prompt, TargetRequest
from modelscape.measures.graphs import Graph
from modelscape.measures.protocols import Extractor, Response
from modelscape.targets.protocols import Target

Triples: TypeAlias = Iterable[tuple[str, str, str]]
ExtractorResult: TypeAlias = Graph | Triples
ExtractorFunction: TypeAlias = Callable[[Response], ExtractorResult | Awaitable[ExtractorResult]]

CLAIM_INSTRUCTIONS = (
    "Decompose the text into its atomic factual claims. Reply with only a JSON array of "
    "[subject, relation, object] triples. Use short lowercase phrases, and always use the same "
    "wording for the same entity or relation."
)


@dataclass(frozen=True)
class GraphDistance:
    """The share of claims that appear in only one of two responses (Jaccard distance).

    ``details`` lists the claims only in the first response (``removed``) and only in the
    second (``added``). Two responses without claims have distance zero.
    """

    extractor: Extractor

    @property
    def identity(self) -> Identity:
        return Identity(
            name="graph_distance",
            parameters={"extractor": self.extractor.identity.model_dump(mode="json")},
        )

    async def compare(self, pairs: Sequence[tuple[Response, Response]]) -> Sequence[MeasureValue]:
        unique = {_key(response): response for pair in pairs for response in pair}
        graphs = await self.extractor.extract(list(unique.values()))
        if len(graphs) != len(unique):
            raise MeasureError(
                f"Extractor '{self.extractor.identity.name}' returned {len(graphs)} graphs "
                f"for {len(unique)} responses."
            )
        lookup = dict(zip(unique, graphs, strict=True))
        return [_distance(lookup[_key(start)], lookup[_key(end)]) for start, end in pairs]


@dataclass(frozen=True)
class CallableExtractor:
    """An extractor defined by a sync or async function from a response to its claims."""

    function: ExtractorFunction
    _: KW_ONLY
    name: str
    version: str = "1"
    parameters: Mapping[str, JsonValue] = field(default_factory=dict[str, JsonValue])

    @property
    def identity(self) -> Identity:
        return Identity(name=self.name, version=self.version, parameters=dict(self.parameters))

    async def extract(self, responses: Sequence[Response]) -> Sequence[Graph]:
        return await asyncio.gather(*(self._one(response) for response in responses))

    async def _one(self, response: Response) -> Graph:
        result = self.function(response)
        if inspect.isawaitable(result):
            result = await result
        return result if isinstance(result, Graph) else Graph.of(result)


@dataclass(frozen=True)
class ModelExtractor:
    """An extractor that asks a model to decompose each response into claim triples."""

    target: Target
    _: KW_ONLY
    instructions: str = CLAIM_INSTRUCTIONS
    concurrency: int = 8

    @property
    def identity(self) -> Identity:
        return Identity(
            name="model_extractor",
            parameters={
                "target": self.target.identity.model_dump(mode="json"),
                "instructions": self.instructions,
            },
        )

    async def extract(self, responses: Sequence[Response]) -> Sequence[Graph]:
        semaphore = asyncio.Semaphore(self.concurrency)

        async def bounded(response: Response) -> Graph:
            async with semaphore:
                return await self._one(response)

        return await asyncio.gather(*(bounded(response) for response in responses))

    async def _one(self, response: Response) -> Graph:
        prompt = Prompt.of(response.output.as_text(), system=self.instructions)
        output = await self.target.invoke(TargetRequest(prompt=prompt, repetition=0, seed=0))
        return parse_triples(output.as_text())


def parse_triples(text: str) -> Graph:
    """The claim graph in a JSON array of ``[subject, relation, object]`` triples."""
    start, end = text.find("["), text.rfind("]")
    try:
        items: object = json.loads(text[start : end + 1]) if 0 <= start < end else None
    except json.JSONDecodeError:
        items = None
    if not isinstance(items, list):
        raise MeasureError(f"Expected a JSON array of claim triples, got {text[:200]!r}.")
    return Graph.of(_triple(item) for item in cast(list[object], items))


def _triple(item: object) -> tuple[str, str, str]:
    parts = cast(list[object], item) if isinstance(item, list) else []
    words = [part for part in parts if isinstance(part, str) and part.strip()]
    if len(parts) != 3 or len(words) != 3:
        raise MeasureError(f"Expected a [subject, relation, object] triple, got {item!r}.")
    return words[0], words[1], words[2]


def _key(response: Response) -> tuple[str, str]:
    return response.variant.id, response.output.as_text()


def _distance(start: Graph, end: Graph) -> MeasureValue:
    before, after = start.keys, end.keys
    union = before | after
    return MeasureValue(
        value=len(before ^ after) / len(union) if union else 0.0,
        details={
            "removed": [list(key) for key in sorted(before - after)],
            "added": [list(key) for key in sorted(after - before)],
        },
    )
