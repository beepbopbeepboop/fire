#!/usr/bin/env python3
"""Tests for a comptime SPECIALIZATION: `f[a, b](...)` on both formal paths.

A specialization is a call whose brackets bind a generic's comptime
parameters, and it is spelled in a way that looks like a subscript. That
ambiguity is the whole subject of this file, because both formal backends
resolve it by flattening the callee to its base NAME — and everything that
goes wrong here goes wrong after that flattening.

The three cases, in the order they are worth knowing:

  1. the root of the bracket is a CALLEE, not a read of a value. It was
     walked as a read, so a call to an imported generic was refused as a
     storage problem: the arm64 sweep reported `std/sys/_assembly.mojo`'s
     `_get_kgen_string[asm]()` as "is imported from `string_slice`, so it
     is a module-level name of another module", and seventeen files
     inherited that diagnosis through their import chains;
  2. a bracketed callee this unit does NOT compile is refused, by name,
     with the reason. Both backends used to emit the call with the
     brackets DROPPED: `plain[3](5)` became a plain `plain(5)`, which
     built, ran, and printed a number the source never wrote. Measured;
  3. a specialization of a LOCAL generic is none of the above: it
     lowers, the brackets become leading arguments, and the program runs
     with the answer CPython gives.

The refusal text is ONE function (`formal.model.specialization_call_refusal`)
read by both backends, so 2 is pinned on both architectures — an
arch-free answer is the only way one construct cannot come back with two
different verdicts.

§5 and §5b are the OTHER name this path has to resolve: a function VALUE. It
used to have no spelling here in either position, and it has one now — a
function of this unit read as a word IS a word, its code ADDRESS, materialized
by each backend's `_load_var` (`ADRP`+`ADD` on arm64, `LEA r, [rip+d]` on
x86-64) and branched through by its `_emit_call`. §5 pins that by EXECUTION on
both architectures and §5's siblings pin the brackets reaching a callee that is
such a word, which is `std/algorithm/backend/tile.mojo`'s own call. What is
still refused, each by name and for a reason of its own, is in §5c: a keyword
through a value, a bracket on an UNANNOTATED parameter, and a parameter whose
declared type cannot hold a function. §5b is the half that could not be told
from a C symbol: a callee the calling function BINDS is a value, not a symbol,
and "a name this unit does not compile" used to branch against a symbol named
after the parameter and let the loader refuse the image four stages later.

Invoked directly:
    python3 test_formal_specialization.py [-v]
"""
import argparse
import os
import platform
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from test_formal_dylib import TestFailure, check, run_fire

FIRE = os.path.join(HERE, "fire.py")

ARCHES = ("arm64", "x86_64")


# ── the programs ─────────────────────────────────────────────────────────────
#
# `plain` is a CONCRETE exported function, so `plain[3](5)` is a subscript of
# a value rather than a specialization: it is the case that used to lower to
# a plain `plain(5)`. `widen` is a GENERIC, so `widen[3](5)` is the genuine
# specialization of the same spelling.

PLAIN_LIB = """\
def plain(v: Int32) -> Int32:
    return v + 100
"""

GENERIC_LIB = """\
def widen[x: Int32](v: Int32) -> Int32:
    return v * x


def anchor(v: Int32) -> Int32:
    return v
"""

SUBSCRIPTED_CALL = """\
from lib import plain


def main() -> Int32:
    var b = plain[3](5)
    print(b)
    return 0
"""

CROSS_MODULE_SPECIALIZATION = """\
from lib import widen


def main() -> Int32:
    var b = widen[3](5)
    print(b)
    return 0
"""

# The library for the EXPORT-RULE case, and the two facts that make it the
# subject. `anchor` is a CONCRETE export, so the module builds as a dylib at
# all; `_helper` is a private member, so the export table has no entry for it
# and `_bracketed_export_gap` — not the bracketed scan — is what answers. It is
# NOT a generic: a generic edge is `library_free_edges`' business, and that is
# what moved `widen`'s case off the export rule.
PRIVATE_MEMBER_LIB = """\
def anchor(v: Int32) -> Int32:
    return v


def _helper(v: Int32) -> Int32:
    return v + 1
"""

# `_helper` is bound directly rather than reached through the module, because
# that is the spelling the export rule names: `lib._helper[3](5)` reduces its
# dotted chain to the MODULE and the refusal is about `lib` — true, and a
# different question from the one this case is pinning.
BRACKETED_PRIVATE_CALL = """\
from lib import _helper


def main() -> Int32:
    var b = _helper[3](5)
    print(b)
    return 0
"""

LOCAL_SPECIALIZATION = """\
def widen[x: Int32](v: Int32) -> Int32:
    return v * x


def main() -> Int32:
    var b = widen[3](5)
    print(b)
    return 0
"""

LOCAL_SPECIALIZATION_CPYTHON = 15        # 5 * 3
SUBSCRIPTED_CALL_CPYTHON = 105           # 5 + 100, the answer it fabricated

# The CPython answers for the four function-value programs above.  Each is
# stated here rather than read out of a run, and every case that uses one
# ALSO runs the same source through the interpreter and compares, so a number
# that is simply wrong in both places is caught rather than pinned.
FUNCTION_AS_VALUE_CPYTHON = 105          # call_it(plain, 5) → plain(5)
TILE_CALL_CPYTHON = "18"                # (0+3) + (3+3) + (6+3), tile(0, 10, work)
TWO_BRACKET_CALL_CPYTHON = "7"           # add(2, 5) — the 10 is a third argument
BARE_AND_VIA_LOCAL_CPYTHON = "406\n107"  # bare: 100+101+102+103; local: 7+100

# `func(i)` where `func` arrived as a parameter: the whole body of
# `stdlib/std/algorithm/backend/cpu/map.mojo`, which is what the 2026-10-02
# sweep classified `not-answerable/unresolved-extern` on BOTH architectures
# ("the image would bind 1 symbol(s) that nothing provides: func"). One line of
# callee, one line of call, and the untyped parameter is the more honest
# spelling of it: the annotation is not what makes this unanswerable, and a
# test that pinned only the annotated form would leave the untyped one (which
# is what a corpus is full of) unmeasured.
CALL_THROUGH_A_PARAMETER = """\
def apply(size: Int, func):
    for i in range(size):
        func(i)


def main() -> Int32:
    return 0
"""

# The control for the same check, and the one half that could have gone the
# other way: a name the function declares `global` is NOT a local of it, so
# `global printf; printf(…)` is still a call to a C symbol and still builds.
# `callee_is_a_bound_value` subtracts `global_names_bound_in` for exactly this,
# because the register allocator does, and a check that did not would refuse
# every program that shadows a C name that way.
GLOBAL_SHADOW_CALLS_THE_C_LIBRARY = """\
def main() -> Int32:
    global printf
    printf("global-call-ok\\n")
    return 0
"""
GLOBAL_SHADOW_CPYTHON = "global-call-ok"

