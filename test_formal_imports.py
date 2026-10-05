#!/usr/bin/env python3
"""Regression tests for formal import resolution (`import` → dylib → link).

The formal path used to ignore `ImportStmt`/`FromImportStmt` entirely, which
is worse than an error: the calls an import implies were left as references to
symbols nothing defines, so the program BUILT and then died in dyld at launch
with "Symbol not found". These tests pin the replacement behaviour:

  1. an imported module is compiled and linked, and the program runs;
  2. it is compiled IN FULL — a function the program never calls is still in
     the library, compiled and exported, because a module dylib represents a
     source FILE, not the call sites that happened to need it;
  3. a module's identity is the name the importer used, not the file's
     basename — every package resolves to `__init__.mojo`, so deriving the
     qualifier from the path would name them all `_init_`;
  4. cross-module calls carry the dependency's exported spelling, and the
     library records the load commands that let dyld bind them;
  5. dependencies are linked before their dependents;
  6. a cycle terminates and both halves still work;
  7. an import that resolves to nothing is a clean compile error with a
     non-zero exit, not a traceback and not a silently broken binary;
  8. an import that is semantically INERT is not a dependency at all
     (`from __future__ import ...`, and the guarded spellings — a
     `TYPE_CHECKING` block, an `if False:`/`if version_info` arm, a guarded
     `try: import`);
  9. the resolution ORDER is Mojo source > host module > repository `.py`
     sibling > the stdlib loader, and each step of it is pinned by a test that
     goes red if the order inverts — because the failure mode of getting it
     wrong is a program that binds the wrong module and computes the wrong
     answer with nothing to grep for. Inside the first of those steps the name
     AS SPELLED is offered to every search root before the LEAF fallback is
     offered to any, so a dotted import cannot bind a module its own name does
     not spell (`test_the_spelling_outranks_a_nearer_roots_leaf`, and the
     measured stdlib rows behind it).
 10. an import EDGE that binds no name the dependency could publish as one
     boundary symbol needs no library at all, and a module that genuinely has
     no boundary symbol is still REFUSED for every edge that does bind
     something from it — with a message saying which of the ways it has none.
     The decision and its cost are in bugs/FORMAL_known_limits.md §1, and the
     tests at the end of this file pin both the rule and the accuracy of the
     message, because a message that is false about the file sends the reader
     after a construct that is not there.

Invoked directly:
    python3 test_formal_imports.py [-v]
"""
import argparse
import glob
import json
import os
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from exec_budget import RUN_TIMEOUT_S   # noqa: E402

#: How long this process waits for a `Popen` it has just `terminate()`d to be
#: reaped. NOT a per-child budget, and named here so the widened estate check
#: sees a name rather than a bare number and does not have to be told this is
#: deliberate: `exec_budget`'s constants size a COMPILE, a LINK and a RUN of
#: compiled code, and this bounds the wait AFTER a signal — the writer process
#: republishing a library in place, stopped in the `finally` below, whose corpse
#: has to be collected before the case can judge what the 400 runs printed. It
#: is `test_formal_sweep.py`'s `SIGTERM_REAP_S` under the same name, because it
#: is the same wait.
SIGTERM_REAP_S = 60

# The independent Mach-O reader and the CLI driver live in the dylib suite;
# imported rather than copied so a fix to the reader cannot leave a second,
# quietly different one behind.
from test_formal_dylib import (TestFailure, check, parse_macho, read_uleb,
                               run_fire)

# The resolver's own tier table, read rather than a list of names copied here:
# `test_several_unresolvable_imports_are_all_named` picks its two blocker
# modules out of it, and a copied list would keep naming a module that has since
# been answered — which is exactly how that test stopped testing two blockers.
from formal import imports as I

FIRE = os.path.join(HERE, "fire.py")
# Module dylibs are written per ARCHITECTURE (formal/build.py's
# `_resolve_imports`): a dylib is a target-specific image, so an arm64 library
# and an x86-64 library for the same source are two artifacts, not two
# versions of one, and a shared directory keyed by module name alone let the
# second architecture overwrite the first. A test that looks for a built dylib
# therefore has to ask for the architecture it built.
#
# This file also gets a CAS of its OWN, which it must set before `cas` is
# imported, because `fresh_cas()` below deletes the whole module-dylib
# directory. Against the shared `~/.gmojo` that is only safe when this file
# runs alone: under a `-j18` bucket it deletes libraries that a parallel job —
# test_formal_sweep.py's dyld probe builds and then loads one — is holding a
# path to, which is how `formal-sweep` failed only at 9 jobs and passed at 2.
# An isolated home also stops this file reading another tree's dylibs, so a
# test cannot pass on a library it did not build.
_CAS_HOME = tempfile.mkdtemp(prefix="formal_imports_cas_")
os.environ["GMOJO_HOME"] = _CAS_HOME
CAS_IMPORTS_ROOT = os.path.join(_CAS_HOME, "cas", "formal-imports")
import cas  # noqa: E402  — after GMOJO_HOME above, which is what cas reads


def _drop_cas_home():
    shutil.rmtree(_CAS_HOME, ignore_errors=True)


def cas_imports(arch="arm64"):
    return os.path.join(CAS_IMPORTS_ROOT, arch)


def module_dylib(prefix, arch="arm64"):
    """The built library for `prefix`, found by prefix rather than by name.

    A module library's file name is
    `<prefix>.<source-digest>.<compiler-digest>.<arch>.dylib`: the source
    digest is there so two builds of the same module name cannot overwrite each
    other, the COMPILER digest is there because the CAS is shared by every
    checkout on the machine and sibling worktrees routinely sit at different
    commits with byte-identical module sources (measured: five distinct
    `formal/build.py` digests behind one `struct.mojo`), and the arch is there
    so the two architectures cannot either. So the name is only stable up to
    the digests, and every test that wants a library has to look it up.
    Globbing on `<prefix>.*.<arch>.dylib` still pins the convention that
    matters — the arch really is in the name, and it really is the last field —
    while tolerating the digests between.

    **Exactly one** match is required, and that is now a real invariant rather
    than an accident: with the compiler in the key, two checkouts at different
    commits produce two DIFFERENT paths for the same module, so a stale library
    from an earlier commit of this same tree no longer collides with the
    current one — it is simply a second file, and this is what says so.
    """
    import glob
    found = sorted(glob.glob(os.path.join(
        cas_imports(arch), f"{prefix}.*.{arch}.dylib")))
    if not found:
        raise AssertionError(
            f"no module dylib for {prefix!r} under {cas_imports(arch)}")
    if len(found) > 1:
        raise AssertionError(
            f"{prefix!r} has more than one library, which means two different "
            f"sources claimed one name: {found}")
    return found[0]

# A module whose functions are all one int64 in, one int64 out, so every
# exported function can be called the same way from ctypes.
LIB = """\
def helper(x):
  return x + 1


def never_called_by_prog(x):
  return x * 100


def _private(x):
  return x
"""

PKG = """\
from leaf import base
def mid(x):
  return base(x) + 1
"""

LEAF = """\
def base(x):
  return x * 2


def leaf_only(x):
  return x + 1000
"""

PROG = """\
from mylib import helper
def main():
  return helper(41)
"""

CHAIN_PROG = """\
from pkg import mid
def main():
  return mid(20)
"""

CYCLE_A = """\
from b import bfn
def afn(x):
  return bfn(x) + 1
"""

CYCLE_B = """\
from a import afn
def bfn(x):
  return x * 3
"""

CYCLE_PROG = """\
from a import afn
def main():
  return afn(4)
"""


def write_tree(root, files):
    for rel, text in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)


def fresh_cas():
    """Module dylibs are cached by content, so a stale one from an earlier
    run could mask a regression; every test starts from an empty cache."""
    shutil.rmtree(CAS_IMPORTS_ROOT, ignore_errors=True)


def build(root, name, expect_ok=True, arch=None):
    out = os.path.join(root, name)
    argv = ["build", "--formal", "--no-prove", "-o", out]
    if arch:
        argv.append(f"--backend={arch}")
    argv.append(os.path.join(root, name.replace(".aout", ".mojo")))
    result = run_fire(argv, cwd=root)
    if expect_ok:
        check(result.returncode == 0,
              f"build failed: {(result.stderr or result.stdout).strip()[-400:]}")
        check(os.path.isfile(out), f"no executable written at {out}")
    return result, out


def run(out):
    r = subprocess.run([out], capture_output=True, text=True, timeout=RUN_TIMEOUT_S)
    return r.returncode, (r.stderr or r.stdout)


def _build_one(src, out, expect_ok=True):
    """`fire.py build --formal --no-prove` on one EXISTING source file.

    `build` above compiles `<root>/<name>.mojo`, which is the right shape for a
    test that writes its own tree and the wrong one for a file already in this
    repository — the program under test here is a real swept file, and copying
    it to a temp directory would change what the sweep means (its own imports
    resolve relative to where it sits).
    """
    argv = ["build", "--formal", "--no-prove", "-o", out, src]
    result = run_fire(argv, cwd=HERE)
    if expect_ok:
        check(result.returncode == 0,
              f"build failed: {(result.stderr or result.stdout).strip()[-400:]}")
        check(os.path.isfile(out), f"no executable written at {out}")
    return result.returncode, (result.stderr or result.stdout or "")


def manifest(dylib):
    with open(dylib + ".manifest.json") as f:
        return json.load(f)


def test_import_links_and_runs(tmpdir, _shared):
    root = os.path.join(tmpdir, "simple")
    os.makedirs(root)
    write_tree(root, {"mylib/__init__.mojo": LIB, "prog.mojo": PROG})
    fresh_cas()
    _result, out = build(root, "prog.aout")
    check(os.path.basename(out) == "prog.aout", "wrong output name")
    code, err = run(out)
    check(code == 42, f"program returned {code}, expected 42; stderr: {err}")


def test_module_qualified_call_runs(tmpdir, _shared):
    """`import mylib` then `mylib.helper(x)` — the other spelling of an import.

    `PROG` above uses `from mylib import helper`, which is one of the two
    ways to write the same call, and the other one was REFUSED: the callee
    exclusion in `check_module_symbols` is collected by node identity and only
    for a callee that is an `IdentExpr`, so the root of a `MemberExpr` callee
    (`mylib` in `mylib.helper`) was read as a module-level name with no
    storage. The refusal's own message recommended the form it refused
    ("give it a function (a `mylib.fn()` call lowers)").

    Both halves are needed and only measuring them in order shows that. With
    the placement refusal gone, the call then failed on an unresolved symbol,
    because the manifest's flat map is keyed by the BARE name (`helper` — the
    spelling `from mylib import helper` writes) while `_callee_symbol` hands
    the codegen the DOTTED one (`mylib.helper`). That is answered by
    `model.dylib_export_lookup`, which resolves a DOTTED callee from the
    export table of the library built for that module and never from the flat
    map — so `mod.f` cannot bind some other library's `f` either. A test that
    only checked the first half would have traded one refusal for another.

    This is the top-level form; `pkg.sub` is the same call one level down and
    has its own two tests below, because that is where the manifest's key and
    the name a caller writes stop being the same string.
    """
    qualified = ("import mylib\n\n"
                 "def main():\n  return mylib.helper(41)\n")
    root = os.path.join(tmpdir, "qualified_call")
    os.makedirs(root)
    write_tree(root, {"mylib/__init__.mojo": LIB, "prog.mojo": qualified})
    fresh_cas()
    _result, out = build(root, "prog.aout")
    code, err = run(out)
    check(code == 42,
          f"`import mylib` + `mylib.helper(41)` returned {code}, expected 42; "
          f"a module-qualified call is a call through an exported symbol, not "
          f"a read of a module object: {err}")


def test_a_module_name_read_as_a_value_is_still_refused(tmpdir, _shared):
    """The other half of the above, and the one that could have regressed.

    Exempting the root of a `mod.fn()` callee must not exempt a READ of the
    same name elsewhere in the function: a module object genuinely has no
    storage on this path (every formal value lives in a function's own stack
    scratch), so `len(mylib)` is still refused, and that refusal is correct.
    This is the assertion that the fix is scoped to call position rather than
    to the name.
    """
    reads_module = ("import mylib\n\n"
                    "def main():\n  return len(mylib)\n")
    root = os.path.join(tmpdir, "read_module")
    os.makedirs(root)
    write_tree(root, {"mylib/__init__.mojo": LIB, "prog.mojo": reads_module})
    fresh_cas()
    result = run_fire(["build", "--formal", "--no-prove", "-o",
                       os.path.join(root, "prog.aout"),
                       os.path.join(root, "prog.mojo")], cwd=root)
    text = result.stderr + result.stdout
    check(result.returncode != 0,
          "`len(mylib)` built and ran — a read of a module object was "
          "exempted along with the call through it, and a module has no "
          "storage to read")
    check("module-level name" in text,
           f"the refusal must say what is wrong (a module-level name has no "
           f"storage), not name some other construct: {text[-300:]}")


def test_package_submodule_call_runs(tmpdir, _shared):
    """`import pkg.sub` then `pkg.sub.helper(x)` — the same call, one level down.

    The two halves of a module-qualified call both have to agree about WHERE a
    module's name lives, and a package is where they disagree:

      * the name check asks "is this root an imported module?", and the root
        of `pkg.sub.helper` is `pkg` while the only imported name is
        `pkg.sub` — matching for equality refused the spelling a package
        submodule is written with, and the refusal's own remedy sentence
        ("give it a function, a `pkg.fn()` call lowers") recommended it;
      * the manifest keys an export by the module's ABI PREFIX, and a prefix
        is a C identifier, so `pkg.sub`'s exports are keyed `pkg_sub`. The
        emitter looked the qualifier up as written, found nothing, and left
        the call pointing at `pkg.sub.helper` — a symbol nothing defines,
        caught by the bind audit, but only after the whole image was built.

    `os.path.join` is 532 measured call sites in this tree, so this is not a
    corner: it is the form the largest module in the tree is written with.
    """
    qualified = ("import pkg.sub\n\n"
                 "def main():\n  return pkg.sub.helper(41)\n")
    root = os.path.join(tmpdir, "pkg_sub_call")
    os.makedirs(root)
    write_tree(root, {"pkg/__init__.mojo": "def unused(x):\n  return x\n",
                      "pkg/sub.mojo": LIB, "prog.mojo": qualified})
    fresh_cas()
    _result, out = build(root, "prog.aout")
    code, err = run(out)
    check(code == 42,
          f"`import pkg.sub` + `pkg.sub.helper(41)` returned {code}, "
          f"expected 42; a package submodule is a module, under its dotted "
          f"name in the source and its ABI prefix in the manifest: {err}")
    # …and the manifest really does spell it the other way, so this test is
    # testing the normalization rather than agreeing with it.
    m = manifest(module_dylib("pkg_sub"))
    check(any(e["module"] == "pkg_sub" and e["name"] == "helper"
              for e in m["exports"]),
          f"the library does not key its export by the ABI prefix this "
          f"resolution depends on: {m['exports'][:2]}")


def test_package_submodule_unexported_name_is_refused(tmpdir, _shared):
    """The other half of the above, under the same normalization.

    A call to a name the submodule does not export has to be refused HERE,
    naming the module and what it does export, and not emitted as a call
    against a symbol nothing defines. Under the ABI-prefix spelling that is
    one lookup away from being missed: the table is not empty, it is simply
    not the table the qualifier as written names.
    """
    missing = ("import pkg.sub\n\n"
               "def main():\n  return pkg.sub.nosuchfunction(1)\n")
    root = os.path.join(tmpdir, "pkg_sub_missing")
    os.makedirs(root)
    write_tree(root, {"pkg/__init__.mojo": "def unused(x):\n  return x\n",
                      "pkg/sub.mojo": LIB, "prog.mojo": missing})
    fresh_cas()
    result = run_fire(["build", "--formal", "--no-prove", "-o",
                       os.path.join(root, "prog.aout"),
                       os.path.join(root, "prog.mojo")], cwd=root)
    text = result.stderr + result.stdout
    check(result.returncode != 0,
          "`pkg.sub.nosuchfunction(1)` built — the module is linked, so the "
          "call has a table to be missing from and must be a build error")
    check("exports no `nosuchfunction`" in text
          and "pkg.sub" in text and "helper" in text,
          f"the refusal must name the module, the name and what the module "
          f"does export, so a reader is not left to diff two lists: {text[-400:]}")



def test_module_compiled_in_full(tmpdir, _shared):
    """The point of compiling a whole file rather than the referenced
    functions: an unreferenced function must still be there, compiled and
    exported, or the next importer of the same source gets a library that is
    missing half of it."""
    root = os.path.join(tmpdir, "full")
    os.makedirs(root)
    write_tree(root, {"mylib/__init__.mojo": LIB, "prog.mojo": PROG})
    fresh_cas()
    _result, out = build(root, "prog.aout")
    dylib = module_dylib("mylib")
    check(os.path.isfile(dylib), f"no module dylib at {dylib}")
    m = manifest(dylib)
    names = sorted(e["name"] for e in m["exports"])
    check(names == ["helper", "never_called_by_prog"],
          f"module exports {names}; a module dylib represents the whole "
          f"source file, so the uncalled function must be in it too")
    check("_private" not in names,
          f"a `_`-prefixed function was exported: {names}")
    import ctypes
    lib = ctypes.CDLL(dylib)
    never = [e for e in m["exports"] if e["name"] == "never_called_by_prog"][0]
    fn = getattr(lib, never["symbol"])
    fn.restype = ctypes.c_int64
    fn.argtypes = [ctypes.c_int64]
    check(fn(7) == 700,
          f"the uncalled function is in the library but computes {fn(7)}, "
          f"expected 700 — so it was exported without being compiled")
    try:
        getattr(lib, "_private")
        raise TestFailure("dlsym resolved the private _private function")
    except AttributeError:
        pass
    with open(dylib, "rb") as f:
        info = parse_macho(f.read())
    for entry in m["exports"]:
        check("_" + entry["symbol"] in info["exports"],
              f"the trie does not carry the manifest's export "
              f"{entry['symbol']}")


def test_package_identity_is_module_name(tmpdir, _shared):
    """Two packages must not collide on `__init__`."""
    root = os.path.join(tmpdir, "ident")
    os.makedirs(root)
    write_tree(root, {
        "mylib/__init__.mojo": LIB,
        "prog.mojo": PROG,
        "other/__init__.mojo": "def other_fn(x):\n  return x + 5\n",
        "uses_other.mojo": "from other import other_fn\n"
                           "from mylib import helper\n"
                           "def main():\n  return other_fn(helper(1))\n",
    })
    fresh_cas()
    _result, out = build(root, "uses_other.aout")
    code, err = run(out)
    check(code == 7, f"two packages both resolved to one library: returned "
                     f"{code}, expected 7; stderr: {err}")
    for name in (module_dylib("mylib"), module_dylib("other")):
        check(os.path.isfile(os.path.join(cas_imports(), name)),
              f"{name} was not built; a package's identity has to come from "
              f"the module name, since __init__.mojo has no other")


def test_cross_module_call_is_qualified(tmpdir, _shared):
    """A call to a sibling's function must reference that library's exported
    spelling, and the library must carry the load command that lets dyld bind
    it — otherwise the image builds and dies at load with "Symbol not
    found" for a function that plainly exists."""
    root = os.path.join(tmpdir, "qualified")
    os.makedirs(root)
    write_tree(root, {"pkg/__init__.mojo": PKG, "leaf.mojo": LEAF,
                      "prog.mojo": CHAIN_PROG})
    fresh_cas()
    _result, out = build(root, "prog.aout")
    code, err = run(out)
    check(code == 41, f"transitive chain returned {code}, expected 41 "
                      f"(mid(20) = base(20)+1); stderr: {err}")
    pkg = module_dylib("pkg")
    with open(pkg, "rb") as f:
        data = f.read()
    check(b"base" in data, "sanity: the module's code should mention base")
    leaf_sym = [e["symbol"] for e in
                manifest(module_dylib("leaf"))["exports"]
                if e["name"] == "base"][0]
    check(leaf_sym.encode() in data,
          f"pkg.dylib does not reference the leaf export {leaf_sym!r}; a "
          f"cross-module call must use the dependency's exported spelling")
    check(b"_base\x00" not in data.replace(b"_" + leaf_sym.encode() + b"\0", b""),
          "pkg.dylib still carries an unqualified reference to `base`")
    # and the load command that makes the bind possible
    r = subprocess.run(["otool", "-L", pkg], capture_output=True, text=True)
    check(os.path.basename(module_dylib("leaf")) in r.stdout,
          f"pkg.dylib does not link leaf.dylib:\n{r.stdout}")


def test_dependencies_linked_first(tmpdir, _shared):
    root = os.path.join(tmpdir, "order")
    os.makedirs(root)
    write_tree(root, {"pkg/__init__.mojo": PKG, "leaf.mojo": LEAF,
                      "prog.mojo": CHAIN_PROG})
    fresh_cas()
    _result, out = build(root, "prog.aout")
    r = subprocess.run(["otool", "-L", out], capture_output=True, text=True)
    lines = [l for l in r.stdout.splitlines() if "formal-imports" in l]
    check(len(lines) == 2, f"expected both module dylibs on the link line, "
                           f"got {lines}")
    check(os.path.basename(module_dylib("leaf")) in lines[0]
          and os.path.basename(module_dylib("pkg")) in lines[1],
          f"dependencies must be linked before their dependents; got {lines}")


def test_import_cycle_terminates(tmpdir, _shared):
    root = os.path.join(tmpdir, "cycle")
    os.makedirs(root)
    write_tree(root, {"a.mojo": CYCLE_A, "b.mojo": CYCLE_B,
                      "prog.mojo": CYCLE_PROG})
    fresh_cas()
    _result, out = build(root, "prog.aout")
    code, err = run(out)
    check(code == 13, f"a mutual import returned {code}, expected 13 "
                      f"(afn(4) = bfn(4)+1); stderr: {err}")


def test_unresolvable_import_is_a_clean_error(tmpdir, _shared):
    root = os.path.join(tmpdir, "bad")
    os.makedirs(root)
    write_tree(root, {"prog.mojo": "import nonexistent_module_xyz\n"
                                   "def main():\n  return 1\n"})
    fresh_cas()
    result, out = build(root, "prog.aout", expect_ok=False)
    check(result.returncode != 0,
          "an import that resolves to nothing must fail the build; the old "
          "behaviour was to drop it and produce a binary that dies in dyld")
    check(not os.path.isfile(out),
          "an executable was written despite the unresolved import")
    text = (result.stderr or "") + (result.stdout or "")
    check("Traceback" not in text,
          f"an unresolved import should be a clean error, not a traceback:\n"
          f"{text[-400:]}")
    check("nonexistent_module_xyz" in text,
          f"the error should name the module it could not resolve:\n"
          f"{text[-400:]}")


def test_several_unresolvable_imports_are_all_named(tmpdir, _shared):
    """Every blocker in one diagnostic, and the SAME set whatever the order.

    `unresolvable_imports` above raises inside the loop that builds the modules,
    so it reported whichever unresolvable import came first in the statement
    list. The measurement is in
    `“What the admitted contracts did and did NOT move in the sweep”`: fixing
    `subprocess` on eight files moved them from "refused for `subprocess`" to
    "refused for `tempfile`", no file moved out of `not-answerable/host-import`,
    and the per-module breakdown before and after measured two different things
    — which is a diagnostic whose subject is the ORDER of a file's import lines.

    Three assertions, because each of them is a different way the property can
    come back:
      * all three names are in the message (completeness — a reader with three
        modules to remove is told about three);
      * the message is the SAME for both orders (order-independence), which is
        what makes a census drawn from it a measurement rather than a sample of
        how the file is written;
      * the resolvable import is NOT named as a blocker, so "all of them" cannot
        be satisfied by listing every import the file has.

    The single-module wording is pinned by the test above, and it is a separate
    function rather than a branch inside this one: a `refuse:` case in
    `test_formal_run.py`, a needle in `test_formal_sweep_truth.py` and the
    chain the sweep peels are all written against that sentence, and "several"
    must not cost the single case its wording.

    **THE TWO UNRESOLVABLE NAMES ARE CHOSEN FROM WHAT IS STILL UNREACHABLE,
    not written into the fixture**, and the history is why: they were
    `tempfile` and `glob`, and `tempfile` stopped being a blocker on 2026-10-03
    when `formal/hostmods/tempfile.mojo` landed — a host module with a source
    resolves before the tier lists are ever consulted — so a fixture naming it
    went on passing as a ONE-module test with a two-module name in it. Handing
    the replacement to `zlib` fixed that instance and left the same trap armed
    for the next module that lands, so the pair is derived from
    `HOST_UNREACHABLE` instead and the `len(blockers) == 2` check below is what
    says the derivation still has two members to give. It reads `['atexit',
    'builtins']` on this tree, both host modules with no source and both real
    rows in the sweep's host ranking.
    """
    root = os.path.join(tmpdir, "many")
    os.makedirs(root)
    # The two blocker names are CHOSEN, not fixed, and they were `tempfile` and
    # `glob` until 2026-10-03, when `formal/hostmods/tempfile.mojo` landed and
    # `tempfile` stopped being a blocker.  A test that kept it would still have
    # passed — `glob` is still named — while quietly testing ONE blocker instead
    # of two, which is the property the two orderings exist to check.  So the
    # pair is taken from what is still unreachable, which is the only list that
    # cannot go stale the same way.
    blockers = sorted(I.HOST_UNREACHABLE - {"asyncio", "socket"})[:2]
    check(len(blockers) == 2 and "sys" not in blockers,
          f"this test needs two names that are still unresolvable host modules "
          f"and got {blockers!r} out of HOST_UNREACHABLE. Either fewer than two "
          f"are unreachable any more — in which case this property has nothing "
          f"left to test and the test should go with them — or the pair has to "
          f"be chosen by hand and the choice written down here.")
    one, two = blockers
    orderings = {
        "alpha": f"import {one}\nimport {two}\nimport sys\n",
        "omega": f"import {two}\nimport {one}\n",
    }
    for tag, imports in orderings.items():
        write_tree(root, {f"{tag}.mojo":
                          imports + "def main():\n  return 1\n"})
    fresh_cas()
    texts = {}
    for tag in orderings:
        result, out = build(root, f"{tag}.aout", expect_ok=False)
        check(result.returncode != 0,
              f"{tag}: an unresolvable import must fail the build")
        check(not os.path.isfile(out),
              f"{tag}: an executable was written despite unresolved imports")
        text = (result.stderr or "") + (result.stdout or "")
        check("Traceback" not in text,
              f"{tag}: an unresolved import should be a clean error:\n"
              f"{text[-400:]}")
        for mod in blockers:
            check(mod in text,
                  f"{tag}: the diagnostic names {mod!r} nowhere, so fixing it "
                  f"only reveals the next one:\n{text[-400:]}")
        check("'sys'" not in text,
              f"{tag}: the message lists an import that RESOLVES "
              f"(formal/hostmods/sys.mojo), so \"every blocker\" has become "
              f"\"every import\":\n{text[-400:]}")
        texts[tag] = text
    # The two files differ only in the order of two import lines, so the
    # sentences have to be identical once the file's own name is set aside —
    # and once the NAMES are set aside too, since `omega` says the two in the
    # other order and the sentence has to be the same text either way.
    same = texts["alpha"].replace("alpha", "F")
    other = texts["omega"].replace("omega", "F")
    check(same == other,
          "the same file with its import lines in the other order produced a "
          f"different diagnostic:\n  {same.strip()[-300:]}\n  "
          f"{other.strip()[-300:]}")


