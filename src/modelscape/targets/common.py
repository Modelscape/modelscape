from __future__ import annotations

from collections.abc import Mapping
from typing import TypeAlias
from urllib.parse import urlsplit

from pydantic import JsonValue

Options: TypeAlias = Mapping[str, JsonValue]


def missing_extra(target: str, extra: str) -> str:
    return f'{target} requires the "{extra}" extra: uv add "modelscape[{extra}]"'


def public_endpoint(url: object) -> str:
    """An endpoint URL without user info, query, or fragment, safe to store in an identity."""
    parts = urlsplit(str(url))
    port = f":{parts.port}" if parts.port is not None else ""
    return f"{parts.scheme}://{parts.hostname}{port}{parts.path}"
