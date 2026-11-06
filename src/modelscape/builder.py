"""A notebook widget that writes a scenario spec: mark what varies, set the answer, save YAML.

Requires the ``widget`` extra: ``uv add "modelscape[widget]"``.
"""

from __future__ import annotations

import copy
import json
import os
import re
import string
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast, get_args

from pydantic import JsonValue, ValidationError

from modelscape import lexicons
from modelscape.core.coordinates import Scale
from modelscape.core.errors import ModelscapeError, SpecError
from modelscape.core.files import format_yaml, parse_scalar, read_yaml
from modelscape.core.serialization import AxisValue
from modelscape.core.text import word_diff
from modelscape.scenarios import SPECS, spec
from modelscape.spec import Number, Range, Spec, filled, range_of
from modelscape.template import Entry, Lexical, Lexicon

if TYPE_CHECKING:
    from pandas import DataFrame

try:
    import anywidget
    import traitlets
except ModuleNotFoundError as error:
    raise ModuleNotFoundError(
        'Builder requires the widget extra: uv add "modelscape[widget]"'
    ) from error

SCRIPT = Path(__file__).parent / "static" / "builder.js"
if not SCRIPT.is_file():
    raise FileNotFoundError(
        "The builder is not built: npm --prefix page ci && npm --prefix page run build"
    )
OPERATIONS = frozenset(
    {
        "mark",
        "remove",
        "per_version",
        "group",
        "drop",
        "rename",
        "rows",
        "range",
        "add",
        "move",
        "extend",
        "vary",
        "versions",
        "version",
        "answer",
        "instruct",
        "edit",
        "save",
        "undo",
    }
)
EDITABLE = frozenset(
    {"name", "version", "description", "system", "prompt", "cases", "seed", "repetitions", "design"}
)
INSTRUCTION = "Reply with only a JSON object:"
SAMPLES = 6
EMPTY: dict[str, JsonValue] = {"summary": None, "samples": [], "counts": None}
LEXICONS = list(lexicons.available())

Draft = dict[str, Any]
Piece = tuple[str, str | None]


