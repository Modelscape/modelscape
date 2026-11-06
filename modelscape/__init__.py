"""Find out which details change a language model's answer, and whether they should.

spec -> checked variants -> repeated outputs -> shifts beyond noise -> report
"""

from importlib.metadata import version

from modelscape.analysis import (
    AxisScore,
    BehaviorProfile,
    BoundaryCandidate,
    BoundaryCriterion,
    Divergence,
    Inference,
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
from modelscape.runs import Run, run
from modelscape.scenario import Scenario, json_field, json_reply, text_match
from modelscape.space import Axis, TaskSpace
from modelscape.spec import Spec
from modelscape.targets import CallableTarget, TargetOutput, TargetRequest
from modelscape.template import Entry, Lexicon, Template

__version__ = version("modelscape")

__all__ = [
    "Axis",
    "AxisScore",
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
    "Run",
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
    "run",
    "text_match",
]