# A word the SOURCE says is not a function's address, at both ends of one call —
# the decidable half of `bugs/FORMAL_function_value_calls_are_not_proved_to_be_calls.md`.
#
# All three programs below built, branched to whatever word they held, and died
# of SIGBUS on arm64 / SIGSEGV on x86-64 with nothing on either stream, while
# CPython raised `TypeError` on the same text. That is the loud end of this
# backend's range rather than a silent wrong answer, so the cost of it was a
# diagnostic the KERNEL delivered — and the three shapes are the three sources of
# evidence the analysis reads, one per row, which is why they are three programs
# and not one:
#
#   * `passing/local`    — the argument is a LOCAL the calling function bound to
#     an integer, decided by FLOW rather than by a declaration or a spelling
#     (`model.caller_local_holds`);
#   * `passing/element`  — the argument is `xs[0]` where `xs` is a local built
#     only from container LITERALS, so every element the subscript could hand
#     back is visible in the source (`model.caller_local_element_holds`).
#
# The last one is deliberately this narrow and not `xs[i]` on any list: an
# element of a container CAN be a function — a list of them is `map.mojo`'s own
# shape — so a subscript of a name is only an answer where the walk can see every
# element. `PASSING_ELEMENT_POSITIVE` is that boundary: the same spelling with a
# function among the elements builds and runs, which is what says the reader
# reads the elements rather than the spelling.
NOT_AN_ADDRESS_PASSING_LITERAL = """\
def apply_arg(size: Int, f):
    var t = 0
    var i = 0
    while i < size:
        t += f(i)
        i += 1
    return t

def main() -> Int32:
    return apply_arg(3, 17)
"""

NOT_AN_ADDRESS_PASSING_DECLARED = """\
def apply_arg(size: Int, f):
    var t = 0
    var i = 0
    while i < size:
        t += f(i)
        i += 1
    return t

def main(n: Int) -> Int32:
    return apply_arg(3, n)
"""

NOT_AN_ADDRESS_PASSING_LOCAL = """\
def apply_arg(size: Int, f):
    var t = 0
    var i = 0
    while i < size:
        t += f(i)
        i += 1
    return t

def main() -> Int32:
    var g = 17
    return apply_arg(3, g)
"""

NOT_AN_ADDRESS_PASSING_ELEMENT = """\
def apply_arg(size: Int, f):
    var t = 0
    var i = 0
    while i < size:
        t += f(i)
        i += 1
    return t

def main() -> Int32:
    var xs = [10, 20, 30]
    return apply_arg(3, xs[0])
"""

# The boundary case, and it BUILDS AND RUNS: the same subscript, with a function
# among the literal's elements. A reader that classified `xs[0]` by its SPELLING
# would refuse this, which is the ordinary program.
PASSING_ELEMENT_POSITIVE = """\
def apply_arg(size: Int, f):
    var t = 0
    var i = 0
    while i < size:
        t += f(i)
        i += 1
    return t

def dbl(x: Int) -> Int:
    return x * 2

def main() -> Int32:
    var fns = [dbl, dbl]
    var acc = 0
    acc = apply_arg(3, fns[0])
    print(acc)
    return 0
"""

PASSING_ELEMENT_POSITIVE_CPYTHON = "6"

NOT_AN_ADDRESS_CALLING_LOCAL = """\
def main(n: Int) -> Int32:
    var f = 17
    return f(n)
"""

# The same fact as `CALL_THROUGH_A_PARAMETER`, one position out: a function of
# THIS UNIT read as a WORD rather than called by name. It is this program's
# `plain` that used to be the first name with nowhere to live, and it is the
# whole of §5 — one word, the function's entry address, materialized by
# `_load_var` and handed to `call_it` like any other argument.
FUNCTION_AS_VALUE = """\
def plain(v: Int32) -> Int32:
    return v + 100

def call_it(f, x: Int32) -> Int32:
    return f(x)

def main() -> Int32:
    var b = call_it(plain, 5)
    print(b)
    return 0
"""

# THE TILE SHAPE, and the program this file's §5 is about.
#
# `workgroup_function: Some[def[width: Int](Int) -> Int]` is
# `std/algorithm/backend/tile.mojo`'s own declaration with the function type
# written out instead of behind its `comptime Static1DTileUnitFunc` alias,
# because that is the spelling this repository's INTERPRETER can execute (see
# `bugs/CODEGEN_comptime_function_type_alias_is_erased_by_the_parser.md`) — and a
# differential test needs an oracle, so the alias comes off and nothing else
# changes: the brackets still bind a comptime parameter of the callee's type,
# and the callee is still a word.
#
# The specialization is a ONE-bracket one, because a comma inside a nested type
# application does not parse (`Some[def[w: Int, h: Int](Int) -> Int]` is a
# SyntaxError; the parser reads the items as two arguments of `Some`), so the
# two-parameter form is spelled with the function type at the top level of the
# annotation instead — `TWO_BRACKET_CALL` below.
TILE_CALL = """\
def work[width: Int](offset: Int):
    return offset + width

def tile(offset: Int, upperbound: Int, workgroup_function: Some[def[width: Int](Int) -> Int]) -> Int:
    var total = 0
    var current_offset = offset
    while current_offset <= upperbound - 3:
        total += workgroup_function[3](current_offset)
        current_offset += 3
    return total

def main():
    print(tile(0, 10, work))
    return 0
"""

# The same program with `tile` in ANOTHER MODULE, which is the shape the sweep
# cares about: `stdlib/std/algorithm/backend/tile.mojo` is a library a consumer
# imports, and the function value crosses INTO it. The consumer's own function
# is materialized as an address in the consumer's image and the callee in the
# library branches through the word, so neither image needs the other's
# functions to be in its label table.
TILE_LIB = """\
def tile(offset: Int, upperbound: Int, workgroup_function: Some[def[width: Int](Int) -> Int]) -> Int:
    var total = 0
    var current_offset = offset
    while current_offset <= upperbound - 3:
        total += workgroup_function[3](current_offset)
        current_offset += 3
    return total
"""

TILE_PROGRAM = """\
from lib import tile

def work[width: Int](offset: Int):
    return offset + width

def main():
    print(tile(0, 10, work))
    return 0
"""

# TWO brackets through a value: `f[w, h](x)`. The annotation is a bare
# function type because a comma inside `Some[…]` does not parse, and the
# parser reduces a function-typed parameter to `def ... -> R` — it does not
# keep the parameter list — so this is also the case that pins why the reader
# can classify the bracket but not COUNT it.
TWO_BRACKET_CALL = """\
def add(a: Int, b: Int) -> Int:
    return a + b

def two(f: def[w: Int, h: Int](Int) -> Int, x: Int) -> Int:
    return f[2, 5](x)

def main():
    print(two(add, 10))
    return 0
"""

# A value stored in a LOCAL and called from there, and a bare call through an
# UNANNOTATED parameter: `stdlib/std/algorithm/backend/cpu/map.mojo`'s shape,
# which has no brackets to read and so needs no annotation.
BARE_AND_VIA_LOCAL = """\
def add(a: Int, b: Int) -> Int:
    return a + b

def bare(f, n: Int) -> Int:
    var t = 0
    var i = 0
    while i < n:
        t += f(i, 100)
        i += 1
    return t

def via_local(f, x: Int) -> Int:
    var g = f
    return g(x, 100)

def main():
    print(bare(add, 4))
    print(via_local(add, 7))
    return 0
"""


def write_tree(root, files):
    for rel, text in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path) or root, exist_ok=True)
        with open(path, "w") as f:
            f.write(text)