def test_no_import_needs_no_dylib(tmpdir, _shared):
    root = os.path.join(tmpdir, "solo")
    os.makedirs(root)
    write_tree(root, {"prog.mojo": "def main():\n  return 7\n"})
    fresh_cas()
    _result, out = build(root, "prog.aout")
    code, err = run(out)
    check(code == 7, f"returned {code}, expected 7; stderr: {err}")
    check(not os.path.isdir(cas_imports()) or
          not os.listdir(cas_imports()),
          "a program with no imports built module dylibs anyway")


def test_a_module_dylib_is_published_only_signed(tmpdir, _shared):
    """The shared path never holds the unsigned library `codesign` replaces.

    `compile_formal_dylib` writes a module library and then runs `codesign -s -`
    as a SEPARATE PROCESS which rewrites the same file in place to append
    `LC_CODE_SIGNATURE`. Between the write and the end of that subprocess the
    path holds a complete but UNSIGNED Mach-O, and the two versions are very
    different sizes — 49 304 bytes as the linker writes it, 67 680 after
    `codesign`, on the same library. That path is not private: it is the shared
    CAS directory every worktree on the machine writes, and an ALREADY-LINKED
    image loads it at RUN time, taking no lock. So one build republishing a
    module while another's program started produced, in the wild:

        dyld[2165]: Library not loaded: …/struct.6cd3c815d2e8.arm64.dylib
          Referenced from: … cs3.bin
          Reason: tried: '…' (missing code signature in …)
        child exit -6

    — a program that built, linked and was right, refused by the loader with a
    message naming a library and saying nothing about a concurrent build. That
    is the shape of a thousand "flaky" test reports, and it cannot be
    `expect=`-marked away.

    The fix is `formal/build.py::_publish_signed_image`: the write and the
    `codesign` happen in a subdirectory of the target's own directory holding
    the SAME BASENAME (the basename is part of the artifact's identity —
    `@rpath/<basename>` is baked into `LC_ID_DYLIB` and into the load command of
    everything that links it), and `os.replace` publishes it whole. Same tree,
    so the replace is atomic. It is ONE primitive for the program, the library
    and the module dylib, rather than a second publish path in
    `formal/imports.py`, which is where the module dylib's own builder would
    otherwise have had to reimplement it.

    What is asserted, and it is asserted from INSIDE the window rather than by
    racing it, because a polling observer would pass by luck on an idle machine
    and that is exactly how this survived:

      * the observation is taken while `_ad_hoc_sign` is running, which is the
        instant the unsigned bytes exist;
      * every `.dylib` visible at the published directory at that instant is
        signed — which is what makes "the published path is not the path being
        signed" an OBSERVED property rather than a claim about the code;
      * the published file afterwards is signed, its install name is its own
        basename (the identity a staging FILE would have broken), its manifest is
        beside it AND its manifest's `dylib`/`load_path` name the published
        library rather than the staging directory the bytes came from, and no
        staging directory is left behind.
    """
    import formal.build as FB
    from formal import imports as FI

    root = os.path.join(tmpdir, "signwin")
    os.makedirs(root)
    write_tree(root, {"mylib/__init__.mojo": LIB})
    out_dir = os.path.join(tmpdir, "libs")
    os.makedirs(out_dir)
    fresh_cas()
    FI._BUILT.clear()

    def _published():
        """The libraries a RUNNING image could load from `out_dir` right now."""
        return sorted(f for f in os.listdir(out_dir)
                      if f.endswith(".dylib") or f.endswith(".dylib.lock"))

    def _signed(path):
        r = subprocess.run(["codesign", "-v", path], capture_output=True)
        return r.returncode == 0, (r.stderr or b"").decode("utf-8", "replace")

    observations = []

    def _spy_sign(path, *a, **k):
        # The moment the unsigned bytes exist. `path` is what is about to be
        # signed; everything already in `out_dir` is what another process's
        # running image would find there instead.
        seen = _published()
        observations.append((path, seen, [_signed(os.path.join(out_dir, f))
                                          for f in seen if f.endswith(".dylib")]))
        return real_sign(path, *a, **k)

    real_sign = FB._ad_hoc_sign
    FB._ad_hoc_sign = _spy_sign
    try:
        out = FI.build_module_dylib(
            "mylib", os.path.join(root, "mylib", "__init__.mojo"),
            out_dir, "arm64")
    finally:
        FB._ad_hoc_sign = real_sign

    check(observations, "the build never signed anything, so nothing was "
                        "observed: this test needs the window to be open")
    for path, seen, checks in observations:
        check(path != os.path.join(out_dir, os.path.basename(path)),
              f"codesign was handed {path!r}, which IS the published path: the "
              f"build wrote the library where a running image loads it and is "
              f"now signing it in place, so every concurrent reader can catch "
              f"the unsigned half (formal/build.py's _publish_signed_image)")
        for name, (ok, why) in zip([f for f in seen if f.endswith(".dylib")],
                                   checks):
            check(ok, f"while codesign was signing, {name!r} was already at "
                      f"the published path and is NOT a valid signed image "
                      f"({why.strip()}): a running image that loaded it there "
                      f"would die with 'missing code signature'")

    check(os.path.isfile(out), f"the library was not published at {out}")
    ok, why = _signed(out)
    check(ok, f"the published library is not signed: {why.strip()}")
    base = os.path.basename(out)
    info = subprocess.run(["otool", "-l", out], capture_output=True,
                          text=True).stdout
    want = f"@rpath/{base}"
    check(want in info,
          f"the published library's load commands do not name it {want!r}, so "
          f"the staging changed the install name — and a dylib's install name "
          f"is baked into the load command of everything that links it:\n"
          f"{info[-400:]}")
    check(os.path.isfile(out + ".manifest.json"),
          "the manifest was not published beside the library, so every reader "
          "(the consumer's own manifest walk, external_declarations) finds a "
          "library with no exports")
    # The manifest's OWN two path fields name the published library, and this is
    # the hazard a staging directory created: `write_dylib_manifest` records
    # `dylib` and `load_path` as `abspath` of the output it was handed, and
    # `load_path` is what the executable puts in its own `LC_LOAD_DYLIB`. A
    # manifest published from inside the staging directory therefore names a
    # directory the publish then deletes, and the program that reads it links
    # against a path that does not exist — which is exactly what happened when
    # `formal/imports.py` owned its own staging publish. The build runs at the
    # published path and only the BYTES are staged, so this holds by
    # construction; it is asserted because "by construction" is what a
    # refactor takes away.
    payload = manifest(out)
    for field in ("dylib", "load_path"):
        check(os.path.abspath(payload.get(field) or "") == os.path.abspath(out),
              f"the manifest's {field} is {payload.get(field)!r}, not the "
              f"published library {out!r}; a consumer links against that path, "
              f"and if it named a staging directory it was deleted before the "
              f"link ran")
    leftovers = [f for f in os.listdir(out_dir) if f.startswith(".stage")]
    check(not leftovers,
          f"the staging directory was left behind: {leftovers}")


# ── the resolution rules ─────────────────────────────────────────────────────
# The four tests below pin ONE ordering (see formal/imports.py's
# `resolve_module_path`): Mojo source > host module > repository `.py`
# sibling > module_loader. Each of those is a decision that can be silently
# got wrong, and "silently" is the failure that matters — a name that binds to
# the wrong file builds and computes the wrong answer, with nothing to grep
# for. So each test is written so that reordering the passes makes it RED, not
# merely different.


def test_future_import_is_inert(tmpdir, _shared):
    """`from __future__ import annotations` is a declaration, not a dependency.

    It binds no value and emits no code, so there is nothing for the link step
    to provide and nothing to compile. Demanding a source file for it made 32
    real files in this repo fail with "not a stdlib or sibling module, and no
    such file exists" — a name nobody is looking for, reported in place of the
    `import os` that is the actual reason those files cannot be built."""
    root = os.path.join(tmpdir, "future")
    os.makedirs(root)
    write_tree(root, {"prog.mojo":
                      "from __future__ import annotations\n"
                      "def main():\n  return 11\n"})
    fresh_cas()
    _result, out = build(root, "prog.aout")
    code, err = run(out)
    check(code == 11, f"returned {code}, expected 11; stderr: {err}")
    check(not os.path.isdir(cas_imports()) or not os.listdir(cas_imports()),
          "a __future__ import built a module dylib; it is inert and must not "
          "produce a dependency")


def test_guarded_imports_stay_inert(tmpdir, _shared):
    """The rest of the inert family: a name that is not unconditionally
    required is not a dependency.

    `TYPE_CHECKING` blocks, `if False:` and `if sys.version_info` arms and
    guarded `try: import x except ImportError:` are all inert for the same
    reason `__future__` is. They need no list of their own because they are
    all NESTED inside an `if`/`try` and `imported_modules` descends into a
    function body but stops at a conditional. That is load-bearing rather than
    incidental — a resolver that descended into a conditional would make every
    one of these a hard dependency — so it is pinned here at the collector and
    end to end.

    The FUNCTION-LOCAL half is here for the same reason, and it is the half a
    reader would most expect to be missed: `imported_modules` now walks INTO a
    `def` body, so a guarded import inside one has to be shown to stay inert
    too. Without this case the walk could descend into `If`/`Try` bodies as
    well and every assertion below would still pass."""
    from formal.imports import imported_modules
    src = ("from __future__ import annotations\n"
           "import os\n"
           "if False:\n  import nonexistent_guard_false\n"
           "if sys.version_info >= (3, 99):\n"
           "  import nonexistent_guard_version\n"
           "try:\n  import nonexistent_guard_try\n"
           "except ImportError:\n  nonexistent_guard_try = None\n"
           # …and the same three inside a function body, which the walk now
           # reaches and must still treat as inert.
           "def f():\n"
           "  import real_function_local\n"
           "  if False:\n    import nonexistent_guard_in_fn\n"
           "  try:\n    import nonexistent_guard_try_in_fn\n"
           "  except ImportError:\n    nonexistent_guard_try_in_fn = None\n")
    import fire_compiler as F
    stmts = F.Parser(F.py_tokenize(src)).with_filename("g.py").parse_module()
    got = imported_modules(stmts)
    # `real_function_local` IS a dependency — an unconditional statement of the
    # function's block, and the callee it binds is on the link line — while
    # every guarded one is not, at module level and inside the function alike.
    check(got == ["os", "real_function_local"],
          f"imported_modules returned {got}; a guarded import is inert at "
          f"module level AND inside a function body, while an unconditional "
          f"function-local import is a real dependency — only `os` and "
          f"`real_function_local` are")
    root = os.path.join(tmpdir, "guarded")
    os.makedirs(root)
    # The probe is the program's OUTPUT, and it prints from `main` — which the
    # module body calls, because that is what a real file of this shape does.
    #
    # The exit code used to be the probe, and it was measuring the wrong thing
    # twice over. It was 13 because the formal entry point called `main` for a
    # module whose body did not: `formal/build.py:_module_body_function` now
    # runs the body, and a body that does not call `main` does not run it, so
    # the process exits 0 — which is what CPython does for the same file
    # (`main()` at file level returns into nothing). That shift is
    # `FORMAL_toplevel_statements_dropped` being fixed, not a
    # regression, and asserting 13 would have pinned the silent drop back in
    # place. What this test is actually about is INERTNESS: the guarded import
    # must not become a dependency, so the build has to succeed at all and the
    # body has to have run. Both are visible in what the program prints.
    write_tree(root, {"prog.mojo":
                      "if False:\n  import nonexistent_guard_false\n"
                      "def guarded():\n"
                      "  if False:\n    import nonexistent_guard_in_fn\n"
                      "def main():\n  guarded()\n"
                      "  printf(\"guarded-import-inert\\n\")\n"
                      "main()\n"})
    fresh_cas()
    _result, out = build(root, "prog.aout")
    code, out_text = run(out)
    check("guarded-import-inert" in out_text,
          f"the guarded import was not inert: the body did not run "
          f"(exit {code}, output {out_text!r}). A non-inert resolver would "
          f"have failed the build on `nonexistent_guard_false` instead.")


def test_a_function_local_import_is_a_dependency(tmpdir, _shared):
    """`import X` inside a function body is on the link line, and the file is
    refused as an IMPORT problem rather than as a name-placement one.

    The old behaviour was not a missing refusal but a MISDIRECTED one.
    `test_runtime_header_scan.py` — the one file in the 623-file x86-64 sweep
    whose terminal refusal was a nested import read as a value — was reported
    as

        exports: 'reflect' has no home: this module declares no module-level
        name by that spelling, and the reading function declares no local or
    parameter by it either. This path places a name in a register or a spill
    slot allocated for THIS function […]

    which is false in a way a reader cannot check: `reflect` IS a module-level
    name, of ANOTHER module, and the walk asked the wrong question because the
    name it never found is the answer. A reader sent to the register allocator
    for a fact about the import graph is the cost this pins shut.

    Three things are asserted, and each is a different property:

      * the file is refused (it is — `reflect` reaches `importlib`, a host
        module), so this is not a case of the refusal being removed;
      * the message names the IMPORT, which is the diagnosis; and
      * the message does NOT claim the name has no home, because that is the
        sentence that was false about the file.

    The collector is asserted directly as well, since the end-to-end half can
    only observe this one file's particular chain."""
    from formal.imports import imported_modules
    import fire_compiler as F
    src = ("def exports(h):\n"
           "  import reflect\n"
           "  return reflect.collect_runtime_exports_h(h)\n")
    stmts = F.Parser(F.py_tokenize(src)).with_filename("g.py").parse_module()
    got = imported_modules(stmts)
    check(got == ["reflect"],
          f"imported_modules returned {got} for a function-local import; a "
          f"module the code cannot run without is on the link line whether the "
          f"import is written at column 0 or in a body")

    rc, text = _build_one(os.path.join(HERE, "test_runtime_header_scan.py"),
                           os.path.join(tmpdir, "trhs.aout"),
                           expect_ok=False)
    check(rc != 0,
          "test_runtime_header_scan.py is still refused — its `reflect` chain "
          "reaches `importlib`, which is a host module, so this is not a case "
          "of the refusal being removed: it BUILT")
    check("imports 'reflect'" in text,
          "the refusal names the import, which is the whole diagnosis; the "
          f"message does not mention the import: {text.strip()[-400:]}")
    check("has no home" not in text,
          "the refusal no longer claims `reflect` has no home — it is a "
          "module-level name of another module, and that sentence sent the "
          "reader to the register allocator for a fact about the import "
          f"graph; it is still there: {text.strip()[-400:]}")


# The bound this case asserts, and why it is a bound rather than a stopwatch.
# Measured 2026-10-03 on this tree: `bindings.mojo` builds (as a REFUSAL, in
# 3.2 s) on arm64 and on x86-64. Measured 2026-10-02, before the import chain
# was walked in dependency order: the same build never terminated — five
# workers' copies of it were found still running, the oldest 1 day 15 hours,
# each at about 55% of a core, and `tools/control.py guard` had to be given a
# 120-minute kill for `fire.py build` because of it. So the number here is three
# orders of magnitude below the failure and 40x below the guard: it is not a
# performance budget, it is the assertion that the file is CLASSIFIED rather
# than still converging, and it is here because a build that never terminates is
# the one outcome the sweep has no verdict for.
BOUNDED_BUILD_S = 120


class _Skip(Exception):
    """A case that cannot run HERE, reported and counted rather than failed.

    One case needs it and it is this one: the stdlib is a sibling CHECKOUT, so
    a tree without it has nothing to measure, and failing in that case would
    make the suite red for a fact about the machine rather than about the
    compiler.  A skip that is silent is the failure mode CLAUDE.md warns about
    for an `expect=` marker, so it prints its reason and is counted in the
    tally — see `main`'s `SKIP  <name>` line.
    """


def _stdlib_dir():
    """The swept stdlib's root, or None when there is no checkout beside us."""
    try:
        from module_loader import STDLIB_PATH
    except Exception:
        return None
    std = os.path.join(STDLIB_PATH, "std") if STDLIB_PATH else None
    return std if std and os.path.isdir(std) else None


def test_a_swept_stdlib_file_is_classified_in_a_bounded_time(tmpdir, _shared):
    """The largest swept file is a build that TERMINATES, with a verdict.

    `std/python/bindings.mojo` is 1,997 lines and the deepest import closure in
    the sweep, and it is here because it used to be the one file whose build did
    not come back at all: five workers' `fire.py build --formal --no-prove`
    runs against it were found still going, the oldest a day and a half, each
    burning about 55% of a core, and two `test_formal_math.py combperm` runs
    were at 9-10 hours beside them. None of those were Lean — every one of them
    was `--no-prove` — so it was a non-converging pass over the import closure
    in this tier, and the only instrument that could have said so was the guard
    that was added afterwards to kill it.

    What is asserted here is the property that makes the sweep able to report
    the file at all, and it is deliberately NOT "this file is refused": a
    refusal is today's answer, a build would be a better one, and pinning
    either would turn a future improvement into a test failure.  The three
    outcomes that pass are a build that produced an image, a non-zero exit
    whose message names the file and is not a traceback, and nothing else —
    a timeout, a kill, or a traceback all fail, and each of those is the state
    the sweep cannot classify.
    """
    stdlib = _stdlib_dir()
    if stdlib is None:
        raise _Skip("no stdlib checkout beside this tree, so there is no swept "
                    "file to build")
    src = os.path.join(stdlib, "python", "bindings.mojo")
    check(os.path.isfile(src),
          f"the stdlib checkout at {stdlib} has no python/bindings.mojo, so "
          f"this case is not measuring the file it claims to measure")
    for arch in ("arm64", "x86_64"):
        out = os.path.join(tmpdir, f"bindings.{arch}.aout")
        argv = ["build", "--formal", "--no-prove", f"--backend={arch}",
                "-o", out, src]
        started = time.monotonic()
        try:
            result = run_fire(argv, cwd=HERE)
        except subprocess.TimeoutExpired:
            raise TestFailure(
                f"[{arch}] {src} did not finish within run_fire's own timeout "
                f"— the non-converging build is back, or is close enough to it "
                f"that the shared 600 s bound is what stops it") from None
        took = time.monotonic() - started
        text = result.stderr or result.stdout or ""
        check(took <= BOUNDED_BUILD_S,
              f"[{arch}] {src} took {took:.0f}s, over this case's "
              f"{BOUNDED_BUILD_S}s bound. It used not to finish at all, and "
              f"the two hanging commands in the report were one per "
              f"architecture, so a per-architecture bound is the only one that "
              f"could have told them apart: a build that takes minutes here is "
              f"a pass that has started to converge again, and it is worth "
              f"knowing before it is another day and a half")
        check("Traceback (most recent call last)" not in text,
              f"[{arch}] {src} raised rather than being classified: "
              f"{text.strip()[-600:]}")
        if result.returncode == 0:
            check(os.path.isfile(out),
                  f"[{arch}] {src} exited 0 and wrote no image at {out}")
            continue
        check("bindings.mojo" in text,
              f"[{arch}] {src} was refused without naming itself, so a reader "
              f"has no way to tell which of its imports the refusal is about: "
              f"{text.strip()[-400:]}")


def test_widening_the_imported_list_widens_nothing_else(tmpdir, _shared):
    """The gate `check_module_symbols` documents, exercised.

    Its own comment is explicit that it is "GATED on the root naming an
    imported module", and that the gate is what makes admitting a dotted callee
    safe — so widening the imported list widens what that gate admits, and
    that is the one risk in collecting a function-local import.

    What has to keep working is the method call on a VALUE whose spelling is
    the same as a module reference. `import os` binds the name `os`; so does a
    local variable, and `os.join(x)` on the second is a method call while on the
    first it is `os.path.join`. The gate tells them apart by asking whether the
    root names an imported module, and a program where a LOCAL shadows one is
    the case where getting it backwards computes a plausible wrong number
    instead of failing.

    So the requirement here is not that these are refused — `xs.append` lowers
    and should — but that each one runs and answers what the source says. A
    gate that over-refused would be a coverage bug; a gate that under-refused
    would be a wrong-answer bug, and only RUNNING the image tells the two
    apart. The programs therefore return a value the test computes, and the
    exit status is compared with it.

    The value `n` the entry function receives is MEASURED rather than written
    down — the formal entry point passes 10, and a test that hard-coded it
    would be asserting a fact about the harness rather than about the gate. A
    program that returns `n` unchanged measures it."""
    entry_root = os.path.join(tmpdir, "entry")
    os.makedirs(entry_root)
    write_tree(entry_root, {"prog.mojo":
                            "def main(n: Int) -> Int:\n  return n\n"})
    fresh_cas()
    _r, entry_out = build(entry_root, "prog.aout")
    n_at_entry = run(entry_out)[0]
    check(n_at_entry == 10,
          f"the entry function receives 10 (measured, not assumed); it got "
          f"{n_at_entry}, so every expected value below is wrong")
    cases = {
        # A LOCAL named `os` with `os` imported: `os` here is the local's
        # word, and a dotted callee rooted at it is the local's method.  The
        # answer uses `os` twice, so a lowering that read the MODULE would not
        # merely differ — it would have no storage to read.
        "local_shadows_imported_name": (
            "import os\n"
            "def main(n: Int) -> Int:\n"
            "  var os = 40\n"
            "  return os + n\n", 40 + n_at_entry),
        # A method call on a value, with nothing imported at all — so the gate
        # has no imported name to admit and `xs` can only be a value. The
        # count after the append is what says the method lowered as a method.
        "value_method_no_import": (
            "def main(n: Int) -> Int:\n"
            "  var xs = [1, 2, 3]\n"
            "  xs.append(4)\n"
            "  return len(xs)\n", 4),
        # A struct whose NAME is also imported. `Pair()` is a construction of
        # this module's struct; a gate that treated the root as a module
        # reference would look for a `Pair` in the imported package. The
        # struct is TWO fields, so it is a frame and the field reads are real
        # loads — a construction that quietly produced a frame address would
        # answer with an address here.
        "struct_named_like_imported_module": (
            "import struct\n"
            "struct Pair:\n"
            "  var a: Int\n"
            "  var b: Int\n"
            "def main(n: Int) -> Int:\n"
            "  var p = Pair()\n"
            "  p.a = n\n"
            "  return p.a + p.b\n", n_at_entry),
    }
    for name, (source, want) in cases.items():
        root = os.path.join(tmpdir, name)
        os.makedirs(root)
        write_tree(root, {"prog.mojo": source})
        fresh_cas()
        _result, out = build(root, "prog.aout")
        if not os.path.isfile(out):
            check(False, f"{name} builds")
            continue
        code, text = run(out)
        check(code == want,
              f"{name} runs and returns what the source says ({want}); it "
              f"returned {code}, output {text!r}")


def test_repository_sibling_resolves(tmpdir, _shared):
    """This repository is the source the formal path compiles, so a program
    importing a sibling has to be able to FIND it.

    Every file in the repo that does `import fire_compiler` was reported as
    importing "not a stdlib or sibling module, and no such file exists" — a
    statement that is simply false about a file sitting in the same tree."""
    root = os.path.join(tmpdir, "sibling")
    os.makedirs(root)
    write_tree(root, {
        "sibmod.py": "def bump(x):\n  return x + 2\n",
        "prog.mojo": "from sibmod import bump\ndef main():\n  return bump(40)\n",
    })
    fresh_cas()
    _result, out = build(root, "prog.aout")
    code, err = run(out)
    check(code == 42, f"returned {code}, expected 42; stderr: {err}")
    dylib = module_dylib("sibmod")
    check(os.path.isfile(dylib),
          f"the sibling was found but no dylib was built for it at {dylib}")


def test_package_relative_dotted_import_resolves(tmpdir, _shared):
    """A dotted import of a sibling INSIDE the same package.

    This is the shape `formal/x86_64_codegen.py`'s `import formal.types` has:
    the project root is the file's own directory, so the full dotted path
    spells to `formal/formal/types.py` and finds nothing, and the name
    resolves through the leaf instead — `types.py`, in the very directory the
    import was written in."""
    root = os.path.join(tmpdir, "pkgrel")
    os.makedirs(root)
    write_tree(root, {
        "sub/types.py": "def base(x):\n  return x * 2\n",
        "sub/user.mojo": ("from sub.types import base\n"
                          "def main():\n  return base(21)\n"),
    })
    fresh_cas()
    _result, out = build(os.path.join(root, "sub"), "user.aout")
    code, err = run(out)
    check(code == 42, f"returned {code}, expected 42; stderr: {err}")


def test_the_spelling_outranks_a_nearer_roots_leaf(tmpdir, _shared):
    """A dotted name binds to what it SPELLS, never to a nearer root's leaf.

    `resolve_module_path` walks its roots nearest-first and, at each one,
    offered the name as spelled and then the name's LEAF.  So the leaf of one
    name could be preferred over the spelling of another, decided by nothing but
    how deep the IMPORTER sat — which is not a fact about the import.  Measured
    over the stdlib on the tree before the fix, 31 bindings in 252 files went to
    a module other than the one they named, and two of them are the clearest
    possible statement of it: `std/sys/info.mojo` and `std/_gpu/host/info.mojo`
    each import the other and each got THEMSELVES.  (Both are rows in
    `test_a_dotted_stdlib_import_resolves_to_the_module_it_names` below.)

    The tree here is that shape with the numbers replaced, so the two candidate
    answers are DIFFERENT and the program's exit code says which one it got:

        a/mod/__init__.mojo        what the LEAF `mod` finds one root nearer
                                   — returns 99
        pkg/sub/mod.mojo           what `pkg.sub.mod` SPELLS — returns 10
        pkg/sub/__init__.mojo      …so `mod` is a module of a package
        a/b/prog.mojo              `from pkg.sub.mod import value`

    `a/b`, `a` and the project root are all search roots for `a/b/prog.mojo`
    (the walk in `_search_roots` ascends from the importer), so the leaf was
    offered at `<root>/a` before the spelling was offered at `<root>`.  It used
    to be taken there, and the program printed 99.  `pkg/sub/mod.mojo` is a
    `.mojo` and not a package because within ONE root a module beats a package
    (`pkg/sub/mod.mojo` before `pkg/sub/mod/__init__.mojo`), which is a
    different rule and is not what this case is about."""
    root = os.path.join(tmpdir, "spelling")
    os.makedirs(root)
    write_tree(root, {
        "pkg/__init__.mojo": "def own():\n  return 1\n",
        "pkg/sub/__init__.mojo": "def own():\n  return 2\n",
        "pkg/sub/mod.mojo": "def value():\n  return 10\n",
        "a/mod/__init__.mojo": "def value():\n  return 99\n",
        "a/b/prog.mojo": ("from pkg.sub.mod import value\n"
                          "def main():\n  return value()\n"),
    })
    fresh_cas()
    got = I.resolve_module_path("pkg.sub.mod",
                                relative_to=os.path.join(root, "a", "b",
                                                         "prog.mojo"))
    check(got is not None
          and os.path.abspath(got) == os.path.abspath(
              os.path.join(root, "pkg", "sub", "mod.mojo")),
          f"`pkg.sub.mod` from a/b/prog.mojo resolved to {got!r}; the name "
          f"spells pkg/sub/mod.mojo, and a nearer root's leaf is not allowed "
          f"to answer for it")
    _result, out = build(os.path.join(root, "a", "b"), "prog.aout")
    code, err = run(out)
    check(code == 10,
          f"returned {code}, expected 10 (pkg/sub/mod.mojo); stderr: {err}. "
          f"99 is the leaf `mod/` one root nearer, and a program that imported "
          f"`pkg.sub.mod` and computed 99 is a wrong answer with nothing on "
          f"the link line to catch it")


