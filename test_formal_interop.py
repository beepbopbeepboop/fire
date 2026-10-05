#!/usr/bin/env python3
"""INTEROP: a formal dylib, consumed by a C program and by Python `ctypes`.

A dylib is only useful if something else can call it. Every other formal suite
in this tree looks at a formal image from the INSIDE — the codegen produced
code, the proof typechecks, `python3 fire.py run` agrees with CPython — and an
interface nobody calls is an interface nothing has ever exercised. This file is
the outside. It builds a real `.dylib` per architecture, reads the C
declaration out of that library's own manifest, and calls every export three
ways:

  1. from a C program compiled by `cc` (and by gcc where there is one), linked
     against the library, with the free functions' declarations GENERATED FROM
     THE MANIFEST, so the manifest is the thing under test rather than a
     hand-written transcription of it;
  2. from `ctypes` — in an arm64 Python here, and in an x86-64 Python under
     Rosetta 2 for the x86-64 library, because an arm64 `ctypes` cannot load an
     x86-64 dylib at all;
  3. against CPython evaluating the same expression.

That third one is mechanical rather than asserted. Every case's oracle is
DERIVED from the library's own `return` statement by substituting the case's
arguments for that statement's parameters, and
`test_every_oracle_is_the_librarys_own_expression` fails when the derived text
and the written one differ. "CPython running the same source" has to mean more
than "the author typed the number twice", and this is what it means here.

The corpus covers the rows `doc/ABI.md` states for a formal boundary: 64-bit
integers (including past the argument registers, into the caller's frame), narrow
signed and unsigned integers, `Bool`, `String`, `Float64`, `Optional` with its
niche word, a struct receiver passed BY POINTER (a multi-field frame and a
one-word cell), and the mutator-return ABI.

`doc/ABI.md` is CHECKED here, not restated. Each assertion names the row it
checks, and the rows that live in code rather than prose are asked of the code:
the receiver table is transcribed into `METHOD_DECLARATIONS` and re-derived from
`reflect`'s own method signature and from the emitter's own receiver rule
(`model.struct_is_one_field` + `model.receiver_writeback_name`); the `Optional`
niches are asked of `model.optional_none_word`; the word convention is asserted
against the manifest the library actually published.

    python3 test_formal_interop.py [-v]
"""

import argparse
import ctypes
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from exec_budget import COMPILE_TIMEOUT_S, LINK_TIMEOUT_S, RUN_TIMEOUT_S  # noqa: E402
FIRE = os.path.join(HERE, "fire.py")

# The shared per-child budgets (`exec_budget.py`), not literals: a `timeout=`
# spelled here is a budget this tree has already decided how to size, and a
# literal is how a timeout that means "compiler bug" spreads from file to file.
# A library BUILD is a compile, a `cc` link is a link, and running a client is
# a run.
REC = "="                       # a case's label, REC, its word(s)

ARM64 = "arm64"
X86_64 = "x86_64"

_MODEL = None


class TestFailure(Exception):
    pass


def check(condition, message):
    if not condition:
        raise TestFailure(message)


def f64_word(value) -> int:
    """The 64-bit word a `Float64` crosses a formal boundary as."""
    return struct.unpack("<Q", struct.pack("<d", float(value)))[0]


def mask(word) -> int:
    """A value as a client prints it: 64 bits, unsigned."""
    return int(word) & 0xFFFFFFFFFFFFFFFF


def formal_model():
    """`formal.model`, imported on demand and once.

    Three checks need it and each needs it for the same reason: it is asking the
    CODE a row of `doc/ABI.md` states rather than restating the row. The
    `Optional` niche table, the receiver convention, and the name a method is
    exported under are all facts the model owns, and a test that hard-codes any
    of them keeps passing after the code stops agreeing with it. Imported lazily
    so this file's module-level work — the corpus, the cases, the two client
    generators — does not pay for the backend.
    """
    global _MODEL
    if _MODEL is None:
        sys.path.insert(0, HERE)
        import formal.model
        _MODEL = formal.model
    return _MODEL


# ── the library under test ─────────────────────────────────────────────────
#
# One module, so one dylib per architecture, so a client's whole view of the
# boundary is one manifest. Every function is ANNOTATED: `doc/ABI.md`'s
# declaration for an export is read out of the annotation, so an unannotated
# function publishes `void` and would be testing something else. Every body is a
# single `return` (the three `Optional`s have two, which is what makes them
# interesting), because the oracle is derived from that text.
#
# The PARAMETER NAMES are load-bearing and are not the obvious ones. The oracle
# substitutes a case's arguments into the body's parameter names, so a
# one-letter name that also occurs inside the method being called rewrites the
# method: `def str_starts(s, p): return s.startswith(p)` becomes
# `"hello"."hello"tart"hello"with("he")`, because `s` is a letter of
# `startswith`. `text` and `needle` occur nowhere else in their own bodies.

CORPUS = '''\
struct Point:
  var x: Int
  var y: Int

  def sum(self) -> Int:
    return self.x + self.y

  def bump(mut self, by: Int) -> Int:
    self.x = self.x + by
    return self.x


struct Cell:
  var _value: Int

  def get(self) -> Int:
    return self._value

  def bump(mut self, by: Int) -> Int:
    self._value = self._value + by
    return self._value


def int_add(a: Int, b: Int) -> Int:
  return a + b


def int_many(a: Int, b: Int, c: Int, d: Int, e: Int, f: Int, g: Int, h: Int, i: Int, j: Int) -> Int:
  return a + b * 2 + c * 3 + d * 4 + e * 5 + f * 6 + g * 7 + h * 8 + i * 9 + j * 10


def i32_add(a: Int32, b: Int32) -> Int32:
  return a + b


def u32_add(a: UInt32, b: UInt32) -> UInt32:
  return a + b


def i8_add(a: Int8, b: Int8) -> Int8:
  return a + b


def bool_not(a: Bool) -> Bool:
  return not a


def str_echo(text: String) -> String:
  return text


def str_starts(text: String, needle: String) -> Bool:
  return text.startswith(needle)


def str_count(text: String, needle: String) -> Int:
  return text.count(needle)


def float_add(a: Float64, b: Float64) -> Float64:
  return a + b


def float_three(a: Float64, b: Float64, c: Float64) -> Float64:
  return a + b + c


def opt_str(v: String, present: Bool) -> Optional[String]:
  if present:
    return v
  return None


def opt_i32(v: Int32, present: Bool) -> Optional[Int32]:
  if present:
    return v
  return None


def opt_bool(v: Bool, present: Bool) -> Optional[Bool]:
  if present:
    return v
  return None
'''


# doc/ABI.md §"The formal backend's receiver convention", transcribed. A
# receiver crosses a boundary by POINTER for a struct of two or more fields and
# for a mutating method (whose one-word cell the callee writes through), and BY
# VALUE for a plain `self` on a one-field struct. The POINTER is spelled
# `struct Struct *` because that is what `reflect` publishes for a method (with
# the tag a C declaration needs) and because a client can then declare the
# struct itself — the frame is 8-byte slots, one per
# field, in declaration order, so `struct Point { int64_t x; int64_t y; }` IS
# the frame. These are the declarations this file's clients bind the four
# methods through, because the manifest publishes `Struct.method` where a
# declaration belongs (`bugs/FORMAL_a_method_export_publishes_no_c_declaration.md`).
METHOD_DECLARATIONS = {
    # Two fields: the address of a frame of 8-byte slots, one per field.
    "Point.sum": "int64_t (struct Point *)",
    "Point.bump": "int64_t (struct Point *, int64_t)",
    # One field, plain `self`: the value itself, in a register.
    "Cell.get": "int64_t (int64_t)",
    # One field, `mut self`: the address of the one-word cell.
    "Cell.bump": "int64_t (struct Cell *, int64_t)",
}


