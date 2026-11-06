"""Templates: prompts with slots, filled from lexicons, that generate checked task spaces."""

from __future__ import annotations

import json
import math
import os
import random
import string
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, TypeAlias, cast

from pydantic import Field, JsonValue, model_validator

from modelscape.core.coordinates import Scale, same_value
from modelscape.core.errors import TaskSpaceError
from modelscape.core.files import read_yaml
from modelscape.core.serialization import AxisValue, FrozenModel, content_hash
from modelscape.grammar import Attribute, FunctionPerturbation, FunctionRealizer, Task
from modelscape.space import Axis, TaskSpace

Reference: TypeAlias = Callable[[Mapping[str, AxisValue]], JsonValue]
Versions: TypeAlias = Mapping[str, Mapping[Any, str]]
Texts: TypeAlias = str | dict[AxisValue, str]
Cell: TypeAlias = AxisValue | dict[AxisValue, str]


class Entry(FrozenModel):
    """One way to fill a slot: its label, the text it puts in the prompt, and its properties.

    ``text`` is one text, or one text per prompt version, such as ``{en: ..., fr: ...}``.
    """

    label: AxisValue
    text: Texts
    properties: dict[str, AxisValue] = Field(default_factory=dict[str, AxisValue])

    def text_in(self, version: AxisValue | None) -> str:
        """The text this entry puts in prompt version ``version``."""
        if isinstance(self.text, str):
            return self.text
        for label, text in self.text.items():
            if version is not None and same_value(label, version):
                return text
        raise ValueError(f"Entry {self.label!r} has no text for prompt version {version!r}.")