def test_a_dotted_stdlib_import_resolves_to_the_module_it_names(tmpdir,
                                                                _shared):
    """Every measured stdlib binding that the leaf fallback got wrong.

    The synthetic case above pins the RULE; this pins the CASES it was measured
    on, because a rule that is right and a tree that has moved are different
    facts and this is the one that says whether the rule still has anything to
    do.  Each row is (the importing file, the name it writes, the file the name
    spells); the whole stdlib is checked, so a NEW instance of the same shape
    fails here too rather than waiting for the next sweep to find it.

    Skipped, with the reason printed and counted, when there is no stdlib
    checkout beside this tree — see `_stdlib_dir` and `_Skip`."""
    stdlib = _stdlib_dir()
    if stdlib is None:
        raise _Skip("no stdlib checkout beside this tree, so there is no swept "
                    "file whose imports can be read")
    cases = [
        # A sibling package at `<stdlib>/std` captured the leaf. The three
        # files are the measured `std.sys.compile` rows.
        ("collections/_asan_annotations.mojo", "std.sys.compile",
         "sys/compile.mojo"),
        ("builtin/_startup.mojo", "std.sys.compile", "sys/compile.mojo"),
        ("testing/assert_aborts.mojo", "std.sys.compile", "sys/compile.mojo"),
        # A pair of modules that each import the other and each got themselves:
        # the leaf matched the importer's OWN file.
        ("_gpu/host/info.mojo", "std.sys.info", "sys/info.mojo"),
        ("sys/info.mojo", "std._gpu.host.info", "_gpu/host/info.mojo"),
        ("_gpu/intrinsics.mojo", "std.sys.intrinsics", "sys/intrinsics.mojo"),
        ("_gpu/primitives/id.mojo", "std.sys.intrinsics",
         "sys/intrinsics.mojo"),
        ("_gpu/primitives/warp.mojo", "std.sys.intrinsics",
         "sys/intrinsics.mojo"),
        # A package and the module beside it, where the leaf found the PACKAGE
        # for a name that spells the module (`std.math.math`).
        ("complex/complex.mojo", "std.math.math", "math/math.mojo"),
        ("simd.mojo", "std.math.math", "math/math.mojo"),
        ("_plugin/_trait.mojo", "std.math.math", "math/math.mojo"),
        ("builtin/debug_assert.mojo", "std.io.io", "io/io.mojo"),
        ("format/_utils.mojo", "std.io.io", "io/io.mojo"),
        ("builtin/_stubs.mojo", "std.os.os", "os/os.mojo"),
        ("os/fstat.mojo", "std.time.time", "time/time.mojo"),
        ("os/_macos.mojo", "std.time.time", "time/time.mojo"),
        ("builtin/string_literal.mojo", "std.collections.string.format",
         "collections/string/format.mojo"),
        # …and the other direction: a module that spells a PACKAGE and got the
        # module beside it instead.
        ("math/uutils.mojo", "std.math", "math/__init__.mojo"),
        # A leaf that is the IMPORTER'S OWN FILE: the degenerate case of the
        # same shape, and the one a reader finds least believable.
        # `std/_gpu/_utils.mojo` and `std/format/_utils.mojo` are both
        # `_utils.mojo`, so `from std.format._utils import FormatStruct` names
        # the far module while the NEAREST search root holds a file with the
        # very basename. Asked per root, this file was its own answer — so the
        # self-resolution is the row worth naming of the two the ordering can
        # get wrong, and the sibling rows above are the other one.
        ("_gpu/_utils.mojo", "std.format._utils", "format/_utils.mojo"),
        ("memory/alloc.mojo", "std.memory", "memory/__init__.mojo"),
        ("memory/pointer.mojo", "std.memory", "memory/__init__.mojo"),
        ("benchmark/bencher.mojo", "std.benchmark", "benchmark/__init__.mojo"),
        ("python/bindings.mojo", "std.python", "python/__init__.mojo"),
        ("testing/prop/random.mojo", "std.random", "random/__init__.mojo"),
        ("collections/string/string.mojo", "std.collections.string",
         "collections/string/__init__.mojo"),
    ]
    for rel, name, spelled in cases:
        src = os.path.join(stdlib, rel)
        check(os.path.isfile(src),
              f"the stdlib checkout at {stdlib} has no {rel}, so this row is "
              f"not measuring the file it claims to measure")
        got = I.resolve_module_path(name, relative_to=src)
        check(got is not None
              and os.path.abspath(got) == os.path.abspath(
                  os.path.join(stdlib, spelled)),
              f"{rel} writes `from {name} import …`, which spells "
              f"{spelled}; it resolved to "
              f"{os.path.relpath(got, stdlib) if got else None} instead")

    # And the whole stdlib, so the shape cannot come back in a file no sweep
    # row names yet: a leaf match in a root NEARER than the one that spells the
    # name. `first_source` asked of a two-root list is the rule itself, and the
    # roots are the ones a real build of that file searches.
    drifted = []
    for dirpath, _dirs, files in os.walk(stdlib):
        for fname in sorted(files):
            if not fname.endswith(".mojo"):
                continue
            path = os.path.join(dirpath, fname)
            try:
                stmts = I.module_statements(path)
            except Exception:
                continue
            roots = I._search_roots(path, None)
            for mod in I.imported_modules(stmts):
                if mod.startswith("."):
                    continue
                now = I.resolve_module_path(mod, relative_to=path)
                alt = I.first_source(mod, roots, ".mojo")
                if alt and now and os.path.abspath(alt) != os.path.abspath(now):
                    drifted.append((os.path.relpath(path, stdlib), mod,
                                    os.path.relpath(now, stdlib),
                                    os.path.relpath(alt, stdlib)))
    check(not drifted,
          f"{len(drifted)} stdlib import(s) still resolve to a module other "
          f"than the one they name: {drifted[:6]}")


def test_host_module_still_refused_despite_same_named_sibling(tmpdir, _shared):
    """The precedence that must NOT be reordered: host module before `.py`.

    This repository contains `formal/types.py` and `mojo/middle/types.py` —
    sibling sources whose basename is a CPython standard-library module. If a
    sibling were consulted first, an ordinary `from types import
    SimpleNamespace` would silently rebind to a same-named local module: the
    build would go on, using a module the file never meant, and nothing would
    say so. Python's own absolute-import rule agrees — `import types` is the
    standard library, never a neighbour.

    `types.py` here DEFINES the symbol being imported, so if the ordering ever
    inverts this test goes red instead of quietly passing."""
    root = os.path.join(tmpdir, "shadow")
    os.makedirs(root)
    write_tree(root, {
        "types.py": "def SimpleNamespace(x):\n  return x\n",
        "prog.mojo": ("from types import SimpleNamespace\n"
                      "def main():\n  return 1\n"),
    })
    fresh_cas()
    result = run_fire(["build", "--formal", "--no-prove", "-o",
                       os.path.join(root, "prog.aout"),
                       os.path.join(root, "prog.mojo")], cwd=root)
    check(result.returncode != 0,
          "`import types` bound to the local types.py and the build SUCCEEDED "
          "— a host module name was captured by a sibling, which is the "
          "silently-wrong-module failure this precedence exists to prevent")
    text = result.stderr + result.stdout
    check("host module" in text,
          f"the refusal must name the real reason (a CPython host module), "
          f"not claim the file is missing: {text[-300:]}")
    check("types.py" not in text.split("imports")[0],
          f"the error should be about the `types` IMPORT, not types.py: "
          f"{text[-300:]}")


def test_a_stdlib_module_in_no_tier_is_not_reported_as_a_typo(tmpdir, _shared):
    """`shlex` is a standard-library module, so the diagnostic says so.

    `formal/imports.py`'s two tiers are how anything downstream says WHY a
    file is out of reach — `host_module_tier` is what a coverage report asks —
    and a name in NEITHER tier falls through to module RESOLUTION and is
    reported "not a stdlib or sibling module, and no such file exists". For
    `shlex` that sentence is false: it is a standard-library module, and it is
    the one diagnostic in this family that misidentifies what kind of thing
    the name is. A false statement about the TARGET, in a message nobody wrote
    a rule for.

    Which tier is a judgement and not a formality, so both halves are checked:
    the tier decides the wording (`unresolvable_import_error` asks
    `_is_host_module`, not which tier), so a name classified into the wrong
    one gives a true sentence for the wrong reason. `shlex` is `modelled` and
    not `unreachable` because it is pure computation over strings — a state
    machine over a byte string, the same shape as `re` and `fnmatch`, both
    written. The streaming `shlex.shlex` reader is a generator over
    `readline`, which is the `fnmatch.iglob` shape and is not in reach by the
    same argument; `split`/`quote`/`join` are.

    The premise is asserted against CPython's own list rather than trusted:
    the whole failure is a name that IS in the standard library being reported
    as not one."""
    import sys as _sys
    import formal.imports as I
    check("shlex" in _sys.stdlib_module_names,
          "precondition: shlex is a CPython standard-library module, which is "
          "the fact the diagnostic used to deny")
    check(not I._host_tier_conflicts(),
          "a name in two tiers is a partition bug: %s"
          % I._host_tier_conflicts())

    # **`shlex` HAS SINCE BEEN WRITTEN** (`formal/hostmods/shlex.mojo`, `quote`,
    # checked against CPython's own by `test_formal_shlex.py` on both
    # backends), so it is in NO tier — `formal/imports.py`'s own rule, and the
    # same accounting `html` and `posixpath` went through on 2026-10-03. The
    # diagnostic this row was written for therefore no longer fires for it at
    # all: `import shlex` RESOLVES. So the row is split, and both halves are
    # kept because each is a different claim about a different name.
    #
    # `shlex` is now the OPPOSITE assertion — a written module leaves the tier,
    # and an import of it builds — and the "which TIER decides the wording" half
    # moves to `datetime`, which is still `modelled` and needs nothing this
    # target lacks (`formal/hostmods/time.mojo` already reads the clock
    # `datetime.now()` wants; the arithmetic is integer work). `resource` is the
    # other still-modelled name of the same shape.
    check(not I.host_module_tier("shlex"),
          "host_module_tier('shlex') is %r; its Mojo source exists, so an entry "
          "left behind would refuse a file AFTER the module that answers it is "
          "on disk, which is a false statement about the target"
          % I.host_module_tier("shlex"))
    check("datetime" in I.HOST_MODELLED,
          "datetime is not in HOST_MODELLED: it needs nothing a freestanding "
          "image does not have, so calling it unreachable would be a "
          "permanent-fact claim about the target and it is not one")
    check(I.host_module_tier("datetime") == "modelled",
          "host_module_tier('datetime') is %r, so a coverage report counts it "
          "as neither tier" % I.host_module_tier("datetime"))
    root = os.path.join(tmpdir, "datetime")
    os.makedirs(root)
    write_tree(root, {"prog.mojo": "import datetime\ndef main():\n  return 1\n"})
    fresh_cas()
    result = run_fire(["build", "--formal", "--no-prove", "-o",
                       os.path.join(root, "prog.aout"),
                       os.path.join(root, "prog.mojo")], cwd=root)
    check(result.returncode != 0,
          "a host-module import is still refused — this test is about the "
          "WORDING, and a build that succeeded would be a different bug")
    text = (result.stderr or "") + (result.stdout or "")
    check("host module" in text,
          "the refusal must name the real reason (a CPython host module): "
          f"{text[-300:]}")
    check("not a stdlib or sibling module" not in text,
          "the refusal still calls a standard-library module something that "
          f"does not exist: {text[-300:]}")
    # …and the closure, which is the other half of what became of `shlex`: a
    # written module's import BUILDS rather than being refused, and
    # `test_formal_shlex.py::group_resolve` is what checks the module itself.
    written = os.path.join(tmpdir, "shlex_written")
    os.makedirs(written)
    write_tree(written, {"prog.mojo": ("import shlex\n\ndef main():\n"
                                       "  return 0\n")})
    fresh_cas()
    ok = run_fire(["build", "--formal", "--no-prove", "-o",
                   os.path.join(written, "prog.aout"),
                   os.path.join(written, "prog.mojo")], cwd=written)
    check(ok.returncode == 0,
          "import shlex is refused although formal/hostmods/shlex.mojo answers "
          f"it: {(ok.stderr or ok.stdout or '').strip()[-300:]}")


def test_no_standard_library_module_is_left_in_neither_tier(tmpdir, _shared):
    """The six names that were, and what each one is placed by.

    `test_a_stdlib_module_in_no_tier_is_not_reported_as_a_typo` above pins the
    property for `shlex`, one module. It was true for six more on 2026-10-03,
    and they were found by a RANKING rather than by reading the tier list:
    `tools/formal_sweep_causes.py --host` prints `UNTIERED` for a name in
    neither tier with no model, which turned "some names are in neither tier"
    from a sentence in a comment into six module names and ten swept files.

    A name in neither tier is refused with "not a stdlib or sibling module, and
    no such file exists", which is a false statement about a CPython
    standard-library module — and it is also the sentence that says the reader
    has a TYPO, which is the wrong thing to tell someone whose import is
    correct. Ten files in the 2026-10-02 arm64 sweep were reading it.

    The tier each one lands in is a judgement made BY THE RULE and stated in
    `formal/imports.py`, so this test checks the placement and not just the
    membership:

      * `builtins` and `sysconfig` are UNREACHABLE, and each for a measured
        reason rather than a read one — `builtins` because the three files that
        want it all spell `set(dir(builtins))`, which asks the interpreter to
        enumerate itself, and `sysconfig` because `fire.py` imports it and
        never uses it, so what it wants is where an interpreter that is not here
        would be installed.
      * `datetime` and `resource` are still MODELLED, because neither needs an
        object this target does not have: `datetime` is a clock this tree already
        reads plus calendar arithmetic, and `resource` is `getrusage(2)` in
        libSystem with a fixed struct.
      * `html` and `posixpath` needed no object this target does not have either
        -- `html` is five character replacements, and `posixpath` IS
        `formal/hostmods/os/path/__init__.mojo` under another spelling -- and
        both have since been WRITTEN, so they are in no tier at all. They are
        checked by the `written` table below, keyed on whether the module is on
        disk rather than on a date, so a third one landing does not need this
        file edited to agree with the tree. **`posixpath` in particular left by
        being WRITTEN**, which is the same rule `shutil` and `tempfile`
        followed; the accounting for a name added to a tier and then written is
        `test_formal_link_accounting.py`'s `HOST_SET_ADDED_THEN_WRITTEN`, and
        `test_posixpath_is_provided_by_a_re_export` is what pins that
        `import posixpath` BUILDS.

    **TWO OF THE FOUR HAVE SINCE BEEN WRITTEN, so their tier is `\'\'` and not
    `\'modelled\'`,** and that is `formal/imports.py`\'s own rule rather than a
    change of judgement about them: a name LEAVES a tier by being written,
    because an entry left behind after the module that answers it is on disk
    would be a false statement about the target rather than a conservative one.
    `formal/hostmods/html.mojo` (`escape`, five ordered replacements, checked by
    `test_formal_html.py`) and `formal/hostmods/posixpath.mojo` (thirty
    one-line forwards to `os.path`, checked by `test_formal_posixpath.py`) both
    landed on 2026-10-03. The classification is kept in the table with the tier
    it had and the one it has, because a reader comparing this file with
    `formal/imports.py` should see a MODULE LANDING rather than a rule quietly
    changing \u2014 and because the judgement ("no object this target lacks") is
    still what put them in a tier at all.

    So: the premise (each is a real CPython stdlib module, read from
    `sys.stdlib_module_names` and not trusted), the membership (each is in a
    tier), the placement (each tier is the one its reason implies), and the
    WORDING (each is refused as a host module and not as a typo).
    """
    import sys as _sys
    import formal.imports as I
    placed = {
        # name: (tier, why that tier, in one line)
        "builtins": ("unreachable",
                     "`set(dir(builtins))`: the interpreter's own namespace"),
        "sysconfig": ("unreachable",
                      "where an embedded CPython would be installed"),
        "datetime": ("modelled", "a clock this tree reads, plus arithmetic"),
        "resource": ("modelled", "`getrusage(2)` is libSystem"),
    }
    # The two that have since been WRITTEN. Their tier is `""` now, and the
    # expectation is keyed on whether the module is on disk rather than on a
    # date, so a third one landing does not need this file edited to agree with
    # the tree \u2014 `formal/imports.py`'s rule fires by itself and this row is
    # what checks that it did.
    written = {
        "html": ("five character replacements over a string",
                 "formal/hostmods/html.mojo"),
        "posixpath": ("`os/path/__init__.mojo` IS CPython's posixpath",
                      "formal/hostmods/posixpath.mojo"),
    }
    for name, (why, path) in sorted(written.items()):
        check(os.path.isfile(os.path.join(HERE, path)),
              f"precondition: {name} is expected to have a module at {path}, "
              f"and it does not \u2014 so the tier below is not about a written "
              f"module at all")
        got = I.host_module_tier(name)
        check(got == "",
              f"host_module_tier({name!r}) is {got!r}, not '' \u2014 {why}, and "
              f"{path} answers it, so a tier entry left behind would be a false "
              f"statement about the target rather than a conservative one")
    for name, (tier, why) in sorted(placed.items()):
        check(name in _sys.stdlib_module_names,
              f"precondition: {name} is not a CPython standard-library module, "
              f"so the diagnostic it used to get was not a false statement "
              f"about one")
        check(not I._host_tier_conflicts(),
              "a name in two tiers is a partition bug: %s"
              % I._host_tier_conflicts())
        got = I.host_module_tier(name)
        check(got == tier,
              f"host_module_tier({name!r}) is {got!r}, not {tier!r} — {why}. "
              f"The tier is what a coverage report counts a file against, so "
              f"the wrong one moves a number rather than just a sentence")
    root = os.path.join(tmpdir, "untiered")
    os.makedirs(root, exist_ok=True)
    for name in sorted(placed):
        # `posixpath` is not in `placed` any more, and this loop asserts that
        # every name IN it is still refused as a host module — so a name that has
        # been written cannot be added here without failing, which is the point.
        # Its own assertion is that `import posixpath` BUILDS (see
        # `test_posixpath_is_provided_by_a_re_export`).
        # A DIRECTORY PER NAME, and the reason is worth recording because the
        # first version of this test put `builtins.mojo` NEXT TO the program
        # that imports `builtins` and watched it build: the resolver's third
        # pass finds a sibling source, so the program resolved its own import to
        # itself and the test reported a false pass. The tier change is exactly
        # what stops that — a name in a HOST tier outranks a sibling — which is
        # `test_host_module_still_refused_despite_same_named_sibling`'s subject
        # and is why this fixture does not rely on it.
        one = os.path.join(root, name)
        os.makedirs(one, exist_ok=True)
        prog = os.path.join(one, "prog.mojo")
        with open(prog, "w") as f:
            f.write(f"import {name}\ndef main():\n  return 1\n")
        fresh_cas()
        result = run_fire(["build", "--formal", "--no-prove", "-o",
                           os.path.join(one, "prog.aout"), prog], cwd=one)
        check(result.returncode != 0,
              f"import {name} built. A module with a Mojo source would "
              f"resolve, which is a different (and better) finding — update "
              f"this table and the census row together")
        text = (result.stderr or "") + (result.stdout or "")
        check("host module" in text,
              f"import {name} is not refused as a host module, so this name "
              f"is being resolved some other way: {text[-300:]}")
        check("not a stdlib or sibling module" not in text,
              f"import {name} is still refused as a name that does not exist, "
              f"which is a false statement about a CPython standard-library "
              f"module: {text[-300:]}")


def test_a_name_with_nothing_to_implement_gets_its_own_tier(tmpdir, _shared):
    """The FOURTH answer, and the two corrections that earned it.

    `bugs/FORMAL_stdlib_module_names_are_not_classified.md` §"The next step"
    named the gap exactly: its "neither tier, deliberately" group — "a name
    whose only spelling is a documentation or test artefact (`this`,
    `antigravity`, `turtledemo`, `idlelib`), or a Windows-only / POSIX-only
    module that is not this host's (`msvcrt`, `winreg`, `nt*`, `posix`,
    `genericpath`, `nturl2path`)" — "want[s] a third answer or an explicit
    exclusion list, which is a decision about the table rather than a
    classification — and it should be recorded as one, not left to look like an
    oversight."

    **It is the FOURTH and not the third**, because `HOST_ADMITTED` took that
    slot, and `host_module_tier` now answers four values plus `''`.

    **The premise each name rests on is CPython's own `find_spec`, not a
    remembered list**, which is what splits the doc's single group into three
    with different answers:

      * `this`, `antigravity`, `turtledemo` — a spec EXISTS and what is behind
        it is not code. `this` is the Zen of Python as a module-level string,
        `antigravity` opens a browser, `turtledemo` is a directory of example
        scripts. Nothing to implement and nothing missing, so neither
        `unreachable` ("needs an object this target lacks") nor `modelled`
        ("nothing is missing and the work is undone") is true of them, and
        `HOST_NOT_A_MODULE` says the one thing that is.
      * `msvcrt`, `winreg`, `winsound`, `nt` — **no spec AT ALL** on the
        interpreter that runs this tree. CPython cannot find them here either,
        so the object is missing from the target and `unreachable` is the
        table's own rule applied, not a new category.
      * `ntpath`, `nturl2path`, `genericpath`, `posix` — a spec EXISTS here,
        because they are frozen or arithmetic-over-strings modules CPython
        ships everywhere and only ever *uses* on Windows. **These are the
        CORRECTION**: the doc listed them with `msvcrt` as "not this host's",
        and for `posix` that is false outright — this is a POSIX target, and
        `formal/hostmods/os/_syscalls.mojo` already makes every libSystem call
        `posix` would need. So they are `modelled`.

    And `idlelib` is in NEITHER new tier and that is also a correction: the doc
    lists it twice, once as a documentation artefact and once under
    `unreachable`. The second is right — IDLE is an interactive editor, so it
    needs a terminal — and `HOST_UNREACHABLE`'s existing "A terminal" heading is
    that fact, so it is left in the queue rather than given the wrong tier.

    **The Wording half is the point of the tier.** A member of
    `HOST_NOT_A_MODULE` is in the union, so the arm that says "a host module …
    which has no Mojo source" would fire — true, and it tells the reader to go
    and implement a module that has no API. So the new arm is tested FIRST.
    """
    import sys as _sys
    import formal.imports as I

    not_a_module = {
        "this": "the Zen of Python, one module-level string",
        "antigravity": "importing it opens a browser window",
        "turtledemo": "a directory of turtle-graphics demonstration scripts",
    }
    # Measured, not remembered: CPython itself cannot find these here, so the
    # object is missing from the target and the EXISTING `unreachable` row is
    # the rule applied rather than a fourth category invented for them.
    foreign = ("msvcrt", "winreg", "winsound", "nt")
    # …and the four the doc grouped with them, which a spec here contradicts.
    pure = {
        "posix": "the POSIX low-level module, and THIS is a POSIX target",
        "genericpath": "the platform-independent base `os.path` builds on",
        "ntpath": "the Windows path parser, which is string manipulation",
        "nturl2path": "`url2pathname`/`pathname2url`, string in, string out",
    }
    check(not I._host_tier_conflicts(),
          "a name in two tiers is a partition bug: %s"
          % I._host_tier_conflicts())
    check(not (I.HOST_NOT_A_MODULE
               & (I.HOST_UNREACHABLE | I.HOST_MODELLED | I.HOST_ADMITTED)),
          "HOST_NOT_A_MODULE asserts the LEAST of the four tiers, so a name in "
          "two of them is a claim that contradicts itself")

    for name, why in sorted(not_a_module.items()):
        check(name in _sys.stdlib_module_names,
              f"precondition: {name} is not a CPython standard-library module")
        got = I.host_module_tier(name)
        check(got == "not-a-module",
              f"host_module_tier({name!r}) is {got!r}, not 'not-a-module' — "
              f"{why}. In either other tier it would assert something false "
              f"about the module")
    for name, why in sorted(pure.items()):
        got = I.host_module_tier(name)
        check(got == "modelled",
              f"host_module_tier({name!r}) is {got!r}, not 'modelled' — "
              f"{why}, so nothing is missing from the target and only the "
              f"module is unwritten. Calling it unreachable would be a "
              f"permanent-fact claim about the target and it is not one")
    for name in foreign:
        got = I.host_module_tier(name)
        check(got == "unreachable",
              f"host_module_tier({name!r}) is {got!r}, not 'unreachable' — it "
              f"needs an object this target does not have")
    check(not I.host_module_tier("idlelib"),
          "idlelib is in no tier: it is a TERMINAL (an interactive editor), so "
          "`unreachable` is right and giving it 'not-a-module' would claim "
          "there is nothing to implement when there is a whole editor")

    # …and the SPEC measurement itself, so the three groups cannot drift apart
    # from the interpreter the next time one of them is questioned.
    import importlib.util
    for name in sorted(not_a_module):
        spec = importlib.util.find_spec(name)
        check(spec is not None and spec.origin,
              f"precondition: CPython finds source for {name!r} here, which is "
              f"what makes it 'nothing to implement' rather than 'not this "
              f"host's' — measured {spec!r}")
    for name in foreign:
        try:
            spec = importlib.util.find_spec(name)
        except (ImportError, ValueError):
            spec = None
        check(spec is None,
              f"precondition: CPython cannot find {name!r} on this host at "
              f"all, which is the measurement the `unreachable` placement rests "
              f"on — measured {spec!r}")

    # The WORDING, which is the load-bearing half: a name in this tier must not
    # be sent to implement a module that has no API.
    for name in sorted(not_a_module):
        one = os.path.join(tmpdir, "notamodule", name)
        os.makedirs(one, exist_ok=True)
        prog = os.path.join(one, "prog.mojo")
        with open(prog, "w") as f:
            f.write(f"import {name}\ndef main():\n  return 1\n")
        fresh_cas()
        result = run_fire(["build", "--formal", "--no-prove", "-o",
                           os.path.join(one, "prog.aout"), prog], cwd=one)
        check(result.returncode != 0,
              f"import {name} built. A module with a Mojo source would "
              f"resolve, which is a different (and better) finding")
        text = (result.stderr or "") + (result.stdout or "")
        check("no content to compile" in text,
              f"import {name} does not say there is nothing to implement, so "
              f"the reader is sent to write a module with no API: "
              f"{text[-300:]}")
        check("host module" not in text,
              f"import {name} is refused as a host module awaiting a Mojo "
              f"source, which is the sentence the new tier exists to replace: "
              f"{text[-300:]}")
        check("not a stdlib or sibling module" not in text,
              f"import {name} is still refused as a name that does not exist, "
              f"which is false of a CPython standard-library module: "
              f"{text[-300:]}")


