from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from modelscape.core.errors import MeasureError
from modelscape.core.identity import Identity
from modelscape.core.measurements import MeasureValue
from modelscape.core.observations import TargetOutput
from modelscape.core.serialization import canonical_json
from modelscape.core.tasks import Variant
from modelscape.measures.protocols import Response
from modelscape.measures.text import normalize_text


@dataclass(frozen=True)
class ExactMatch:
    """1.0 when the output text equals the variant's reference, otherwise 0.0.

    With ``normalize``, comparison ignores case and collapses whitespace.
    """

    normalize: bool = True

    @property
    def identity(self) -> Identity:
        return Identity(name="exact_match", version="1", parameters={"normalize": self.normalize})

    async def score(self, responses: Sequence[Response]) -> Sequence[MeasureValue]:
        return [self._score(variant, output) for variant, output in responses]

    def _score(self, variant: Variant, output: TargetOutput) -> MeasureValue:
        expected = _reference_text(variant, self.identity.name)
        actual = output.as_text()
        if self.normalize:
            expected, actual = normalize_text(expected), normalize_text(actual)
        return MeasureValue(value=float(expected == actual))


def _reference_text(variant: Variant, metric: str) -> str:
    reference = variant.reference
    if reference is None:
        raise MeasureError(
            f"Metric '{metric}' needs a reference, but variant '{variant.id}' of case "
            f"'{variant.case_id}' has none."
        )
    return reference if isinstance(reference, str) else canonical_json(reference)
