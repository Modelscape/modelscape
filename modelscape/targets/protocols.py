from __future__ import annotations

from typing import Protocol, runtime_checkable

from modelscape.core.identity import Identity
from modelscape.core.observations import TargetOutput, TargetRequest


class Target(Protocol):
    """The system under evaluation, seen only from outside: prompt in, output out.

    No access to weights, activations, logits, token probabilities, or deterministic decoding
    is assumed. ``identity`` must change whenever behavior-relevant configuration changes, such
    as the model name or decoding parameters, and must never contain secrets.
    """

    @property
    def identity(self) -> Identity: ...

    async def invoke(self, request: TargetRequest) -> TargetOutput: ...


@runtime_checkable
class Closable(Protocol):
    """A target holding connections that ``aclose`` releases once a run is over."""

    async def aclose(self) -> None: ...
