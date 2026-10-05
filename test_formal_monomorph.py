#!/usr/bin/env python3
"""`formal/monomorph.py` — a generic's INSTANTIATIONS are its boundary symbols.

`doc/ABI.md` §Generics says a generic is not one symbol and each instantiation
is, and this file pins what that means on the formal dylib path: a module that
declares only `struct Pair[T]` now publishes `prefix_Pair_Int` and its methods,
and a program that writes `Pair[Int]()` binds them. Before this the module had no
boundary symbol at all and the whole thing was one refusal — the second wall
behind the 165-file row in `bugs/FORMAL_sweep_work_map_2026-10-03_b8.md` §4.1,
which sits behind the codegen wall in `std/collections/binary_heap.mojo` and so
was invisible until that file's own constructs lower.

The case shape here is `BinaryHeap[Int]` in miniature: a library that declares
nothing but the template, and a program that applies it. Every behavioural case
is a CPython DIFFERENTIAL on both architectures — a constant would be an
assertion about a lowering made by the same person who wrote the lowering, and
the whole class of bug this feature can have (two instantiations, one trie
entry, a call that silently binds the wrong body) prints a plausible number
rather than refusing.

WHY THIS FILE AND NOT A GROUP IN `test_formal_run.py`. That file's
`run_cpython_pair_case` writes ONE source and builds it; every case here needs a
LIBRARY and a PROGRAM, because the thing under test is what crosses a dylib
boundary. Generalising the helper to take a dict of files would have meant
editing a 10,000-line file several other formal branches are also editing, for a
runner this file needs about thirty lines of.

The unit cases are the other half and are not differential on purpose: they pin
the DECISIONS (which names are templates, what a concrete type argument is,
which call sites get rewritten) and those are properties of the source, not of
an image.

THE HARNESS is `test_formal_dylib.py`'s `run_fire`/`check` and
`test_formal_imports.py`'s `write_tree`/`fresh_cas`, imported rather than copied.
The second import is also how this file gets a CAS of its OWN: that module's
body is what sets `GMOJO_HOME` to a fresh `mkdtemp` and exposes
`CAS_IMPORTS_ROOT`, and `fresh_cas()` empties that root — which every case here
needs, because a module dylib is content-addressed and a stale one from an
earlier build would mask the regression (and would hide the two-demand-sets
case, which is precisely about two libraries with one source). Importing it also
means its `__main__`-only cleanup never runs, so `_drop_cas_home` is called
here too — see `main`.

Invoked directly:
    python3 test_formal_monomorph.py [-v]
"""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from test_formal_dylib import TestFailure, check, run_fire   # noqa: E402
import test_formal_imports as FI                               # noqa: E402
from test_formal_imports import _Skip, fresh_cas, write_tree  # noqa: E402

FIRE = os.path.join(HERE, "fire.py")
ARCHES = ("arm64", "x86_64")
BUILD_TIMEOUT = 600
RUN_TIMEOUT = 120


# ── the library, and the program that applies it ───────────────────────────
#
# `Pair` is `BinaryHeap`'s shape reduced to what this backend can represent: two
# `T` fields (so the struct is FRAMED and its receiver is a frame address, the
# by-reference path `formal/model.py::wide_receiver_by_reference` describes) and
# a read method. Nothing here is a placeholder for something better: every case
# below that needs a different shape writes its own library, because a template
# is not interesting unless its body has something in it.

PAIR_LIB = """\
struct Pair[T]:
    var first: T
    var second: T

    def get_first(self) -> T:
        return self.first

    def swap(self):
        var held = self.first
        self.first = self.second
        self.second = held
"""

# The CPython twin. A Mojo generic struct instantiates to a class with concrete
# attributes, so this is the same program with the type argument bound — not a
# simulation of the lowering, just the same computation written the way Python
# would have to write it.
PAIR_CPYTHON = """\
class Pair:
    def __init__(self):
        self.first = 0
        self.second = 0

    def get_first(self):
        return self.first

    def swap(self):
        held = self.first
        self.first = self.second
        self.second = held
"""

PAIR_PROG = """\
from pairlib import Pair

def main():
    var a = Pair[Int]()
    var b = Pair[Bool]()
    a.first = 7
    a.second = 3
    b.first = True
    print(a.get_first())
    print(b.get_first())
    a.swap()
    print(a.get_first())
"""

# The reference spells `int()` where the Mojo side does not: a formal Bool is
# ONE WORD and prints as 1, where Python's `True` is its own object. That is a
# fact about the value model this backend has (`formal/model.py`'s one-word
# value), not about monomorphization, and the two programs are the same
# computation — so the difference is spelled in the reference rather than
# asserted away, because a case that quietly accepted `True` and `1` as equal
# would stop being a differential for every other line.
PAIR_CPYTHON_MAIN = """\
def main():
    a = Pair()
    b = Pair()
    a.first = 7
    a.second = 3
    b.first = True
    print(a.get_first())
    print(int(b.get_first()))
    a.swap()
    print(a.get_first())
"""


def build_pair_case(tmpdir, arch, name="mm_pair", lib=PAIR_LIB,
                    prog=PAIR_PROG, extra=None, libname="pairlib.mojo"):
    """Write the library and the program, build for `arch`, return the paths.

    Both files go in ONE directory because that is the smallest thing that is a
    real import: `from pairlib import Pair` resolves to a sibling source, which
    `formal/imports.py::resolve_module_path` handles by search root rather than
    by anything a test had to arrange. `extra` adds more files to the same tree,
    for the cases that need a package beside the library. `lib=None` writes no
    library at all, which is the ONE-FILE shape — the case where this module is
    both the library and the consumer, and where nothing has to cross a boundary
    for the instantiation to be needed.
    """
    root = os.path.join(tmpdir, f"{name}_{arch}")
    os.makedirs(root)
    files = {"main.mojo": prog} if lib is None else {
        libname: lib, "main.mojo": prog}
    files.update(extra or {})
    write_tree(root, files)
    out = os.path.join(root, f"main.{arch}.aout")
    argv = ["build", "--formal", "--no-prove", f"--backend={arch}",
            "-o", out, os.path.join(root, "main.mojo")]
    try:
        result = run_fire(argv, cwd=root)
    except subprocess.TimeoutExpired:
        raise TestFailure(
            f"[{arch}] {prog!r} did not finish within {BUILD_TIMEOUT}s") from None
    return root, out, result


def run_pair_case(tmpdir, arch, name, lib, prog, cpython, expect_ok=True,
                  extra=None, libname="pairlib.mojo"):
    """Build on `arch`, run it, and require CPython's answer.

    The CPython reference is RUN here, at test time, from the same text — a
    hand-written expected string is a constant asserted by the same person who
    wrote the lowering, which is the failure mode
    `test_formal_run.py::run_cpython_pair_case` was written to remove.

    `expect_ok=False` returns the build text instead, for the cases whose
    subject is a REFUSAL.
    """
    root, out, result = build_pair_case(tmpdir, arch, name, lib, prog,
                                        extra, libname)
    text = (result.stderr or "") + (result.stdout or "")
    if not expect_ok:
        return text
    check(result.returncode == 0,
          f"[{arch}] did not build: {text.strip()[-400:]}")
    py = os.path.join(root, "main.py")
    with open(py, "w") as f:
        f.write(cpython + "\nmain()\n")
    ref = subprocess.run([sys.executable, py], capture_output=True, text=True,
                         timeout=RUN_TIMEOUT)
    check(ref.returncode == 0,
          f"the CPython reference itself failed (exit {ref.returncode}): "
          f"{ref.stderr.strip()[-300:]}")
    run = subprocess.run([out], capture_output=True, text=True,
                         timeout=RUN_TIMEOUT)
    check(run.stdout == ref.stdout,
          f"[{arch}] printed {run.stdout!r}, CPython printed {ref.stdout!r}")
    check(run.returncode == 0,
          f"[{arch}] computed the right answer and exited {run.returncode}")
    return run.stdout


# ── behavioural: the boundary symbols ───────────────────────────────────────


def test_a_generic_struct_template_is_instantiated_at_the_importers_type(
        tmpdir):
    """`struct Pair[T]` alone is a library; `Pair[Int]()` is a program.

    The headline case, and the shape `std/collections/binary_heap.mojo` +
    `BinaryHeap[Int]` have at full size. Before this the build failed with

        pairlib.mojo: formal dylib has no public functions: pairlib.mojo exports
        nothing under doc/ABI.md's rules: it declares only the generic struct
        template(s) Pair, and a parametric type has no single boundary layout
        either.

    — `formal/build.py::no_public_api_reason`, which was RIGHT about the file and
    was also the whole of `bugs/FORMAL_known_limits.md` §1.2's "Stage 5
    monomorphization on the formal path … this is weeks, not an afternoon".

    Two type arguments in one program, because the failure this feature has to
    not have is two instantiations collapsing onto one symbol: `Pair[Int]` and
    `Pair[Bool]` are two concrete structs with two sets of methods, and a
    program that prints 7, 1, 3 has bound both of them.
    """
    for arch in ARCHES:
        fresh_cas()
        got = run_pair_case(tmpdir, arch, "mm_pair", PAIR_LIB, PAIR_PROG,
                            PAIR_CPYTHON + "\n" + PAIR_CPYTHON_MAIN)
        check(got == "7\n1\n3\n",
              f"[{arch}] printed {got!r}, which is neither CPython's answer nor "
              f"anything this case wrote down")


def test_a_generic_function_template_is_instantiated_too(tmpdir):
    """A `def f[T]` in another module is a boundary symbol the same way.

    Not a second feature: `doc/ABI.md` §Generics says "each instantiation is",
    and the difference between the struct and the function case is only that a
    function needs no layout, so a library whose whole API is
    `def twice[T](x: T) -> T` — `std/stat/stat.mojo`'s seven `S_ISxxx` — is a
    module that was refused for the same reason `binary_heap.mojo` was.
    """
    lib = ("def twice[T](x: T) -> T:\n"
           "    return x + x\n")
    prog = ("from fnlib import twice\n"
            "\n"
            "def main():\n"
            "    print(twice[Int](21))\n")
    cpython = ("def twice(x):\n"
               "    return x + x\n"
               "\n"
               "def main():\n"
               "    print(twice(21))\n")
    for arch in ARCHES:
        fresh_cas()
        got = run_pair_case(tmpdir, arch, "mm_fn", lib, prog, cpython,
                            libname="fnlib.mojo")
        check(got == "42\n", f"[{arch}] printed {got!r}, expected 42")


def test_a_struct_template_the_module_declares_can_itself_apply(tmpdir):
    """`struct Box[T]` and `Box[Int]()` in ONE file — the shape that was
    refused by name, on both architectures, for every struct template.

    `formal/monomorph.py::demands` deliberately SKIPS a consumer's own
    templates, and `formal/imports.py::instantiation_demands` passes
    `own_templates` for the same reason: a call to a generic this unit compiles
    is answered by the local-specialisation machinery
    (`_specialization_of` → `comptime.specialization_name`). That is TRUE of a
    FUNCTION template — `def twice[T]` beside `twice[Int](n)` builds today, and
    is its own case below — and FALSE of a STRUCT template, which is a call to a
    name the unit does not compile: `_callee_defs(functions)` is a table of
    functions, and the instantiation is emitted under a mangled name nothing had
    emitted. So the one demand set no caller could see was the module's own:

        build: Box[…](…) calls a name this unit does not compile, so the
        brackets cannot be bound …

    with a `return` the program never wrote. Two instantiations in one file,
    because the failure this change must not have is the two collapsing onto one
    symbol: `Box[Int]` and `Box[Bool]` are two concrete structs, and a program
    that prints 7 then 1 has bound both.
    """
    src = ("struct Box[T]:\n"
           "    var v: T\n"
           "\n"
           "    def get(self) -> T:\n"
           "        return self.v\n"
           "\n"
           "def main():\n"
           "    var a = Box[Int]()\n"
           "    var b = Box[Bool]()\n"
           "    a.v = 7\n"
           "    b.v = True\n"
           "    print(a.get())\n"
           "    print(b.get())\n")
    cpython = ("class Box:\n"
               "    def __init__(self):\n"
               "        self.v = 0\n"
               "\n"
               "    def get(self):\n"
               "        return self.v\n"
               "\n"
               "def main():\n"
               "    a = Box()\n"
               "    b = Box()\n"
               "    a.v = 7\n"
               "    b.v = True\n"
               "    print(a.get())\n"
               "    print(int(b.get()))\n")
    for arch in ARCHES:
        fresh_cas()
        got = run_pair_case(tmpdir, arch, "mm_own", None, src, cpython)
        check(got == "7\n1\n",
              f"[{arch}] printed {got!r}, which is neither CPython's answer nor "
              f"anything this case wrote down")