def test_a_host_module_refusal_says_what_this_target_offers(tmpdir, _shared):
    """The refusal's second half: what to write here instead, where the reader is.

    `unresolvable_import_error`'s first half is a fact about the RESOLVER — no
    Mojo source, no front-end provider — and it is the whole of what the message
    used to say. Measured on this repository: five files in its own tooling are
    blocked on `import collections`, four of them on
    `collections.namedtuple("Census", "ok detail …")`
    (`formal/lean.py:816`, `formal/model.py:13195`, `tools/formal_sweep.py`),
    and the answer for a compile-time-known record with readable fields is a
    `struct`. Without that sentence the refusal reads as "this target cannot do
    records", and the next thing a reader does is file the next bug document
    about `collections` — which is what
    `bugs/FORMAL_a_type_cannot_be_constructed_or_cloned_at_run_time.md` is.

    **BOTH DIRECTIONS, because advice on every host module is the same noise in a
    different place.** The second row is a host module with no entry: its
    refusal must be exactly what it was, which is what stops this from growing
    into a paragraph nobody reads.
    """
    root = os.path.join(tmpdir, "advice")
    os.makedirs(root, exist_ok=True)
    prog = os.path.join(root, "prog.mojo")
    with open(prog, "w") as f:
        f.write("from collections import namedtuple\n"
                "def main() -> int:\n"
                "    C = namedtuple(\"C\", \"a b\")\n"
                "    return 0\n")
    fresh_cas()
    result = run_fire(["build", "--formal", "--no-prove", "-o",
                       os.path.join(root, "prog.aout"), prog], cwd=root)
    check(result.returncode != 0,
          "the host-module refusal did not fire, so this row is not testing "
          "the message")
    text = result.stderr + result.stdout
    check("STRUCT" in text,
          "the refusal does not say the record the callers want is a struct, "
          f"which is the whole deliverable: {text[-400:]}")
    check("doc/ABI.md" in text,
          "the refusal does not say what is NOT possible (a type built at run "
          f"time), so it reads as a blanket 'no': {text[-400:]}")

    other = os.path.join(root, "other.mojo")
    with open(other, "w") as f:
        f.write("from itertools import chain\n"
                "def main() -> int:\n"
                "    return 0\n")
    result = run_fire(["build", "--formal", "--no-prove", "-o",
                       os.path.join(root, "other.aout"), other], cwd=root)
    text = result.stderr + result.stdout
    check("host module" in text,
          f"`itertools` lost its refusal: {text[-300:]}")
    check("STRUCT" not in text,
          "a host module with no entry in the advice table grew one, which "
          f"makes every such refusal a paragraph: {text[-300:]}")


def test_an_unclassified_stdlib_name_is_not_called_a_typo(tmpdir, _shared):
    """238 names: CPython ships them, this table classifies none of them.

    The same defect as the row above, one tier wider, and it was 222 names wide
    rather than one because `shlex` was fixed by adding ONE tier entry while the
    question it was really asking — "is this name in the standard library?" —
    has an oracle: CPython's own `sys.stdlib_module_names`. Answering it from the
    hand-kept tiers made the build say, of a module CPython ships:

        build: a.mojo imports 'binascii', which is not a stdlib or sibling
        module, and no such file exists

    which is false about the target, and 36 sweep rows were filed as unresolved
    imports rather than as the host-import rows they are. The wording now has
    three arms and this is the middle one: a name in a tier says it is a host
    module, a name CPython ships and no tier names says it is a standard-library
    module with no tier and therefore no verdict, and a name CPython does not
    ship is the only one that may be called unresolvable.

    Both boundaries are checked, because a rule that answered "yes" for
    everything would make the typo sentence unreachable and this suite's other
    rows (`test_an_unresolvable_import_says_no_such_file_exists` and its
    neighbours) would stop testing anything.
    """
    import sys as _sys
    import formal.imports as I
    unclassified = [n for n in sorted(_sys.stdlib_module_names)
                    if not I.host_module_tier(n)]
    check(len(unclassified) > 100,
          "precondition: this test is about the names in NO tier, and there are "
          f"only {len(unclassified)} of them now — if they have been "
          "classified, this row is about nothing and should go")
    for name in ("binascii", "cmath", "getopt", "tomllib"):
        check(name in _sys.stdlib_module_names,
              f"precondition: {name} is a CPython standard-library module, "
              "which is the fact the diagnostic used to deny")
        check(I.is_cpython_stdlib(name),
              f"is_cpython_stdlib({name!r}) is False: it is the host's own "
              "library, and CPython's own table says so")
        check(not I.host_module_tier(name),
              f"{name} is expected to be in no tier — this row is about the "
              "wording of an UNCLASSIFIED name, and if it has been classified "
              "the row above is the one that applies")
    # `html` was in that list and left it on 2026-10-03, when the row above
    # placed it `modelled` (five character replacements over a string, needing
    # no object this target lacks). **It has since been WRITTEN**
    # (`formal/hostmods/html.mojo`, `escape`, checked by `test_formal_html.py`),
    # so its tier is `""` — which is still "not in no tier", and that is all
    # this row asks: the point of the assertion is that a name CPython ships
    # must not produce the TYPO sentence, and a name this tree answers for
    # produces a third wording again.
    #
    # The distinction the two rows exist to keep is therefore
    # `host_module_tier(n) != ""`, not `== "modelled"` — and the row above is
    # the one that says WHICH tier, with the two written names tracked
    # separately there because a written name has none. Asserting `"modelled"`
    # here is what made this row go red the moment a module was written for a
    # name the ranking had classified, which is a false alarm about a row whose
    # subject never changed.
    check(not I.host_module_tier("html"),
          "html IS in a tier, so this row is not about it after all: it is one "
          "word in 'a standard-library module with no tier' that must NOT "
          "produce the typo sentence, and the row above is where its tier is "
          "pinned. Written on 2026-10-03, so it is written again")
    check(I.is_cpython_stdlib("os.path"),
          "a dotted name is matched on its TOP component, like "
          "`_is_host_module` and `host_module_tier`")
    check(not I.is_cpython_stdlib("not_a_module_anywhere"),
          "a name CPython does not ship must not be called a standard-library "
          "module, or the typo sentence becomes unreachable")
    check(not I.is_cpython_stdlib(""),
          "the empty name is not a module")
    # A classified name that this tree BUILDS is still not a host module for
    # `_is_host_module`'s purposes, which is the distinction the two predicates
    # exist to keep: `math` is in CPython's table and has a `formal/hostmods/`
    # source, so the build must not refuse it.
    check(not I._is_host_module("math"),
          "_is_host_module('math') became True: that predicate answers 'is this "
          "one of the names we have classified as unbuildable', and `math` has "
          "a source in formal/hostmods/ and is pinned False by "
          "test_formal_math.py")
    root = os.path.join(tmpdir, "unclassified")
    os.makedirs(root)
    write_tree(root, {"prog.mojo": "import binascii\ndef main():\n  return 1\n"})
    fresh_cas()
    result = run_fire(["build", "--formal", "--no-prove", "-o",
                       os.path.join(root, "prog.aout"),
                       os.path.join(root, "prog.mojo")], cwd=root)
    check(result.returncode != 0,
          "an unclassified standard-library import is still refused — this "
          "test is about the WORDING")
    text = (result.stderr or "") + (result.stdout or "")
    check("not a stdlib or sibling module" not in text,
          "the refusal still calls a standard-library module something that "
          f"does not exist: {text[-300:]}")
    check("standard-library module" in text,
          f"the refusal must say what the name IS: {text[-300:]}")
    check("no tier" in text,
          "and it must say that nothing here can say whether the module is "
          f"reachable, which is the whole difference from a tiered name: "
          f"{text[-300:]}")


def test_no_unclassified_stdlib_name_is_imported_by_anything(tmpdir, _shared):
    """The other half of the row above: those 200-odd names have NO consumer.

    `test_an_unclassified_stdlib_name_is_not_called_a_typo` pins what a build
    SAYS about a name in no tier, and it says the true thing: this tree cannot
    say whether the module is reachable. What it cannot pin is whether that
    matters, because "unclassified" is a statement about the table and not about
    the corpus. The corpus question is the one that decides how much of the
    table is worth filling, and it is cheap to ask of every `.mojo` file rather
    than of the ones a sweep happened to reach:

        unclassified names  x  files that IMPORT one of them  =  (must be empty)

    Measured over this repository and the stdlib on 2026-10-03, it is EMPTY --
    not one of the 223 was imported by any of the 370 files, which is why
    `bugs/FORMAL_stdlib_module_names_are_not_classified.md` stopped asking for
    222 per-name judgements: there is no measurement to tell a right entry from
    a plausible one, and no file whose answer changes. Asserting it here makes
    that a standing invariant rather than a snapshot, and it is a TRIPWIRE with
    a direction: the day a file imports `binascii`, this goes red and the fix is
    to place the name by the rule in `formal/imports.py`, which is the only
    thing that can answer the question the new consumer has asked.

    The stdlib half SKIPS when it is absent, on purpose and for the reason
    `test_formal_mlir_precedence.py`'s census says: the stdlib lives OUTSIDE
    this repository, and "there is no corpus here" must not print the same word
    as "every consumer of these names is classified". The repository half is
    unconditional, so the invariant is still checked on a checkout without it.
    """
    import sys as _sys
    # The set is asked of ONE accessor now, and that is the point of this
    # revision: "in no tier AND no module" used to have to be spelled here, by
    # pairing `host_module_tier` with `resolve_module_path`, because
    # `host_module_tier`'s `''` cannot say which of the two it means -- a name
    # this tree has WRITTEN leaves its tier (see the rule on `HOST_MODELLED`), so
    # `os`, `sys` and `os._syscalls` answer `''` while being the three
    # most-imported modules in the corpus. Three consumers had grown three ways
    # of telling those apart (this one, `tools/formal_sweep_causes.py`'s
    # `formal/hostmods/` path check, and `tools/formal_host_import_wall.py`'s),
    # and
    # `formal/imports.py::host_module_verdict` is now the one classification
    # with every outcome named. So `unclassified` is a NAME this tree can say
    # rather than an absence a reader has to infer.
    #
    # `probe` still matters even though the accessor resolves: it is what makes
    # the resolver answer with the same nearest-first roots the build uses.
    probe = os.path.join(HERE, "formal", "arm64.py")
    unclassified = {n for n in _sys.stdlib_module_names
                    if I.host_module_verdict(n, relative_to=probe,
                                             project_root=probe)[0]
                    == "unclassified"}
    check(len(unclassified) > 100,
          f"precondition: only {len(unclassified)} CPython standard-library "
          "names are in no tier, so this row is about the names in no tier "
          "only if there are many of them")
    roots = [(HERE, "this repository")]
    stdlib = os.path.join(HERE, "..", "new-modular", "Mojo", "stdlib", "std")
    if os.path.isdir(stdlib):
        roots.append((stdlib, "the stdlib"))
    consumers = []
    scanned = 0
    for root, what in roots:
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in sorted(dirs)
                       if d not in (".git", "build", ".tmp", "__pycache__")]
            for name in sorted(files):
                if not name.endswith(".mojo"):
                    continue
                path = os.path.join(dirpath, name)
                try:
                    with open(path, "rb") as f:
                        source = f.read()
                    stmts = I.parse_module_for_closure(source, path)
                except Exception:  # noqa: BLE001 — a file this path cannot
                    continue        # parse is not a consumer of anything
                scanned += 1
                for mod in I.imported_modules(stmts):
                    top = mod.split(".")[0]
                    if top in unclassified:
                        consumers.append((mod, os.path.relpath(path, root)))
    check(scanned > 100,
          f"only {scanned} .mojo files were scanned, so this row is not "
          "covering the corpus it claims to cover")
    check(not consumers,
          "these files import a CPython standard-library name that no tier "
          "classifies, so nothing here can say whether the module is "
          f"reachable and the file's host-import row has no verdict: "
          f"{consumers[:10]}")


def test_every_name_has_one_named_verdict_and_no_answer_is_an_absence(
        tmpdir, _shared):
    """`host_module_verdict`: the six answers, one row each, and the partition.

    `host_module_tier` answers a MEMBERSHIP question and its `''` is ambiguous in
    the one direction a report cares about: a name this tree has WRITTEN leaves
    its tier (`HOST_MODELLED`'s own rule), so `os`, `sys` and `os._syscalls`
    answer `''` and are the three most-imported modules in the corpus, while the
    standard-library names nobody classified answer `''` too. Three consumers
    had grown three ways of telling those apart —
    `test_no_unclassified_stdlib_name_is_imported_by_anything` paired the tier
    with `resolve_module_path`, `tools/formal_sweep_causes.py` inferred it from a
    `formal/hostmods/` path existing (which is a third definition again: it
    misses a repository sibling and a package outside that directory), and
    `tools/formal_host_import_wall.py` paired both with `is_cpython_stdlib`. One
    classification, every answer named, is what makes a report's `''` mean one
    thing.

    Each row below is a REAL name in this tree, and the `detail` half is checked
    where there is one: `written` and `admitted` are the two answers that answer
    "then what provides it", so an empty path for either would be a row that
    names a state and withholds the file.

    The partition is the part that is worth having. Over every name CPython
    ships, the verdict is one of the five answers that are statements about the
    target or about this tree, and `not-a-module` is unreachable for them — so
    the classification of the standard library is COMPLETE, which is the closed
    invariant that replaces this file's earlier `count > 100` placeholder. The
    `unclassified` count is still asserted to be large, so this row stays about
    the names in no tier; what changed is that they are a NAMED answer rather
    than an absence a reader has to infer.
    """
    import sys as _sys
    probe = os.path.join(HERE, "formal", "arm64.py")

    def verdict(name):
        return I.host_module_verdict(name, relative_to=probe,
                                     project_root=probe)

    rows = (
        # name, the answer, what makes it that one, and the detail it carries
        ("dataclasses", "front-end",
         "a compile-time transform, so there is no source and nothing to link"),
        ("os", "written", "formal/hostmods/os/__init__.mojo answers it"),
        ("os._syscalls", "written",
         "a SUBMODULE of a written package, which is why the answer has to go "
         "through the resolver rather than through the name's top component"),
        ("subprocess", "admitted",
         "a source AND `@admitted` contracts for the operations whose answer is "
         "a host fact"),
        ("copy", "modelled", "in HOST_MODELLED and unwritten: a gap with an "
                             "owner"),
        ("asyncio", "unreachable",
         "in HOST_UNREACHABLE: an event loop and a thread are objects this "
         "image does not have"),
        ("binascii", "unclassified",
         "CPython ships it, no source here, no tier: the queue "
         "`FORMAL_stdlib_module_names_are_not_classified.md` carries"),
        ("definitely_not_a_real_module_9f3a", "not-a-module",
         "nothing here provides it and CPython does not ship it — a typo, or a "
         "gap in this repository, which `tools/formal_sweep.py` classes as "
         "`not-answerable/unresolved-import`"),
    )
    for name, want, why in rows:
        answer, detail = verdict(name)
        check(answer == want,
              f"{name} is {answer!r} and this row is about it being {want!r} "
              f"({why}) — a `detail` of {detail!r}")
        if want in ("written", "admitted"):
            check(detail.endswith(".mojo") and os.path.isfile(detail),
                  f"{name} answers {want!r} and its detail {detail!r} is not "
                  "a source file, so the answer names a state and withholds "
                  "the file that provides it")
        else:
            check(detail == "",
                  f"{name} answers {want!r} and carries detail {detail!r}; "
                  "only written and admitted name a file")

    # The empty name, and the one answer it must give rather than raising: a
    # caller that asks about nothing should not have to guard the call.
    check(verdict("") == ("not-a-module", ""),
          f"the empty name answers {verdict('')!r}")

    # THE PARTITION, over everything CPython ships.
    tally = {}
    for name in _sys.stdlib_module_names:
        answer, _detail = verdict(name)
        tally[answer] = tally.get(answer, 0) + 1
        # `not-a-module` is unreachable for a CPython-shipped name AS AN
        # ABSENCE, and `HOST_NOT_A_MODULE` is what makes that distinction
        # checkable rather than a matter of taste: `this`, `antigravity` and
        # `turtledemo` are shipped AND answer `not-a-module`, and the only thing
        # separating them from the typo answer is a tier that says why. So the
        # invariant is the pair — no shipped name gets the typo answer, and
        # every shipped name that DOES get it is one a table claims.
        check(answer != "not-a-module"
              or I.host_module_tier(name) == "not-a-module",
              f"CPython ships {name}, so no verdict can reach the TYPO "
              "sentence's answer — nothing here provides it and CPython does "
              "not ship it — as an absence; a tier that says the name is "
              f"shipped-and-empty is the other half, and `host_module_tier"
              f"({name!r})` is {I.host_module_tier(name)!r}")
        if answer in ("modelled", "unreachable"):
            # The rule `HOST_MODELLED` states and this file's other rows pin: a
            # name LEAVES a tier by being WRITTEN, because an entry left behind
            # a module that answers it is a false statement about the target
            # rather than a conservative one. Asserting it here is what makes
            # `written` and the two claim tiers disjoint rather than
            # order-dependent.
            check(I.resolve_module_path(name, relative_to=probe,
                                        project_root=probe) is None,
                  f"{name} is {answer!r} AND has a source, so it is in a tier "
                  "and answered at once — remove the stale entry or the source")
    # SEVEN, and the seventh is `not-a-module` — the one answer that is a
    # statement about THIS repository rather than about the target or about
    # CPython's list. It is in `host_module_verdict`'s own table (which says
    # "six strings" over a seven-row table, corrected here), and it became
    # reachable for a name CPython ships when `HOST_NOT_A_MODULE` landed: a
    # spec exists and what is behind it is not code. Listing it here rather than
    # leaving the check to enumerate six is what stops the NEXT answer from
    # arriving undocumented, which is the failure this row exists to catch.
    for answer in tally:
        check(answer in ("front-end", "written", "admitted", "modelled",
                         "unreachable", "unclassified", "not-a-module"),
              f"the verdict {answer!r} is not one of the seven answers, so a "
              "report reading it has an eighth case nobody documented")
    check(tally.get("unclassified", 0) > 100,
          f"precondition: only {tally.get('unclassified', 0)} CPython "
          "standard-library names are unclassified, so this row is about the "
          "unclassified names only if there are many of them")


def test_mojo_source_beats_host_module(tmpdir, _shared):
    """The other precedence: a real Mojo module beats the host-module list.

    If the host check ran first, a `math.mojo` sitting beside the importer
    would be refused in favour of CPython's `math` — binding the program to
    the wrong module. A target's own source is a stronger statement than any
    name in HOST_MODULES."""
    root = os.path.join(tmpdir, "mojobeats")
    os.makedirs(root)
    write_tree(root, {
        "math.mojo": "def sqrtish(x):\n  return x + 1\n",
        "prog.mojo": "from math import sqrtish\ndef main():\n  return sqrtish(41)\n",
    })
    fresh_cas()
    _result, out = build(root, "prog.aout")
    code, err = run(out)
    check(code == 42,
          f"returned {code}, expected 42 — the local math.mojo lost to the "
          f"host-module list, so the program bound CPython's `math` instead: "
          f"{err}")


# The NEXT STEP, for the host modules where measurement has already answered it.
#
# A refusal that names the module and stops is the shape this table exists to
# end. The measurement behind it: every file that stops on one of these names
# stops on the MODULE and never reaches the call, so the message is all the
# reader has — five files in this repository stop on `collections`, and the one
# next step for them ("the record you want is spelled at compile time, so
# declare a `struct`") is not discoverable from the message that refused them.

def test_a_host_module_refusal_carries_its_measured_next_step(tmpdir, _shared):
    """`import collections` is refused, and the refusal says what to write.

    Three things are pinned, and each is a way this could be a decoration: the
    refusal still happens (a table that made the module resolvable would turn
    this green for the wrong reason); the advice NAMES both the thing wanted and
    the spelling that works (`namedtuple` and `struct`); and the message is one
    sentence appended to the existing wording, so a classifier matching on
    `unresolvable_import_error`'s own `kind` text is unaffected."""
    import formal.imports as I
    root = os.path.join(tmpdir, "collections")
    os.makedirs(root)
    write_tree(root, {
        "prog.mojo": ("import collections\n"
                      "def main(n):\n"
                      "  return n\n"),
    })
    fresh_cas()
    result = run_fire(["build", "--formal", "--no-prove", "-o",
                       os.path.join(root, "prog.aout"),
                       os.path.join(root, "prog.mojo")], cwd=root)
    text = result.stderr + result.stdout
    check(result.returncode != 0,
          "a program importing `collections` BUILT — the advice table is not "
          "allowed to make a host module resolvable, only to explain it")
    check("host module" in text,
          f"the refusal must still name the real reason: {text[-300:]}")
    check("namedtuple" in text,
          f"the refusal must name the name the file wants, or the reader has "
          f"to find it themselves: {text[-300:]}")
    check("struct" in text,
          f"the refusal must name the spelling that WORKS on this target — a "
          f"record is a `struct` — or it names a want and not an answer: "
          f"{text[-300:]}")
    # The base wording is preserved verbatim as the prefix, which is what makes
    # the append safe for `formal_sweep.py`'s message families.
    base = I.unresolvable_import_error("prog.mojo", "collections")
    check(base.startswith("prog.mojo imports 'collections', which is a host "
                          "module (CPython standard library), which has no Mojo "
                          "source for this backend to compile"),
          f"the generated wording changed shape, so anything matching on it "
          f"moves: {base!r}")


def test_host_module_advice_is_honest(tmpdir, _shared):
    """Every advice entry is a CLAIM the module still has no source.

    An entry left behind after someone writes `formal/hostmods/collections.mojo`
    would be advice to reimplement a module that is sitting in the tree, which
    is worse than no advice at all — and nothing else would notice, because the
    entry is only read on a path the new module makes unreachable. So the claim
    is checked here, against the tree, rather than trusted.

    The other direction is checked in the same loop: an entry whose advice does
    not name the thing the module is wanted FOR is a generic sentence, and a
    generic sentence in a generated message is noise."""
    import formal.imports as I
    for name, advice in I.HOST_MODULE_ADVICE.items():
        src = I.resolve_module_path(name, relative_to=os.path.join(HERE, "x"),
                                    project_root=HERE)
        check(src is None,
              f"HOST_MODULE_ADVICE has an entry for {name!r} but it now "
              f"resolves to {src!r} — a module source exists, so the advice is "
              f"telling a reader to write what is already in the tree")
        check(len(advice) > 40,
              f"the advice for {name!r} is too short to be a next step: "
              f"{advice!r}")
    check("collections" in I.HOST_MODULE_ADVICE,
          "the `collections` advice was deleted; the five files that stop there "
          "are back to a message that names the module and nothing else")
    # A dotted name asks for the same answer, which is the rule that makes a
    # per-spelling table wrong by omission.
    check(I.host_module_advice("collections.abc") ==
          I.host_module_advice("collections"),
          "a dotted host module did not get its package's advice")
    check(I.host_module_advice("re") == "",
          "`re` has no advice — it is answered by `formal/hostmods/re.mojo`, and "
          "an entry there would be advice to reimplement a module that exists")



# A struct-only module, and a program that uses it across the import boundary.
# Both halves matter: the module must be buildable at all (its API is methods,
# not free functions), and the caller's `Counter()` / `c.get()` have to be
# recognised as operations on an IMPORTED type rather than as calls to
# unknown free functions.
STRUCT_LIB = """\
struct Counter:
  var n: Int
  fn get(self) -> Int:
    return self.n
  fn bumped(self) -> Int:
    return self.n + 1
"""

STRUCT_USER = """\
from slib import Counter

def main() -> Int:
  var c = Counter()
  c.n = 10
  return c.get() + c.bumped()
"""


def test_struct_method_across_modules(tmpdir, _shared):
    root = os.path.join(tmpdir, "structmod")
    os.makedirs(root)
    write_tree(root, {"slib.mojo": STRUCT_LIB, "user.mojo": STRUCT_USER})
    fresh_cas()
    _result, out = build(root, "user.aout")
    code, err = run(out)
    check(code == 21, f"cross-module struct use returned {code}, expected 21 "
                      f"(c.get() + c.bumped() with c.n = 10); stderr: {err}")
    dylib = module_dylib("slib")
    check(os.path.isfile(dylib), f"a struct-only module built no dylib at "
                                 f"{dylib}")
    names = sorted(e["name"] for e in manifest(dylib)["exports"])
    check(names == ["Counter_bumped", "Counter_get"],
          f"a struct-only module exported {names}; its methods ARE its API, "
          f"so exporting nothing makes it unbuildable and unimportable")
    with open(dylib, "rb") as f:
        info = parse_macho(f.read())
    for e in manifest(dylib)["exports"]:
        check("_" + e["symbol"] in info["exports"],
              f"the trie is missing the method export {e['symbol']}")


# A library that CONSTRUCTS its own struct.  `STRUCT_LIB` above declares one
# and only ever constructs it in the IMPORTER, so nothing in it exercises the
# library's own `Counter()` — and that omission is the whole of the gap this
# case covers: a struct crosses the boundary as a LAYOUT, not as a symbol
# (`reflect.emit_table_c` skips `SYM_TYPE` entries, so `_Counter` is never
# defined anywhere), while the codegen recognises an `S(...)` constructor by
# consulting the struct table it is HANDED.  On the dylib path that table was
# not handed over, so a constructor in the library's own body fell through the
# ordinary call path and became a BL against a symbol nothing defines, and the
# build failed with "the library would bind 1 symbol(s) that nothing provides:
# Counter" — a link-line diagnosis for a codegen omission, naming neither the
# constructor nor the file.
SELF_CTOR_LIB = """\
struct Counter:
  var n: Int
  var tag: Int

def make(n: Int) -> Int:
  var c = Counter()
  c.n = n
  c.tag = 1
  return c.n + c.tag

def make_static(n: Int) -> Int:
  var c = Counter()
  c.n = n
  c.tag = 2
  return c.n * 10 + c.tag
"""


def test_a_library_may_construct_its_own_struct(tmpdir, _shared):
    """`Counter()` inside the LIBRARY, which is a different thing from
    `Counter()` in the importer.

    The answer is asserted rather than the build succeeding, because a library
    that compiled the constructor to the WRONG value would link perfectly: the
    two library functions are separate symbols, so `make` being wrong cannot
    affect `make_static`, and only their sum pins both. Measured against
    CPython's own reading of the same three functions, which gives `make(10)`
    = 11, `make_static(10)` = 102 and the program 13.

    The `Counter()` in the importer is already covered by
    `test_struct_method_across_modules`; what is new here is the one INSIDE
    `make`/`make_static`, in the library's own compilation."""
    root = os.path.join(tmpdir, "selfctor")
    os.makedirs(root)
    write_tree(root, {
        "clib.mojo": SELF_CTOR_LIB,
        "cuser.mojo": ("from clib import make, make_static\n"
                       "\n"
                       "def main() -> Int:\n"
                       "  return make(10) + make_static(10) - 100\n"),
    })
    fresh_cas()
    _result, out = build(root, "cuser.aout")
    code, err = run(out)
    # 11 + 102 - 100 = 13, CPython's answer for the same three functions.
    check(code == 13,
          f"a library constructing its own struct returned {code}, expected 13 "
          f"(make(10)=11 and make_static(10)=102); stderr: {err}. If this "
          f"build refused with \"would bind 1 symbol(s) that nothing "
          f"provides: Counter\", the library's struct declarations did not "
          f"reach the emitter — a class crosses as a layout, so there is no "
          f"`Counter` symbol for the dangling call to have found.")


# A module that exports only a GENERIC, so the import has no symbol to bind.
# `generic_funcs` is `reflect.collect_exports_src`'s own exclusion
# (`re.findall(r'\b(?:fn|def)\s+(\w+)\s*\[', src)`), so the empty export set here
# is the real rule and not a hand-built shape — `doc/ABI.md`'s Generics section
# is explicit that a generic is not a single boundary symbol.
GENERIC_LIB = """\
def widen[T: Intable](v: T) -> T:
  return v

def helper(x: Int) -> Int:
  return x + 1
"""


