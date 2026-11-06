from __future__ import annotations

import asyncio
from typing import cast

import pytest

from modelscape.core import Prompt, TargetOutput, TargetRequest
from modelscape.targets import CallableTarget, TargetFunction

REQUEST = TargetRequest(prompt=Prompt.of("2+2?"), repetition=1, seed=7)


async def test_callable_target_wraps_sync_and_async_functions() -> None:
    async def asynchronous(request: TargetRequest) -> TargetOutput:
        await asyncio.sleep(0)
        return TargetOutput(text="async", metadata={"seed": request.seed})

    sync = CallableTarget(lambda request: f"sync {request.repetition}", name="sync")
    assert (await sync.invoke(REQUEST)).text == "sync 1"
    result = await CallableTarget(asynchronous, name="async").invoke(REQUEST)
    assert result.metadata == {"seed": 7}


async def test_callable_target_keeps_structured_results() -> None:
    classifier = CallableTarget(lambda request: {"label": "spam", "score": 0.9}, name="clf")
    output = await classifier.invoke(REQUEST)
    assert output.structured == {"label": "spam", "score": 0.9}
    assert output.text is None
    assert output.as_text() == '{"label":"spam","score":0.9}'


async def test_callable_target_rejects_unsupported_results() -> None:
    def nothing(request: TargetRequest) -> None:
        return None

    def opaque(request: TargetRequest) -> object:
        return object()

    with pytest.raises(TypeError, match="must return a value"):
        await CallableTarget(cast(TargetFunction, nothing), name="none").invoke(REQUEST)
    with pytest.raises(TypeError, match="text, a JSON value, or TargetOutput"):
        await CallableTarget(cast(TargetFunction, opaque), name="opaque").invoke(REQUEST)


def test_target_identity_tracks_configuration() -> None:
    first = CallableTarget(lambda request: "", name="m", parameters={"temperature": 0.0})
    second = CallableTarget(lambda request: "", name="m", parameters={"temperature": 1.0})
    assert first.identity.fingerprint != second.identity.fingerprint