def test_a_module_that_applies_its_own_template_publishes_it(tmpdir):
    """§9a: the OWN demand set is a library's too, not only an executable's.

    The case above is the one-file shape — this module is both the library and
    the consumer, and `compile_formal`'s own `stmts` are the ones `_own_
    instantiations` rewrites. The LIBRARY path never had it: `build_module_
    dylib` compiled the module's own source and whatever an IMPORTER asked for,
    and `compile_formal_dylib` re-parses each source itself, so neither
    `instantiation_demands` (which is asked with `own_templates=`, which empties
    the own set on purpose) nor the rewrite was on it. The refusal was a
    question about an importer asked of a file with no importer in it:

        build: main.mojo imports 'pairlib', which cannot be built either:
        pairlib.mojo: `Pair[…](…) calls a name this unit does not compile, so
        the brackets cannot be bound … so a call arriving here asked for none

    Three halves, and each is a different function, which is why it took all
    three:

      * `monomorph.own_demands` is the own demand set as a NAME, so the artifact
        identity (`demands_key`) and the rewrite read one table;
      * `compile_formal_dylib` takes the statements to compile, because the
        rewrite is on the AST and a generated copy of the module would have to
        reproduce its prefix and its line numbers;
      * a library's own sources are now a MERGED struct table for every source's
        preparation, because the instantiated declaration arrives as a SECOND
        source file of the library and a frame-holder analysis that cannot see a
        sibling's struct refuses the field store (`test_formal_dylib.py`'s
        sibling-source case, which is that half on its own).

    **Two instantiations in one library**, because the failure this must not
    have is the two collapsing onto one symbol: `Pair[Int]` and `Pair[Bool]` are
    two concrete structs with two sets of methods, and a library that publishes
    7 and 1 has bound both. **And the library's own exports carry the
    instantiation**, which is what makes this a boundary case rather than an
    inlining one: `pairlib_Pair_1_T_3_Int_get_first` has to be in the manifest
    for the program to have anything to bind.
    """
    lib = ("struct Pair[T]:\n"
           "    var first: T\n"
           "\n"
           "    def get_first(self) -> T:\n"
           "        return self.first\n"
           "\n"
           "def int_pair() -> Int:\n"
           "    var a = Pair[Int]()\n"
           "    a.first = 7\n"
           "    return a.get_first()\n"
           "\n"
           "def bool_pair() -> Int:\n"
           "    var b = Pair[Bool]()\n"
           "    b.first = True\n"
           "    return b.get_first()\n")
    prog = ("from pairlib import int_pair, bool_pair\n"
            "\n"
            "def main():\n"
            "    print(int_pair())\n"
            "    print(bool_pair())\n")
    cpython = ("class Pair:\n"
               "    def __init__(self):\n"
               "        self.first = 0\n"
               "\n"
               "    def get_first(self):\n"
               "        return self.first\n"
               "\n"
               "def int_pair():\n"
               "    a = Pair()\n"
               "    a.first = 7\n"
               "    return a.get_first()\n"
               "\n"
               "def bool_pair():\n"
               "    b = Pair()\n"
               "    b.first = True\n"
               "    # A formal Bool is ONE WORD and prints as 1, where Python's is "
               "its\n"
               "    # own object — the same spelling the file's headline case "
               "makes\n"
               "    # and for the same reason: a reference that quietly accepted "
               "`True`\n"
               "    # and `1` would stop being a differential for every other "
               "line.\n"
               "    return int(b.get_first())\n"
               "\n"
               "def main():\n"
               "    print(int_pair())\n"
               "    print(bool_pair())\n")
    for arch in ARCHES:
        fresh_cas()
        got = run_pair_case(tmpdir, arch, "mm_ownlib", lib, prog, cpython)
        check(got == "7\n1\n",
              f"[{arch}] printed {got!r}, which is neither CPython's answer nor "
              f"anything this case wrote down")
    # The instantiation is a BOUNDARY symbol, so the manifest has to carry it —
    # with the module's OWN prefix, because that is the library it was compiled
    # into. A program that answers 7 can in principle have inlined the body, so
    # the manifest is the half that says the mechanism ran.
    found = []
    for _base, _dirs, files in os.walk(FI.CAS_IMPORTS_ROOT):
        for name in files:
            if name.startswith("pairlib.") and name.endswith(".manifest.json"):
                with open(os.path.join(_base, name)) as f:
                    found += [e["symbol"] for e in json.load(f)["exports"]]
    check(any(s.startswith("pairlib_Pair_1_T_3_Int_get_first")
              for s in found),
          f"no `pairlib_Pair_1_T_3_Int_get_first` in any pairlib dylib "
          f"({found}) — the instantiation was computed but not published, which "
          f"is the `declares only the template(s)` refusal's other half")


def test_a_package_reexport_attributes_the_demand_to_the_defining_module(
        tmpdir):
    """`from pkg import Pair` must instantiate in `pairlib`, not in `pkg`.

    The case that caught a real defect, and it is here rather than in a comment
    because the defect was in `dylib_chain`: `_BUILT` gained the demands digest
    as a third key element, that function looked dependencies up by
    `(arch, path)`, the lookup found nothing, and `main → pkg → pairlib` linked
    `pkg` ALONE. The image bound `Pair_Int_get_first` and the build died with

        the image would bind 1 symbol(s) that nothing provides:
        Pair_Int_get_first

    — a complaint about the LINK LINE for a library that had been built and was
    simply not on it. 162 of the 165 files in
    `bugs/FORMAL_sweep_work_map_2026-10-03_b8.md` §3.1 reach
    `binary_heap.mojo` through `std/collections/__init__.mojo`'s re-export and
    not by naming it, so this is the shape the row actually has.

    The program imports through the package and says nothing about `pairlib`,
    which is what makes it a test of the ATTRIBUTION rather than of the
    instantiation.
    """
    for arch in ARCHES:
        fresh_cas()
        got = run_pair_case(
            tmpdir, arch, "mm_pkg",
            lib=PAIR_LIB,
            prog=("from pkg import Pair\n"
                  "\n"
                  "def main():\n"
                  "    var a = Pair[Int]()\n"
                  "    a.first = 11\n"
                  "    print(a.get_first())\n"),
            cpython=("class Pair:\n"
                     "    def __init__(self):\n"
                     "        self.first = 0\n"
                     "\n"
                     "    def get_first(self):\n"
                     "        return self.first\n"
                     "\n"
                     "def main():\n"
                     "    a = Pair()\n"
                     "    a.first = 11\n"
                     "    print(a.get_first())\n"),
            extra={"pkg/__init__.mojo": "from pairlib import Pair\n"},
            )
        check(got == "11\n", f"[{arch}] printed {got!r}, expected 11")
    # …and the attribution is the fact, not the program's success: `pkg` must
    # declare nothing, so the instantiated declaration can only have come from
    # the module that declares `Pair`.
    root = os.path.join(tmpdir, "mm_pkg_arm64")
    with open(os.path.join(root, "pkg", "__init__.mojo")) as f:
        check("struct" not in f.read(),
              "the package body grew a declaration, so this case would stop "
              "being a test of where the demand is attributed")


def test_an_instantiation_agrees_with_the_concrete_struct_of_the_same_shape(
        tmpdir):
    """The instantiated body computes what the CONCRETE one computes.

    A differential against CPython says the program is right; it does not say the
    instantiation is the same program as the definition it came from. So this
    runs the same computation twice — once through `Pair[T]` instantiated at
    `Int`, once through a `PairInt` written out by hand — and requires the two
    to agree. That is the invariant the whole mechanism rests on: `Pair_Int` has
    to be `Pair[T]` with `T` bound, not a near neighbour of it, and the two ways
    it could differ (a parameter not substituted, a field not substituted) both
    produce a program that runs.

    Deliberately NOT compared against CPython here, because the hand-written
    struct is the control: if both are wrong in the same way the case still
    passes, and the cases above are what rule that out.
    """
    generic = ("struct Pair[T]:\n"
               "    var first: T\n"
               "\n"
               "    def scaled(self) -> T:\n"
               "        return self.first * 3\n")
    concrete = ("struct PairInt:\n"
                "    var first: Int\n"
                "\n"
                "    def scaled(self) -> Int:\n"
                "        return self.first * 3\n")
    for arch in ARCHES:
        fresh_cas()
        got = run_pair_case(
            tmpdir, arch, "mm_agree",
            lib=generic,
            prog=("from pairlib import Pair\n"
                  "\n"
                  "def main():\n"
                  "    var a = Pair[Int]()\n"
                  "    a.first = 14\n"
                  "    print(a.scaled())\n"),
            cpython=("class Pair:\n"
                     "    def __init__(self):\n"
                     "        self.first = 0\n"
                     "\n"
                     "    def scaled(self):\n"
                     "        return self.first * 3\n"
                     "\n"
                     "def main():\n"
                     "    a = Pair()\n"
                     "    a.first = 14\n"
                     "    print(a.scaled())\n"))
        root, _out, _r = build_pair_case(
            tmpdir, arch, "mm_agree_concrete", concrete,
            ("from pairlib import PairInt\n"
             "\n"
             "def main():\n"
             "    var a = PairInt()\n"
             "    a.first = 14\n"
             "    print(a.scaled())\n"))
        run = subprocess.run([os.path.join(root, f"main.{arch}.aout")],
                             capture_output=True, text=True,
                             timeout=RUN_TIMEOUT)
        check(run.stdout == got,
              f"[{arch}] the instantiation printed {got!r} and the hand-written "
              f"struct printed {run.stdout!r} — `Pair_Int` is not `Pair[T]` "
              f"with T bound")


# ── behavioural: what must stay refused ─────────────────────────────────────


def test_a_bare_call_to_an_imported_generic_is_still_refused(tmpdir):
    """`widen(5)` names no instantiation, so no boundary symbol can mean it.

    The control for every case above, and the half of the old limit that no
    amount of monomorphization can answer. A bracket says WHICH specialization;
    a bare call says none, and one trie entry cannot be two instantiations —
    which is the reason `doc/ABI.md` §Generics exists and the reason
    `no_public_api_reason` was right to refuse the template under its base name
    rather than conservative to export it.

    `test_formal_imports.py`'s `an imported generic is refused as an export gap`
    owns the BARE case and its message; this one asserts the property that
    changed — that the two spellings of the same call, in the same file with the
    same import, no longer get the same verdict.

    The library declares a CONCRETE function as well as the template, and that
    is load-bearing: it is what lets the module through the export gate at all,
    so the refusal under test is the IMPORTER's (`imported_callee_refusal`, which
    names the call) rather than the module's own (`no_public_api_reason`, which
    names the library). With a template and nothing else there is no demand at
    all, so nothing is instantiated and the module is refused for having no
    boundary symbol — which is true of it, and is
    `bugs/FORMAL_known_limits.md` §1.2's original refusal doing exactly its job.
    """
    lib = ("def widen[T: Intable](v: T) -> T:\n"
           "    return v\n"
           "\n"
           "def helper(x: Int) -> Int:\n"
           "    return x\n")
    for arch in ARCHES:
        fresh_cas()
        bare = run_pair_case(
            tmpdir, arch, "mm_bare", lib,
            ("from pairlib import widen\n"
             "\n"
             "def main():\n"
             "    print(widen(5))\n"),
            "", expect_ok=False)
        check("does not export it" in bare,
              f"[{arch}] a bare call to an imported generic must be refused as "
              f"an export gap: {bare.strip()[-400:]}")
        # …and the refusal must not tell this file its SOURCE is wrong. It used
        # to end "spell it as `widen[<a type>](…)` and the library will carry
        # the instantiation", which is a repair for correct code: in Mojo a
        # template call's type arguments are INFERRED, `widen(5)` is the spelling
        # the stdlib uses (`FormatStruct(writer, "Allocation")` is 68 files of
        # it), and the gap is in this path's demand pipeline. That is the
        # `refuse_without:` defect — a next step that is wrong about the code
        # being compiled — so the sentence now says which side the fault is on,
        # names the inference and its measurement, and calls the bracket a
        # WORKAROUND. The property is pinned here rather than in the message's
        # own test because it is a property of the REFUSAL a program gets.
        check("the SOURCE is right" in bare
              and "does not infer them yet" in bare,
              f"[{arch}] the refusal does not say the bare spelling is correct "
              f"source and that the inference is what is missing: "
              f"{bare.strip()[-600:]}")
        check("workaround" in bare,
              f"[{arch}] the bracket is offered without saying it is a "
              f"workaround for this path rather than a correction: "
              f"{bare.strip()[-400:]}")
        check("FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_"
              "inferrable.md" in bare,
              f"[{arch}] the refusal does not point at the measurement of the "
              f"inference it is short of")
        check("spell it as `widen[" not in bare,
              f"[{arch}] the old imperative is back: a reader sent to edit "
              f"correct stdlib")
        bracketed = run_pair_case(
            tmpdir, arch, "mm_brack", lib,
            ("from pairlib import widen\n"
             "\n"
             "def main():\n"
             "    print(widen[Int](5))\n"),
            ("def widen(v):\n"
             "    return v\n"
             "\n"
             "def main():\n"
             "    print(widen(5))\n"))
        check(bracketed == "5\n",
              f"[{arch}] the bracketed spelling printed {bracketed!r}")


