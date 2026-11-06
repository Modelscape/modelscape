from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import TypeAlias

from pydantic import JsonValue

from modelscape.core.identity import Identity
from modelscape.core.observations import TargetOutput, TargetRequest

TargetResult: TypeAlias = TargetOutput | JsonValue | Mapping[str, object] | Sequence[object]
TargetFunction: TypeAlias = Callable[[TargetRequest], TargetResult | Awaitable[TargetResult]]


class CallableTarget:
    """Any function from a ``TargetRequest`` to text, JSON, or a ``TargetOutput``, as a target.

    Synchronous functions run in worker threads. Put behavior-relevant settings in
    ``parameters``, never credentials.
    """

    __slots__ = ("_function", "_identity", "_is_async")

    def __init__(
        self,
        function: TargetFunction,
        *,
        name: str,
        version: str = "1",
        parameters: Mapping[str, JsonValue] | None = None,
    ) -> None:
        self._function = function
        self._identity = Identity(name=name, version=version, parameters=dict(parameters or {}))
        self._is_async = inspect.iscoroutinefunction(function) or inspect.iscoroutinefunction(
            type(function).__call__
        )

    def __repr__(self) -> str:
        return f"CallableTarget(name={self._identity.name!r}, version={self._identity.version!r})"

    @property
    def identity(self) -> Identity:
        return self._identity

    async def invoke(self, request: TargetRequest) -> TargetOutput:
        if self._is_async:
            result = self._function(request)
        else:
            result = await asyncio.to_thread(self._function, request)
        if inspect.isawaitable(result):
            result = await result
        return _as_output(result)


def _as_output(result: object) -> TargetOutput:
    if isinstance(result, TargetOutput):
        return result
    if isinstance(result, str):
        return TargetOutput(text=result)
    if result is None:
        raise TypeError("Target functions must return a value, got None.")
    try:
        return TargetOutput.model_validate({"structured": result})
    except ValueError as error:
        raise TypeError(
            "Target functions must return text, a JSON value, or TargetOutput, "
            f"got {type(result).__name__}."
        ) from error