class Builder(anywidget.AnyWidget):
    """Write a scenario spec from an example prompt, with a live preview.

    Show it in a notebook, select text to make a variable, choose the scale of what varies and
    which answer is correct, and ``save`` the YAML. Every edit is also a method, so the widget
    is optional. ``prompts`` lists every variant the spec asks.
    """

    _esm = SCRIPT
    state = traitlets.Dict().tag(sync=True)
    request = traitlets.Dict().tag(sync=True)

    def __init__(self, prompt: str = "", *, name: str = "scenario") -> None:
        super().__init__()
        self._draft: Draft = {"name": name, "prompt": _escape(prompt)}
        self._saved: str | None = None
        self._history: list[Draft] = []
        self.observe(self._requested, names="request")
        self._refresh()

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> Builder:
        """A builder editing a spec: a YAML file, or a shipped spec by name, such as pressure."""
        found = Path(path)
        draft = read_yaml(found if found.suffix in SPECS or found.is_file() else spec(str(path)))
        if not isinstance(draft, dict):
            raise SpecError(f"{path} does not hold a spec.")
        for slot in cast(Draft, draft).get("slots", {}).values():
            filled(slot)
        for text in _texts(cast(Draft, draft).get("prompt", "")):
            _pieces(text)
        builder = cls()
        builder._draft = cast(Draft, draft)
        builder._history = []
        builder._refresh()
        return builder

    @property
    def draft(self) -> Draft:
        """The spec as written so far, valid or not."""
        return self._draft

    @property
    def spec(self) -> Spec:
        """The spec, once it is complete."""
        return Spec.of(self._draft)

    @property
    def prompts(self) -> DataFrame:
        """Every variant of the spec as one row, as ``Scenario.prompts`` gives it."""
        return self.spec.scenario().prompts()

    def save(self, path: str | os.PathLike[str]) -> Path:
        """Write the spec as YAML, complete or not, and return its path."""
        target = Path(path)
        try:
            text = self.spec.dump()
        except SpecError:
            text = format_yaml(self._draft)
        target.write_text(text, encoding="utf-8")
        self._saved = str(target)
        self._refresh()
        return target

    def mark(
        self,
        piece: int,
        start: int,
        end: int,
        slot: str | None = None,
        *,
        version: AxisValue | None = None,
        lexicon: str | None = None,
    ) -> None:
        """Make characters ``start`` to ``end`` of prompt piece ``piece`` a slot.

        The pieces are those of prompt version ``version``, the first by default, and only that
        version changes. An existing ``slot`` is placed there; a new one takes the selection as
        its value, which becomes a number or a boolean if it spells one, or takes the values of
        the shipped ``lexicon``.
        """
        texts = _texts(self._draft.get("prompt", ""))
        index = 0 if version is None else self._version(version)
        pieces = _pieces(texts[index])
        text, kind = pieces[piece]
        if kind is not None:
            raise ValueError("Only plain prompt text can become a variable.")
        if not text[start:end].strip():
            raise ValueError("Select some text to make a variable.")
        chosen = text[start:end]
        slots: dict[str, object] = self._draft.setdefault("slots", {})
        if lexicon is not None:
            lexicons.get(lexicon)
        name = slot if slot in slots else _free(slot or lexicon or _slug(chosen), slots)
        pieces[piece : piece + 1] = [(text[:start], None), ("", name), (text[end:], None)]
        self._at(index, _joined(pieces))
        if name not in slots:
            slots[name] = lexicon or [_scalar(chosen)]
        self._refresh()

    def remove(self, slot: str) -> None:
        """Turn ``slot`` back into the text of its first value, in every prompt version."""
        first = self._lexicon(slot).entries[0]
        labels = self._labels()
        for index, prompt in enumerate(_texts(self._draft.get("prompt", ""))):
            shown = _texted(first, labels[index] if labels else None)
            pieces = [
                (shown, None) if name == slot else (text, name) for text, name in _pieces(prompt)
            ]
            self._at(index, _joined(pieces))
        del self._draft["slots"][slot]
        self._forget(lambda name: name.partition(".")[0] == slot)
        self._refresh()

    def drop(self, slot: str, property: str) -> None:
        """Remove ``property`` from every value of ``slot``."""
        lexicon = self._lexicon(slot)
        if property not in lexicon.properties:
            raise ValueError(f"'{slot}' has no property '{property}'.")
        entries = tuple(
            entry.model_copy(
                update={"properties": {k: v for k, v in entry.properties.items() if k != property}}
            )
            for entry in lexicon.entries
        )
        self._draft["slots"][slot] = Lexicon(entries=entries).data()
        self._forget(lambda name: name == f"{slot}.{property}")
        self._refresh()

    def rename(self, slot: str, name: str) -> None:
        """Rename ``slot`` everywhere it is used."""
        self._lexicon(slot)
        if not self._available(name):
            raise ValueError(f"'{name}' is not a free slot name.")
        renamed = {slot: name}
        self._each(
            lambda prompt: _joined(
                [(text, each and renamed.get(each, each)) for text, each in _pieces(prompt)]
            )
        )
        self._draft["slots"] = {
            renamed.get(key, key): value for key, value in self._draft["slots"].items()
        }
        self._rename_uses(renamed)
        self._refresh()

    def per_version(self, slot: str, enabled: bool = True) -> None:
        """Give every value of ``slot`` one text per prompt version, or one text again."""
        lexicon = self._lexicon(slot)
        labels = self._labels()
        if enabled and not labels:
            raise ValueError("Write the prompt in versions first.")
        entries = tuple(
            entry.model_copy(
                update={
                    "text": {label: _texted(entry, labels[0]) for label in labels}
                    if enabled
                    else _texted(entry, labels[0] if labels else None)
                }
            )
            for entry in lexicon.entries
        )
        self._draft["slots"][slot] = Lexicon(entries=entries).data()
        self._refresh()

    def rows(self, slot: str, rows: Sequence[Mapping[str, JsonValue]]) -> None:
        """Replace the values of ``slot``; cells that spell numbers or booleans become them.

        A ``text`` may map each prompt version to its text.
        """
        self._lexicon(slot)
        labels = {str(label): label for label in self._labels()}
        parsed = [
            {
                key: _scalar(value)
                if key != "text"
                else {labels.get(str(name), name): text for name, text in value.items()}
                if isinstance(value, dict)
                else value
                for key, value in row.items()
            }
            for row in rows
        ]
        self._draft["slots"][slot] = Lexicon.of(cast(Lexical, parsed)).data()
        self._refresh()

    def range(self, slot: str, start: Number, stop: Number, step: Number) -> None:
        """Make the values of ``slot`` the numbers from ``start`` up to ``stop``, ``step`` apart."""
        self._lexicon(slot)
        try:
            numbers = Range.model_validate({"from": start, "to": stop, "step": step})
        except ValidationError as error:
            raise ValueError(error.errors()[0]["msg"].removeprefix("Value error, ")) from error
        self._draft["slots"][slot] = numbers.data()
        self._refresh()

    def add(self, slot: str) -> None:
        """Add a value to ``slot``: a copy of its last value under a new label."""
        entries = self._lexicon(slot).entries
        last = entries[-1]
        label = _fresh(tuple(entry.label for entry in entries))
        text = str(label) if last.text == str(last.label) else last.text
        added = Entry(label=label, text=text, properties=last.properties)
        self._draft["slots"][slot] = Lexicon(entries=(*entries, added)).data()
        self._refresh()

    def move(self, slot: str, row: int) -> None:
        """Move value ``row`` of ``slot`` one place up; at the top, it is the baseline."""
        entries = list(self._lexicon(slot).entries)
        if not 0 < row < len(entries):
            raise ValueError("Only a value below the first can move up.")
        entries[row - 1], entries[row] = entries[row], entries[row - 1]
        self._draft["slots"][slot] = Lexicon(entries=tuple(entries)).data()
        self._refresh()

    def extend(self, slot: str, property: str) -> None:
        """Give every value of ``slot`` a new ``property``, empty until edited."""
        lexicon = self._lexicon(slot)
        if not property.isidentifier() or property in {"label", "text", *lexicon.properties}:
            raise ValueError(f"'{property}' is not a free property name.")
        entries = tuple(
            entry.model_copy(update={"properties": {**entry.properties, property: ""}})
            for entry in lexicon.entries
        )
        self._draft["slots"][slot] = Lexicon(entries=entries).data()
        self._refresh()

    def vary(self, attribute: str, scale: Scale | None) -> None:
        """Vary ``attribute`` on ``scale``, or stop varying it with ``None``."""
        if scale is not None and scale not in get_args(Scale):
            raise ValueError(f"'{scale}' is not a scale; use nominal, ordinal, or numeric.")
        entries: Draft = self._draft.setdefault("vary", {})
        entry = entries.get(attribute)
        if scale is None:
            entries.pop(attribute, None)
        elif isinstance(entry, dict):
            entry["scale"] = scale
        else:
            entries[attribute] = scale
        self._refresh()

    def versions(self, name: str | None, labels: Sequence[AxisValue] = ()) -> None:
        """Write the whole prompt in versions: one per label, all values of attribute ``name``.

        The first label is the baseline. A new version starts as a copy of the first. Without
        a name or labels, the first version becomes the one prompt again.
        """
        prompt = self._draft.get("prompt", "")
        current, texts = _versioned(prompt) or (None, {})
        first = _texts(prompt)[0]
        if name is None or not labels:
            self._draft["prompt"] = first
            self._retext(lambda entry: _texted(entry, next(iter(texts), None)))
            if current is not None:
                self._forget(lambda attribute: attribute == current)
            self._refresh()
            return
        if name != current and not self._available(name):
            raise ValueError(f"'{name}' is not a free name.")
        parsed = [cast(AxisValue, _scalar(label)) for label in labels]
        if len({json.dumps(label) for label in parsed}) != len(parsed):
            raise ValueError("Version labels must be unique.")
        self._draft["prompt"] = {name: {label: texts.get(label, first) for label in parsed}}
        self._retext(lambda entry: {label: _texted(entry, label) for label in parsed})
        if current is not None and current != name:
            self._rename_uses({current: name})
        self._refresh()

    def version(self, label: AxisValue, text: str) -> None:
        """Set the text of prompt version ``label``, written like ``edit("prompt", ...)``."""
        versioned = _versioned(self._draft.get("prompt"))
        if versioned is None:
            raise ValueError("The prompt has no versions.")
        name, texts = versioned
        if label not in texts:
            raise ValueError(f"No prompt version is labeled {label!r}.")
        _pieces(text)
        self._draft["prompt"] = {name: {**texts, label: text}}
        self._refresh()

    def answer(
        self,
        field: str | None,
        choices: Sequence[AxisValue],
        correct: AxisValue
        | Mapping[str, Mapping[AxisValue, AxisValue]]
        | Sequence[Mapping[str, JsonValue]]
        | None = None,
        *,
        pattern: str | None = None,
    ) -> None:
        """Read ``field`` of a JSON reply, or the first match of ``pattern``, one of ``choices``.

        ``correct`` is as in a spec; a table may also be given as pairs of a value and its answer.
        """
        read = {"pattern": pattern} if pattern else {"field": field}
        answer: Draft = {**read, "choices": list(choices)}
        if isinstance(correct, Mapping):
            answer["correct"] = _table(correct)
        elif isinstance(correct, list | tuple):
            answer["correct"] = [dict(rule) for rule in correct]
        elif correct is not None:
            answer["correct"] = correct
        self._draft["answer"] = answer
        self._refresh()

    def group(self, name: str, when: Mapping[str, JsonValue] | None) -> None:
        """Name the cases whose attributes match ``when``; ``None`` removes group ``name``."""
        if not name:
            raise ValueError("A group needs a name.")
        groups: Draft = self._draft.setdefault("groups", {})
        if when is None:
            groups.pop(name, None)
        else:
            groups[name] = dict(when)
        if not groups:
            del self._draft["groups"]
        self._refresh()

    def edit(self, key: str, value: JsonValue) -> None:
        """Set a top-level field such as ``name``, ``system``, or ``cases``; ``None`` clears it.

        A ``prompt`` is template text: slots in braces, and literal braces doubled. It sets the
        first version of a prompt in versions.
        """
        if key not in EDITABLE:
            raise ValueError(f"'{key}' cannot be edited; edit {', '.join(sorted(EDITABLE))}.")
        if key == "prompt":
            text = str(value or "")
            _pieces(text)
            self._at(0, text)
        elif value is None or value == "":
            self._draft.pop(key, None)
        else:
            self._draft[key] = value
        self._refresh()

    def instruct(self) -> None:
        """End the system prompt with an instruction to reply in the answer's JSON format."""
        instruction = _instruction(self._draft)
        if instruction is None:
            raise ValueError("Set the answer's field and choices first.")
        kept = [
            paragraph
            for paragraph in self._draft.get("system", "").split("\n\n")
            if paragraph.strip() and not paragraph.startswith(INSTRUCTION)
        ]
        self._draft["system"] = "\n\n".join([*kept, instruction])
        self._refresh()

    def undo(self) -> None:
        """Take back the last change."""
        if len(self._history) < 2:
            raise ValueError("Nothing to undo.")
        self._history.pop()
        self._draft = copy.deepcopy(self._history[-1])
        self._saved = None
        self._refresh()

    def _requested(self, change: Any) -> None:
        request = cast(dict[str, Any], change["new"])
        operation, arguments = request.get("operation"), request.get("arguments", {})
        if operation not in OPERATIONS:
            return
        try:
            getattr(self, operation)(**arguments)
        except (ModelscapeError, ValueError, IndexError, TypeError) as error:
            self._refresh(str(error))

    def _labels(self) -> list[AxisValue]:
        versioned = _versioned(self._draft.get("prompt"))
        return list(versioned[1]) if versioned else []

    def _version(self, label: AxisValue) -> int:
        for index, each in enumerate(self._labels()):
            if json.dumps(each) == json.dumps(label):
                return index
        raise ValueError(f"No prompt version is labeled {label!r}.")

    def _at(self, index: int, text: str) -> None:
        self._each(lambda prompt: text, only=index)

    def _retext(self, change: Callable[[Entry], str | dict[AxisValue, str]]) -> None:
        for slot, value in self._draft.get("slots", {}).items():
            lexicon = filled(value)
            if lexicon.versioned:
                entries = tuple(
                    entry.model_copy(update={"text": change(entry)}) for entry in lexicon.entries
                )
                self._draft["slots"][slot] = Lexicon(entries=entries).data()

    def _each(self, change: Callable[[str], str], only: int | None = None) -> None:
        prompt = self._draft.get("prompt", "")
        versioned = _versioned(prompt)
        if versioned is None:
            self._draft["prompt"] = change(str(prompt))
            return
        name, texts = versioned
        self._draft["prompt"] = {
            name: {
                label: change(text) if only in (None, index) else text
                for index, (label, text) in enumerate(texts.items())
            }
        }

    def _available(self, name: str) -> bool:
        versioned = _versioned(self._draft.get("prompt"))
        taken = {*self._draft.get("slots", {}), *(versioned[:1] if versioned else ())}
        return name.isidentifier() and name not in taken

    def _rename_uses(self, renamed: Mapping[str, str]) -> None:
        self._draft["vary"] = _renamed(self._draft.get("vary", {}), renamed)
        if "groups" in self._draft:
            self._draft["groups"] = {
                group: _renamed(when, renamed) for group, when in self._draft["groups"].items()
            }
        answer = self._draft.get("answer", {})
        correct = answer.get("correct")
        if isinstance(correct, dict):
            answer["correct"] = _renamed(correct, renamed)
        if isinstance(correct, list):
            answer["correct"] = [
                {**rule, "when": _renamed(rule["when"], renamed)} if "when" in rule else rule
                for rule in cast(list[dict[str, Any]], correct)
            ]

    def _lexicon(self, slot: str) -> Lexicon:
        slots: Draft = self._draft.get("slots", {})
        if slot not in slots:
            raise ValueError(f"No slot is called '{slot}'.")
        return filled(slots[slot])

    def _refresh(self, problem: str | None = None) -> None:
        if not self._history or self._history[-1] != self._draft:
            self._history.append(copy.deepcopy(self._draft))
            self._saved = None
        instruction = _instruction(self._draft)
        self.state = {
            "name": self._draft.get("name", ""),
            "system": self._draft.get("system", ""),
            "prompts": self._prompts(),
            "versions": self._versions(),
            "slots": self._slots(),
            "answer": self._answer(),
            "groups": self._groups(),
            "lexicons": cast(JsonValue, LEXICONS),
            "saved": self._saved,
            "cases": self._draft.get("cases"),
            "repetitions": self._draft.get("repetitions"),
            "instructed": instruction is not None and instruction in self._draft.get("system", ""),
            "undoable": len(self._history) > 1,
            **self._preview(problem),
        }

    def _prompts(self) -> list[JsonValue]:
        labels: list[AxisValue | None] = [*self._labels()] or [None]
        texts = _texts(self._draft.get("prompt", ""))
        return [
            {"label": label, "text": text, "pieces": self._shown(text, label)}
            for label, text in zip(labels, texts, strict=True)
        ]

    def _shown(self, prompt: str, version: AxisValue | None) -> list[JsonValue]:
        slots = self._draft.get("slots", {})
        return [
            {
                "text": text
                if slot is None or slot not in slots
                else _texted(self._lexicon(slot).entries[0], version),
                "slot": slot,
            }
            for text, slot in _pieces(prompt)
        ]

    def _versions(self) -> dict[str, JsonValue] | None:
        versioned = _versioned(self._draft.get("prompt"))
        if versioned is None:
            return None
        name, texts = versioned
        return {"name": name, "scale": self._scale(name), "labels": list(texts)}

    def _scale(self, attribute: str) -> str | None:
        vary: dict[str, str | dict[str, str]] = self._draft.get("vary", {})
        entry = vary.get(attribute)
        return entry["scale"] if isinstance(entry, dict) else entry

    def _slots(self) -> list[JsonValue]:
        shown: list[JsonValue] = []
        for slot, value in self._draft.get("slots", {}).items():
            lexicon = self._lexicon(slot)
            attributes = [slot, *(f"{slot}.{key}" for key in lexicon.properties)]
            shown.append(
                {
                    "name": slot,
                    "shipped": value if isinstance(value, str) else None,
                    "range": value if range_of(value) else None,
                    "versioned": lexicon.versioned,
                    "columns": ["label", "text", *lexicon.properties],
                    "rows": cast(
                        JsonValue,
                        [
                            [entry.label, entry.text, *entry.properties.values()]
                            for entry in lexicon.entries
                        ],
                    ),
                    "attributes": [
                        {"name": name, "scale": self._scale(name), "values": self._values(name)}
                        for name in attributes
                    ],
                }
            )
        return shown

    def _values(self, attribute: str) -> list[JsonValue]:
        slot, _, key = attribute.partition(".")
        return list(self._lexicon(slot).values(key or None))

    def _answer(self) -> dict[str, JsonValue]:
        answer = self._draft.get("answer", {})
        rules, otherwise = _rules(answer.get("correct"))
        return {
            "field": answer.get("field", ""),
            "pattern": answer.get("pattern"),
            "choices": answer.get("choices", []),
            "rules": [
                {"when": [[name, value] for name, value in when.items()], "then": then}
                for when, then in rules
            ],
            "otherwise": otherwise,
        }

    def _groups(self) -> list[JsonValue]:
        return [
            {"name": name, "when": [[attribute, value] for attribute, value in when.items()]}
            for name, when in self._draft.get("groups", {}).items()
        ]

    def _forget(self, gone: Callable[[str], bool]) -> None:
        self._draft["vary"] = {
            name: entry for name, entry in self._draft.get("vary", {}).items() if not gone(name)
        }
        if "groups" in self._draft:
            self._draft["groups"] = {
                group: when
                for group, when in self._draft["groups"].items()
                if not any(gone(name) for name in when)
            }
        answer = self._draft.get("answer", {})
        correct = answer.get("correct")
        if isinstance(correct, dict) and gone(next(iter(cast(dict[str, object], correct)))):
            del answer["correct"]
        if isinstance(correct, list):
            kept = [
                rule
                for rule in cast(list[dict[str, Any]], correct)
                if not any(gone(name) for name in rule.get("when", {}))
            ]
            if len(kept) > 1:
                answer["correct"] = kept
            elif kept:
                answer["correct"] = kept[0]["then"]
            else:
                del answer["correct"]

    def _preview(self, problem: str | None) -> dict[str, JsonValue]:
        missing = _missing(self._draft)
        if missing:
            return {**EMPTY, "problem": problem or missing}
        try:
            scenario = self.spec.scenario()
            space = scenario.task_space
            case = next(iter(space.cases))
            base = space.variant(case)
            samples = [
                space.variant(case, {axis.name: value})
                for axis in space.axes
                for value in axis.values[:2]
                if value != axis.baseline
            ][:SAMPLES]
            variants = len(list(space.variants(scenario.design.coordinates(space.coordinates))))
        except (ModelscapeError, ValueError, KeyError) as error:
            return {**EMPTY, "problem": problem or str(error)}
        shown: list[JsonValue] = [_sample("baseline", base.reference, [[base.prompt.last, "same"]])]
        for sample in samples:
            changed = {
                key: value
                for key, value in sample.coordinate.items()
                if value != base.coordinate[key]
            }
            title = ", ".join(f"{key}={value}" for key, value in changed.items())
            shown.append(
                _sample(title, sample.reference, word_diff(base.prompt.last, sample.prompt.last))
            )
        return {
            "summary": scenario.describe(),
            "samples": shown,
            "problem": problem,
            "counts": {
                "cases": len(space.cases),
                "variants": variants,
                "calls": variants * scenario.repetitions,
                "repetitions": scenario.repetitions,
            },
        }