def test_a_non_concrete_type_argument_is_still_refused(tmpdir):
    """`Pair[t]()` has no instantiation to name, so it is not one.

    The safety property of the mangling, and the reason
    `formal/monomorph.py::type_arg_text` returns `""` for a computed argument
    rather than inventing a spelling: the mangled name IS the ABI, so a computed
    argument given a made-up name would publish a symbol and an importer would
    bind it — and every such call would get whichever instantiation happened to
    be built first, with no diagnostic. That is the failure
    `no_public_api_reason`'s docstring calls "a build-error traded for a
    run-time wrong answer, which is the one trade this whole mechanism exists to
    refuse".

    Asserted as a REFUSAL rather than as silence, and specifically as a
    refusal that does not reach the LINK AUDIT — a dropped demand leaves the
    brackets in place, and what answers them is
    `formal/model.py::specialization_call_refusal`, which names the construct.
    The library is `Pair2` rather than `Pair` because the two-field version is
    the one that produced a WRONG ANSWER when this was only a spelling test (see
    `formal/monomorph.py::type_arg_text`), and a case that only proves the build
    stops would not have caught it.
    """
    lib = ("struct Pair2[T]:\n"
           "    var first: T\n"
           "    var second: T\n"
           "\n"
           "    def scaled(self) -> T:\n"
           "        return self.first + self.second\n")
    for arch in ARCHES:
        fresh_cas()
        _root, _out, result = build_pair_case(
            tmpdir, arch, "mm_dynarg", lib,
            ("from pairlib import Pair2\n"
             "\n"
             "def main():\n"
             "    var t = Float64\n"
             "    var a = Pair2[t]()\n"
             "    a.first = 1.5\n"
             "    a.second = 2.5\n"
             "    print(a.scaled())\n"))
        text = (result.stderr or "") + (result.stdout or "")
        check(result.returncode != 0,
              f"[{arch}] `Pair2[t]()` with `var t = Float64` BUILT and printed "
              f"a number. A type argument the defining module cannot resolve is "
              f"not a type: the library instantiated `Pair2_t` with `T` "
              f"substituted by `t`, an identifier it does not declare, and "
              f"`first + second` compiled as integer addition — so it prints 3 "
              f"where CPython prints 4.0. A build error traded for a run-time "
              f"wrong answer is the one trade this mechanism exists to refuse "
              f"(`formal/build.py::no_public_api_reason` says so)")
        check("binds 1 symbol(s) that nothing provides" not in text,
              f"[{arch}] reached the LINK AUDIT, which names the link line "
              f"rather than the bracket that has no instantiation: "
              f"{text.strip()[-400:]}")


# ── the decisions, pinned without an image ──────────────────────────────────


def test_only_the_export_rule_says_what_is_a_template(tmpdir):
    """The template set comes from `reflect.export_exclusions`, not from here.

    `collect_exports_src` filters the export table through
    `export_exclusions`, so if this module asked "is `Pair` a template" its own
    way, the set it instantiates and the set the export rule excluded could
    drift — and the drift is invisible until a program binds a symbol that was
    never exported under any spelling. So the answer must be the rule's, and
    this asserts it IS the rule's by checking a module the rule files a
    particular way.
    """
    from formal import monomorph as MM
    lib = ("struct Pair[T]:\n"
           "    var first: T\n"
           "\n"
           "def widen[T](v: T) -> T:\n"
           "    return v\n"
           "\n"
           "def plain(v: Int) -> Int:\n"
           "    return v\n"
           "\n"
           "def _private[T](v: T) -> T:\n"
           "    return v\n")
    names = MM.template_names(lib)
    check("Pair" in names and "widen" in names,
          f"a struct template and a function template are both templates, and "
          f"neither was found: {names}")
    check("plain" not in names,
          f"a concrete function was filed as a template: {names}")
    check("_private" not in names,
          f"the export rule files a private name under EXCL_PRIVATE first, so "
          f"it is not a template as far as this module is concerned — a "
          f"private template is not instantiable across a boundary anyway: "
          f"{names}")


def test_a_source_derived_answer_is_made_once_per_source_and_never_shared(tmpdir):
    """One derivation per source TEXT, and each caller gets its own container.

    Both `template_names` and `all_instantiation_calls` are functions of a
    source string and nothing else, and both are asked once per module of an
    import CLOSURE rather than once per source — measured on `std/simd.mojo`,
    where the export rule ran 7 042 times over 160 modules and
    `fire_compiler.py_tokenize` 7 335 times in total, 51% of an 84 s build.

    So this pins three things, and the first is a COUNT rather than a timing
    (a build that got slow again would be noticed by nobody, and one that got
    fast by answering a different question would pass every refusal test in the
    tree):

      * the derivation behind each runs ONCE per distinct source — so a future
        caller that reintroduces a per-module ask fails here;
      * interleaving two sources keeps the two answers apart, which is what a
        key that is not the source would get wrong;
      * the value handed back is a FRESH container every call, so a caller that
        mutates what it got cannot reach into the next caller's answer.
    """
    from formal import monomorph as MM
    import reflect

    lib = ("struct Pair[T]:\n"
           "    var first: T\n"
           "\n"
           "def widen[T](v: T) -> T:\n"
           "    return v\n")
    other = ("struct Box[T]:\n"
             "    var value: T\n")

    # 1 + the count the caller itself causes, per distinct source.
    seen = {"n": 0}
    real_exclusions = reflect.export_exclusions

    def counted(src, parsed=None):
        seen["n"] += 1
        return real_exclusions(src, parsed)

    reflect.export_exclusions = counted
    try:
        names = [MM.template_names(lib) for _ in range(4)]
        other_names = [MM.template_names(other) for _ in range(3)]
        again = MM.template_names(lib)
    finally:
        reflect.export_exclusions = real_exclusions
    check(seen["n"] == 2,
          f"the export rule ran {seen['n']} times for two sources asked seven "
          f"times between them; it is a whole-module tokenize+parse per call "
          f"and it is what made `std/simd.mojo` cost 84 s")
    check(all(n == names[0] for n in names) and again == names[0],
          f"the same source gave different answers across calls: "
          f"{names + [again]}")
    check(all(n == other_names[0] for n in other_names),
          f"the second source's own answers disagree: {other_names}")
    check(set(names[0]) == {"Pair", "widen"},
          f"the cached answer is not the export rule's: {names[0]}")
    check(set(other_names[0]) == {"Box"},
          f"a cached answer was served for the WRONG source, which is the "
          f"failure a key that is not the source produces: {other_names[0]}")

    # The container is the caller's, not the cache's.
    names[0].append("Injected")
    check(MM.template_names(lib) == ["Pair", "widen"],
          f"a caller mutating the list it got back reached into the cached "
          f"answer: {MM.template_names(lib)}")

    parsed = {"n": 0}
    real_statements = MM._consumer_statements

    def counted_statements(src):
        parsed["n"] += 1
        return real_statements(src)

    prog = ("def main():\n"
            "    var a = Pair[Int]()\n"
            "    var b = Pair[Float64]()\n")
    other_prog = ("def main():\n"
                  "    var c = Box[Bool]()\n")
    MM._consumer_statements = counted_statements
    try:
        found = [MM.all_instantiation_calls(prog) for _ in range(5)]
        other_found = [MM.all_instantiation_calls(other_prog) for _ in range(3)]
    finally:
        MM._consumer_statements = real_statements
    check(parsed["n"] == 2,
          f"the consumer source was parsed {parsed['n']} times for eight asks "
          f"over two sources; `formal/imports.py::instantiation_demands` asks "
          f"once per imported module over one unchanged consumer")
    check(all(f == found[0] for f in found) and \
        all(f == other_found[0] for f in other_found),
          f"the same source gave different demand sets across calls: "
          f"{found + other_found}")
    check(found[0] == {"Pair": [("Float64",), ("Int",)]},
          f"the cached demand set is not the derived one: {found[0]}")
    check(other_found[0] == {"Box": [("Bool",)]},
          f"a cached demand set was served for the WRONG consumer: "
          f"{other_found[0]}")
    found[0]["Pair"].append(("Injected",))
    found[0]["Injected"] = [("Bool",)]
    check(MM.all_instantiation_calls(prog) == {"Pair": [("Float64",), ("Int",)]},
          f"a caller mutating the demand set it got back reached into the "
          f"cached one: {MM.all_instantiation_calls(prog)}")

    # 3. BOTH questions, ONE source — which is what
    # `formal/imports.py::build_module_dylib` asks, since it hands the same
    # `module_source_text(source_path)` to `template_names` (as
    # `own_templates`) and to `instantiation_demands` (as `consumer_src`). One
    # cache keyed on the source alone served one question's answer out of the
    # other's slot, and the build died with `'tuple' object has no attribute
    # 'items'` on 4 of the 43 files of the byte-comparison spread.
    both = ("struct Pair[T]:\n"
            "    var first: T\n"
            "\n"
            "def main():\n"
            "    var a = Pair[Int]()\n")
    check(MM.template_names(both) == ["Pair"],
          f"the template set of a source that also has demands: "
          f"{MM.template_names(both)}")
    check(MM.all_instantiation_calls(both) == {"Pair": [("Int",)]},
          f"the demand set of a source whose template set was just read: "
          f"{MM.all_instantiation_calls(both)}")
    check(MM.template_names(both) == ["Pair"],
          f"and the template set again, after the demand set read its slot: "
          f"{MM.template_names(both)}")


def test_a_template_is_located_once_per_source_and_name(tmpdir):
    """`template_kind`/`_template_source` are whole-module SCANS, so they are
    asked once per `(source, name)` and not once per instantiation.

    `elaborate.extract_struct_source` and `extract_fn_source` each split the
    module into lines and run `elaborate._bracket_depth_by_line` over it, and
    `instantiate` asks both of this module's questions once per (template,
    argument-list) pair: 300 asks over FOUR distinct pairs on `std/simd.mojo`,
    which is 600 bracket-depth scans of whole modules and 39% of what was left
    of that build.

    Counted rather than timed, and the count is the point: a caller that
    reintroduces a per-instantiation ask fails here, and one that made the
    lookup answer a different question would still be caught by the equality
    assertions rather than by a clock.
    """
    from formal import monomorph as MM
    import elaborate

    lib = ("struct Pair[T]:\n"
           "    var first: T\n"
           "    var second: T\n"
           "\n"
           "    def scaled(self) -> T:\n"
           "        return self.first + self.second\n"
           "\n"
           "def widen[T](v: T) -> T:\n"
           "    return v\n")
    scans = {"n": 0}
    real_depth = elaborate._bracket_depth_by_line

    def counted(src):
        scans["n"] += 1
        return real_depth(src)

    elaborate._bracket_depth_by_line = counted
    try:
        kinds = [(MM.template_kind(lib, "Pair"), MM.template_kind(lib, "widen"))
                 for _ in range(6)]
        sources = [MM._template_source(lib, "Pair", MM.KIND_STRUCT)
                   for _ in range(6)]
        made = [MM.instantiate(lib, "Pair", (a,))[0]
                for a in ("Int", "Float64", "Bool")]
        again = MM.template_kind(lib, "Pair")
        miss = 0
        for _ in range(3):
            try:
                MM.template_kind(lib, "NoSuchTemplate")
            except MM.MonomorphError:
                miss += 1
    finally:
        elaborate._bracket_depth_by_line = real_depth
    check(all(k == (MM.KIND_STRUCT, MM.KIND_FN) for k in kinds),
          f"a struct template and a function template were not told apart: "
          f"{kinds}")
    check(again == MM.KIND_STRUCT,
          f"the same (source, name) gave a different kind across calls: "
          f"{again}")
    check(all(s == sources[0] and "scaled" in s for s in sources),
          f"the template's own text is not the extractor's: {sources[0]!r}")
    check([m.split("_")[-1] for m in made] == ["Int", "Float64", "Bool"] and
          all(m.startswith("Pair_") for m in made),
          f"three instantiations of one template did not mangle as the ABI "
          f"says: {made}")
    check(scans["n"] <= 16,
          f"{scans['n']} whole-module bracket-depth scans for 6 + 6 + 3 + 3 "
          f"asks over two templates in one source; each is a scan of the "
          f"whole module and there are two `(source, name)` pairs here")
    check(miss == 3,
          f"a name this module does not declare was refused {miss} times "
          f"rather than 3; a refusal answered from a cache would go stale "
          f"against a source that later declares the name")


