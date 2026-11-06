from __future__ import annotations

import functools
import json
import subprocess
import sys
from typing import TYPE_CHECKING, Any

import boto3
import httpx as ollama_http
import httpx2 as httpx
import pytest
from anthropic import AsyncAnthropic
from azure.core.credentials import AccessToken
from botocore.stub import Stubber
from google import genai
from google.genai import types
from ollama import AsyncClient
from openai import AsyncOpenAI

from modelscape import (
    Axis,
    ExecutionConfig,
    Experiment,
    Message,
    Prompt,
    RetryPolicy,
    Runner,
    TaskSpace,
    targets,
)
from modelscape.core import TargetRequest
from modelscape.targets import (
    AnthropicTarget,
    AzureOpenAITarget,
    BedrockTarget,
    GoogleGenAITarget,
    OllamaTarget,
    OpenAITarget,
    Target,
)
from modelscape.targets import azure_openai as azure_module
from tests.helpers import Probe, probe_cases, set_level

if TYPE_CHECKING:
    from types_boto3_bedrock_runtime.client import BedrockRuntimeClient

REQUEST = TargetRequest(prompt=Prompt.of("2+2?", system="Be brief."), repetition=1, seed=7)
BARE = TargetRequest(prompt=Prompt.of("2+2?"), repetition=1, seed=7)
CONVERSATION = TargetRequest(
    prompt=Prompt(
        messages=(
            Message(role="user", content="2+2?"),
            Message(role="assistant", content="4"),
            Message(role="user", content="And 3+3?"),
        )
    ),
    repetition=0,
    seed=1,
)
SECRETS = ("sk-test-secret", "AKIDSECRET", "aws-secret-value", "goog-secret", "azure-secret")
Received = list[httpx.Request]


def transport(payload: dict[str, Any], received: Received) -> httpx.MockTransport:
    def respond(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(respond)


def body(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content)


def assert_no_secrets(target: Target) -> None:
    stored = target.identity.model_dump_json() + repr(target)
    for secret in SECRETS:
        assert secret not in stored


RESPONSES_PAYLOAD: dict[str, Any] = {
    "id": "resp_1",
    "object": "response",
    "created_at": 0,
    "model": "gpt-test-2026-01-01",
    "status": "completed",
    "incomplete_details": None,
    "output": [
        {
            "type": "message",
            "id": "msg_1",
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "4", "annotations": []}],
        }
    ],
    "usage": {
        "input_tokens": 5,
        "output_tokens": 1,
        "total_tokens": 6,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens_details": {"reasoning_tokens": 0},
    },
}


def openai_client(received: Received, payload: dict[str, Any] = RESPONSES_PAYLOAD) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key="sk-test-secret",
        base_url="https://user:pass@models.example/v1",
        http_client=httpx.AsyncClient(transport=transport(payload, received)),
    )


async def test_openai_target_builds_responses_requests() -> None:
    received: Received = []
    target = OpenAITarget(
        "gpt-test",
        temperature=0.7,
        options={"reasoning": {"effort": "low"}},
        client=openai_client(received),
    )
    output = await target.invoke(REQUEST)
    sent = body(received[0])
    assert received[0].url.path == "/v1/responses"
    assert sent == {
        "model": "gpt-test",
        "input": [{"role": "user", "content": "2+2?"}],
        "instructions": "Be brief.",
        "temperature": 0.7,
        "store": False,
        "reasoning": {"effort": "low"},
    }
    assert output.text == "4"
    assert output.metadata == {
        "model": "gpt-test-2026-01-01",
        "stop_reason": "completed",
        "response_id": "resp_1",
    }
    assert output.usage is not None
    assert (output.usage.input_tokens, output.usage.output_tokens) == (5, 1)
    assert target.identity.parameters["endpoint"] == "https://models.example/v1/"
    assert_no_secrets(target)
    for leaked in ("user", "pass"):
        assert leaked not in target.identity.model_dump_json()


