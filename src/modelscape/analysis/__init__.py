"""Analysis of a run: profiles, scorecards, boundaries, thresholds, and robustness checks."""

from modelscape.analysis.profiles import BehaviorProfile, BoundaryCandidate, BoundaryCriterion
from modelscape.analysis.results import Results, Trace
from modelscape.analysis.robustness import AxisSensitivity, MeasureAgreement
from modelscape.analysis.scorecard import AxisScore, Divergence, Scorecard
from modelscape.analysis.statistics import Estimate, Inference
from modelscape.analysis.threshold import Threshold
from modelscape.analysis.transitions import (
    CaseMetric,
    CaseTransition,
    MetricPoint,
    Transition,
    VariantVariability,
)

__all__ = [
    "AxisScore",
    "AxisSensitivity",
    "BehaviorProfile",
    "BoundaryCandidate",
    "BoundaryCriterion",
    "CaseMetric",
    "CaseTransition",
    "Divergence",
    "Estimate",
    "Inference",
    "MeasureAgreement",
    "MetricPoint",
    "Results",
    "Scorecard",
    "Threshold",
    "Trace",
    "Transition",
    "VariantVariability",
]
