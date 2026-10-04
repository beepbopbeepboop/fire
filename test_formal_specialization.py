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

§5 and §5b are the OTHER name this path cannot resolve, and they are in this
file because that is where the question lives: a function VALUE has no
spelling here, in either position. A callee the calling function BINDS is a
value, not a symbol (§5b), and "a name this unit does not compile" cannot
tell the two apart — it emitted a branch against a symbol named after the
parameter and the loader refused the image four stages later. A function of
this unit read as an ARGUMENT (§5) is refused earlier and by different code,
`formal/build.py`'s name-placement walk, which used to answer with a sentence
about the register allocator. One fact, two checks; each case's docstring says
which is which.

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

# The same fact as `CALL_THROUGH_A_PARAMETER`, one position out: a function of
# THIS UNIT read as a word rather than called by name, which
# `formal/build.py`'s name-placement walk refuses with
# `model.function_value_refusal` before codegen. The callee inside `call_it` is
# a parameter too, but the walk never gets that far — `main`'s `plain` is the
# first name with nowhere to live — so this program and the one above are
# refused by different code and are pinned separately.
FUNCTION_AS_VALUE = """\
def plain(v: Int32) -> Int32:
    return v + 100

def call_it(f, x: Int32) -> Int32:
    return f(x)

def main() -> Int32:
    return call_it(plain, 5)
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

    **WHICH of the two refusals answers `widen[3](5)` changed under this case,
    and the answer is the export rule rather than the brackets — so this case
    now pins the export rule.** `_bracketed_export_gap` asks the export rule
    FIRST for a bracketed callee whose base name is imported and whose module's
    library on the link line does not publish it, and the bracketed scan falls
    through to `specialization_call_refusal` when it does publish it
    (`c245c138`, which measured `plain[3](5)` keeping the brackets' own
    sentence and did not update this needle). A generic template is not
    exported by that rule at all — it is one symbol per instantiation and the
    module exports no instantiation — so `widen` is NOT published and the
    export rule is the sentence that is true of it. This case therefore pins
    `plain`'s half's twin: the second half, a base name the module does not
    publish, and `plain[3](5)` — the base name it does — is
    `test_a_cross_module_specialization_of_a_published_name_says_brackets`
    below. Between them both arms of `_bracketed_export_gap` are pinned, which
    is what the split is for; this case used to pin the second arm twice and
    the first arm not at all.
    """
    root = os.path.join(tmpdir, "crossmodule")
    os.makedirs(root)
    write_tree(root, {"lib.mojo": GENERIC_LIB, "prog.mojo":
                      CROSS_MODULE_SPECIALIZATION})
    result = build(root, expect_ok=False)
    text = text_of(result)
    check("widen" in text,
          f"the refusal does not name the callee: {text.strip()[-300:]}")
    check("does not export it" in text or "does not publish" in text,
          f"a specialization of a name the module does not EXPORT is refused "
          f"for something other than the export rule, which is the fact that "
          f"decides it: {text.strip()[-300:]}")
    check("doc/ABI.md" in text or "export rule" in text,
          f"the refusal does not name the rule that keeps the name off the "
          f"boundary: {text.strip()[-300:]}")
    check("one per instantiation" in text or "monomorph" in text
          or "instantiation is the boundary symbol" in text,
          f"the refusal does not say WHY a cross-module instantiation has no "
          f"callee here: {text.strip()[-300:]}")


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


# ── 5. a callee this path cannot name: a function VALUE, in two positions ───
#
# One fact, two halves, and the fact is that this path has no function values:
# a formal value is one 64-bit word with a home in a register, a spill slot, a
# receiver's frame or a folded module constant, and the word a function value
# needs is a code ADDRESS whose target this build cannot establish.
#
# ARGUMENT position — `call_it(plain, 5)`, where `plain` is a function of THIS
# unit read as a word: `formal/build.py`'s name-placement walk refuses it with
# `model.function_value_refusal`, before codegen. The shape
# `std/algorithm/backend/tile.mojo` is refused for is a callee that is a
# PARAMETER, so the brackets are a specialization of a function TYPE and the
# callee itself is a word — reduced to the part that is about this path rather
# than about brackets, that is passing a function as an argument.
#
# CALLEE position — `func(i)` where `func` arrived as a parameter: the same
# fact one step in, caught at the call site by
# `model.callee_is_a_bound_value` / `model.callee_value_refusal`, which both
# backends ask from their own copy of `_emit_call` beside
# `specialization_call_refusal`. This is the whole body of
# `stdlib/std/algorithm/backend/cpu/map.mojo`.
#
# The two refusals are separate code on purpose — one is a placement walk over
# names, the other is a decision about a callee — so each half is pinned where
# it lives. Neither check may swallow the ordinary cases: a local that shadows
# a function is the local, and a name declared `global` is not a local of the
# function at all.