async def test_openai_target_reports_incomplete_responses_and_sends_conversations() -> None:
    received: Received = []
    payload = {
        **RESPONSES_PAYLOAD,
        "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
    }
    target = OpenAITarget("gpt-test", max_tokens=16, client=openai_client(received, payload))
    output = await target.invoke(CONVERSATION)
    sent = body(received[0])
    assert [message["role"] for message in sent["input"]] == ["user", "assistant", "user"]
    assert sent["max_output_tokens"] == 16
    assert "temperature" not in sent
    assert "instructions" not in sent
    assert output.metadata["stop_reason"] == "max_output_tokens"


def test_provider_fingerprints_track_behavioral_configuration() -> None:
    client = openai_client([])
    base = OpenAITarget("gpt-test", client=client).identity.fingerprint
    variants = [
        OpenAITarget("gpt-other", client=client),
        OpenAITarget("gpt-test", temperature=0.0, client=client),
        OpenAITarget("gpt-test", options={"reasoning": {"effort": "high"}}, client=client),
        OpenAITarget("gpt-test", version="2", client=client),
    ]
    assert all(target.identity.fingerprint != base for target in variants)
    assert OpenAITarget("gpt-test", client=client).identity.fingerprint == base


class StaticCredential:
    def get_token(self, *scopes: str, **kwargs: object) -> AccessToken:
        assert scopes == (azure_module.SCOPE,)
        return AccessToken("azure-secret-token", 4_102_444_800)


@pytest.fixture
def azure_transport(monkeypatch: pytest.MonkeyPatch) -> Received:
    received: Received = []
    client = httpx.AsyncClient(transport=transport(RESPONSES_PAYLOAD, received))
    monkeypatch.setattr(
        azure_module, "AsyncOpenAI", functools.partial(AsyncOpenAI, http_client=client)
    )
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    return received


async def test_azure_target_uses_v1_endpoint_with_api_key_from_environment(
    azure_transport: Received, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://contoso.openai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-secret-key")
    target = AzureOpenAITarget("my-deployment", temperature=0.2)
    output = await target.invoke(REQUEST)
    request = azure_transport[0]
    assert str(request.url) == "https://contoso.openai.azure.com/openai/v1/responses"
    assert request.headers["authorization"] == "Bearer azure-secret-key"
    assert body(request)["model"] == "my-deployment"
    assert output.text == "4"
    assert target.identity.name == "azure:my-deployment"
    assert target.identity.parameters["endpoint"] == "https://contoso.openai.azure.com/openai/v1/"
    assert_no_secrets(target)


async def test_azure_target_authenticates_with_entra_id_credentials(
    azure_transport: Received,
) -> None:
    target = AzureOpenAITarget(
        "my-deployment",
        endpoint="https://contoso.services.ai.azure.com/openai/v1",
        credential=StaticCredential(),
    )
    await target.invoke(REQUEST)
    request = azure_transport[0]
    assert str(request.url) == "https://contoso.services.ai.azure.com/openai/v1/responses"
    assert request.headers["authorization"] == "Bearer azure-secret-token"
    assert_no_secrets(target)


def test_azure_target_requires_an_endpoint(azure_transport: Received) -> None:
    with pytest.raises(ValueError, match="AZURE_OPENAI_ENDPOINT"):
        AzureOpenAITarget("my-deployment")


async def test_anthropic_target_builds_messages_requests() -> None:
    received: Received = []
    payload = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-test-1",
        "content": [
            {"type": "thinking", "thinking": "Adding.", "signature": "sig"},
            {"type": "text", "text": "Four"},
            {"type": "text", "text": "."},
        ],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 9, "output_tokens": 2},
    }
    client = AsyncAnthropic(
        api_key="sk-test-secret",
        http_client=httpx.AsyncClient(transport=transport(payload, received)),
    )
    target = AnthropicTarget(
        "claude-test",
        max_tokens=64,
        options={"top_k": 5},
        client=client,
    )
    output = await target.invoke(REQUEST)
    assert body(received[0]) == {
        "model": "claude-test",
        "max_tokens": 64,
        "messages": [{"role": "user", "content": "2+2?"}],
        "system": "Be brief.",
        "top_k": 5,
    }
    assert output.text == "Four."
    assert output.metadata == {
        "model": "claude-test-1",
        "stop_reason": "end_turn",
        "response_id": "msg_1",
    }
    assert output.usage is not None
    assert (output.usage.input_tokens, output.usage.output_tokens) == (9, 2)
    assert_no_secrets(target)


