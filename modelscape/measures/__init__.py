"""Point metrics score one response; difference measures compare two responses.

A response is a variant together with the target's output, so measures can judge behavior in
the context of the task. Differences come at three levels: wording (edit distance, word
overlap), meaning (embedding distance), and claims (distance between claim graphs).
"""

from modelscape.core.measurements import MeasureValue
from modelscape.measures.callables import CallableDifference, CallableMetric
from modelscape.measures.differences import (
    EmbeddingCosineDistance,
    NormalizedEditDistance,
    TokenJaccardDistance,
)
from modelscape.measures.graphs import Edge, Graph
from modelscape.measures.metrics import ExactMatch
from modelscape.measures.protocols import (
    DifferenceMeasure,
    Embedder,
    Extractor,
    PointMetric,
    Response,
)
from modelscape.measures.structure import (
    CallableExtractor,
    GraphDistance,
    ModelExtractor,
    parse_triples,
)

__all__ = [
    "CallableDifference",
    "CallableExtractor",
    "CallableMetric",
    "DifferenceMeasure",
    "Edge",
    "Embedder",
    "EmbeddingCosineDistance",
    "ExactMatch",
    "Extractor",
    "Graph",
    "GraphDistance",
    "MeasureValue",
    "ModelExtractor",
    "NormalizedEditDistance",
    "PointMetric",
    "Response",
    "TokenJaccardDistance",
    "parse_triples",
]
