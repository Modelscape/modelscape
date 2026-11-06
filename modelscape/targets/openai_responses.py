"""OpenAI models through the official ``openai`` SDK and the Responses API.

Requires the ``openai`` extra: ``uv add "modelscape[openai]"``.
"""

from __future__ import annotations

from modelscape.core.identity import Identity
from modelscape.core.observations import TargetOutput, TargetRequest, Usage
from modelscape.targets.common import Options, missing_extra, public_endpoint

try:
    from openai import AsyncOpenAI, omit
except ModuleNotFoundError as error:
    raise ModuleNotFoundError(missing_extra("OpenAITarget", "openai")) from error


class OpenAITarget:
    """A model on the OpenAI Responses API, or on any server that implements it.

    ``options`` adds request fields as-is. Reads ``OPENAI_API_KEY`` and ``OPENAI_BASE_URL``; pass
    ``client`` for any other setup.
    """

    __slots__ = (
        "_client",
        "_identity",
        "_max_tokens",
        "_model",
        "_options",
        "_temperature",
        "_top_p",
    )

    def __init__(
        self,
        model: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        options: Options | None = None,
        client: AsyncOpenAI | None = None,
        name: str | None = None,
        version: str = "1",
    ) -> None:
        self._client = client or AsyncOpenAI()
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._top_p = top_p
        self._options = dict(options or {})
        self._identity = Identity(
            name=name or f"openai:{model}",
            version=version,
            parameters={
                "model": model,
                "endpoint": public_endpoint(self._client.base_url),
                "temperature": temperature,
                "max_tokens": max_tokens,
                "top_p": top_p,
                "options": self._options,
            },
        )

    def __repr__(self) -> str:
        return f"{type(self).__name__}(model={self._model!r}, name={self._identity.name!r})"

    @property
    def identity(self) -> Identity:
        return self._identity

    async def aclose(self) -> None:
        """Close this target's client, inside the event loop that used it."""
        await self._client.close()

    async def invoke(self, request: TargetRequest) -> TargetOutput:
        response = await self._client.responses.create(
            model=self._model,
            input=[
                {"role": message.role, "content": message.content}
                for message in request.prompt.messages
            ],
            instructions=omit if request.prompt.system is None else request.prompt.system,
            temperature=omit if self._temperature is None else self._temperature,
            max_output_tokens=omit if self._max_tokens is None else self._max_tokens,
            top_p=omit if self._top_p is None else self._top_p,
            store=False,
            extra_body=self._options or None,
        )
        incomplete = response.incomplete_details
        usage = response.usage
        return TargetOutput(
            text=response.output_text,
            metadata={
                "model": response.model,
                "stop_reason": incomplete.reason if incomplete else response.status,
                "response_id": response.id,
            },
            usage=None
            if usage is None
            else Usage(input_tokens=usage.input_tokens, output_tokens=usage.output_tokens),
        )
