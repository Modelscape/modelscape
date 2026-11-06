"""Amazon Bedrock models through ``boto3`` and the Bedrock Runtime Converse API.

Requires the ``aws`` extra: ``uv add "modelscape[aws]"``.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from modelscape.core.identity import Identity
from modelscape.core.observations import TargetOutput, TargetRequest, Usage
from modelscape.targets.common import Options, missing_extra

try:
    import boto3
except ModuleNotFoundError as error:
    raise ModuleNotFoundError(missing_extra("BedrockTarget", "aws")) from error

if TYPE_CHECKING:
    from types_boto3_bedrock_runtime.client import BedrockRuntimeClient
    from types_boto3_bedrock_runtime.type_defs import (
        ConverseRequestTypeDef,
        ConverseResponseTypeDef,
        InferenceConfigurationTypeDef,
    )


class BedrockTarget:
    """A model ID, inference profile, or ARN on Amazon Bedrock, through the Converse API.

    Credentials come from the AWS chain; ``region``, ``session``, or ``client`` configure it.
    ``options`` adds top-level Converse fields as-is.
    """

    __slots__ = ("_client", "_identity", "_model", "_request")

    def __init__(
        self,
        model: str,
        *,
        region: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        options: Options | None = None,
        session: boto3.Session | None = None,
        client: BedrockRuntimeClient | None = None,
        name: str | None = None,
        version: str = "1",
    ) -> None:
        self._client: BedrockRuntimeClient = (
            client if client is not None else _client(session, region)
        )
        self._model = model
        inference: InferenceConfigurationTypeDef = {}
        if temperature is not None:
            inference["temperature"] = temperature
        if max_tokens is not None:
            inference["maxTokens"] = max_tokens
        if top_p is not None:
            inference["topP"] = top_p
        self._request: dict[str, object] = {
            "modelId": model,
            **({"inferenceConfig": inference} if inference else {}),
            **(options or {}),
        }
        self._identity = Identity(
            name=name or f"bedrock:{model}",
            version=version,
            parameters={
                "model": model,
                "region": self._client.meta.region_name,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "top_p": top_p,
                "options": dict(options or {}),
            },
        )

    def __repr__(self) -> str:
        return f"BedrockTarget(model={self._model!r}, name={self._identity.name!r})"

    @property
    def identity(self) -> Identity:
        return self._identity

    async def invoke(self, request: TargetRequest) -> TargetOutput:
        prompt = request.prompt
        fields = cast(
            "ConverseRequestTypeDef",
            {
                **self._request,
                **({"system": [{"text": prompt.system}]} if prompt.system is not None else {}),
                "messages": [
                    {"role": message.role, "content": [{"text": message.content}]}
                    for message in prompt.messages
                ],
            },
        )
        response = await asyncio.to_thread(self._client.converse, **fields)
        return self._output(response)

    def _output(self, response: ConverseResponseTypeDef) -> TargetOutput:
        message = response["output"].get("message")
        blocks = message["content"] if message else []
        usage = response["usage"]
        routed = response.get("trace", {}).get("promptRouter", {}).get("invokedModelId")
        return TargetOutput(
            text="".join(block["text"] for block in blocks if "text" in block),
            metadata={
                "model": routed or self._model,
                "stop_reason": response["stopReason"],
                "latency_ms": response.get("metrics", {}).get("latencyMs"),
                "request_id": response.get("ResponseMetadata", {}).get("RequestId"),
            },
            usage=Usage(input_tokens=usage["inputTokens"], output_tokens=usage["outputTokens"]),
        )


def _client(session: boto3.Session | None, region: str | None) -> BedrockRuntimeClient:
    session = session or boto3.Session()
    if session.get_credentials() is None:
        raise RuntimeError(
            "BedrockTarget found no AWS credentials. Configure them with `aws configure`, "
            "`aws sso login`, AWS_PROFILE, environment variables, or an IAM role."
        )
    return session.client("bedrock-runtime", region_name=region)
