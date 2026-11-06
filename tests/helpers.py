from __future__ import annotations

import json
import random
from collections.abc import Mapping, Sequence
from typing import Literal, cast

from modelscape import (
    Axis,
    ExecutionConfig,
    RetryPolicy,
    Task,
    TaskSpace,
    attribute,
    perturbation,
)
from modelscape.targets import CallableTarget, TargetRequest

FAST = ExecutionConfig(concurrency=4, timeout_seconds=5, retry=RetryPolicy(max_attempts=1))


class Probe(Task):
    question: str
    intensity: int = 0
    tone: Literal["plain", "formal"] = "plain"
    notes: tuple[str, ...] = ()

    @attribute
    def level(self) -> int:
        """How intense the probe is."""
        return self.intensity

    @attribute
    def style(self) -> str:
        return self.tone

    @attribute
    def note_count(self) -> int:
        return len(self.notes)

    def reference(self) -> str:
        return "stable"


@perturbation
def set_level(task: Probe, level: int) -> Probe:
    return task.replace(intensity=level)


@perturbation
def set_style(task: Probe, style: str) -> Probe:
    return task.replace(tone=style)


@perturbation
def set_notes(task: Probe, count: int) -> Probe:
    return task.replace(notes=tuple(f"note {index}" for index in range(count)))


def probe_cases(count: int = 3) -> dict[str, Probe]:
    return {f"case-{index}": Probe(question=f"question {index}") for index in range(count)}


def level_space(
    cases: Mapping[str, Probe] | None = None, levels: Sequence[int] = (0, 1, 2, 3)
) -> TaskSpace[Probe]:
    return TaskSpace(
        cases=cases or probe_cases(),
        axes=[
            Axis(Probe.level, levels, via=set_level, scale="numeric"),
            Axis(Probe.style, ("plain", "formal"), via=set_style, scale="nominal"),
        ],
    )


def payload(request: TargetRequest) -> dict[str, object]:
    return cast(dict[str, object], json.loads(request.prompt.last))


def level(request: TargetRequest) -> int:
    value = payload(request)["intensity"]
    return value if isinstance(value, int) else 0


def case_index(request: TargetRequest) -> int:
    return int(str(payload(request)["question"]).split()[-1])


def threshold_answer(request: TargetRequest) -> str:
    return "shifted output" if level(request) >= 2 else "stable"


def threshold_target(name: str = "threshold") -> CallableTarget:
    return CallableTarget(threshold_answer, name=name)


def noisy_threshold_target(name: str = "noisy", threshold: int = 2) -> CallableTarget:
    def answer(request: TargetRequest) -> str:
        rng = random.Random(request.seed)
        word = "changed" if level(request) >= threshold else "stable"
        return f"{word} answer{rng.choice(['', ' indeed'])}"

    return CallableTarget(answer, name=name, parameters={"threshold": threshold})
