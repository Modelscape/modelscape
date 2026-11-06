from __future__ import annotations

from collections.abc import Iterable, Sequence

import numpy as np

from modelscape.analysis.comparisons import group_cells
from modelscape.analysis.statistics import FloatArray
from modelscape.core.coordinates import Coordinate
from modelscape.core.errors import AnalysisError
from modelscape.core.measurements import DifferenceMeasurement, PointMeasurement
from modelscape.core.observations import Observation


class ResultIndex:
    """Lookup structure over the records of one experiment run."""

    __slots__ = ("_cells", "_differences", "_points")

    def __init__(
        self,
        observations: Iterable[Observation],
        point_measurements: Iterable[PointMeasurement],
        difference_measurements: Iterable[DifferenceMeasurement],
    ) -> None:
        self._cells = group_cells(observations)
        self._points = {
            (measurement.measure.name, measurement.observation_id): measurement
            for measurement in point_measurements
        }
        self._differences = {
            (
                measurement.measure.name,
                measurement.start_observation_id,
                measurement.end_observation_id,
            ): measurement
            for measurement in difference_measurements
        }

    def cell(self, target: str, case_id: str, coordinate: Coordinate) -> tuple[Observation, ...]:
        return self._cells.get((target, case_id, coordinate), ())

    def metric_values(
        self, metric: str, observations: Sequence[Observation]
    ) -> tuple[FloatArray, list[str]]:
        records = [self._point(metric, observation) for observation in observations]
        values = np.array([record.value for record in records], dtype=np.float64)
        return values, [record.id for record in records]

    def within_matrix(
        self, measure: str, observations: Sequence[Observation]
    ) -> tuple[FloatArray, list[str]]:
        size = len(observations)
        matrix = np.full((size, size), np.nan)
        identifiers: list[str] = []
        for row in range(size):
            for column in range(row + 1, size):
                record = self._difference(measure, observations[row], observations[column])
                matrix[row, column] = matrix[column, row] = record.value
                identifiers.append(record.id)
        return matrix, identifiers

    def cross_matrix(
        self, measure: str, start: Sequence[Observation], end: Sequence[Observation]
    ) -> tuple[FloatArray, list[str]]:
        matrix = np.empty((len(start), len(end)))
        identifiers: list[str] = []
        for row, left in enumerate(start):
            for column, right in enumerate(end):
                record = self._difference(measure, left, right)
                matrix[row, column] = record.value
                identifiers.append(record.id)
        return matrix, identifiers

    def _point(self, metric: str, observation: Observation) -> PointMeasurement:
        record = self._points.get((metric, observation.id))
        if record is None:
            raise AnalysisError(
                f"Metric '{metric}' was not measured for observation '{observation.id}'."
            )
        return record

    def _difference(
        self, measure: str, start: Observation, end: Observation
    ) -> DifferenceMeasurement:
        record = self._differences.get((measure, start.id, end.id))
        if record is None:
            raise AnalysisError(
                f"Measure '{measure}' was not computed between observations "
                f"'{start.id}' and '{end.id}'."
            )
        return record