def build(root, expect_ok=True, arch="arm64", sources=("prog.mojo",)):
    """`fire.py build --formal` over `sources`; the built image under `root`."""
    out = os.path.join(root, "prog.aout")
    argv = ["build", "--formal", "--no-prove", "-o", out]
    if arch != "arm64":
        argv.append(f"--backend={arch}")
    argv += [os.path.join(root, s) for s in sources]
    result = run_fire(argv, cwd=root)
    if expect_ok:
        check(result.returncode == 0,
              f"build failed: {(result.stderr or result.stdout).strip()[-400:]}")
        check(os.path.isfile(out), f"no executable written at {out}")
    else:
        check(result.returncode != 0,
              "the build SUCCEEDED, so the construct this test pins as a "
              "refusal now compiles — and the alternative it was refusing in "
              "place of is a program that runs and answers a question nobody "
              "asked")
    return result


def text_of(result):
    return (result.stderr or result.stdout)


def run_image(root, arch="arm64"):
    out = os.path.join(root, "prog.aout")
    r = subprocess.run([out], capture_output=True, text=True, timeout=120)
    return r.returncode, (r.stderr or r.stdout).strip()


def cpython(root, sources=("prog.mojo",)):
    """The same source through CPython, so 'correct' is measured not asserted."""
    import ast
    r = subprocess.run(
        [sys.executable, "-c",
         "import sys,runpy;sys.argv=['prog'];runpy.run_path(sys.argv[0])",
         os.path.join(root, sources[0])],
        capture_output=True, text=True, timeout=120)
    return r.returncode, (r.stderr or r.stdout).strip()


def interpreter(root, source="prog.mojo"):
    """`fire.py run source` from `root`, and its stdout — the ORACLE.

    Not bare `sys.executable`: a two-file program needs `from lib import …`
    resolved, which means the repository's own module loader, which means
    `fire.py run` with `root` as the working directory. `cpython` above is
    CPython on one file and stays for the single-source cases; where a case
    needs a second module this is the reader, and the two agree on the
    single-file programs (measured per case: the case compares the oracle
    against a stated constant first, so a disagreement between them fails
    rather than passing whichever one happens to be right).
    """
    r = run_fire(["run", os.path.join(root, source)], cwd=root)
    return (r.stderr or r.stdout).strip()


# ── 1. the root of a bracket is a callee ─────────────────────────────────────

def test_a_specialization_root_is_a_callee_not_a_read(tmpdir):
    """The name check must not report a specialization's root as a value read.

    Pinned on the DECISION, in-process, because a build-level test cannot
    tell this apart from the next refusal down: the point is that the
    diagnosis is not the "module-level name of another module" one, which
    claims a storage problem the file does not have and sends the reader
    after an allocator table instead of after the call.
    """
    import fire_compiler as F
    import formal.build as B
    import formal.model as M

    src = ("from lib import widen\n"
           "def main() -> Int32:\n"
           "    var b = widen[3](5)\n"
           "    return b\n")
    stmts = F.Parser(F.py_tokenize(src)).with_filename("t").parse_module()
    # The fourth value is the unit's module-global slot table, which
    # `_prepare_functions` returns as well as publishes (a nested call for an
    # import publishes its own over ours). These probes want none of them and
    # say so by name.
    fns, structs, syms, _slots = B._prepare_functions(stmts, synthetic=False)
    M.publish_module_symbols(syms)
    try:
        B.check_module_symbols(fns, {s.name: s for s in structs})
    except Exception as e:
        text = str(e)
        check("'widen'" not in text or "no home" not in text,
              f"the specialization's root was still walked as a read of a "
              f"value: {text[:300]}")
        check("is imported from `lib`" not in text,
              f"the name check still blames a module-level name for a CALL: "
              f"{text[:300]}")


def test_the_true_case_for_that_check_is_a_plain_read(tmpdir):
    """The check is not neutered: a bare READ of an imported name is refused.

    The permissive half alone would be a hole. `lib.plain` with no call and
    no brackets is a read of a module-level name of another module, which is
    exactly what the refusal text is for, and it must still be refused.
    """
    import fire_compiler as F
    import formal.build as B
    import formal.model as M

    src = ("from lib import plain\n"
           "def main() -> Int32:\n"
           "    var b = plain\n"
           "    return 0\n")
    stmts = F.Parser(F.py_tokenize(src)).with_filename("t").parse_module()
    # The fourth value is the unit's module-global slot table, which
    # `_prepare_functions` returns as well as publishes (a nested call for an
    # import publishes its own over ours). These probes want none of them and
    # say so by name.
    fns, structs, syms, _slots = B._prepare_functions(stmts, synthetic=False)
    M.publish_module_symbols(syms)
    refused = False
    try:
        B.check_module_symbols(fns, {s.name: s for s in structs})
    except Exception as e:
        refused = True
        check("is imported from `lib`" in str(e),
              f"a bare read of an imported name is refused for the wrong "
              f"reason: {str(e)[:300]}")
    check(refused,
          "a bare read of an imported name is no longer refused at all, so "
          "the name check is now a no-op rather than a narrower check")


# ── 2. a bracketed callee this unit does not compile is refused ──────────────

def test_a_subscript_of_an_imported_value_is_refused(tmpdir):
    """`plain[3](5)` must NOT build, and must not print 105.

    The fabricated-answer case, and the reason the refusal exists. `plain`
    is a defined symbol the link line really provides, so nothing downstream
    catches a dropped bracket: before the fix the image built, ran, and
    printed `plain(5)` = 105.
    """
    root = os.path.join(tmpdir, "subscripted")
    os.makedirs(root)
    write_tree(root, {"lib.mojo": PLAIN_LIB, "prog.mojo": SUBSCRIPTED_CALL})
    result = build(root, expect_ok=False)
    text = text_of(result)
    check("plain" in text,
          f"the refusal does not name the callee: {text.strip()[-300:]}")
    check("brackets cannot be bound" in text,
          f"the refusal is not the specialization one, so a dropped bracket "
          f"is still not what is being reported: {text.strip()[-300:]}")
    check(str(SUBSCRIPTED_CALL_CPYTHON) in text or "dropped" in text,
          f"the refusal does not say the brackets were dropped, which is the "
          f"fact that makes it actionable: {text.strip()[-300:]}")