# ── the cases ──────────────────────────────────────────────────────────────
#
# `args` are ABI-LEVEL values: ("i", int) one word, ("s", str) a `char *`,
# ("d", float) a `Float64` AS ITS IEEE-754 BIT PATTERN.
#
# `recv` spells the receiver the way the table above does:
#   {"by": "frame", "words": [...]}   a multi-field struct, by address
#   {"by": "cell",  "word": n}        a one-field struct's mutator, by address
#   {"by": "value", "word": n}        a one-field struct's plain `self`
#
# `py` is the oracle: the library's own return expression with this case's
# arguments substituted for its parameters, in Python. Derived and checked
# rather than trusted — see `oracle_text`.
#
# `want` is the expected list of words: the RETURN first, then the receiver's
# words as they stand AFTER the call, because a mutator's write is part of its
# answer and that is the whole claim of the mutator-return ABI. Omitted, the
# receiver's words are the ones the call went in with.
#
# `ret_index` picks which `return` of a multi-return function this case reaches.
#
# `result` says how the RETURN is compared:
#   "word"      (default) the raw 64-bit word;
#   "str"       one word, 1 iff the returned `char *` holds exactly `py`, or is
#               NULL when `py` is `None` — so neither consumer owns the string;
#   "ptr_is_arg"  one word, 1 iff the returned pointer IS the first `char *`
#               argument, which is the only way to see the `String` row's
#               ownership claim (there is no copy, so a client that freed the
#               result would be freeing its own string).

CASES = [
    dict(name="int_add", args=[("i", 40), ("i", 2)], py="40 + 2", want=[42]),

    # Ten arguments. arm64 has eight integer argument registers and x86-64 six,
    # so this case's last words travel in the CALLER'S FRAME on both. What is
    # checked is that the callee reads them there, in order, and gave its own
    # frame back — a callee that clobbered a callee-saved register or left the
    # stack misaligned shows up here as a wrong sum.
    dict(name="int_many",
         args=[("i", v) for v in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)],
         py="1 + 2 * 2 + 3 * 3 + 4 * 4 + 5 * 5 + 6 * 6 + 7 * 7 + 8 * 8"
            " + 9 * 9 + 10 * 10", want=[385]),

    # A narrow SIGNED integer crosses as the low bits of a word and the callee
    # SIGN-extends them (`sxtw x19, w19` on arm64, `movsxd` on x86-64), so -5 is
    # the word 0xFFFF...FB and not the word 4294967291.
    dict(name="i32_add", args=[("i", -5), ("i", -6)], py="-5 + -6", want=[-11]),

    # …and a narrow UNSIGNED one ZERO-extends (`and x19, x19, #0xffffffff`), so
    # 4000000000 is its own word rather than a sign-extended -294967296.
    dict(name="u32_add", args=[("i", 4000000000), ("i", 100)],
         py="4000000000 + 100", want=[4000000100]),

    dict(name="i8_add", args=[("i", 100), ("i", 20)], py="100 + 20",
         want=[120]),
    dict(name="bool_not", args=[("i", 1)], py="not 1", want=[0]),

    # A `String` is a bare `char *`.
    dict(name="str_echo", args=[("s", "hello")], py='"hello"',
         result="str", want=[1]),
    # …and `str_echo` returns the pointer it was given: no copy, no allocation,
    # nothing to free. `test_a_string_return_is_the_callers_pointer` is the
    # same fact seen as an identity rather than as a value.
    dict(name="str_echo", args=[("s", "hello")], py='"hello"',
         result="ptr_is_arg", want=[1]),
    dict(name="str_starts", args=[("s", "hello"), ("s", "he")],
         py='"hello".startswith("he")', want=[1]),
    dict(name="str_count", args=[("s", "banana"), ("s", "na")],
         py='"banana".count("na")', want=[2]),

    # ── the Float64 row ──
    # doc/ABI.md's scalar table says `Float64` is a C `double`, and that is what
    # the COMPILED path implements. A formal boundary is one 64-bit WORD: the
    # callee reads the general-purpose argument registers and returns in the
    # general-purpose one, using the FP registers only inside its own arithmetic
    # (`fmov d0, x0; fadd d0, d0, d1; fmov x0, d0`). A client that followed the
    # scalar table put 1.5 and 2.25 in the FP registers and read the answer from
    # the FP return register, and got 2.14e-314 on arm64 and 6.42e-314 on
    # x86-64 where CPython says 3.75. So the client passes the bit pattern and
    # reads the bit pattern back.
    dict(name="float_add", args=[("d", 1.5), ("d", 2.25)], py="1.5 + 2.25",
         want=[f64_word(3.75)]),
    dict(name="float_three", args=[("d", 1.5), ("d", 2.25), ("d", 0.25)],
         py="1.5 + 2.25 + 0.25", want=[f64_word(4.0)]),

    # ── the Optional rows ──
    # `None` is a NICHE word chosen per payload type, not 0 for every payload.
    # For a `String` it is 0 (an address no program holds); for an `Int32` it is
    # `1 << 32`, which is 33 bits and is therefore the whole reason a
    # declaration reading `w0` cannot implement this row; for a `Bool` it is 2.
    dict(name="opt_str", args=[("s", "hello"), ("i", 1)], py='"hello"',
         result="str", want=[1]),
    dict(name="opt_str", args=[("s", "hello"), ("i", 0)], py="None",
         ret_index=1, result="str", niche="String"),
    dict(name="opt_i32", args=[("i", 7), ("i", 1)], py="7", want=[7]),
    dict(name="opt_i32", args=[("i", 7), ("i", 0)], py="None", ret_index=1,
         niche="Int32"),
    dict(name="opt_bool", args=[("i", 1), ("i", 1)], py="1", want=[1]),
    dict(name="opt_bool", args=[("i", 1), ("i", 0)], py="None", ret_index=1,
         niche="Bool"),

    # ── the receiver rows, and the mutator-return ABI ──
    dict(name="Point.sum", recv=dict(by="frame", words=[10, 20]),
         py="10 + 20", want=[30, 10, 20]),
    dict(name="Point.bump", recv=dict(by="frame", words=[10, 20]),
         args=[("i", 5)], py="10 + 5", want=[15, 15, 20]),
    dict(name="Cell.get", recv=dict(by="value", word=10), py="10", want=[10]),
    dict(name="Cell.bump", recv=dict(by="cell", word=10), args=[("i", 5)],
         py="10 + 5", want=[15, 15]),
]


# ── reading the corpus, to derive an oracle from it ────────────────────────

def corpus_free_params(name):
    """`[param names]` of `def name(…)`.

    The ANNOTATION is dropped, because the substitution below is keyed on the
    name: `def i32_add(a: Int32, b: Int32)` binds `a` and `b`, and a key of
    `"a: Int32"` matches nothing in a body that says `a + b`.
    """
    match = re.search(rf"^def {re.escape(name)}\(([^)]*)\)", CORPUS, re.M)
    check(match is not None, f"the corpus declares no function {name}")
    return [p.split(":")[0].strip() for p in match.group(1).split(",")
            if p.strip()]


def corpus_struct(struct_name):
    """The text of `struct Struct`'s body, fields and methods together."""
    match = re.search(rf"^struct {re.escape(struct_name)}:\n(.*?)(?=^\S)",
                      CORPUS, re.M | re.S)
    check(match is not None, f"the corpus declares no struct {struct_name}")
    return match.group(1)


