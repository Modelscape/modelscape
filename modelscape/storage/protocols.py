from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, TypeAlias, TypeVar

from modelscape.core.experiments import ExperimentRecord, RunManifest
from modelscape.core.measurements import DifferenceMeasurement, PointMeasurement
from modelscape.core.observations import Observation
from modelscape.core.tasks import Variant

Record: TypeAlias = (
    Variant
    | Observation
    | PointMeasurement
    | DifferenceMeasurement
    | ExperimentRecord
    | RunManifest
)

RECORD_KINDS: tuple[type[Record], ...] = (
    Variant,
    Observation,
    PointMeasurement,
    DifferenceMeasurement,
    ExperimentRecord,
    RunManifest,
)

RecordT = TypeVar("RecordT", bound=Record)


class Store(Protocol):
    """Durable home for scientific records, keyed by record kind and id.

    ``put`` inserts or replaces records. ``get`` returns the subset of requested ids that
    exist. Implementations must be safe to interrupt between calls.
    """

    def put(self, records: Iterable[Record]) -> None: ...

    def get(self, kind: type[RecordT], ids: Iterable[str]) -> dict[str, RecordT]: ...
