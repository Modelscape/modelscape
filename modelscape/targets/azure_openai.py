"""Azure OpenAI and Microsoft Foundry models through the Azure OpenAI v1 API.

Requires the ``azure`` extra: ``uv add "modelscape[azure]"``.
"""

from __future__ import annotations

import asyncio
import os

from modelscape.core.identity import Identity
from modelscape.core.observations import TargetOutput, TargetRequest
from modelscape.targets.common import Options, missing_extra

try:
    from azure.core.credentials import TokenCredential
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    from openai import AsyncOpenAI

    from modelscape.targets.openai_responses import OpenAITarget
except ModuleNotFoundError as error:
    raise ModuleNotFoundError(missing_extra("AzureOpenAITarget", "azure")) from error

SCOPE = "https://ai.azure.com/.default"


class AzureOpenAITarget:
    """A deployment on Azure OpenAI or Microsoft Foundry, through the Responses API.

    ``model`` is the deployment name; ``endpoint`` defaults to ``AZURE_OPENAI_ENDPOINT``.
    Authenticates with ``credential``, then ``AZURE_OPENAI_API_KEY``, then Microsoft Entra ID.
    """

    __slots__ = ("_target",)

    def __init__(
        self,
        model: str,
        *,
        endpoint: str | None = None,
        credential: TokenCredential | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        options: Options | None = None,
        client: AsyncOpenAI | None = None,
        name: str | None = None,
        version: str = "1",
    ) -> None:
        self._target = OpenAITarget(
            model,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            options=options,
            client=client or _client(endpoint, credential),
            name=name or f"azure:{model}",
            version=version,
        )

    def __repr__(self) -> str:
        return f"AzureOpenAITarget(name={self.identity.name!r})"

    @property
    def identity(self) -> Identity:
        return self._target.identity

    async def aclose(self) -> None:
        """Close this target's client, inside the event loop that used it."""
        await self._target.aclose()

    async def invoke(self, request: TargetRequest) -> TargetOutput:
        return await self._target.invoke(request)


def _client(endpoint: str | None, credential: TokenCredential | None) -> AsyncOpenAI:
    resource = endpoint or os.environ.get("AZURE_OPENAI_ENDPOINT")
    if not resource:
        raise ValueError(
            "AzureOpenAITarget needs an endpoint: pass endpoint=... or set AZURE_OPENAI_ENDPOINT."
        )
    base = resource.rstrip("/").removesuffix("/openai/v1")
    base_url = f"{base}/openai/v1/"
    key = os.environ.get("AZURE_OPENAI_API_KEY")
    if credential is None and key:
        return AsyncOpenAI(base_url=base_url, api_key=key)
    provider = get_bearer_token_provider(credential or DefaultAzureCredential(), SCOPE)

    async def token() -> str:
        return await asyncio.to_thread(provider)

    return AsyncOpenAI(base_url=base_url, api_key=token)
