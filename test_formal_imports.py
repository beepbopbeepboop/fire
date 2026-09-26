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
     non-zero exit, not a traceback and not a silently broken binary.

Invoked directly:
    python3 test_formal_imports.py [-v]
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

# The independent Mach-O reader and the CLI driver live in the dylib suite;
# imported rather than copied so a fix to the reader cannot leave a second,
# quietly different one behind.
from test_formal_dylib import (TestFailure, check, parse_macho, read_uleb,
                               run_fire)

FIRE = os.path.join(HERE, "fire.py")
CAS_IMPORTS = os.path.expanduser("~/.gmojo/cas/formal-imports")

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
    shutil.rmtree(CAS_IMPORTS, ignore_errors=True)


def build(root, name, expect_ok=True):
    out = os.path.join(root, name)
    result = run_fire(["build", "--formal", "--no-prove", "-o", out,
                       os.path.join(root, name.replace(".aout", ".mojo"))],
                      cwd=root)
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
    dylib = os.path.join(CAS_IMPORTS, "mylib.dylib")
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
    for name in ("mylib.dylib", "other.dylib"):
        check(os.path.isfile(os.path.join(CAS_IMPORTS, name)),
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
    pkg = os.path.join(CAS_IMPORTS, "pkg.dylib")
    with open(pkg, "rb") as f:
        data = f.read()
    check(b"base" in data, "sanity: the module's code should mention base")
    leaf_sym = [e["symbol"] for e in
                manifest(os.path.join(CAS_IMPORTS, "leaf.dylib"))["exports"]
                if e["name"] == "base"][0]
    check(leaf_sym.encode() in data,
          f"pkg.dylib does not reference the leaf export {leaf_sym!r}; a "
          f"cross-module call must use the dependency's exported spelling")
    check(b"_base\x00" not in data.replace(b"_" + leaf_sym.encode() + b"\0", b""),
          "pkg.dylib still carries an unqualified reference to `base`")
    # and the load command that makes the bind possible
    r = subprocess.run(["otool", "-L", pkg], capture_output=True, text=True)
    check("leaf.dylib" in r.stdout,
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
    check("leaf.dylib" in lines[0] and "pkg.dylib" in lines[1],
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
    check(not os.path.isdir(CAS_IMPORTS) or
          not os.listdir(CAS_IMPORTS),
          "a program with no imports built module dylibs anyway")



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
    dylib = os.path.join(CAS_IMPORTS, "slib.dylib")
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


def test_wide_struct_is_refused_by_name(tmpdir, _shared):
    """A struct too wide for one word must be refused where the decision is.

    It used to reach the call path and become a BL against a symbol named
    after the type, so the image built and then aborted in dyld with
    "Symbol not found" — a loader failure pointing at a compile-time limit."""
    src = os.path.join(tmpdir, "wide.mojo")
    with open(src, "w") as f:
        f.write("struct Pair:\n  var a: Int\n  var b: Int\n"
                "def main() -> Int:\n  var p = Pair()\n  return 0\n")
    out = os.path.join(tmpdir, "wide.aout")
    result = run_fire(["build", "--formal", "--no-prove", "-o", out, src])
    check(result.returncode != 0, "a two-field struct was accepted silently")
    text = result.stderr + result.stdout
    check("Pair" in text and "word" in text,
          f"the refusal should name the struct and the limit: {text[-300:]}")
    check("dyld" not in text and "Symbol not found" not in text,
          f"this must fail at compile time, not in the loader: {text[-300:]}")


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
    ("a struct too wide for one word is refused by name",
     test_wide_struct_is_refused_by_name),
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

    print(f"\nformal imports: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