def test_a_cross_module_specialization_is_refused(tmpdir):
    """A generic of ANOTHER module, specialized: refused, not emitted.

    The `_get_kgen_string[asm]()` shape from `std/sys/_assembly.mojo`. The
    instantiation is the boundary symbol (doc/ABI.md §Generics) and this path
    does not monomorphize, so there is no callee here to pass leading
    arguments to.

    The library also exports a CONCRETE `anchor`, so it builds as a dylib at
    all: a module exporting only the generic is refused earlier, by the export
rule, with an equally true message about there being no boundary symbol.
    That refusal is real and is not what this case is about.

    **WHICH REFUSAL, and why it is not the brackets' one.** This case asserted
    "brackets cannot be bound" and was RED on `master` at `c5ab524d` (measured:
    `git archive HEAD` into a scratch tree, `python3
    test_formal_specialization.py` → `PASS=6 FAIL=1`, this case, verbatim).
    `build.py::_bracketed_export_gap` now asks the EXPORT rule first — on
    purpose, and its own docstring says why: a private name, a generic
    template, an overload and a C library name are four facts about what a
    module publishes, and only one of them is about brackets. So for a
    cross-module GENERIC the two refusals are structurally exclusive: the one
    thing `doc/ABI.md`'s export rule never publishes is a generic, so a
    cross-module generic can never reach the bracket check. The case now pins
    the refusal that fires, and names `widen` — which is the part of the
    original assertion that was right and worth keeping.

    **WHICH of the two refusals answers `widen[3](5)` has now changed TWICE, and
    the answer this case pins is the brackets' own.** It used to be
    `specialization_call_refusal` (this case asserted "brackets cannot be bound"
    and was RED on `master` at `c5ab524d`), then the EXPORT rule, because
    `_bracketed_export_gap` asks the export rule first for a bracketed callee
    whose base name is imported and whose module's library on the link line does
    not publish it. It is the brackets' again, and not because anything moved
    the check — because `formal/imports.py::library_free_edges` (per-edge, added
    with the sweep) now declines to BUILD that library at all: `from lib import
    widen` binds one name, it is a template, and no INSTANTIATION is demanded of
    it, so the edge needs no library. `widen[3]` names a VALUE, and
    `instantiation_demands` reads type arguments, so there is no demand; the
    library is not built, `link_line` is empty, and
    `_module_published_names`' empty-table guard sends `_bracketed_export_gap`
    back to the brackets' sentence.

    That is not a regression of the export rule, it is the export rule losing a
    shape it never had: for a cross-module GENERIC both brackets now answer.
    `widen[Int32](5)` names a type, so it IS a demand, the library IS built, and
    the call is MONOMORPHIZED into it and runs
    (`test_formal_monomorph.py::test_a_generic_function_template_is_
    instantiated_too`); `widen[3](5)` names a value, so there is no
    instantiation to compile and the refusal says exactly that —
    *"its brackets named no type argument, named a value rather than a type"* —
    which is more specific than anything the export rule could say about it.
    So the export-rule arm of `_bracketed_export_gap` is now reachable only for
    a name that is not a template at all, and
    `test_a_bracketed_callee_the_module_does_not_publish_says_the_export_rule`
    below pins it on the private dotted member that function's own docstring
    names. `plain[3](5)` — the base name the module DOES publish — is
    `test_a_cross_module_specialization_of_a_published_name_says_brackets`.
    """
    root = os.path.join(tmpdir, "crossmodule")
    os.makedirs(root)
    write_tree(root, {"lib.mojo": GENERIC_LIB, "prog.mojo":
                      CROSS_MODULE_SPECIALIZATION})
    result = build(root, expect_ok=False)
    text = text_of(result)
    check("widen" in text,
          f"the refusal does not name the callee: {text.strip()[-300:]}")
    check("brackets cannot be bound" in text,
          f"a specialization of an UNPUBLISHED name is refused for something "
          f"other than the brackets, and the two rules are told apart by "
          f"whether the module's library exists at all: {text.strip()[-300:]}")
    check("a value rather than a type" in text,
          f"the refusal does not say WHICH of the two ways a bracket names no "
          f"instantiation this is, and it is the one that is true here — "
          f"`widen[3]` is a comptime VALUE, not a type: {text.strip()[-300:]}")
    check("doc/ABI.md" in text or "instantiation is the boundary symbol" in text,
          f"the refusal does not name the rule that keeps a template off the "
          f"boundary under its base name: {text.strip()[-300:]}")


def test_a_bracketed_callee_the_module_does_not_publish_says_the_export_rule(
        tmpdir):
    """`lib._helper[3](5)`: a PRIVATE member, so the export rule is the sentence.

    The arm of `formal/build.py::_bracketed_export_gap` that
    `test_a_cross_module_specialization_is_refused` used to reach and no longer
    can: `_helper` is not a template, so the edge binds a name the module could
    publish and `library_free_edges` keeps the library — and a library whose
    private names are excluded from its export table publishes no `_helper`, so
    `_bracketed_export_gap` answers before the bracketed scan does. `doc/ABI.md`'s
    rule names four exclusions and this case pins one of them (a leading `_` is
    private), so a refusal that stopped being able to say which would still pass
    the two rules it shares with every other exclusion.

    Bound as `from lib import _helper` rather than reached as `lib._helper`,
    because that is the spelling the message names: a DOTTED chain reduces to
    its module, so `lib._helper[3](5)` is refused about `lib` — measured, and
    true, but a different question from this one. (`_bracketed_export_gap`'s
    docstring's own example is dotted, so it is worth knowing that the dotted
    spelling does not reach it: that is what `check_library_free_calls` and the
    module-attribute rules are for.)
    """
    root = os.path.join(tmpdir, "exportgap")
    os.makedirs(root)
    write_tree(root, {"lib.mojo": PRIVATE_MEMBER_LIB,
                      "prog.mojo": BRACKETED_PRIVATE_CALL})
    result = build(root, expect_ok=False)
    text = text_of(result)
    check("_helper" in text,
          f"the refusal does not name the callee: {text.strip()[-300:]}")
    check("does not export it" in text or "does not publish" in text,
          f"a bracketed callee the module does not PUBLISH is refused for "
          f"something other than the export rule, which is the fact that "
          f"decides it: {text.strip()[-300:]}")
    check("a name with a leading `_` is private" in text,
          f"the refusal does not say WHICH of the four exclusions keeps this "
          f"name off the boundary, and it is the private one: "
          f"{text.strip()[-300:]}")
    check("doc/ABI.md" in text or "export rule" in text,
          f"the refusal does not name the rule that keeps the name off the "
          f"boundary: {text.strip()[-300:]}")
    check("one per instantiation" in text or "monomorph" in text
          or "instantiation is the boundary symbol" in text,
          f"the refusal does not say WHY a name is not one boundary symbol: "
          f"{text.strip()[-300:]}")


def test_a_cross_module_specialization_of_a_published_name_says_brackets(tmpdir):
    """The other half of the split: a base name the module DOES publish.

    `plain[3](5)`, and it is the case `_bracketed_export_gap` deliberately
    leaves to `specialization_call_refusal`: `plain` is exported perfectly
    well, so there IS a symbol for the call to bind and the only reason it has
    no callee is the brackets — which are the generic's comptime parameters,
    ordinary leading arguments the call site would have to evaluate and pass,
    and there is no declaration in hand to decide that against. Told the
    export rule instead, the reader goes looking for a missing symbol in a
    library that has one, which is the wrong errand and the expensive one.

    This row is here because the case above stopped pinning it. It was the
    only assertion of the brackets' own sentence for a cross-module
    specialization, and `_bracketed_export_gap` was measured on exactly this
    program and reported as keeping it while the needle stayed pointed at the
    generic — so a change that sent BOTH halves to the export rule would have
    passed the suite.
    """
    root = os.path.join(tmpdir, "crossmodule_published")
    os.makedirs(root)
    write_tree(root, {"lib.mojo": PLAIN_LIB, "prog.mojo": SUBSCRIPTED_CALL})
    result = build(root, expect_ok=False)
    text = text_of(result)
    check("plain" in text,
          f"the refusal does not name the callee: {text.strip()[-300:]}")
    check("brackets cannot be bound" in text,
          f"a bracketed callee the module DOES publish is refused by the "
          f"export rule rather than by the brackets, which are the only "
          f"thing wrong with it: {text.strip()[-300:]}")
    check("monomorph" in text or "instantiation is the boundary symbol" in text,
          f"the refusal does not say WHY a cross-module instantiation has no "
          f"callee here: {text.strip()[-300:]}")