def test_a_function_read_as_a_value_is_refused_by_name(tmpdir):
    """A function is not a word here, and the refusal has to say THAT.

    Before this the same program was refused by the emitter's placement
    fallback: `'plain' has no home: the register allocator collected no home
    for it, so the emitter and the allocation walk disagree about this
    function's locals` — a true statement about this pass, and a useless one,
    because it sends the reader to look for a register-allocation bug in a
    program whose real problem is a construct this path does not have. Same
    shape as `external_call` used as a value, which `external_call_value_refusal`
    already names.

    It is also the answer to the question `std/algorithm/backend/tile.mojo`
    raises. That call is `workgroup_function[tile_size](offset)` where
    `workgroup_function` is a parameter, so the refusal a reader meets first
    is about the BRACKETS — and the wall behind it is that the callee is a
    value at all, which is what this case pins. Pinned on both architectures:
    the two backends each have their own copy of the placement fallback, and
    either one losing the check is a different diagnostic for one construct.

    **Why the assertions are CLAUSES and not one sentence**, which is the whole
    of this case's second history: `model.function_value_refusal` was DEFINED
    TWICE in `formal/model.py` — two commits, two honest wordings, one refusal —
    and Python's rebinding made the first dead, so for one gate this case
    asserted a sentence no build could print and was RED on a tree whose
    behaviour was correct (the dead definition is deleted; the doc that recorded
    it went with its fix, and this paragraph is what is left of it). A pin on
    one spelling of a message is what let that happen, so what is pinned here is
    what the message has to MEAN — the name the reader wrote, the construct, the
    missing representation — which survives a reword and fails on a message that
    has gone back to describing the machinery. The duplicate cannot come back:
    `test_formal_external_call.py`'s `no_module_level_name_is_bound_twice_in_model`
    fails on any module-level name bound twice in `formal/model.py`.
    """
    seen = {}
    for arch in ARCHES:
        root = os.path.join(tmpdir, f"fnvalue_{arch}")
        os.makedirs(root)
        with open(os.path.join(root, "prog.mojo"), "w") as f:
            f.write(FUNCTION_AS_VALUE)
        seen[arch] = text_of(build(root, expect_ok=False, arch=arch)).strip()
    for arch, text in seen.items():
        for needle, why in (
            ("plain",
             "the refusal does not name the name the reader wrote"),
            ("is a FUNCTION",
             "the refusal does not name the CONSTRUCT: it is still reporting "
             "a placement symptom rather than the thing that is missing"),
            ("no representation",
             "the refusal does not say what is missing, which is the fact "
             "that makes it actionable"),
        ):
            check(needle in text,
                  f"[{arch}] {why} ({needle!r}): {text[-300:]}")
        check("has no home" not in text,
              f"[{arch}] the register-allocator sentence is back: {text[-300:]}")
    # One construct, one sentence: the two backends each read the same
    # `model.function_value_refusal`, so the only way they can differ is if one
    # of them stops asking it — which is a different diagnostic for one
    # program, and the same class of defect as the shadowed definition.
    a, b = seen["arm64"], seen["x86_64"]
    check(a == b,
          "the two architectures refused one construct differently:\n"
          f"  arm64:  {a[:220]}\n  x86-64: {b[:220]}")


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

def test_a_call_through_a_parameter_is_refused_on_both_architectures(tmpdir):
    """`func(i)` where `func` is a parameter: refused by name, on both machines.

    The other half of "a name this unit does not compile", and the one that
    could not be told from a C symbol: `is_extern = name not in
    self._functions` is true of a parameter as much as of `printf`, and the
    extern path's job is to emit a call to a symbol, so it emitted a call to a
    symbol spelled `func`. The image was written and then the loader refused
    it — which the build reported as `the image would bind 1 symbol(s) that
    nothing provides`, a true sentence about the link line that says nothing
    about the construct, and a `not-answerable` class for a file that is a
    codegen gap in itself.

    Pinned on the construct rather than on the absence of that sentence, so a
    future edit cannot pass by moving the same verdict somewhere else.
    """
    seen = {}
    for arch in ARCHES:
        root = os.path.join(tmpdir, f"value_{arch}")
        os.makedirs(root)
        write_tree(root, {"prog.mojo": CALL_THROUGH_A_PARAMETER})
        seen[arch] = text_of(build(root, expect_ok=False, arch=arch)).strip()
    for arch, text in seen.items():
        for needle in ("is a name apply binds", "call through a VALUE",
                       "no representation for a function value"):
            check(needle in text,
                  f"[{arch}] the refusal does not name the construct "
                  f"({needle!r}): {text[-300:]}")
        check("would bind" not in text,
              f"[{arch}] the build still reports this as a MISSING SYMBOL "
              f"rather than as the construct that is missing, which is the "
              f"verdict this test exists to move: {text[-300:]}")
    a, b = seen["arm64"], seen["x86_64"]
    check(a == b,
          "the two architectures refused one construct differently:\n"
          f"  arm64:  {a[:220]}\n  x86-64: {b[:220]}")


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


TESTS = [
    ("a specialization's root is a callee, not a read",
     test_a_specialization_root_is_a_callee_not_a_read),
    ("a bare read of an imported name is still refused",
     test_the_true_case_for_that_check_is_a_plain_read),
    ("a subscript of an imported value is refused, not silently dropped",
     test_a_subscript_of_an_imported_value_is_refused),
    ("a cross-module specialization is refused by name",
     test_a_cross_module_specialization_is_refused),
    ("a cross-module specialization of a PUBLISHED name says brackets",
     test_a_cross_module_specialization_of_a_published_name_says_brackets),
    ("both architectures refuse it identically",
     test_both_architectures_refuse_the_same_construct_the_same_way),
    ("a local specialization lowers and matches CPython",
     test_a_local_specialization_runs_and_matches_cpython),
    ("an external_call template is not refused as a specialization",
     test_an_external_call_template_is_not_refused_as_a_specialization),
("a function read as a value is refused by name",
     test_a_function_read_as_a_value_is_refused_by_name),
    ("a local shadowing a function is still the local",
     test_a_local_shadowing_a_function_is_still_read_as_the_local),
    ("a call through a parameter is refused, as a construct, on both",
     test_a_call_through_a_parameter_is_refused_on_both_architectures),
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
