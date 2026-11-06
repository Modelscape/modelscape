from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple, Protocol

from modelscape.core.identity import Identity
from modelscape.core.measurements import MeasureValue
from modelscape.core.observations import TargetOutput
from modelscape.core.tasks import Variant
from modelscape.measures.graphs import Graph


class Response(NamedTuple):
    """One output together with the variant that produced it.

    The variant carries the task, its attributes, reference, prompt, and coordinate, so a
    measure can judge behavior in context rather than from text alone.
    """

    variant: Variant
    output: TargetOutput


class PointMetric(Protocol):
    """Scores single responses at one location in the task space, such as correctness.

    ``score`` receives a batch and returns one value per response, in order.
    """

    @property
    def identity(self) -> Identity: ...

    async def score(self, responses: Sequence[Response]) -> Sequence[MeasureValue]: ...


class DifferenceMeasure(Protocol):
    """Quantifies how much two responses differ; zero means no measurable difference.

    ``compare`` receives a batch of response pairs and returns one value per pair, in order.
    """

    @property
    def identity(self) -> Identity: ...

    async def compare(
        self, pairs: Sequence[tuple[Response, Response]]
    ) -> Sequence[MeasureValue]: ...


class Embedder(Protocol):
    """Maps texts to fixed-length vectors for semantic comparison."""

    @property
    def identity(self) -> Identity: ...

    async def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


class Extractor(Protocol):
    """Decomposes responses into claim graphs for structural comparison.

    ``extract`` receives a batch and returns one graph per response, in order.
    """

    @property
    def identity(self) -> Identity: ...

    async def extract(self, responses: Sequence[Response]) -> Sequence[Graph]: ...