def test_both_architectures_refuse_the_same_construct_the_same_way(tmpdir):
    """    The text is arch-free, so the two machines cannot answer differently.

    x86-64 has no `SubscriptExpr` branch in `_callee_symbol` at all, so it was
    answering this construct with "unsupported call target on the formal x86-64
    path (got SubscriptExpr)" — an AST node the author never wrote. Measured
    with the callee check already fixed: arm64 BUILT the program and printed
    105, and x86-64 refused it with that text. One construct, two machines,
    one of them producing an answer the source does not contain.

    This test passes on some earlier trees, and that is correct rather than
    weak: it pins the INVARIANT (the two agree), and the tree where they
    disagreed had arm64 building a wrong image, which the build-level tests
    above catch directly.
    """
    seen = {}
    for arch in ARCHES:
        root = os.path.join(tmpdir, f"arch_{arch}")
        os.makedirs(root)
        write_tree(root, {"lib.mojo": PLAIN_LIB, "prog.mojo":
                          SUBSCRIPTED_CALL})
        seen[arch] = text_of(build(root, expect_ok=False, arch=arch)).strip()
    a, b = seen["arm64"], seen["x86_64"]
    check(a == b,
          "the two architectures refused one construct differently:\n"
          f"  arm64:  {a[:220]}\n  x86-64: {b[:220]}")


# ── 3. a LOCAL specialization still lowers and runs ─────────────────────────

def test_a_local_specialization_runs_and_matches_cpython(tmpdir):
    """The permissive half, pinned by EXECUTION against CPython.

    The refusal above is scoped to a callee this unit does not compile. A
    specialization of a function in the same unit has its declaration in hand,
    its brackets become leading arguments, and it must keep working — a test
    that only checked the refusals would pass with the whole feature turned
    off.
    """
    root = os.path.join(tmpdir, "local")
    os.makedirs(root)
    write_tree(root, {"prog.mojo": LOCAL_SPECIALIZATION})
    build(root)
    code, out = run_image(root)
    check(code == 0, f"the image exited {code}: {out[:300]}")
    check(out == str(LOCAL_SPECIALIZATION_CPYTHON),
          f"a local specialization printed {out!r}, not "
          f"{LOCAL_SPECIALIZATION_CPYTHON} — the bracket did not reach the "
          f"callee as a leading argument")


# ── 4. the OTHER bracketed callee, which is not a specialization ─────────────

def test_an_external_call_template_is_not_refused_as_a_specialization(tmpdir):
    """The two bracket-that-are-callees do not collide, on either machine.

    `external_call["sym", RetType](args)` and `f[a, b](args)` are the SAME AST
    shape — a `CallExpr` whose callee is a `SubscriptExpr` — and the refusals
    that keep them apart are both keyed on that shape alone. So this is a
    regression test for an interaction rather than for a construct: the
    specialization refusal was landed without the `is_extern_call` guard, and it
    then fired on the `external_call` it is supposed to be silent about. It
    fired on every one of them — 15 of the 29 cases in
    `test_formal_external_call.py` failed the moment the two landed in one tree,
    and `std/os/env.mojo`'s 55 files went back to refusing on a construct that
    lowers.

    The two differ by a question only `M.is_external_call_template` can answer,
    so that is what decides it, and a CALLEE's brackets are not read as a
    comptime parameter list. Pinned on BOTH architectures because the guard is
    written twice and either copy can lose it.
    """
    src = ("def main() -> Int32:\n"
           "    var n = external_call[\"strlen\", Int32](\"abcd\")\n"
           "    print(n)\n"
           "    return 0\n")
    for arch in ARCHES:
        root = os.path.join(tmpdir, f"xc_{arch}")
        os.makedirs(root)
        with open(os.path.join(root, "prog.mojo"), "w") as f:
            f.write(src)
        build(root, arch=arch)
        code, out = run_image(root, arch)
        check(code == 0,
              f"[{arch}] the image exited {code}: {out[:300]}")
        check(out == "4",
              f"[{arch}] printed {out!r}, not '4' — the C symbol's return "
              f"value did not reach the program")


# ── 5. a function VALUE is a code ADDRESS, in three positions ───────────────
#
# One fact and three halves, and the fact is that a function value IS one of
# this path's values: a formal value is one 64-bit word with a home in a
# register, a spill slot, a receiver's frame or a folded module constant, and
# the word a function needs is its code ADDRESS. It used to have no home — the
# word's TARGET is what this build could not establish — and it does now.
#
# ARGUMENT position — `call_it(plain, 5)`, where `plain` is a function of THIS
# unit read as a word: lowered, and pinned by execution against CPython. The
# shape `std/algorithm/backend/tile.mojo` reaches for is a callee that is a
# PARAMETER, so the brackets are a specialization of a function TYPE and the
# callee itself is a word; that is what §5's other cases answer.
#
# CALLEE position — `func(i)` where `func` arrived as a parameter, and
# `workgroup_function[3](offset)`, the same word with brackets on it: caught at
# the call site by `model.callee_is_a_bound_value` /
# `model.callee_value_refusal` beside `specialization_call_refusal`, both
# backends asking the same two shared functions. This is the whole body of
# `stdlib/std/algorithm/backend/cpu/map.mojo`.
#
# The two checks are separate code on purpose — one is a decision about what a
# NAME denotes, the other about what a call may do to it — so each half is
# pinned where it lives. Neither may swallow the ordinary cases: a local that
# shadows a function is the local, and a name declared `global` is not a local
# of the function at all.


def test_a_function_read_as_a_value_is_a_code_address(tmpdir):
    """`call_it(plain, 5)` RUNS and answers CPython, on both machines.

    The construct used to be refused twice over, by two different pieces of
    code, and each refusal is worth remembering because what replaced it is
    not a special case:

    It is also the answer to the question `std/algorithm/backend/tile.mojo`
    raises. That call is `workgroup_function[tile_size](offset)` where
    `workgroup_function` is a parameter, so the refusal a reader meets first
    is about the BRACKETS — and the wall behind it is that the callee is a
    value at all, which is what this case pins. Pinned on both architectures:
    the two backends each have their own copy of the placement fallback, and
    either one losing the check is a different diagnostic for one construct.

      * `formal/build.py`'s name-placement walk answered "a FUNCTION … is not
        a value on this path", and before that the emitter's placement
        fallback answered "'plain' has no home: the register allocator
        collected no home for it …" — a true statement about the allocator and
        a useless one, because it sends the reader looking for a
        register-allocation bug in a program whose problem was a construct;
      * `model.function_value_refusal`'s own text said a function "has no
        representation here", which is what a CODE ADDRESS is not: a function
        value is one word, and the word is the address.

    Both are now `ADRP`+`ADD` from the function's entry label (arm64) and
    `LEA r, [rip+d]` (x86-64), and the value lands in a register, a spill slot
    or a call's argument exactly as any other word does. Pinned by EXECUTION
    against CPython on BOTH architectures, because "it compiled" is the weaker
    half and the two backends have two copies of every decision this touches.

    **And the refusal this case used to pin is not gone, it is NARROWER.** It
    was `model.function_value_refusal`, which was DEFINED TWICE in
    `formal/model.py` — two commits, two honest wordings, one refusal — and
    Python's rebinding made the first dead, so for one gate this case asserted a
    sentence no build could print and was red on a tree whose behaviour was
    correct. The dead definition is deleted; what survives of that sentence is
    the arm for a function of ANOTHER image (`_extern_decls`, whose body is in
    a library and whose address would need a GOT slot), which no program in this
    file can reach — a Mojo module function read as a value is stopped earlier
    and better, by `module_state_no_storage`'s rule that a dylib publishes
    FUNCTIONS and folded CONSTANTS and not a VARIABLE. So the history now lives
    where the sentence does: `formal/model.py::function_value_refusal`'s own
    docstring carries the duplicate and the measurement only the dead copy
    recorded. The duplicate cannot come back —
    `test_formal_external_call.py`'s `no_module_level_name_is_bound_twice_in_model`
    fails on any module-level name bound twice in `formal/model.py`.
    """
    for arch in ARCHES:
        root = os.path.join(tmpdir, f"fnvalue_{arch}")
        os.makedirs(root)
        with open(os.path.join(root, "prog.mojo"), "w") as f:
            f.write(FUNCTION_AS_VALUE)
        build(root, arch=arch)
        code, out = run_image(root, arch)
        check(code == 0, f"[{arch}] the image exited {code}: {out[:300]}")
        check(out == str(FUNCTION_AS_VALUE_CPYTHON),
              f"[{arch}] printed {out!r}, not "
              f"{FUNCTION_AS_VALUE_CPYTHON} — a function passed as an argument "
              f"is not reaching the caller as the function's address")


