from __future__ import annotations

from collections.abc import Sequence

from modelscape.analysis.profiles import BehaviorProfile, BoundaryCriterion
from modelscape.analysis.statistics import rank_correlation
from modelscape.analysis.transitions import Transition
from modelscape.core.serialization import FrozenModel


class AxisSensitivity(FrozenModel):
    """How strongly one target responds to one axis under one measure.

    ``peak`` is the transition with the largest excess change: a local step on an ordinal or
    numeric axis, or a baseline comparison on a nominal one.
    """

    target: str
    measure: str
    axis: str
    peak: Transition | None
    boundaries: int

    @property
    def max_excess(self) -> float | None:
        if self.peak is None or self.peak.excess is None:
            return None
        return self.peak.excess.value


class MeasureAgreement(FrozenModel):
    """Whether two difference measures tell the same story about the same transitions.

    ``rank_correlation`` compares how both measures order the transitions by excess change.
    ``boundary_overlap`` is the share of candidate boundaries that both measures find; two
    measures that find no boundary at all agree fully. Both are ``None`` when there is nothing
    to compare.
    """

    target: str
    first: str
    second: str
    transitions: int
    rank_correlation: float | None
    boundary_overlap: float | None


def rank_axes(profiles: Sequence[BehaviorProfile]) -> tuple[AxisSensitivity, ...]:
    ranked = [
        AxisSensitivity(
            target=profile.target,
            measure=profile.measure,
            axis=profile.axis,
            peak=_peak(profile),
            boundaries=len(profile.candidate_boundaries),
        )
        for profile in profiles
    ]
    return tuple(
        sorted(ranked, key=lambda item: -item.max_excess if item.max_excess is not None else 0.0)
    )


def compare_measures(
    target: str,
    measures: tuple[str, str],
    transitions: tuple[Sequence[Transition], Sequence[Transition]],
    criterion: BoundaryCriterion,
) -> MeasureAgreement:
    first, second = transitions
    left = {_key(transition): transition for transition in first}
    right = {_key(transition): transition for transition in second}
    shared = [key for key in left if key in right]
    pairs = [
        (excess_left.value, excess_right.value)
        for key in shared
        if (excess_left := left[key].excess) is not None
        and (excess_right := right[key].excess) is not None
    ]
    found_left = {_key(item.transition) for item in criterion.select(first)}
    found_right = {_key(item.transition) for item in criterion.select(second)}
    union = found_left | found_right
    return MeasureAgreement(
        target=target,
        first=measures[0],
        second=measures[1],
        transitions=len(shared),
        rank_correlation=rank_correlation(
            [value for value, _ in pairs], [value for _, value in pairs]
        ),
        boundary_overlap=(
            None if not shared else len(found_left & found_right) / len(union) if union else 1.0
        ),
    )


def _peak(profile: BehaviorProfile) -> Transition | None:
    candidates = [transition for transition in profile.steps if transition.excess is not None]
    return max(
        candidates,
        key=lambda transition: transition.excess.value if transition.excess else 0.0,
        default=None,
    )


def _key(transition: Transition) -> tuple[str, str]:
    return transition.start.key, transition.end.key