def test_the_re_export_closure_is_walked_once_for_a_consumers_whole_dep_set(tmpdir):
    """`module_templates_by_path` walked the whole closure once per DEPENDENCY.

    `imported_instantiations` loops over a consumer's imports and asks
    `instantiation_demands` once per `dep`, and each ask walked that dep's whole
    re-export closure with a `visited` set private to the call. The per-module
    ANSWER was already memoised (`formal/monomorph.py`'s `_derived_from_source`),
    so what was left was the walk, and the walk was a product: measured on
    `std/math/math.mojo` (2026-10-04) at **16 walks, 1.56 s of a 4.6 s build, 34%**
    — the largest single residue in
    `bugs/PERF_formal_import_asks_are_products_of_the_closure.md`.

    Two halves, and the second is the one a count cannot see:

      * `template_closure(paths)` walks the whole SET once with one `visited`,
        and `instantiation_demands(..., closure=…)` takes a reachability slice
        instead of walking. Counted below by wrapping `template_closure` itself.
      * the slice must EQUAL the standalone walk — every key, and the ORDER. The
        order is not cosmetic: `imported_instantiations`'s
        `demap.setdefault((base, args), mangled)` keeps the FIRST owner's body
        for a name two owners declare, so a slice assembled in a different order
        instantiates a different module's body under the same symbol, builds,
        and answers differently. That is why `_closure_template_slice` is an
        explicit depth-first walk of the recorded edges rather than a filter over
        the table's insertion order, and why this case compares `list(items())`.
    """
    from formal import imports as FI
    import formal.build as FB
    import os

    pkg = os.path.join(tmpdir, "rexp")
    os.makedirs(pkg)
    # A package whose `__init__` re-exports a template from a sibling, plus a
    # second package, plus a bare `import` — the bare import is the shape that
    # is NOT in the closure of `__init__`, so it is what makes the slice have to
    # be reachability and not a prefix.
    with open(os.path.join(pkg, "leaf.mojo"), "w") as f:
        f.write("struct Pair[T]:\n"
                "    var a: T\n"
                "    var b: T\n"
                "def widen[T](v: T) -> T:\n"
                "    return v\n")
    with open(os.path.join(pkg, "__init__.mojo"), "w") as f:
        f.write("from .leaf import Pair\nfrom .leaf import widen\n")
    with open(os.path.join(pkg, "other.mojo"), "w") as f:
        f.write("def twice[T](v: T) -> T:\n    return v\n")
    with open(os.path.join(pkg, "consumer.mojo"), "w") as f:
        f.write("from . import Pair\n"
                "from . import widen\n"
                "from .other import twice\n"
                "def main():\n"
                "    var p = Pair[Int]()\n"
                "    print(widen[Int](1))\n"
                "    print(times[Int](2))\n")

    source_path = os.path.join(pkg, "consumer.mojo")
    consumer = FI.module_source_text(source_path)
    stmts = FB.parse_module(consumer, source_path)
    paths = []
    for mod in FI.imported_modules(stmts):
        dep = FI.resolve_module_path(mod, relative_to=source_path,
                                     project_root=source_path)
        if dep:
            paths.append(dep)
    check(len(paths) >= 2,
          f"the fixture resolved {paths} as imports of the consumer, expected "
          f"the package and `.other` — a consumer whose `from . import Pair` and "
          f"`from . import widen` both land on the package is the shape that "
          f"makes the dep set and the closure different sets")

    walks = {"n": 0}
    real_closure = FI.template_closure

    def counted(roots, project_root=None):
        walks["n"] += 1
        return real_closure(roots, project_root=project_root)

    # The SLICED loop is the production shape and is counted; the standalone
    # loop below it is this case's REFERENCE and is counted separately, so the
    # two numbers cannot be confused.
    FI.template_closure = counted
    try:
        closure = counted(paths, project_root=source_path)
        sliced = [list(FI.instantiation_demands(
            dep, consumer, project_root=source_path, closure=closure).items())
            for dep in paths]
        sliced_walks = walks["n"]
        walks["n"] = 0
        standalones = [list(FI.instantiation_demands(
            dep, consumer, project_root=source_path).items())
            for dep in paths]
        standalone_walks = walks["n"]
    finally:
        FI.template_closure = real_closure

    check(sliced_walks == 1,
          f"a consumer with {len(paths)} imports walked the re-export closure "
          f"{sliced_walks} times on the path that has the table; it is one "
          f"walk of the dep SET, and every slice is a reachability question "
          f"inside it")
    check(standalone_walks == len(paths),
          f"the reference loop walked {standalone_walks} times for "
          f"{len(paths)} deps; if this is not one walk per dep then the "
          f"comparison below is not the comparison it claims to be")
    check(any(sliced),
          f"no dep of the fixture asked for any template, so the slice is "
          f"compared against nothing: {sliced}")
    check(sliced == standalones,
          f"a slice of the shared closure differs from the standalone walk "
          f"(keys or ORDER — both are load-bearing): sliced={sliced} "
          f"standalone={standalones}")
    # And the slice is genuinely a SLICE, not the whole table: `.other` is in
    # the shared table because it is one of the ROOTS, and it is in NO other
    # root's slice because the package does not re-export it. That is the
    # property a "just hand everyone the whole table" shortcut would lose, and
    # it is a correctness property rather than a tidiness one:
    # `instantiation_demands` attributes a demand to the module that DECLARES
    # it, so a slice that over-reaches would demand an instantiation in a
    # module the consumer cannot reach.
    other = os.path.join(pkg, "other.mojo")
    leaf = os.path.join(pkg, "leaf.mojo")
    # The PACKAGE's module is its `__init__.mojo`, which is what `paths` carries
    # — slicing by the directory would be a root the walk never saw.
    pkg_module = os.path.join(pkg, "__init__.mojo")
    other_key, leaf_key = os.path.abspath(other), os.path.abspath(leaf)
    check(other_key in closure[0],
          f"`.other` declares the generic `twice` and is a root of the shared "
          f"walk, so it must be in the table: {sorted(closure[0])}")
    pkg_slice = FI._closure_template_slice(closure[0], closure[1], pkg_module)
    check(other_key not in pkg_slice,
          f"the package's slice names `.other`, which it does not re-export: "
          f"{sorted(pkg_slice)}")
    check(leaf_key in pkg_slice,
          f"the package's slice does not name `.leaf`, which it re-exports "
          f"from: {sorted(pkg_slice)}")
    check("twice" not in pkg_slice.get(pkg_module, []) and
          "Pair" in (pkg_slice.get(leaf_key) or []),
          f"the slice's own contents do not separate the two modules' "
          f"templates: {pkg_slice}")


def test_an_instantiation_substitutes_the_parameter_and_keeps_the_self_spelling(tmpdir):
    """`Self.T` is `T`, and the shared substitution would otherwise break it.

    `monomorphize_source` substitutes each parameter's spelling with a
    whole-word `re.sub`, and `\\bT\\b` matches the `T` in `Self.T` as happily as
    the bare one — so `var items: List[Self.T]` came out as `List[Self.Int]`, a
    spelling nothing declares. This is the shape `std/collections/binary_heap.mojo`
    writes (`var _data: List[Self.T]`, `List[Self.T]()` in its own `__init__`),
    which is the file the 165-file row is about.

    The fold lives in `formal/monomorph.py` rather than in the shared function
    because the compiled path never hands `monomorphize_source` a struct
    template as a unit, so teaching it about `Self` would be a change to a
    shared engine on the strength of a caller that does not exist there.
    """
    from formal import monomorph as MM
    src = ("struct Bag[T]:\n"
           "    var items: List[Self.T]\n"
           "\n"
           "    def fill(self):\n"
           "        self.items = List[Self.T]()\n")
    mangled, concrete = MM.instantiate(src, "Bag", ("Int",))
    # The mangled spelling comes from the ONE mangler rather than from a
    # literal, and that is the whole point of this assertion: `monomorphize.
    # mangle` deliberately encodes each field with its index, its name and a
    # digest (`Box[T]` → `Box_1_T_5_Int64`) because the old spelling was not
    # INJECTIVE — two instantiations could share a symbol — and a literal here
    # went stale the moment that landed, turning this case red on a mangling
    # scheme nobody had broken. Deriving it makes the case say what it is
    # about: that `instantiate` uses the shared mangler, not that a particular
    # string came out of it.
    import monomorphize
    check(mangled == monomorphize.mangle("Bag", {"T": "Int"}),
          f"the mangled name is {mangled!r}, which is not what the shared "
          f"mangler produces")
    check("Self." not in concrete,
          f"`Self.T` survived into the instantiation, which binds nothing: "
          f"{concrete!r}")
    check("List[Int]" in concrete,
          f"the field's type argument was not substituted: {concrete!r}")
    # …and the SAME derivation for the declaration's own name, which is the
    # other half of what this case is about (the substitution is only useful if
    # the declaration is renamed to the symbol the library will publish).
    check(f"struct {mangled}" in concrete and "struct Bag[" not in concrete,
          f"the declaration was not renamed and de-parameterised: "
          f"{concrete!r}")


def test_a_type_argument_that_is_computed_is_not_a_demand(tmpdir):
    """`Pair[t]`, `Pair[2]` and `Pair[Int, Int]` — three different answers.

    * **`Pair[t]`** with `var t = Int` in the same function is a NAME and a
      spelling, so a demand pipeline that only asked "is this an identifier"
      would instantiate `Pair_t` with `T` substituted by `t` — an identifier the
      library does not declare. Nothing downstream objects: a field's declared
      type is not read by `struct_is_framed` (which counts fields, not types), so
      the library compiles and the program computes. Measured, and it is the
      failure `no_public_api_reason`'s docstring says must not happen:

          var t = Float64 ; a = Pair2[t]() ; a.first = 1.5 ; a.second = 2.5
          print(a.scaled())          # CPython 4.0, this path 3

      So a bare identifier argument has to be a name the reading scope does not
      BIND as a value, which is `formal/build.py::_names_bound_in` for a
      function and `formal/model.py::collect_module_symbols` for the module
      level. Deliberately the negation and not `model.is_type_name`, whose own
      docstring says it must not answer "can this name be read" and whose four
      tables have no float in them: `Pair2[Float64]()` is correct Mojo and
      asking it would refuse it.
    * **`Pair[2]`**'s argument IS a spelling, but it is a VALUE: it is
      `tile[2, 3](…)`, a comptime specialization whose brackets both backends
      already answer through `mojo/middle/comptime.specialization_args`, and
      demanding `Pair_2` for it would publish a boundary symbol for a
      specialization of a value parameter.
    * **`Pair[Int, Int]`** IS a demand — of a two-parameter template — and
      `instantiate` refuses it because `Pair` declares one. A comma list is
      several arguments and not one spelling: joining the items into `Int_Int`
      would make the arity check complain about the count when the source got it
      exactly right.

    The arity refusal has to name the DECLARATION's count, because that is the
    half of the pair a reader can act on: they wrote two and the template
    declares one.
    """
    from formal import monomorph as MM
    prog = ("def main():\n"
            "    var t = Int\n"
            "    var a = Pair[t]()\n"
            "    var b = Pair[2]()\n"
            "    var c = Pair[Int, Int]()\n"
            "    var d = Pair[Float64]()\n"
            "    var e = Pair[Int]()\n")
    found = MM.all_instantiation_calls(prog)
    check(found.get("Pair") == [("Float64",), ("Int",), ("Int", "Int")],
          f"only `Pair[Int]`, `Pair[Float64]` and `Pair[Int, Int]` are demands "
          f"here — and `Float64` being one of them is the half that pins the "
          f"negation: `model.is_type_name` says no for it, so asking that "
          f"instead of the reading scope's bindings would refuse correct Mojo: "
          f"{found}")
    src = "struct Pair[T]:\n    var first: T\n"
    try:
        MM.instantiate(src, "Pair", ("Int", "Bool"))
    except MM.MonomorphError as e:
        check("declares 1" in str(e),
              f"the arity refusal has to name the declaration's own count: {e}")
    else:
        raise TestFailure(
            "a bracket with two type arguments instantiated a template that "
            "declares one, so `Pair_Int_Bool` would be a body built from a "
            "parameter the source never bound")