class Lexicon(FrozenModel):
    """The entries a slot can take.

    Labels are unique and of one type, and every entry has the same properties, each of one
    type.
    """

    entries: tuple[Entry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> Lexicon:
        first = self.entries[0]
        labels = [entry.label for entry in self.entries]
        if len({json.dumps(label) for label in labels}) != len(labels):
            raise ValueError("Lexicon labels must be unique.")
        for entry in self.entries:
            if type(entry.label) is not type(first.label):
                raise ValueError(f"Lexicon labels must share one type, got {entry.label!r}.")
            if isinstance(entry.text, dict) is not isinstance(first.text, dict):
                raise ValueError("Either every text of a lexicon is per version, or none is.")
            if entry.properties.keys() != first.properties.keys():
                raise ValueError(f"Entry {entry.label!r} does not have the lexicon's properties.")
            for key, value in entry.properties.items():
                if type(value) is not type(first.properties[key]):
                    raise ValueError(f"Property '{key}' must share one type, got {value!r}.")
        return self

    @classmethod
    def of(cls, values: Lexical) -> Lexicon:
        """A lexicon from values, a mapping of labels to texts, rows, or a lexicon.

        A row is a mapping with a ``label``, a ``text``, or both; its other keys are properties.
        """
        if isinstance(values, Lexicon):
            return values
        if isinstance(values, Mapping):
            texts = cast(Mapping[AxisValue, str], values)
            return cls(entries=tuple(Entry(label=key, text=text) for key, text in texts.items()))
        if isinstance(values, str):
            raise ValueError(f"A lexicon is a list or a mapping, not the text {values!r}.")
        return cls(entries=tuple(_entry(value) for value in values))

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> Lexicon:
        """A lexicon from a YAML file holding any form ``of`` takes."""
        return cls.of(read_yaml(path))

    def data(self) -> list[AxisValue] | list[dict[str, Cell]] | dict[AxisValue, Texts]:
        """The lexicon in the shortest form ``of`` takes back: values, a mapping, or rows."""
        if any(entry.properties for entry in self.entries):
            return [_row(entry) for entry in self.entries]
        if all(entry.text == str(entry.label) for entry in self.entries):
            return [entry.label for entry in self.entries]
        return {entry.label: entry.text for entry in self.entries}

    @property
    def properties(self) -> tuple[str, ...]:
        return tuple(self.entries[0].properties)

    @property
    def versioned(self) -> bool:
        """Whether every entry has one text per prompt version."""
        return isinstance(self.entries[0].text, dict)

    @property
    def fingerprint(self) -> str:
        return content_hash(self.model_dump(mode="json"))

    def values(self, property: str | None = None) -> tuple[AxisValue, ...]:
        """Every label, or every value of one property, in order of first appearance."""
        found = [
            entry.label if property is None else entry.properties[property]
            for entry in self.entries
        ]
        return tuple({json.dumps(value): value for value in found}.values())

    def find(self, label: AxisValue) -> Entry:
        for entry in self.entries:
            if same_value(entry.label, label):
                return entry
        raise ValueError(f"No entry is labeled {label!r}.")

    def swap(self, entry: Entry, property: str, value: AxisValue) -> Entry:
        """The counterpart of ``entry`` with ``property`` set to ``value``.

        It agrees with ``entry`` on every other property and has the same rank among such
        entries.
        """
        source = self._peers(entry, property, entry.properties[property])
        target = self._peers(entry, property, value)
        if not target:
            raise ValueError(
                f"No entry has {property}={value!r} and the other properties of {entry.label!r}."
            )
        return target[source.index(entry) % len(target)]

    def _peers(self, entry: Entry, property: str, value: AxisValue) -> list[Entry]:
        wanted = {**entry.properties, property: value}
        return [
            item
            for item in self.entries
            if all(same_value(item.properties[key], wanted[key]) for key in wanted)
        ]


Lexical: TypeAlias = (
    Lexicon | Mapping[Any, Texts] | Sequence[AxisValue] | Sequence[Mapping[str, Cell]]
)


def _entry(value: AxisValue | Mapping[str, Cell]) -> Entry:
    if not isinstance(value, Mapping):
        return Entry(label=value, text=str(value))
    fields = dict(value)
    if "label" not in fields and "text" not in fields:
        raise ValueError(f"Row {value!r} needs a label or a text.")
    if "label" not in fields and isinstance(fields["text"], dict):
        raise ValueError(f"Row {value!r} needs a label, since its text is per version.")
    label = cast(AxisValue, fields.pop("label") if "label" in fields else fields["text"])
    text = fields.pop("text", label)
    return Entry(
        label=label,
        text=text if isinstance(text, dict) else str(text),
        properties=cast(dict[str, AxisValue], fields),
    )


def _row(entry: Entry) -> dict[str, Cell]:
    if entry.label == entry.text:
        return {"text": entry.text, **entry.properties}
    text = {} if entry.text == str(entry.label) else {"text": entry.text}
    return {"label": entry.label, **text, **entry.properties}


class Filling(Task):
    """A task written by a template: the entry chosen for every slot."""

    entries: dict[str, Entry]


class Template:
    """A prompt with ``{slot}`` placeholders, each filled from a lexicon.

    Every slot is an attribute valued by its entry's label, and every property is an attribute
    named ``slot.property``. Varying a property swaps each entry for its counterpart, so
    ``name.gender`` swaps each name for one of the other gender. ``reference`` computes the
    correct answer from the attributes.

    The prompt may come in versions, such as ``{"friendliness": {"neutral": ..., "polite":
    ...}}``; ``friendliness`` is then an attribute like a slot.
    """

    __slots__ = ("_language", "_prompt", "_realizer", "_slots", "name", "reference", "text")

    def __init__(
        self,
        text: str | Versions,
        slots: Mapping[str, Lexical],
        *,
        name: str = "Template",
        system: str | None = None,
        reference: Reference | None = None,
        version: str = "1",
    ) -> None:
        self._slots = {slot: Lexicon.of(values) for slot, values in slots.items()}
        self._prompt: str | None = None
        if isinstance(text, str):
            texts = [text]
        else:
            self._prompt, versions = _versions(text, self._slots)
            self._slots[self._prompt] = versions
            texts = [entry.text_in(None) for entry in versions.entries]
        for each in texts:
            placeholders = {
                field for _, field, _, _ in string.Formatter().parse(each) if field is not None
            }
            if placeholders != set(slots):
                raise TaskSpaceError(
                    f"Template placeholders {sorted(placeholders)} must be exactly its slots "
                    f"{sorted(slots)}."
                )
        versions = self._slots[self._prompt].values() if self._prompt else ()
        for slot, lexicon in self._slots.items():
            if lexicon.versioned and not versions:
                raise TaskSpaceError(
                    f"Slot '{slot}' has texts per version, but the prompt has none."
                )
            for entry in lexicon.entries:
                if isinstance(entry.text, dict) and _keys(entry.text) != _keys(versions):
                    raise TaskSpaceError(
                        f"Entry {entry.label!r} of slot '{slot}' needs one text for each prompt "
                        f"version {list(versions)}."
                    )
        taken = sorted(slot for slot in self._slots if hasattr(Filling, slot))
        if taken:
            raise TaskSpaceError(f"Slot names {taken} are taken by Task; rename them.")
        self.text = text
        self.name = name
        self.reference = reference
        self._language = self._define()
        source = self._slots[self._prompt].fingerprint if self._prompt else cast(str, text)
        self._realizer = FunctionRealizer(
            self._render, name=name, version=version, system=system, parameters={"text": source}
        )

    def __repr__(self) -> str:
        return f"Template({self.name!r}, slots={list(self._slots)!r})"

    @property
    def attributes(self) -> tuple[str, ...]:
        return tuple(
            name
            for slot, lexicon in self._slots.items()
            for name in (slot, *(f"{slot}.{key}" for key in lexicon.properties))
        )

    def values(self, attribute: str) -> tuple[AxisValue, ...]:
        """Every value of ``attribute`` in its lexicon, in order of first appearance."""
        if attribute not in self.attributes:
            raise TaskSpaceError(
                f"'{attribute}' is not an attribute of template {self.name}; its attributes are "
                f"{list(self.attributes)}."
            )
        slot, _, property = attribute.partition(".")
        return self._slots[slot].values(property or None)

    def axis(
        self,
        attribute: str,
        scale: Scale,
        values: Iterable[AxisValue] | None = None,
        *,
        baseline: AxisValue | None = None,
    ) -> Axis[Filling, Any]:
        """An axis over a slot, a slot property, or the prompt versions.

        By default it takes every value of the attribute.
        """
        declared = tuple(values) if values is not None else self.values(attribute)
        slot, _, property = attribute.partition(".")
        lexicon = self._slots[slot]

        def choose(task: Filling, value: AxisValue) -> Filling:
            current = task.entries[slot]
            entry = lexicon.swap(current, property, value) if property else lexicon.find(value)
            return task.replace(entries={**task.entries, slot: entry})

        via = FunctionPerturbation[Filling, AxisValue](
            choose,
            name=attribute,
            free=frozenset({slot} if property else ()),
            parameters={"lexicon": lexicon.fingerprint},
        )
        return Axis(attribute, declared, via=via, scale=scale, baseline=baseline)

    def space(
        self, axes: Sequence[Axis[Filling, Any]], *, cases: int | None = None, seed: int = 0
    ) -> TaskSpace[Filling]:
        """A task space over ``axes``, with up to ``cases`` distinct seeds drawn at the baseline.

        Slots and properties that are not axes vary between seeds. Without ``cases``, every
        combination is a seed. The same ``seed`` always draws the same seeds.
        """
        baseline = {axis.name: axis.baseline for axis in axes}
        choices = {slot: self._choices(slot, baseline) for slot in self._slots}
        total = math.prod(len(options) for options in choices.values())
        picks = (
            range(total)
            if cases is None or cases >= total
            else sorted(random.Random(seed).sample(range(total), cases))
        )
        varied = [slot for slot, options in choices.items() if len(options) > 1]
        seeds: dict[str, Filling] = {}
        for pick in picks:
            entries: dict[str, Entry] = {}
            for slot, options in choices.items():
                pick, index = divmod(pick, len(options))
                entries[slot] = options[index]
            case = "/".join(str(entries[slot].label) for slot in varied) or self.name.lower()
            seeds[case] = self._language(entries=entries)
        return TaskSpace(cases=seeds, axes=axes, realizer=self._realizer)

    def _choices(self, slot: str, baseline: Mapping[str, AxisValue]) -> list[Entry]:
        fixed = {
            name.partition(".")[2]: value
            for name, value in baseline.items()
            if name.partition(".")[0] == slot
        }
        options = [
            entry
            for entry in self._slots[slot].entries
            if all(
                same_value(entry.properties[key] if key else entry.label, value)
                for key, value in fixed.items()
            )
        ]
        if not options:
            raise TaskSpaceError(f"No entry of slot '{slot}' matches the baseline {fixed}.")
        return options

    def _render(self, task: Filling) -> str:
        version = task.entries[self._prompt].label if self._prompt else None
        texts = {slot: entry.text_in(version) for slot, entry in task.entries.items()}
        prompt = texts.pop(self._prompt) if self._prompt else cast(str, self.text)
        return prompt.format_map(texts).strip()

    def _define(self) -> type[Filling]:
        namespace: dict[str, object] = {"__module__": __name__, "__qualname__": self.name}
        for slot, lexicon in self._slots.items():
            first = lexicon.entries[0]
            namespace[slot] = _attribute(slot, None, type(first.label))
            for key, value in first.properties.items():
                namespace[f"{slot}.{key}"] = _attribute(slot, key, type(value))
        if self.reference is not None:
            namespace["reference"] = _reference(self.reference)
        return cast(type[Filling], type(self.name, (Filling,), namespace))


def _versions(text: Versions, slots: Mapping[str, Lexicon]) -> tuple[str, Lexicon]:
    if len(text) != 1:
        raise TaskSpaceError("Prompt versions map one attribute name to its versions.")
    ((name, versions),) = text.items()
    if not name.isidentifier() or name in slots:
        raise TaskSpaceError(f"'{name}' cannot name the prompt versions; use a free name.")
    lexicon = Lexicon.of(versions)
    if lexicon.versioned:
        raise TaskSpaceError(f"The versions of '{name}' are whole prompts, one text each.")
    return name, lexicon


def _keys(values: Iterable[AxisValue]) -> set[str]:
    return {json.dumps(value) for value in values}


def _reference(compute: Reference) -> Callable[[Filling], JsonValue]:
    def reference(self: Filling) -> JsonValue:
        return compute(self.attributes())

    return reference


def _attribute(slot: str, key: str | None, kind: type) -> Attribute[Filling, AxisValue]:
    def read(task: Filling) -> AxisValue:
        entry = task.entries[slot]
        return entry.label if key is None else entry.properties[key]

    read.__annotations__ = {"return": kind.__name__}
    read.__doc__ = f"The {key or 'label'} of the {slot} entry."
    return Attribute(read)
