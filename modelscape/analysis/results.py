from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import JsonValue

from modelscape.analysis.index import ResultIndex
from modelscape.analysis.profiles import BehaviorProfile, BoundaryCriterion, build_profile
from modelscape.analysis.scorecard import (
    Divergence,
    Scorecard,
    build_divergence,
    build_scorecard,
)
from modelscape.analysis.statistics import Inference
from modelscape.analysis.threshold import Answer
from modelscape.analysis.transitions import Transition, measure_transition
from modelscape.core.coordinates import AxisValue
from modelscape.core.errors import AnalysisError, StoreError
from modelscape.core.experiments import ExperimentRecord, RunManifest
from modelscape.core.identity import Identity
from modelscape.core.measurements import DifferenceMeasurement, PointMeasurement
from modelscape.core.observations import Observation
from modelscape.core.tasks import Variant
from modelscape.storage.protocols import RecordT, Store


class Results:
    """All records of one experiment run, with the analyses defined over them.

    Every aggregate returned here carries the ``measurement_ids`` behind it.
    """

    __slots__ = (
        "_difference_measurements",
        "_experiment",
        "_index",
        "_observations",
        "_point_measurements",
        "_variants",
    )

    def __init__(
        self,
        experiment: ExperimentRecord,
        variants: Sequence[Variant],
        observations: Sequence[Observation],
        point_measurements: Sequence[PointMeasurement],
        difference_measurements: Sequence[DifferenceMeasurement],
    ) -> None:
        self._experiment = experiment
        self._variants = tuple(variants)
        self._observations = tuple(observations)
        self._point_measurements = tuple(point_measurements)
        self._difference_measurements = tuple(difference_measurements)
        self._index = ResultIndex(observations, point_measurements, difference_measurements)

    def __repr__(self) -> str:
        return (
            f"Results(experiment={self._experiment.id!r}, variants={len(self._variants)}, "
            f"observations={len(self._observations)}, failures={len(self.failures)}, "
            f"point_measurements={len(self._point_measurements)}, "
            f"difference_measurements={len(self._difference_measurements)})"
        )

    @classmethod
    def load(cls, store: Store, experiment_id: str) -> Results:
        """Rebuild the results of a completed run from a store."""
        experiment = _one(store, ExperimentRecord, experiment_id)
        manifest = _one(store, RunManifest, experiment_id)
        return cls(
            experiment=experiment,
            variants=_all(store, Variant, manifest.variant_ids),
            observations=_all(store, Observation, manifest.observation_ids),
            point_measurements=_all(store, PointMeasurement, manifest.point_measurement_ids),
            difference_measurements=_all(
                store, DifferenceMeasurement, manifest.difference_measurement_ids
            ),
        )

    @property
    def experiment(self) -> ExperimentRecord:
        return self._experiment

    @property
    def variants(self) -> tuple[Variant, ...]:
        return self._variants

    @property
    def observations(self) -> tuple[Observation, ...]:
        return self._observations

    @property
    def failures(self) -> tuple[Observation, ...]:
        return tuple(observation for observation in self._observations if not observation.succeeded)

    @property
    def point_measurements(self) -> tuple[PointMeasurement, ...]:
        return self._point_measurements

    @property
    def difference_measurements(self) -> tuple[DifferenceMeasurement, ...]:
        return self._difference_measurements

    def select(
        self,
        *,
        target: str | None = None,
        case: str | None = None,
        coordinate: Mapping[str, AxisValue] | None = None,
    ) -> tuple[Observation, ...]:
        """Observations filtered by target name, case id, and coordinate.

        A partial ``coordinate`` is completed with baseline values, as everywhere else.
        """
        location = None if coordinate is None else self._experiment.space.coordinate(coordinate)
        return tuple(
            observation
            for observation in self._observations
            if (target is None or observation.target.name == target)
            and (case is None or observation.case_id == case)
            and (location is None or observation.coordinate == location)
        )

    def table(self) -> list[dict[str, JsonValue]]:
        """One tidy row per observation, with its point metrics and execution timing."""
        metrics: dict[str, dict[str, JsonValue]] = {}
        for measurement in self._point_measurements:
            metrics.setdefault(measurement.observation_id, {})[measurement.measure.name] = (
                measurement.value
            )
        return [
            {
                "target": observation.target.name,
                "case": observation.case_id,
                **dict(observation.coordinate),
                "repetition": observation.repetition,
                "schedule_position": observation.schedule_position,
                "started_at": observation.started_at.isoformat(),
                "completed_at": observation.completed_at.isoformat(),
                "succeeded": observation.succeeded,
                "output": observation.output.as_text(),
                **metrics.get(observation.id, {}),
            }
            for observation in self._observations
        ]

    def profile(
        self,
        axis: str,
        measure: str,
        *,
        target: str | None = None,
        fixed: Mapping[str, AxisValue] | None = None,
        cases: Sequence[str] | None = None,
        criterion: BoundaryCriterion | None = None,
        inference: Inference | None = None,
    ) -> BehaviorProfile:
        """Behavior of one target along one axis under one difference measure."""
        return build_profile(
            self._index,
            self._experiment,
            target=self._target(target),
            axis=axis,
            measure=self._measure(measure),
            fixed=fixed,
            cases=self._case_ids(cases),
            inference=inference or Inference(),
            criterion=criterion or BoundaryCriterion(),
        )

    def profiles(
        self,
        axis: str,
        measure: str,
        *,
        fixed: Mapping[str, AxisValue] | None = None,
        cases: Sequence[str] | None = None,
        criterion: BoundaryCriterion | None = None,
        inference: Inference | None = None,
    ) -> tuple[BehaviorProfile, ...]:
        """One profile per target, computed identically for direct comparison."""
        return tuple(
            self.profile(
                axis,
                measure,
                target=target.name,
                fixed=fixed,
                cases=cases,
                criterion=criterion,
                inference=inference,
            )
            for target in self._experiment.targets
        )

    def transitions(
        self,
        measure: str,
        *,
        target: str | None = None,
        cases: Sequence[str] | None = None,
        inference: Inference | None = None,
    ) -> tuple[Transition, ...]:
        """Every local transition between evaluated neighbors on ordinal and numeric axes."""
        name = self._target(target)
        measure_name = self._measure(measure)
        selected = self._case_ids(cases)
        settings = inference or Inference()
        return tuple(
            measure_transition(
                self._index,
                target=name,
                measure=measure_name,
                view="local",
                axis=pair.axis,
                start=pair.start,
                end=pair.end,
                cases=selected,
                inference=settings,
            )
            for pair in self._experiment.space.neighbors(self._experiment.coordinates)
        )

    def scorecard(
        self,
        metric: str,
        measure: str,
        *,
        target: str | None = None,
        group: str = "all",
        answered: str | None = None,
        answer: Answer | None = None,
        cases: Sequence[str] | None = None,
        criterion: BoundaryCriterion | None = None,
        inference: Inference | None = None,
    ) -> Scorecard:
        """Accuracy, spurious and missed change, and per-axis shifts of one target.

        ``metric`` scores correctness and ``measure`` compares two answers; every axis is read
        along its line through the baseline. ``answered``, a metric that is 1 when an answer
        could be read, gives the share of readable outputs. ``answer``, which reads the answer
        from an output, adds a threshold to every causal numeric axis.
        """
        return build_scorecard(
            self._index,
            self._experiment,
            self._variants,
            target=self._target(target),
            group=group,
            metric=self._metric(metric),
            measure=self._measure(measure),
            answered=None if answered is None else self._metric(answered),
            answer=answer,
            cases=self._case_ids(cases),
            criterion=criterion or BoundaryCriterion(),
            inference=inference or Inference(),
        )

    def divergence(
        self,
        measure: str,
        first: str,
        second: str,
        *,
        cases: Sequence[str] | None = None,
        criterion: BoundaryCriterion | None = None,
        inference: Inference | None = None,
    ) -> Divergence:
        """Where two targets of this experiment differ beyond the run-to-run variation of each.

        ``first`` must come before ``second`` in the experiment's targets.
        """
        names = [target.name for target in self._experiment.targets]
        if self._target(first) == self._target(second) or names.index(first) > names.index(second):
            raise AnalysisError(
                f"Compare two different targets in experiment order {names!r}, "
                f"got '{first}' and '{second}'."
            )
        return build_divergence(
            self._index,
            self._experiment,
            first=first,
            second=second,
            measure=self._measure(measure),
            cases=self._case_ids(cases),
            criterion=criterion or BoundaryCriterion(),
            inference=inference or Inference(),
        )

    def _target(self, name: str | None) -> str:
        names = [target.name for target in self._experiment.targets]
        if name is None:
            if len(names) == 1:
                return names[0]
            raise AnalysisError(f"This experiment has several targets {names!r}; pass target=.")
        if name not in names:
            raise AnalysisError(f"Unknown target '{name}'; known targets are {names!r}.")
        return name

    def _measure(self, name: str) -> str:
        return _known(name, "difference measure", self._experiment.difference_measures)

    def _metric(self, name: str) -> str:
        return _known(name, "point metric", self._experiment.point_metrics)

    def _case_ids(self, cases: Sequence[str] | None) -> tuple[str, ...]:
        if cases is None:
            return self._experiment.case_ids
        unknown = [case for case in cases if case not in self._experiment.case_ids]
        if unknown or not cases:
            raise AnalysisError(
                f"Cases must be a non-empty subset of the experiment's cases; unknown: {unknown!r}."
            )
        return tuple(cases)


def _known(name: str, kind: str, identities: Sequence[Identity]) -> str:
    names = [identity.name for identity in identities]
    if name not in names:
        raise AnalysisError(f"Unknown {kind} '{name}'; this experiment has {names!r}.")
    return name


def _one(store: Store, kind: type[RecordT], identifier: str) -> RecordT:
    found = store.get(kind, [identifier])
    if identifier not in found:
        raise StoreError(f"The store has no {kind.__name__} with id '{identifier}'.")
    return found[identifier]


def _all(store: Store, kind: type[RecordT], identifiers: Sequence[str]) -> list[RecordT]:
    found = store.get(kind, identifiers)
    missing = [identifier for identifier in identifiers if identifier not in found]
    if missing:
        raise StoreError(
            f"The store is missing {len(missing)} {kind.__name__} records, e.g. '{missing[0]}'."
        )
    return [found[identifier] for identifier in identifiers]
