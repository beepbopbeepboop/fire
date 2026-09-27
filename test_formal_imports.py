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
     answer with nothing to grep for.
 10. a module that genuinely has no boundary symbol is REFUSED, and the
     refusal says which of the ways it has none. 33 of the 578 swept files
     are this one refusal; the decision and its cost are in
     bugs/FORMAL_known_limits.md §1, and the five tests at the end of this
     file pin both the decision and the accuracy of the message, because a
     message that is false about the file sends the reader after a construct
     that is not there.

Invoked directly:
    python3 test_formal_imports.py [-v]
"""
import argparse
import json
import os
import platform
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# The independent Mach-O reader and the CLI driver live in the dylib suite;
# imported rather than copied so a fix to the reader cannot leave a second,
# quietly different one behind.
from test_formal_dylib import (TestFailure, check, parse_macho, read_uleb,
                               run_fire)

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


def _drop_cas_home():
    shutil.rmtree(_CAS_HOME, ignore_errors=True)


def cas_imports(arch="arm64"):
    return os.path.join(CAS_IMPORTS_ROOT, arch)


def module_dylib(prefix, arch="arm64"):
    """The built library for `prefix`, found by prefix rather than by name.

    A module library's file name is `<prefix>.<source-digest>.<arch>.dylib`:
    the digest is there so two builds of the same module name cannot overwrite
    each other, and the arch is there so the two architectures cannot either.
    So the name is only stable up to the digest, and every test that wants a
    library has to look it up. Globbing on `<prefix>.*.<arch>.dylib` still
    pins the convention that matters — the arch really is in the name, and it
    really is the last field — while tolerating the digest between.
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
    r = subprocess.run([out], capture_output=True, text=True, timeout=120)
    return r.returncode, (r.stderr or r.stdout)


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


