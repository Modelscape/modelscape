"""Controlled behavioral mapping of large language models.

structured task -> controlled changes -> repeated observations -> behavioral profile
"""

from importlib.metadata import version

from modelscape.analysis import (
    AxisScore,
    AxisSensitivity,
    BehaviorProfile,
    BoundaryCandidate,
    BoundaryCriterion,
    Divergence,
    Inference,
    MeasureAgreement,
    Results,
    Scorecard,
)
from modelscape.core import Coordinate, Grid, Message, Prompt, Scale, Sweep, TaskSchema, Variant
from modelscape.execution import ExecutionConfig, Experiment, RetryPolicy, Runner
from modelscape.gate import Requirement
from modelscape.grammar import Node, Task, attribute, perturbation, realizer
from modelscape.measures import CallableDifference, CallableMetric, MeasureValue, Response
from modelscape.page import ReportPage, ScenarioPage
from modelscape.report import Provenance, Report, TargetProvenance
from modelscape.scenario import Scenario, json_field, json_reply, text_match
from modelscape.space import Axis, TaskSpace
from modelscape.spec import Spec
from modelscape.targets import CallableTarget, TargetOutput, TargetRequest
from modelscape.template import Entry, Lexicon, Template

__version__ = version("modelscape")

__all__ = [
    "Axis",
    "AxisScore",
    "AxisSensitivity",
    "BehaviorProfile",
    "BoundaryCandidate",
    "BoundaryCriterion",
    "CallableDifference",
    "CallableMetric",
    "CallableTarget",
    "Coordinate",
    "Divergence",
    "Entry",
    "ExecutionConfig",
    "Experiment",
    "Grid",
    "Inference",
    "Lexicon",
    "MeasureAgreement",
    "MeasureValue",
    "Message",
    "Node",
    "Prompt",
    "Provenance",
    "Report",
    "ReportPage",
    "Requirement",
    "Response",
    "Results",
    "RetryPolicy",
    "Runner",
    "Scale",
    "Scenario",
    "ScenarioPage",
    "Scorecard",
    "Spec",
    "Sweep",
    "TargetOutput",
    "TargetProvenance",
    "TargetRequest",
    "Task",
    "TaskSchema",
    "TaskSpace",
    "Template",
    "Variant",
    "__version__",
    "attribute",
    "json_field",
    "json_reply",
    "perturbation",
    "realizer",
    "text_match",
]