def test_an_imported_generic_is_refused_as_an_export_gap(tmpdir, _shared):
    """A bare `widen(5)` must be refused naming the EXPORT RULE, and must not
    reach the link audit.

    Before, the bare spelling was exempted as a callee and emitted as a `BL`,
    and the build failed with

        the image would bind 1 symbol(s) that nothing provides: widen.
        … Deciding which is a question for the assembler, and it is asked
        nowhere in this backend

    — a message about the LINK LINE for a fact the build already knew, and one
    whose own text admits the question was never asked. The bare spelling is
    the one a reader is most likely to have written, so it is the one that was
    worst served.

    **The BRACKETED spelling is no longer in this case, and its leaving is the
    whole of `formal/monomorph.py`.**  This test used to assert that
    `widen[Int](5)` was refused too, on the reasoning that "which of the two
    messages it should carry is
    `FORMAL_bracketed_private_name_refused_as_a_specialization`'s
    subject and its own claim, so this test does not decide it" — i.e. it was
    never sure the refusal was the right answer, only that it was a refusal.
    The right answer is that a bracket says WHICH instantiation and a boundary
    symbol per instantiation is what `doc/ABI.md` §Generics calls for: the module
    now publishes `widen_Int`, the call binds it, and the program returns 5.
    `test_formal_monomorph.py` is where that is pinned, with a CPython
    differential; the case here is the half that stays refused, and it is the
    half that cannot be answered by any amount of monomorphization: a BARE
    `widen(5)` says no instantiation at all, so no trie entry could mean it."""
    root = os.path.join(tmpdir, "genericcallee")
    os.makedirs(root)
    write_tree(root, {
        "glib.mojo": GENERIC_LIB,
        "guser.mojo": ("from glib import widen\n"
                       "\n"
                       "def main() -> Int:\n"
                       "  return widen(5)\n"),
        "gbrack.mojo": ("from glib import widen\n"
                        "\n"
                        "def main() -> Int:\n"
                        "  return widen[Int](5)\n"),
    })
    fresh_cas()
    result = run_fire(["build", "--formal", "--no-prove",
                       "-o", os.path.join(tmpdir, "guser.aout"),
                       os.path.join(root, "guser.mojo")], cwd=root)
    text = (result.stderr or "") + (result.stdout or "")
    check(result.returncode != 0,
          f"guser.mojo BUILT: a call to a generic the exporting module keeps "
          f"off the boundary cannot bind, so an image that compiled is an image "
          f"with a dangling call in it")
    check("binds 1 symbol(s) that nothing provides" not in text,
          f"guser.mojo reached the LINK AUDIT, which names the link "
          f"line rather than the export rule that emptied it: "
          f"{text.strip()[-400:]}")
    # …and it must name the rule.
    check("does not export it" in text and "widen" in text,
          f"a bare call to an imported generic must be refused as an export "
          f"gap naming the name: {text.strip()[-400:]}")
    # …and the bracketed spelling of the SAME call, in the same file with the
    # same import, must not be.  `doc/ABI.md` §Generics: a generic is not one
    # symbol, each instantiation is; the bracket says which, so there is a symbol
    # to bind and the two must not get the same verdict.
    result = run_fire(["build", "--formal", "--no-prove",
                       "-o", os.path.join(tmpdir, "gbrack.aout"),
                       os.path.join(root, "gbrack.mojo")], cwd=root)
    check(result.returncode == 0,
          f"gbrack.mojo was refused, and `widen[Int](5)` names the "
          f"instantiation it wants: {((result.stderr or '') + (result.stdout or '')).strip()[-400:]}")


def test_a_bare_call_to_an_exported_name_still_binds(tmpdir, _shared):
    """The control for the case above, and the guard on its scope.

    `helper(5)` is a bare callee in the same position as `widen(5)`, in the same
    module, differing only in that `helper` IS exported. The new refusal asks
    "does any library on this link line publish this name", so a predicate that
    had drifted to "is this name imported" — or that read the manifests a
    second way and got a different answer than the emitter — would refuse a
    program that works. It builds, RUNS, and returns 7 (= 5 + 1, plus the 1 the
    program adds)."""
    root = os.path.join(tmpdir, "genericctl")
    os.makedirs(root)
    write_tree(root, {
        "glib.mojo": GENERIC_LIB,
        "gctl.mojo": ("from glib import helper\n"
                      "\n"
                      "def main() -> Int:\n"
                      "  return helper(5) + 1\n"),
    })
    fresh_cas()
    _result, out = build(root, "gctl.aout")
    code, err = run(out)
    check(code == 7,
          f"a bare call to an exported name returned {code}, expected 7; "
          f"stderr: {err}")


def test_one_word_struct_field_is_the_value(tmpdir, _shared):
    """`c.n` and `c` must be the SAME word for a one-field struct.

    They are not by construction: a field write lands in a slot keyed by the
    access path (`c.n`) while the method receives `c`. If those are two
    different slots the method reads the constructor's zero and every
    accessor returns a constant — a program that builds, runs, and computes
    the wrong answer, with no diagnostic anywhere. So this asserts the value,
    not merely that it runs."""
    src = os.path.join(tmpdir, "field.mojo")
    with open(src, "w") as f:
        f.write("struct Box:\n  var v: Int\n"
                "  fn get(self) -> Int:\n    return self.v\n"
                "def main() -> Int:\n"
                "  var b = Box()\n  b.v = 41\n  return b.get() + 1\n")
    out = os.path.join(tmpdir, "field.aout")
    rc = run_fire(["build", "--formal", "--no-prove", "-o", out, src]).returncode
    check(rc == 0, f"build failed: {rc}")
    r = subprocess.run([out], capture_output=True, text=True, timeout=RUN_TIMEOUT_S)
    check(r.returncode == 42,
          f"returned {r.returncode}, expected 42 — if this is 1, the field "
          f"and the receiver are different storage and the accessor is "
          f"returning the constructor's zero")


WIDE_SRC = ("struct Pair:\n  var a: Int\n  var b: Int\n"
            "  fn get_a(self) -> Int:\n    return self.a\n"
            "  fn set_a(self, v: Int):\n    self.a = v\n"
            "def main() -> Int:\n  var p = Pair()\n  p.set_a(6)\n"
            "  return p.get_a()\n")


def test_wide_struct_is_refused_with_the_switch_off(tmpdir, _shared):
    """With the by-reference receiver OFF, a wide struct is still refused.

    It used to reach the call path and become a BL against a symbol named
    after the type, so the image built and then aborted in dyld with
    "Symbol not found" — a loader failure pointing at a compile-time limit.
    The limit is now a switch rather than a wall, so the refusal is a property
    of the switch's OFF setting and this is the test that says so; with the
    switch on (the default) the same source builds and runs, which
    `test_wide_struct_runs_by_reference` covers. A switch nobody ever exercises
    is not a switch, it is a constant."""
    src = os.path.join(tmpdir, "wide.mojo")
    with open(src, "w") as f:
        f.write(WIDE_SRC)
    out = os.path.join(tmpdir, "wide.aout")
    result = run_fire(["build", "--formal", "--no-prove", "-o", out, src],
                      env={"MOJO_FORMAL_WIDE_RECEIVER": "0"})
    check(result.returncode != 0,
          "a two-field struct was accepted with the by-reference receiver off")
    text = result.stderr + result.stdout
    check("Pair" in text and "word" in text,
          f"the refusal should name the struct and the limit: {text[-300:]}")
    check("dyld" not in text and "Symbol not found" not in text,
          f"this must fail at compile time, not in the loader: {text[-300:]}")


def test_wide_struct_runs_by_reference(tmpdir, _shared):
    """A two-field struct builds, RUNS, and gets the right answer.

    The receiver is the ADDRESS of a frame of two 8-byte slots, which is still
    one word, so the value model is untouched and the accessor sees the write
    the method made. The exit status is the assertion: 6, and a build that
    quietly computed 0 would be the exact failure the one-word lowering had
    (a method-local slot nothing ever wrote)."""
    src = os.path.join(tmpdir, "wide_on.mojo")
    with open(src, "w") as f:
        f.write(WIDE_SRC)
    out = os.path.join(tmpdir, "wide_on.aout")
    result = run_fire(["build", "--formal", "--no-prove", "-o", out, src])
    check(result.returncode == 0,
          f"a two-field struct should build by reference: "
          f"{(result.stderr or result.stdout).strip()[-300:]}")
    run = subprocess.run([out], capture_output=True, text=True, timeout=RUN_TIMEOUT_S)
    check(run.returncode == 6,
          f"exit status {run.returncode}, expected 6 (the value the method "
          f"wrote through the receiver)")


# ── a module's identity is a function of its SOURCE, not of who reached it ──
#
# `build_module_dylib` takes a `_parent` to resolve a relative import against,
# and nothing computed it: `_resolve_imports` called it with no parent at all.
# A relative import AT THE ROOT — which is what `formal/hostmods/os/path/
# __init__.mojo`'s `.._syscalls` is — therefore resolved differently depending
# on the spelling that reached the file. Built on its own it became
# `___syscalls.<digest>.arm64.dylib` exporting `___syscalls_fs_chdir_9f63a2`;
# reached as `.path` from `os/__init__.mojo` in the same process it became
# `__syscalls.<digest>.arm64.dylib` exporting `__syscalls_fs_chdir_9f63a2`.
#
# Nothing failed, which is why it survived: `_BUILT` is keyed by resolved path
# and every consumer reads the manifest beside the library that was actually
# built. But `build_module_dylib`'s own comment says the source digest in the
# filename "is what makes sharing safe rather than merely rare", and for this
# module the ARTIFACT depended on the spelling rather than on the source, so
# the digest stopped being sufficient to identify it. Two processes building
# the same tree in a different order got different libraries for one file.

def test_own_module_identity_is_the_package_chain(tmpdir, _shared):
    """`own_module_identity` names a file by its package chain.

    A pure function of the PATH, so it is worth pinning on its own rather than
    only through a build: the property is "the same file always gets the same
    name", and a build that succeeds either way cannot demonstrate it."""
    from formal.imports import own_module_identity
    root = os.path.join(tmpdir, "ident")
    write_tree(root, {
        "os/__init__.mojo": "pass\n",
        "os/_syscalls.mojo": "def chdir(p):\n  return 0\n",
        "os/path/__init__.mojo": "from .._syscalls import chdir\n",
        "sys.mojo": "def getargv():\n  return 0\n",
    })
    want = {
        "os/__init__.mojo": "os",
        "os/_syscalls.mojo": "os._syscalls",
        "os/path/__init__.mojo": "os.path",
        # No package anywhere above it, so the roots decide — and this is the
        # case that is `sys` rather than `ident.sys`, which is what an importer
        # spelling `import sys` needs.
        "sys.mojo": "sys",
    }
    for rel, expected in want.items():
        got = own_module_identity(os.path.join(root, rel),
                                  os.path.join(root, "prog.mojo"))
        check(got == expected,
              f"{rel} is addressed as {got!r}, expected {expected!r}")
    # And the identity does not depend on the ARGUMENT. Every call site passes
    # the file being compiled as its own project root, so a root that varied
    # with it would reintroduce the instability this exists to remove.
    a = own_module_identity(os.path.join(root, "os/_syscalls.mojo"),
                            os.path.join(root, "prog.mojo"))
    b = own_module_identity(os.path.join(root, "os/_syscalls.mojo"),
                            os.path.join(root, "os/path/__init__.mojo"))
    check(a == b == "os._syscalls",
          f"the identity moved with the project root: {a!r} then {b!r}")
    # A non-Mojo file has no module identity to give, and answering with a name
    # would put a `.py` basename into a C prefix.
    check(own_module_identity(os.path.join(root, "helper.py"), root) is None,
          "a .py file was given a module identity")


def test_a_relative_import_at_the_root_builds_one_library(tmpdir, _shared):
    """The end-to-end half: `.._syscalls` inside `os/path` links and RUNS.

    The behaviour, not the spelling — a build that produced a different library
    for the same source would still pass this, which is what
    `test_own_module_identity_is_the_package_chain` above is for. What this
    pins is that qualifying a root-relative import against the importer's own
    identity did not break the resolution: `.._syscalls` from inside the
    package `os.path` is the module `os._syscalls`, and the call through it
    arrives with the right answer."""
    root = os.path.join(tmpdir, "rootrel")
    write_tree(root, {
        "os/__init__.mojo": "pass\n",
        "os/_syscalls.mojo": "def chdir(p):\n  return 41 + 1\n",
        "os/path/__init__.mojo": (
            "from .._syscalls import chdir\n"
            "def go(p):\n  return chdir(p)\n"),
        "prog.mojo": ("from os.path import go\n"
                      "def main():\n  return go(\"/\")\n"),
    })
    fresh_cas()
    _result, out = build(root, "prog.aout")
    code, err = run(out)
    check(code == 42, f"returned {code}, expected 42; stderr: {err}")


# ── a package whose API is its re-exports ───────────────────────────────────
#
# A `pkg/__init__.mojo` that is nothing but `from .sub import name` has a
# real, public, importable API — and used to be refused as "a struct-only
# module has no free-function API", which took down every file that imports
# the PACKAGE, over a module with nothing wrong with it. That is most of the
# stdlib: std/stat, std/atomic, std/ffi, std/sys, std/reflection and the rest
# are all re-export-only `__init__` files. Every stdlib `__init__` the sweep
# refused was refused for this reason.

REEXPORT_PKG = """\
from .sub import bump
from .sub import Box
"""

REEXPORT_SUB = """\
def bump(x):
  return x + 2


struct Box:
  var v: Int
"""

REEXPORT_PROG = """\
from pkg import bump
def main():
  return bump(40)
"""


def test_package_reexport_builds_and_runs(tmpdir, _shared):
    """`from pkg import bump`, where pkg only re-exports, builds and RUNS.

    The test that would have caught the original bug: a dylib that builds is
    not a result, an importing program that builds, loads and returns the
    right value is. It failed before the fix with
    "__init__.mojo: formal dylib has no public functions", even though
    `bump` was right there in `pkg/sub.mojo`, compiled, exported, and already
    on this program's link line.
    """
    root = os.path.join(tmpdir, "reexport")
    os.makedirs(root)
    write_tree(root, {"pkg/__init__.mojo": REEXPORT_PKG,
                      "pkg/sub.mojo": REEXPORT_SUB,
                      "prog.mojo": REEXPORT_PROG})
    fresh_cas()
    _result, out = build(root, "prog.aout")
    code, err = run(out)
    check(code == 42, f"a re-exported function returned {code}, expected 42; "
                      f"stderr: {err}")


def test_namespace_library_exports_nothing(tmpdir, _shared):
    """The package's own dylib exports NOTHING, and says it is a namespace.

    This is the half of the re-export fix that has to be right in the
    restrictive direction. A re-export is not a new definition, so the symbol
    must NOT be copied into the package's export trie: the trie is an ADDRESS
    lookup, and an entry for a symbol this image does not contain sends every
    consumer of the package to an address inside a file with no code. The
    names resolve through the submodule's own manifest, which is on the same
    link line — so the correct export table here is the empty one, and the
    only thing that must be right about it is that it is empty.
    """
    root = os.path.join(tmpdir, "ns")
    os.makedirs(root)
    write_tree(root, {"pkg/__init__.mojo": REEXPORT_PKG,
                      "pkg/sub.mojo": REEXPORT_SUB,
                      "prog.mojo": REEXPORT_PROG})
    fresh_cas()
    _result, _out = build(root, "prog.aout")
    pkg = module_dylib("pkg")
    check(os.path.isfile(pkg), f"no package dylib at {pkg}")
    m = manifest(pkg)
    check(m.get("kind") == "namespace",
          f"the package dylib is not marked namespace: {m.get('kind')!r}")
    check(m.get("exports") == [],
          f"the package dylib exports {m.get('exports')!r}; a re-export is "
          f"not a definition, so its export table must be empty — an entry "
          f"here is an address lookup into an image that has no code")
    check("bump" in (m.get("reexports") or {}),
          f"the re-export is not recorded in the manifest: "
          f"{m.get('reexports')!r}")
    # And the trie itself, read independently of the writer.
    with open(pkg, "rb") as f:
        info = parse_macho(f.read())
    check(info["exports"] == {},
          f"the package dylib's export trie is not empty: {info['exports']}")
    # The definition is in the submodule, which is where a consumer must find
    # it — so the submodule's trie must really carry it. The submodule's
    # dylib is found through the package manifest's own `depends_on` rather
    # than by guessing its file name: a relative import spells its module name
    # `.sub`, and the file name is derived from that.
    deps = m.get("depends_on") or []
    check(len(deps) == 1 and deps[0]["source"].endswith("sub.mojo"),
          f"the package dylib does not record its submodule: {deps}")
    sub = module_dylib("pkg_sub")
    if not os.path.isfile(sub):
        found = [n for n in os.listdir(cas_imports()) if n.endswith(".dylib")]
        check(False, f"no submodule dylib at {sub}; the directory holds "
                     f"{found}")
    with open(sub, "rb") as f:
        sub_info = parse_macho(f.read())
    sym = [e["symbol"] for e in manifest(sub)["exports"]
           if e["name"] == "bump"][0]
    check("_" + sym in sub_info["exports"],
          f"the submodule's trie does not carry {sym}; the re-exported name "
          f"has nothing to resolve to")


# A package body that is a DOCSTRING, which is what `formal/__init__.py` is and
# what a docs-only package is. Measured on the 2026-10-03 sweep
# (`bugs/sweeps/sweep-arm-8.txt`): the export gate refused it as "declares no
# function and no type at all", which took out three repository files that
# import the PACKAGE (`from formal import model as M`) and name nothing it
# publishes.
#
# The program's spelling is load-bearing and measured, not chosen: `import pkg`
# is what puts the PACKAGE in the importer's closure and so what makes its dylib
# get built, while `from pkg.sub import bump` does not build it at all (the
# closure holds the submodule) and `from pkg import sub` builds it and is then
# refused for binding a module as a value — a different refusal, further on, and
# not this gate's business.
EMPTY_BODY_PKG = '"""A namespace package: the API is the submodules."""\n'
SUBMODULE_ONLY_MODULE = """\
def bump(x):
  return x + 2
"""
EMPTY_BODY_PROG = """\
import pkg
import pkg.sub
def main():
  return 42
"""
PKG_ATTRIBUTE_PROG = """\
import pkg
def main():
  return pkg.bump(40)
"""


def test_a_docstring_only_package_is_a_namespace_library(tmpdir, _shared):
    """A package `__init__` that declares nothing builds, and a consumer of it
    builds, LOADS and RUNS.

    The positive half, and the RUN is the point: a dylib that builds is not a
    result. The package's library is on this program's link line with an empty
    trie, so `return 42` is also the statement that dyld can load a namespace
    library and the program still starts.
    """
    root = os.path.join(tmpdir, "emptybody")
    os.makedirs(root)
    write_tree(root, {"pkg/__init__.mojo": EMPTY_BODY_PKG,
                      "pkg/sub.mojo": SUBMODULE_ONLY_MODULE,
                      "prog.mojo": EMPTY_BODY_PROG})
    fresh_cas()
    result, out = build(root, "prog.aout")
    check(result.returncode == 0,
          f"a consumer of a docstring-only package did not build: "
          f"{(result.stderr or result.stdout or '').strip()[-400:]}")
    rc, text = run(out)
    check(rc == 42,
          f"the program did not run to its own return value (exit {rc}): "
          f"{text!r}")


def test_a_docstring_only_package_dylib_is_empty_and_says_namespace(
        tmpdir, _shared):
    """The restrictive half, read off the artifact rather than off the exit code.

    An empty trie is the DESIGN here and not a side effect: the package defines
    nothing, so any entry in its export table would be an address lookup into an
    image with no code. And `kind: "namespace"` is what makes
    `load_dylib_manifests` accept an empty `exports` list at all, so this is
    the fact a later edit has to preserve.
    """
    root = os.path.join(tmpdir, "emptybody2")
    os.makedirs(root)
    write_tree(root, {"pkg/__init__.mojo": EMPTY_BODY_PKG,
                      "pkg/sub.mojo": SUBMODULE_ONLY_MODULE,
                      "prog.mojo": EMPTY_BODY_PROG})
    fresh_cas()
    _result, _out = build(root, "prog.aout")
    pkg = module_dylib("pkg")
    check(os.path.isfile(pkg), f"no package dylib at {pkg}")
    m = manifest(pkg)
    check(m.get("kind") == "namespace",
          f"the package dylib is not marked namespace: {m.get('kind')!r}")
    check(m.get("exports") == [],
          f"a package that declares nothing exports {m.get('exports')!r}")
    with open(pkg, "rb") as f:
        info = parse_macho(f.read())
    check(info["exports"] == {},
          f"the package dylib's export trie is not empty: {info['exports']}")


def test_a_name_the_empty_package_does_not_declare_is_still_refused(
        tmpdir, _shared):
    """The protective half, and the one that must not regress.

    The package now builds, so the question is what happens to a consumer that
    asks it for something. `pkg.bump` has to be a REFUSAL naming the package —
    not an empty trie read as "nothing there, fine", and above all not a bind
    to some other library's `bump`. This is the failure the export gate exists
    to prevent, and widening the gate must not have widened it.
    """
    root = os.path.join(tmpdir, "emptybody3")
    os.makedirs(root)
    write_tree(root, {"pkg/__init__.mojo": EMPTY_BODY_PKG,
                      "pkg/sub.mojo": SUBMODULE_ONLY_MODULE,
                      "prog.mojo": PKG_ATTRIBUTE_PROG})
    fresh_cas()
    result, _out = build(root, "prog.aout", expect_ok=False)
    check(result.returncode != 0,
          "`pkg.bump` bound against a package that declares nothing; the "
          "trie is empty, so whatever it resolved to is not this package's")
    text = result.stderr or result.stdout
    check("pkg" in text,
          f"the refusal does not name the package: {text.strip()[-300:]}")


def test_a_package_that_declares_something_is_still_refused(tmpdir, _shared):
    """The other side of the predicate, and it is three shapes.

    `formal/build.py`'s branch fires on a package that declares NOTHING, so
    each of these has to keep its own refusal: a generic-only body (one trie
    entry cannot be two instantiations), a body whose only declaration is
    private, and a body whose names are all C library symbols. Without the
    `_declared_api_shape` test the branch swallowed all three, and the
    generic-only module test at the end of this file went red — which is why
    that row exists and why the three are named here.

    The program imports the package itself (`from pkg import widen`), which is
    the spelling that makes the package's dylib get built at all; with
    `import pkg.sub` there is no package library to refuse and the case would
    pass vacuously.

    **AND IT CALLS THE NAME**, which is the whole difference from 2026-10-04 and
    the reason the `gen` row's expected wording changed. The per-edge rule
    (`formal/imports.py::library_free_edges`) exempts an edge that binds nothing
    but templates, so a package whose body is one generic template, imported by
    a program that never calls it, now builds — and there is nothing to assert
    about a refusal there. Calling it puts the edge back in the shape the gate
    exists for: a bare call to a template has no callee, and the refusal comes
    from the IMPORTER (`imported_callee_refusal`, naming `widen`) rather than
    from the module's own gate. The other two shapes are unaffected: `widen` is
    not a name either of them declares, so their edges keep their library and
    their own sentences.
    """
    cases = {
        "gen": ("def widen[T: Intable](v: T) -> T:\n  return v\n",
                "does not export it"),
        "private": ("def _hidden(x):\n  return x\n", "private"),
        "clib": ("def exit(x):\n  return x\n", "C library symbol"),
    }
    for tag, (body, expect) in sorted(cases.items()):
        root = os.path.join(tmpdir, "notempty_" + tag)
        os.makedirs(root)
        write_tree(root, {"pkg/__init__.mojo": body,
                          "prog.mojo": "from pkg import widen\n"
                                      "def main():\n  return widen(1)\n"})
        fresh_cas()
        result, _out = build(root, "prog.aout", expect_ok=False)
        text = result.stderr or result.stdout
        check(result.returncode != 0,
              f"a package whose body is {tag!r} built; it declares a name a "
              f"reader might have wanted to bind, which is a finding and not "
              f"a namespace package")
        check(expect in text,
              f"the {tag!r} refusal does not say {expect!r}: "
              f"{text.strip()[-300:]}")


def test_reexport_of_an_unexported_name_is_refused(tmpdir, _shared):
    """A re-export nothing provides is refused, naming the name.

    The protective half. If this were waved through, the package would build,
    the consumer's call to `hidden` would stay unbound, and the failure would
    move from this build to dyld at launch — a build error traded for a
    program that dies before `main`, which is the one trade this whole import
    mechanism exists to refuse. `hidden` is private in `sub.mojo`, so
    doc/ABI.md keeps it out of the boundary and there is nothing to forward.
    """
    root = os.path.join(tmpdir, "badreexport")
    os.makedirs(root)
    write_tree(root, {
        "pkg/__init__.mojo": "from .sub import hidden\n",
        "pkg/sub.mojo": "def _hidden(x):\n  return x\n",
        "prog.mojo": "from pkg import hidden\ndef main():\n  return hidden(1)\n",
    })
    fresh_cas()
    result, _out = build(root, "prog.aout", expect_ok=False)
    check(result.returncode != 0,
          "a package re-exporting a name nothing exports built successfully")
    text = (result.stderr or result.stdout)
    check("hidden" in text,
          f"the refusal does not name the unforwardable name: "
          f"{text.strip()[-300:]}")


# The three files of the aliased re-export, written out rather than built from
# the REEXPORT_* constants above because the ALIAS is the whole subject: reusing
# those would put a `from .sub import bump as …` line in a tree whose other
# tests assert on `bump` by name, and the difference between the two is exactly
# what has to be visible here.
ALIAS_LEAF = """\
def base(x):
  return x * 2
"""

ALIAS_PKG = """\
from leaf import base as aliased
"""

ALIAS_PROG = """\
from pkg import aliased
def main():
  return aliased(21)
"""


def test_aliased_reexport_binds_under_both_spellings(tmpdir, _shared):
    """`from leaf import base as aliased`, re-exported, binds as `aliased`.

    The bug this is the regression test for was one of NAME, not of kind: the
    package's manifest published the name the DEFINING module gave the symbol
    (`base`) and not the name every consumer of the package actually writes
    (`aliased`), so the program's call reached the bind audit as a symbol
    nothing provides and the build refused an image that was correct Mojo. The
    refusal was right; the manifest was wrong.

    BOTH spellings are in the program on purpose, which is what makes this a
    test of ADDITIVENESS rather than of a substitution. The original name is
    still published — an export is matched against a library's export set by the
    defining name, and a package that stopped publishing `base` would break
    every consumer that asks for it. So the two calls must agree, and the guard
    is that a change that quietly became SUBTRACTIVE fails here rather than in
    some importer nobody was looking at.
    """
    prog = ("from pkg import aliased\n"
            "from leaf import base\n\n"
            "def main():\n"
            "  printf(\"a=%d b=%d|\", aliased(21), base(21))\n"
            "  return aliased(21)\n")
    root = os.path.join(tmpdir, "alias")
    os.makedirs(root)
    write_tree(root, {"leaf/__init__.mojo": ALIAS_LEAF,
                      "pkg/__init__.mojo": ALIAS_PKG,
                      "prog.mojo": prog})
    fresh_cas()
    _result, out = build(root, "prog.aout")
    code, err = run(out)
    check(code == 42, f"the aliased re-export returned {code}, expected 42; "
                      f"stderr: {err}")
    check("a=42 b=42|" in err,
          f"the two spellings of one re-export disagree: {err.strip()!r}")

    # The manifest, which is where the defect was. Both keys, both pointing at
    # the DEFINITION's symbol, and `defines` naming the name it was found under
    # so a reader can tell an alias from a definition.
    m = manifest(module_dylib("pkg"))
    fwd = m.get("reexports") or {}
    check(set(fwd) == {"base", "aliased"},
          f"the package publishes {sorted(fwd)}; an aliased re-export has to "
          f"publish the name consumers write AND the name the definition has, "
          f"or one of the two spellings cannot resolve: {fwd!r}")
    leaf_sym = [e["symbol"] for e in manifest(module_dylib("leaf"))["exports"]
                if e["name"] == "base"]
    check(leaf_sym, f"the leaf library exports no `base`: "
                    f"{manifest(module_dylib('leaf'))['exports']!r}")
    for spelling in ("base", "aliased"):
        check(fwd[spelling].get("symbol") == leaf_sym[0],
              f"`{spelling}` forwards {fwd[spelling].get('symbol')!r} but the "
              f"definition is {leaf_sym[0]!r}; a re-export must bind the "
              f"DEFINITION, or two spellings of one function are two "
              f"addresses")
    check(fwd["aliased"].get("defines") == "base",
          f"the alias does not record the name it stands for: "
          f"{fwd['aliased']!r}")
    check(fwd["base"].get("defines") == "base",
          f"a plain re-export records something other than its own name: "
          f"{fwd['base']!r}")


