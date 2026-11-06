from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, JsonValue

from modelscape.core.coordinates import Coordinate
from modelscape.core.identity import Identity
from modelscape.core.serialization import FrozenModel, JsonObject, canonical_json, stable_id

SEED_MASK = 0x7FFFFFFF


class Message(FrozenModel):
    """One turn of a conversation."""

    role: Literal["user", "assistant"]
    content: str


class Prompt(FrozenModel):
    """The exact text a target receives: an optional system instruction and a conversation."""

    system: str | None = None
    messages: tuple[Message, ...] = Field(min_length=1)

    @classmethod
    def of(cls, user: str, *, system: str | None = None) -> Prompt:
        return cls(system=system, messages=(Message(role="user", content=user),))

    @property
    def last(self) -> str:
        return self.messages[-1].content


class TargetRequest(FrozenModel):
    """What a target receives: the prompt only, never the task, coordinate, or step history.

    ``seed`` is a hint derived from the observation's id. Providers may ignore it or honor it
    only partly, so no analysis assumes a seed makes outputs reproducible. Repetitions measure
    run-to-run variation either way.
    """

    prompt: Prompt
    repetition: int = Field(ge=0)
    seed: int = Field(ge=0)


class Usage(FrozenModel):
    """Tokens and cost of one invocation, as far as the provider reports them."""

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cost: float | None = Field(default=None, ge=0)


class TargetError(FrozenModel):
    """Why an invocation failed after its retries."""

    type: str
    message: str


class TargetOutput(FrozenModel):
    """One invocation result. Model output is untrusted data and is never executed or rendered."""

    text: str | None = None
    structured: JsonValue = None
    metadata: JsonObject = Field(default_factory=dict)
    usage: Usage | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    error: TargetError | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None

    def as_text(self) -> str:
        if self.text is not None:
            return self.text
        if self.structured is None:
            return ""
        return canonical_json(self.structured)


class Observation(FrozenModel):
    """One repetition of one target on one variant.

    ``schedule_position`` is the observation's place in the randomized run order, and
    ``started_at`` and ``completed_at`` record when it ran. None of these are part of its id.
    """

    id: str
    variant_id: str
    case_id: str
    coordinate: Coordinate
    target: Identity
    repetition: int = Field(ge=0)
    seed: int = Field(ge=0)
    output: TargetOutput
    attempts: int = Field(ge=1)
    schedule_position: int = Field(ge=0)
    started_at: datetime
    completed_at: datetime

    @property
    def succeeded(self) -> bool:
        return self.output.succeeded


def observation_id(variant_id: str, target_fingerprint: str, repetition: int, seed: int) -> str:
    """The id of an observation; the same inputs always give the same id, so reruns reuse it."""
    return stable_id(
        {
            "variant_id": variant_id,
            "target": target_fingerprint,
            "repetition": repetition,
            "seed": seed,
        }
    )


def request_seed(observation: str) -> int:
    return int(observation[:8], 16) & SEED_MASK