def _versioned(prompt: object) -> tuple[str, dict[AxisValue, str]] | None:
    if not isinstance(prompt, dict):
        return None
    ((name, texts),) = cast(dict[str, dict[AxisValue, str]], prompt).items()
    return name, texts


def _texts(prompt: object) -> list[str]:
    versioned = _versioned(prompt)
    if versioned is None:
        return [str(prompt or "")]
    return list(versioned[1].values())


def _texted(entry: Entry, version: AxisValue | None) -> str:
    if isinstance(entry.text, str):
        return entry.text
    found = [text for label, text in entry.text.items() if json.dumps(label) == json.dumps(version)]
    return found[0] if found else next(iter(entry.text.values()))


def _instruction(draft: Draft) -> str | None:
    answer = draft.get("answer", {})
    if not answer.get("field") or len(answer.get("choices", [])) < 2:
        return None
    choices = " or ".join(json.dumps(choice) for choice in answer["choices"])
    return f'{INSTRUCTION} {{"{answer["field"]}": {choices}}}.'


def _sample(title: str, reference: JsonValue, parts: list[JsonValue]) -> JsonValue:
    return {"title": title, "reference": reference, "parts": parts}


def _rules(correct: object) -> tuple[list[tuple[dict[str, AxisValue], AxisValue]], JsonValue]:
    if isinstance(correct, list):
        rules = cast(list[dict[str, Any]], correct)
        conditional = [(dict(rule["when"]), rule["then"]) for rule in rules if rule.get("when")]
        last = rules[-1] if rules else {}
        return conditional, None if last.get("when") else last.get("then")
    if isinstance(correct, dict):
        ((attribute, table),) = cast(dict[str, dict[AxisValue, AxisValue]], correct).items()
        answers = list(table.values())
        otherwise = max(answers, key=answers.count) if answers else None
        return [
            ({attribute: value}, then) for value, then in table.items() if then != otherwise
        ], otherwise
    return [], cast(JsonValue, correct)