def corpus_method_params(struct_name, method):
    """`[argument names]` of a method, RECEIVER EXCLUDED.

    The receiver is written `self`, `mut self`, `out self` or `inout self` —
    doc/ABI.md's list of the conventions — and it is not one of the call's
    arguments: the case table passes it separately, in the `recv` field, in the
    shape the receiver convention says it travels. Leaving it in the list would
    pair the case's first ARGUMENT with the receiver's name and silently derive
    the oracle from the wrong substitution.
    """
    match = re.search(rf"^  def {re.escape(method)}\(([^)]*)\)",
                      corpus_struct(struct_name), re.M)
    check(match is not None,
          f"the corpus's {struct_name} declares no method {method}")
    names = [p.split(":")[0].strip() for p in match.group(1).split(",")
             if p.strip()]
    check(names and names[0].split()[-1] == "self",
          f"{struct_name}.{method} does not declare a receiver first "
          f"({names}); every convention here ends in `self`")
    return names[1:]


def corpus_fields(struct_name):
    """`[field names]` of `struct Struct`, in declaration order.

    Declaration order is the whole of it: a multi-field receiver is "a frame of
    8-byte slots, one per field, in declaration order" (doc/ABI.md), so this
    list is what says which C struct member is `x` and which is `y` — and the C
    client generates its `struct Point` from it.
    """
    return re.findall(r"^  var (\w+):", corpus_struct(struct_name), re.M)


def corpus_returns(name):
    """`[return expressions]` of a free function's body, in source order."""
    block = re.search(rf"^def {re.escape(name)}\(.*?\n(.*?)(?=^def |\Z)",
                      CORPUS, re.M | re.S)
    check(block is not None, f"the corpus declares no function {name}")
    return [m.strip() for m in re.findall(r"^\s*return (.*)$",
                                          block.group(1), re.M)]


def corpus_method_statements(struct_name, method):
    """`[statement]` of a method's body, in source order.

    A statement is an assignment (`self.f = …`, with or without a type
    annotation) or a `return` expression. Both kinds are needed: see
    `oracle_text`.
    """
    block = re.search(rf"^  def {re.escape(method)}\(.*?\n(.*?)(?=^  def |\Z)",
                      corpus_struct(struct_name), re.M | re.S)
    check(block is not None,
          f"the corpus's {struct_name} declares no method {method}")
    statements = []
    for raw in block.group(1).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("return "):
            statements.append(line[len("return "):].strip())
        elif "=" in line and not line.startswith("if"):
            statements.append(line)
        else:
            raise TestFailure(
                f"{struct_name}.{method}: the oracle derivation does not know "
                f"the statement {line!r}; every statement in this corpus's "
                f"methods is an assignment or a return on purpose")
    return statements


def py_literal(kind, value) -> str:
    """`value` as CPython spells it, in a form both languages agree on."""
    if kind == "s":
        return '"%s"' % value
    if kind == "d":
        return repr(float(value))
    return str(int(value))


def substitute(text, subs):
    """`text` with every key of `subs` replaced, longest key first.

    Longest first is load-bearing and not an optimisation: a method body reads
    `self.x + self.y`, and replacing `x` before `self.x` would rewrite the
    attribute into `self.10 + self.20`.
    """
    if not subs:
        return text
    pattern = re.compile("|".join(re.escape(k) for k in
                                  sorted(subs, key=len, reverse=True)))
    return pattern.sub(lambda m: subs[m.group(0)], text)


def squash(text) -> str:
    return "".join(text.split())


def oracle_text(case):
    """`case`'s return expression as the library wrote it, in Python.

    A case reaches one of the corpus's `return` statements — `ret_index` says
    which — and this substitutes the case's arguments for that statement's
    parameters. Nothing else is done to the text: the expression the library
    computes and the expression CPython evaluates are then the same characters,
    which is the strongest form of "CPython running the same source" available
    across two languages with no shared syntax.

    A METHOD body is walked statement by statement rather than read at the
    return, and the reason is the row it is here to test: a mutator is
    `self.f = <expr>` followed by `return self.f`, so the value the caller reads
    back out of the receiver is computed by an ASSIGNMENT, not by the return
    expression. Reading only the return would give the field's INCOMING value —
    `10` where the answer is `15` — and the write-back this file exists to check
    would never enter the oracle at all. So an assignment is evaluated with the
    substitutions in force and its result becomes the new substitution for the
    field it wrote, and the return is then substituted against that.
    """
    name = case["name"]
    if "." in name:
        struct_name, method = name.split(".", 1)
        subs = {}
        recv = case["recv"]
        words = recv.get("words") or [recv["word"]]
        for field, word in zip(corpus_fields(struct_name), words):
            subs[f"self.{field}"] = str(mask(word))
        for param, (kind, value) in zip(
                corpus_method_params(struct_name, method),
                case.get("args", ())):
            subs[param] = py_literal(kind, value)
        return _walk_body(corpus_method_statements(struct_name, method), subs,
                          name, case)
    body = corpus_returns(name)
    subs = dict(
        (param, py_literal(kind, value))
        for param, (kind, value) in zip(corpus_free_params(name),
                                         case.get("args", ())))
    index = case.get("ret_index", 0)
    check(index < len(body),
          f"{name}: the case reaches return #{index} and the body has "
          f"{len(body)}")
    return substitute(body[index], subs)


ASSIGNMENT_RE = re.compile(r"^(self\.\w+)\s*=\s*(.+)$")


def corpus_body_statements(case):
    """Every statement of `case`'s body, for the assignment/text check."""
    name = case["name"]
    if "." in name:
        struct_name, method = name.split(".", 1)
        return corpus_method_statements(struct_name, method)
    block = re.search(rf"^def {re.escape(name)}\(.*?\n(.*?)(?=^def |\Z)",
                      CORPUS, re.M | re.S)
    check(block is not None, f"the corpus declares no function {name}")
    return [line.strip() for line in block.group(1).splitlines()
            if line.strip()]


def _walk_body(statements, subs, name, case):
    """The case's `return` text, after applying the body's assignments."""
    index = case.get("ret_index", 0)
    seen = 0
    for statement in statements:
        assign = ASSIGNMENT_RE.match(statement)
        if assign:
            target, expression = assign.group(1), assign.group(2)
            value = eval(squash(substitute(expression, subs)),      # noqa: S307
                         {"__builtins__": {}}, {})
            subs[target] = str(mask(value))
            continue
        if seen == index:
            return substitute(statement, subs)
        seen += 1
    raise TestFailure(f"{name}: the case reaches return #{index} and the "
                      f"body has {seen}")


def oracle_value(case):
    """The word this case's return is.

    `None` is the one value Python has and this boundary does not: at the ABI an
    empty `Optional[T]` is the NICHE word for the payload type
    (`formal/model.py::optional_none_word`), so a case that reaches a
    `return None` asks the model for that word rather than having it written
    down beside the function. `test_the_optional_niches_are_the_documented_words`
    is what pins the model's table to `doc/ABI.md`'s, so the two questions stay
    separate and each has one answer.
    """
    # The result MODE is asked first, because it decides what a word MEANS: for
    # `str` and `ptr_is_arg` the word is a comparison, not the payload, and an
    # empty `Optional[String]` is the NULL pointer — which both consumers render
    # as 1 for "is what was asked for".
    if case.get("result") in ("str", "ptr_is_arg"):
        return 1
    if case.get("ret_index"):
        niche, why = formal_model().optional_none_word(case["niche"])
        check(niche is not None and not why,
              f"{case['name']}: `Optional[{case['niche']}]` has no niche word "
              f"({why}), so this case cannot state an expected answer")
        return mask(niche)
    value = eval(oracle_text(case), {"__builtins__": {}}, {})   # noqa: S307
    if isinstance(value, float):
        return f64_word(value)
    return mask(value)