def test_a_value_typed_bracket_is_not_read_as_a_type(tmpdir):
    """`Pair[t]` in a comment, a docstring and an MLIR literal is not a call.

    The rewrite is on the AST precisely so this holds: the parser has already
    thrown those three away, so a textual rewrite would have had to re-implement
    the tokenizer's knowledge to leave them alone. And the value-position case
    is the one `formal/model.py::subscript_callee_names` exists to distinguish —
    `len(List)` reads `List`, it does not call it — so exempting by NAME rather
    than by position is a defect this case would catch.
    """
    from formal import monomorph as MM
    from formal.build import parse_module
    prog = ("# Pair[Int]() in a comment\n"
            '"""Pair[Int]() in a docstring."""\n'
            "def main():\n"
            "    var a = Pair[Int]()\n"
            "    var xs = [1, 2]\n"
            "    print(a.get_first(), xs[0])\n")
    stmts = parse_module(prog)
    n = MM.rewrite_instantiation_calls(stmts, {("Pair", ("Int",)): "Pair_Int"})
    check(n == 1,
          f"exactly one call site is a constructor — `xs[0]` is a subscript on "
          f"a VALUE and `Pair[Int]` in the comment and the docstring is not a "
          f"call at all — and {n} were rewritten")
    callee = stmts[1].body[0].value.func
    check(getattr(callee, "name", None) == "Pair_Int",
          f"the constructor call's callee is {callee!r}, not the mangled name")
    check(callee.line == 4,
          f"the replacement lost its position ({callee.line!r}); every "
          f"diagnostic downstream reports line and column, and a callee moved "
          f"to line 0 sends the reader to the top of the file")


def test_a_literal_display_is_a_bracket_argument_and_a_bare_literal_is_not(
        tmpdir):
    """The one value shape a bracket argument accepts is a LITERAL DISPLAY.

    `TypeDict[T=Int, Trait=AnyType, [1,2,3], Int, String, Float64]` is
    `std/collections/type_dict.mojo`'s own use site and every one of its
    parameters is a VALUE, so the bracket has to be able to name one — but
    naming a value is an ABI question, because the mangled name IS the boundary
    symbol and two instantiations differing only in a value argument must be two
    symbols or the second overwrites the first.

    Three things are pinned here, and the second is the one that is easy to get
    wrong in the direction of a wrong answer:

    * **`[1, 2, 3]`, `(4, 5)`, `[-3, 5]`, `[True, 5]` and a nested
      `[[1,2],[3,4]]` are demands**, and each mangles to its own symbol.  A
      display of literals has exactly one closed-form spelling, so the rendering
      is a FUNCTION of the value and `monomorphize.safe_suffix` (injective on
      text) makes the mangling injective with it.
    * **`Pair[2]` and `tile[2, 3]` are still NOT demands.**  A bare literal at
      the top level of a bracket is the comptime-specialization case, which both
      backends already answer through `mojo/middle/comptime.specialization_args`;
      demanding `tile_2_3` for it as well would publish a boundary symbol for a
      specialization the build already emits under its own name.  The asymmetry
      is the whole design and it is what this case exists to hold.
    * **A display with a computed element is refused WHOLE, not half.**  `keys[0]
      + base` inside a display has no closed form, and a partial display would
      substitute a body built from half the values the source wrote — the
      fabricated-answer outcome every other refusal in this module exists to
      avoid.  So is a display naming a name the reading scope binds as a value,
      which is the same negation `type_arg_text` applies to a type argument.
    """
    from formal import monomorph as MM
    prog = ("def main():\n"
            "    var a = Box[Int, [1, 2, 3]]()\n"
            "    var b = Box[Int, (4, 5)]()\n"
            "    var c = Box[Int, [-3, 5]]()\n"
            "    var d = Box[Int, [True, 5]]()\n"
            "    var e = Box[Int, [[1, 2], [3, 4]]]()\n"
            "    var f = Box[Int, [1, 2, 3 + base]]()\n"
            "    var g = Box[Int, [1, t]]()\n"
            "    var h = Pair[2]()\n"
            "    var i = tile[2, 3](7)\n"
            "    var t = Int\n")
    found = MM.all_instantiation_calls(prog)
    check(found.get("Box") == [("Int", "(4, 5)"), ("Int", "[-3, 5]"),
                               ("Int", "[1, 2, 3]"), ("Int", "[True, 5]"),
                               ("Int", "[[1, 2], [3, 4]]")],
          f"the five displays of literals are demands and the two that are not "
          f"displays, or hold a computed element, or name a value binding, are "
          f"not: {found}")
    check("Pair" not in found and "tile" not in found,
          f"a bare literal bracket is `tile[2, 3]`'s shape and belongs to the "
          f"local specialization machinery, not to a boundary symbol: "
          f"{found}")

    # The mangling is the ABI, so distinctness is asserted on the SYMBOLS rather
    # than on the display strings, and the pair that could collide is the one
    # the rendering could have flattened: a one-element tuple, a one-element
    # list and the bare element all hold the same value.
    src = ("def total[T: AnyType, keys: List[T]](base: Int) -> Int:\n"
           "    return base + keys[0]\n")
    mangled = {}
    for args in (("Int", "[1, 2, 3]"), ("Int", "[3, 2, 1]"),
                 ("Int", "(1, 2, 3)"), ("Int", "(1,)"), ("Int", "[1]")):
        mangled[args] = MM.instantiate(src, "total", args)[0]
    check(len(set(mangled.values())) == len(mangled),
          f"two instantiations differing only in a VALUE argument share one "
          f"symbol, so the second overwrites the first: {mangled}")

    # …and the spelling is the text that goes into the body, so a consumer that
    # reads the value has to get the value and not a mangled fragment.
    _name, concrete = MM.instantiate(src, "total", ("Int", "[1, 2, 3]"))
    check("base + [1, 2, 3][0]" in concrete,
          f"the display was not substituted into the body as written: "
          f"{concrete!r}")
    import fire_compiler as FC
    try:
        FC.Parser(FC.py_tokenize(concrete)).parse_module()
    except Exception as exc:                        # noqa: BLE001
        raise TestFailure(
            f"the instantiation does not parse, which is the whole defect: "
            f"{exc!r}\n{concrete!r}") from None


VALUE_BRACKET_LIB = """\
def total[T: AnyType, keys: List[T]](base: Int) -> Int:
    return base + keys[0]
"""

VALUE_BRACKET_PROG = """\
from vlib import total

def main():
    print(total[Int, [1, 2, 3]](10))
    print(total[Int, [7, 8, 9]](10))
    print(total[Int, (4, 5)](10))
"""

VALUE_BRACKET_CPYTHON = """\
def total(base, keys):
    return base + keys[0]
def main():
    print(total(10, [1, 2, 3]))
    print(total(10, [7, 8, 9]))
    print(total(10, (4, 5)))
"""


def test_a_value_bracket_argument_reaches_the_boundary_symbol(tmpdir):
    """`total[Int, [1, 2, 3]]` binds the library's symbol, and `keys[0]` is `1`.

    The end-to-end half, and the reason the numbers are the assertion: a
    mangling that collapsed two value arguments onto one symbol would build, run
    and print the FIRST program's answer twice — a plausible answer, which is
    the failure mode this whole file was written to catch.  `keys[0]` is what
    makes the value observable at all: it is the one read of a bracket value
    parameter that lowers today, because the parameter's own annotation
    (`keys: List[T]`) classifies the subscript base and the substitution puts a
    list literal there.  A read that goes through `len()` instead does not (see
    the bug doc deleted with the consumer-side fix, `§"What is not the cause"`
    and the wall it stopped at, now
    `bugs/FORMAL_a_value_bracket_parameter_cannot_be_read_in_the_template.md`),
    which is why this case reads element zero.

    Both spellings of a display and two different values of it, so the
    distinctness the mangling has to provide is exercised rather than asserted:
    `[1, 2, 3]` and `[7, 8, 9]` are two libraries whose symbols differ, and
    `(4, 5)` is a third spelling of a two-element display.
    """
    for arch in ARCHES:
        got = run_pair_case(tmpdir, arch, "mm_valuedisp", VALUE_BRACKET_LIB,
                            VALUE_BRACKET_PROG, VALUE_BRACKET_CPYTHON,
                            libname="vlib.mojo")
        check(got == "11\n17\n14\n",
              f"[{arch}] printed {got!r} for three instantiations whose first "
              f"elements are 1, 7 and 4 over a base of 10")


# ── the artifact's identity ─────────────────────────────────────────────────


def test_two_demand_sets_are_two_libraries(tmpdir):
    """`Pair[Int]` and `Pair[Bool]` are two libraries, not one shared library.

    A module dylib is content-addressed on its source, which used to be enough:
    one source produced one artifact. A generic template breaks that — the same
    source, built for two different demand sets, has two different sets of
    exported symbols and is two different libraries — and the identity has to
    say so in BOTH the in-process cache and the file name, for the reason `arch`
    is in both (a stale hit is a wrong-boundary-symbol library that still builds
    and links).

    Measured in one process, so the cache is the thing under test: the second
    build must not be served the first one's library.
    """
    from formal import monomorph as MM
    from formal import imports as I
    lib = ("struct Pair[T]:\n"
           "    var first: T\n"
           "\n"
           "    def get_first(self) -> T:\n"
           "        return self.first\n")
    check(MM.demands_key({}) == MM.demands_key(None) == "",
          "the empty demand set must digest to the empty string, so every "
          "module that declares no generic template keeps the dylib name it "
          "had before instantiations existed")
    check(MM.demands_key({"Pair": [("Int",)]})
          != MM.demands_key({"Pair": [("Bool",)]}),
          "two demand sets must not digest to the same key")
    check(MM.demands_key({"Pair": [("Int",)]})
          == MM.demands_key({"Pair": [("Int",)]}),
          "the same demand set must digest to the same key, or nothing is ever "
          "a cache hit")
    with tempfile.TemporaryDirectory() as root:
        path = os.path.join(root, "pairlib.mojo")
        with open(path, "w") as f:
            f.write(lib)
        out_dir = os.path.join(root, "libs")
        here = os.path.abspath(path)
        want_int = I.build_module_dylib("pairlib", path, out_dir, "arm64",
                                        project_root=root,
                                        demands={here: {"Pair": [("Int",)]}})
        want_bool = I.build_module_dylib("pairlib", path, out_dir, "arm64",
                                         project_root=root,
                                         demands={here: {"Pair": [("Bool",)]}})
        check(want_int != want_bool,
              f"two demand sets produced one path ({want_int!r}); a program "
              f"that binds `Pair_Bool_get_first` would be handed a library that "
              f"exports `Pair_Int_get_first` instead")
        # …and the expected symbol is spelled by the ONE mangler for the same
        # reason as the case above: `Pair_Int` was the pre-injective spelling and
        # went stale with it. The NEGATIVE half still keys on the plain base
        # names, because what it is testing is that the demand set decided the
        # artifact — and `Pair_Bool` is a substring of nothing an `Int` library
        # publishes, whether or not the mangler lengthens it.
        import monomorphize
        for path_built, want, other in (
                (want_int, monomorphize.mangle("Pair", {"T": "Int"}),
                 monomorphize.mangle("Pair", {"T": "Bool"})),
                (want_bool, monomorphize.mangle("Pair", {"T": "Bool"}),
                 monomorphize.mangle("Pair", {"T": "Int"}))):
            with open(I._manifest_path(path_built)) as f:
                exports = {e.get("symbol") for e in
                           (json.load(f).get("exports") or [])}
            check(any(want in (s or "") for s in exports),
                  f"{os.path.basename(path_built)} exports no {want} symbol: "
                  f"{sorted(exports)}")
            check(not any(other in (s or "") for s in exports),
                  f"{os.path.basename(path_built)} also exports {other}, so "
                  f"the demand set is not what decided the artifact: "
                  f"{sorted(exports)}")