OLLAMA_PAYLOAD: dict[str, Any] = {
    "model": "qwen-test:14b",
    "created_at": "2026-01-01T00:00:00Z",
    "message": {"role": "assistant", "content": "Four.", "thinking": "Adding."},
    "done": True,
    "done_reason": "stop",
    "prompt_eval_count": 9,
    "eval_count": 2,
}


def ollama_client(received: list[ollama_http.Request]) -> AsyncClient:
    def respond(request: ollama_http.Request) -> ollama_http.Response:
        received.append(request)
        return ollama_http.Response(200, json=OLLAMA_PAYLOAD)

    return AsyncClient("models.local:11434", transport=ollama_http.MockTransport(respond))


async def test_ollama_target_builds_chat_requests() -> None:
    received: list[ollama_http.Request] = []
    target = OllamaTarget(
        "qwen-test:14b",
        temperature=0.5,
        max_tokens=64,
        think=False,
        options={"num_ctx": 4096},
        client=ollama_client(received),
    )
    output = await target.invoke(CONVERSATION.model_copy(update={"prompt": REQUEST.prompt}))
    sent = json.loads(received[0].content)
    assert str(received[0].url) == "http://models.local:11434/api/chat"
    assert sent["messages"] == [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": "2+2?"},
    ]
    assert sent["think"] is False
    assert sent["options"] == {"seed": 1, "temperature": 0.5, "num_predict": 64, "num_ctx": 4096}
    assert output.text == "Four."
    assert output.metadata == {"model": "qwen-test:14b", "stop_reason": "stop"}
    assert output.usage is not None
    assert (output.usage.input_tokens, output.usage.output_tokens) == (9, 2)


async def test_ollama_target_sends_conversations_and_keeps_the_model_default() -> None:
    received: list[ollama_http.Request] = []
    target = OllamaTarget("qwen-test:14b", client=ollama_client(received))
    await target.invoke(CONVERSATION)
    sent = json.loads(received[0].content)
    assert [message["role"] for message in sent["messages"]] == ["user", "assistant", "user"]
    assert "think" not in sent
    assert sent["options"] == {"seed": 1}
    assert target.identity.parameters == {"model": "qwen-test:14b", "think": None, "options": {}}
    assert OllamaTarget("qwen-test:14b", think=False).identity != target.identity


GEMINI_PAYLOAD: dict[str, Any] = {
    "candidates": [
        {"content": {"role": "model", "parts": [{"text": "4"}]}, "finishReason": "MAX_TOKENS"}
    ],
    "usageMetadata": {
        "promptTokenCount": 7,
        "candidatesTokenCount": 1,
        "thoughtsTokenCount": 3,
        "totalTokenCount": 11,
    },
    "modelVersion": "gemini-test-001",
    "responseId": "gem-1",
}


async def test_google_target_builds_generate_content_requests() -> None:
    received: Received = []
    client = genai.Client(
        api_key="goog-secret",
        http_options=types.HttpOptions(
            httpx_async_client=httpx.AsyncClient(transport=transport(GEMINI_PAYLOAD, received))
        ),
    )
    target = GoogleGenAITarget(
        "gemini-test",
        temperature=0.2,
        max_tokens=32,
        options={"top_k": 40},
        client=client,
    )
    output = await target.invoke(REQUEST)
    request = received[0]
    sent = body(request)
    assert request.url.path.endswith("/models/gemini-test:generateContent")
    assert sent["contents"] == [{"role": "user", "parts": [{"text": "2+2?"}]}]
    assert sent["systemInstruction"]["parts"] == [{"text": "Be brief."}]
    assert sent["generationConfig"] == {
        "temperature": 0.2,
        "maxOutputTokens": 32,
        "topK": 40,
        "seed": 7,
    }
    assert output.text == "4"
    assert output.metadata == {
        "model": "gemini-test-001",
        "stop_reason": "MAX_TOKENS",
        "response_id": "gem-1",
    }
    assert output.usage is not None
    assert (output.usage.input_tokens, output.usage.output_tokens) == (7, 4)
    assert target.identity.parameters["backend"] == "gemini-api"
    assert_no_secrets(target)
    await target.invoke(CONVERSATION)
    followup = body(received[1])
    assert [content["role"] for content in followup["contents"]] == ["user", "model", "user"]
    assert "systemInstruction" not in followup