def test_no_import_needs_no_dylib(tmpdir, _shared):
    """The common case must stay exactly as cheap as it was."""
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
    all NESTED inside an `if`/`try` and `imported_modules` reads only the
    module's top level. That is load-bearing rather than incidental — a
    resolver that descended into a body would make every one of these a hard
    dependency — so it is pinned here, both at the collector and end to end."""
    from formal.imports import imported_modules
    src = ("from __future__ import annotations\n"
           "import os\n"
           "if False:\n  import nonexistent_guard_false\n"
           "if sys.version_info >= (3, 99):\n"
           "  import nonexistent_guard_version\n"
           "try:\n  import nonexistent_guard_try\n"
           "except ImportError:\n  nonexistent_guard_try = None\n")
    import fire_compiler as F
    stmts = F.Parser(F.py_tokenize(src)).with_filename("g.py").parse_module()
    got = imported_modules(stmts)
    check(got == ["os"],
          f"imported_modules returned {got}; a guarded import is inert, and "
          f"so is the __future__ directive — only `os` is a dependency")
    root = os.path.join(tmpdir, "guarded")
    os.makedirs(root)
    write_tree(root, {"prog.mojo":
                      "if False:\n  import nonexistent_guard_false\n"
                      "def main():\n  return 13\n"})
    fresh_cas()
    _result, out = build(root, "prog.aout")
    code, err = run(out)
    check(code == 13, f"returned {code}, expected 13; stderr: {err}")


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
    r = subprocess.run([out], capture_output=True, text=True, timeout=60)
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
    run = subprocess.run([out], capture_output=True, text=True, timeout=60)
    check(run.returncode == 6,
          f"exit status {run.returncode}, expected 6 (the value the method "
          f"wrote through the receiver)")


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


def test_a_module_with_no_boundary_symbol_is_refused(tmpdir, _shared):
    """A module whose only public function is a GENERIC template is refused.

    The limit, pinned. doc/ABI.md §Generics is explicit that a generic is not
    a single boundary symbol — each INSTANTIATION is, keyed in the CAS by its
    type arguments — and that monomorphization is Stage 5, which this path
    does not do. So there is no name an importer could bind, and the honest
    answer is the refusal.

    It is a `refuse` in substance: the build must FAIL and the message must
    name the module and say GENERIC. If a future change makes this build, this
    test fails — which is the point, because the only way to make it build is
    to publish the template under its base name, and that is a run-time wrong
    answer rather than a build error.
    """
    root = os.path.join(tmpdir, "genericonly")
    os.makedirs(root)
    write_tree(root, {"mylib/__init__.mojo": GENERIC_ONLY_MODULE,
                      "prog.mojo": "from mylib import widen\n"
                                  "def main():\n  return 0\n"})
    fresh_cas()
    result, _out = build(root, "prog.aout", expect_ok=False)
    check(result.returncode != 0,
          "a module exporting only a generic template built successfully; one "
          "trie entry cannot be two instantiations, so a call with different "
          "type arguments would silently bind the first one's body")
    text = result.stderr or result.stdout
    check("__init__.mojo" in text,
          f"the refusal does not name the module: {text.strip()[-300:]}")
    check("GENERIC" in text,
          f"the refusal does not say the export is blocked by genericity: "
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


TESTS = [
    ("an import links the module and the program runs",
     test_import_links_and_runs),
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
    ("a program with no imports builds no dylib",
     test_no_import_needs_no_dylib),
    ("a struct method is callable across modules",
     test_struct_method_across_modules),
    ("a one-word struct's field IS its value",
     test_one_word_struct_field_is_the_value),
    ("a struct too wide for one word is refused with the switch off",
     test_wide_struct_is_refused_with_the_switch_off),
    ("a two-field struct builds and runs by reference",
     test_wide_struct_runs_by_reference),
    ("a __future__ import is inert, not a dependency",
     test_future_import_is_inert),
    ("a guarded import is inert too", test_guarded_imports_stay_inert),
    ("a repository sibling resolves", test_repository_sibling_resolves),
    ("a package-relative dotted import resolves",
     test_package_relative_dotted_import_resolves),
    ("a host module is refused despite a same-named sibling",
     test_host_module_still_refused_despite_same_named_sibling),
    ("a package that only re-exports builds and runs",
     test_package_reexport_builds_and_runs),
    ("a package dylib exports nothing and says namespace",
     test_namespace_library_exports_nothing),
    ("a re-export nothing provides is refused by name",
     test_reexport_of_an_unexported_name_is_refused),
    ("a module dylib matches the program's arch, both arches",
     test_module_dylib_matches_the_programs_arch),
    ("both architectures' libraries coexist",
     test_both_arch_libraries_coexist),
    ("a re-exported type reaches the importer",
     test_reexported_type_reaches_the_importer),
    ("a local Mojo module beats the host-module list",
     test_mojo_source_beats_host_module),
    ("a module exporting only a generic template is refused",
     test_a_module_with_no_boundary_symbol_is_refused),
    ("a generic template is not exported under its base name",
     test_a_generic_template_is_not_exported_under_its_base_name),
    ("a C-library-named definition is not blamed on privacy",
     test_a_clib_named_definition_is_refused_not_blamed_on_privacy),
    ("a concrete and a generic of one name are told apart",
     test_a_concrete_and_a_generic_of_one_name_are_told_apart),
    ("a public generic is not reported as private",
     test_a_public_generic_is_not_reported_as_private),
]


# ── known failures, recorded rather than hidden ──────────────────────────────
#
# The same contract as `test_formal.py`'s EXPECTED_FAILURES and as an
# `expect='<why>'` marker in tools/suite.py: a test listed here that PASSES is
# reported as a FAILURE, because a marker nobody revisits is a bug quietly
# reintroduced. So these are pins in both directions — they cannot rot green,
# and they cannot rot red.
#
# All three are message-ACCURACY guards for `no_public_api_reason`, and all
# three are live defects on this tree rather than unimplemented features. Each
# names the stdlib module it was measured on, because "a test is red" is not a
# reason and "std/memory/memory.mojo is told it has no public declarations
# when it has fifteen" is. Full analysis, reproducers and the cost of each fix:
# bugs/FORMAL_known_limits.md §1.3.
EXPECTED_FAILURES = {
    "a C-library-named definition is not blamed on privacy":
        "formal/build.py's no_public_api_reason falls through to an "
        "unconditional 'every declaration in it is private (a leading `_`)' "
        "for any module with a concrete public function that exports nothing, "
        "because all four named branches are gated on `not concrete_funcs`. "
        "Measured on std/memory/memory.mojo (fifteen public functions, four "
        "private) and on a one-function `def strlen` reproducer. The real "
        "cause is reflect._CLIB_SYMS. Fix: a fifth branch naming the excluded "
        "symbol, and a fall-through that states no reason it has not checked.",

    "a concrete and a generic of one name are told apart":
        "formal/build.py's _declared_api_shape collects generics into a set "
        "of NAMES and looks each parsed FunctionDef up in it, so a name that "
        "is concrete in one definition and a template in another is counted "
        "as a template twice. Measured on std/sys/terminate.mojo, whose "
        "concrete `def exit():` is reported as a GENERIC template. Fix: "
        "classify per definition rather than per name.",

    "a public generic is not reported as private":
        "no_public_api_reason's 'both private and parametric' branch is "
        "gated on the module having ANY private declaration and then asserts "
        "the properties of the generics themselves. Measured on "
        "std/memory/unsafe.mojo: two public generics (bitcast, pack_bits) and "
        "one private helper, reported as 'the only function it declares … "
        "which is both private and parametric'. Fix: gate on the "
        "intersection set(gen_funcs) & set(private).",
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: formal output is arm64-only, host is "
              f"{platform.machine()}")
        return 0

    passed = failed = expected = 0
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

    print(f"\nformal imports: PASS={passed} EXPECTED={expected} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        _drop_cas_home()
