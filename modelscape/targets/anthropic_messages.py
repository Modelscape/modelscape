"""Anthropic Claude models through the official ``anthropic`` SDK and the Messages API.

Requires the ``anthropic`` extra: ``uv add "modelscape[anthropic]"``.
"""

from __future__ import annotations

from modelscape.core.identity import Identity
from modelscape.core.observations import TargetOutput, TargetRequest, Usage
from modelscape.targets.common import Options, missing_extra, public_endpoint

try:
    from anthropic import AsyncAnthropic, omit
except ModuleNotFoundError as error:
    raise ModuleNotFoundError(missing_extra("AnthropicTarget", "anthropic")) from error

DEFAULT_MAX_TOKENS = 1024


class AnthropicTarget:
    """A Claude model on the Anthropic Messages API.

    ``options`` adds request fields as-is. Reads ``ANTHROPIC_API_KEY``; pass ``client`` for any
    other setup.
    """

    __slots__ = (
        "_client",
        "_identity",
        "_max_tokens",
        "_model",
        "_options",
    )

    def __init__(
        self,
        model: str,
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        options: Options | None = None,
        client: AsyncAnthropic | None = None,
        name: str | None = None,
        version: str = "1",
    ) -> None:
        self._client = client or AsyncAnthropic()
        self._model = model
        self._max_tokens = max_tokens
        self._options = dict(options or {})
        self._identity = Identity(
            name=name or f"anthropic:{model}",
            version=version,
            parameters={
                "model": model,
                "endpoint": public_endpoint(self._client.base_url),
                "max_tokens": max_tokens,
                "options": self._options,
            },
        )

    def __repr__(self) -> str:
        return f"AnthropicTarget(model={self._model!r}, name={self._identity.name!r})"

    @property
    def identity(self) -> Identity:
        return self._identity

    async def aclose(self) -> None:
        """Close this target's client, inside the event loop that used it."""
        await self._client.close()

    async def invoke(self, request: TargetRequest) -> TargetOutput:
        message = await self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=[
                {"role": "user", "content": message.content}
                if message.role == "user"
                else {"role": "assistant", "content": message.content}
                for message in request.prompt.messages
            ],
            system=omit if request.prompt.system is None else request.prompt.system,
            extra_body=self._options or None,
        )
        return TargetOutput(
            text="".join(block.text for block in message.content if block.type == "text"),
            metadata={
                "model": message.model,
                "stop_reason": message.stop_reason,
                "response_id": message.id,
            },
            usage=Usage(
                input_tokens=message.usage.input_tokens,
                output_tokens=message.usage.output_tokens,
            ),
        )
