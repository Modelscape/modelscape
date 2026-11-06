"""Point metrics score one response; difference measures compare two responses.

A response is a variant together with the target's output, so measures can judge behavior in
the context of the task. Differences are in wording (edit distance, word overlap) or in
meaning (embedding distance).
"""

from modelscape.core.measurements import MeasureValue
from modelscape.measures.callables import CallableDifference, CallableMetric
from modelscape.measures.differences import (
    EmbeddingCosineDistance,
    NormalizedEditDistance,
    TokenJaccardDistance,
)
from modelscape.measures.metrics import ExactMatch
from modelscape.measures.protocols import (
    DifferenceMeasure,
    Embedder,
    PointMetric,
    Response,
)

__all__ = [
    "CallableDifference",
    "CallableMetric",
    "DifferenceMeasure",
    "Embedder",
    "EmbeddingCosineDistance",
    "ExactMatch",
    "MeasureValue",
    "NormalizedEditDistance",
    "PointMetric",
    "Response",
    "TokenJaccardDistance",
]
