from __future__ import annotations

from collections.abc import Mapping

from modelscape.core.serialization import AxisValue


class ModelscapeError(Exception):
    """Base class for all errors raised by modelscape."""


class SchemaError(ModelscapeError):
    """A task is not valid in its task language."""


class TaskSpaceError(ModelscapeError):
    """A task space, axis, or coordinate is malformed or used inconsistently."""


class PerturbationError(ModelscapeError):
    """A perturbation failed or produced an unacceptable variant."""


class ControlViolationError(PerturbationError):
    """A perturbation changed attributes that had to stay the same."""

    def __init__(
        self,
        perturbation: str,
        case_id: str,
        changes: Mapping[str, tuple[AxisValue, AxisValue]],
    ) -> None:
        self.perturbation = perturbation
        self.case_id = case_id
        self.changes = dict(changes)
        described = ", ".join(
            f"{name} {before!r} -> {after!r}" for name, (before, after) in self.changes.items()
        )
        super().__init__(
            f"Perturbation '{perturbation}' changed attributes that must stay the same in case "
            f"'{case_id}': {described}. If this is intended, list them in free=[...]."
        )


class MeasureError(ModelscapeError):
    """A measure could not be computed for the given observations."""


class SpecError(ModelscapeError):
    """A scenario spec is incomplete or malformed."""


class ScenarioError(ModelscapeError):
    """A scenario could not be found, or does not define a Scenario."""


class RequirementError(ModelscapeError):
    """A report requirement could not be parsed."""


class ReportError(ModelscapeError):
    """A report file could not be read."""


class ExperimentError(ModelscapeError):
    """An experiment specification is invalid."""


class StoreError(ModelscapeError):
    """A store could not persist or load records."""


class AnalysisError(ModelscapeError):
    """Requested analysis is not supported by the available observations."""
