from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import KW_ONLY, dataclass, field
from typing import TypeAlias

from pydantic import JsonValue

from modelscape.core.identity import Identity
from modelscape.core.measurements import MeasureValue
from modelscape.core.observations import TargetOutput
from modelscape.core.tasks import Variant
from modelscape.measures.protocols import Response

MeasureResult: TypeAlias = float | MeasureValue
MetricFunction: TypeAlias = Callable[
    [Variant, TargetOutput], MeasureResult | Awaitable[MeasureResult]
]
DifferenceFunction: TypeAlias = Callable[
    [Response, Response], MeasureResult | Awaitable[MeasureResult]
]


@dataclass(frozen=True)
class CallableMetric:
    """A point metric defined by a sync or async function of a variant and its output.

    The function returns a number, or a ``MeasureValue`` with structured ``details``.
    """

    function: MetricFunction
    _: KW_ONLY
    name: str
    version: str = "1"
    parameters: Mapping[str, JsonValue] = field(default_factory=dict[str, JsonValue])

    @property
    def identity(self) -> Identity:
        return Identity(name=self.name, version=self.version, parameters=dict(self.parameters))

    async def score(self, responses: Sequence[Response]) -> Sequence[MeasureValue]:
        return await asyncio.gather(
            *(_resolve(self.function(variant, output)) for variant, output in responses)
        )


@dataclass(frozen=True)
class CallableDifference:
    """A difference measure defined by a sync or async function of two responses.

    Each ``Response`` exposes ``variant`` and ``output``, so the function can compare
    decisions, confidence, cited evidence, or anything else relative to the task it answered.
    """

    function: DifferenceFunction
    _: KW_ONLY
    name: str
    version: str = "1"
    parameters: Mapping[str, JsonValue] = field(default_factory=dict[str, JsonValue])

    @property
    def identity(self) -> Identity:
        return Identity(name=self.name, version=self.version, parameters=dict(self.parameters))

    async def compare(self, pairs: Sequence[tuple[Response, Response]]) -> Sequence[MeasureValue]:
        return await asyncio.gather(*(_resolve(self.function(start, end)) for start, end in pairs))


def as_measure_value(result: object) -> MeasureValue:
    if isinstance(result, MeasureValue):
        return result
    if isinstance(result, (bool, int, float)):
        return MeasureValue(value=float(result))
    raise TypeError(f"Measures must return a number or MeasureValue, got {type(result).__name__}.")


async def _resolve(result: MeasureResult | Awaitable[MeasureResult]) -> MeasureValue:
    if inspect.isawaitable(result):
        return as_measure_value(await result)
    return as_measure_value(result)
