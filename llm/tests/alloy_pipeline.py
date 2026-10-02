"""A loki.process pipeline read out of an `.alloy` file and run on log lines.

Alloy cannot run one module's stages from a unit test, so this reads the
module's own stage blocks and applies them in order with Python's `re`, the
way loki.process does. It models only the stages the logging modules use:
multiline, replace, match (with drop), regex, template, labels, static_labels
and output. Anything else, and any template or selector shape it does not
model, raises, so the model cannot silently drift from the module.

The behaviours of loki.process that decided past mistakes are modelled on
purpose: a regex that finds nothing leaves the values an earlier stage
extracted in place, and a block whose selector passes a line its expression
misses would still stamp its labels, so that is an error here.

Go's RE2 and Python's `re` agree on the constructs the modules use, except
that RE2 spells end-of-text `\\z` where Python spells it `\\Z`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re

TOKEN = re.compile(r'\s+|//[^\n]*|"(?:[^"\\]|\\.)*"|[A-Za-z_][\w.]*|-?\d+|[{}=,\[\]]')
STRING = r'"((?:[^"\\]|\\.)*)"'
FILTER = re.compile(rf"(\|=|!=|\|~|!~)\s*{STRING}")
MATCHER = re.compile(rf'(\w+)\s*(=~|!~|!=|=)\s*{STRING}')


def go_regex(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern.replace("\\z", "\\Z"))


@dataclass
class Block:
    name: str
    label: str | None = None
    attrs: dict[str, object] = field(default_factory=dict)
    children: list[Block] = field(default_factory=list)


def tokens(text: str) -> list[str]:
    found = []
    position = 0
    while position < len(text):
        match = TOKEN.match(text, position)
        if not match:
            raise ValueError(f"cannot tokenise at {text[position:position + 40]!r}")
        position = match.end()
        if not match.group().isspace() and not match.group().startswith("//"):
            found.append(match.group())
    return found


def alloy_string(token: str) -> str:
    return json.loads(token)


class Parser:
    def __init__(self, text: str) -> None:
        self.tokens = tokens(text)
        self.position = 0

    def peek(self) -> str | None:
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def take(self) -> str:
        token = self.tokens[self.position]
        self.position += 1
        return token

    def blocks(self, until_close: bool) -> list[Block]:
        found: list[Block] = []
        while self.peek() is not None and self.peek() != "}":
            found.append(self.block())
        if until_close:
            assert self.take() == "}"
        return found

    def block(self) -> Block:
        name = self.take()
        label = alloy_string(self.take()) if self.peek().startswith('"') else None
        assert self.take() == "{", f"{name} is not followed by a block"
        block = Block(name, label)
        while self.peek() != "}":
            if self.tokens[self.position + 1] == "=":
                key = self.take()
                self.take()
                block.attrs[key] = self.value()
            else:
                block.children.append(self.block())
        self.take()
        return block

    def value(self) -> object:
        token = self.take()
        if token.startswith('"'):
            return alloy_string(token)
        if token == "{":
            values: dict[str, object] = {}
            while self.peek() != "}":
                key = self.take()
                assert self.take() == "="
                values[key] = self.value()
                if self.peek() == ",":
                    self.take()
            self.take()
            return values
        return int(token) if re.fullmatch(r"-?\d+", token) else token  # a number, or a reference such as argument.forward_to.value


def parse(text: str) -> list[Block]:
    return Parser(text).blocks(until_close=False)


@dataclass
class Selector:
    matchers: list[tuple[str, str, str]]
    filters: list[tuple[str, str]]

    @classmethod
    def read(cls, text: str) -> Selector:
        braces = re.match(r"\s*\{([^}]*)\}", text)
        assert braces, f"selector without labels: {text!r}"
        matchers = [(n, op, json.loads(f'"{v}"')) for n, op, v in MATCHER.findall(braces.group(1))]
        filters = [(op, json.loads(f'"{literal}"')) for op, literal in FILTER.findall(text[braces.end():])]
        return cls(matchers, filters)

    def passes(self, line: str, labels: dict[str, str]) -> bool:
        for name, op, wanted in self.matchers:
            value = labels.get(name, "")
            if op == "=" and value != wanted:
                return False
            if op == "!=" and value == wanted:
                return False
            if op == "=~" and not re.fullmatch(wanted, value):
                return False
            if op == "!~" and re.fullmatch(wanted, value):
                return False
        for op, wanted in self.filters:
            if op == "|=":
                found = wanted in line
            elif op == "!=":
                found = wanted not in line
            elif op == "|~":
                found = go_regex(wanted).search(line) is not None
            else:
                found = go_regex(wanted).search(line) is None
            if not found:
                return False
        return True


@dataclass
class Entry:
    """One stored log entry: its line as stored and the labels the pipeline gave it."""

    text: str
    labels: dict[str, str]

    @property
    def level(self) -> str | None:
        return self.labels.get("detected_level")

    @property
    def kind(self) -> str:
        return self.labels.get("llm_line", "")

    @property
    def fields(self) -> dict[str, str]:
        return {k: v for k, v in self.labels.items() if k.startswith("llm_") and k != "llm_line"}


class Dropped(Exception):
    pass


class Pipeline:
    """The stages of one `loki.process` block, run on the lines of one stream."""

    def __init__(self, process: Block, service: str) -> None:
        self.stages = process.children
        self.service = service

    @classmethod
    def from_module(cls, path: Path, process_label: str = "this") -> Pipeline:
        (declare,) = [b for b in parse(path.read_text()) if b.name == "declare"]
        (process,) = [b for b in declare.children if b.name == "loki.process" and b.label == process_label]
        (outer,) = [s for s in process.children if s.name == "stage.match"]
        service = re.search(r'service="([^"]+)"', str(outer.attrs["selector"])).group(1)
        return cls(outer, service)

    def multiline_firstline(self) -> re.Pattern[str] | None:
        for stage in self.stages:
            if stage.name == "stage.multiline":
                return go_regex(str(stage.attrs["firstline"]))
        return None

    def entries(self, lines: list[str]) -> list[str]:
        """Physical lines grouped into entries.

        A line that does not start an entry continues the one before it, but
        only when that one is open: a stray line with no entry before it is an
        entry of its own, as loki.process emits it.
        """
        firstline = self.multiline_firstline()
        grouped: list[str] = []
        open_entry = False
        for line in lines:
            starts = firstline is None or firstline.search(line) is not None
            if starts or not open_entry:
                grouped.append(line)
                open_entry = starts and firstline is not None
            else:
                grouped[-1] += "\n" + line
        return grouped

    def process(self, lines: list[str]) -> list[Entry]:
        out = []
        for line in self.entries(lines):
            try:
                out.append(self.run(line))
            except Dropped:
                pass
        return out

    def run(self, line: str) -> Entry:
        state = State(line, {"service": self.service})
        self.stage_list(self.stages, state)
        return Entry(state.line, state.labels)

    def stage_list(self, stages: list[Block], state: State) -> None:
        for stage in stages:
            handler = getattr(self, "stage_" + stage.name.removeprefix("stage.").replace(".", "_"), None)
            if handler is None:
                raise NotImplementedError(f"{stage.name} is not modelled")
            handler(stage, state)

    def stage_multiline(self, stage: Block, state: State) -> None:
        pass  # applied when lines are grouped into entries

    def stage_match(self, stage: Block, state: State) -> None:
        if Selector.read(str(stage.attrs["selector"])).passes(state.line, state.labels):
            if stage.attrs.get("action") == "drop":
                raise Dropped
            self.stage_list(stage.children, state)

    def stage_replace(self, stage: Block, state: State) -> None:
        pattern = go_regex(str(stage.attrs["expression"]))
        replacement = str(stage.attrs["replace"])
        state.line = pattern.sub(lambda m: m.group(0).replace(m.group(1), replacement), state.line)

    def stage_regex(self, stage: Block, state: State) -> None:
        source = stage.attrs.get("source")
        subject = state.line if source is None else state.extracted[str(source)]
        found = go_regex(str(stage.attrs["expression"])).search(subject)
        assert found, f"expression {stage.attrs['expression']!r} misses a line its selector passed: {subject[:100]!r}"
        state.extracted.update({k: v for k, v in found.groupdict().items() if v is not None})

    def stage_template(self, stage: Block, state: State) -> None:
        source = str(stage.attrs["source"])
        state.extracted[source] = render(str(stage.attrs["template"]), state.extracted, state.extracted.get(source, ""))

    def stage_labels(self, stage: Block, state: State) -> None:
        for label, key in dict(stage.attrs["values"]).items():
            value = state.extracted.get(str(key), "")
            if value:
                state.labels[label] = value

    def stage_static_labels(self, stage: Block, state: State) -> None:
        for label, value in dict(stage.attrs["values"]).items():
            assert not (label == "llm_line" and state.labels.get(label)), (
                f"two kinds for one line: {state.labels[label]} and {value}: {state.line[:100]!r}"
            )
            state.labels[str(label)] = str(value)

    def stage_output(self, stage: Block, state: State) -> None:
        state.line = state.extracted[str(stage.attrs["source"])]


@dataclass
class State:
    line: str
    labels: dict[str, str]
    extracted: dict[str, str] = field(default_factory=dict)


def render(template: str, extracted: dict[str, str], value: str) -> str:
    """The template forms the modules use: `{{ .name }}` substitution and an
    if/else-if chain on `.Value` ending in an else."""
    if "{{ if" in template:
        chain = re.findall(r'\{\{ (?:else )?if eq \.Value "([^"]*)" \}\}([^{]*)', template)
        fallback = re.search(r"\{\{ else \}\}([^{]*)\{\{ end \}\}", template)
        assert chain and fallback, f"unsupported template {template!r}"
        return dict(chain).get(value, fallback.group(1))

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        assert name in extracted, f"template uses {name}, which no stage extracted"
        return extracted[name]

    unknown = re.sub(r"\{\{ \.(\w+) \}\}", "", template)
    assert "{{" not in unknown, f"unsupported template {template!r}"
    return re.sub(r"\{\{ \.(\w+) \}\}", substitute, template)