def test_a_local_shadowing_a_function_is_still_read_as_the_local(tmpdir):
    """The negative guard: the check must not fire on a name the function binds.

    `placed` in `formal/build.py` deliberately contains every function name of
    the image, because that is what lets a specialization's root and a bracketed
    callee through as callees; the function-value pre-pass subtracts those names
    and asks about the rest. A parameter or a local that SHADOWS a module-level
    function is the local, and shadowing is ordinary Mojo — so this is the case
    that would break if the pre-pass asked about the name alone.
    """
    src = ("def plain(v: Int32) -> Int32:\n"
           "    return v + 100\n"
           "\n"
           "def main() -> Int32:\n"
           "    var plain = 7\n"
           "    return plain + 1\n")
    for arch in ARCHES:
        root = os.path.join(tmpdir, f"shadow_{arch}")
        os.makedirs(root)
        with open(os.path.join(root, "prog.mojo"), "w") as f:
            f.write(src)
        build(root, arch=arch)
        code, out = run_image(root, arch)
        check(code == 8,
              f"[{arch}] a local shadowing a function exited {code} "
              f"(printed {out.strip()[:80]!r}), so the shadowing local was "
              f"refused or read as something else")


# ── 5b. the CALLEE half: a name the calling function BINDS is not a symbol ───

def test_a_call_through_a_parameter_runs_on_both_architectures(tmpdir):
    """`func(i)` where `func` is a parameter: one `BLR`/`CALL r64`, and CPython's
    answer.

    The other half of "a name this unit does not compile", and the one that
    could not be told from a C symbol: `is_extern = name not in
    self._functions` is true of a parameter as much as of `printf`, and the
    extern path's job is to emit a call to a symbol, so it emitted a call to a
    symbol spelled `func`. The image was written and then the loader refused it
    — reported as `the image would bind 1 symbol(s) that nothing provides`, a
    true sentence about the link line that says nothing about the construct.

    It now branches through the word, and the shape is the whole body of
    `stdlib/std/algorithm/backend/cpu/map.mojo` (`func(i)`, one line of callee).
    `via_local` in the same program is the second spelling: the value read into
    a local first, so the address goes through a spill slot as well as a
    register, and a lowering that only materialized it in a register would pass
    the first half and fail this one.

    Both halves are pinned by EXECUTION against CPython on BOTH architectures.
    A value call is the one construct in this file whose lowering is a
    REGISTER-SHUFFLE question rather than a naming question — the callee must be
    evaluated before the arguments and kept across them — so a wrong answer here
    is a wrong number rather than a refusal, and only running it can see that.
    """
    for arch in ARCHES:
        root = os.path.join(tmpdir, f"value_{arch}")
        os.makedirs(root)
        with open(os.path.join(root, "prog.mojo"), "w") as f:
            f.write(BARE_AND_VIA_LOCAL)
        build(root, arch=arch)
        code, out = run_image(root, arch)
        check(code == 0, f"[{arch}] the image exited {code}: {out[:300]}")
        check(out == BARE_AND_VIA_LOCAL_CPYTHON,
              f"[{arch}] printed {out!r}, not {BARE_AND_VIA_LOCAL_CPYTHON!r} — a "
              f"call through a parameter, or through a local holding one, did "
              f"not reach the function")


def test_a_specialization_through_a_value_runs_on_both_architectures(tmpdir):
    """THE ROW: `workgroup_function[tile_size](offset)`, both machines, CPython.

    `std/algorithm/backend/tile.mojo:83`, and the shape the 163-file chain in
    `bugs/FORMAL_sweep_work_map_2026-10-03_b9.md` §4.1 lands on: a
    specialization whose CALLEE is a word. Three things have to be true at once
    and none of them is implied by the other two, which is why this is one case
    and not three:

      * the call is through a WORD, so the brackets have no declaration to bind
        against — they are passed as ordinary leading arguments, which is what
        `comptime.param_names` says a comptime parameter is on this path;
      * the bracket is not an INDEX, and the only thing that can say so is the
        parameter's declared type (`Some[…]` cannot be subscripted at all), so
        the annotation is load-bearing rather than documentation;
      * the callee is in another MODULE, so the word crosses an image boundary
        as data and the callee needs no symbol for it.

    The `Some[…]` annotation is what the stdlib itself writes
    (`workgroup_function: Some[Static1DTileUnitFunc]`), so this is the program's
    own declaration rather than one written for the test.
    """
    for arch in ARCHES:
        root = os.path.join(tmpdir, f"tile_{arch}")
        os.makedirs(root)
        with open(os.path.join(root, "prog.mojo"), "w") as f:
            f.write(TILE_CALL)
        build(root, arch=arch)
        code, out = run_image(root, arch)
        check(code == 0, f"[{arch}] the image exited {code}: {out[:300]}")
        check(out == TILE_CALL_CPYTHON,
              f"[{arch}] printed {out!r}, not {TILE_CALL_CPYTHON} — the "
              f"specialization's brackets did not reach the callee as leading "
              f"arguments, or the call did not go through the word at all")


def test_the_specialization_reaches_into_another_module_on_both(tmpdir):
    """The same call, with the callee in a LINKED LIBRARY. CPython again.

    `tile.mojo` is a library: every one of the four files the sweep counts is
    reached through `std/algorithm/backend/__init__.mojo`, and a function value
    that cannot cross a dylib boundary would leave the row answering a question
    no consumer can ask. The consumer materializes the address of ITS OWN
    function and passes the word; the library branches through it. Neither image
    needs the other's functions in its label table, which is the whole reason
    the representation is an address and not a name.
    """
    for arch in ARCHES:
        root = os.path.join(tmpdir, f"tilelib_{arch}")
        os.makedirs(root)
        write_tree(root, {"lib.mojo": TILE_LIB, "prog.mojo": TILE_PROGRAM})
        want = interpreter(root, "prog.mojo")
        check(want == TILE_CALL_CPYTHON,
              f"[{arch}] the interpreter answered {want!r} for the cross-module "
              f"program, not {TILE_CALL_CPYTHON!r}, so the oracle this case "
              f"compares against is not the same program")
        build(root, arch=arch, sources=("prog.mojo", "lib.mojo"))
        code, out = run_image(root, arch)
        check(code == 0, f"[{arch}] the image exited {code}: {out[:300]}")
        check(out == want,
              f"[{arch}] printed {out!r}, not {want!r} — a function value did "
              f"not cross into the linked library")