def oracle_words(case):
    """The whole expected list: the return, then the receiver's words.

    A receiver passed BY VALUE is the one shape with nothing to read back: the
    callee has a copy, so the caller's word is untouched by definition and
    printing it would be asserting that twice.
    """
    recv = case.get("recv")
    head = [oracle_value(case)]
    if not recv or recv["by"] == "value":
        return head
    if "want" in case and len(case["want"]) > 1:
        return head + [mask(w) for w in case["want"][1:]]
    return head + [mask(w) for w in (recv.get("words") or [recv["word"]])]


# ── building ───────────────────────────────────────────────────────────────

def host_machine():
    return platform.machine() in ("arm64", "aarch64")


def rosetta():
    """`True` when this host can also RUN an x86-64 image, else the reason."""
    if host_machine() and sys.platform == "darwin":
        return True, ""
    return False, (f"host is {platform.machine()}; an x86-64 formal image needs "
                   f"Rosetta 2, which only Apple Silicon has")


def runnable_arches():
    """The architectures a client can be built and run for on this host."""
    arches = []
    if host_machine():
        arches.append(ARM64)
    can_rosetta, why = rosetta()
    if can_rosetta:
        arches.append(X86_64)
    return arches, why


def write_corpus(tmpdir):
    path = os.path.join(tmpdir, "interop.mojo")
    with open(path, "w") as f:
        f.write(CORPUS)
    return path


def build_dylib(arch, tmpdir, source):
    """`(path, manifest)` for one architecture, built with no proof.

    Through `fire.py dylib` for BOTH, because that is what a consumer of a formal
    dylib has: a command line, not a python call into `formal.build`. The x86-64
    arm names `--no-prove --backend=x86_64` rather than `--formal`, which is the
    only spelling that can work — the per-export CONTRACT is arm64-only, and
    `dylib --formal --backend=x86_64` says so and exits 2 — and it is the
    spelling the arm64 refusal's own diagnostic recommends.

    Before 2026-10-05 that recommendation was FALSE: the guard that names it
    fired on the `--backend` value alone, so `dylib --no-prove --backend=x86_64`
    was refused by a message ending "drop --formal: `dylib --no-prove` is that"
    (see `fire.py`, the `--formal` in that guard's condition), and there was no
    command line at all that produced an x86-64 formal library. Building through
    the CLI is what keeps that fixed: a test that went back to the python call
    would pass either way.
    """
    out = os.path.join(tmpdir, f"libinterop.{arch}.dylib")
    argv = ["dylib", "--no-prove", "--backend=" + arch, "-o", out, source]
    if arch == ARM64:
        # arm64 CAN carry a per-export contract, so ask for the proof too — the
        # command a user gets by default on this architecture.
        argv = ["dylib", "--formal", "--no-prove", "-o", out, source]
    result = subprocess.run([sys.executable, FIRE] + argv, capture_output=True,
                            text=True, timeout=COMPILE_TIMEOUT_S, cwd=HERE)
    if result.returncode != 0 or not os.path.isfile(out):
        raise TestFailure(
            f"`fire.py {' '.join(argv)}` did not produce a library: "
            f"{(result.stderr or result.stdout).strip()[-600:]}")
    with open(out, "rb") as f:
        magic = f.read(8)
    cputype = struct.unpack_from("<i", magic, 4)[0]
    want = {"arm64": 0x0100000C, "x86_64": 0x01000007}[arch]
    check(magic[:4] == b"\xcf\xfa\xed\xfe" and cputype == want,
          f"`fire.py {' '.join(argv)}` wrote a Mach-O for cputype {cputype:#x}, "
          f"and this case asked for {arch} ({want:#x}) — a client on the other "
          f"architecture cannot load it")
    with open(out + ".manifest.json") as f:
        return out, json.load(f)


def exports_by_name(manifest):
    return {e["name"]: e for e in manifest["exports"]}


def split_signature(signature):
    """`(return type, name, (param types…))` out of a C signature.

    `int64_t add (int64_t, int64_t)` → `('int64_t', 'add', ('int64_t',
    'int64_t'))`; `char * platform_name (void)` → `('char *', 'platform_name',
    ())`.
    """
    head, _, rest = signature.partition("(")
    params = rest.rsplit(")", 1)[0].strip()
    parts = head.strip().rsplit(None, 1)
    if len(parts) != 2:
        raise TestFailure(f"cannot read a declaration out of {signature!r}")
    return parts[0], parts[1], tuple(
        p.strip() for p in params.split(",") if p.strip() and p != "void")


def declaration_for(entry):
    """`(declaration, return type, param types)` a client generates.

    The manifest publishes two fields per export: `symbol`, the boundary symbol,
    and `signature`, the C declaration of the SOURCE name. A client's declaration
    is the signature with its name token replaced by the symbol, and that join is
    part of what is under test — it is the only step between "the manifest says
    this" and "the C compiler agrees".
    """
    ret, _, params = split_signature(entry["signature"])
    return (f"extern {ret} {entry['symbol']}({', '.join(params) or 'void'});",
            ret, params)


# ── the C consumer ─────────────────────────────────────────────────────────

C_PRELUDE = '''\
/* Generated by test_formal_interop.py. Do not edit: the declarations below
   come from the library's own manifest, which is the thing under test. */
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

static uint64_t dbl_word(double d) { uint64_t b; memcpy(&b, &d, 8); return b; }
static char *S_HELLO = "hello";
static char *S_HE = "he";
static char *S_BANANA = "banana";
static char *S_NA = "na";
'''


def c_struct_decls():
    """`struct Point` / `struct Cell` as the receiver rows say they are laid out.

    One `int64_t` per field, in declaration order — doc/ABI.md's "a frame of
    8-byte slots, one per field, in declaration order" — generated from the
    corpus's own field list so a client cannot quietly agree with the emitter
    about a layout neither of them declared.
    """
    out = []
    for struct_name in ("Point", "Cell"):
        fields = corpus_fields(struct_name)
        body = " ".join(f"int64_t {f};" for f in fields)
        out.append(f"struct {struct_name} {{ {body} }};")
    return out


def c_arg(arg):
    kind, value = arg
    if kind == "i":
        return f"{mask(value)}ULL"
    if kind == "d":
        return f"dbl_word({value!r})"
    if kind == "s":
        return "S_" + value.upper()
    raise TestFailure(f"unknown argument kind {kind!r}")


def c_result_expr(case):
    """The C expression that is 1 iff the returned pointer is what we want."""
    if case["result"] == "ptr_is_arg":
        return "(uint64_t)(r == arg0)"
    if case["py"] == "None":
        return "(uint64_t)(r == NULL)"
    return f'(uint64_t)(r != NULL && strcmp(r, "{case["py"].strip(chr(34))}") == 0)'


