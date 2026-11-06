"""Any server with an OpenAI-compatible Chat Completions API, through the official ``openai`` SDK.

vLLM, SGLang, LM Studio, llama.cpp, OpenRouter, Together, Groq, and many others serve it.
Requires the ``openai`` extra: ``uv add "modelscape[openai]"``.
"""

from __future__ import annotations

import os
from typing import Any

from modelscape.core.identity import Identity
from modelscape.core.observations import TargetOutput, TargetRequest, Usage
from modelscape.targets.common import Options, missing_extra, public_endpoint

try:
    from openai import AsyncOpenAI, omit
except ModuleNotFoundError as error:
    raise ModuleNotFoundError(missing_extra("OpenAIChatTarget", "openai")) from error

UNUSED_KEY = "unused"
BASE_URL = "OPENAI_CHAT_BASE_URL"
API_KEY = "OPENAI_CHAT_API_KEY"
OPENAI = "https://api.openai.com/v1"


class OpenAIChatTarget:
    """A model on an OpenAI-compatible Chat Completions API.

    ``base_url`` defaults to ``OPENAI_CHAT_BASE_URL``, then to OpenAI. ``api_key`` defaults to
    ``OPENAI_CHAT_API_KEY``; OpenAI itself falls back to ``OPENAI_API_KEY``, which is never sent
    to another server. A server that needs no key runs without one. Pass ``client`` for any
    other setup. ``options`` adds request fields as-is, such as
    ``{"chat_template_kwargs": {"enable_thinking": False}}`` for vLLM.
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
        base_url: str | None = None,
        api_key: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        options: Options | None = None,
        client: AsyncOpenAI | None = None,
        name: str | None = None,
        version: str = "1",
    ) -> None:
        if client is not None and (base_url is not None or api_key is not None):
            raise ValueError("Pass either a client or its base_url and api_key, not both.")
        self._client = client or _client(base_url, api_key)
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._top_p = top_p
        self._options = dict(options or {})
        self._identity = Identity(
            name=name or f"openai-chat:{model}",
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
        prompt = request.prompt
        system = [] if prompt.system is None else [{"role": "system", "content": prompt.system}]
        messages: Any = [
            *system,
            *({"role": message.role, "content": message.content} for message in prompt.messages),
        ]
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=omit if self._temperature is None else self._temperature,
            max_tokens=omit if self._max_tokens is None else self._max_tokens,
            top_p=omit if self._top_p is None else self._top_p,
            extra_body=self._options or None,
        )
        choice = response.choices[0]
        usage = response.usage
        return TargetOutput(
            text=choice.message.content or "",
            metadata={
                "model": response.model,
                "stop_reason": choice.finish_reason,
                "response_id": response.id,
            },
            usage=None
            if usage is None
            else Usage(input_tokens=usage.prompt_tokens, output_tokens=usage.completion_tokens),
        )


def _client(base_url: str | None, api_key: str | None) -> AsyncOpenAI:
    url = base_url or os.environ.get(BASE_URL)
    key = api_key or os.environ.get(API_KEY)
    if url is None:
        return AsyncOpenAI(base_url=OPENAI, api_key=key)
    return AsyncOpenAI(base_url=url, api_key=key or UNUSED_KEY)
