from __future__ import annotations

import inspect
import math
from collections.abc import Callable, Mapping
from functools import cache
from typing import Any, Generic, Self, TypeVar, cast, overload

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError

from modelscape.core.errors import SchemaError
from modelscape.core.serialization import AxisValue, JsonObject, content_hash
from modelscape.core.tasks import AttributeSchema, TaskSchema

TaskT = TypeVar("TaskT", bound="Task")
ValueT = TypeVar("ValueT", bound=AxisValue)


class Attribute(Generic[TaskT, ValueT]):
    """A property computed from a task, such as its number of evidence items.

    Attributes are the dimensions a task space can vary. Read on a task, an attribute returns
    its value; read on the task class, it returns the attribute itself, which is how an
    ``Axis`` refers to it.
    """

    __slots__ = ("_function", "description", "name")

    def __init__(self, function: Callable[[TaskT], ValueT]) -> None:
        self._function = function
        self.name: str = function.__name__
        self.description: str | None = inspect.getdoc(function)

    def __repr__(self) -> str:
        return f"Attribute({self.name!r})"

    def __set_name__(self, owner: type[Any], name: str) -> None:
        self.name = name

    @overload
    def __get__(self, instance: None, owner: type[Any]) -> Self: ...

    @overload
    def __get__(self, instance: TaskT, owner: type[Any]) -> ValueT: ...

    def __get__(self, instance: TaskT | None, owner: type[Any]) -> Self | ValueT:
        if instance is None:
            return self
        return self.of(instance)

    @property
    def type_name(self) -> str:
        annotation = inspect.get_annotations(self._function).get("return", "")
        return annotation if isinstance(annotation, str) else annotation.__name__

    def of(self, task: TaskT) -> ValueT:
        value = self._function(task)
        self._check(task, value)
        return value

    def _check(self, task: Task, value: object) -> None:
        if not isinstance(value, (bool, int, float, str)):
            raise SchemaError(
                f"Attribute '{self.name}' of {type(task).__name__} must be a bool, int, float, "
                f"or str, got {type(value).__name__}."
            )
        if isinstance(value, float) and not math.isfinite(value):
            raise SchemaError(f"Attribute '{self.name}' of {type(task).__name__} is not finite.")


def attribute(function: Callable[[TaskT], ValueT]) -> Attribute[TaskT, ValueT]:
    """Declare a task property that axes can vary and perturbations must keep fixed."""
    return Attribute(function)


class Node(BaseModel):
    """An immutable component of a task, such as a piece of evidence or a hypothesis."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Task(BaseModel):
    """A task, written in a task language you define.

    A subclass defines the language: typed fields and validators decide which tasks are
    valid, ``@attribute`` methods compute the properties that can be varied, and ``reference``
    gives the correct answer when there is one. The language is named after its class, not its
    module, so moving the code keeps every stored record valid.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", ignored_types=(Attribute,))

    @classmethod
    def describe(cls) -> TaskSchema:
        return TaskSchema(
            name=cls.__qualname__,
            structure=cls.model_json_schema(),
            attributes=tuple(
                AttributeSchema(name=name, type=item.type_name, description=item.description)
                for name, item in attributes_of(cls).items()
            ),
        )

    def attributes(self) -> dict[str, AxisValue]:
        return {name: item.of(self) for name, item in attributes_of(type(self)).items()}

    def reference(self) -> JsonValue:
        return None

    def content(self) -> JsonObject:
        return self.model_dump(mode="json")

    @property
    def fingerprint(self) -> str:
        return content_hash(self.content())

    def replace(self, **changes: object) -> Self:
        return parse(type(self), {**dict(self), **changes})


@cache
def attributes_of(schema: type[Task]) -> Mapping[str, Attribute[Any, Any]]:
    return {
        name: cast(Attribute[Any, Any], value)
        for owner in reversed(schema.__mro__)
        for name, value in vars(owner).items()
        if isinstance(value, Attribute)
    }


def parse(schema: type[TaskT], content: object) -> TaskT:
    try:
        return schema.model_validate(content)
    except ValidationError as error:
        raise SchemaError(f"Not a valid {schema.__name__}: {error}") from error