def c_driver(cases):
    """The C program: every declaration from `cases`, then one print per word.

    Every word prints as 16 hex digits, whatever its type. That is not
    cosmetic: a `printf` format per type is a second place for the two consumers
    to disagree, and printing the RAW word is what lets the C program and the
    Python program emit the same numbers, so they can be compared with each other
    as well as with the oracle.
    """
    out = [C_PRELUDE]
    out.extend(c_struct_decls())
    out.append("")
    seen = set()
    for case in cases:
        if case.decl not in seen:
            seen.add(case.decl)
            out.append(case.decl)
    out.append("")
    out.append("int main(void) {")
    for case in cases:
        spec = case.case
        # Each case in its own block: they all declare `r` and a receiver, and
        # twenty cases sharing one scope is twenty redefinitions of both.
        out.append("  {")
        out.append(f"  /* {spec['name']} */")
        args = []
        recv = spec.get("recv")
        if recv:
            struct_name = spec["name"].split(".", 1)[0]
            if recv["by"] in ("frame", "cell"):
                words = recv.get("words") or [recv["word"]]
                initial = ", ".join(f"{mask(w)}ULL" for w in words)
                out.append(f"  struct {struct_name} recv = {{{initial}}};")
                args.append("&recv")
            else:
                out.append(f"  uint64_t recv = {mask(recv['word'])}ULL;")
                args.append("recv")
        for arg in spec.get("args", ()):
            if arg[0] == "s" and spec.get("result") == "ptr_is_arg" \
                    and not args:
                args.append("arg0")
                continue
            args.append(c_arg(arg))
        if spec.get("result") == "ptr_is_arg":
            out.append("  char *arg0 = (char *)malloc(16);")
            out.append('  memcpy(arg0, "hello", 6);')
        call = f"{case.symbol}({', '.join(args)})"
        if spec.get("result") in ("str", "ptr_is_arg"):
            out.append(f"  char *r = {call};")
            out.append(f'  printf("{case.label}.ret=%016llx\\n", '
                       f"(unsigned long long)({c_result_expr(spec)}));")
        else:
            out.append(f"  {case.ret} r = {call};")
            out.append(f'  printf("{case.label}.ret=%016llx\\n", '
                       f"(unsigned long long)(uint64_t)r);")
        if recv and recv["by"] != "value":
            for i, field in enumerate(corpus_fields(spec["name"].split(".")[0])):
                out.append(f'  printf("{case.label}.recv{i}=%016llx\\n", '
                           f"(unsigned long long)(uint64_t)recv.{field});")
        out.append("  }")
    out.append("")
    out.append("  return 0;")
    out.append("}")
    return "\n".join(out) + "\n"


def parse_words(stdout):
    """`{case label: [word, …]}` from a client's output.

    The label is `<case>#<n>` and the field is `.ret` or `.recv<i>`; the case is
    what a comparison wants, and the ORDER of the words is what the driver
    printed in — return first, then the receiver's fields in declaration order,
    which is the same order `oracle_words` builds and the order a frame's layout
    makes load-bearing.
    """
    out = {}
    for line in stdout.splitlines():
        if not line.strip():
            continue
        head, _, word = line.partition(REC)
        check(head and word, f"unreadable output line {line!r}")
        label, _, _field = head.rpartition(".")
        out.setdefault(label, []).append(int(word, 16))
    return out


def c_compilers():
    found = [cc for cc in ("cc", "gcc") if shutil.which(cc)]
    check(found, "no C compiler on PATH, so there is no C client to run")
    return found


def compile_and_run(arch, tmpdir, csrc, dylib, stem):
    """Compile `csrc` against `dylib` with every C compiler, and run it."""
    results, problems = [], []
    for cc in c_compilers():
        cbin = os.path.join(tmpdir, f"{stem}_{arch}_{cc.replace('/', '_')}")
        argv = [cc, "-O0", "-o", cbin, csrc, dylib,
                f"-Wl,-rpath,{os.path.dirname(dylib)}"]
        if arch == X86_64:
            argv[1:1] = ["-arch", "x86_64"]
        built = subprocess.run(argv, capture_output=True, text=True,
                               timeout=LINK_TIMEOUT_S, cwd=tmpdir)
        if built.returncode != 0:
            problems.append(
                f"{cc}: {(built.stderr or built.stdout).strip()[-500:]}")
            continue
        argv = ["arch", "-x86_64", cbin] if arch == X86_64 else [cbin]
        run = subprocess.run(argv, capture_output=True, text=True,
                             timeout=RUN_TIMEOUT_S, cwd=tmpdir)
        if run.returncode != 0:
            raise TestFailure(f"[{arch}] the C client exited {run.returncode}: "
                              f"{run.stderr.strip()[-300:]}")
        results.append((cc, parse_words(run.stdout)))
    check(results, f"[{arch}] no C compiler could build a client against the "
                   f"library:\n      " + "\n      ".join(problems))
    return results


def run_c_client(arch, tmpdir, dylib, cases):
    csrc = os.path.join(tmpdir, f"client_{arch}.c")
    with open(csrc, "w") as f:
        f.write(c_driver(cases))
    return compile_and_run(arch, tmpdir, csrc, dylib, "client")


# ── the ctypes consumer ────────────────────────────────────────────────────
#
# One driver, run as a subprocess for whichever architecture it is asked about:
# an arm64 `ctypes` cannot load an x86-64 dylib, so the x86-64 half runs under
# `arch -x86_64`. It reads the same case description the C consumer is generated
# from, so the two are driven by one table.

CTYPES_DRIVER = '''\
"""Generated by test_formal_interop.py — see that file's docstring."""
import ctypes
import json
import sys


def check(condition, message):
    if not condition:
        raise ValueError(message)


# Every type a manifest signature can name, so a declaration this driver cannot
# read is a failure ABOUT THE ANSWER rather than a crash while setting up the
# call. That matters for what the test is for: a manifest still spelling
# `int32_t` has to come out as `KeyError`-free and as a wrong number the
# comparison can point at, because the wrong number is the evidence.
_CT = {
    "int8_t": ctypes.c_int8,
    "int16_t": ctypes.c_int16,
    "int32_t": ctypes.c_int32,
    "int64_t": ctypes.c_int64,
    "uint8_t": ctypes.c_uint8,
    "uint16_t": ctypes.c_uint16,
    "uint32_t": ctypes.c_uint32,
    "uint64_t": ctypes.c_uint64,
    "_Bool": ctypes.c_int32,
    "float": ctypes.c_float,
    "double": ctypes.c_double,
    "char *": ctypes.c_char_p,
    "void": None,
}


def struct_type(name, fields):
    """A `ctypes` struct with one 64-bit slot per field, in order.

    Generated rather than written down, for the same reason the C client
    generates its `struct Point`: the receiver's layout IS the ABI claim, and a
    struct somebody typed by hand would agree with the emitter by accident.
    """
    return type(name, (ctypes.Structure,),
                {"_fields_": [(f, ctypes.c_int64) for f in fields]})


def ctype(name, structs):
    """The ctypes type for one C type name.

    A `struct X` in a declaration is the generated type for `X`: the C client
    and this driver both build their receiver struct from the corpus's own field
    list, so neither is transcribing a layout the other happens to agree with.
    """
    if name in _CT:
        return _CT[name]
    if name == "char":
        return ctypes.c_char
    if name.startswith("struct "):
        name = name[len("struct "):]
    if name in structs:
        return structs[name]
    raise KeyError(name)


def pointer(decl, structs):
    """`(restype, argtypes)` for a declaration, with `T *` as `POINTER(T)`.

    A receiver is the one parameter whose type is a STRUCT, and doc/ABI.md says
    it is "a frame of 8-byte slots, one per field, in declaration order" — so
    the struct type the client passes is generated from the corpus's field list,
    which is what makes this a check of the layout rather than a transcription
    of it.
    """
    decl = decl.strip()
    if decl.startswith("extern "):
        decl = decl[len("extern "):]
    head, _, params = decl.partition("(")
    params = params.rsplit(")", 1)[0].strip()
    types = []
    for p in params.split(",") if params and params != "void" else []:
        p = p.strip()
        if p.endswith("*"):
            types.append(ctypes.POINTER(ctype(p[:-1].strip(), structs)))
        else:
            types.append(ctype(p, structs))
    # `<return type> <name>`: the type is everything before the last
    # whitespace-separated token, which is the name.
    words = head.strip().rsplit(None, 1)
    check(len(words) == 2, "the declaration has no function name in it")
    return ctype(words[0], structs), types


def mask(value):
    return int(value) & 0xFFFFFFFFFFFFFFFF


def f64_word(value):
    import struct
    return struct.unpack("<Q", struct.pack("<d", float(value)))[0]


def run(dylib, spec):
    lib = ctypes.CDLL(dylib)
    structs = {name: struct_type(name, fields)
               for name, fields in spec["structs"].items()}
    out = {}
    for case in spec["cases"]:
        ret_t, arg_t = pointer(case["decl"], structs)
        fn = getattr(lib, case["symbol"])
        # A POINTER-IDENTITY question needs the address, and `c_char_p` converts
        # a `char *` result to `bytes` — which answers "are the contents equal"
        # and not "is it the same pointer", and the contents are equal either
        # way. So that one case asks for `c_void_p`.
        fn.restype = (ctypes.c_void_p if case.get("result") == "ptr_is_arg"
                      else ret_t)
        fn.argtypes = arg_t
        args, keep = [], {}
        recv = case.get("recv")
        if recv:
            name = case["name"].split(".")[0]
            if recv["by"] in ("frame", "cell"):
                words = recv.get("words") or [recv["word"]]
                frame = structs[name](*words)
                keep["recv"] = frame
                args.append(ctypes.byref(frame))
            else:
                args.append(recv["word"])
        for index, (kind, value) in enumerate(case.get("args", [])):
            if kind == "s":
                if case.get("result") == "ptr_is_arg" and not keep:
                    buf = ctypes.create_string_buffer(value.encode())
                    keep["arg0"] = buf
                    args.append(buf)
                else:
                    args.append(value.encode())
            elif kind == "d":
                args.append(f64_word(value))
            else:
                args.append(mask(value))
        result = fn(*args)
        words = []
        mode = case.get("result")
        if mode == "str":
            want = case["want_str"]
            words.append(1 if (result is None if want is None
                               else result == want.encode()) else 0)
        elif mode == "ptr_is_arg":
            words.append(1 if result == ctypes.addressof(keep["arg0"]) else 0)
        else:
            words.append(mask(result))
        frame = keep.get("recv")
        if frame is not None:
            words.extend(mask(getattr(frame, f))
                         for f in spec["structs"][case["name"].split(".")[0]])
        out[case["label"]] = words
    return out


def main():
    dylib, spec_path = sys.argv[1], sys.argv[2]
    with open(spec_path) as f:
        spec = json.load(f)
    print(json.dumps(run(dylib, spec)))


if __name__ == "__main__":
    main()
'''


