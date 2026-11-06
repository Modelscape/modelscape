from __future__ import annotations

from collections.abc import Iterator, Sequence

from pydantic import JsonValue


def structural_diff(before: JsonValue, after: JsonValue) -> tuple[str, ...]:
    """JSON Pointers of every location where ``after`` differs from ``before``.

    Objects are compared key by key and arrays index by index; each difference is reported at
    the deepest location where it occurs.
    """
    return tuple(pointer(path) for path in _differences(before, after, ()))


def pointer(segments: Sequence[str | int]) -> str:
    return "".join("/" + str(segment).replace("~", "~0").replace("/", "~1") for segment in segments)


def _differences(
    before: JsonValue, after: JsonValue, path: tuple[str | int, ...]
) -> Iterator[tuple[str | int, ...]]:
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(before.keys() | after.keys()):
            if key in before and key in after:
                yield from _differences(before[key], after[key], (*path, key))
            else:
                yield (*path, key)
    elif isinstance(before, list) and isinstance(after, list):
        for index in range(max(len(before), len(after))):
            if index < len(before) and index < len(after):
                yield from _differences(before[index], after[index], (*path, index))
            else:
                yield (*path, index)
    elif type(before) is not type(after) or before != after:
        yield path
