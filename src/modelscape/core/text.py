"""Word-level differences between two prompts."""

from __future__ import annotations

import difflib
import re

from pydantic import JsonValue


def word_diff(before: str, after: str) -> list[JsonValue]:
    """``after`` as ``[text, kind]`` parts: each ``same``, ``added``, or ``removed``."""
    old, new = re.split(r"(\s+)", before), re.split(r"(\s+)", after)
    parts: list[JsonValue] = []
    for tag, first, last, start, end in difflib.SequenceMatcher(a=old, b=new).get_opcodes():
        if tag == "equal":
            parts.append(["".join(new[start:end]), "same"])
            continue
        if first < last:
            parts.append(["".join(old[first:last]), "removed"])
        if start < end:
            parts.append(["".join(new[start:end]), "added"])
    return parts