def ctypes_spec(cases):
    """The case description the ctypes consumer runs on."""
    out = []
    for case in cases:
        spec = case.case
        entry = dict(label=case.label, name=spec["name"], symbol=case.symbol,
                     decl=case.decl, recv=spec.get("recv"),
                     args=[[k, v] for k, v in spec.get("args", ())])
        if "result" in spec:
            entry["result"] = spec["result"]
        if spec.get("result") == "str":
            entry["want_str"] = (None if spec["py"] == "None"
                                 else spec["py"].strip('"'))
        out.append(entry)
    return dict(structs={name: corpus_fields(name)
                         for name in ("Point", "Cell")}, cases=out)


def x86_64_python():
    """An interpreter that runs as x86-64, or None with the reason.

    Rosetta 2 translates a PROCESS, and it can only translate a binary that has
    an x86-64 slice. A Homebrew interpreter on Apple Silicon does not — it is
    `Mach-O 64-bit executable arm64` — so `arch -x86_64 <it>` fails, and the
    failure says so about the wrong file when the interpreter is reached through
    a symlink. The candidate list is therefore asked rather than assumed, and
    each candidate is asked by RUNNING it: a path that exists is not a path that
    runs.
    """
    for candidate in ("/usr/bin/python3", sys.executable):
        if not candidate or not os.path.isfile(candidate):
            continue
        probe = subprocess.run(
            ["arch", "-x86_64", candidate, "-c",
             "import platform; print(platform.machine())"],
            capture_output=True, text=True, timeout=RUN_TIMEOUT_S)
        if probe.returncode == 0 and probe.stdout.strip() == "x86_64":
            return candidate, ""
    return None, ("no interpreter on this host runs as x86_64, and Rosetta 2 "
                  "needs a binary with an x86-64 slice (a Homebrew python on "
                  "Apple Silicon is arm64-only)")


def run_ctypes_client(arch, tmpdir, dylib, cases):
    driver = os.path.join(tmpdir, f"ctypes_driver_{arch}.py")
    spec_path = os.path.join(tmpdir, f"cases_{arch}.json")
    with open(driver, "w") as f:
        f.write(CTYPES_DRIVER)
    with open(spec_path, "w") as f:
        json.dump(dict(arch=arch, **ctypes_spec(cases)), f)
    if arch == X86_64:
        python, why = x86_64_python()
        check(python is not None, f"[{arch}] the ctypes client cannot run: {why}")
        argv = ["arch", "-x86_64", python, driver, dylib, spec_path]
    else:
        argv = [sys.executable, driver, dylib, spec_path]
    result = subprocess.run(argv, capture_output=True, text=True,
                            timeout=RUN_TIMEOUT_S, cwd=tmpdir)
    check(result.returncode == 0,
          f"[{arch}] the ctypes client failed: "
          f"{(result.stderr or result.stdout).strip()[-700:]}")
    return json.loads(result.stdout)


# ── the case list for one library ──────────────────────────────────────────

class Bound:
    """One case, bound to the library under it: label, symbol, declaration."""

    __slots__ = ("label", "case", "symbol", "ret", "decl")

    def __init__(self, label, case, symbol, ret, decl):
        self.label = label
        self.case = case
        self.symbol = symbol
        self.ret = ret
        self.decl = decl


def build_cases(manifest):
    """`[Bound]` — what each case is, bound to this library's own symbols.

    A FREE FUNCTION's declaration is generated: the manifest's own signature
    with its name token replaced by the exported symbol. A METHOD's is not,
    because the manifest publishes `Struct.method` where a declaration belongs,
    so the documented declaration from `METHOD_DECLARATIONS` is used and the
    missing one is asserted by `test_the_receiver_rule_is_the_documented_one`
    rather than worked around quietly.
    """
    by_name = exports_by_name(manifest)
    bound = []
    for index, case in enumerate(CASES):
        name = case["name"]
        # A method is exported under the LIFTED name — `Point_sum`, the
        # `model.method_function_name` of `Point.sum` — while the case table
        # spells it the way the source and `doc/ABI.md` do. Joining the two
        # through the model's own namer rather than by string surgery means a
        # change to that spelling cannot make this file bind the wrong export.
        export_name = (name if "." not in name else
                       formal_model().method_function_name(*name.split(".", 1)))
        entry = by_name.get(export_name)
        check(entry is not None,
              f"the manifest publishes no export named {export_name!r} for "
              f"case {name} (has {sorted(by_name)})")
        label = f"{name}#{index}"
        if entry.get("kind") == "method":
            struct_name, method = name.split(".", 1)
            documented = METHOD_DECLARATIONS.get(name)
            check(documented is not None,
                  f"{name} is a method with no entry in this file's copy of "
                  f"doc/ABI.md's receiver table")
            ret, params = documented.split(" (", 1)
            decl = (f"extern {ret.strip()} {entry['symbol']}"
                    f"({params.rstrip(')')});")
            ret = ret.strip()
        else:
            decl, ret, _ = declaration_for(entry)
        bound.append(Bound(label, case, entry["symbol"], ret, decl))
    return bound


