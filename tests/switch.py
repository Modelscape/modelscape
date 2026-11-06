from __future__ import annotations

import json
import random
from collections.abc import Callable
from dataclasses import replace
from typing import Literal, cast

from modelscape import Axis, Results, Runner, Scenario, Task, TaskSpace, attribute, perturbation
from modelscape.report import Report
from modelscape.storage import MemoryStore
from modelscape.targets import CallableTarget, Target, TargetRequest
from tests.helpers import FAST


class Switch(Task):
    case: str
    level: int = 0
    tone: Literal["plain", "formal"] = "plain"

    @attribute
    def strength(self) -> int:
        return self.level

    @attribute
    def style(self) -> str:
        return self.tone

    def reference(self) -> str:
        return "high" if self.level >= 2 else "low"


@perturbation
def set_level(task: Switch, level: int) -> Switch:
    return task.replace(level=level)


@perturbation
def set_tone(task: Switch, tone: str) -> Switch:
    return task.replace(tone=tone)


SCENARIO = Scenario(
    name="switch",
    version="1",
    description="A causal level and an invariant tone.",
    task_space=TaskSpace(
        cases={f"c{index}": Switch(case=f"c{index}") for index in range(3)},
        axes=[
            Axis(Switch.strength, (0, 1, 2, 3), via=set_level, scale="numeric"),
            Axis(Switch.style, ("plain", "formal"), via=set_tone, scale="nominal"),
        ],
    ),
    answer=lambda output: output.as_text() or None,
    repetitions=4,
    groups={"first": ["c0"]},
)


SPACE = SCENARIO.task_space
NOISY = replace(
    SCENARIO,
    repetitions=8,
    task_space=TaskSpace(
        cases={f"c{index}": Switch(case=f"c{index}") for index in range(6)},
        axes=SPACE.axes,
    ),
    groups={},
)


def correct(task: dict[str, object]) -> str:
    return "high" if cast(int, task["level"]) >= 2 else "low"


def late(task: dict[str, object]) -> str:
    return "high" if cast(int, task["level"]) >= 3 else "low"


def stubborn(task: dict[str, object]) -> str:
    return "low"


def swayed(task: dict[str, object]) -> str:
    return "high" if task["tone"] == "formal" else correct(task)


def noisy(rule: Callable[[dict[str, object]], str], name: str) -> Target:
    def answer(request: TargetRequest) -> str:
        right = rule(cast(dict[str, object], json.loads(request.prompt.last)))
        wrong = "low" if right == "high" else "high"
        return wrong if random.Random(request.seed).random() < 0.25 else right

    return CallableTarget(answer, name=name)


def model(
    rule: Callable[[dict[str, object]], str], name: str, calls: list[str] | None = None
) -> Target:
    def answer(request: TargetRequest) -> str:
        if calls is not None:
            calls.append(name)
        return rule(cast(dict[str, object], json.loads(request.prompt.last)))

    return CallableTarget(answer, name=name)


async def mapped(
    *targets: Target, scenario: Scenario = SCENARIO, store: MemoryStore | None = None
) -> tuple[Results, Report]:
    results = await Runner(store=store).run(scenario.experiment(targets, FAST))
    return results, scenario.report(results)
