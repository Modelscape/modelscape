"""Targets: the AI systems under evaluation.

Provider targets import their SDK only when first used and each needs its extra, for example
``uv add "modelscape[aws]"`` for ``BedrockTarget``.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from modelscape.core.observations import TargetError, TargetOutput, TargetRequest, Usage
from modelscape.targets.callable import CallableTarget, TargetFunction, TargetResult
from modelscape.targets.protocols import Target

if TYPE_CHECKING:
    from modelscape.targets.anthropic_messages import AnthropicTarget
    from modelscape.targets.azure_openai import AzureOpenAITarget
    from modelscape.targets.bedrock import BedrockTarget
    from modelscape.targets.google_genai import GoogleGenAITarget
    from modelscape.targets.ollama_chat import OllamaTarget
    from modelscape.targets.openai_responses import OpenAITarget

PROVIDERS = {
    "AnthropicTarget": "modelscape.targets.anthropic_messages",
    "AzureOpenAITarget": "modelscape.targets.azure_openai",
    "BedrockTarget": "modelscape.targets.bedrock",
    "GoogleGenAITarget": "modelscape.targets.google_genai",
    "OllamaTarget": "modelscape.targets.ollama_chat",
    "OpenAITarget": "modelscape.targets.openai_responses",
}

__all__ = [
    "AnthropicTarget",
    "AzureOpenAITarget",
    "BedrockTarget",
    "CallableTarget",
    "GoogleGenAITarget",
    "OllamaTarget",
    "OpenAITarget",
    "Target",
    "TargetError",
    "TargetFunction",
    "TargetOutput",
    "TargetRequest",
    "TargetResult",
    "Usage",
]


def __getattr__(name: str) -> object:
    if name in PROVIDERS:
        return getattr(import_module(PROVIDERS[name]), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
