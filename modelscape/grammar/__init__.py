"""Task languages: typed tasks, computed attributes, checked perturbations, and prompts.

A ``Task`` subclass defines which tasks are valid. ``@attribute`` methods compute the
properties of every task. A ``@perturbation`` changes a task to a new value of one attribute
and is checked to reach that value while leaving every other attribute unchanged. A
``@realizer`` turns a task into the exact prompt a model receives.
"""

from modelscape.grammar.diff import structural_diff
from modelscape.grammar.perturbation import (
    FunctionPerturbation,
    Perturbation,
    perturb,
    perturbation,
)
from modelscape.grammar.realization import FunctionRealizer, JsonRealizer, Realizer, realizer
from modelscape.grammar.task import Attribute, Node, Task, attribute, attributes_of

__all__ = [
    "Attribute",
    "FunctionPerturbation",
    "FunctionRealizer",
    "JsonRealizer",
    "Node",
    "Perturbation",
    "Realizer",
    "Task",
    "attribute",
    "attributes_of",
    "perturb",
    "perturbation",
    "realizer",
    "structural_diff",
]