def test_two_brackets_through_a_value_pass_both_on_both(tmpdir):
    """`f[w, h](x)`: a comma list is TWO arguments, and both arrive.

    `workgroup_function[tile_size_x, tile_size_y](x, y)` is
    `tile.mojo`'s `tile2d`, and a comma list is one AST node to read and two
    arguments to pass. `formal/monomorph.py::bracket_items` is the one place
    that expands it, because the OTHER reader of the same bracket — the demand
    walk that asks whether a bracket spells type arguments — has to expand it
    identically or the two disagree about `f[a, b]`.

    The expected value is STATED rather than read from the interpreter, and
    that is a real difference from the other three cases: the interpreter
    cannot execute this program — `f[2, 5](x)` through a value answers `None`
    there, and so does `add[2, 5](x)` through a NAME, so the gap is in
    `_MojoBoundComptimeFunction` (the interpreter's own bound-comptime object,
    which answers `None` rather than binding the items and calling through) and
    not in this construct. The formal answer is the one the interpreter gives
    for the same call spelled with the items as ordinary arguments,
    `add(2, 5)` = 7, which is what a comptime parameter IS on this path.
    """
    for arch in ARCHES:
        root = os.path.join(tmpdir, f"two_{arch}")
        os.makedirs(root)
        with open(os.path.join(root, "prog.mojo"), "w") as f:
            f.write(TWO_BRACKET_CALL)
        build(root, arch=arch)
        code, out = run_image(root, arch)
        check(code == 0, f"[{arch}] the image exited {code}: {out[:300]}")
        check(out == TWO_BRACKET_CALL_CPYTHON,
              f"[{arch}] printed {out!r}, not {TWO_BRACKET_CALL_CPYTHON!r} — "
              f"the bracket's two items did not both arrive as leading "
              f"arguments")


def test_the_two_remaining_refusals_of_a_value_call(tmpdir):
    """What is still refused, by name, and why each one has no answer here.

    Three shapes, one per decision, all asked by both backends from the same
    two shared functions so the architectures cannot disagree about them:

      * a KEYWORD through a value — `f(x=1)`, and a keyword item in the
        bracket. A keyword names a parameter, and a callee reached through a
        word has no parameter list in hand; binding it would mean inventing
        one. Positionally it is the same program.
      * a bracket this build cannot read — an UNANNOTATED parameter, where the
        bracket could be a specialization or an index into a container and the
        declared type is the only thing that can say. This is the half of
        `map.mojo`'s shape that stays refused, and it is right to: `f[0](x)`
        through an untyped `f` is genuinely ambiguous.
      * a parameter whose declared type CANNOT hold a function — `List[Int]`,
        where the brackets are necessarily an index. A call through it is a
        branch to whatever word the container held.

    The bare call through the same unannotated parameter is NOT in this list and
    must keep working: there is no bracket to read, which is the whole
    difference between `map.mojo` and `tile.mojo`.
    """
    keyword = ("def add(a: Int, b: Int) -> Int:\n"
               "    return a + b\n\n"
               "def call_kw(f, x: Int) -> Int:\n"
               "    return f(x, b=2)\n\n"
               "def main():\n"
               "    print(call_kw(add, 1))\n"
               "    return 0\n")
    unreadable = ("def add(a: Int, b: Int) -> Int:\n"
                  "    return a + b\n\n"
                  "def call_bracketed(f, x: Int) -> Int:\n"
                  "    return f[2, 5](x)\n\n"
                  "def main():\n"
                  "    print(call_bracketed(add, 10))\n"
                  "    return 0\n")
    not_callable = ("def call_container(f: List[Int], x: Int) -> Int:\n"
                    "    return f(x)\n\n"
                    "def main():\n"
                    "    var xs = [1, 2, 3]\n"
                    "    print(call_container(xs, 4))\n"
                    "    return 0\n")
    seen = {}
    for arch in ARCHES:
        for label, src, needles in (
                ("kw", keyword, ("keyword argument in",
                                 "no declaration to bind it by NAME")),
                ("bracket", unreadable, ("bracketed call through a VALUE",
                                         "does not declare one this path can "
                                         "read")),
                ("container", not_callable, ("a word that is not a code "
                                             "address is nothing to branch "
                                             "through", "`List[Int]`"))):
            root = os.path.join(tmpdir, f"refuse_{label}_{arch}")
            os.makedirs(root)
            with open(os.path.join(root, "prog.mojo"), "w") as f:
                f.write(src)
            text = text_of(build(root, expect_ok=False, arch=arch)).strip()
            for needle in needles:
                check(needle in text,
                      f"[{arch}] the {label} case did not refuse with its own "
                      f"sentence ({needle!r}): {text[-300:]}")
            seen.setdefault(label, []).append(text)
    for label, texts in seen.items():
        check(texts[0] == texts[1],
              f"the two architectures refused the {label} case differently:\n"
              f"  arm64:  {texts[0][:200]}\n  x86-64: {texts[1][:200]}")


def test_a_global_shadowed_name_is_still_a_call_to_the_c_library(tmpdir):
    """The control: the check must not swallow an ordinary extern call.

    `global printf` makes `printf` a name the function writes but NOT a local
    of it — the module's binding is what `printf(…)` still means, and the
    register allocator already answers it that way
    (`global_names_bound_in`). A callee check that read "does this body
    mention the name" would refuse this, and the refusal would be false: the
    image builds, links and prints, on both architectures.

    Run rather than built, because "it compiled" is the weaker half.
    """
    for arch in ARCHES:
        root = os.path.join(tmpdir, f"gshadow_{arch}")
        os.makedirs(root)
        write_tree(root, {"prog.mojo": GLOBAL_SHADOW_CALLS_THE_C_LIBRARY})
        build(root, arch=arch)
        code, out = run_image(root, arch)
        check(code == 0, f"[{arch}] the image exited {code}: {out[:300]}")
        check(out == GLOBAL_SHADOW_CPYTHON,
              f"[{arch}] printed {out!r}, not {GLOBAL_SHADOW_CPYTHON!r} — a "
              f"name declared `global` stopped being a call to the C library")



