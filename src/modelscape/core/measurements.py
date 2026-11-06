from __future__ import annotations

from pydantic import Field

from modelscape.core.identity import Identity
from modelscape.core.serialization import FrozenModel, JsonObject, stable_id


class MeasureValue(FrozenModel):
    """A scalar produced by a measure, with optional structured auxiliary data."""

    value: float = Field(allow_inf_nan=False)
    details: JsonObject = Field(default_factory=dict)


class PointMeasurement(FrozenModel):
    """A point metric evaluated on one observation at one location in the task space."""

    id: str
    measure: Identity
    observation_id: str
    value: float = Field(allow_inf_nan=False)
    details: JsonObject = Field(default_factory=dict)

    @classmethod
    def key(cls, measure: Identity, observation_id: str) -> str:
        return stable_id({"measure": measure.fingerprint, "observation": observation_id})

    @classmethod
    def create(
        cls, measure: Identity, observation_id: str, result: MeasureValue
    ) -> PointMeasurement:
        return cls(
            id=cls.key(measure, observation_id),
            measure=measure,
            observation_id=observation_id,
            value=result.value,
            details=result.details,
        )


class DifferenceMeasurement(FrozenModel):
    """A difference measure comparing the outputs of two observations."""

    id: str
    measure: Identity
    start_observation_id: str
    end_observation_id: str
    value: float = Field(allow_inf_nan=False)
    details: JsonObject = Field(default_factory=dict)

    @classmethod
    def key(cls, measure: Identity, start_observation_id: str, end_observation_id: str) -> str:
        return stable_id(
            {
                "measure": measure.fingerprint,
                "start": start_observation_id,
                "end": end_observation_id,
            }
        )

    @classmethod
    def create(
        cls,
        measure: Identity,
        start_observation_id: str,
        end_observation_id: str,
        result: MeasureValue,
    ) -> DifferenceMeasurement:
        return cls(
            id=cls.key(measure, start_observation_id, end_observation_id),
            measure=measure,
            start_observation_id=start_observation_id,
            end_observation_id=end_observation_id,
            value=result.value,
            details=result.details,
        )