def _pieces(prompt: str) -> list[Piece]:
    pieces: list[Piece] = []
    for text, slot, _, _ in string.Formatter().parse(prompt):
        if text:
            pieces.append((text, None))
        if slot is not None:
            pieces.append(("", slot))
    return pieces


def _joined(pieces: Sequence[Piece]) -> str:
    return "".join(_escape(text) if slot is None else f"{{{slot}}}" for text, slot in pieces)


def _escape(text: str) -> str:
    return text.replace("{", "{{").replace("}", "}}")


def _slug(text: str) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())[:3]
    slug = "_".join(words) or "slot"
    return slug if slug[0].isalpha() else f"slot_{slug}"


def _free(name: str, taken: Mapping[str, object]) -> str:
    candidates = (name if number == 1 else f"{name}_{number}" for number in range(1, 1000))
    return next(candidate for candidate in candidates if candidate not in taken)


def _renamed(entry: Any, renamed: Mapping[str, str]) -> Any:
    def rename(name: str) -> str:
        slot, dot, key = name.partition(".")
        return f"{renamed.get(slot, slot)}{dot}{key}"

    if isinstance(entry, str):
        return rename(entry)
    return {rename(key): value for key, value in cast(dict[str, object], entry).items()}


def _scalar(value: JsonValue) -> JsonValue:
    return parse_scalar(value) if isinstance(value, str) else value


def _fresh(labels: tuple[AxisValue, ...]) -> AxisValue:
    first = labels[0]
    if isinstance(first, bool):
        raise ValueError("A slot of true and false has no room for another value.")
    if isinstance(first, int | float):
        return max(cast(tuple[int | float, ...], labels)) + 1
    return _free(str(labels[-1]), {str(label): None for label in labels})


def _table(
    correct: Mapping[str, Mapping[AxisValue, AxisValue]],
) -> dict[str, dict[AxisValue, AxisValue]]:
    return {attribute: dict(table) for attribute, table in correct.items()}


def _missing(draft: Draft) -> str | None:
    answer = draft.get("answer", {})
    if not draft.get("slots"):
        return "Select text in the prompt to make a variable."
    if not draft.get("vary"):
        return "Choose what to vary, and its scale."
    read = answer.get("field") or answer.get("pattern")
    if not read or len(answer.get("choices", [])) < 2 or "correct" not in answer:
        return "Set the answer: the reply field, its choices, and which one is correct."
    correct = answer["correct"]
    if isinstance(correct, list) and (not correct or "when" in correct[-1]):
        return "Choose the answer otherwise."
    return None
