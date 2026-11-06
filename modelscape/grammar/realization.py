from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import KW_ONLY, dataclass, field
from typing import Generic, Protocol, TypeVar, overload

from pydantic import JsonValue

from modelscape.core.identity import Identity
from modelscape.core.observations import Prompt
from modelscape.grammar.task import Task

TaskT = TypeVar("TaskT", bound=Task)
TaskT_contra = TypeVar("TaskT_contra", bound=Task, contravariant=True)


class Realizer(Protocol[TaskT_contra]):
    """Turns a structured task into the exact prompt a target receives.

    The prompt belongs to the task, not to the model: every target receives the same prompt
    for the same variant, and that prompt is stored with the variant.
    """

    @property
    def identity(self) -> Identity: ...

    def realize(self, task: TaskT_contra) -> Prompt: ...


@dataclass(frozen=True)
class FunctionRealizer(Generic[TaskT]):
    """A realizer defined by a function returning a prompt or the text of one user message."""

    function: Callable[[TaskT], Prompt | str]
    _: KW_ONLY
    name: str
    version: str = "1"
    system: str | None = None
    parameters: Mapping[str, JsonValue] = field(default_factory=dict[str, JsonValue])

    @property
    def identity(self) -> Identity:
        return Identity(
            name=self.name,
            version=self.version,
            parameters={**self.parameters, "system": self.system},
        )

    def realize(self, task: TaskT) -> Prompt:
        produced = self.function(task)
        if isinstance(produced, Prompt):
            return produced
        return Prompt.of(produced, system=self.system)


@dataclass(frozen=True)
class JsonRealizer:
    """The default realizer: the task content as indented JSON."""

    system: str | None = None

    @property
    def identity(self) -> Identity:
        return Identity(name="json", parameters={"system": self.system})

    def realize(self, task: Task) -> Prompt:
        text = json.dumps(task.content(), indent=2, ensure_ascii=False)
        return Prompt.of(text, system=self.system)


@overload
def realizer(function: Callable[[TaskT], Prompt | str], /) -> FunctionRealizer[TaskT]: ...


@overload
def realizer(
    *,
    name: str | None = None,
    version: str = "1",
    system: str | None = None,
    parameters: Mapping[str, JsonValue] | None = None,
) -> Callable[[Callable[[TaskT], Prompt | str]], FunctionRealizer[TaskT]]: ...


def realizer(
    function: Callable[[TaskT], Prompt | str] | None = None,
    /,
    *,
    name: str | None = None,
    version: str = "1",
    system: str | None = None,
    parameters: Mapping[str, JsonValue] | None = None,
) -> FunctionRealizer[TaskT] | Callable[[Callable[[TaskT], Prompt | str]], FunctionRealizer[TaskT]]:
    """Declare a function ``task -> prompt`` as a realizer.

    Change ``version`` whenever the wording changes. ``system`` is sent as the system
    instruction when the function returns plain text.
    """

    def wrap(inner: Callable[[TaskT], Prompt | str]) -> FunctionRealizer[TaskT]:
        return FunctionRealizer(
            inner,
            name=name or inner.__name__,
            version=version,
            system=system,
            parameters=dict(parameters or {}),
        )

    return wrap if function is None else wrap(function)
