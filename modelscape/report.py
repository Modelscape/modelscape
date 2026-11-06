"""Reports: the scorecards, divergences, and provenance of a scenario run."""

from __future__ import annotations

import os
import platform
from collections.abc import Sequence
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from modelscape.analysis import (
    BoundaryCandidate,
    Divergence,
    Estimate,
    Results,
    Scorecard,
    Threshold,
)
from modelscape.core.errors import ReportError
from modelscape.core.identity import Identity
from modelscape.core.observations import Observation
from modelscape.core.serialization import FrozenModel

Number = TypeVar("Number", int, float)

FORMAT = 1


class TargetProvenance(FrozenModel):
    """One target's identity, the model versions its provider reported, and its usage."""

    identity: Identity
    models: tuple[str, ...]
    observations: int
    failed: int
    input_tokens: int | None
    output_tokens: int | None
    cost: float | None


class Provenance(FrozenModel):
    """The software, times, and targets behind a report."""

    modelscape: str
    python: str
    platform: str
    created_at: datetime
    first_observation: datetime | None
    last_observation: datetime | None
    targets: tuple[TargetProvenance, ...]

    @classmethod
    def of(cls, results: Results) -> Provenance:
        """The provenance of a run."""
        observations = results.observations
        return cls(
            modelscape=version("modelscape"),
            python=platform.python_version(),
            platform=platform.platform(),
            created_at=datetime.now(UTC),
            first_observation=min((item.started_at for item in observations), default=None),
            last_observation=max((item.completed_at for item in observations), default=None),
            targets=tuple(
                _target(identity, [item for item in observations if item.target == identity])
                for identity in results.experiment.targets
            ),
        )


class Report(FrozenModel):
    """Scorecards per target and group, divergences from the first target, and provenance.

    ``format`` is the version of the report file layout, raised when a release changes it.
    """

    format: int = FORMAT
    scenario: Identity
    experiment: str
    scorecards: tuple[Scorecard, ...]
    divergences: tuple[Divergence, ...]
    provenance: Provenance

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> Report:
        """Read a report file written by this or an earlier release."""
        text = Path(path).read_text(encoding="utf-8")
        try:
            found = _Format.model_validate_json(text).format
            if found > FORMAT:
                raise ReportError(
                    f"{path} has report format {found}, but this modelscape reads up to "
                    f"{FORMAT}. Upgrade modelscape to read it."
                )
            return cls.model_validate_json(text)
        except ValidationError as error:
            raise ReportError(f"{path} is not a modelscape report: {error}") from error

    def save(self, path: str | os.PathLike[str]) -> None:
        """Write the report as JSON."""
        Path(path).write_text(self.model_dump_json(indent=2), encoding="utf-8")

    def summary(self) -> str:
        """The report as the command line prints it."""
        lines = [
            f"{self.scenario.name} {self.scenario.version}",
            *(_scorecard(card) for card in self.scorecards),
        ]
        for divergence in self.divergences:
            found = ", ".join(_where(item, None) for item in divergence.candidates) or "nowhere"
            lines.append(
                f"\n{divergence.second} differs from {divergence.first} beyond noise at "
                f"{len(divergence.candidates)} of {len(divergence.contrasts)} coordinates: {found}"
            )
        lines.append(f"\nmodelscape {self.provenance.modelscape}, Python {self.provenance.python}")
        lines.extend(_served(item) for item in self.provenance.targets)
        return "\n".join(lines)


class _Format(BaseModel):
    format: int = FORMAT


def _target(identity: Identity, observations: Sequence[Observation]) -> TargetProvenance:
    outputs = [item.output for item in observations]
    usages = [output.usage for output in outputs if output.usage is not None]
    models = {model for output in outputs if isinstance(model := output.metadata.get("model"), str)}
    return TargetProvenance(
        identity=identity,
        models=tuple(sorted(models)),
        observations=len(outputs),
        failed=sum(not output.succeeded for output in outputs),
        input_tokens=_total([usage.input_tokens for usage in usages]),
        output_tokens=_total([usage.output_tokens for usage in usages]),
        cost=_total([usage.cost for usage in usages]),
    )


def _total(values: Sequence[Number | None]) -> Number | None:
    present = [value for value in values if value is not None]
    return sum(present[1:], present[0]) if present else None


def _scorecard(card: Scorecard) -> str:
    lines = [
        f"\n{card.target}  {card.group} ({len(card.cases)} cases)",
        f"  accuracy {_estimate(card.accuracy)}   answered {_number(card.answered)}   "
        f"spurious change {_number(card.spurious_change)}   "
        f"missed change {_number(card.missed_change)}",
    ]
    width = max((len(axis.axis) for axis in card.axes), default=0) + 2
    for axis in card.axes:
        shifts = ", ".join(_where(item, axis.axis) for item in axis.shifts) or "none"
        lines.append(f"  {axis.axis:<{width}} {axis.scale:<8} {axis.role:<10} shifts: {shifts}")
        if axis.threshold is not None:
            lines.append(f"  {'':<{width}} {'':<8} {'':<10} {_threshold(axis.threshold)}")
    return "\n".join(lines)


def _threshold(threshold: Threshold) -> str:
    correct = f"correct {threshold.reference:.2f}"
    flip, width = threshold.flip, threshold.width
    if flip is None or width is None:
        return f"flips: none within the axis, {correct}"
    return f"flips at {_estimate(flip)}, {correct}, width {_estimate(width)}"


def _served(target: TargetProvenance) -> str:
    models = ", ".join(target.models) or "unreported models"
    tokens = (
        f", {target.input_tokens} input and {target.output_tokens} output tokens"
        if target.input_tokens is not None and target.output_tokens is not None
        else ""
    )
    cost = f", cost {target.cost:.2f}" if target.cost is not None else ""
    return (
        f"  {target.identity.name} served {models}: {target.observations} observations, "
        f"{target.failed} failed{tokens}{cost}"
    )


def _where(candidate: BoundaryCandidate, axis: str | None) -> str:
    transition = candidate.transition
    if axis is None:
        return str(transition.end)
    if transition.view == "local":
        return f"{axis} {transition.start_value} → {transition.end_value}"
    return f"{axis}={transition.end_value}"


def _estimate(estimate: Estimate) -> str:
    if estimate.lower is None or estimate.upper is None:
        return f"{estimate.value:.2f}"
    return f"{estimate.value:.2f} [{estimate.lower:.2f}, {estimate.upper:.2f}]"


def _number(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"
