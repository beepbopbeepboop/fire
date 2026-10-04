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
    for the cases that need a package beside the library.
    """
    root = os.path.join(tmpdir, f"{name}_{arch}")
    os.makedirs(root)
    files = {libname: lib, "main.mojo": prog}
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


TESTS = [
    ("a generic struct template is instantiated at the importer's type",
     test_a_generic_struct_template_is_instantiated_at_the_importers_type),
    ("a generic function template is instantiated too",
     test_a_generic_function_template_is_instantiated_too),
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
    ("an instantiation substitutes the parameter and keeps the Self spelling",
     test_an_instantiation_substitutes_the_parameter_and_keeps_the_self_spelling),
    ("a type argument that is computed is not a demand",
     test_a_type_argument_that_is_computed_is_not_a_demand),
    ("a value-typed bracket is not read as a type",
     test_a_value_typed_bracket_is_not_read_as_a_type),
    ("two demand sets are two libraries",
     test_two_demand_sets_are_two_libraries),
    ("a bracketed parameter annotation instantiates",
     test_a_bracketed_parameter_annotation_instantiates),
    ("a stated mangled spelling is the one the mangler produces",
     test_a_stated_mangled_spelling_is_the_one_the_mangler_produces),
]

EXPECTED_FAILURES: dict = {}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: formal output is arm64-only, host is "
              f"{platform.machine()}")
        return 0

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