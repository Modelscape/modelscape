"""Which observation pairs are compared. Execution and analysis share it, so they agree."""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Sequence

from modelscape.core.coordinates import Coordinate, CoordinateSystem
from modelscape.core.observations import Observation

CellKey = tuple[str, str, Coordinate]


def comparison_pairs(
    space: CoordinateSystem, coordinates: Sequence[Coordinate]
) -> tuple[tuple[Coordinate, Coordinate], ...]:
    """Every adjacent neighbor pair, plus every evaluated coordinate against the baseline."""
    baseline = space.baseline
    neighbors = [(pair.start, pair.end) for pair in space.neighbors(coordinates)]
    anchored = [(baseline, coordinate) for coordinate in coordinates if coordinate != baseline]
    return tuple(dict.fromkeys([*neighbors, *anchored]))


def group_cells(observations: Iterable[Observation]) -> dict[CellKey, tuple[Observation, ...]]:
    """Successful observations per (target name, case id, coordinate), ordered by repetition."""
    cells: dict[CellKey, list[Observation]] = {}
    for observation in observations:
        if observation.succeeded:
            key = (observation.target.name, observation.case_id, observation.coordinate)
            cells.setdefault(key, []).append(observation)
    return {
        key: tuple(sorted(members, key=lambda observation: observation.repetition))
        for key, members in cells.items()
    }


def within_pairs(observations: Sequence[Observation]) -> list[tuple[Observation, Observation]]:
    return list(itertools.combinations(observations, 2))


def between_pairs(
    start: Sequence[Observation], end: Sequence[Observation]
) -> list[tuple[Observation, Observation]]:
    return list(itertools.product(start, end))


def measured_pairs(
    space: CoordinateSystem,
    coordinates: Sequence[Coordinate],
    observations: Iterable[Observation],
    targets: Sequence[str],
) -> list[tuple[Observation, Observation]]:
    """All observation pairs a difference measure must score for an experiment.

    Within each target: repetitions of one variant, neighbors, and the baseline against every
    coordinate. Across targets, in experiment order: both targets at the same coordinate.
    """
    cells = group_cells(observations)
    cases = sorted({case for _, case, _ in cells})
    pairs: list[tuple[Observation, Observation]] = []
    for target in targets:
        for case in cases:
            for coordinate in coordinates:
                pairs.extend(within_pairs(cells.get((target, case, coordinate), ())))
            for start, end in comparison_pairs(space, coordinates):
                pairs.extend(
                    between_pairs(
                        cells.get((target, case, start), ()), cells.get((target, case, end), ())
                    )
                )
    for first, second in itertools.combinations(targets, 2):
        for case in cases:
            for coordinate in coordinates:
                pairs.extend(
                    between_pairs(
                        cells.get((first, case, coordinate), ()),
                        cells.get((second, case, coordinate), ()),
                    )
                )
    return pairs