def test_a_bracketed_parameter_annotation_instantiates(tmpdir):
    """`keys: List[T]` is a parameter, and every instantiation of it used to be
    a file that does not parse.

    The head matcher's character class was "not a bracket", so it stopped at
    `List[T]`'s `]`, `monomorphize_source` cut the head there and left `]:`
    behind:

        struct Box[T: AnyType, keys: List[T]]:      ->  struct Box_1_…_x005D]:
        parse error: Unexpected RBRACKET(']')

    which is the worst of the three failure directions — the instantiation is
    produced, substituted correctly, and cannot be compiled. It is not an exotic
    shape either: it is `std/collections/type_dict.mojo` (every one of whose
    parameters is a value) and `SIMD[…]` in any numeric template.

    **The assertion that was missing everywhere is that the emitted source
    PARSES** — the mangled name was already right, so a test that checked only
    the name passed against a definition no compiler would accept. Hence
    `Parser(py_tokenize(out)).parse_module()` here, and the substitution is
    checked as well because a head that ends in the right place still has to
    substitute INSIDE the annotation.
    """
    from formal import monomorph as MM
    import fire_compiler as F
    src = ("struct Box[T: AnyType, keys: List[T]]:\n"
           "    var items: List[T]\n"
           "\n"
           "    def size(self) -> Int:\n"
           "        return len(self.items)\n")
    mangled, concrete = MM.instantiate(src, "Box", ("Int", "[1, 2, 3]"))
    check(concrete.startswith(f"struct {mangled}:"),
          f"the definition was not renamed and its parameter list not dropped: "
          f"{concrete!r}")
    check(concrete.rstrip().endswith("return len(self.items)"),
          f"the body was cut with the head: {concrete!r}")
    check("List[Int]" in concrete,
          f"a type parameter inside another parameter's ANNOTATION was not "
          f"substituted: {concrete!r}")
    try:
        mod = F.Parser(F.py_tokenize(concrete)).parse_module()
    except Exception as exc:                        # noqa: BLE001
        raise TestFailure(
            f"the instantiation does not parse, which is the whole defect: "
            f"{exc!r}\n{concrete!r}") from None
    check(any(getattr(s, "name", None) == mangled for s in mod),
          f"the parser did not read the instantiated name back: "
          f"{[getattr(s, 'name', None) for s in mod]}")

    # THE CONTROL, so the fix cannot be "the parameter list ends at the first
    # `]`" all over again, and the NESTED case, because a matcher that counts
    # one level is a matcher with the same bug one level down.
    import elaborate as E
    check(E.type_param_names("struct Box[T: AnyType, keys: List[T]]:\n"
                             "    pass\n") == ["T", "keys"],
          "the parameter reader stops at the `]` inside `List[T]`")
    check(E.type_param_names(
        "struct Box[T, keys: SIMD[Tuple[Int, Int], 4]]:\n    pass\n")
        == ["T", "keys"],
        "a bracketed type argument carrying its own comma splits the parameter "
        "in half (`split(',')` rather than a top-level split)")
    check(E.parse_bounds("struct Box[T: AnyType, keys: List[T]]:\n    pass\n")
          == {"T": "AnyType", "keys": "List[T]"},
          "the trait bound of a parameter whose type is a type application is "
          "read from a truncated list")

    # …and the multi-line form `type_dict.mojo` writes, whose parameters carry
    # a trailing comma, a `//` separator and a `*values` marker. This is the
    # real declaration, transcribed: every parameter of that struct is a VALUE,
    # so the `keys: List[T]` line is not an edge case there but the middle of
    # the parameter list, and before the fix `type_param_names` returned
    # `['T', 'Trait', 'keys']` — it stopped at that `]` and lost `*values`.
    typed_dict = ("struct TypeDict[\n"
                 "    T: Equatable & Movable,\n"
                 "    Trait: type_of(AnyType),\n"
                 "    //,\n"
                 "    keys: List[T],\n"
                 "    *values: Trait,\n"
                 "](TrivialRegisterPassable):\n"
                 "    var items: List[T]\n"
                 "\n"
                 "    def get(self) -> Int:\n"
                 "        return len(Self.keys) + len(self.items)\n")
    check(E.type_param_names(typed_dict) == ["T", "Trait", "keys", "*values"],
          f"std/collections/type_dict.mojo's parameter list is not read whole: "
          f"{E.type_param_names(typed_dict)}")
    mangled_td, concrete_td = MM.instantiate(
        typed_dict, "TypeDict", ("Int", "AnyType", "[1,2,3]", "String"))
    check("len([1,2,3])" in concrete_td,
          f"`len(Self.keys)` was not folded with the argument the "
          f"instantiation supplied: {concrete_td!r}")
    try:
        F.Parser(F.py_tokenize(concrete_td)).parse_module()
    except Exception as exc:                        # noqa: BLE001
        raise TestFailure(f"the TypeDict instantiation does not parse: "
                          f"{exc!r}\n{concrete_td!r}") from None
    check(concrete_td.startswith(f"struct {mangled_td}("),
          f"the declaration's base class and parameter list were lost: "
          f"{concrete_td!r}")


def test_a_stated_mangled_spelling_is_the_one_the_mangler_produces(tmpdir):
    """No `doc/` or `bugs/` file may state a mangled spelling the mangler does
    not produce.

    The two cases above used to write `Pair_Int` out by hand, and both went
    stale the moment `monomorphize.mangle` became injective — leaving
    `doc/ABI.md` §Generics stating, in the one document a consumer reads to
    learn what the boundary symbol is, a symbol no code produces. Deriving the
    expected name in a TEST is not enough: a test stops at its own file, and
    the sentence a reader reads was in a contract. So the invariant is checked
    where the prose is.

    `Pair[Int]` is the witness because it is the example every one of these
    documents uses. The rule is deliberately narrow: it looks for a token that
    LOOKS like this mangling (`Pair_` plus an alnum continuation) and requires
    it to be a well-formed `_fields` encoding — `Pair` followed by one or more
    `_{len}_{name}_{len}_{value}` fields, each declared length checked against
    the segment it introduces. That is what `monomorphize._fields` emits and
    what its docstring says is uniquely decodable ("the maximal digit run is a
    count, the next `_` separates, and each count is followed by exactly that
    many characters"), so the check is the mangler's own format read back rather
    than a copy of it: `Pair_1_T_6_Colour` is a different instantiation and
    passes, `Pair_Int` and `Pair_Colour` are the pre-injective shape and do not.
    Asking "is this string a mangling of SOME instantiation" rather than "is it
    the one for `Int`" is what lets a document use the mangler on any example.

    **A paragraph that discusses the ENCODING may name the spelling the
    encoding replaced**, because "it used to be `Pair_Int`" is the sentence that
    tells a reader holding the old name what to look for. That exemption is
    keyed on the word `injective` in the paragraph rather than on any list of
    known-old spellings, so it cannot rot into "any stale spelling is fine" —
    an example line does not say the encoding is injective, and the two
    paragraphs that do are the ones about the change. The scan is per paragraph
    rather than per line because prose wraps: the word and the spelling it
    qualifies are routinely 80 columns apart.
    """
    import monomorphize
    import re
    problems: list = []

    def decodes(token: str) -> bool:
        """Whether `token` is `<name>` followed by `_fields`-shaped fields.

        The decoder is `monomorphize._fields`' own description read back: at
        each position a digit run is a length, an `_` separates, and exactly
        that many characters must follow. Written out rather than imported
        because there is nothing to import — `_fields` produces, it does not
        parse — and because a test that re-implements the producer's format is
        what makes the format a CONTRACT rather than an accident.
        """
        pos = token.find("_")
        if pos < 0:
            return False                      # no fields: `Pair` is its own name
        i = pos + 1
        fields = 0
        while i < len(token):
            start = i
            while i < len(token) and token[i].isdigit():
                i += 1
            if i == start or i >= len(token) or token[i] != "_":
                return False
            count = int(token[start:i])
            i += 1
            if i + count > len(token) or token[i + count] != "_":
                return False
            i += 1 + count                    # the field's name
            start = i
            while i < len(token) and token[i].isdigit():
                i += 1
            if i == start or i >= len(token) or token[i] != "_":
                return False
            count = int(token[start:i])
            i += 1
            if i + count > len(token):
                return False
            i += count                        # the field's value
            fields += 1
        return fields > 0

    pattern = re.compile(r"\bPair_[A-Za-z0-9_]*")
    for root in ("doc", "bugs"):
        base = os.path.join(HERE, root)
        for dirpath, _dirs, files in os.walk(base):
            for name in sorted(files):
                if not name.endswith(".md"):
                    continue
                path = os.path.join(dirpath, name)
                rel = os.path.relpath(path, HERE)
                text = open(path, encoding="utf-8").read()
                for para in re.split(r"\n\s*\n", text):
                    if "injective" in para.lower():
                        continue
                    for token in pattern.findall(para):
                        token = token.rstrip("_")
                        if not decodes(token):
                            line = text[:text.index(para)].count("\n") + 1
                            problems.append(
                                f"{rel}:{line} states {token!r}, which is not a "
                                f"spelling monomorphize.mangle can produce — it "
                                f"emits length-prefixed fields "
                                f"(`Pair[Int]` is "
                                f"{monomorphize.mangle('Pair', {'T': 'Int'})!r}"
                                f"), and this one carries no lengths")
    check(not problems,
          "a document states a mangled spelling no code produces:\n  "
          + "\n  ".join(problems))


# ── what the INFERENCE would have to do, measured ──────────────────────────
#
# The case above is the control: `widen(5)` is refused, and the refusal says the
# source is right and this path does not infer the type arguments. That is the
# honest half. The other half is the SIZE of the work, and
# `bugs/FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable.md`
# §3 step 1 asks for it without having it: "derive its type arguments from the
# call's argument types instead of from a bracket" — where the type argument "is
# not IN the call, it is a property of the argument's DECLARED TYPE".
#
# `tools/formal_template_call_census.py` is that measurement, and these two cases
# are what keeps it honest: the first asks the classifier each of the five
# questions on sources small enough to read, the second asks it the three shapes
# the doc MEASURED on the real stdlib, so a census whose numbers have drifted
# from the corpus says so here rather than in the next sweep.

def _census_rows(root):
    """The census over one directory, as `{callee: [(bucket, bounded, selfq)]}`."""
    sys.path.insert(0, os.path.join(HERE, "tools"))
    import formal_template_call_census as T
    rows, _n_files, _n_calls, unresolved = T.collect([root])
    out = {}
    for _path, _line, name, _module, bucket, bounded, selfq, _params in rows:
        out.setdefault(name, []).append((bucket, bounded, selfq))
    return out, unresolved