def test_a_word_the_source_says_is_not_an_address_is_refused(tmpdir):
    """Both ends of one call, on both architectures, with CPython as the oracle.

    The other half of §5b, and the one that is a REFUSAL rather than a lowering.
    A function value is a code address, so `f(i)` through a word is one
    `BLR`/`CALL r64` — and nothing proved the word IS an address. Where the
    source itself says what the word holds, the build can say so at build time,
    which is the difference between a diagnostic the author reads and a SIGBUS
    the kernel delivers.

    Three shapes because there are three sources of evidence, and each is asked
    by a different reader so a fix to one cannot make the other two pass:

      * the CALLING end is asked by both emitters, from the calling function's
        own `ValueKinds` AND from every statement that binds the callee name
        (`model.callee_word_is_not_an_address`) — the second conjunct is what
        stops the model's own "a word is an integer" default from refusing the
        `via_local` row above, so both directions are pinned here;
      * the PASSING end is asked from `formal/build.py`'s name-placement walk,
        which is the only pass holding the callee and the call site at once. Its
        last two rows are decided by the CALLER's own statements rather than by
        a declaration or a spelling, so they are also the rows a change to the
        value model cannot silently take with it.

    **The oracle is checked, not assumed.** CPython raises `TypeError` on all
    three programs, so "this path used to build and trap" is a measurement of a
    real disagreement rather than a preference; and the two architectures are
    required to produce the SAME sentence, because the whole point of the
    readers being in `formal/model.py` rather than in a backend is that they
    cannot answer one construct differently.
    """
    shapes = (
        ("passing/literal", NOT_AN_ADDRESS_PASSING_LITERAL,
         "passed to `apply_arg()` as parameter `f`"),
        ("passing/declared", NOT_AN_ADDRESS_PASSING_DECLARED,
         "a value declared `Int`"),
        ("passing/local", NOT_AN_ADDRESS_PASSING_LOCAL,
         "holds an integer, passed to `apply_arg()` as parameter `f`"),
        ("passing/element", NOT_AN_ADDRESS_PASSING_ELEMENT,
         "holds an element read out of a container literal"),
        ("calling/local", NOT_AN_ADDRESS_CALLING_LOCAL,
         "and every statement of the function that binds it writes that"),
    )
    seen = {}
    for label, src, needle in shapes:
        root = os.path.join(tmpdir, f"notaddr_{label.replace('/', '_')}")
        os.makedirs(root)
        with open(os.path.join(root, "prog.mojo"), "w") as f:
            f.write(src)
        # The interpreter, not bare `cpython`: `fire.py run` resolves a
        # multi-file program and this row's oracle is the sentence both engines
        # agree on for a program they both reject.
        oracle = interpreter(root)
        check(oracle.startswith("TypeError:") or "TypeError:" in oracle,
              f"[{label}] the interpreter answered "
              f"{oracle.strip()[:200]!r} on a program whose only wrongness is "
              f"calling a word that is not a function, so the oracle for this "
              f"row is not saying what the row is about")
        for arch in ARCHES:
            arch_root = os.path.join(root, arch)
            os.makedirs(arch_root)
            with open(os.path.join(arch_root, "prog.mojo"), "w") as f:
                f.write(src)
            text = text_of(build(arch_root, expect_ok=False,
                                 arch=arch)).strip()
            check("is called as a FUNCTION and the source says it holds"
                  in text,
                  f"[{arch}] the {label} case did not refuse with the "
                  f"not-an-address message: {text[-300:]}")
            check(needle in text,
                  f"[{arch}] the {label} case refused without naming which "
                  f"end of the call it stopped at ({needle!r}): {text[-300:]}")
            seen.setdefault(label, []).append(text)
    for label, texts in seen.items():
        check(texts[0] == texts[1],
              f"the two architectures refused the {label} case differently:\n"
              f"  arm64:  {texts[0][:200]}\n  x86-64: {texts[1][:200]}")


def test_a_list_of_functions_is_still_an_address_to_subscript(tmpdir):
    """`xs[0]` where the literal holds FUNCTIONS: builds, runs, CPython's answer.

    The control for `passing/element` in the row above, and it is here because
    that reader's narrowness is the only thing worth claiming about it.
    `model.caller_local_element_holds` refuses a subscript of a local **only**
    where every syntactic write of the name is a container literal whose every
    element is itself not an address; this program is the same spelling with a
    function in the literal, so it is the case that narrowness is FOR, and a
    reader that classified `xs[0]` by its spelling would refuse the ordinary
    program `map.mojo` writes.

    Run rather than refused-checked, because the shape's whole point is that a
    value call through a subscripted list element reaches the function.
    """
    for arch in ARCHES:
        root = os.path.join(tmpdir, f"fnlist_{arch}")
        os.makedirs(root)
        with open(os.path.join(root, "prog.mojo"), "w") as f:
            f.write(PASSING_ELEMENT_POSITIVE)
        build(root, arch=arch)
        code, out = run_image(root, arch)
        check(code == 0, f"[{arch}] the image exited {code}: {out[:300]}")
        check(out == PASSING_ELEMENT_POSITIVE_CPYTHON,
              f"[{arch}] printed {out!r}, not "
              f"{PASSING_ELEMENT_POSITIVE_CPYTHON!r} — a subscript of a list "
              f"OF FUNCTIONS stopped reaching the function")


TESTS = [
    ("a specialization's root is a callee, not a read",
     test_a_specialization_root_is_a_callee_not_a_read),
    ("a bare read of an imported name is still refused",
     test_the_true_case_for_that_check_is_a_plain_read),
    ("a subscript of an imported value is refused, not silently dropped",
     test_a_subscript_of_an_imported_value_is_refused),
    ("a cross-module specialization is refused by name",
     test_a_cross_module_specialization_is_refused),
    ("a bracketed callee the module does not publish says the export rule",
     test_a_bracketed_callee_the_module_does_not_publish_says_the_export_rule),
    ("a cross-module specialization of a PUBLISHED name says brackets",
     test_a_cross_module_specialization_of_a_published_name_says_brackets),
    ("both architectures refuse it identically",
     test_both_architectures_refuse_the_same_construct_the_same_way),
    ("a local specialization lowers and matches CPython",
     test_a_local_specialization_runs_and_matches_cpython),
    ("an external_call template is not refused as a specialization",
     test_an_external_call_template_is_not_refused_as_a_specialization),
    ("a function read as a value is its code address, and runs",
     test_a_function_read_as_a_value_is_a_code_address),
    ("a local shadowing a function is still the local",
     test_a_local_shadowing_a_function_is_still_read_as_the_local),
    ("a call through a parameter runs, on both",
     test_a_call_through_a_parameter_runs_on_both_architectures),
    ("a specialization through a value runs, on both",
     test_a_specialization_through_a_value_runs_on_both_architectures),
    ("…and it reaches into a linked module, on both",
     test_the_specialization_reaches_into_another_module_on_both),
    ("two brackets through a value pass both, on both",
     test_two_brackets_through_a_value_pass_both_on_both),
    ("a word the source says is not an address is refused, on both",
     test_a_word_the_source_says_is_not_an_address_is_refused),
    ("…and a list of FUNCTIONS is still one, on both",
     test_a_list_of_functions_is_still_an_address_to_subscript),
    ("the two remaining refusals of a value call",
     test_the_two_remaining_refusals_of_a_value_call),
    ("a `global`-shadowed name is still a call to the C library",
     test_a_global_shadowed_name_is_still_a_call_to_the_c_library),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: formal output is arm64-only, host is "
              f"{platform.machine()}")
        return 0

    passed = failed = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        for name, fn in TESTS:
            try:
                fn(tmpdir)
            except TestFailure as e:
                failed += 1
                print(f"  FAIL  {name}\n        {e}")
                continue
            except Exception as e:
                failed += 1
                print(f"  ERROR {name}\n        {type(e).__name__}: {e}")
                if args.verbose:
                    import traceback
                    traceback.print_exc()
                continue
            passed += 1
            print(f"  PASS  {name}")

    print(f"\nformal specialization: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
