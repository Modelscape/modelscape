from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import Field, JsonValue

from modelscape.core.coordinates import AxisValue, Coordinate
from modelscape.core.identity import Identity
from modelscape.core.observations import Prompt
from modelscape.core.serialization import FrozenModel, JsonObject, content_hash, stable_id


class AttributeSchema(FrozenModel):
    name: str
    type: str
    description: str | None = None


class TaskSchema(FrozenModel):
    """A machine-readable description of a task language.

    ``structure`` is the JSON Schema of valid tasks, and ``attributes`` lists the properties
    computed from every task: the dimensions a task space can vary.
    """

    name: str
    structure: JsonObject
    attributes: tuple[AttributeSchema, ...]

    @property
    def fingerprint(self) -> str:
        return content_hash(self.model_dump(mode="json"))


class PerturbationStep(FrozenModel):
    """The record of one checked perturbation step.

    ``also_changed`` lists the free attributes that changed together with ``axis``. Every
    other attribute was checked to be unchanged.
    """

    case_id: str
    axis: str
    source: AxisValue
    target: AxisValue
    perturbation: Identity
    changed_paths: tuple[str, ...]
    also_changed: tuple[str, ...]
    parent_hash: str
    content_hash: str


class Variant(FrozenModel):
    """A task at one coordinate, the exact prompt for it, and the steps that produced it."""

    id: str
    case_id: str
    coordinate: Coordinate
    task: JsonObject
    attributes: dict[str, AxisValue]
    reference: JsonValue = None
    prompt: Prompt
    content_hash: str
    steps: tuple[PerturbationStep, ...] = Field(default=())

    @classmethod
    def create(
        cls,
        *,
        case_id: str,
        coordinate: Coordinate,
        task: JsonObject,
        attributes: Mapping[str, AxisValue],
        reference: JsonValue,
        prompt: Prompt,
        steps: Sequence[PerturbationStep],
    ) -> Variant:
        digest = content_hash(task)
        history = tuple(steps)
        identifier = stable_id(
            {
                "case_id": case_id,
                "coordinate": dict(coordinate),
                "content_hash": digest,
                "prompt": prompt.model_dump(mode="json"),
                "steps": [step.model_dump(mode="json") for step in history],
            }
        )
        return cls(
            id=identifier,
            case_id=case_id,
            coordinate=coordinate,
            task=task,
            attributes=dict(attributes),
            reference=reference,
            prompt=prompt,
            content_hash=digest,
            steps=history,
        )

    @property
    def changed_paths(self) -> tuple[str, ...]:
        return tuple(sorted({path for step in self.steps for path in step.changed_paths}))