def test_aliased_reexport_runs_on_both_architectures(tmpdir, _shared):
    """The same aliased tree builds and RUNS on arm64 and on x86-64.

    The resolution table (`model.dylib_aliased_export`) is one shared function,
    but the emitters that consult it are two files with two copies of the
    question, so one architecture passing is not evidence about the other — and
    the failure mode when the second is wrong is a link error, not a wrong
    answer, so nothing else in this file would report it.
    """
    for arch in ("arm64", "x86_64"):
        root = os.path.join(tmpdir, f"alias_{arch}")
        os.makedirs(root)
        write_tree(root, {"leaf/__init__.mojo": ALIAS_LEAF,
                          "pkg/__init__.mojo": ALIAS_PKG,
                          "prog.mojo": ALIAS_PROG})
        fresh_cas()
        _result, out = build(root, "prog.aout", arch=arch)
        code, err = run(out)
        check(code == 42, f"[{arch}] the aliased re-export returned {code}, "
                          f"expected 42; stderr: {err}")


def test_a_private_name_aliased_public_stays_unpublished(tmpdir, _shared):
    """`from x import _priv as pub` publishes NOTHING, exactly as before.

    The guard for the alias filter. A private definition cannot cross the
    boundary at all — `doc/ABI.md` keeps a leading `_` out of the export set —
    so a package that re-exports one under a public name has no symbol to
    forward, and the honest answers are the two this test pins: the manifest
    does not claim to publish it, and a caller is still refused BY NAME rather
    than bound to something. Publishing `pub` here would be worse than the
    original bug: it would make the name resolve and call a symbol that is not
    in the image.
    """
    root = os.path.join(tmpdir, "alias_private")
    os.makedirs(root)
    write_tree(root, {
        "leaf/__init__.mojo": "def _hidden(x):\n  return x\n",
        "pkg/__init__.mojo": "from leaf import _hidden as pub\n",
        "prog.mojo": "from pkg import pub\ndef main():\n  return pub(1)\n",
    })
    fresh_cas()
    result, _out = build(root, "prog.aout", expect_ok=False)
    check(result.returncode != 0,
          "a package re-exporting a private definition under a public alias "
          "built successfully, so a caller of `pub` has nothing to bind")
    text = result.stderr or result.stdout
    check("pub" in text,
          f"the refusal does not name the published spelling: "
          f"{text.strip()[-300:]}")


def test_a_relative_import_keeps_private_declarations_out_of_the_trie(
        tmpdir, _shared):
    """`doc/ABI.md`'s privacy rule holds at the RELATIVE boundary too.

    The claim this pins down was that a relative import's dylib mangles a
    private name into its export table with the underscores intact, so the
    image binds a symbol the library exports and a private function of one
    module is callable from another. The underscorING is real — it is dyld's,
    applied to every C symbol — and the rule is applied: a module reached
    through `from ._helper import twice` exports `twice` and exports neither
    `_hidden` nor `__secret`, which is the same answer a top-level module gets
    for the same pair. So the leak is not there.

    What is checked is the TRIE and not the manifest, and separately, because
    the manifest is what the build believes it published and the trie is what
    dyld will actually resolve: a name in the manifest and not in the trie is
    an unbound bind, and a name in the trie and not in the manifest is the
    leak. Reading it with `parse_macho` rather than with the writer's own
    reader is `test_a_package_dylib_exports_nothing`'s reason: asking the
    writer to read its own output is how a writer's bug becomes invisible.

    The last check is the invariant the export table is read against, and it
    is what makes "the name has an underscore in it" meaningless on its own:
    a Mach-O export is `"_"` + the C symbol, every one, so the trie name is
    never evidence about privacy and the bind name is the C symbol without
    dyld's one underscore."""
    root = os.path.join(tmpdir, "relprivacy")
    os.makedirs(root)
    write_tree(root, {
        "relpkg/_helper.mojo": (
            "def twice(a: Int) -> Int:\n  return a + a\n\n"
            "def _hidden(a: Int) -> Int:\n  return a\n\n"
            "def __secret(a: Int) -> Int:\n  return a - a\n"),
        "relpkg/__init__.mojo": (
            "from ._helper import twice\n\n"
            "def main(n: Int) -> Int:\n  return twice(21)\n"),
    })
    fresh_cas()
    # The package's `__init__.mojo` is the program, so the build names it
    # directly — `build()` derives the source from the output's file name, and
    # the entry point here is `relpkg/__init__.mojo`.
    out = os.path.join(root, "prog.aout")
    result = run_fire(["build", "--formal", "--no-prove", "-o", out,
                       os.path.join(root, "relpkg", "__init__.mojo")],
                      cwd=root)
    check(result.returncode == 0,
          f"the relative import did not build: "
          f"{(result.stderr or result.stdout).strip()[-400:]}")
    code, err = run(out)
    check(code == 42,
          f"the relative import did not run (returned {code}): {err}")
    sub = module_dylib("relpkg__helper")
    if not os.path.isfile(sub):
        found = sorted(os.listdir(cas_imports()))
        check(False, f"no library for the relative module at {sub}; the "
                     f"directory holds {found}")
        return
    with open(sub, "rb") as f:
        info = parse_macho(f.read())
    trie = info["exports"]
    published = [e["name"] for e in manifest(sub)["exports"]]
    check("twice" in published,
          f"the public function is not published: {published}")
    for private in ("_hidden", "__secret"):
        check(private not in published,
              f"{private} is in the module's published exports: {published}")
        check(not any(private in n for n in trie),
              f"{private} reached the export trie as one of {sorted(trie)}")
    for e in manifest(sub)["exports"]:
        check("_" + e["symbol"] in trie,
              f"the trie does not carry the C symbol {e['symbol']!r} for "
              f"export {e['name']!r}, so the caller's bind has nothing to "
              f"resolve to")
        check(not e["symbol"].startswith("_"),
              f"the published C symbol {e['symbol']!r} starts with an "
              f"underscore, which doc/ABI.md's export rule excludes")


def test_a_name_the_module_defines_wins_over_its_own_import(tmpdir, _shared):
    """`from leaf import base as g` beside a local `def g` calls the LOCAL one.

    The precedence `imported_bound_names` and `import_bindings` both state, and
    the one case where recording an alias could have changed it: a name this
    module DEFINES is its definition, so a consumer binding `g` must get that
    body and not `base`'s. The two are given different answers on purpose
    (`x + 1` and `x * 2`), because a test that only checked the program built
    would pass with either body and say nothing about which one was called.

    `x * 2` would also be the WRONG ANSWER rather than a link failure, which is
    the shape this whole area has: the two are the same function under two
    names, and picking the wrong one is invisible to every check that is not a
    comparison of the two.
    """
    prog = ("from pkg import g\n\n"
            "def main():\n"
            "  printf(\"g=%d base=%d|\", g(3), base(3))\n"
            "  return g(3)\n")
    root = os.path.join(tmpdir, "alias_shadowed")
    os.makedirs(root)
    write_tree(root, {
        "leaf/__init__.mojo": ALIAS_LEAF,
        "pkg/__init__.mojo": ("from leaf import base as g\n"
                              "\n"
                              "def g(x):\n"
                              "  return x + 1\n"),
        "prog.mojo": prog,
    })
    fresh_cas()
    _result, out = build(root, "prog.aout")
    code, err = run(out)
    check(code == 4, f"`g(3)` returned {code}: the module's own definition of "
                     f"`g` is `x + 1` and the import's is `x * 2`, so the "
                     f"import shadowed a name this module defines; stderr: "
                     f"{err}")
    check("g=4 base=6|" in err,
          f"the two definitions of one name disagree: {err.strip()!r}")


def test_module_dylib_matches_the_programs_arch(tmpdir, _shared):
    """An x86-64 program's module dylibs are x86-64, and it RUNS.

    Run for BOTH arches from one test on purpose: arm64-only evidence proves
    nothing about x86-64 here, because the defect was a dylib built for one
    architecture and linked into a program for another. That combination
    builds, links, and passes every static check the toolchain makes — the
    only symptom is dyld refusing to load it, after the build has "succeeded".

    Two independent things had to be fixed for this to hold, and both are
    "a key that is not the thing being cached": `build_module_dylib` took an
    `arch` and never used it (the codegen and the Mach-O header were both
    hardwired to arm64), and it wrote every architecture's library to ONE path
    keyed by module name alone, so the two overwrote each other.
    """
    for arch, cputype in (("arm64", 0x0100000C), ("x86_64", 0x01000007)):
        root = os.path.join(tmpdir, f"arch_{arch}")
        os.makedirs(root)
        write_tree(root, {"mylib/__init__.mojo": LIB,
                          "prog.mojo": PROG})
        fresh_cas()
        _result, out = build(root, "prog.aout", arch=arch)
        for name in (os.path.basename(module_dylib("mylib", arch)),):
            path = os.path.join(cas_imports(arch), name)
            check(os.path.isfile(path),
                  f"[{arch}] no module dylib at {path}")
            with open(path, "rb") as f:
                head = f.read(8)
            check(struct.unpack_from("<I", head, 4)[0] == cputype,
                  f"[{arch}] {name} has cputype "
                  f"{struct.unpack_from('<I', head, 4)[0]}, expected "
                  f"{cputype}: the library was built for the wrong "
                  f"architecture")
        code, err = run(out)
        check(code == 42, f"[{arch}] returned {code}, expected 42; "
                          f"stderr: {err[-300:]}")


def test_both_arch_libraries_coexist(tmpdir, _shared):
    """Building for one architecture does not destroy the other's library.

    The overwrite half of the previous test, isolated: a program for the other
    architecture must still find a library of ITS OWN architecture at the path
    its own link line names. Before the per-architecture directory and the
    architecture in the file name, the second build replaced the first's file
    and the first program stopped loading.
    """
    roots = {}
    for arch in ("arm64", "x86_64"):
        root = os.path.join(tmpdir, f"coexist_{arch}")
        os.makedirs(root)
        write_tree(root, {"mylib/__init__.mojo": LIB, "prog.mojo": PROG})
        roots[arch] = root
    fresh_cas()
    _r, first = build(roots["arm64"], "prog.aout", arch="arm64")
    first_dylib = module_dylib("mylib")
    with open(first_dylib, "rb") as f:
        before = f.read()
    _r, second = build(roots["x86_64"], "prog.aout", arch="x86_64")
    with open(first_dylib, "rb") as f:
        after = f.read()
    check(before == after,
          f"building for x86_64 changed the arm64 library at {first_dylib}: "
          f"the two architectures share a path and overwrite each other")
    # And the arm64 program, built before the other architecture ran, still
    # runs — which is the symptom the overwrite actually caused.
    code, err = run(first)
    check(code == 42, f"the arm64 program stopped working after an x86-64 "
                      f"build: returned {code}; stderr: {err[-300:]}")
    code, err = run(second)
    check(code == 42, f"the x86-64 program returned {code}, expected 42; "
                      f"stderr: {err[-300:]}")