def compare(arch, consumer, bound, got):
    words = got.get(bound.label)
    check(words is not None,
          f"[{arch}] {consumer}: printed nothing for {bound.case['name']}")
    want = oracle_words(bound.case)
    check(words == want,
          f"[{arch}] {consumer}: {bound.case['name']}"
          f"({bound.case.get('args')}) computed "
          f"{['0x%x' % w for w in words]} where CPython says "
          f"{['0x%x' % w for w in want]} (`{bound.case['py']}`)")


# ── the tests ──────────────────────────────────────────────────────────────

def test_every_oracle_is_the_librarys_own_expression(tmpdir, shared):
    """Each oracle is the library's own return expression, substituted.

    `py` is written out in every case so CPython can evaluate it, and two texts
    for one expression is a liability: the oracle decides whether a right answer
    is right, so it must not be a second opinion somebody typed. Every `py` is
    therefore DERIVED — the corpus's return statement with this case's arguments
    substituted for its parameters — and this fails when the derived text and the
    written one differ. Whitespace is not compared, because it differs between
    the two languages' own formatting and means nothing.

    The three `Optional` cases reach `return None`, the one expression that
    cannot be evaluated in Python: the interesting value there is not what the
    source says but the NICHE the model spells it with. Those are checked the
    other way round — the body must be exactly `None` — and the word is asked of
    `model.optional_none_word` in the next test.
    """
    for case in CASES:
        if case.get("ret_index"):
            check(oracle_text(case) == "None",
                  f"{case['name']}: the case reaches a second `return` that "
                  f"does not say `None` ({oracle_text(case)!r})")
            continue
        derived = oracle_text(case)
        written = case["py"]
        if squash(derived) == squash(written):
            continue
        # A body with an ASSIGNMENT cannot be compared as text: the derivation
        # evaluated `self.x = self.x + by` to get the field's new value, so what
        # it produced for `return self.x` is the literal `15` where the written
        # oracle is the expression `10 + 5`. Those are the same answer and they
        # are checked as VALUES here — with the text claim still asserted for
        # every case that has no assignment, which is every case where the two
        # spellings could differ at all.
        if not any(ASSIGNMENT_RE.match(s) for s in corpus_body_statements(case)):
            check(False,
                  f"{case['name']}: the oracle is written {written!r} and the "
                  f"library's own return expression, with this case's "
                  f"arguments substituted, is {derived!r}")
        got = eval(squash(derived), {"__builtins__": {}}, {})    # noqa: S307
        want = eval(squash(written), {"__builtins__": {}}, {})   # noqa: S307
        check(got == want,
              f"{case['name']}: the oracle is written {written!r} and the "
              f"library's body, with this case's arguments substituted and its "
              f"assignment evaluated, gives {derived!r} = {got!r}")


def test_the_optional_niches_are_the_documented_words(tmpdir, shared):
    """`doc/ABI.md`'s `Optional` table, asked of the one reader of it.

    The table says the empty word is 0 for a `String` (an address no program
    holds), `1 << w` for a `w`-bit integer, 2 for a `Bool`, and that `Int` and
    `Float64` are REFUSED because every word is a value of them. All four are
    facts about `formal/model.py::optional_none_word`, so they are asked of it —
    including the refusal, which is a row of the same table and the one a corpus
    cannot reach, since a library exporting an `Optional[Int]` does not build.
    """
    M = formal_model()
    documented = {"String": 0, "Bool": 2, "Int8": 1 << 8, "Int16": 1 << 16,
                  "Int32": 1 << 32, "UInt8": 1 << 8, "UInt16": 1 << 16,
                  "UInt32": 1 << 32}
    for payload, want in sorted(documented.items()):
        got, why = M.optional_none_word(payload)
        check(got == want,
              f"doc/ABI.md says an empty `Optional[{payload}]` is the word "
              f"{want}, and model.optional_none_word says {got}"
              + (f" ({why})" if why else ""))
    for payload in ("Int", "Int64", "UInt", "UInt64", "Float64", "Float32"):
        got, why = M.optional_none_word(payload)
        check(got is None and why,
              f"doc/ABI.md says an empty `Optional[{payload}]` is REFUSED "
              f"because every word is a value of it, and "
              f"model.optional_none_word says {got!r} (with no reason)")


def test_the_manifest_publishes_what_the_callee_implements(tmpdir, shared):
    """`doc/ABI.md`'s scalar table against what a formal boundary is.

    The formal backends were publishing the COMPILED path's declaration
    unchanged, so a client that generated its declaration from the manifest got
    one the library does not implement: `double float_add (double, double)` for
    a callee that reads two general-purpose words and returns a word. This
    asserts the published shape for every export of every free function in the
    corpus, row by row:

      * every scalar VALUE is spelled one 64-bit word;
      * no C floating-point type appears — `doc/ABI.md`'s `Float64` row is the
        compiled path's, and on this boundary the value is a word;
      * a POINTER keeps its spelling, because a pointer is a word AND the
        pointee is information a client needs: `uint8_t *` is what
        `model.dylib_export_pointer_pointee` reads to know a buffer is
        subscriptable, so a rewrite that swept the pointee up with the value
        would have taken that with it.
    """
    for arch, dylib, manifest in shared["libs"]:
        by_name = exports_by_name(manifest)
        for name, entry in sorted(by_name.items()):
            if entry.get("kind") == "method":
                continue
            ret, _, params = split_signature(entry["signature"])
            where = f"[{arch}] {name}"
            check("double" not in ret and "float" not in ret
                  and "fp16" not in ret,
                  f"{where} publishes a C floating-point return type "
                  f"({entry['signature']!r}); a formal boundary is one 64-bit "
                  f"word and doc/ABI.md's `Float64` row is the compiled "
                  f"path's")
            for p in params:
                check(p == "int64_t" or p.endswith("*"),
                      f"{where} publishes the parameter type {p!r}; every "
                      f"scalar value on a formal boundary is one int64_t "
                      f"word")
            check(ret in ("void", "int64_t") or ret.endswith("*"),
                  f"{where} publishes the return type {ret!r}")
    # The pointee rule, checked on the reader itself rather than on a corpus
    # case, because a formal library exporting a `Pointer[UInt8]` is not
    # something this corpus can promise to build — and it is the rule most
    # likely to be broken by a later change, since sweeping the pointee up with
    # the value would look like tidying.
    rewritten = {
        "uint8_t * sigma_table (void)": "uint8_t * sigma_table (void)",
        "char * platform_name (void)": "char * platform_name (void)",
        "double probe (double, _Bool, float)":
            "int64_t probe (int64_t, int64_t, int64_t)",
        "int32_t narrow (int32_t)": "int64_t narrow (int64_t)",
        "void setg (uint64_t)": "void setg (uint64_t)",
        "int64_t plain (int64_t)": "int64_t plain (int64_t)",
        "uint64_t * table (void)": "uint64_t * table (void)",
    }
    for signature, want in sorted(rewritten.items()):
        got = formal_model().formal_boundary_signature(signature)
        check(got == want,
              f"formal_boundary_signature({signature!r}) is {got!r} and "
              f"doc/ABI.md's word convention says {want!r}")


