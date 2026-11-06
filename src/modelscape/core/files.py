"""YAML read strictly: only ``true`` and ``false`` are booleans, and dates and octals stay text."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, cast

import yaml

WIDTH = 120
FLOW_WIDTH = 110
FOLD_WIDTH = 100
RESOLVERS = (
    ("null", r"^(?:~|null|)$", ("~", "n", "")),
    ("bool", r"^(?:true|false)$", ("t", "f")),
    ("int", r"^[-+]?(?:0|[1-9][0-9]*)$", tuple("-+0123456789")),
    ("float", r"^[-+]?(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?$", tuple("-+.0123456789")),
)


class _Loader(yaml.SafeLoader):
    pass


_Loader.yaml_implicit_resolvers = {}
for _tag, _pattern, _first in RESOLVERS:
    for _character in _first:
        _Loader.yaml_implicit_resolvers.setdefault(_character, []).append(
            (f"tag:yaml.org,2002:{_tag}", re.compile(_pattern))
        )


class _Dumper(yaml.SafeDumper):
    depth = 0

    def represent_text(self, data: str) -> yaml.ScalarNode:
        style = "|" if "\n" in data else ">" if _foldable(data) else None
        return yaml.ScalarNode("tag:yaml.org,2002:str", data, style=style)

    def represent_list(self, data: Any) -> yaml.SequenceNode:
        items = list(cast(list[object] | tuple[object, ...], data))
        self.depth += 1
        node = super().represent_list(items)
        self.depth -= 1
        node.flow_style = self.depth > 0 and _short(items)
        rows = [cast(dict[object, object], item) for item in items if isinstance(item, dict)]
        if rows:
            inline = all(_short(row) for row in rows)
            for child in node.value:
                child.flow_style = inline
        return node

    def represent_dict(self, data: Any) -> yaml.MappingNode:
        self.depth += 1
        node = super().represent_dict(data)
        self.depth -= 1
        node.flow_style = self.depth > 1 and _short(cast(dict[object, object], data))
        return node


_Dumper.add_representer(str, _Dumper.represent_text)
_Dumper.add_representer(list, _Dumper.represent_list)
_Dumper.add_representer(tuple, _Dumper.represent_list)
_Dumper.add_representer(dict, _Dumper.represent_dict)


def parse_yaml(text: str) -> Any:
    """The value of a YAML document."""
    return yaml.load(text, Loader=_Loader)


def read_yaml(path: str | os.PathLike[str]) -> Any:
    """The value of a YAML file."""
    return parse_yaml(Path(path).read_text(encoding="utf-8"))


def format_yaml(value: object) -> str:
    """``value`` as YAML: keys in order, multi-line text as blocks, short collections inline."""
    return yaml.dump(value, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=WIDTH)


def parse_scalar(text: str) -> bool | int | float | str:
    """``text`` as the boolean or number it spells in YAML, or as itself."""
    try:
        value: object = parse_yaml(text)
    except yaml.YAMLError:
        return text
    return value if isinstance(value, bool | int | float) else text


def _short(data: list[object] | dict[object, object]) -> bool:
    items = list(data.values()) if isinstance(data, dict) else data
    parts = [
        part
        for item in items
        for part in (cast(list[object], item) if isinstance(item, list | tuple) else [item])
    ]
    if not items or any(
        isinstance(part, dict | list | tuple) or _multiline(part) for part in parts
    ):
        return False
    shown = yaml.dump(data, Dumper=yaml.SafeDumper, default_flow_style=True, width=1_000_000)
    return len(shown) <= FLOW_WIDTH


def _multiline(item: object) -> bool:
    return isinstance(item, str) and "\n" in item


def _foldable(text: str) -> bool:
    return len(text) > FOLD_WIDTH and text == text.strip() and "  " not in text