CONVERSE_RESPONSE: dict[str, Any] = {
    "output": {
        "message": {
            "role": "assistant",
            "content": [
                {"reasoningContent": {"reasoningText": {"text": "Adding."}}},
                {"text": "4"},
            ],
        }
    },
    "stopReason": "end_turn",
    "usage": {"inputTokens": 12, "outputTokens": 1, "totalTokens": 13},
    "metrics": {"latencyMs": 321},
    "trace": {"promptRouter": {"invokedModelId": "arn:aws:bedrock:us-east-1::routed"}},
    "ResponseMetadata": {"RequestId": "req-123", "HTTPStatusCode": 200, "HTTPHeaders": {}},
}


@pytest.fixture
def aws_session() -> boto3.Session:
    return boto3.Session(
        aws_access_key_id="AKIDSECRET",
        aws_secret_access_key="aws-secret-value",
        region_name="eu-west-1",
    )


@pytest.fixture
def bedrock(aws_session: boto3.Session) -> BedrockRuntimeClient:
    return aws_session.client("bedrock-runtime")


async def test_bedrock_target_builds_converse_requests(bedrock: BedrockRuntimeClient) -> None:
    target = BedrockTarget(
        "anthropic.test-model-v1:0",
        temperature=0.3,
        max_tokens=50,
        top_p=0.9,
        options={"additionalModelRequestFields": {"top_k": 50}},
        client=bedrock,
    )
    with Stubber(bedrock) as stubber:
        stubber.add_response(
            "converse",
            CONVERSE_RESPONSE,
            {
                "modelId": "anthropic.test-model-v1:0",
                "messages": [{"role": "user", "content": [{"text": "2+2?"}]}],
                "system": [{"text": "Be brief."}],
                "inferenceConfig": {"temperature": 0.3, "maxTokens": 50, "topP": 0.9},
                "additionalModelRequestFields": {"top_k": 50},
            },
        )
        output = await target.invoke(REQUEST)
    assert output.text == "4"
    assert output.metadata == {
        "model": "arn:aws:bedrock:us-east-1::routed",
        "stop_reason": "end_turn",
        "latency_ms": 321,
        "request_id": "req-123",
    }
    assert output.usage is not None
    assert (output.usage.input_tokens, output.usage.output_tokens) == (12, 1)
    assert target.identity.parameters["region"] == "eu-west-1"
    assert "HTTPHeaders" not in output.model_dump_json()
    assert_no_secrets(target)


def test_bedrock_target_resolves_region_from_argument_or_session(
    aws_session: boto3.Session,
) -> None:
    explicit = BedrockTarget("amazon.test-v1", region="us-east-1", session=aws_session)
    configured = BedrockTarget("amazon.test-v1", session=aws_session)
    assert explicit.identity.parameters["region"] == "us-east-1"
    assert configured.identity.parameters["region"] == "eu-west-1"
    assert explicit.identity.fingerprint != configured.identity.fingerprint


async def test_bedrock_target_omits_unset_parameters(bedrock: BedrockRuntimeClient) -> None:
    target = BedrockTarget("amazon.test-v1", client=bedrock)
    response = {key: CONVERSE_RESPONSE[key] for key in ("output", "stopReason", "usage", "metrics")}
    with Stubber(bedrock) as stubber:
        stubber.add_response(
            "converse",
            response,
            {
                "modelId": "amazon.test-v1",
                "messages": [{"role": "user", "content": [{"text": "2+2?"}]}],
            },
        )
        output = await target.invoke(BARE)
    assert output.metadata["model"] == "amazon.test-v1"
    assert output.metadata["request_id"] is None


async def test_bedrock_errors_become_redacted_observations(
    bedrock: BedrockRuntimeClient,
) -> None:
    target = BedrockTarget("amazon.test-v1", client=bedrock)
    space = TaskSpace(
        cases=probe_cases(1), axes=[Axis(Probe.level, (0,), via=set_level, scale="numeric")]
    )
    experiment = Experiment(
        task_space=space,
        targets=[target],
        execution=ExecutionConfig(retry=RetryPolicy(max_attempts=1)),
    )
    with Stubber(bedrock) as stubber:
        stubber.add_client_error("converse", "ThrottlingException", "Too many requests.", 429)
        results = await Runner().run(experiment)
    error = results.observations[0].output.error
    assert error is not None
    assert error.type == "ThrottlingException"
    assert "Too many requests." in error.message
    assert "AKIDSECRET" not in results.observations[0].model_dump_json()