def test_the_receiver_rule_is_the_documented_one(tmpdir, shared):
    """`doc/ABI.md`'s receiver table, derived two more ways and compared.

    The C client cannot generate a method's declaration from the manifest (it
    publishes `Struct.method`), so this file's copy of the table is the only
    thing telling both clients where the receiver goes. That is exactly the kind
    of claim that rots, so each row is derived from two INDEPENDENT sources and
    compared:

      * `reflect`'s own method signature — the reader every method export on
        every backend is named by — which fixes the return type and the
        non-receiver parameter types, with the manifest's word convention
        applied to them; and
      * the emitter's own receiver rule: `model.struct_is_one_field` for the
        struct's shape and `model.receiver_writeback_name` for the mutating
        convention, the two functions both backends ask about a receiver.

    The rule being checked is doc/ABI.md's: a receiver is an ADDRESS unless the
    struct is one field and the method is not a mutator, in which case it is the
    value in a register.
    """
    sys.path.insert(0, HERE)
    M = formal_model()
    import formal.imports as FI                                  # noqa: PLC0415
    import reflect                                               # noqa: PLC0415

    entries = {e["name"]: e for e in
               reflect.collect_exports_src(CORPUS, "interop")}
    for arch, dylib, manifest in shared["libs"]:
        linked = [dict(source=shared["source"], exports=manifest["exports"])]
        decls = FI.external_declarations(linked)
        by_name = exports_by_name(manifest)
        for name, documented in sorted(METHOD_DECLARATIONS.items()):
            struct_name, method = name.split(".", 1)
            entry = by_name[M.method_function_name(struct_name, method)]
            decl = decls.get(entry["symbol"])
            check(decl is not None,
                  f"[{arch}] {name}: no declaration could be read back from "
                  f"the corpus the library was built from")
            owner = getattr(decl, "_owner_struct", None)
            check(owner is not None and owner.name == struct_name,
                  f"[{arch}] {name}: the declaration carries no owning struct")
            one_field = M.struct_is_one_field(owner)
            mutating = M.receiver_writeback_name(decl) is not None
            by_address = (not one_field) or mutating
            reflected = entries.get(f"{struct_name}.{method}")
            check(reflected is not None,
                  f"reflect publishes no method entry for {name}")
            want_ret, want_params = documented.split(" (", 1)
            want_params = tuple(p.strip()
                                for p in want_params.rstrip(")").split(","))
            got_ret, _, got_params = split_signature(
                M.formal_boundary_signature(reflected["signature"]))
            where = f"[{arch}] {name}"
            check(got_ret == want_ret.strip(),
                  f"{where}: doc/ABI.md's row says the return is "
                  f"{want_ret.strip()!r} and the manifest's own reader says "
                  f"{got_ret!r} ({reflected['signature']!r})")
            check(got_params[1:] == want_params[1:],
                  f"{where}: doc/ABI.md's row says the non-receiver "
                  f"parameters are {want_params[1:]} and the manifest's own "
                  f"reader says {got_params[1:]} "
                  f"({reflected['signature']!r})")
            # The RECEIVER is where the two backends differ, and it is NOT taken
            # from reflect: reflect spells a method's receiver `Struct *`, which
            # is right for the compiled path (a real C++ `Struct *self`) and
            # wrong for a formal boundary in one measurable case — a one-field
            # struct's plain `self`, which the formal backends pass BY VALUE,
            # so `Cell.get` really is `int64_t (int64_t)`. That divergence is
            # why the manifest publishes no method declaration at all
            # (`bugs/FORMAL_a_method_export_publishes_no_c_declaration.md`); it
            # is checked against the emitter's own rule instead.
            check(want_params[0].endswith("*") == by_address,
                  f"{where}: this file's own copy of doc/ABI.md's table says "
                  f"the receiver is {want_params[0]!r} and the emitter's rule "
                  f"says {'an address' if by_address else 'the value'}")
            # The entry the manifest DOES publish for a method keeps the struct
            # name where formal/imports.py reads it: that string is how a
            # build-pass refusal learns which structs a linked library provides.
            check(entry["signature"] == f"{struct_name}.{method}",
                  f"[{arch}] {name}: the manifest publishes "
                  f"{entry['signature']!r} and imports.linked_struct_owners "
                  f"reads the struct name out of that field")


def test_a_c_client_computes_what_cpython_computes(tmpdir, shared):
    """A C program linked against the library, bound through the manifest."""
    for arch, dylib, manifest in shared["libs"]:
        cases = build_cases(manifest)
        for cc, got in run_c_client(arch, tmpdir, dylib, cases):
            for bound in cases:
                compare(arch, cc, bound, got)


def test_a_ctypes_client_computes_what_cpython_computes(tmpdir, shared):
    """The same calls through `ctypes`, on every architecture."""
    for arch, dylib, manifest in shared["libs"]:
        cases = build_cases(manifest)
        got = run_ctypes_client(arch, tmpdir, dylib, cases)
        for bound in cases:
            compare(arch, "ctypes", bound, got)


def test_the_two_clients_agree(tmpdir, shared):
    """C and `ctypes` produce the same words, on every architecture.

    Not a restatement of the oracle check: this is the cross-IMPLEMENTATION
    one, and it is the only assertion here that would notice a boundary that
    works by accident in one host language — a register a C compiler happens to
    fill that `ctypes` leaves alone, say. Ten arguments is the case that catches
    it: `ctypes` converts a Python int to a C `int` unless `argtypes` says
    otherwise, so a driver that forgot them would put the ninth and tenth
    arguments in the wrong registers and still be "calling the same function".
    """
    for arch, dylib, manifest in shared["libs"]:
        cases = build_cases(manifest)
        c_results = run_c_client(arch, tmpdir, dylib, cases)[0][1]
        py_results = run_ctypes_client(arch, tmpdir, dylib, cases)
        diffs = [(bound.label, c_results.get(bound.label),
                  py_results.get(bound.label)) for bound in cases
                 if c_results.get(bound.label) != py_results.get(bound.label)]
        check(not diffs,
              f"[{arch}] C and ctypes disagree on {len(diffs)} of "
              f"{len(cases)} cases; first three:\n      " +
              "\n      ".join(f"{label}: C {a}, ctypes {b}"
                              for label, a, b in diffs[:3]))


TESTS = [
    ("every oracle is the library's own expression",
     test_every_oracle_is_the_librarys_own_expression),
    ("the Optional niches are the documented words",
     test_the_optional_niches_are_the_documented_words),
    ("the manifest publishes what the callee implements",
     test_the_manifest_publishes_what_the_callee_implements),
    ("the receiver rule is the documented one",
     test_the_receiver_rule_is_the_documented_one),
    ("a C client computes what CPython computes",
     test_a_c_client_computes_what_cpython_computes),
    ("a ctypes client computes what CPython computes",
     test_a_ctypes_client_computes_what_cpython_computes),
    ("the C and ctypes clients agree",
     test_the_two_clients_agree),
]


def setup_shared(tmpdir):
    source = write_corpus(tmpdir)
    arches, why = runnable_arches()
    libs = []
    for arch in arches:
        dylib, manifest = build_dylib(arch, tmpdir, source)
        libs.append((arch, dylib, manifest))
    return dict(source=source, libs=libs, why=why)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    passed = failed = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            shared = setup_shared(tmpdir)
        except TestFailure as e:
            print(f"ERROR: formal interop could not build its library: {e}")
            return 1
        if shared["why"]:
            print(f"SKIP: x86-64: {shared['why']}")
        print(f"libraries: {', '.join(a for a, _, _ in shared['libs'])}")
        for name, fn in TESTS:
            try:
                fn(tmpdir, shared)
            except TestFailure as e:
                failed += 1
                print(f"  FAIL  {name}\n        {e}")
                continue
            except Exception as e:                            # noqa: BLE001
                failed += 1
                print(f"  ERROR {name}\n        {type(e).__name__}: {e}")
                if args.verbose:
                    import traceback
                    traceback.print_exc()
                continue
            passed += 1
            print(f"  PASS  {name}")

    print(f"\nformal interop: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())