def test_the_library_is_published_atomically(tmpdir, _shared):
    """A reader never observes a library that is half-written or unsigned.

    The measured flake this pins. `~/.gmojo/cas/formal-imports/<arch>/` is one
    directory shared by every checkout on the machine, so a program linking
    `mylib`'s library runs while an unrelated worktree rebuilds that exact
    path. The publish used to be write → chmod → `codesign`, none of it atomic,
    and for the gap between the chmod and the signature the file on disk is a
    valid Mach-O with NO signature — which `dyld` refuses outright. Measured on
    this tree: a fixed image died with `dyld: Library not loaded … missing code
    signature` for roughly 1 run in 20 while sibling worktrees were building,
    and passed on either side of the window, which is why it presented as a
    flaky test rather than as a race.

    Driven the same way rather than argued: a reader is run in a tight loop
    across the whole publish, so any window at all shows up as a nonzero exit
    with a `dyld` complaint. The rebuilder runs in a subprocess so it is a
    genuinely separate writer, not an in-process one.
    """
    root = os.path.join(tmpdir, "atomic")
    os.makedirs(root)
    write_tree(root, {"mylib/__init__.mojo": LIB, "prog.mojo": PROG})
    fresh_cas()
    _r, prog = build(root, "prog.aout", arch="arm64")
    lib = module_dylib("mylib")

    # The rebuild, as its own process: a writer that recompiles and re-signs
    # the very path the reader below loads, over and over. It drives the real
    # `fire.py`, which is what a sibling worktree does anyway and is the honest
    # shape of the hazard.
    rebuilder = os.path.join(root, "rebuild.py")
    with open(rebuilder, "w") as f:
        f.write(
            "import os, subprocess, sys, time\n"
            f"root = {root!r}\n"
            "env = dict(os.environ)\n"
            f"env['GMOJO_HOME'] = {os.environ['GMOJO_HOME']!r}\n"
            f"fire = {FIRE!r}\n"
            "end = time.time() + int(sys.argv[1])\n"
            "while time.time() < end:\n"
            "    subprocess.run([sys.executable, fire, 'build', '--formal',\n"
            "                    '--no-prove', '-o',\n"
            "                    os.path.join(root, 'rebuild.aout'),\n"
            "                    os.path.join(root, 'prog.mojo')],\n"
            "                   capture_output=True, env=env, cwd=root)\n")
    writer = subprocess.Popen(
        [sys.executable, rebuilder, "25"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        bad = []
        runs = 0
        for _ in range(400):
            runs += 1
            code, err = run(prog)
            if code != 42:
                bad.append((code, (err or "").strip()[-200:]))
                if len(bad) >= 3:
                    break
    finally:
        writer.terminate()
        writer.wait(timeout=SIGTERM_REAP_S)
    if not bad:
        return
    raise TestFailure(
        f"{len(bad)} of {runs} runs of a program linking {lib} failed while "
        f"that library was being republished (expected 42). First: "
        + "; ".join(f"exit {c}: {e}" for c, e in bad[:3])
        + ". A library that is published in place is observable half-written; "
          "the publish has to be atomic.")


def test_the_library_path_names_the_compiler_too(tmpdir, _shared):
    """The cache key folds in the compiler, not only the module's source.

    The shared-CAS hazard this closes is about the COMPILER, not the source.
    Checkouts on this machine are routinely at different commits with
    byte-identical module sources, and `~/.gmojo/cas` is one directory for all
    of them: measured here, four sibling worktrees had five distinct
    `formal/build.py` digests behind a single `formal/hostmods/struct.mojo`
    digest, and they all wrote `struct.<src>.arm64.dylib`. Whichever finished
    last replaced the others' library, so a program could link against a
    library some other checkout's codegen produced — the wrong-artifact class
    the source digest was added to prevent, one level up.

    Asserted on the NAME, because that is the contract a stale library would
    break: the name must change when the compiler does. Simulating a compiler
    change is what makes this testable at all — the alternative is a second
    checkout, which no unit test may rely on.
    """
    import formal.imports as I
    root = os.path.join(tmpdir, "compkey")
    os.makedirs(root)
    write_tree(root, {"mylib/__init__.mojo": LIB, "prog.mojo": PROG})
    fresh_cas()
    _r, _p = build(root, "prog.aout", arch="arm64")
    first = module_dylib("mylib")

    # The rule itself, exercised directly: `module_dylib_path` is what decides
    # the name, so it is what has to change when the compiler does. Driving it
    # through `build` instead would only measure the in-process `_BUILT` cache,
    # which is keyed by (arch, source path) and hands the first build's path
    # straight back — a test that passes for the wrong reason.
    real_fp = cas.formal_fingerprint
    try:
        base = I.module_dylib_path(cas_imports("arm64"), "mylib",
                                   os.path.join(root, "mylib", "__init__.mojo"),
                                   "arm64")
        cas.formal_fingerprint = lambda: "f" * 40
        other = I.module_dylib_path(cas_imports("arm64"), "mylib",
                                    os.path.join(root, "mylib", "__init__.mojo"),
                                    "arm64")
    finally:
        cas.formal_fingerprint = real_fp
    if base == other:
        raise TestFailure(
            f"changing the compiler fingerprint left the library path at "
            f"{os.path.basename(base)!r}, so two checkouts at different commits "
            f"overwrite each other's library with an incompatible build")
    if os.path.basename(first) != os.path.basename(base):
        raise TestFailure(
            f"the built library is {os.path.basename(first)!r} but "
            f"module_dylib_path names {os.path.basename(base)!r}; the test "
            f"below would then be checking a path nothing publishes to")
    # And the fingerprint really is the compiler's, not a constant: two
    # different values must give two different names, which is the property a
    # sibling checkout relies on.
    try:
        cas.formal_fingerprint = lambda: "a" * 40
        third = I.module_dylib_path(cas_imports("arm64"), "mylib",
                                    os.path.join(root, "mylib", "__init__.mojo"),
                                    "arm64")
    finally:
        cas.formal_fingerprint = real_fp
    if third == other:
        raise TestFailure(
            "two DIFFERENT compiler fingerprints produced the same library "
            "path, so the compiler component is not actually in the key")


def test_reexported_type_reaches_the_importer(tmpdir, _shared):
    """A re-exported STRUCT TYPE is recognised as a type by the importer.

    The type half of the same bug. `from pkg import Box` resolves to
    `pkg/__init__.mojo`, which declares no struct — it re-exports one — so
    reading only the file the import NAME resolved to found nothing, and
    `Box()` in the importer lowered to a call to an undefined function. A
    package's API is its re-exports, so reaching a type means walking to the
    module that defines it.
    """
    sys.path.insert(0, HERE)
    import fire_compiler as F
    from formal.imports import imported_struct_defs
    root = os.path.join(tmpdir, "rextype")
    os.makedirs(root)
    write_tree(root, {"pkg/__init__.mojo": "from .sub import Box\n",
                      "pkg/sub.mojo": "struct Box:\n  var v: Int\n",
                      "prog.mojo": "from pkg import Box\n"
                                   "def main():\n  return 0\n"})
    prog = os.path.join(root, "prog.mojo")
    with open(prog) as f:
        stmts = F.Parser(F.py_tokenize(f.read())).with_filename(prog) \
                    .parse_module()
    names = [s.name for s in imported_struct_defs(prog, stmts,
                                                  project_root=prog)]
    check("Box" in names,
          f"a struct re-exported through a package is invisible to its "
          f"importer; imported_struct_defs found {names}")



# ── a name a package FORWARDS, filed by what DEFINES it ────────────────────
#
# The row above is the same defect one hop further out, and it is the
# `declared_kinds` half rather than the `imported_struct_defs` half:
# `test_reexported_type_reaches_the_importer` walks to the defining module so
# the importer can CONSTRUCT the type, and nothing walked for the KIND. So a
# name reached through the PACKAGE (`from pkg import Shape`, where `pkg/__init__`
# forwards it from `pkg/sub.mojo`) had no kind at all — `"unknown"` — and
# `"unknown"` is not `"type"`, so `formal/build.py::_namespace_library` put it in
# the set that must be provided AS A SYMBOL and refused the module.
#
# Measured on the tree's own stdlib, where it is `std/hashlib/hasher.mojo`'s
# `from std.collections import Span`: 221 import sites name a struct or trait
# through a package that re-exports it, and every one of them reached the symbol
# check as `"unknown"`. The message was false in every clause — "a real gap in
# that module's public API — a private, generic or overloaded definition" — on a
# name that is public, is not generic, and is not overloaded, and is a TYPE: a
# type has no symbol to be missing.
#
# So `declared_kinds` now follows the forwarding edge, with the build's own
# resolver and a hop bound. It can only turn `"unknown"` into a real kind, and
# the only kind that leaves the symbol check is `"type"`, so it can remove a
# refusal and cannot add one — which is what the negative beside it pins.

FORWARDED_SUB = ("struct Shape:\n"
                 "  var a: Int\n"
                 "\n"
                 "def keep() -> Int:\n"
                 "  return 1\n")
FORWARDED_PKG = "from .sub import Shape, keep\n"
FORWARDED_MID = ("from pkg import Shape\n"
                 "\n"
                 "trait Sized:\n"
                 "  fn area(self, s: Shape) -> Int:\n"
                 "    ...\n")
FORWARDED_PROG = "from pkg2.mid import Sized\n\ndef main():\n  return 1\n"


def test_declared_kinds_files_a_forwarded_name_by_its_definition(
        tmpdir, _shared):
    """The table itself, with no build: a forwarded name carries its kind.

    The cheapest possible statement of the rule, and the one that cannot rot
    with a layout change: `pkg/__init__.mojo` declares nothing at all, so
    before the fix every name it forwards was absent.
    """
    sys.path.insert(0, HERE)
    from formal.imports import declared_kinds
    root = os.path.join(tmpdir, "fwd")
    os.makedirs(root)
    write_tree(root, {"pkg/sub.mojo": FORWARDED_SUB,
                      "pkg/__init__.mojo": FORWARDED_PKG,
                      "pkg2/mid.mojo": FORWARDED_MID})
    kinds = declared_kinds(os.path.join(root, "pkg", "__init__.mojo"))
    check(kinds.get("Shape") == "type",
          f"a struct the package forwards is not filed as a type: {kinds!r}")
    check(kinds.get("keep") == "function",
          f"a function the package forwards must keep being filed as one, or "
          f"the missing-symbol check stops protecting a real gap: {kinds!r}")
    check("Ghost" not in kinds,
          f"a name nothing declares must stay absent: {kinds!r}")


def test_a_forwarded_type_is_not_demanded_as_a_symbol(tmpdir, _shared):
    """A module that imports a TYPE through a package builds, both arches.

    `pkg2/mid.mojo` is `hasher.mojo`'s shape: no free function, so it is built
    as a NAMESPACE library, and its API names a struct it reached through the
    package. Before the fix the build refused it with the missing-symbol message
    and every clause of that message was false. Both architectures, because the
    kind table is shared and the two emitters consult it separately — the same
    reason `test_aliased_reexport_runs_on_both_architectures` gives.
    """
    for arch in ("arm64", "x86_64"):
        root = os.path.join(tmpdir, f"fwd_{arch}")
        os.makedirs(root)
        write_tree(root, {"pkg/sub.mojo": FORWARDED_SUB,
                          "pkg/__init__.mojo": FORWARDED_PKG,
                          "pkg2/mid.mojo": FORWARDED_MID,
                          "prog.mojo": FORWARDED_PROG})
        fresh_cas()
        build(root, "prog.aout", arch=arch)


def test_a_forwarded_name_nothing_defines_is_still_refused(tmpdir, _shared):
    """The guard on the guard: following an edge must not forgive a real gap.

    `Ghost` is declared nowhere, so it stays absent, so it is still demanded as a
    symbol and still refused BY NAME. A change that resolved kinds more
    liberally — or that swallowed an unresolvable one as `"type"` — would let a
    package publish a name nothing defines, and the consumer's call would reach
    dyld unbound, which is the outcome `formal/build.py`'s message exists to
    prevent.
    """
    root = os.path.join(tmpdir, "fwdghost")
    os.makedirs(root)
    write_tree(root, {"pkg/sub.mojo": "def keep() -> Int:\n  return 1\n",
                      "pkg/__init__.mojo": "from .sub import keep, Ghost\n",
                      "prog.mojo": "from pkg import keep\n\n"
                                   "def main():\n  return keep()\n"})
    fresh_cas()
    result, _out = build(root, "prog.aout", expect_ok=False)
    check(result.returncode != 0,
          "`Ghost` is declared nowhere and the package published it anyway; "
          "the missing-symbol check has been widened past its evidence")
    text = result.stderr or result.stdout
    check("Ghost" in text,
          f"the refusal does not name the gap: {text.strip()[-300:]}")



# ── the "exports nothing" family: 33 of the sweep's 578 files ────────────────
#
# These five pin the LIMIT, and each one is a pin in the anti-rot direction: it
# asserts that a refusal still fires, so if the limit is closed the test goes
# RED and has to be looked at. That is the same contract as an `expect=`
# marker in tools/suite.py, for the same reason — a limit nobody can detect
# the disappearance of is indistinguishable from a limit nobody re-checked.
#
# The family is documented, audited and costed in
# bugs/FORMAL_known_limits.md §1. Measured there: 33 files, EIGHT terminal
# modules, and all eight refusals TRUE. What is pinned here is therefore not a
# bug but a decision, plus three message-ACCURACY guards, because
# `no_public_api_reason` had no test at all before this wave and three of its
# six branches were saying something false about the file they were reported
# against (bugs/FORMAL_known_limits.md §1.3).

GENERIC_ONLY_MODULE = "def widen[T: Intable](v: T) -> T:\n  return v\n"
CONCRETE_MODULE = "def widen(v):\n  return v\n"


def test_a_module_nobody_binds_a_concrete_name_from_needs_no_library(
        tmpdir, _shared):
    """A module whose every imported name is a TEMPLATE is not built, and the
    program that imports it builds and runs.

    **THE PER-EDGE RULE, and the decision this row used to pin the other way.**
    A module dylib exists so that something on an import EDGE can bind a symbol
    in it, so an edge that binds no name the dependency could publish as one
    symbol needs no library — `formal/imports.py::library_free_edges` decides
    that per edge and `build_module_dylib` and `_resolve_imports` both act on
    it. `BinaryHeap` is the measured case (`std/collections/__init__.mojo`
    re-exports it and 162 of the 163 files the export gate blocked name nothing
    it declares), and `bugs/FORMAL_sweep_work_map_2026-10-03_b9.md` §4.1 is the
    measurement.

    What this pins is the half that could have gone wrong silently: the program
    RUNS and **no library for the module exists at all**, so the pass is not
    "an empty trie happened to link". A library with an empty export table would
    satisfy a build that never binds anything, and the assertion that would
    catch a regression to that is the absence of the file.

    It replaces `test_a_module_with_no_boundary_symbol_is_refused`, which
    asserted the opposite and existed to stop a template being published under
    its base name. That is still refused, and it is still pinned — by
    `test_a_generic_template_is_not_exported_under_its_base_name` below (the
    export set is empty) and by the next test (a bare call cannot bind). The
    difference the reversal makes is that the module is no longer refused for
    having no boundary symbol when NOTHING on the edge wants one.
    """
    root = os.path.join(tmpdir, "genericonly")
    os.makedirs(root)
    write_tree(root, {"mylib.mojo": GENERIC_ONLY_MODULE,
                      "prog.mojo": "from mylib import widen\n"
                                  "def main():\n  return 0\n"})
    fresh_cas()
    _result, out = build(root, "prog.aout")
    code, err = run(out)
    check(code == 0,
          f"a program that imports a template and calls nothing returned {code} "
          f"rather than 0: {err}")
    built = sorted(glob.glob(os.path.join(cas_imports("arm64"),
                                          "mylib.*.arm64.dylib")))
    check(not built,
          f"a library was built for a module this edge binds no concrete name "
          f"from, so the pass above is an empty trie that happened to link "
          f"rather than the edge needing nothing: {built}")


def test_a_bare_call_to_a_template_is_refused_by_the_export_rule(tmpdir, _shared):
    """The surviving half of the old limit: `widen(3)` names no instantiation,
    so it has no callee — and the refusal says so, by NAME.

    The counterpart to the test above, and the reason the per-edge rule is not a
    hole. The edge is exempt because every name it binds is a template, and the
    one thing that still cannot be done across it is CALL one without spelling
    the type argument: `widen(3)` is a BL against a symbol that does not exist
    under any spelling. So `formal/imports.py::check_library_free_calls` refuses
    it where the edge decision was made, and with
    `formal/model.py::imported_callee_refusal` — the same sentence every other
    unbindable imported callee gets.

    It used to be refused by the module's own export gate instead, one layer
    away, and the message the reader gets is the part worth pinning: it must
    NAME THE CALL and the rule that stops it, because the gate's sentence
    ("`widen` has no boundary symbol") is about the library and a reader who
    never knew a library was being built cannot use it. Three assertions, one
    per fact the sentence has to carry: the callee's name, the export rule, and
    the spelling that would work.
    """
    root = os.path.join(tmpdir, "genericonly_bare")
    os.makedirs(root)
    write_tree(root, {"mylib.mojo": GENERIC_ONLY_MODULE,
                      "prog.mojo": "from mylib import widen\n"
                                  "def main():\n  return widen(3)\n"})
    fresh_cas()
    result, _out = build(root, "prog.aout", expect_ok=False)
    text = result.stderr or result.stdout
    check(result.returncode != 0,
          "a bare call to an imported template built successfully; one trie "
          "entry cannot be two instantiations, so a call with different type "
          "arguments would silently bind the first one's body")
    check("widen" in text,
          f"the refusal does not name the call it is about: "
          f"{text.strip()[-300:]}")
    check("doc/ABI.md" in text,
          f"the refusal does not say which rule stops the call: "
          f"{text.strip()[-300:]}")
    check("widen[<a type>]" in text,
          f"the refusal does not give the spelling that would bind: "
          f"{text.strip()[-300:]}")


def test_a_generic_template_is_not_exported_under_its_base_name(tmpdir,
                                                                _shared):
    """The export set is empty for a generic-only module, and is the concrete
    name for the same module with one concrete function.

    The restrictive half, and the reason the family above is a limit rather
    than an oversight. Read straight out of `formal.build`, so it pins the
    DECISION and not the message: this is the predicate the refusal is built
    on, and a change that made it non-empty for a generic template would let
    33 files build and every one of them wrong.
    """
    sys.path.insert(0, HERE)
    from formal.build import _export_entries
    gen = os.path.join(tmpdir, "gen_only.mojo")
    with open(gen, "w") as f:
        f.write(GENERIC_ONLY_MODULE)
    check(_export_entries([gen]) == {},
          f"a generic template reached the export set: "
          f"{sorted(_export_entries([gen]))}")
    con = os.path.join(tmpdir, "concrete.mojo")
    with open(con, "w") as f:
        f.write(CONCRETE_MODULE)
    got = sorted(_export_entries([con]))
    check(got == ["widen"],
          f"the same module with one CONCRETE function exported {got}, not "
          f"['widen'] — so the difference between the two cases is genericity "
          f"and nothing else")


def test_a_constants_only_module_is_not_told_nothing_could_be_added(
        tmpdir, _shared):
    """A module of nothing but constants is not told "nothing this backend
    could add".

    The fourth message-accuracy guard on `no_public_api_reason`, and the one
    `bugs/FORMAL_std_os_io_round2_scope_is_one_refusal_shape.md` §6 item 2
    filed as a dead end: the branch's text ended "There is nothing an importer
    could bind, and nothing this backend could add." — and the second clause
    is **false**, which is why that document said of it "the sentence is a dead
    end for whoever reads the 6 files first".

    The constants are already inlined at their use sites by the
    module-constant substitution; what is absent is a RULE that a module with
    nothing to export needs no dylib at all, so an importer reading the
    constant directly needs no library. That is one feature, and
    `bugs/FORMAL_a_module_that_exports_nothing_cannot_be_a_dylib.md` is where
    it is written down — so the message now says which feature it is and where
    it lives, rather than telling a reader that nothing would help.

    **The assertion is on the false clause and on the owner being named**, and
    both directions matter: a message that merely stopped saying the false thing
    would leave the 6 files with no next step, which is the same dead end in a
    quieter form.
    """
    sys.path.insert(0, HERE)
    from formal.build import no_public_api_reason
    path = os.path.join(tmpdir, "constants_only.mojo")
    with open(path, "w") as f:
        f.write('comptime ALPHA: Int = 7\ncomptime BETA: String = "x"\n')
    reason = no_public_api_reason([path])
    check("declares no function and no type at all" in reason,
          f"the constants-only branch did not fire: {reason}")
    check("nothing this backend could add" not in reason,
          "the refusal still tells the reader that nothing could be added, "
          f"which is false — the constants are already inlined at their use "
          f"sites and the missing thing is a rule, not an implementation: "
          f"{reason}")
    check("FORMAL_a_module_that_exports_nothing_cannot_be_a_dylib" in reason,
          "the refusal does not name the feature that would remove it, so the "
          f"6 files behind this row still have no next step: {reason}")
    check("BACKEND" in reason,
          "the refusal does not say the missing thing is a backend RULE "
          f"rather than work on the module, which is the part a reader acts "
          f"on: {reason}")
    # …and the branch's own judgement is untouched: there really is nothing an
    # importer could bind, and the refusal is still correct.
    check("nothing an importer could bind" in reason,
          f"the refusal stopped saying why the refusal is correct: {reason}")
    # The private sibling is a DIFFERENT branch and must not have been edited.
    priv = os.path.join(tmpdir, "private_only.mojo")
    with open(priv, "w") as f:
        f.write("def _hidden() -> Int:\n  return 1\n")
    other = no_public_api_reason([priv])
    check("every declaration in it is private" in other
          and "BACKEND" not in other,
          f"the constants-only wording leaked into the private branch, whose "
          f"reason is a different fact: {other}")


def test_a_clib_named_definition_is_refused_not_blamed_on_privacy(tmpdir,
                                                                  _shared):
    """A module defining only `strlen` is refused, and NOT told it is private.

    A message-accuracy guard, and it guards a bug that is live on this tree.
    `no_public_api_reason` ends in an unconditional fall-through that reads
    "every declaration in it is private (a leading `_`)", and it is reached by
    every module with at least one CONCRETE public function that nevertheless
    exports nothing — because all four named branches are gated on `not
    concrete_funcs`. `std/memory/memory.mojo` gets it today, and it declares
    fifteen public functions and four private ones.

    The cause is `reflect._CLIB_SYMS`: `strlen` is a C library symbol, so the
    export rule drops it. The assertion is only that the message does not
    blame a privacy rule that was not applied, which is what a reader would
    otherwise act on.
    """
    sys.path.insert(0, HERE)
    from formal.build import no_public_api_reason
    path = os.path.join(tmpdir, "clib_named.mojo")
    with open(path, "w") as f:
        f.write("def strlen(s: String) -> Int:\n  return 1\n")
    reason = no_public_api_reason([path])
    check("is private" not in reason,
          f"a module with NO private declaration was told every declaration "
          f"in it is private: {reason}")
    check("strlen" in reason,
          f"the refusal does not name the symbol the export rule actually "
          f"excluded: {reason}")


def test_a_concrete_and_a_generic_of_one_name_are_told_apart(tmpdir, _shared):
    """`def f()` plus `def f[T](…)` is ONE concrete and ONE generic, not two
    generics.

    The second message-accuracy guard, on a bug that is live on this tree and
    that `std/sys/terminate.mojo` hits today. `_declared_api_shape` collects
    generics into a set of NAMES and then looks each parsed definition up in
    it, so a name that is concrete in one place and a template in another is
    counted as a template in both places — and the message then says "every
    public function in it is a GENERIC template" about a function that has no
    template parameters at all.
    """
    sys.path.insert(0, HERE)
    from formal.build import _declared_api_shape
    path = os.path.join(tmpdir, "one_name_two_defs.mojo")
    with open(path, "w") as f:
        f.write("def exit():\n  return 0\n\n"
                "def exit[intable: Intable](code: intable):\n  return 0\n")
    shape = _declared_api_shape(open(path).read())
    check(shape["funcs"] == ["exit"],
          f"the concrete `def exit()` was not counted as concrete: {shape}")
    check(shape["generic_funcs"] == ["exit"],
          f"the generic `def exit[intable]` was not counted as generic: "
          f"{shape}")


def test_a_public_generic_is_not_reported_as_private(tmpdir, _shared):
    """Two PUBLIC generics and one private helper is not "the only function
    it declares … which is both private and parametric".

    The third message-accuracy guard, same shape of mistake as the one above:
    the branch's condition tests whether the module has ANY private
    declaration, and its text then asserts something about the generics
    themselves. `std/memory/unsafe.mojo` hits it today — it declares two
    public generics (`bitcast`, `pack_bits`) and one private helper, and is
    told its only function is a template that is "both private and
    parametric". Neither half is true.
    """
    sys.path.insert(0, HERE)
    from formal.build import no_public_api_reason
    path = os.path.join(tmpdir, "public_generics.mojo")
    with open(path, "w") as f:
        f.write("def bitcast[T: Copyable](x: T) -> T:\n  return x\n\n"
                "def pack_bits[T: Copyable](x: T) -> T:\n  return x\n\n"
                "def _helper(x: Int) -> Int:\n  return x\n")
    reason = no_public_api_reason([path])
    check("both private and parametric" not in reason,
          f"two PUBLIC generic templates were reported as private: {reason}")
    check("only function it declares" not in reason,
          f"two public declarations were reported as one: {reason}")


# ── wave 5 (E1): the messages must name the rule, not guess at it ────────────
#
# The three guards above were written as `expect=` markers because the defects
# were live, and they started reporting "marked expect=… but it PASSES" the
# moment the messages were corrected. What is below is the OTHER direction: it
# pins the CONTENT of the corrected messages, because a `refuse:`-style
# assertion ("does not say X") is satisfied by any rewording at all, including a
# less informative one.


def test_a_clib_defined_name_is_reported_as_a_definition(tmpdir, _shared):
    """A module whose only name is a C library symbol says so, and says the
    hazard: the file DEFINES the name.

    The `_CLIB_SYMS` exclusion is right for a CALL — the symbol is already
    reachable with `dlsym` out of the system dylibs — and wrong for a
    DEFINITION, which is what `std/sys/terminate.mojo` does: it defines `exit`.
    If that module also exported one other symbol, an importer's `exit()` would
    bind libSystem's, silently, with no diagnostic. A message that only says
    "it is a C library symbol" leaves the reader with the benign half of the
    rule and none of the dangerous one, so both halves are asserted here."""
    sys.path.insert(0, HERE)
    from formal.build import no_public_api_reason
    path = os.path.join(tmpdir, "clib_defined.mojo")
    with open(path, "w") as f:
        f.write("def strlen(s: String) -> Int:\n  return 1\n")
    reason = no_public_api_reason([path])
    check("C library symbol" in reason,
          f"the refusal does not name the rule that excluded the only symbol: "
          f"{reason}")
    check("strlen" in reason,
          f"the refusal does not name the symbol: {reason}")
    check("DEFINES the name" in reason,
          f"the refusal does not say the module DEFINES the C library symbol it "
          f"is excluded for, which is the half of the rule that is wrong here "
          f"and the only half with a consequence: {reason}")


def test_the_fallthrough_names_a_rule_for_each_public_name(tmpdir, _shared):
    """A module with a concrete public function is told WHICH rule excluded each
    of its names, and the two rules are told apart.

    The old fall-through was unconditional and read "every declaration in it is
    private (a leading `_`)", so it fired on every module the four named
    branches did not cover and named a privacy rule that had never been
    applied. This reproducer has one public name the C-library rule excludes and
    one the template rule excludes, so a single-rule message cannot satisfy it
    — which is what makes it a test of the content rather than of the absence
    of the old sentence."""
    sys.path.insert(0, HERE)
    from formal.build import no_public_api_reason
    path = os.path.join(tmpdir, "two_rules.mojo")
    with open(path, "w") as f:
        f.write("def strlen(s: String) -> Int:\n  return 1\n\n"
                "def widen[T: Copyable](x: T) -> T:\n  return x\n")
    reason = no_public_api_reason([path])
    check("strlen" in reason and "C library symbol" in reason,
          f"the C-library rule is not named for the name it excludes: {reason}")
    check("widen" in reason and "GENERIC template" in reason,
          f"the template rule is not named for the name it excludes: {reason}")
    check("is private" not in reason,
          f"a module with a public declaration was told its declarations are "
          f"private: {reason}")


def test_a_clib_only_module_does_not_reach_the_per_name_fallthrough(
        tmpdir, _shared):
    """GUARD: a module whose every public name is a C library symbol takes the
    DEDICATED branch, not the generic per-name one.

    Before this change there was no such branch, so a `def strlen` module fell
    all the way through to the privacy sentence. The dedicated branch says
    something the per-name list cannot — that the module DEFINES the name — and
    this is what keeps it reachable now that the fall-through can enumerate
    C-library names too. Without it, the fifth branch could be deleted and
    every case above would still pass."""
    sys.path.insert(0, HERE)
    from formal.build import no_public_api_reason
    path = os.path.join(tmpdir, "clib_only.mojo")
    with open(path, "w") as f:
        f.write("def strlen(s: String) -> Int:\n  return 1\n")
    reason = no_public_api_reason([path])
    check(reason.startswith("formal dylib has no public functions: "
                            "clib_only.mojo exports nothing under doc/ABI.md's "
                            "rules: every name it declares"),
          f"a C-library-only module did not take the dedicated branch: {reason}")


def test_a_private_generic_module_is_told_it_is_private(tmpdir, _shared):
    """GUARD, and it is about a branch that was DELETED rather than re-gated.

    `no_public_api_reason` had a branch reading "the only function it declares
    is the generic template …, which is both private and parametric", gated on
    the module having ANY private declaration. The suggested repair was to gate
    it on `set(gen_funcs) & set(private)`, and that would have made it
    UNREACHABLE rather than correct: `gen_funcs` holds only non-underscore
    names and `private` only underscore ones, so the intersection is empty for
    every possible module. A branch that cannot be reached in a state where its
    claim is true is the same defect as one that can, so it is gone.

    This case pins both halves of that: the phrase is not producible for the
    module it was written for, and that module is still told the true reason.
    `std/utils/_select.mojo` is the module it was measured on — its only
    declaration is the private template `_select_register_value`."""
    sys.path.insert(0, HERE)
    from formal.build import no_public_api_reason
    path = os.path.join(tmpdir, "priv_generic.mojo")
    with open(path, "w") as f:
        f.write("def _select_register_value[T: Copyable](x: T) -> T:\n"
                "  return x\n")
    reason = no_public_api_reason([path])
    check("is both private and parametric" not in reason,
          f"a sentence about a branch that cannot be reached is still "
          f"reachable: {reason}")
    check("every declaration in it is private" in reason,
          f"a module whose only declaration is a private template was not told "
          f"so, which is the true and sufficient reason: {reason}")
    check("_select_register_value" in reason,
          f"the refusal does not name the declaration: {reason}")


def test_a_generic_struct_template_is_still_reported_as_one(tmpdir, _shared):
    """GUARD: the struct-template branch still fires, and still says "generic
    struct template".

    It is one of the four branches the new fall-through could have swallowed,
    and swallowing it would lose a distinction the reader needs: a parametric
    TYPE has no single boundary layout, which is a different fact from a
    parametric FUNCTION having no single symbol. `std/reflection/function.mojo`
    is the module it was measured on."""
    sys.path.insert(0, HERE)
    from formal.build import no_public_api_reason
    path = os.path.join(tmpdir, "generic_struct.mojo")
    with open(path, "w") as f:
        f.write("struct ReflectedFn[func_type, func]:\n"
                "  var x: Int\n")
    reason = no_public_api_reason([path])
    check("generic struct template" in reason,
          f"a module declaring only a generic struct template lost that "
          f"distinction: {reason}")
    check("ReflectedFn" in reason,
          f"the refusal does not name the template: {reason}")


# ── reflect.py: the export probe must not raise, and must not change ─────────


def test_a_dataclass_field_with_a_default_is_in_a_struct_layout(tmpdir, _shared):
    """`x: int = 0` in a struct body is a FIELD, and the layout descriptor says so.

    `fire_compiler.Parser` deliberately keeps an annotated assignment with a
    value as an `AssignStmt` CARRYING `type_ann` rather than a `VarDecl` (see
    the annotated-assignment branch in `parse_stmt` for the blast radius of
    changing that), so a reader that reaches for `.name` gets an
    `AttributeError` instead of a field. That is not a diagnostic: it is a
    traceback out of `collect_exports_src`, which is the export probe, so the
    whole module fails to build for a reason no message names — measured on
    `gimple_codegen.py` and `fire_compiler.py`, whose dataclass fields are
    exactly this shape.

    The importer parses these pairs back and keeps the ones that split into
    `ctype name`, so a field missing here is a field missing from the type the
    importer materializes."""
    sys.path.insert(0, HERE)
    import reflect
    path = os.path.join(tmpdir, "annotated_field.mojo")
    with open(path, "w") as f:
        f.write("struct Cfg:\n"
                "  var a: Int = 3\n"
                "  var b: Int\n"
                "  self.c: Int = 0\n"
                "  def get(self) -> Int:\n    return self.a\n")
    types = {e["name"]: e["signature"] for e in reflect.collect_exports_src(
        open(path).read(), "m")}
    check("Cfg" in types, f"the struct produced no TYPE entry: {sorted(types)}")
    sig = types["Cfg"]
    check("int64_t a;" in sig,
          f"the field declared `a: Int = 3` is not in the layout descriptor — "
          f"an annotated assignment is an AssignStmt, and its name is on "
          f"`.target`, not `.name`: {sig!r}")
    check("int64_t b;" in sig,
          f"the plain VarDecl field is missing too, so the reader is dropping "
          f"fields rather than misreading one: {sig!r}")
    check("c;" not in sig,
          f"a class-level `self.c: Int = 0` binds no declaration name and must "
          f"not be given one: {sig!r}")


def test_every_module_in_this_repository_survives_the_export_probe(tmpdir,
                                                                   _shared):
    """No source in this repository makes `collect_exports_src` raise.

    The `_struct_layout_sig` crash was found by sweeping the repository rather
    than by reading the code, and it is the kind of defect that hides: it fires
    on a SHAPE rather than a name, so it disables every module with a
    dataclass field with a default and no module without one, and the two
    `GimpleGen_gen_module` files it was found on could not be built at all.
    A per-file check is the only thing that finds the next one, and it is cheap
    because the probe is an AST pass with no codegen."""
    sys.path.insert(0, HERE)
    import reflect
    checked = failed = 0
    for name in sorted(os.listdir(HERE)):
        if not name.endswith((".py", ".mojo")) or name.startswith("test_"):
            continue
        path = os.path.join(HERE, name)
        if not os.path.isfile(path):
            continue
        checked += 1
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                reflect.collect_exports_src(f.read(), "m")
        except Exception as exc:                      # noqa: BLE001
            failed += 1
            check(False, f"the export probe raised on {name}: "
                         f"{type(exc).__name__}: {exc}")
    check(checked >= 50,
          f"only {checked} files were probed, so this case is not covering the "
          f"repository it claims to cover")


def test_the_exclusion_table_does_not_change_the_export_set(tmpdir, _shared):
    """`collect_exports_src` filters through `export_exclusions` and exports
    EXACTLY what it exported before.

    The refactor moved the private / C-library / overloaded / generic decisions
    out of `collect_exports_src` and into one table both it and
    `no_public_api_reason` read, so that a refusal cannot name a rule the export
    did not apply. A consolidation like that is only safe if the decision is
    UNCHANGED, and "the two implementations agree" is not a thing a reader can
    check by reading — so it is measured here, over every `.py` and `.mojo` in
    the repository plus the stdlib's `std/`, against the rule as it was written
    before the table existed (recomputed inline, from the same four inputs).

    This is the case that would catch a consolidation which quietly widens what
    a dylib exports, which is the one direction in which "one rule, two readers"
    is worse than two rules."""
    sys.path.insert(0, HERE)
    import re
    import reflect
    from fire_compiler import py_tokenize, Parser, FunctionDef
    from mojo.backend_gimple.emit_funcs import dup_def_signature_key

    stdlib = None
    try:
        from module_loader import STDLIB_PATH
        if STDLIB_PATH and os.path.isdir(STDLIB_PATH):
            stdlib = os.path.join(STDLIB_PATH, "std")
    except Exception:
        pass

    paths = []
    for name in sorted(os.listdir(HERE)):
        if name.endswith((".py", ".mojo")) and os.path.isfile(
                os.path.join(HERE, name)):
            paths.append(os.path.join(HERE, name))
    if stdlib:
        for root, _dirs, files in os.walk(stdlib):
            for name in sorted(files):
                if name.endswith(".mojo"):
                    paths.append(os.path.join(root, name))

    def old_exports(src, parsed):
        """`collect_exports_src` exactly as it was before the table existed."""
        generic = set(re.findall(r'\b(?:fn|def)\s+(\w+)\s*\[', src))
        generic |= set(re.findall(r'\bstruct\s+(\w+)\s*\[', src))
        dup: dict = {}
        for s in parsed:
            if isinstance(s, FunctionDef):
                dup.setdefault(s.name, []).append(s)
        overloaded = {n for n, ds in dup.items()
                      if len(ds) >= 2
                      and len({dup_def_signature_key(d) for d in ds}) != 1}
        skip = generic | overloaded
        return [e for e in reflect.collect_exports(parsed, "M")
                if e['name'].split('.', 1)[0] not in skip
                and e['name'].split('.', 1)[0] not in reflect._CLIB_SYMS]

    differing = probed = 0
    for path in paths:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                src = f.read()
            parsed = Parser(py_tokenize(src)).parse_module()
        except Exception:
            continue
        probed += 1
        want = sorted((e["name"], e["signature"], e["kind"])
                      for e in old_exports(src, parsed))
        got = sorted((e["name"], e["signature"], e["kind"])
                     for e in reflect.collect_exports_src(src, "M"))
        if want != got:
            differing += 1
            check(False, f"the export set for {path} changed: "
                         f"{set(want) ^ set(got)}")
    check(probed >= 300,
          f"only {probed} modules were compared, so this case is not covering "
          f"the corpus it claims to cover")


# ── the host-import wall's own instrument ─────────────────────────────────
#
# `tools/formal_host_import_wall.py` ranks what a file's import CLOSURE still
# names, which is the question a sweep's `not-answerable/host-import` class
# cannot answer: the class is one bucket over a queue of unrelated capabilities,
# and a module landing unmasks the row behind it. The doc that asked for the
# tool is `bugs/FORMAL_the_host_import_wall_is_at_its_honest_floor.md` §5, and
# these are its pins — the properties that make the ranking a MEASUREMENT rather
# than a second description to drift.
#
# Everything here is Lean-free and builds nothing: the instrument reads the
# backend's own readers, so a bug in it is a wrong TABLE, not a wrong image, and
# a test that had to compile a file to check it would be a test about the
# compiler.
#
# These pins were written against a second tool, `formal_host_import_walls.py`,
# which another branch built for the same doc at the same time. Two tools
# answering one question is a second thing to forget an arm of, so this file is
# the one that survived and the pins were moved onto it: `walls.py`'s `measure`
# returned `(reach, alone, files_of, (clean, errors))` where `rank` returns
# `{name: {"reach": [...], "alone": [...]}}` and `module_imports` answers None
# for a file the backend cannot read — which is where `clean` and `errors` come
# from here. Nothing was lost but `walls.py`'s `--scope`, which is now
# `formal_host_import_wall.py`'s.


def _wall_module():
    """The tool, imported as a module.

    Imported rather than run as a subprocess because the pins below are about
    the numbers it computes; a subprocess would only be able to read them off
    stdout, and the point of `reach`/`alone` being separate columns is that a
    reader has them separately.
    """
    sys.path.insert(0, os.path.join(HERE, "tools"))
    import formal_host_import_wall as W
    return W


def _measure(W, paths, unmodelled=frozenset()):
    """`walls.py`'s five-tuple, computed from `wall.py`'s two functions.

    Kept as a helper so the pins read the way they were written and the
    difference between the two tools is in ONE place: `rank` gives the two
    count columns and the file lists, and `module_imports` answers `None` for a
    file the backend cannot read, which is this tree's `errors`. The
    `clean`/`errors` split is therefore not a property of the tool but of this
    wrapper — which is the honest place for it, because `rank` does not
    promise it.
    """
    rows = W.rank(list(paths), unmodelled)
    reach = {n: len(v["reach"]) for n, v in rows.items()}
    alone = {n: len(v["alone"]) for n, v in rows.items()}
    files_of = {n: v["reach"] for n, v in rows.items()}
    errors = [p for p in paths if W.module_imports(p) is None]
    clean = sum(1 for p in paths if p not in errors and not W.walls_of(p, unmodelled))
    return reach, alone, files_of, (clean, errors)


def test_the_wall_instrument_uses_the_backends_own_readers(tmpdir, _shared):
    """A closure walk that reads the WRONG tree reports an empty wall.

    `imported_modules` takes `fire_compiler`'s nodes; handing it
    `ast.parse(...).body` returns nothing at all, so every row of such a table
    reads 0 and the table looks like a clean corpus. That is the failure this
    row exists to make impossible to reintroduce silently: it asserts the tool
    sees a host module through `formal.build.parse_module` and cannot see one
    through `ast`.
    """
    W = _wall_module()
    check(W.module_imports is not None, "the tool could not be imported")

    class _Fake:                                   # not a dataclass node
        __dataclass_fields__ = ()

    check(W.FB.parse_module("import os\n", "<t>") is not None,
          "parse_module returned nothing for a one-line import")
    got = W.I.imported_modules(W.FB.parse_module("import os\n", "<t>"))
    check("os" in got,
          f"the backend's reader did not see `import os` (got {got})")
    check(not I.imported_modules([_Fake()]),
          "a non-node yielded a name, so the reader is not the one under test")
    # And the two readers disagree, which is the whole reason the tool is not
    # written against `ast`: `imported_modules` filters the front-end-provided
    # names, an `ast` walk does not.
    check("dataclasses" in I.FRONTEND_PROVIDED_MODULES,
          "the front-end-provided list changed, so this row's contrast is gone")
    got = W.I.imported_modules(
        W.FB.parse_module("import dataclasses\n", "<t>"))
    check("dataclasses" not in got,
          "a front-end-provided module is being counted as a wall")


def _a_real_wall_name(W):
    """A host module this tree does NOT resolve, chosen from the tier tables.

    Picked at run time rather than written down, because a written-down name goes
    stale the day a wave models it and the case then fails for the best possible
    reason — which is the one kind of failure that trains a reader to ignore a
    red suite. The tables are the same ones the tool ranks with, so this is the
    same question the ranking asks, asked once here.
    """
    for name in sorted(I.HOST_MODULES):
        if name in sys.stdlib_module_names \
                and I.host_module_tier(name) != "not-a-module" \
                and I.resolve_module_path(name) is None:
            return name
    return None


def test_the_wall_instrument_separates_reach_from_alone(tmpdir, _shared):
    """`reach` and `alone` are different questions and the tool answers both.

    `reach` is how many files name the module at all; `alone` is how many for
    which it is the ONLY name, i.e. the files "writing this module makes this
    file build" is a true statement about. A ranking built on `reach` alone
    picks the module with the widest closure — `importlib`, which most of this
    repository reaches and for which "write importlib" is true of none of them —
    so the column a worker plans against has to be the second one, and the
    instrument has to print both.

    Three files over two walls: one naming both, one naming one, one naming
    neither. The third is what makes `clean` a measurement rather than a
    constant, and the second is what makes `alone` a different number from
    `reach`.
    """
    W = _wall_module()
    wall_a = _a_real_wall_name(W)
    wall_b = None
    for name in sorted(I.HOST_MODULES):
        # …and a `HOST_NOT_A_MODULE` member is skipped for the same reason
        # `_a_real_wall_name` skips it: the instrument's `alone` column asks
        # "is this the only WALL on this file", and `antigravity` is not one —
        # it is a name the table says has no content to compile. Counting it
        # made `alone` wrong by one on the file that names both, which is the
        # number the row exists to read.
        if name != wall_a and name in sys.stdlib_module_names \
                and I.host_module_tier(name) != "not-a-module" \
                and I.resolve_module_path(name) is None:
            wall_b = name
            break
    check(wall_a is not None and wall_b is not None,
          "no two host modules are walls in this tree, so the columns cannot "
          "be told apart here")
    d = str(tmpdir)
    a = os.path.join(d, "a.mojo")                    # both walls
    b = os.path.join(d, "b.mojo")                    # one wall
    c = os.path.join(d, "c.mojo")                    # none
    open(a, "w").write(f"import {wall_a}\nimport {wall_b}\n")
    open(b, "w").write(f"import {wall_a}\n")
    open(c, "w").write("x = 1\n")
    reach, alone, files_of, (clean, errors) = _measure(W, [a, b, c])
    check(not errors, f"unexpected parse errors: {errors}")
    check(reach.get(wall_a) == 2,
          f"reach for `{wall_a}` was {reach.get(wall_a)}, not 2")
    check(alone.get(wall_a) == 1,
          f"alone for `{wall_a}` was {alone.get(wall_a)}: it is the only wall "
          f"on one of the two files that name it")
    check(reach.get(wall_b) == 1 and alone.get(wall_b, 0) == 0,
          f"`{wall_b}` is not the only wall on its file, so `alone` must not "
          f"count it (reach {reach.get(wall_b)}, alone {alone.get(wall_b)})")
    check(clean == 1,
          f"exactly one of the three files names no wall, so clean was {clean}")
    check(sorted(files_of.get(wall_a, [])) == sorted([a, b]),
          "the file list does not name the files the reach count came from")


def test_the_wall_instrument_measures_a_delta_on_one_tree(tmpdir, _shared):
    """`--pretend-unmodelled` is what makes "writing this module moves N files"
    a measurement, and it has to move the numbers.

    A before/after across two checkouts measures the merge, not the change, which
    is why this flag exists. The fixture imports `os`, which this tree DOES
    resolve (`formal/hostmods/os.mojo`) — so the file starts with no wall at all
    and pretending `os` absent is exactly "that module is not in this tree",
    which is the state a wave measures before it writes one. Both the `reach`
    row and the `clean` count have to move, and in one direction only: a delta
    that went the other way is a bug in the instrument whatever the number is.
    """
    W = _wall_module()
    check(W.I.resolve_module_path("os") is not None,
          "`os` is not a wall on this tree any more, so pretending it absent "
          "measures nothing; pick a module that resolves and is absent")
    p = os.path.join(str(tmpdir), "p.mojo")
    open(p, "w").write("import os\nimport signal\n")
    reach_b, _alone_b, _files_b, (clean_b, _) = _measure(W, [p])
    reach_a, alone_a, _files_a, (clean_a, _) = _measure(W, [p], frozenset(("os",)))
    check("os" not in reach_b,
          "`os` is already a wall on this tree, so the delta measures nothing")
    check(clean_b == 1 and clean_a == 0,
          f"pretending `os` absent must move clean from 1 to 0, and it went "
          f"{clean_b} to {clean_a}")
    check(reach_a.get("os") == 1 and alone_a.get("os") == 1,
          f"pretending `os` absent did not make it a wall that is ALSO alone "
          f"(reach {reach_a.get('os')}, alone {alone_a.get('os')})")
    # One module's absence adds exactly that module's row and disturbs nothing
    # else — the property that makes the flag usable as a DELTA rather than as a
    # second scope.
    expected = dict(reach_b)
    expected["os"] = 1
    check(reach_a == expected,
          f"pretending one module absent changed other rows too: "
          f"{ {k: v for k, v in reach_a.items() if expected.get(k) != v} }")


def test_the_wall_instrument_reads_the_sweep_column_with_its_own_peel(tmpdir, _shared):
    """The `sweep` column is the LAST host module named, not the first.

    A refusal chains (`a imports b, which imports c, which is a host module`),
    and which module the row is really about is the one at the END of the chain:
    the first is what the file asked for, the last is what stopped it. Reading
    the first attributes the row to a module that is merely the file's first
    dependency, which is how a ranking ends up pointing at `collections` for
    everything.
    """
    W = _wall_module()
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        log = os.path.join(d, "sweep.txt")
        open(log, "w").write(
            "NOT-ANSWERABLE/HOST-IMPORT: x.mojo  (build: x.mojo imports "
            "'copy', which cannot be built either: y.mojo imports "
            "'importlib', which is a host module)\n"
            "PASS other.mojo\n")
        rows = W.sweep_rows(log)
    counts = {}
    for _p, _name in rows.items():
        counts[_name] = counts.get(_name, 0) + 1
    check(counts.get("importlib") == 1,
          f"the chain's terminal module was not the one counted: {counts}")
    check("copy" not in counts,
          "the chain's FIRST host module was counted, which is the wrong end")
    check(W.sweep_rows("") == {} and W.sweep_rows("/nope") == {},
          "a missing sweep log must be an empty column, not an error")


def test_a_dead_import_is_not_a_wall_this_tree_has_to_climb(tmpdir, _shared):
    """A module in the file's closure that the file never READS is not a wall.

    `tools/apply_extraction.py` imported `copy` and used it zero times, so it was
    the `alone` row of `tools/formal_host_import_wall.py`'s ranking — the file's
    ONLY unresolved name, and therefore the whole of what stood between it and a
    build. `bugs/FORMAL_eleven_of_thirteen_host_import_rows_are_closure.md`
    recorded that row as "`copy`'s is `deepcopy` over objects this path has no
    heap for", which is false of this file: there is no `deepcopy` in it, and no
    reference to the module at all. The honest reading is that the import is
    DEAD, and a dead import is removed rather than modelled — which is the same
    answer `itertools` got for `test_formal_run.py` in that document's own §4.

    The claim asked here is the one a reader can act on: for a handful of files
    in this repository, every module in the import closure is either resolvable
    or genuinely read. `copy` is named explicitly because it is the row that was
    measured, and because a future re-addition of the import would put the file
    straight back on the wall with nothing failing here.
    """
    root = HERE
    stdlib = os.environ.get("MOJO_STDLIB") or os.path.join(
        os.path.dirname(HERE), "new-modular", "Mojo", "stdlib", "std")

    def closure_unresolved(path):
        seen, stack, out = set(), [path], set()
        while stack:
            p = stack.pop()
            rp = os.path.realpath(p)
            if rp in seen or not p or not os.path.exists(p):
                continue
            seen.add(rp)
            for m in I.imported_modules(I.module_statements(p)):
                d = I.resolve_module_path(m, relative_to=p,
                                          project_root=root)
                if d is None and os.path.isdir(stdlib):
                    d = I.resolve_module_path(m, relative_to=p,
                                              project_root=stdlib)
                out.add(m) if d is None else stack.append(d)
        return out

    # THE ROW, and the fact that makes it a dead import rather than a use: the
    # module is in the file's statements and in NO expression. A file that
    # really used it would fail this, which is the point — the check is not
    # "the import is gone" but "nothing reads what it imports".
    target = os.path.join(root, "tools", "apply_extraction.py")
    check(os.path.exists(target), f"{target} is gone, so this row is stale")
    with open(target) as fh:
        stmts = I.module_statements(target)
    names = I.imported_modules(stmts)
    check("copy" not in names,
          f"`tools/apply_extraction.py` imports `copy` again, which puts it "
          f"back on the host-import wall as the file's ONLY unresolved name; "
          f"its modules are {sorted(names)}")
    import ast as _ast
    with open(target) as fh:
        tree = _ast.parse(fh.read())
    reads = [n for n in _ast.walk(tree)
             if isinstance(n, _ast.Name) and n.id == "copy"]
    check(not reads,
          f"`copy` is imported and read {len(reads)} time(s) — then this is a "
          f"use, not a dead import, and the wall is a real one")
    un = closure_unresolved(target)
    check("copy" not in un,
          f"`tools/apply_extraction.py` still has `copy` in its unresolved "
          f"closure: {sorted(un)}")

    # The general shape, over the files the ranking measured as being one stdlib
    # call from a sweep. **`fractions` is excluded and named**, because it is a
    # REAL wall rather than a dead import: `test_formal_time.py` imports
    # `fractions.Fraction` and uses it as the oracle. The distinction the row
    # turns on is not "is the module in the closure" but "does anything READ
    # it" — the check above asks the second question of `copy` for exactly this
    # reason, and a file that genuinely reads its wall is supposed to be red.
    for rel in ("tools/apply_extraction.py",):
        p = os.path.join(root, rel)
        if not os.path.exists(p):
            continue
        un = closure_unresolved(p)
        check(not un,
              f"{rel} has an unresolved import the formal sweep files as "
              f"not-answerable/host-import: {sorted(un)}")

    # And the half that is a real wall STAYS one: `fractions` is read, so this
    # is the case that keeps the row above honest — a check that only ever saw
    # dead imports would pass with the whole ranking still red.
    tf = os.path.join(root, "test_formal_time.py")
    if os.path.exists(tf):
        check("fractions" in closure_unresolved(tf),
              "test_formal_time.py no longer has `fractions` in its unresolved "
              "closure — either the import went away (then this row is stale) "
              "or it resolves (then the tool's `alone` column is stale)")

def test_a_memo_replaces_the_decorator_the_corpus_cannot_climb(tmpdir, _shared):
    """`version.py`'s `functools.lru_cache` was a row, and the row closed.

    `bugs/FORMAL_eleven_of_thirteen_host_import_rows_are_closure.md` recorded
    `functools` as the last honest row on the host-import wall — "`functools`
    for `version.py`, one file ... which is a capability question and not a
    missing file" — and the document's OWN two closures say what the answer is
    when a row is a CORPUS spelling rather than a module: `itertools` left
    `test_formal_run.py` (a double index loop over pairs the generator already
    knows the length of) and `copy` left `tools/apply_extraction.py` (a dead
    import). Here `lru_cache` decorated a ZERO-ARGUMENT function, so the whole
    of what it did was "compute once", and that is two module globals.

    So this asks the three questions the row turns on, and none of them is
    "is the string `functools` still in the file":

      1. **the closure is empty** — every module `version.py` reaches resolves,
         walked with `formal/imports.py`'s own resolver, the one the build uses.
         That is `alone 0`, and it is the claim the ranking's `alone` column is
         for. Re-adding the import puts `functools` straight back on the wall.
      2. **the memo is a MEMO** — computed once, and the same object after.
         This is the half a dead-import test does not have: deleting an import
         that nothing reads cannot get this wrong, but a hand-rolled cache that
         recomputes per call is not the `lru_cache(maxsize=1)` it replaced, and
         the cost would be two `git` subprocesses per caller. `version()` is on
         the path of `fire.py`, `cas.py` and `jit/arm64.py`.
      3. **the ANSWER is unchanged** — the value still comes from the same
         resolution order, measured against a local `functools.lru_cache` built
         from the pre-change body. A cache that returns the right string for the
         wrong reason (a primed `'unknown'`, say) passes 1 and 2 and is still a
         regression in every caller.
    """
    root = HERE
    stdlib = os.environ.get("MOJO_STDLIB") or os.path.join(
        os.path.dirname(HERE), "new-modular", "Mojo", "stdlib", "std")

    def closure_unresolved(path):
        seen, stack, out = set(), [path], set()
        while stack:
            p = stack.pop()
            rp = os.path.realpath(p)
            if rp in seen or not p or not os.path.exists(p):
                continue
            seen.add(rp)
            for m in I.imported_modules(I.module_statements(p)):
                d = I.resolve_module_path(m, relative_to=p,
                                          project_root=root)
                if d is None and os.path.isdir(stdlib):
                    d = I.resolve_module_path(m, relative_to=p,
                                              project_root=stdlib)
                out.add(m) if d is None else stack.append(d)
        return out

    target = os.path.join(root, "version.py")
    check(os.path.exists(target), f"{target} is gone, so this row is stale")

    # (1) The closure. `functools` named because it is the row that was
    # measured, and because its return is the failure that matters.
    un = closure_unresolved(target)
    check("functools" not in un,
          f"`version.py` imports `functools` again, which puts it back on the "
          f"host-import wall as the file's ONLY unresolved name")
    check(not un,
          f"`version.py` has an unresolved import the formal sweep files as "
          f"not-answerable/host-import: {sorted(un)}")

    # (2) and (3) need the module, imported under a name of our own so the
    # repository's own `version` — which three modules import — is not disturbed
    # for the rest of this process.
    import importlib.util as _ilu
    spec = _ilu.spec_from_file_location("_version_under_test", target)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    first = mod.version()
    check(first == mod.version(),
          f"`version()` returned {first!r} then {mod.version()!r} — the memo "
          f"is not a memo, and every caller pays the two `git` subprocesses")

    # **The memo is READ, not just written** — and this is the check the string
    # comparison above cannot make, which is why it is here and not implied by
    # it. A `version()` that recomputed every call and stored the result would
    # answer the same string every time, so `first == mod.version()` holds and
    # `_VERSION_CACHE == first` holds, and the substitution is broken in the way
    # that costs the most: two `git` subprocesses per caller, on the path of
    # `fire.py`, `cas.py` and `jit/arm64.py`. What distinguishes them is that a
    # memo is AUTHORITATIVE, so poisoning it with a string no amount of
    # recomputing could produce must come straight back out. This is measured,
    # not assumed: with the early return deleted the rest of this test passes.
    saved_cache = mod._VERSION_CACHE
    try:
        mod._VERSION_CACHE = "poisoned-sentinel"
        poisoned = mod.version()
        check(poisoned == "poisoned-sentinel",
              f"with `_VERSION_CACHE = 'poisoned-sentinel'` `version()` "
              f"answered {poisoned!r}: the memo is WRITTEN but never READ, so "
              f"every call recomputes -- the same answer, and the cost of "
              f"`lru_cache(maxsize=1)` paid back")
    finally:
        mod._VERSION_CACHE = saved_cache
    check(mod._VERSION_CACHE == first,
          f"`version()` set no memo (`_VERSION_CACHE` is "
          f"{mod._VERSION_CACHE!r} after answering {first!r})")

    # (3) The same answer as the decorator it replaced, from the same order:
    # RELEASE, then the git short SHA with `-dirty`, then `'unknown'`. Built
    # here rather than imported so the two are compared on THIS tree.
    import functools as _ft
    import subprocess as _sp
    here = os.path.dirname(os.path.abspath(target))

    def _reference():
        def _git(*a):
            return _sp.run(['git', '-C', here, *a], capture_output=True,
                           text=True, timeout=RUN_TIMEOUT_S)
        if mod.RELEASE:
            return mod.RELEASE
        try:
            r = _git('rev-parse', '--short', 'HEAD')
            if r.returncode == 0 and r.stdout.strip():
                v = r.stdout.strip()
                if _git('diff', '--quiet', 'HEAD').returncode != 0:
                    v += '-dirty'
                return v
        except Exception:
            pass
        return 'unknown'

    # Wrapped the way the file wrapped it, so the reference is a real
    # `lru_cache(maxsize=1)` and not a hand-rolled stand-in beside it.
    cached = _ft.lru_cache(maxsize=1)(_reference)
    check(first == cached(),
          f"`version()` answers {first!r} where the `lru_cache` it replaced "
          f"answers {cached()!r} — the memo changed the value, not only the "
          f"cost of computing it")

    # And `RELEASE`, which is the branch nothing else here reaches: a constant
    # overrides the git SHA, so it is the one input that does not depend on the
    # tree being a git checkout at all.
    saved_release, saved_cache = mod.RELEASE, mod._VERSION_CACHE
    try:
        mod.RELEASE, mod._VERSION_CACHE = "9.9-test", None
        check(mod.version() == "9.9-test",
              f"with RELEASE='9.9-test' `version()` answered "
              f"{mod.version()!r} — the override branch is dead or shadowed")
        check(mod.version() is mod.version(),
              "the RELEASE answer is not memoised either")
    finally:
        mod.RELEASE, mod._VERSION_CACHE = saved_release, saved_cache


TESTS = [
    ("a memo replaces the decorator the corpus cannot climb",
     test_a_memo_replaces_the_decorator_the_corpus_cannot_climb),
    ("an import links the module and the program runs",
     test_import_links_and_runs),
    ("a module-qualified call `mod.fn()` links and runs",
     test_module_qualified_call_runs),
    ("a module name READ as a value is still refused",
     test_a_module_name_read_as_a_value_is_still_refused),
    ("a package submodule's qualified call links and runs",
     test_package_submodule_call_runs),
    ("a name a package submodule does not export is refused",
     test_package_submodule_unexported_name_is_refused),
    ("the imported module is compiled in full", test_module_compiled_in_full),
    ("a package is identified by its module name",
     test_package_identity_is_module_name),
    ("a cross-module call uses the dependency's export",
     test_cross_module_call_is_qualified),
    ("dependencies are linked before dependents",
     test_dependencies_linked_first),
    ("a mutual import terminates and works", test_import_cycle_terminates),
    ("an unresolvable import is a clean error",
     test_unresolvable_import_is_a_clean_error),
    ("every unresolvable import is named, whatever the order",
     test_several_unresolvable_imports_are_all_named),
    ("a program with no imports builds no dylib",
     test_no_import_needs_no_dylib),
    ("a module dylib is published only signed",
     test_a_module_dylib_is_published_only_signed),
    ("a struct method is callable across modules",
     test_struct_method_across_modules),
    ("a library may construct its own struct",
     test_a_library_may_construct_its_own_struct),
    ("an imported generic is refused as an export gap",
     test_an_imported_generic_is_refused_as_an_export_gap),
    ("a bare call to an exported name still binds",
     test_a_bare_call_to_an_exported_name_still_binds),
    ("a one-word struct's field IS its value",
     test_one_word_struct_field_is_the_value),
    ("a struct too wide for one word is refused with the switch off",
     test_wide_struct_is_refused_with_the_switch_off),
    ("a two-field struct builds and runs by reference",
     test_wide_struct_runs_by_reference),
    ("a __future__ import is inert, not a dependency",
     test_future_import_is_inert),
    ("a guarded import is inert too", test_guarded_imports_stay_inert),
    ("a function-local import is a dependency",
     test_a_function_local_import_is_a_dependency),
    ("widening the imported list widens nothing else",
     test_widening_the_imported_list_widens_nothing_else),
    ("a repository sibling resolves", test_repository_sibling_resolves),
    ("a package-relative dotted import resolves",
     test_package_relative_dotted_import_resolves),
    ("the spelling outranks a nearer root's leaf",
     test_the_spelling_outranks_a_nearer_roots_leaf),
    ("a dotted stdlib import resolves to the module it names",
     test_a_dotted_stdlib_import_resolves_to_the_module_it_names),
    ("a module's identity is its package chain, not its reach order",
     test_own_module_identity_is_the_package_chain),
    ("a relative import at the root builds one library and runs",
     test_a_relative_import_at_the_root_builds_one_library),
    ("a host module is refused despite a same-named sibling",
     test_host_module_still_refused_despite_same_named_sibling),
    ("a standard-library module in no tier is not reported as a typo",
     test_a_stdlib_module_in_no_tier_is_not_reported_as_a_typo),
    ("no standard-library module is left in neither tier",
     test_no_standard_library_module_is_left_in_neither_tier),
    ("a name with nothing to implement gets its own tier",
     test_a_name_with_nothing_to_implement_gets_its_own_tier),
    ("a host-module refusal says what this target offers instead",
     test_a_host_module_refusal_says_what_this_target_offers),
    ("an unclassified CPython stdlib name is not called a typo",
     test_an_unclassified_stdlib_name_is_not_called_a_typo),
    ("no unclassified stdlib name is imported by anything",
     test_no_unclassified_stdlib_name_is_imported_by_anything),
    ("a package that only re-exports builds and runs",
     test_package_reexport_builds_and_runs),
    ("a package dylib exports nothing and says namespace",
     test_namespace_library_exports_nothing),
    ("a docstring-only package builds and runs",
     test_a_docstring_only_package_is_a_namespace_library),
    ("a docstring-only package dylib is empty and says namespace",
     test_a_docstring_only_package_dylib_is_empty_and_says_namespace),
    ("a name the empty package does not declare is still refused",
     test_a_name_the_empty_package_does_not_declare_is_still_refused),
    ("a package that declares something is still refused",
     test_a_package_that_declares_something_is_still_refused),
    ("a re-export nothing provides is refused by name",
     test_reexport_of_an_unexported_name_is_refused),
    ("an ALIASED re-export binds under both spellings",
     test_aliased_reexport_binds_under_both_spellings),
    ("an aliased re-export runs on both architectures",
     test_aliased_reexport_runs_on_both_architectures),
    ("a private name aliased public stays unpublished",
     test_a_private_name_aliased_public_stays_unpublished),
    ("a relative import keeps private declarations out of the trie",
     test_a_relative_import_keeps_private_declarations_out_of_the_trie),
    ("a name the module defines wins over its own import",
     test_a_name_the_module_defines_wins_over_its_own_import),
    ("a module dylib matches the program's arch, both arches",
     test_module_dylib_matches_the_programs_arch),
    ("both architectures' libraries coexist",
     test_both_arch_libraries_coexist),
    ("a library is published atomically, never half-written",
     test_the_library_is_published_atomically),
    ("the library path names the compiler as well as the source",
     test_the_library_path_names_the_compiler_too),
    ("a re-exported type reaches the importer",
     test_reexported_type_reaches_the_importer),
    ("a forwarded name is filed by what defines it",
     test_declared_kinds_files_a_forwarded_name_by_its_definition),
    ("a forwarded type is not demanded as a symbol, both arches",
     test_a_forwarded_type_is_not_demanded_as_a_symbol),
    ("a forwarded name nothing defines is still refused",
     test_a_forwarded_name_nothing_defines_is_still_refused),
    ("a local Mojo module beats the host-module list",
     test_mojo_source_beats_host_module),
    ("a host-module refusal carries its measured next step",
     test_a_host_module_refusal_carries_its_measured_next_step),
    ("every host-module advice entry is honest",
     test_host_module_advice_is_honest),
    ("a module nobody binds a concrete name from needs no library",
     test_a_module_nobody_binds_a_concrete_name_from_needs_no_library),
    ("a bare call to a template is refused by the export rule",
     test_a_bare_call_to_a_template_is_refused_by_the_export_rule),
    ("a generic template is not exported under its base name",
     test_a_generic_template_is_not_exported_under_its_base_name),
    ("a constants-only module is not told nothing could be added",
     test_a_constants_only_module_is_not_told_nothing_could_be_added),
    ("a C-library-named definition is not blamed on privacy",
     test_a_clib_named_definition_is_refused_not_blamed_on_privacy),
    ("a concrete and a generic of one name are told apart",
     test_a_concrete_and_a_generic_of_one_name_are_told_apart),
    ("a public generic is not reported as private",
     test_a_public_generic_is_not_reported_as_private),
    ("a C-library-named definition is reported as a definition",
     test_a_clib_defined_name_is_reported_as_a_definition),
    ("the fall-through names a rule for each public name",
     test_the_fallthrough_names_a_rule_for_each_public_name),
    ("a C-library-only module takes the dedicated branch",
     test_a_clib_only_module_does_not_reach_the_per_name_fallthrough),
    ("a private generic module is told it is private",
     test_a_private_generic_module_is_told_it_is_private),
    ("a generic struct template is still reported as one",
     test_a_generic_struct_template_is_still_reported_as_one),
    ("a dataclass field with a default is in a struct layout",
     test_a_dataclass_field_with_a_default_is_in_a_struct_layout),
    ("every module here survives the export probe",
     test_every_module_in_this_repository_survives_the_export_probe),
    ("the exclusion table does not change the export set",
     test_the_exclusion_table_does_not_change_the_export_set),
    ("the largest swept file is classified in a bounded time",
     test_a_swept_stdlib_file_is_classified_in_a_bounded_time),
    ("every name has one named verdict, and no answer is an absence",
     test_every_name_has_one_named_verdict_and_no_answer_is_an_absence),
    ("the host-import wall's instrument reads the backend's own tree",
     test_the_wall_instrument_uses_the_backends_own_readers),
    ("the wall instrument separates reach from alone",
     test_the_wall_instrument_separates_reach_from_alone),
    ("a dead import is not a wall this tree has to climb",
     test_a_dead_import_is_not_a_wall_this_tree_has_to_climb),
    ("the wall instrument measures a delta on one tree",
     test_the_wall_instrument_measures_a_delta_on_one_tree),
    ("the wall instrument reads the sweep column with its own peel",
     test_the_wall_instrument_reads_the_sweep_column_with_its_own_peel),
]


# ── known failures, recorded rather than hidden ──────────────────────────────
#
# The same contract as `test_formal.py`'s EXPECTED_FAILURES and as an
# `expect='<why>'` marker in tools/suite.py: a test listed here that PASSES is
# reported as a FAILURE, because a marker nobody revisits is a bug quietly
# reintroduced. So these are pins in both directions — they cannot rot green,
# and they cannot rot red.
#
# EMPTY, and that is the point. It held three message-ACCURACY guards for
# `no_public_api_reason`, each with the stdlib module it had been measured on
# (bugs/FORMAL_known_limits.md §1.3), and all three started reporting
# "marked expect=… but it PASSES" the moment the messages were corrected — which
# is the mechanism working, not a failure to suppress. The guards are still in
# `TESTS` above and are now ordinary passing tests; what was removed is the
# MARKER, and with it the claim that the defects are live.
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
    with tempfile.TemporaryDirectory() as tmpdir:
        for name, fn in TESTS:
            expect = EXPECTED_FAILURES.get(name)
            if expect is not None and name not in [n for n, _f in TESTS]:
                print(f"  STALE  {name}\n        marked expected-fail but is "
                      f"not in TESTS — drop the marker")
                failed += 1
                continue
            try:
                fn(tmpdir, None)
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
                print(f"  FAIL  {name}\n        marked expect=… but it PASSES "
                      f"— drop the marker:\n        {expect}")
                continue
            passed += 1
            print(f"  PASS  {name}")

    stale = sorted(set(EXPECTED_FAILURES) - {n for n, _f in TESTS})
    for name in stale:
        print(f"  STALE  {name}\n        marked expect=… but is not in TESTS "
              f"— drop the marker")
        failed += 1

    print(f"\nformal imports: PASS={passed} EXPECTED={expected} "
          f"SKIP={skipped} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        _drop_cas_home()
