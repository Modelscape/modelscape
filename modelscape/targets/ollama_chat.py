"""Local models served by Ollama, through the official ``ollama`` SDK and its chat API.

Requires the ``ollama`` extra: ``uv add "modelscape[ollama]"``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from modelscape.core.identity import Identity
from modelscape.core.observations import TargetOutput, TargetRequest, Usage
from modelscape.targets.common import Options, missing_extra

try:
    from ollama import AsyncClient, ChatResponse
except ModuleNotFoundError as error:
    raise ModuleNotFoundError(missing_extra("OllamaTarget", "ollama")) from error


class _Chat(Protocol):
    async def chat(
        self,
        model: str = "",
        messages: Sequence[Mapping[str, Any]] | None = None,
        *,
        think: bool | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> ChatResponse: ...

    async def close(self) -> None: ...


class OllamaTarget:
    """A model served by Ollama, at ``host``, ``OLLAMA_HOST``, or ``http://127.0.0.1:11434``.

    ``think`` turns a reasoning model's thinking on or off; ``None`` keeps the model's default.
    Every request's seed is the sampling seed, so a rerun asks the same. ``options`` adds model
    options such as ``num_ctx`` as-is. A tag names whatever weights the server holds, so bump
    ``version`` after pulling a tag again.
    """

    __slots__ = ("_client", "_identity", "_model", "_options", "_think")

    def __init__(
        self,
        model: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        think: bool | None = None,
        options: Options | None = None,
        host: str | None = None,
        client: AsyncClient | None = None,
        name: str | None = None,
        version: str = "1",
    ) -> None:
        self._client: _Chat = client or AsyncClient(host)
        self._model = model
        self._think = think
        sampling = {"temperature": temperature, "num_predict": max_tokens, "top_p": top_p}
        self._options = {
            **{key: value for key, value in sampling.items() if value is not None},
            **(options or {}),
        }
        self._identity = Identity(
            name=name or f"ollama:{model}",
            version=version,
            parameters={"model": model, "think": think, "options": self._options},
        )

    def __repr__(self) -> str:
        return f"OllamaTarget(model={self._model!r}, name={self._identity.name!r})"

    @property
    def identity(self) -> Identity:
        return self._identity

    async def aclose(self) -> None:
        """Close this target's client, inside the event loop that used it."""
        await self._client.close()

    async def invoke(self, request: TargetRequest) -> TargetOutput:
        prompt = request.prompt
        system = [] if prompt.system is None else [{"role": "system", "content": prompt.system}]
        response = await self._client.chat(
            model=self._model,
            messages=[
                *system,
                *(
                    {"role": message.role, "content": message.content}
                    for message in prompt.messages
                ),
            ],
            think=self._think,
            options={"seed": request.seed, **self._options},
        )
        return TargetOutput(
            text=response.message.content or "",
            metadata={"model": response.model, "stop_reason": response.done_reason},
            usage=Usage(input_tokens=response.prompt_eval_count, output_tokens=response.eval_count),
        )
