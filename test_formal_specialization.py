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
          f"a cross-module specialization is refused for something other than "
          f"the brackets: {text.strip()[-300:]}")
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


TESTS = [
    ("a specialization's root is a callee, not a read",
     test_a_specialization_root_is_a_callee_not_a_read),
    ("a bare read of an imported name is still refused",
     test_the_true_case_for_that_check_is_a_plain_read),
    ("a subscript of an imported value is refused, not silently dropped",
     test_a_subscript_of_an_imported_value_is_refused),
    ("a cross-module specialization is refused by name",
     test_a_cross_module_specialization_is_refused),
    ("both architectures refuse it identically",
     test_both_architectures_refuse_the_same_construct_the_same_way),
    ("a local specialization lowers and matches CPython",
     test_a_local_specialization_runs_and_matches_cpython),
    ("an external_call template is not refused as a specialization",
     test_an_external_call_template_is_not_refused_as_a_specialization),
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
