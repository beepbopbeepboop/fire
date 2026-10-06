#!/usr/bin/env python3
"""A module whose whole API is TRAITS builds, and an importer of it runs.

## What this pins, and why it is not a message fix

`std/traits/anytype.mojo` declares `trait AnyType:` and nothing else. Every
read of `AnyType` in the standard library is a TYPE position — `def
f[T: AnyType](…)`, `var h: Some[Copyable]` — and yet that module was refused
with the sentence "anytype.mojo exports nothing under doc/ABI.md's rules
because it declares no function and no type at all". It declares a type. The
refusal was false about the file, and it took five of the x86-64 sweep's
`codegen/dependency` lines with it (`tools/formal_sweep.py`, the
`anytype.mojo: module exports nothing x5` row).

Two changes make it true, and only the first is a diagnostic:

  1. `declared_kinds` files a `TraitDef` as a TYPE. Without that a package that
     re-exports a trait — `std/traits/__init__.mojo` is five `from .sub import
     Name` statements and nothing else — reached `compile_formal_dylib` with the
     name's kind `"unknown"`, which is not `"type"`, so it landed in the
     re-exported-FUNCTION set that must be *provided as a symbol*. A trait has
     no symbol, so the package was refused with the message for a missing
     function DEFINITION.
  2. `compile_formal_dylib` lowers a trait-only module the way it already
     lowered a pure re-export package: `_namespace_library`, a real MH_DYLIB
     with no code and an EMPTY export trie, with the traits recorded under the
     manifest's own `traits` key.

## Why the empty trie is the right answer and not a shortcut

A trait is a compile-time contract naming method SIGNATURES, and this backend
dispatches a method by NAME on the receiver's own type — `_struct_methods`
lifts a struct's methods; nothing resolves a name to a trait. So a trait-only
module has no code to emit, and a trie entry for a symbol this image does not
contain is an address lookup into an empty file, which is the one outcome worse
than refusing (`_namespace_library`'s own docstring).

That claim is not an inference from the design, it is pinned in both directions
below, because the thing that would make it false is a trait default method
becoming REACHABLE:

  * `a_trait_default_method_is_not_dispatched` — a trait default method called
    on a value is refused by name on the receiver, and it is refused
    IDENTICALLY whether the trait is declared in the same file or imported from
    another module. Identical is the load-bearing word: if the imported case
    were waved through, this test would see a build where it expects the
    refusal, which is the failure the empty trie must not introduce.
  * `a_structs_own_method_is_lowered_and_correct` — the positive control. A
    struct that defines the method itself is lowered from the STRUCT, runs, and
    agrees with CPython. So the refusal above is about trait dispatch and not
    about method calls in general, and this test is what would notice if a
    change started swallowing real methods.

Every executed case builds the image, RUNS it, and compares with CPython. The
CPython side is a separate twin source per case rather than the `.mojo` file
itself, for a reason that is a property of this tree and not of the construct:
a Mojo file using `struct`, `-> Int` and `T: Trait` is not a Python program, so
"the same text" is not available and the suite's own answer is a twin
(`test_formal_run.py`'s `run_cpython_pair_case` takes `source` and
`cpython_source` for exactly this). Each twin here is the same computation with
the Mojo-only spelling replaced, and each case says so at the point of use.

Invoked directly:
    python3 test_formal_trait_module.py [-v]
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from test_formal_dylib import TestFailure, check, parse_macho, run_fire

# This file gets a CAS of its OWN, for the reason `test_formal_imports.py`
# states and `test_formal_sweep.py` was bitten by: module dylibs are cached
# under `cas/formal-imports/<arch>/` by source digest, so a stale one from an
# earlier run can mask a regression, and against the shared `~/.gmojo` this
# file's "start from empty" would delete libraries a parallel job is holding a
# path to.
_CAS_HOME = tempfile.mkdtemp(prefix="formal_trait_cas_")
os.environ["GMOJO_HOME"] = _CAS_HOME
CAS_IMPORTS_ROOT = os.path.join(_CAS_HOME, "cas", "formal-imports")

RUN_TIMEOUT = 60


def _drop_cas_home():
    shutil.rmtree(_CAS_HOME, ignore_errors=True)


def cas_imports(arch="arm64"):
    return os.path.join(CAS_IMPORTS_ROOT, arch)


def module_dylib(prefix, arch="arm64"):
    import glob
    found = sorted(glob.glob(os.path.join(
        cas_imports(arch), f"{prefix}.*.{arch}.dylib")))
    if not found:
        raise AssertionError(
            f"no module dylib for {prefix!r} under {cas_imports(arch)}")
    return found[0]


def manifest(path):
    import json
    with open(path + ".manifest.json") as f:
        return json.load(f)


def fresh_cas():
    shutil.rmtree(CAS_IMPORTS_ROOT, ignore_errors=True)


def write_tree(root, files):
    for rel, text in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)


def build(root, name, expect_ok=True, arch=None):
    out = os.path.join(root, name)
    argv = ["build", "--formal", "--no-prove", "-o", out]
    if arch:
        argv.append(f"--backend={arch}")
    argv.append(os.path.join(root, name.replace(".aout", ".mojo")))
    result = run_fire(argv, cwd=root)
    if expect_ok:
        check(result.returncode == 0,
              f"build failed: {(result.stderr or result.stdout).strip()[-600:]}")
        check(os.path.isfile(out), f"no executable written at {out}")
    return result, out


def run_image(path):
    r = subprocess.run([path], capture_output=True, timeout=RUN_TIMEOUT)
    return r.returncode, r.stderr.decode()


def run_cpython(root, name):
    """CPython running the twin source, for the comparison every case makes.

    A formal entry point's return value IS its exit status — `main` returns it
    and the startup stub branches on it — so the twin raises `SystemExit` with
    the same value and the two answers are directly comparable.
    """
    r = subprocess.run([sys.executable, os.path.join(root, name)],
                       capture_output=True, timeout=RUN_TIMEOUT)
    return r.returncode, r.stderr.decode()


def require_same_as_cpython(root, out, twin, label):
    """The image's exit status must be the twin's, or say why it could not be run."""
    code, err = run_image(out)
    want, werr = run_cpython(root, twin)
    check(want != 1 or "Traceback" not in werr,
          f"the CPython twin itself failed (exit {want}): {werr[-300:]}")
    check(code == want,
          f"[{label}] the image returned {code}, CPython returned {want} for "
          f"the same computation; stderr: {err or werr}")


# ── the sources ──────────────────────────────────────────────────────────────

# A trait-only module: one trait, no function, no struct. This is the whole
# shape — `std/traits/anytype.mojo` is `trait AnyType:` and a docstring, and
# `std/os/pathlike.mojo` is `trait PathLike:` and a docstring.
TRAIT_LIB = '''\
"""A contract with no definition."""
trait Marker:
    def tag(self) -> Int:
        return 7
'''

# The importer. The trait BOUND (`T: Marker`, the spelling every stdlib
# signature uses) is what has to resolve; `use_it` never calls the trait's
# method, because nothing can (`a_trait_default_method_is_not_dispatched`).
TRAIT_PROG = '''\
from lib import Marker

struct Thing:
    var n: Int

    def __init__(out self, n: Int):
        self.n = n

def use_it[T: Marker](x: T) -> Int:
    return 41 + 1

def main() -> Int32:
    var t = Thing(3)
    return Int32(use_it(t))
'''

# The twin for `TRAIT_PROG`: the same computation, with `struct`/`-> Int`/
# `T: Trait` spelled the way Python spells them and the trait bound dropped
# (Python has no trait bounds, which is exactly the part of the Mojo program
# that is not Python). The arithmetic is 41 + 1 = 42 either way.
TRAIT_PROG_TWIN = '''\
class Thing:
    def __init__(self, n):
        self.n = n

def use_it(x):
    return 41 + 1

t = Thing(3)
raise SystemExit(use_it(t))
'''

# The package shape: `__init__.mojo` is nothing but `from .marker import
# Marker`, which is what `std/traits/__init__.mojo` is.
TRAIT_PKG = "from .marker import Marker\n"

# A trait default method called on a value, written TWICE — same file and
# imported — because "the same answer in both" is the property the empty trie
# rests on.
TRAIT_DISPATCH_SAME_FILE = '''\
trait Marker:
    def tag(self) -> Int:
        return 7

struct Thing:
    var n: Int

    def __init__(out self, n: Int):
        self.n = n

def main() -> Int32:
    var t = Thing(3)
    return Int32(t.tag())
'''

TRAIT_DISPATCH_IMPORTED = '''\
from lib import Marker

struct Thing:
    var n: Int

    def __init__(out self, n: Int):
        self.n = n

def main() -> Int32:
    var t = Thing(3)
    return Int32(t.tag())
'''

# The positive control: the method comes from the STRUCT, so it is lowered from
# the struct. `3 + 39 = 42` — the same 42 the other cases reach, deliberately,
# so a run that computed some other 42 cannot pass by coincidence.
STRUCT_METHOD = '''\
struct Thing:
    var n: Int

    def __init__(out self, n: Int):
        self.n = n

    def tag(self) -> Int:
        return self.n + 39

def main() -> Int32:
    var t = Thing(3)
    return Int32(t.tag())
'''

STRUCT_METHOD_TWIN = '''\
class Thing:
    def __init__(self, n):
        self.n = n

    def tag(self):
        return self.n + 39

raise SystemExit(Thing(3).tag())
'''

# A module with a trait AND a concrete function: the trait must not make the
# function disappear, and the function must still be exported and callable.
MIXED = '''\
trait Marker:
    pass

def bump(x: Int) -> Int:
    return x + 1
'''

MIXED_PROG = '''\
from mixed import Marker, bump

struct Thing:
    var n: Int

    def __init__(out self, n: Int):
        self.n = n

def use_it[T: Marker](x: T) -> Int:
    return bump(41)

def main() -> Int32:
    var t = Thing(3)
    return Int32(use_it(t))
'''

MIXED_PROG_TWIN = '''\
def bump(x):
    return x + 1

def use_it(x):
    return bump(41)

raise SystemExit(use_it(None))
'''


# ── the cases ────────────────────────────────────────────────────────────────

def test_a_trait_only_module_builds_and_the_importer_runs(tmpdir, _shared):
    """The construct: a trait-only module, and a program that imports it.

    Both architectures are BUILT, and the host's is EXECUTED and compared with
    CPython. A lowering that produced a wrong image would satisfy every
    structural check in this file and still fail here.
    """
    root = os.path.join(tmpdir, "trait")
    write_tree(root, {"lib.mojo": TRAIT_LIB, "prog.mojo": TRAIT_PROG,
                      "prog.py": TRAIT_PROG_TWIN})
    fresh_cas()
    # Both architectures build. Running the other one needs that machine, so
    # the executed comparison is on the host's and the build is the claim for
    # the other — stated here rather than left to look like both ran.
    for arch in ("arm64", "x86_64"):
        fresh_cas()
        _result, out = build(root, "prog.aout", arch=arch)
        if arch == platform.machine():
            require_same_as_cpython(root, out, "prog.py", arch)


def test_a_trait_only_module_is_a_namespace_library_with_an_empty_trie(tmpdir,
                                                                     _shared):
    """The restrictive direction: NO symbol, and the manifest says so.

    A trie entry for a symbol this image does not contain is an address lookup
    into a file with no code, which is the one outcome worse than refusing. So
    the one thing that must be right here is that the trie is empty, and the
    trait names must be recorded where a reader can see their absence is BY
    DESIGN — under `traits`, not under `reexports`, whose contract is "there is
    a symbol for this" (see `_record_namespace`).
    """
    root = os.path.join(tmpdir, "trie")
    write_tree(root, {"lib.mojo": TRAIT_LIB, "prog.mojo": TRAIT_PROG})
    fresh_cas()
    _result, _out = build(root, "prog.aout")
    lib = module_dylib("lib")
    m = manifest(lib)
    check(m.get("kind") == "namespace",
          f"the trait-only library is not marked namespace: {m.get('kind')!r}")
    check(m.get("exports") == [],
          f"the trait-only library exports {m.get('exports')!r}; a trait has "
          f"no symbol, so its export table must be empty — an entry here is an "
          f"address lookup into an image that has no code")
    check(m.get("traits") == ["Marker"],
          f"the trait is not recorded under the manifest's own `traits` key: "
          f"{m.get('traits')!r}")
    check("Marker" not in (m.get("reexports") or {}),
          f"the trait was filed under `reexports`, whose contract is that each "
          f"entry names a symbol: {m.get('reexports')!r}")
    # The trie itself, read with the independent reader rather than the writer.
    with open(lib, "rb") as f:
        info = parse_macho(f.read())
    check(info["exports"] == {},
          f"the trait-only library's export trie is not empty: "
          f"{info['exports']}")


def test_a_package_that_only_re_exports_traits_builds_and_runs(tmpdir,
                                                               _shared):
    """The `std/traits/__init__.mojo` shape: a re-export and nothing else.

    The package is a NAMESPACE library too, and its own re-export names a TYPE
    — which is what `declared_kinds` now has to say, because an unknown kind is
    not `"type"` and lands in the set that must be provided as a symbol. Before
    the change this was refused with the message for a missing function
    DEFINITION, naming a definition that was declared one file away.
    """
    root = os.path.join(tmpdir, "pkg")
    write_tree(root, {"pkg/__init__.mojo": TRAIT_PKG,
                      "pkg/marker.mojo": TRAIT_LIB,
                      "prog.mojo": TRAIT_PROG.replace("from lib import Marker",
                                                      "from pkg import Marker"),
                      "prog.py": TRAIT_PROG_TWIN})
    fresh_cas()
    _result, out = build(root, "prog.aout")
    require_same_as_cpython(root, out, "prog.py", "arm64")
    m = manifest(module_dylib("pkg"))
    check(m.get("kind") == "namespace",
          f"the package is not marked namespace: {m.get('kind')!r}")
    check(m.get("exports") == [],
          f"the package exports {m.get('exports')!r}; a re-export is not a "
          f"definition, so its export table must be empty")
    check("Marker" in (m.get("reexports") or {}),
          f"the trait re-export is not recorded: {m.get('reexports')!r}")


def test_a_trait_default_method_is_not_dispatched(tmpdir, _shared):
    """The refusal that must SURVIVE, and must be the SAME one either way.

    A trait default method is not a definition this path can call: dispatch is
    by name on the receiver's own type, and nothing resolves a name to a trait.
    So the call is refused — and it must be refused identically whether the
    trait is in the same file or imported, because "the imported case behaves
    like the local one" is exactly what an empty trie for the imported module
    depends on. If the imported case were waved through, this test sees a build
    where it expects the refusal.
    """
    for label, files in (
            ("same file", {"prog.mojo": TRAIT_DISPATCH_SAME_FILE}),
            ("imported", {"lib.mojo": TRAIT_LIB,
                          "prog.mojo": TRAIT_DISPATCH_IMPORTED})):
        root = os.path.join(tmpdir, "disp_" + label.replace(" ", "_"))
        write_tree(root, files)
        fresh_cas()
        result, _out = build(root, "prog.aout", expect_ok=False)
        text = (result.stderr or result.stdout or "")
        check(result.returncode != 0,
              f"[{label}] a trait default method call BUILT; an empty trie for "
              f"a trait-only module is only correct if such a call is "
              f"unreachable, and this is the call that would make it reachable")
        check("tag" in text,
              f"[{label}] the refusal does not name the method: {text[-400:]}")
        check("method call on a value" in text,
              f"[{label}] the refusal is not the method-call one, so it is "
              f"saying something else: {text[-400:]}")


def test_a_structs_own_method_is_lowered_and_correct(tmpdir, _shared):
    """The positive control, executed and compared with CPython.

    `a_trait_default_method_is_not_dispatched` says a trait's method is not
    reachable. This says the STRUCT's own method is, and computes the right
    answer — so the refusal above is a fact about trait dispatch and not a
    blanket refusal of method calls, which is what would be true if this test
    stopped passing.
    """
    root = os.path.join(tmpdir, "sm")
    write_tree(root, {"prog.mojo": STRUCT_METHOD, "prog.py": STRUCT_METHOD_TWIN})
    fresh_cas()
    _result, out = build(root, "prog.aout")
    require_same_as_cpython(root, out, "prog.py", "arm64")


def test_a_trait_beside_a_function_does_not_hide_the_function(tmpdir,
                                                               _shared):
    """The refusal must not become a blanket exemption.

    A module with a trait AND a concrete function is an ordinary library: the
    function is exported, its trie entry is present, and the importer's call to
    it binds. The trait is why the module is allowed to be a library at all,
    so it must not be a way for a module's FUNCTIONS to stop being exported.
    """
    root = os.path.join(tmpdir, "mixed")
    write_tree(root, {"mixed.mojo": MIXED, "prog.mojo": MIXED_PROG,
                      "prog.py": MIXED_PROG_TWIN})
    fresh_cas()
    _result, out = build(root, "prog.aout")
    require_same_as_cpython(root, out, "prog.py", "arm64")
    m = manifest(module_dylib("mixed"))
    names = [e["name"] for e in m["exports"]]
    check("bump" in names,
          f"the function is not exported beside the trait: {names}")
    check(m.get("kind") != "namespace",
          f"a module WITH a function was marked namespace, which means it was "
          f"built as a library with no code and every call into it is "
          f"unbound: kind={m.get('kind')!r}")


TESTS = [
    ("a trait-only module builds and the importer runs",
     test_a_trait_only_module_builds_and_the_importer_runs),
    ("a trait-only module is a namespace library with an empty trie",
     test_a_trait_only_module_is_a_namespace_library_with_an_empty_trie),
    ("a package that only re-exports traits builds and runs",
     test_a_package_that_only_re_exports_traits_builds_and_runs),
    ("a trait default method is not dispatched",
     test_a_trait_default_method_is_not_dispatched),
    ("a struct's own method is lowered and correct",
     test_a_structs_own_method_is_lowered_and_correct),
    ("a trait beside a function does not hide the function",
     test_a_trait_beside_a_function_does_not_hide_the_function),
]


def main():
    ap = argparse.ArgumentParser(description="__doc__")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if platform.machine() not in ("arm64", "x86_64"):
        print(f"SKIP: formal output is arm64/x86-64 only, host is "
              f"{platform.machine()}")
        return 0

    passed = failed = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        for name, fn in TESTS:
            try:
                fn(tmpdir, None)
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

    print(f"\nformal trait module: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        _drop_cas_home()