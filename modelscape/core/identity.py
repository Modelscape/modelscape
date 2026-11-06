from __future__ import annotations

from pydantic import Field

from modelscape.core.serialization import FrozenModel, JsonObject, content_hash


class Identity(FrozenModel):
    """Stable identity of an executable component such as a perturbation, measure, or target.

    Parameters must capture every setting that can change the component's behavior, and must
    never contain secrets.
    """

    name: str = Field(min_length=1)
    version: str = Field(default="1", min_length=1)
    parameters: JsonObject = Field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        return content_hash(self.model_dump(mode="json"))
