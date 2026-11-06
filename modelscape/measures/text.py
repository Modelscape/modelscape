from __future__ import annotations

import re

WORD = re.compile(r"\w+")


def normalize_text(text: str) -> str:
    return " ".join(text.casefold().split())


def word_set(text: str) -> frozenset[str]:
    return frozenset(WORD.findall(text.casefold()))


def levenshtein(left: str, right: str) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for row, left_char in enumerate(left, start=1):
        current = [row]
        for column, right_char in enumerate(right, start=1):
            current.append(
                min(
                    previous[column] + 1,
                    current[column - 1] + 1,
                    previous[column - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]
