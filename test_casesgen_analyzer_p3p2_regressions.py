#!/usr/bin/env python3
"""Regression source: the three root causes that made the compiled
`Tools/cases_generator/analyzer.py` diverge from CPython on
`Python/bytecodes.c` after every compile blocker was resolved (see
COMPILE_FAIL_Tools_cases_generator_analyzer-part3-part2, doc deleted with the fix).

  (b) Generator keyword padding. A generator with defaults, called with a
      keyword targeting a later slot (`tokenize(src, filename=filename)` on
      `def tokenize(src, line=1, filename="")`), must pack the keyword into
      ITS OWN parameter slot. The start-call emission packed it into the
      first unfilled slot (`line`) and padded the keyword's own slot with
      the default, so the body read bytes of the filename pointer as the
      line number. Pinned by `gen("S", filename="F")`: pre-fix the printed
      line number is "F" and the filename is ""; post-fix it is 1 and "F".

  (a) `__repr__` wrapper. A class that has fields AND a user `__repr__`
      must print through the user method (lexer.py's `Token` shape). The
      reflection dispatch emitted a field dump instead of the wrapper that
      calls `__repr__`. Pinned the way the analyzer reaches it
      (Properties.dump's `escaping_calls`: an `EscapingCall` dataclass with
      a single `Token` field, whose field dump reprs the field through the
      type-tag dispatch, plus the `SimpleStmt.contents` list of Tokens
      whose element repr goes through the element shim).

  (c) Shadowed builtins as values. Module-level `hex = ...` / `float = ...`
      shadow the same-named builtins in this namespace; passed as call
      arguments they must pack the string globals, not the builtins' C
      function pointers (`_funcptr_mojo_hex` / `_funcptr_mojo_make_float`,
      whose machine-code bytes the string machinery then read). Pinned by
      `choice(hex, float)` on a varargs function (lexer.py's `choice`
      shape), the only spelling that packed the value through a MojoList.

Run through test_casesgen_analyzer_p3p2_regressions_build.py: the compiled
binary's stdout must be byte-identical to CPython's on this source.
"""
from dataclasses import dataclass


def gen(src, line=1, filename=""):
    yield "g " + src + " " + str(line) + " " + filename
    yield "g " + str(line) + " " + filename


def section_gen():
    for t in gen("S", filename="F"):
        print(t)


@dataclass
class Token:
    kind: str
    text: str

    def __repr__(self):
        return self.kind + "(" + repr(self.text) + ")"


@dataclass
class Stmt:
    contents: list[Token]


@dataclass
class EscapingCall:
    stmt: Stmt
    call: Token
    kills: object = None


@dataclass
class Properties:
    escaping_calls: dict[int, EscapingCall]

    def dump(self, indent: str) -> None:
        text = "escaping_calls:\n"
        for tkns in self.escaping_calls.values():
            text += f"{indent}    {tkns}\n"
        print(indent, text, sep="")


def section_repr():
    print(Token("NUMBER", "0xFF"))
    props = Properties({1: EscapingCall(Stmt([Token("INT", "159")]), Token("IDENTIFIER", "x"), None)})
    props.dump("    ")


hex = "HEXSTR"
float = "FLOATSTR"


def choice(*opts):
    return "|".join("(%s)" % opt for opt in opts)


def section_shadow():
    print(choice(hex, float))
    print("hex:", hex)
    print("float:", float)


section_gen()
section_repr()
section_shadow()