def test_bedrock_target_fails_early_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    session = boto3.Session(region_name="us-east-1")
    monkeypatch.setattr(session, "get_credentials", lambda: None)
    with pytest.raises(RuntimeError, match="no AWS credentials"):
        BedrockTarget("amazon.test-v1", session=session)


PROVIDERS = {
    "BedrockTarget": ("bedrock", "boto3", "aws"),
    "OpenAITarget": ("openai_responses", "openai", "openai"),
    "AzureOpenAITarget": ("azure_openai", "azure.identity", "azure"),
    "GoogleGenAITarget": ("google_genai", "google.genai", "google"),
    "AnthropicTarget": ("anthropic_messages", "anthropic", "anthropic"),
    "OllamaTarget": ("ollama_chat", "ollama", "ollama"),
}


def run_isolated(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False, timeout=60
    )


BLOCK = (
    "import sys\n"
    "blocked = ('boto3', 'botocore', 'openai', 'anthropic', 'google.genai', 'azure.identity', "
    "'ollama')\n"
    "for name in blocked:\n"
    "    sys.modules[name] = None\n"
)


async def test_provider_targets_close_their_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    openai, azure = openai_client([]), openai_client([])
    anthropic = AsyncAnthropic(api_key="sk-test-secret")
    gemini = genai.Client(api_key="goog-secret")
    ollama = OllamaTarget("qwen-test", client=ollama_client([]))
    closed: list[str] = []

    async def aclose() -> None:
        closed.append("google")

    monkeypatch.setattr(gemini.aio, "aclose", aclose)
    for item in (
        OpenAITarget("gpt-test", client=openai),
        AzureOpenAITarget("gpt-test", client=azure),
        AnthropicTarget("claude-test", client=anthropic),
        GoogleGenAITarget("gemini-test", client=gemini),
        ollama,
    ):
        await item.aclose()
    assert (openai.is_closed(), azure.is_closed(), anthropic.is_closed()) == (True, True, True)
    assert closed == ["google"]
    with pytest.raises(RuntimeError, match="closed"):
        await ollama.invoke(REQUEST)


def test_core_imports_without_provider_sdks() -> None:
    result = run_isolated(
        BLOCK + "import modelscape, modelscape.targets, modelscape.execution, modelscape.analysis\n"
        "from modelscape.targets import CallableTarget, Target\n"
        "print('ok')\n"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


@pytest.mark.parametrize("target", sorted(PROVIDERS))
def test_provider_targets_explain_missing_extras(target: str) -> None:
    module, _, extra = PROVIDERS[target]
    for statement in (
        f"from modelscape.targets import {target}",
        f"import modelscape.targets.{module}",
    ):
        result = run_isolated(BLOCK + statement)
        assert result.returncode != 0
        assert f'uv add "modelscape[{extra}]"' in result.stderr.splitlines()[-1]


def test_provider_targets_satisfy_the_target_protocol(aws_session: boto3.Session) -> None:
    targets: list[Target] = [
        BedrockTarget("amazon.test-v1", session=aws_session),
        OpenAITarget("gpt-test", client=openai_client([])),
        AnthropicTarget("claude-test", client=AsyncAnthropic(api_key="sk-test-secret")),
        GoogleGenAITarget("gemini-test", client=genai.Client(api_key="goog-secret")),
        OllamaTarget("qwen-test:14b", client=ollama_client([])),
    ]
    assert [target.identity.name for target in targets] == [
        "bedrock:amazon.test-v1",
        "openai:gpt-test",
        "anthropic:claude-test",
        "google:gemini-test",
        "ollama:qwen-test:14b",
    ]
    for target in targets:
        assert_no_secrets(target)


def test_unknown_target_names_are_attribute_errors() -> None:
    name = "MissingTarget"
    with pytest.raises(AttributeError, match=f"has no attribute '{name}'"):
        getattr(targets, name)
