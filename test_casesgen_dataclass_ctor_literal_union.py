"""Regression for the cases-generator analyzer compile bugs
(COMPILE_FAIL_Tools_cases_generator_analyzer, doc deleted with the fix), root causes
#2A / #2B / #3. The shapes mirror Tools/cases_generator/parsing.py:

  #2A  `kind: Literal["inst", "op"]` — an all-string-literal `Literal[...]`
       annotation must lower to `char *` (not a boxed int), so `a.kind`
       reads back the stored string.
  #2B  `Node.context` is `field(init=False, ...)` on the base class, so
       every dataclass child (InstHeader/InstDef/Pseudo) must exclude
       `context` from the synthesized __init__ positional mapping: the
       six positional args of `InstDef(...)` land on its six REAL fields
       (annotations..block), not on a leading context slot.
  #3   `describe(op: InstDef | Pseudo)` — a union parameter over two
       compiled structs must box to int64_t so member access dispatches
       on the runtime type tag, instead of reading one member's layout
       with the other's offsets.

The compiled build's stdout must be byte-identical to
`python3 <this file>` (and to the interpreter path `fire.py run`).
"""

from dataclasses import dataclass, field
from typing import Literal, cast


class Context:
    def __init__(self, begin: int, end: int):
        self.begin = begin
        self.end = end


@dataclass
class Node:
    context: Context | None = field(init=False, compare=False, default=None)


@dataclass
class InstHeader(Node):
    annotations: list[str]
    kind: Literal["inst", "op"]
    name: str
    inputs: list[str]
    outputs: list[str]


@dataclass
class InstDef(Node):
    annotations: list[str]
    kind: Literal["inst", "op"]
    name: str
    inputs: list[str]
    outputs: list[str]
    block: str


@dataclass
class Pseudo(Node):
    name: str
    inputs: list[str]
    outputs: list[str]
    flags: list[str]
    targets: list[str]
    as_sequence: bool


def make_inst(name: str, kind: str, inputs: list[str]) -> InstDef:
    kind2 = cast(Literal["inst", "op"], kind)
    return InstDef(
        ["annot"],
        kind2,
        name,
        inputs,
        ["out"],
        "{ ... }",
    )


def describe(op: InstDef | Pseudo) -> str:
    match op:
        case InstDef():
            return "inst:" + op.name + ":" + op.kind
        case Pseudo():
            return "pseudo:" + op.name + ":" + str(len(op.flags))
        case _:
            return "?"


def main() -> str:
    a = make_inst("STORE", "inst", ["a", "b"])
    b = Pseudo("SETUP_ARGS", ["i"], ["o"], ["f1"], [], False)
    lines = []
    lines.append(describe(a))
    lines.append(describe(b))
    lines.append(a.kind)
    lines.append(a.annotations[0])
    lines.append(a.name)
    lines.append(a.inputs[1])
    lines.append(a.outputs[0])
    lines.append(a.block)
    lines.append(b.name)
    lines.append("seq" if b.as_sequence else "notseq")
    lines.append("ctx=" + str(a.context))
    return "\n".join(lines)


print(main())
