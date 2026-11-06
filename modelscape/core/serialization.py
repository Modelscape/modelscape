from __future__ import annotations

import hashlib
import json
from typing import TypeAlias

from pydantic import BaseModel, ConfigDict, JsonValue

JsonObject: TypeAlias = dict[str, JsonValue]
AxisValue: TypeAlias = bool | int | float | str

IDENTIFIER_LENGTH = 32


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def canonical_json(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def content_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def stable_id(value: object) -> str:
    return content_hash(value)[:IDENTIFIER_LENGTH]