def test_the_census_answers_each_of_its_seven_questions(tmpdir):
    """One small source per bucket, because the classifier IS the measurement.

    Each pair below is a library and a caller, and each caller is written so that
    exactly one thing decides its bucket. The seven are the answers an
    implementation of `monomorph.all_instantiation_calls` has to be able to give,
    and a classifier that cannot tell them apart cannot be used to size the work
    either — it would report one number for a feature whose cost is the
    difference between a matcher and a type inferrer.

    **Four of the seven are the corrections of 2026-10-04**
    (`…_inferrable.md` §5b), and each has a fixture that fails without its fix:
    a KEYWORD argument (`Kw`), a comment inside the header (`note`), a comptime
    DEFAULT that is not a type (`cur`), and a declaration the export rule calls a
    template with nothing to substitute (`pick`). Between them they took the
    corpus's `solvable` count from 32 to 2, and the three that were the largest
    of them — 17 `ThinAllocation`, 7 `is_32bit`, `dlsym`'s comment read as a
    type parameter — were all invisible to the pre-2026-10-04 classifier.
    """
    root = os.path.join(tmpdir, "census")
    write_tree(root, {
        # 1. The argument's type is written down and names the parameter:
        #    unification over two annotation strings.
        "easy.mojo": "def widen[T: AnyType](v: T) -> T:\n    return v\n",
        "use_easy.mojo": ("from easy import widen\n"
                          "\n"
                          "def main(n: Int):\n"
                          "    print(widen(n))\n"),
        # 2. Written, but the annotation does not name the parameter: `T: Writer`
        #    against `Some[Writer]` is a bound-resolution question.
        "bound.mojo": ("struct Box[T: Writer]:\n"
                       "    var w: T\n"
                       "\n"
                       "    def __init__(out self, w: T):\n"
                       "        self.w = w\n"),
        "use_bound.mojo": ("from bound import Box\n"
                           "\n"
                           "def show(mut w: Some[Writer]):\n"
                           "    var b = Box(w)\n"
                           "    print(b)\n"),
        # 3. The declaration names the parameter; the argument is a CALL, so its
        #    type needs a return type this path does not compute.
        "made.mojo": "def make_it[T: AnyType](n: T) -> T:\n    return n\n",
        "use_made.mojo": ("from made import make_it\n"
                          "\n"
                          "def main():\n"
                          "    print(make_it(other()))\n"),
        # 4. A phantom: nothing in any parameter mentions `U`, and it has no
        #    default, so no argument can supply it.
        "phantom.mojo": "def pair_up[T: AnyType, U](a: T) -> T:\n    return a\n",
        "use_phantom.mojo": ("from phantom import pair_up\n"
                              "\n"
                              "def main(n: Int):\n"
                              "    print(pair_up(n))\n"),
        # 5. `Self.T` and `ref[Self.o]`: the origin is carried by the CONVENTION,
        #    which `fire_compiler` normalises away, so a matcher that reads only
        #    the annotation files this as a phantom. It is not: both parameters
        #    are decided, and the answer is `NO_UNIFY` because the argument's
        #    `Some[Writer]` does not unify with `T`.
        "fmt.mojo": ("struct FormatStruct[T: Writer, o: MutOrigin]:\n"
                     "    var w: T\n"
                     "\n"
                     "    def __init__(\n"
                     "        out self,\n"
                     "        *,\n"
                     "        ref[Self.o] writer: Self.T,\n"
                     "    ):\n"
                     "        self.w = writer\n"),
        "use_fmt.mojo": ("from fmt import FormatStruct\n"
                         "\n"
                         "def show(mut writer: Some[Writer]):\n"
                         "    var f = FormatStruct(writer)\n"
                         "    print(f)\n"),
        # 6. A DEFAULT settles a parameter no argument mentions, so this is not a
        #    phantom — `invariant` is filled in by Mojo, not by the arguments.
        #    …and it is not SOLVABLE either, which is the correction: `False` is a
        #    comptime VALUE, so the instantiation this site would need is
        #    `masked[Int, False]` and `monomorph.type_arg_text` refuses a literal.
        #    Reported as `solvable` before 2026-10-04, which made this fixture the
        #    single largest false positive the instrument had.
        "masked.mojo": ("def masked[T: AnyType, invariant: Bool = False]"
                        "(v: SIMD[T, _]) -> T:\n    return v\n"),
        #    The caller's annotation is `List[Int]` rather than
        #    `SIMD[DType.float32, 4]` on purpose: a SIMD width is a LITERAL inside
        #    a type application, `type_arg_text` refuses a literal, and this
        #    fixture is about the comptime default and not about that. The
        #    unspellable-annotation case is `spellable` below.
        "use_masked.mojo": ("from masked import masked\n"
                            "\n"
                            "def main(n: List[Int]):\n"
                            "    print(masked(n))\n"),
        # 7. A comptime DEFAULT that is not a type at all: `is_32bit`'s own
        #    `target: CompilationTarget = CompilationTarget.current()`, which is
        #    7 of the corpus's sites. The declaration is readable, the argument
        #    list is empty, and there is nothing to unify — so the answer is not
        #    "solvable" but "settled by something this path cannot spell".
        #    One parameter, defaulted, and no value parameter at all — which is
        #    `std/sys/info.mojo`'s `is_32bit` exactly. A second, undefaulted
        #    parameter would make this a PHANTOM instead, which is a different
        #    question and is already row 4 above.
        "cur.mojo": ("def cur[target: CompilationTarget = "
                     "CompilationTarget.current()]() -> Bool:\n"
                     "    return False\n"),
        "use_cur.mojo": ("from cur import cur\n"
                         "\n"
                         "def main():\n"
                         "    print(cur())\n"),
        # 8. A KEYWORD argument, which is 17 of the 32 sites the pre-2026-10-04
        #    census called solvable and is the corpus's largest instance of the
        #    shape: the argument is in `call.kwargs`, a reader that walks
        #    `call.args` sees nothing at all, and a site nothing was inspected of
        #    falls out of every test into `solvable`.
        "kw.mojo": ("struct Kw[T: AnyType]:\n"
                    "    var xs: List[T]\n"
                    "\n"
                    "    def __init__(out self, *, holder: List[T]):\n"
                    "        self.xs = holder\n"),
        "use_kw.mojo": ("from kw import Kw\n"
                        "\n"
                        "def main(xs: List[Int]):\n"
                        "    var k = Kw(holder=xs)\n"
                        "    print(k)\n"),
        # 9. A COMMENT inside the header. It is not only a parameter this reader
        #    would misread (`std/ffi/__init__.mojo`'s `dlsym` reported a type
        #    parameter called "# Default `dlsym` result is an OpaquePointer."), it
        #    is also a bracket `_balanced` would count.
        "note.mojo": ("def note[\n"
                      "    # the element type\n"
                      "    T: AnyType = Int\n"
                      "](v: List[T]) -> T:\n"
                      "    return v[0]\n"),
        "use_note.mojo": ("from note import note\n"
                          "\n"
                          "def main(xs: List[Int]):\n"
                          "    print(note(xs))\n"),
        # 10. An argument annotation that is a type but NOT one this path could
        #     mangle: `SIMD[DType.float32, 4]`'s width is a literal, and
        #     `type_arg_text` reads a literal as no type argument at all. The
        #     bucket is `UNDECLARED` — the same place a call or an operator lands
        #     — because what the implementer has to do is the same in both cases:
        #     there is no type argument here to be had, whatever the source wrote.
        "spellable.mojo": "def wide2[T: AnyType](v: T) -> T:\n    return v\n",
        "use_spellable.mojo": ("from spellable import wide2\n"
                               "\n"
                               "def main(n: SIMD[DType.float32, 4]):\n"
                               "    print(wide2(n))\n"),
        # 11. A declaration the EXPORT RULE calls a template and which has no type
        #     parameter to substitute — `def pick[](v: Int)`. `monomorph.instantiate`
        #     refuses exactly this ("its declaration has no type parameter, so there
        #     is nothing to substitute"), so a census that reports it `solvable` is
        #     promising an instantiation nothing can build. It was `solvable` for
        #     every `*`-sigil header (`fcntl[*types: Intable]`) before
        #     2026-10-04.
        "pick.mojo": "def pick[](v: Int) -> Int:\n    return v\n",
        "use_pick.mojo": ("from pick import pick\n"
                          "\n"
                          "def main(n: Int):\n"
                          "    print(pick(n))\n"),
    })
    sys.path.insert(0, os.path.join(HERE, "tools"))
    import formal_template_call_census as T
    got, unresolved = _census_rows(root)
    check(not unresolved,
          f"the census could not resolve a defining module in its own fixture: "
          f"{unresolved}")
    want = {
        "widen": T.BUCKET_SOLVABLE,
        "Box": T.BUCKET_NO_UNIFY,
        "make_it": T.BUCKET_UNDECLARED,
        "pair_up": T.BUCKET_PHANTOM,
        "FormatStruct": T.BUCKET_NO_UNIFY,
        "masked": T.BUCKET_COMPTIME_DEFAULT,
        "cur": T.BUCKET_COMPTIME_DEFAULT,
        "Kw": T.BUCKET_SOLVABLE,
        "note": T.BUCKET_SOLVABLE,
        "pick": T.BUCKET_NO_PARAMETER,
        "wide2": T.BUCKET_UNDECLARED,
    }
    for name, bucket in want.items():
        rows = got.get(name) or []
        check(rows, f"{name}(…) was not classified at all; the census saw "
                    f"{sorted(got)}")
        check(all(r[0] == bucket for r in rows),
              f"{name}(…) classified {[r[0] for r in rows]}, expected "
              f"{bucket!r} for every site")
    # The two flags, because they are what turns bucket 2 from "unify two
    # strings" into "resolve a trait bound": `Box` is bounded and `FormatStruct`
    # is written `Self.T`/`Self.o`.
    check(all(r[1] for r in got["Box"]),
          f"Box[T: Writer] classified with no trait-bound flag: {got['Box']}")
    check(all(r[2] for r in got["FormatStruct"]),
          f"FormatStruct's `ref[Self.o] writer: Self.T` did not set the "
          f"`Self.T` flag: {got['FormatStruct']}")
    # The two `solvable` rows here are the only two of ten, and that is the
    # point of the corrections rather than an accident of the fixture: three of
    # the ten are shapes a pre-2026-10-04 reader called `solvable` (the keyword,
    # the comment, the comptime default) and a fourth is a declaration with
    # nothing to substitute at all.
    check({n for n, b in want.items() if b == T.BUCKET_SOLVABLE} ==
          {"widen", "Kw", "note"},
          f"the fixture's solvable set moved: "
          f"{sorted(n for n, b in want.items() if b == T.BUCKET_SOLVABLE)}")


def test_the_census_reads_the_measured_shapes_out_of_the_corpus(_tmpdir):
    """The three symbols the doc measured, asked of the real stdlib.

    `bugs/FORMAL_a_bare_call_to_a_template_whose_type_arguments_are_inferrable.md`
    §1 measures the row by the callee the refusal names — `FormatStruct` 68
    files, `dealloc` 29, `is_negative` 13 — and §2 says every one of those type
    arguments is inferable from the argument's declared type. Asking this census
    about the three is the check that the measurement and the instrument agree,
    and it is where a census that has drifted says so: a stdlib that moved these
    declarations changes the answer here.

    Skipped, with the reason printed and counted, when there is no stdlib
    checkout beside this tree — see `_Skip` and `_stdlib_dir`.

    The scratch directory is taken and unused (`_tmpdir`): this is a static
    census over the stdlib's SOURCE, so it builds nothing. The parameter is
    still declared because the runner's contract is that every case takes one —
    see `_check_case_arities` — and a case that quietly took none raised
    `TypeError` before its first assertion, which the runner reported as an
    ERROR for a case whose whole subject is the corpus.
    """
    stdlib = FI._stdlib_dir()
    if stdlib is None:
        raise _Skip("no stdlib checkout beside this tree, so there are no "
                    "measured call sites to classify")
    sys.path.insert(0, os.path.join(HERE, "tools"))
    import formal_template_call_census as T
    rows, _n_files, _n_calls, unresolved = T.collect([stdlib])
    check(not unresolved,
          f"{len(unresolved)} (file, name) pair(s) named a module that did not "
          f"resolve, so the census is not reporting the whole scope it claims: "
          f"{unresolved[:4]}")
    per = {}
    for _path, _line, name, _module, bucket, bounded, selfq, _params in rows:
        per.setdefault(name, []).append((bucket, bounded, selfq))
    want = {
        "FormatStruct": T.BUCKET_NO_UNIFY,     # `Some[Writer]` against `T: Writer`
        "dealloc": T.BUCKET_UNDECLARED,        # the argument is `x^`
        # …and the row that moved: seven sites whose only type argument is settled
        # by `CompilationTarget.current()`, which is a comptime EXPRESSION and not
        # a type this path can mangle. Reported `solvable` before 2026-10-04
        # because a call with no arguments reaches no test at all.
        "is_32bit": T.BUCKET_COMPTIME_DEFAULT,
    }
    for name, bucket in want.items():
        sites = per.get(name) or []
        check(sites, f"{name}(…) has no site in the census over {stdlib}, so "
                     f"the measurement the doc quotes is not being reproduced")
        wrong = sorted({b for b, _bd, _s in sites} - {bucket})
        check(not wrong,
              f"{name}(…) classified {wrong} where the doc's §2 says the "
              f"argument's type decides it ({bucket!r}); the census and the "
              f"measurement disagree")
    # `is_negative` is the doc's third measured shape and it is TWO shapes, so it
    # is asserted as a set rather than as one bucket: `std/bit/bit.mojo`'s site is
    # inside `bit_width[dtype: DType, width: Int](val: SIMD[dtype, width])`, so the
    # answer a matcher derives is the ENCLOSING template's own `dtype` and no
    # instantiation can be mangled under it, while
    # `std/collections/string/string_span.mojo`'s `is_negative(rhs)` reads a
    # `var rhs: Int` and `dtype := Int` is a real answer. The 2026-10-04 change
    # is what tells those two apart; before it, both were `solvable` and the
    # `Solvable`-count the doc's §5 quotes was 32.
    neg = per.get("is_negative") or []
    check(neg, f"is_negative(…) has no site in the census over {stdlib}, so the "
               f"doc's third measured shape is not being reproduced")
    check({b for b, _bd, _s in neg} <= {T.BUCKET_SOLVABLE, T.BUCKET_UNDECLARED},
          f"is_negative(…) classified {[b for b, _x, _y in neg]}, which is "
          f"neither of the two shapes its sites are: an enclosing template's own "
          f"`dtype` (not spellable) or a concrete `var rhs: Int` (spellable)")
    check(any(b == T.BUCKET_SOLVABLE for b, _bd, _s in neg),
          f"no is_negative(…) site is solvable, so the doc's §2 claim that its "
          f"type argument is inferable from the argument's declared type is not "
          f"reproduced anywhere in the corpus: {[(b, s) for b, _x, s in neg]}")
    check(any(bounded for _b, bounded, _s in per.get("FormatStruct", [])),
          "FormatStruct[T: Writer] classified with no trait-bound row, so the "
          "bound that makes its unification a bound-resolution question is "
          "not being read")
    # The arithmetic, asserted here because the tool's own docstring says its
    # totals are only comparable if they add up.
    kinds = {}
    for _p, _l, _n, _m, bucket, _b, _s, _params in rows:
        kinds[bucket] = kinds.get(bucket, 0) + 1
    check(sum(kinds.values()) == len(rows),
          f"the buckets sum to {sum(kinds.values())} over {len(rows)} rows")
    check(set(kinds) <= set(T.BUCKETS),
          f"a row carries a bucket the tool does not declare: "
          f"{sorted(set(kinds) - set(T.BUCKETS))}")


