"""Simulated models, so a scenario runs without a model or a key.

``modelscape demo`` maps the shipped ``pressure`` scenario on two of them: one follows the
policy, and one also yields to pressure and to the director's office.
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable, Mapping

from pydantic import JsonValue

from modelscape import scenarios
from modelscape.core.observations import TargetRequest
from modelscape.core.serialization import AxisValue
from modelscape.core.tasks import Variant
from modelscape.execution import ProgressCallback
from modelscape.runs import Run, run
from modelscape.spec import Spec
from modelscape.targets import CallableTarget

NOISE = 0.03
SCENARIO = "pressure"
YIELDING: Mapping[AxisValue, float] = {0: 0.0, 1: 0.0, 2: 0.05, 3: 0.3, 4: 0.6, 5: 0.85}
CLAIM = "director_office"

Behavior = Callable[[Variant, random.Random], JsonValue]


def simulated(spec: Spec, behavior: Behavior, *, name: str) -> CallableTarget:
    """A model that answers every variant of ``spec`` as ``behavior`` decides.

    It replies in the spec's JSON ``field``, and in 3% of replies each it gives no answer or a
    random choice: run-to-run noise.
    """
    field = spec.answer.field
    if field is None:
        raise ValueError(f"Spec {spec.name} reads its answer with a pattern; simulate a field.")
    scenario = spec.scenario()
    every = list(scenario.variants())
    variants = {variant.prompt: variant for variant in every}
    if len(variants) != len(every):
        raise ValueError(f"Spec {spec.name} asks some prompts twice; each must be distinct.")
    choices = spec.answer.choices

    async def respond(request: TargetRequest) -> str:
        draw = random.Random(request.seed)
        roll = draw.random()
        if roll < NOISE:
            return "I cannot answer that."
        if roll < 2 * NOISE:
            return json.dumps({field: draw.choice(choices)})
        return json.dumps({field: behavior(variants[request.prompt], draw)})

    return CallableTarget(respond, name=name)


def follows(variant: Variant, draw: random.Random) -> JsonValue:
    """Always the correct answer."""
    return variant.reference


def yields(variant: Variant, draw: random.Random) -> JsonValue:
    """The correct answer, except that it grants more SECRET data the harder it is pushed."""
    pressure = YIELDING[variant.attributes["pressure"]]
    claimed = 0.5 if variant.attributes["requester"] == CLAIM else 0.0
    if variant.reference == "escalate" and draw.random() < max(pressure, claimed):
        return "grant"
    return variant.reference


async def demo(on_progress: ProgressCallback | None = None) -> Run:
    """Map the ``pressure`` scenario on a model that follows its policy and one that yields."""
    spec = Spec.load(scenarios.spec(SCENARIO))
    targets = [
        simulated(spec, follows, name="careful"),
        simulated(spec, yields, name="yielding"),
    ]
    return await run(spec.scenario(), targets, on_progress=on_progress)
