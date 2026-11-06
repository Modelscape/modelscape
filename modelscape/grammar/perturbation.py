from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import KW_ONLY, dataclass, field
from typing import Generic, Protocol, TypeVar, overload

from pydantic import JsonValue

from modelscape.core.coordinates import same_value
from modelscape.core.errors import ControlViolationError, ModelscapeError, PerturbationError
from modelscape.core.identity import Identity
from modelscape.core.serialization import AxisValue
from modelscape.core.tasks import PerturbationStep
from modelscape.grammar.diff import structural_diff
from modelscape.grammar.task import Task, parse

TaskT = TypeVar("TaskT", bound=Task)
ValueT = TypeVar("ValueT", bound=AxisValue)
ValueT_contra = TypeVar("ValueT_contra", bound=AxisValue, contravariant=True)


class Perturbation(Protocol[TaskT, ValueT_contra]):
    """A deterministic change that moves a task to a given value of one attribute.

    Every other attribute must keep its value, except those listed in ``free``: attributes
    that are allowed to change along with it. Those changes are recorded.
    """

    @property
    def identity(self) -> Identity: ...

    @property
    def free(self) -> frozenset[str]: ...

    def apply(self, task: TaskT, value: ValueT_contra) -> TaskT: ...


@dataclass(frozen=True)
class FunctionPerturbation(Generic[TaskT, ValueT]):
    """A perturbation defined by a deterministic function of a task and a target value."""

    function: Callable[[TaskT, ValueT], TaskT]
    _: KW_ONLY
    name: str
    version: str = "1"
    free: frozenset[str] = frozenset()
    parameters: Mapping[str, JsonValue] = field(default_factory=dict[str, JsonValue])

    @property
    def identity(self) -> Identity:
        return Identity(
            name=self.name,
            version=self.version,
            parameters={**self.parameters, "free": list[JsonValue](sorted(self.free))},
        )

    def apply(self, task: TaskT, value: ValueT) -> TaskT:
        return self.function(task, value)


@overload
def perturbation(
    function: Callable[[TaskT, ValueT], TaskT], /
) -> FunctionPerturbation[TaskT, ValueT]: ...


@overload
def perturbation(
    *,
    name: str | None = None,
    version: str = "1",
    free: Iterable[str] = (),
    parameters: Mapping[str, JsonValue] | None = None,
) -> Callable[[Callable[[TaskT, ValueT], TaskT]], FunctionPerturbation[TaskT, ValueT]]: ...


def perturbation(
    function: Callable[[TaskT, ValueT], TaskT] | None = None,
    /,
    *,
    name: str | None = None,
    version: str = "1",
    free: Iterable[str] = (),
    parameters: Mapping[str, JsonValue] | None = None,
) -> (
    FunctionPerturbation[TaskT, ValueT]
    | Callable[[Callable[[TaskT, ValueT], TaskT]], FunctionPerturbation[TaskT, ValueT]]
):
    """Declare a function ``(task, value) -> task`` as a perturbation.

    Change ``version`` whenever the function's behavior changes. ``free`` lists the attributes
    that may change along with the one the function sets.
    """

    def wrap(inner: Callable[[TaskT, ValueT], TaskT]) -> FunctionPerturbation[TaskT, ValueT]:
        return FunctionPerturbation(
            inner,
            name=name or inner.__name__,
            version=version,
            free=frozenset(free),
            parameters=dict(parameters or {}),
        )

    return wrap if function is None else wrap(function)


def perturb(
    rewrite: Perturbation[TaskT, ValueT],
    task: TaskT,
    *,
    case_id: str,
    axis: str,
    value: ValueT,
) -> tuple[TaskT, PerturbationStep]:
    """Apply one perturbation and check that it changed only what it should.

    The result must be valid and deterministic, ``axis`` must equal ``value``, and every other
    attribute that is not listed as free must be unchanged.
    """
    name = rewrite.identity.name
    result = _apply(rewrite, task, value, case_id)
    if _apply(rewrite, task, value, case_id) != result:
        raise PerturbationError(
            f"Perturbation '{name}' is not deterministic on case '{case_id}' at {axis}={value!r}."
        )
    before = task.attributes()
    after = result.attributes()
    if not same_value(after[axis], value):
        raise PerturbationError(
            f"Perturbation '{name}' was asked for {axis}={value!r} on case '{case_id}' "
            f"but produced {axis}={after[axis]!r}."
        )
    changed = {
        key: (before[key], after[key])
        for key in before
        if key != axis and not same_value(before[key], after[key])
    }
    uncontrolled = {key: change for key, change in changed.items() if key not in rewrite.free}
    if uncontrolled:
        raise ControlViolationError(name, case_id, uncontrolled)
    return result, PerturbationStep(
        case_id=case_id,
        axis=axis,
        source=before[axis],
        target=value,
        perturbation=rewrite.identity,
        changed_paths=structural_diff(task.content(), result.content()),
        also_changed=tuple(sorted(changed)),
        parent_hash=task.fingerprint,
        content_hash=result.fingerprint,
    )


def _apply(rewrite: Perturbation[TaskT, ValueT], task: TaskT, value: ValueT, case_id: str) -> TaskT:
    name = rewrite.identity.name
    try:
        produced = rewrite.apply(task, value)
    except ModelscapeError:
        raise
    except Exception as error:
        raise PerturbationError(
            f"Perturbation '{name}' failed on case '{case_id}' for value {value!r}: {error}"
        ) from error
    if type(produced) is not type(task):
        raise PerturbationError(
            f"Perturbation '{name}' returned {type(produced).__name__}, "
            f"expected {type(task).__name__}."
        )
    return parse(type(task), produced.model_dump())