def test_a_variadic_bracket_parameter_takes_the_extra_arguments(tmpdir):
    """`*values: T` is one declaration with an ARITY, and it was read as one
    NAME — so a use site written the way the stdlib writes it was refused for
    arity.

    `elaborate.type_param_names` returns `['T', 'Trait', 'keys', '*values']` for
    `type_dict.mojo`'s real declaration, so the `*` is right there in the list and
    `instantiate` compared its LENGTH against the argument count:

        MonomorphError: Pair[Int, 1, 2, 3] supplies 4 type arguments but `Pair`
        declares 2 (T, *values); an instantiation is one template specialized
        for exactly the arguments it declares

    Six arguments against four names is not a malformed bracket when one of the
    names declares an arity, and the repair that message offered — "take the
    arguments as named parameters" — is the program rewritten, not the program
    answered.

    **What is asserted here is the three things the rule decides**, in the order
    they can each be wrong: the arity (four counts, all of which must
    instantiate), the SUBSTITUTION (a tuple display, because a `*values` is a
    sequence of the arguments supplied and `len(())` is 0 rather than a
    subscript into a name nothing declared), and the IDENTITY (two counts must
    be two mangled names, or the second instantiation would overwrite the
    first's symbol and a consumer would silently bind the wrong body — the
    whole class of bug this feature has). And the emitted source PARSES, for
    the reason the case above exists.
    """
    from formal import monomorph as MM
    import fire_compiler as F
    src = ("struct Pair[T: AnyType, *values: T]:\n"
           "    comptime length = len(Self.values)\n"
           "\n"
           "    def size(self) -> Int:\n"
           "        return Self.length\n")
    names = {}
    for args, want in ((("Int",), "len(())"),
                       (("Int", "1"), "len((1,))"),
                       (("Int", "1", "2", "3"), "len((1, 2, 3))")):
        mangled, concrete = MM.instantiate(src, "Pair", args)
        check(want in concrete,
              f"Pair[{' , '.join(args)}] bound `*values` to something other "
              f"than {want!r}: {concrete!r}")
        try:
            F.Parser(F.py_tokenize(concrete)).parse_module()
        except Exception as exc:                    # noqa: BLE001
            raise TestFailure(
                f"the variadic instantiation does not parse, which is the "
                f"whole defect for this shape: {exc!r}\n{concrete!r}") from None
        names[len(args)] = mangled
    check(len(set(names.values())) == len(names),
          f"two variadic counts produced one mangled name {names}, so the "
          f"second instantiation would overwrite the first's symbol")
    check("(1,)" in MM.instantiate(src, "Pair", ("Int", "1"))[1],
          "a one-element sequence is spelled `(1,)` and not `(1)` — a "
          "parenthesised expression is not a tuple and `len((1))` is a type "
          "error the reader would have to decode")

    # THE REFUSAL THAT SURVIVES, because a rule that reads `*` as an exemption
    # from the arity check would take the check with it: too FEW arguments binds
    # a declaration the bracket does not supply, whatever the declaration says.
    # `**kwargs` is the other half — a keyword collection has no positional
    # spelling in a bracket, so the star is not an exemption there either.
    try:
        MM.instantiate(src, "Pair", ())
    except MM.MonomorphError as e:
        check("supplies 0 type arguments" in str(e),
              f"too few arguments is not refused any more, and its message "
              f"does not say what it counted: {e}")
    else:
        raise TestFailure(
            "a bracket with fewer arguments than the declaration's FIXED "
            "parameters instantiated anyway, so the emitted body would be built "
            "from a parameter the source never bound")
    kwargs = "struct P[T: AnyType, **kw: T]:\n    var x: Int\n"
    try:
        MM.instantiate(kwargs, "P", ("Int", "Bool"))
    except MM.MonomorphError as e:
        check("keyword collection" in str(e),
              f"a `**kwargs` parameter was treated as variadic without saying "
              f"why it is not: {e}")
    else:
        raise TestFailure(
            "`**kwargs` was bound as a positional variadic; a bracket argument "
            "is a positional spelling and a keyword collection is not one")


TESTS = [
    ("a generic struct template is instantiated at the importer's type",
     test_a_generic_struct_template_is_instantiated_at_the_importers_type),
    ("a generic function template is instantiated too",
     test_a_generic_function_template_is_instantiated_too),
    ("a struct template the module declares can itself apply",
     test_a_struct_template_the_module_declares_can_itself_apply),
    ("a module that applies its own template publishes it",
     test_a_module_that_applies_its_own_template_publishes_it),
    ("a package re-export attributes the demand to the defining module",
     test_a_package_reexport_attributes_the_demand_to_the_defining_module),
    ("an instantiation agrees with the concrete struct of the same shape",
     test_an_instantiation_agrees_with_the_concrete_struct_of_the_same_shape),
    ("a bare call to an imported generic is still refused",
     test_a_bare_call_to_an_imported_generic_is_still_refused),
    ("a non-concrete type argument is still refused",
     test_a_non_concrete_type_argument_is_still_refused),
    ("only the export rule says what is a template",
     test_only_the_export_rule_says_what_is_a_template),
    ("a source-derived answer is made once per source and never shared",
     test_a_source_derived_answer_is_made_once_per_source_and_never_shared),
    ("a template is located once per source and name",
     test_a_template_is_located_once_per_source_and_name),
    ("the re-export closure is walked once for a consumer's whole dep set",
     test_the_re_export_closure_is_walked_once_for_a_consumers_whole_dep_set),
    ("an instantiation substitutes the parameter and keeps the Self spelling",
     test_an_instantiation_substitutes_the_parameter_and_keeps_the_self_spelling),
    ("a type argument that is computed is not a demand",
     test_a_type_argument_that_is_computed_is_not_a_demand),
    ("a value-typed bracket is not read as a type",
     test_a_value_typed_bracket_is_not_read_as_a_type),
    ("two demand sets are two libraries",
     test_two_demand_sets_are_two_libraries),
    ("a literal display is a bracket argument and a bare literal is not",
     test_a_literal_display_is_a_bracket_argument_and_a_bare_literal_is_not),
    ("a value bracket argument reaches the boundary symbol",
     test_a_value_bracket_argument_reaches_the_boundary_symbol),
    ("a bracketed parameter annotation instantiates",
     test_a_bracketed_parameter_annotation_instantiates),
    ("a stated mangled spelling is the one the mangler produces",
     test_a_stated_mangled_spelling_is_the_one_the_mangler_produces),
    ("the census answers each of its seven questions",
     test_the_census_answers_each_of_its_seven_questions),
    ("the census reads the measured shapes out of the corpus",
     test_the_census_reads_the_measured_shapes_out_of_the_corpus),
    ("a variadic bracket parameter takes the extra arguments",
     test_a_variadic_bracket_parameter_takes_the_extra_arguments),
]

EXPECTED_FAILURES: dict = {}


def _check_case_arities() -> None:
    """Every case takes the run's scratch directory, and says so here.

    The runner calls `fn(tmpdir)` unconditionally, which is the contract; this
    is the one place that states it, so a case written without the parameter
    fails at the START of the run naming itself instead of reaching its own
    first assertion as a `TypeError` the runner reports as an ERROR — an
    ERROR that reads like the case failed rather than like it never ran, which
    is how `test_the_census_reads_the_measured_shapes_out_of_the_corpus` spent
    a run reporting "the census answers each of the five questions" while the
    case that asks the corpus had never been called.

    An unused scratch directory is named `_tmpdir`, which is the convention the
    census case above follows; it is not a second arity.
    """
    import inspect
    wrong = []
    for name, fn in TESTS:
        params = list(inspect.signature(fn).parameters.values())
        if len(params) != 1 or params[0].kind in (params[0].VAR_POSITIONAL,
                                                 params[0].VAR_KEYWORD):
            wrong.append(f"{fn.__name__} takes "
                         f"{[p.name for p in params] or 'nothing'}")
    if wrong:
        raise SystemExit(
            "every case in TESTS takes the scratch directory the runner passes "
            "it, and these do not: " + "; ".join(wrong) +
            "\n  add the parameter (named `_tmpdir` when the case builds "
            "nothing) rather than letting the runner discover it at call time.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: formal output is arm64-only, host is "
              f"{platform.machine()}")
        return 0

    _check_case_arities()

    passed = failed = expected = skipped = 0
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            for name, fn in TESTS:
                expect = EXPECTED_FAILURES.get(name)
                try:
                    fn(tmpdir)
                except _Skip as e:
                    skipped += 1
                    print(f"  SKIP  {name}\n        {e}")
                    continue
                except TestFailure as e:
                    if expect is not None:
                        expected += 1
                        print(f"  EXPECTED  {name}\n        {expect}")
                        continue
                    failed += 1
                    print(f"  FAIL  {name}\n        {e}")
                    continue
                except Exception as e:
                    if expect is not None:
                        expected += 1
                        print(f"  EXPECTED  {name}\n        {expect}")
                        if args.verbose:
                            import traceback
                            traceback.print_exc()
                        continue
                    failed += 1
                    print(f"  ERROR {name}\n        {type(e).__name__}: {e}")
                    if args.verbose:
                        import traceback
                        traceback.print_exc()
                    continue
                if expect is not None:
                    failed += 1
                    print(f"  FAIL  {name}\n        marked expect=… but it "
                          f"PASSES — drop the marker")
                    continue
                passed += 1
                print(f"  PASS  {name}")
    finally:
        # `test_formal_imports` drops its temporary CAS home only under its own
        # `__main__`, and importing it is what gave this file an isolated
        # `GMOJO_HOME` in the first place — so the cleanup is this file's to
        # make, or the directory outlives the run.
        FI._drop_cas_home()
    total = passed + failed + expected + skipped
    print(f"\nformal monomorphization: PASS={passed} EXPECTED={expected} "
          f"SKIP={skipped} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())