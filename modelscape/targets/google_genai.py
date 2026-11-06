"""Gemini models through the official ``google-genai`` SDK.

Requires the ``google`` extra: ``uv add "modelscape[google]"``.
"""

from __future__ import annotations

from modelscape.core.identity import Identity
from modelscape.core.observations import TargetOutput, TargetRequest, Usage
from modelscape.targets.common import Options, missing_extra

try:
    from google import genai
    from google.genai import types
except ModuleNotFoundError as error:
    raise ModuleNotFoundError(missing_extra("GoogleGenAITarget", "google")) from error


class GoogleGenAITarget:
    """A Gemini model on the Gemini Developer API or Vertex AI.

    Configured from the environment like the SDK, or with ``enterprise``, ``project``, and
    ``location``. ``options`` adds ``GenerateContentConfig`` fields.
    """

    __slots__ = ("_client", "_config", "_identity", "_model")

    def __init__(
        self,
        model: str,
        *,
        enterprise: bool | None = None,
        project: str | None = None,
        location: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        options: Options | None = None,
        client: genai.Client | None = None,
        name: str | None = None,
        version: str = "1",
    ) -> None:
        self._client = client or genai.Client(
            enterprise=enterprise, project=project, location=location
        )
        self._model = model
        self._config: dict[str, object] = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
            "top_p": top_p,
            **(options or {}),
        }
        self._identity = Identity(
            name=name or f"google:{model}",
            version=version,
            parameters={
                "model": model,
                "backend": "google-cloud" if self._client.vertexai else "gemini-api",
                "temperature": temperature,
                "max_tokens": max_tokens,
                "top_p": top_p,
                "options": dict(options or {}),
            },
        )

    def __repr__(self) -> str:
        return f"GoogleGenAITarget(model={self._model!r}, name={self._identity.name!r})"

    @property
    def identity(self) -> Identity:
        return self._identity

    async def aclose(self) -> None:
        """Close this target's client, inside the event loop that used it."""
        await self._client.aio.aclose()

    async def invoke(self, request: TargetRequest) -> TargetOutput:
        prompt = request.prompt
        config = types.GenerateContentConfig.model_validate(
            {"seed": request.seed, "system_instruction": prompt.system, **self._config}
        )
        contents: list[types.ContentUnion] = [
            types.Content(
                role="model" if message.role == "assistant" else "user",
                parts=[types.Part(text=message.content)],
            )
            for message in prompt.messages
        ]
        response = await self._client.aio.models.generate_content(
            model=self._model, contents=contents, config=config
        )
        candidate = response.candidates[0] if response.candidates else None
        reason = candidate.finish_reason if candidate else None
        usage = response.usage_metadata
        return TargetOutput(
            text=response.text,
            metadata={
                "model": response.model_version or self._model,
                "stop_reason": reason.value if reason else None,
                "response_id": response.response_id,
            },
            usage=None
            if usage is None
            else Usage(
                input_tokens=usage.prompt_token_count,
                output_tokens=_sum(usage.candidates_token_count, usage.thoughts_token_count),
            ),
        )


def _sum(*counts: int | None) -> int | None:
    present = [count for count in counts if count is not None]
    return sum(present) if present else None
