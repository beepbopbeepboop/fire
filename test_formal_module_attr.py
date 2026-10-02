#!/usr/bin/env python3
"""Module attribute access on the formal path: `mod.NAME`.

`import mod` binds a MODULE, and everything a program then says about that
module is an attribute of it: a call (`os.path.join(a, b)`), a constant
(`os.sep`, `math.pi`), a chain through a submodule (`pkg.sub.fn(x)`), a name
the module RE-EXPORTS (`pkg.fn(x)` where `fn` is defined in `pkg.sub`). All
four are read through the same thing — the manifest of the library built for
that module — and all four were refused or mis-bound:

  * a call through a dotted chain worked only by accident, and a call to a
    RE-EXPORTED name did not bind at all. A package `__init__` that is nothing
    but `from .sub import f` publishes `f` and has an EMPTY export trie on
    purpose (a re-export is not a new definition, so a trie entry for it is an
    address lookup into an image with no code), and the dotted table had no
    re-exports in it. So `pkg.f(...)` found nothing, was not refused — there
    was no table to report — and reached the link audit as a dangling symbol,
    while `from pkg import f` bound fine. The same function, reachable only
    through the spelling that renames what it calls.
  * a module-level CONSTANT of another module was refused outright, on the
    grounds that "a module-level name is not exported as a word". That is
    true of a VARIABLE and false of a folded literal: there is exactly one
    value of a module-level name the build can fold (the module-level sequence
    is its only writer, and a function that assigns the name shadows it), so
    the build that compiled the module is the authority on that value and the
    importer can materialize the same literal in its own image. No storage is
    involved, which is why this is a substitution and not a symbol.
  * a name the module does not publish at all reached the linker as a dangling
    symbol when the module had a table to be missing from, and a bracketed
    callee (`f[x](...)`) was reported as a READ with no storage — a false
    statement about a call.
  * a dotted READ of a module — `sys.argv`, `sys.stderr`, `mod.K` in a value
    position — was refused as a STORAGE problem about the module ROOT:
    "'sys' is imported from `sys`, and it is a module-level name of another
    module … there is no storage for one here". Every clause is false about
    `sys`: it is not a module-level name of `sys`, it IS the module, and a
    module is not a variable with nowhere to live — it is the library on the
    link line, with a manifest. The name that has no representation is the
    ATTRIBUTE, and that is what the message now says. Six files were refused
    with the old wording on both architectures, which is what
    `tools/formal_sweep_causes.py` files under the cause "a module-level name of
    ANOTHER module is not exported as a word".

What is asserted here, and why each one is a separate test:

  1. the four READABLE shapes build, RUN, and agree with CPython running the
     same program — a call, a re-exported call, a submodule chain, and a
     constant in both spellings. Every case is built for BOTH architectures and
     run wherever the host can run the image, because the failure this backend
     cannot have is one architecture answering differently from the other
     (measured, repeatedly: the same source returned 10 on arm64 and 0 on
     x86-64 where it says 5).
  2. the shapes that must STAY refused stay refused, each for its own reason
     and with a message that names it: a STORE to another module's constant, a
     module-level LIST (a real global with nowhere to live,
     `bugs/FORMAL_module_state_no_storage.md`), and a name the module does not
     publish.
  3. the manifest is the contract, and it says what the consumer needs: which
     module the library IS, the constants it publishes, and the symbol each
     re-export really resolves to. Checked by reading the JSON, because a
     consumer that cannot find those has to guess, and guessing is what this
     whole mechanism exists to prevent.
  4. a module OBJECT still has no storage: `len(mylib)` is refused, because
     exempting a call's root must not exempt a read of the same name. That is
     the test that would catch the fix being scoped to the name instead of to
     the call position — and it is the sibling of the ATTRIBUTE-read cases, so
     the two halves of the scoping are adjacent.
  5. an attribute READ is refused as the attribute, from `main` AND from a
     module body, and is never reported as a variable — plus the structural
     half, that such a chain never reaches the emitter unrefused, because the
     emitter would emit `#0` for it and the program would print 0 and exit 0.
  6. a folded constant is readable in EVERY position. `print(mod.K)` lowered
     while `x = mod.K` was refused, from one walk and one message, because the
     store's value side re-entered the node walk instead of being tested.

Invoked directly:
    python3 test_formal_module_attr.py [-v]
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
from test_formal_dylib import TestFailure, check, run_fire

FIRE = os.path.join(HERE, "fire.py")

# Module dylibs are written per ARCHITECTURE (formal/build.py's
# `_resolve_imports`): a dylib is a target-specific image, so an arm64 library
# and an x86-64 library for the same source are two artifacts, not two
# versions of one. A test that looks for a built dylib therefore has to ask for
# the architecture it built.
#
# This file also gets a CAS of its OWN, set before `cas` is imported, for the
# reason `test_formal_imports.py` sets one: `fresh_cas()` below deletes the
# whole module-dylib directory, which against the shared `~/.gmojo` is only
# safe when this file runs alone. An isolated home also stops this file
# reading another tree's dylibs, so a case cannot pass on a library it did not
# build.
_CAS_HOME = tempfile.mkdtemp(prefix="formal_module_attr_cas_")
os.environ["GMOJO_HOME"] = _CAS_HOME
CAS_IMPORTS_ROOT = os.path.join(_CAS_HOME, "cas", "formal-imports")

HOST = platform.machine()
ARM = ("arm64", "aarch64")
X86 = ("x86_64", "amd64")
ARCHES = ("arm64", "x86_64")
BUILD_TIMEOUT = 600
RUN_TIMEOUT = 120

# An arm64 host runs an x86-64 IMAGE through Rosetta, and this file's most
# valuable comparison is the one between the two backends' answers — so the
# foreign image is run wherever the host can execute it at all. Rosetta
# installs this runtime; its absence is the only reason an arm64 host cannot
# run one, and it is a fact about the machine rather than about the image.
_ROSETTA = "/Library/Apple/usr/libexec/oah/libRosettaRuntime"


def runnable(arch):
    """Whether this host can EXECUTE an image built for `arch`.

    Every case is built for both architectures whatever the host is — the two
    emitters disagreeing is the failure this file exists to catch, and only
    running both images finds it. Running the foreign one needs Rosetta, and a
    host without it is a reason to run fewer images, never to build fewer."""
    if HOST in ARM:
        return arch == "arm64" or os.path.exists(_ROSETTA)
    return HOST in X86


# A module whose whole API is a mix of the three things a dylib publishes: a
# function, and two module-level names the build can fold to literals. `CONST`
# and `S` are the shapes `os.sep` and `math.pi` have, and `addup` is the shape
# every `mod.fn(x)` in this tree has.
LIB = """\
CONST = 41
S = "hello"

def addup(a, b):
  return a + b
"""

# A package whose API is entirely re-exported — the shape every stdlib
# `__init__.mojo` has, and the one that used to be unreachable through the
# spelling `import pkg` binds.
PKG_SUB = """\
def twice(n):
  return n * 2


LIMIT = 7
"""

PKG = "from .sub import twice\nfrom .sub import LIMIT\n"

# A private name: `doc/ABI.md`'s export rule keeps it off the boundary, and a
# call to it is an export gap rather than a storage one.
PRIV = """\
def _helper(x):
  return x + 1


def pub(x):
  return x
"""


def write_tree(root, files):
    """Write `files` under `root` and RETURN them, so a case can hand the same
    dict to the CPython oracle (`cpython`) without repeating the tree."""
    for rel, text in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
    return files


def fresh_cas():
    shutil.rmtree(CAS_IMPORTS_ROOT, ignore_errors=True)


def module_dylib(prefix, arch="arm64"):
    """The built library for `prefix`, found by prefix rather than by name.

    A module library's file name is `<prefix>.<source-digest>.<arch>.dylib`:
    the digest is there so two builds of the same module name cannot overwrite
    each other, and the arch is there so the two architectures cannot either.
    So the name is only stable up to the digest, and every case that wants a
    library has to look it up."""
    import glob
    found = sorted(glob.glob(os.path.join(
        os.path.join(CAS_IMPORTS_ROOT, arch), f"{prefix}.*.{arch}.dylib")))
    if not found:
        raise AssertionError(
            f"no module dylib for {prefix!r} under {CAS_IMPORTS_ROOT}/{arch}")
    if len(found) > 1:
        raise AssertionError(
            f"{prefix!r} has more than one library, which means two different "
            f"sources claimed one name: {found}")
    return found[0]


def manifest(dylib):
    with open(dylib + ".manifest.json") as f:
        return json.load(f)


def build(root, name, arch):
    out = os.path.join(root, f"{name}.{arch}.aout")
    argv = ["build", "--formal", "--no-prove", "--backend", arch, "-o", out,
            os.path.join(root, f"{name}.mojo")]
    result = run_fire(argv, cwd=root)
    check(result.returncode == 0,
          f"`--backend={arch}` build failed: "
          f"{(result.stderr or result.stdout).strip()[-400:]}")
    check(os.path.isfile(out), f"no executable written at {out}")
    return out


def build_expecting_refusal(root, name, arch):
    out = os.path.join(root, f"{name}.{arch}.aout")
    argv = ["build", "--formal", "--no-prove", "--backend", arch, "-o", out,
            os.path.join(root, f"{name}.mojo")]
    result = run_fire(argv, cwd=root)
    text = (result.stderr or result.stdout or "")
    check(result.returncode != 0,
          f"`--backend={arch}` BUILT {name}.mojo, which must be refused")
    check(not os.path.isfile(out),
          f"a refused build still wrote {out}")
    return text


def run(out):
    p = subprocess.run([out], capture_output=True, text=True,
                       timeout=RUN_TIMEOUT)
    return p.returncode, p.stdout, p.stderr


# The oracle is CPython running THE SAME PROGRAM TEXT, not a table of expected
# values written here: a hand-written expectation is a second implementation of
# the answer, and this file's subject is a construct whose whole difficulty is
# that the two spellings of it disagree. `printf` is the one thing the program
# text needs and CPython does not have, so it is defined here — through the
# same C library the formal image calls, so the two are formatting with one
# implementation.
_CPYTHON_SHIM = '''\
import ctypes
_libc = ctypes.CDLL(None)


def printf(fmt, *args):
  if args:
    fmt = fmt % args
  return _libc.printf(fmt.encode("utf-8"))
'''


def cpython(source, root, name, files):
    """`(exit code, stdout)` for CPython running `source` over `files`, or None.

    A MIRROR TREE, and that is the whole trick: the formal build's inputs are
    `.mojo` files, which CPython's importer cannot load, so the same bytes are
    written beside them as `.py` and the program runs there. The mirror is
    written from the same `files` dict the formal tree was written from, so the
    two runs differ in the file EXTENSION and in nothing else — which is what
    makes this an oracle rather than a second implementation. (Writing the
    `.py` copies into the formal tree instead would make the comparison depend
    on `formal/imports.py`'s resolution order preferring `.mojo` over a `.py`
    sibling, and a test whose oracle depends on the thing under test is not an
    oracle.)

    None when CPython cannot run it at all — the program text is then not a
    fair oracle and the case says so rather than comparing against nothing.
    The programs are written so that it can: `def main():` with no parameters,
    because the formal entry stub passes the test input in a register and a
    CPython oracle has to be callable with no arguments."""
    mirror = os.path.join(root, "cpython")
    shutil.rmtree(mirror, ignore_errors=True)
    write_tree(mirror, {rel[:-len(".mojo")] + ".py" if rel.endswith(".mojo")
                        else rel: text
                        for rel, text in files.items()})
    path = os.path.join(mirror, f"{name}.cpython.py")
    with open(path, "w") as f:
        f.write(_CPYTHON_SHIM + "\n" + source + "\n\nimport sys\n"
                "sys.exit(main())\n")
    p = subprocess.run([sys.executable, path], capture_output=True, text=True,
                       timeout=RUN_TIMEOUT, cwd=mirror)
    if p.returncode not in (0, *range(1, 256)):
        return None
    return p.returncode, p.stdout


def agrees_with_cpython(root, name, files, program, verbose=False):
    """Build `program` on both architectures, run it, and compare the answers.

    Three comparisons, and the third is the one this backend has historically
    failed: the program's own answer against CPython's, on each architecture,
    and then the two architectures against EACH OTHER. A construct that lowers
    to different code per architecture is a silent wrong answer on one of them,
    and only running both images finds it.

    `files` is the tree the formal build reads, and the CPython oracle gets the
    same bytes (see `cpython`). Returns the per-architecture `(code, stdout)`
    so a caller can say more about what was compared."""
    fresh_cas()
    want = cpython(program, root, name, files)
    answers = {}
    for arch in ARCHES:
        out = build(root, name, arch)
        if not runnable(arch):
            if verbose:
                print(f"      {arch}: built; this host cannot run it")
            continue
        code, stdout, stderr = run(out)
        answers[arch] = (code, stdout)
        if want is None:
            continue
        check((code, stdout) == want,
              f"{arch}: `{name}` returned {code} and printed {stdout!r}; "
              f"CPython running the same program returned {want[0]} and "
              f"printed {want[1]!r}. stderr: {stderr[:200]!r}")
    if len(answers) == 2 and want is not None:
        (a_code, a_out), (b_code, b_out) = answers["arm64"], answers["x86_64"]
        check((a_code, a_out) == (b_code, b_out),
              f"the two architectures disagree about the same program: arm64 "
              f"returned {a_code} and printed {a_out!r}, x86_64 returned "
              f"{b_code} and printed {b_out!r}. One language implementation "
              f"cannot have two answers, and a difference here is a silent "
              f"wrong answer on one of them")
    if verbose:
        print(f"      {len(answers)} image(s) run, CPython says {want}")
    return answers


# ── the four readable shapes ──────────────────────────────────────────────

def test_a_module_qualified_call_runs(tmpdir, _shared, verbose):
    """`import mylib` then `mylib.addup(a, b)` — the plain dotted call.

    The reference case: the name is a function the module DEFINES, so the
    library's export table has it under the module's own ABI identity and the
    emitter's dotted lookup finds it. Every other case here is a variation on
    this one, so it is the one that has to be right first."""
    prog = ("import mylib\n\n"
            "def main():\n"
            "  printf(\"sum=%d|\", mylib.addup(2, 3))\n"
            "  return mylib.addup(2, 3)\n")
    root = os.path.join(tmpdir, "dotted_call")
    os.makedirs(root)
    files = write_tree(root, {"mylib.mojo": LIB, "prog.mojo": prog})
    agrees_with_cpython(root, "prog", files, prog, verbose)
    m = manifest(module_dylib("mylib"))
    check(any(e["name"] == "addup" for e in m["exports"]),
          f"the module does not export the function the call binds: "
          f"{m['exports']}")


def test_a_reexported_function_is_callable_through_the_package(
        tmpdir, _shared, verbose):
    """`import pkg` then `pkg.twice(n)` — a name the package FORWARDS.

    This is the case that did not work, and the shape of the failure is why it
    is worth its own test rather than a line in the one above. A package whose
    whole API is `from .sub import twice` has an empty export table ON PURPOSE:
    the export trie is an address lookup, and an entry for a symbol this image
    does not contain sends every consumer to an address inside a file with no
    code. The forwarding is recorded in the manifest instead, under
    `reexports`, with the symbol the DEFINING module really exports — so
    `pkg.twice(...)` has to bind through that record, and did not: it found no
    table, was not refused (there was nothing to report), and reached the link
    audit as a dangling symbol. `from pkg import twice` bound fine throughout,
    which is what made this look like a spelling problem rather than a missing
    table.

    The program uses BOTH spellings and both must agree, because the two are
    the same function and the fix makes them resolve to the same symbol."""
    prog = ("import pkg\n"
            "from pkg import twice\n\n"
            "def main():\n"
            "  printf(\"a=%d b=%d|\", pkg.twice(5), twice(5))\n"
            "  return pkg.twice(5) + twice(21)\n")
    root = os.path.join(tmpdir, "reexport")
    os.makedirs(root)
    files = write_tree(root, {"pkg/__init__.mojo": PKG,
                              "pkg/sub.mojo": PKG_SUB, "prog.mojo": prog})
    agrees_with_cpython(root, "prog", files, prog, verbose)
    pkg = manifest(module_dylib("pkg"))
    check(pkg.get("kind") == "namespace" and pkg.get("exports") == [],
          f"the package library is not a namespace with an empty export "
          f"table: {pkg.get('kind')!r} {pkg.get('exports')!r} — an entry for a "
          f"re-exported symbol here is an address lookup into an image with no "
          f"code")
    fwd = (pkg.get("reexports") or {}).get("twice") or {}
    check(fwd.get("symbol"),
          f"the manifest does not record what `twice` forwards to: "
          f"{pkg.get('reexports')!r}")
    sub_sym = [e["symbol"] for e in manifest(module_dylib("pkg_sub"))["exports"]
               if e["name"] == "twice"]
    check(sub_sym and fwd["symbol"] == sub_sym[0],
          f"the forwarding names {fwd.get('symbol')!r} but the submodule "
          f"defines {sub_sym!r}; a re-export must bind the DEFINITION, or the "
          f"two spellings of one function would be two addresses")
    # And the module that owns the forwarding is named by its resolved
    # identity, not by the `.sub` the source spelled: the manifest is read by
    # builds that have never seen this file.
    check(fwd.get("module") == "pkg.sub",
          f"the re-export records {fwd.get('module')!r}; a relative spelling "
          f"means nothing outside the file that wrote it")


def test_a_submodule_chain_runs(tmpdir, _shared, verbose):
    """`import pkg.sub` then `pkg.sub.twice(n)` — the chain, one level down.

    Kept separate from the re-export case because the two differ in WHERE the
    name lives: a submodule is a library with its own manifest and its own ABI
    prefix (`pkg_sub`), while a re-export is a forwarding recorded in another
    module's manifest. The qualifier a caller writes (`pkg.sub`) is neither of
    those strings, and this is the case that pins the normalization."""
    prog = ("import pkg.sub\n\n"
            "def main():\n"
            "  printf(\"%d|\", pkg.sub.twice(5))\n"
            "  return pkg.sub.twice(5)\n")
    root = os.path.join(tmpdir, "submodule_chain")
    os.makedirs(root)
    files = write_tree(root, {"pkg/__init__.mojo": "from .sub import twice\n",
                              "pkg/sub.mojo": PKG_SUB, "prog.mojo": prog})
    agrees_with_cpython(root, "prog", files, prog, verbose)


def test_a_module_constant_is_readable_in_both_spellings(tmpdir, _shared,
                                                        verbose):
    """`mod.CONST`, `mod.S`, and `from mod import CONST` — a module-level name.

    The capability, and the argument for it is short enough to state here: a
    module-level name the build FOLDED TO A LITERAL has exactly one value in a
    whole program. The module-level sequence is its only writer, and a function
    that assigns the name binds a local of the same name, which shadows it — so
    there is nothing to store and nothing that can change it. That is why the
    in-unit substitution can put the literal at every read; what was missing
    across a dylib boundary was only the build that computed the value, and it
    leaves it in the manifest.

    Three spellings, because they are three different questions and a fix that
    answered one of them would leave the others refused: the dotted read
    (`mylib.CONST`), the bare read of a from-import (`CONST`), and a STRING
    constant — which is a different node kind in the AST and a different value
    in the manifest, so a fix that only ever folded integers would pass the
    first two and fail this."""
    prog = ("import mylib\n"
            "from mylib import CONST, S\n\n"
            "def main():\n"
            "  printf(\"%d %s %d %s|\", mylib.CONST, mylib.S, CONST, S)\n"
            "  return mylib.CONST + CONST\n")
    root = os.path.join(tmpdir, "constants")
    os.makedirs(root)
    files = write_tree(root, {"mylib.mojo": LIB, "prog.mojo": prog})
    agrees_with_cpython(root, "prog", files, prog, verbose)
    m = manifest(module_dylib("mylib"))
    check(m.get("constants") == {"CONST": 41, "S": "hello"},
          f"the manifest does not record the module's folded constants, or "
          f"records something else: {m.get('constants')!r} — a consumer cannot "
          f"answer `mod.CONST` from a manifest that does not carry the value")


def test_a_constant_reaches_the_importer_through_a_package(tmpdir, _shared,
                                                          verbose):
    """`pkg.LIMIT` — a constant the package RE-EXPORTS.

    The two mechanisms meet here, and this is the case where they have to meet
    rather than merely coexist. A re-exported constant is not in the package's
    export table (a constant has no symbol) and not in its own manifest's
    `exports` either, so the consumer has to be able to ask the PACKAGE — and
    the package's own build is the only place that knows the name is a constant
    rather than a private function, because `declared_kinds` does not recognize
    a module-level binding and reports it as `unknown`."""
    prog = ("import pkg\n\n"
            "def main():\n"
            "  printf(\"%d|\", pkg.LIMIT)\n"
            "  return pkg.LIMIT\n")
    root = os.path.join(tmpdir, "reexported_constant")
    os.makedirs(root)
    files = write_tree(root, {"pkg/__init__.mojo": PKG,
                              "pkg/sub.mojo": PKG_SUB, "prog.mojo": prog})
    agrees_with_cpython(root, "prog", files, prog, verbose)
    pkg = manifest(module_dylib("pkg"))
    check((pkg.get("constants") or {}).get("LIMIT") == 7,
          f"the package library does not publish the constant it re-exports: "
          f"{pkg.get('constants')!r}")


# ── the shapes that must stay refused, each for its own reason ─────────────

def test_a_store_to_a_module_constant_is_refused(tmpdir, _shared, verbose):
    """`mylib.CONST = 9` — a WRITE, which is not a read and has no home.

    The negative that matters most for this fix, because a substitution pass
    that walked store targets would turn a REFUSED store into a DROPPED one:
    the program would build, run, and behave as if the assignment were not
    there, which is the outcome this backend exists to refuse rather than
    produce. A module-level name in another module is a real global, and a real
    global has nowhere to live on this path
    (`bugs/FORMAL_module_state_no_storage.md`)."""
    prog = ("import mylib\n\n"
            "def main():\n"
            "  mylib.CONST = 9\n"
            "  return 0\n")
    root = os.path.join(tmpdir, "store")
    os.makedirs(root)
    write_tree(root, {"mylib.mojo": LIB, "prog.mojo": prog})
    for arch in ARCHES:
        text = build_expecting_refusal(root, "prog", arch)
        check("VARIABLE" in text or "storage" in text,
              f"{arch}: the refusal must say the write has nowhere to live: "
              f"{text.strip()[-300:]}")


def test_a_module_level_list_is_still_refused(tmpdir, _shared, verbose):
    """`mod.LIST` where the value is a LIST — the case the fold must not take.

    A list is a blob carved out of the frame of the function that built it, so
    it is not a literal, has no compile-time value, and cannot be materialized
    in another image. The refusal has to be this one and not the constant's: a
    reader who is told "the module does not export this name" when the truth is
    "the value is not a value this path can copy" goes looking for a missing
    definition that is not missing."""
    lib = "ITEMS = [1, 2, 3]\n\n\ndef addup(a, b):\n  return a + b\n"
    prog = ("import mylib\n\n"
            "def main():\n"
            "  printf(\"%d|\", mylib.ITEMS[1])\n"
            "  return 0\n")
    root = os.path.join(tmpdir, "list_constant")
    os.makedirs(root)
    write_tree(root, {"mylib.mojo": lib, "prog.mojo": prog})
    for arch in ARCHES:
        text = build_expecting_refusal(root, "prog", arch)
        check("FORMAL_module_state_no_storage.md" in text
              or "storage" in text,
              f"{arch}: a list has no storage to cross a dylib boundary and "
              f"the refusal must say so: {text.strip()[-300:]}")


def test_a_name_the_module_does_not_publish_is_refused(tmpdir, _shared, verbose):
    """`pkg.nosuchfunction(x)` — the module is linked and does not have it.

    The protective half of the re-export fix. A dotted call is answered from
    ONE module's table, so a name that table does not have must be a build
    error naming the module and what it does publish — not a `BL` against a
    symbol nothing defines, which builds, links, passes every static check and
    then dies in the loader before `main` runs. This is also the case that
    proves the forwarding is consulted as the module's OWN answer rather than
    as a fallback: a namespace library's table is empty of definitions, and if
    the forwarding were ignored this is the message that would have to name
    `twice`."""
    prog = ("import pkg\n\n"
            "def main():\n"
            "  return pkg.nosuchfunction(1)\n")
    root = os.path.join(tmpdir, "unpublished")
    os.makedirs(root)
    write_tree(root, {"pkg/__init__.mojo": PKG, "pkg/sub.mojo": PKG_SUB,
                      "prog.mojo": prog})
    for arch in ARCHES:
        text = build_expecting_refusal(root, "prog", arch)
        check("exports no `nosuchfunction`" in text and "twice" in text,
              f"{arch}: the refusal must name the module, the name and what "
              f"the module DOES publish — including the names it forwards: "
              f"{text.strip()[-400:]}")


def test_a_bracketed_call_to_a_private_name_is_refused_as_an_export_gap(
        tmpdir, _shared, verbose):
    """`priv._helper[1](x)` — a call, refused for the export reason, not storage.

    `f[x](...)` is a comptime specialization of `f` and therefore a call, but
    its callee is a `SubscriptExpr`, so the name check saw a bare identifier
    with no local and reported the module-GLOBAL answer: "a module-level name
    is not exported as a word — there is no storage for it". That is false
    about a call. A call needs a SYMBOL, and the real reason this one has none
    is `doc/ABI.md`'s export rule — a leading `_` is private, and a generic
    template is one symbol per instantiation.

    The measured instance is `std/sys/_assembly.mojo`'s
    `_get_kgen_string[asm]()`, which is the terminal construct for nineteen
    swept files. It stays refused either way (the name is not exportable, so
    there is nothing to bind); what this pins is that the message names the
    real reason, because a reader sent to look for storage finds a private
    generic with no storage question at all."""
    prog = ("from priv import _helper\n\n"
            "def main():\n"
            "  return _helper[1](2)\n")
    root = os.path.join(tmpdir, "bracketed_private")
    os.makedirs(root)
    write_tree(root, {"priv.mojo": PRIV, "prog.mojo": prog})
    for arch in ARCHES:
        text = build_expecting_refusal(root, "prog", arch)
        check("does not export it" in text and "_helper" in text,
              f"{arch}: a call to a name the module keeps off the boundary "
              f"must be refused as an export gap, naming the name: "
              f"{text.strip()[-400:]}")
        check("no storage for it" not in text,
              f"{arch}: the refusal still claims the call is a read with no "
              f"storage, which is false about a call: {text.strip()[-400:]}")


def test_a_module_object_read_is_still_refused(tmpdir, _shared, verbose):
    """`len(mylib)` — a READ of the module itself, which has no storage.

    The scoping test. Everything this file adds is scoped to an ATTRIBUTE of a
    module, reached through a name the module publishes; a read of the module
    OBJECT is none of those, and the module object is a name with no storage on
    this path (every formal value lives in a function's own stack scratch). If
    this ever builds, the fix has been scoped to the name rather than to the
    construct."""
    prog = ("import mylib\n\n"
            "def main():\n"
            "  return len(mylib)\n")
    root = os.path.join(tmpdir, "module_object")
    os.makedirs(root)
    write_tree(root, {"mylib.mojo": LIB, "prog.mojo": prog})
    for arch in ARCHES:
        text = build_expecting_refusal(root, "prog", arch)
        check("storage" in text or "publishes FUNCTIONS" in text,
              f"{arch}: a read of a module object must be refused as a name "
              f"with no storage: {text.strip()[-300:]}")


# ── the module's ATTRIBUTE read as a value (the `sys.argv` shape) ───────────
#
# Everything above reaches a module through a CALL or through a name the build
# folded. This section is the shape the work map's row "a module-level name of
# ANOTHER module is not exported as a word" actually held: `sys.argv`,
# `sys.stderr`, `mod.K` in a value position — where the ROOT is a module and the
# thing being read is its ATTRIBUTE.
#
# The bug this pins is a DIAGNOSIS that was false about the name it refused, and
# the reason it is a test rather than a reword is that the false version was
# load-bearing in two directions at once: it sent the reader after storage for a
# name that needs none, and it was the reported failure for six files on both
# architectures.

def test_a_module_attribute_read_is_refused_as_an_attribute(
        tmpdir, _shared, verbose):
    """`mylib.ITEMS` — the refusal names the ATTRIBUTE, not the module.

    Before this, `sys.argv` was refused as "'sys' is imported from `sys`, and
    it is a module-level name of another module … there is no storage for one
    here". Every clause of that is false about `sys`: `sys` is not a module-level
    name of `sys`, it IS the module, and a module is not a variable with nowhere
    to live — it is the library on the link line, with a manifest that says what
    it publishes. The name with no representation is `ITEMS`.

    Asserted on both halves, because either alone would pass a message that got
    the shape right and the reason wrong: the message must name the attribute,
    and it must print what the module DOES publish, so a reader can tell a
    capability the module lacks from a name it simply does not have."""
    lib = "ITEMS = [1, 2, 3]\n\n\ndef addup(a, b):\n  return a + b\n"
    prog = ("import mylib\n\n"
            "def main():\n"
            "  printf(\"%d\", mylib.ITEMS[1])\n"
            "  return 0\n")
    root = os.path.join(tmpdir, "attribute_read")
    os.makedirs(root)
    write_tree(root, {"mylib.mojo": lib, "prog.mojo": prog})
    for arch in ARCHES:
        text = build_expecting_refusal(root, "prog", arch)
        check("mylib.ITEMS" in text and "'ITEMS'" in text,
              f"{arch}: the refusal must name the dotted attribute the source "
              f"wrote, not the module root: {text.strip()[-400:]}")
        check("addup" in text,
              f"{arch}: the refusal must print what the module DOES publish, "
              f"so a reader can see `ITEMS` is not one of them: "
              f"{text.strip()[-400:]}")
        check("FORMAL_module_state_no_storage.md" in text,
              f"{arch}: the design note this shape belongs to must be cited: "
              f"{text.strip()[-400:]}")


def test_a_module_root_is_not_reported_as_a_variable(tmpdir, _shared, verbose):
    """The negative of the above, stated as its own test because it is the one
    that can pass while the positive one is green.

    `mylib.ITEMS` must NOT be refused with the bare-name message — "'mylib' is
    imported from `mylib`, and it is a module-level name of another module …
    there is no storage for one here". That sentence is the bug: it is about a
    storage question for a name that is a module, and a reader who believes it
    goes looking for a `__DATA` slot for the module itself. `formal_sweep_causes.py`
    keys a whole CAUSE on that wording, so a file still classified under it is
    evidence the old message is still being produced somewhere."""
    lib = "ITEMS = [1, 2, 3]\n\n\ndef addup(a, b):\n  return a + b\n"
    prog = ("import mylib\n\n"
            "def main():\n"
            "  printf(\"%d\", mylib.ITEMS[1])\n"
            "  return 0\n")
    root = os.path.join(tmpdir, "attribute_not_variable")
    os.makedirs(root)
    write_tree(root, {"mylib.mojo": lib, "prog.mojo": prog})
    for arch in ARCHES:
        text = build_expecting_refusal(root, "prog", arch)
        check("'mylib' is imported from" not in text,
              f"{arch}: the module root was still reported as a module-level "
              f"name of another module with nowhere to live, which is a "
              f"storage claim about a name that is a module: "
              f"{text.strip()[-400:]}")


def test_a_module_attribute_read_is_never_a_silent_zero(tmpdir, _shared,
                                                       verbose):
    """The safety property, and the reason the refusal is not optional.

    Exempting the module ROOT from the name-placement walk is what makes
    `mod.K` reachable at all — and on its own it is a SILENTLY WRONG ANSWER
    rather than a failure. `ARM64Codegen._emit_expr` on
    `MemberExpr(IdentExpr('mod'), 'attr')` finds no frame slot for `"mod.attr"`,
    falls to its "no object model, so the field itself reads as 0" arm,
    evaluates `_load_var('mod')` and emits `#0`. So `printf("%d", mod.attr)`
    would print 0 and exit 0, with a green build and no refusal anywhere.

    So this asserts the STRUCTURAL half — that a rooted member chain never
    reaches the emitter unrefused — rather than only that this program is
    refused. It is checked in-process on the check itself, because a build-level
    assertion cannot tell "refused" from "refused for an unrelated reason later
    in the file": the point is that the REFUSAL IS THIS ONE, at the attribute.
    """
    import formal.build as B
    import formal.model as M
    import fire_compiler as F

    src = ("import mylib\n\n"
           "def main():\n"
           "  var x = mylib.ITEMS\n"
           "  return 0\n")
    stmts = F.Parser(F.py_tokenize(src)).with_filename("t").parse_module()
    fns, structs, syms, _slots = B._prepare_functions(stmts, synthetic=False)
    M.publish_module_symbols(syms)
    refused = ""
    try:
        B.check_module_symbols(fns, {s.name: s for s in structs},
                               imported_module_names=("mylib",))
    except Exception as e:            # CodegenError, by its message
        refused = str(e)
    check(bool(refused),
          "a module-rooted member read reached codegen unrefused, which is the "
          "silently-wrong-zero case: the emitter has no frame slot for it and "
          "emits #0, so this program would build, print 0 and exit 0")
    check("mylib.ITEMS" in refused,
          f"the refusal must be about the attribute, not the root: "
          f"{refused[:300]}")


def test_a_published_constant_is_readable_in_every_position(tmpdir, _shared,
                                                            verbose):
    """`x = mylib.CONST` — the shape that was refused while `print(mylib.CONST)`
    built.

    `_apply_imported_constant_sites` re-entered the NODE walk on a store's value
    side instead of applying `_rewrite_dotted_child` — the ONE test — to it, so
    the value was never itself tested as a dotted constant. Measured: `print(K)`,
    `return K`, `f(K)`, an `if K:`, an f-string and a subscript index all
    lowered; `x = K`, `var x = K` and `x += K` were refused with the message
    that claims a dylib cannot publish a VARIABLE — about a name that is a
    folded CONSTANT the module's own manifest already carries. Same construct,
    same walk, two verdicts, and the one that got it wrong said the opposite
    thing.

    Two of the three store kinds the walk handles are here — `=` and `+=`. The
    third, `var y: int = mod.K`, cannot appear in this file's programs at all:
    the CPython oracle runs the SAME TEXT, and `var` is Mojo syntax CPython
    cannot parse, so a case using it would compare against an oracle that
    cannot run rather than against CPython's answer. `test_the_store_value_side
    _goes_through_the_one_test` below covers that shape by asking the rewriter
    directly, which needs no oracle.

    Pinned as a RUNNING comparison against CPython over the same program text,
    on both architectures, because "it builds" is not the property — the value
    substituted has to be the module's, which is a different failure from a
    refusal and a worse one."""
    prog = ("import mylib\n\n"
            "def main():\n"
            "  x = mylib.CONST\n"
            "  printf(\"%d|\", x)\n"
            "  x += mylib.CONST\n"
            "  printf(\"%d|\", x)\n"
            "  printf(\"%s|\", mylib.S)\n"
            "  return x\n")
    root = os.path.join(tmpdir, "constant_store")
    os.makedirs(root)
    files = write_tree(root, {"mylib.mojo": LIB, "prog.mojo": prog})
    agrees_with_cpython(root, "prog", files, prog, verbose)


def test_the_store_value_side_goes_through_the_one_test(tmpdir, _shared,
                                                        verbose):
    """`var y: int = mod.K` — every store kind, asked of the rewriter directly.

    The third store kind, which cannot go through the CPython oracle because
    `var` is Mojo syntax (`test_a_published_constant_is_readable_in_every_
    position` says so). Asked of `_apply_imported_constant_sites` directly, so
    the assertion is about the REWRITE — that the node standing in a store's
    value slot is itself tested, not merely walked into — and not about whether
    a backend happens to lower the result.

    This is the structural form of a defect that no build-level test can see:
    a rewrite that recurses into a node instead of testing it reports success
    (`return n` still returns a count) and rewrites nothing. So the assertion
    is that the VALUE became a literal, read back off the tree, and that the
    store's TARGET was left alone — `mod.K = 5` writes another module's state
    and is still refused by name elsewhere, so substituting it would trade a
    refused store for a dropped one."""
    import fire_compiler as F
    import formal.build as B

    tables = {"mylib": {"CONST": 41, "S": "hello"}}
    shapes = {
        "assign":    "  x = mylib.CONST\n",
        "augassign": "  x = 1\n  x += mylib.CONST\n",
        "vardecl":   "  var x: int = mylib.CONST\n",
    }
    for label, body in shapes.items():
        src = "import mylib\n\ndef main():\n" + body + "  return 0\n"
        stmts = F.Parser(F.py_tokenize(src)).with_filename("t").parse_module()
        fns, _structs, _syms, _slots = B._prepare_functions(
            stmts, synthetic=False)
        done = B._apply_imported_constant_sites(
            fns[0].body, tables, B._names_bound_in(fns[0]))
        check(done == 1,
              f"{label}: a store whose VALUE is `mod.CONST` rewrote {done} "
              f"site(s), expected 1 — 0 means the value was walked into "
              f"rather than tested, which is the defect (and reported success "
              f"while doing nothing)")
        stmts_after = [n for n in B.M.iter_nodes(fns[0].body)
                       if type(n).__name__ in ("AssignStmt", "AugAssignStmt",
                                               "VarDecl")]
        values = [getattr(n, "value", None) for n in stmts_after]
        check(any(isinstance(v, F.IntLiteral) and v.value == 41
                  for v in values),
              f"{label}: no store's value is the module's literal, so the "
              f"constant did not cross: {values!r}")

    # …and the TARGET of a store to another module is still not rewritten.
    src = "import mylib\n\ndef main():\n  mylib.CONST = 5\n  return 0\n"
    stmts = F.Parser(F.py_tokenize(src)).with_filename("t").parse_module()
    fns, _structs, _syms, _slots = B._prepare_functions(stmts, synthetic=False)
    done = B._apply_imported_constant_sites(
        fns[0].body, tables, B._names_bound_in(fns[0]))
    target = fns[0].body[0].target
    check(done == 0 and isinstance(target, F.MemberExpr),
          f"a store to another module's name was rewritten ({done} site(s)), "
          f"which drops a write that should be refused rather than performed: "
          f"{target!r}")


def test_a_module_attribute_read_from_the_module_body_is_refused_too(
        tmpdir, _shared, verbose):
    """The other shape the six files had, and the reason both are in this file.

    Three of the six refused at `main:` and three at `__module_body__:` — the
    same construct in a different function, because the sweep walks a module
    body as its own function. A fix scoped to `def main` would have moved three
    files and left three, and the work map's count would not have changed."""
    lib = "ITEMS = [1, 2, 3]\n\n\ndef addup(a, b):\n  return a + b\n"
    prog = ("import mylib\n\n"
            "printf(\"%d\", mylib.ITEMS[1])\n")
    root = os.path.join(tmpdir, "attribute_in_body")
    os.makedirs(root)
    write_tree(root, {"mylib.mojo": lib, "prog.mojo": prog})
    for arch in ARCHES:
        text = build_expecting_refusal(root, "prog", arch)
        check("mylib.ITEMS" in text,
              f"{arch}: the module-body shape must be refused by name too: "
              f"{text.strip()[-400:]}")


def test_a_local_shadowing_a_module_name_is_still_the_local(tmpdir, _shared,
                                                            verbose):
    """`def main(mylib): mylib.ADDUP(1, 2)` — a parameter named like a module.

    The scoping test for the exemption itself. The member-read arm is gated on
    the root naming an imported module, and a PARAMETER of that name shadows it
    in exactly the way the shadowing rule says: the read is of a local, whose
    attribute is a frame slot, not a module attribute. Exempting the root by
    NAME rather than by node identity would exempt this one too, and it would
    then be refused with a message about the module — refusing a program whose
    answer is a local's."""
    prog = ("import mylib\n\n"
            "def main(mylib):\n"
            "  return mylib.ADDUP(1, 2)\n")
    root = os.path.join(tmpdir, "shadowing_local")
    os.makedirs(root)
    write_tree(root, {"mylib.mojo": LIB, "prog.mojo": prog})
    for arch in ARCHES:
        text = build_expecting_refusal(root, "prog", arch)
        check("imported from `mylib`" not in text,
              f"{arch}: a parameter that shadows the module name must be read "
              f"as the local it is, not refused as a module attribute: "
              f"{text.strip()[-400:]}")


# ── the manifest is the contract ──────────────────────────────────────────

def test_the_manifest_names_its_module_and_its_constants(tmpdir, _shared, verbose):
    """What a consumer needs, read back out of the JSON.

    Three fields, and each one exists because a consumer could not otherwise
    answer a question it is going to be asked:

      * `module` — which module this library IS. Every export entry already
        carried its module, so a normal library could be keyed from its own
        table, but a namespace library's table is empty BY DESIGN and nothing
        else in its manifest named it: a consumer asking "does `pkg` publish
        `twice`?" had no way to find `pkg` at all.
      * `constants` — the folded values, which are the only thing a dylib
        publishes that is not a symbol.
      * `reexports` — the forwarding, with the symbol the DEFINING module
        exports.

    Read from the file rather than from the object that wrote it, because a
    consumer reads the file and a test that asserted the writer's own dict
    would pass when the writer and the file disagree."""
    root = os.path.join(tmpdir, "manifest_shape")
    os.makedirs(root)
    write_tree(root, {"mylib.mojo": LIB, "pkg/__init__.mojo": PKG,
                      "pkg/sub.mojo": PKG_SUB})
    fresh_cas()
    for name in ("mylib", "pkg"):
        root_src = os.path.join(root, f"user_{name}.mojo")
        with open(root_src, "w") as f:
            f.write(f"import {name}\n\n\ndef main():\n  return 0\n")
        result = run_fire(["build", "--formal", "--no-prove", "-o",
                           os.path.join(root, f"user_{name}.aout"), root_src],
                          cwd=root)
        check(result.returncode == 0,
              f"building a user of `{name}` failed: "
              f"{(result.stderr or result.stdout).strip()[-300:]}")
    m = manifest(module_dylib("mylib"))
    check(m.get("module") == "mylib",
          f"a normal module library does not name itself: {m.get('module')!r}")
    pkg = manifest(module_dylib("pkg"))
    check(pkg.get("module") == "pkg",
          f"a namespace library does not name itself, so a consumer cannot "
          f"key its forwarding by it: {pkg.get('module')!r}")


TESTS = [
    ("`mod.fn(x)` builds, runs, and agrees with CPython",
     test_a_module_qualified_call_runs),
    ("`pkg.fn(x)` for a RE-EXPORTED function binds the definition",
     test_a_reexported_function_is_callable_through_the_package),
    ("`pkg.sub.fn(x)` — a chain through a submodule",
     test_a_submodule_chain_runs),
    ("`mod.CONST` and `from mod import CONST` both lower",
     test_a_module_constant_is_readable_in_both_spellings),
    ("`pkg.LIMIT` — a constant the package re-exports",
     test_a_constant_reaches_the_importer_through_a_package),
    ("a STORE to another module's constant is refused, not dropped",
     test_a_store_to_a_module_constant_is_refused),
    ("a module-level LIST is still refused, as a storage fact",
     test_a_module_level_list_is_still_refused),
    ("a name the module does not publish is refused, naming what it does",
     test_a_name_the_module_does_not_publish_is_refused),
    ("`priv._helper[1](x)` is refused as an export gap, not a storage one",
     test_a_bracketed_call_to_a_private_name_is_refused_as_an_export_gap),
    ("`len(mylib)` — a read of the module object — is still refused",
     test_a_module_object_read_is_still_refused),
    ("`mylib.ITEMS` is refused as the ATTRIBUTE, naming what the module does",
     test_a_module_attribute_read_is_refused_as_an_attribute),
    ("a module root is never reported as a variable with no storage",
     test_a_module_root_is_not_reported_as_a_variable),
    ("a module-attribute read never reaches the emitter as a silent zero",
     test_a_module_attribute_read_is_never_a_silent_zero),
    ("a published constant reads in EVERY position, including a store's value",
     test_a_published_constant_is_readable_in_every_position),
    ("every store kind tests its VALUE side, and a module store stays a store",
     test_the_store_value_side_goes_through_the_one_test),
    ("the same attribute read is refused from a module BODY too",
     test_a_module_attribute_read_from_the_module_body_is_refused_too),
    ("a local that shadows a module name is read as the local it is",
     test_a_local_shadowing_a_module_name_is_still_the_local),
    ("the manifest names its module, its constants and its forwarding",
     test_the_manifest_names_its_module_and_its_constants),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    passed = failed = 0
    with tempfile.TemporaryDirectory(prefix="formal_module_attr_") as tmpdir:
        for name, fn in TESTS:
            try:
                fn(tmpdir, None, args.verbose)
            except TestFailure as e:
                failed += 1
                print(f"  FAIL  {name}\n        {e}")
                continue
            except Exception as e:  # unexpected: report, do not mask
                failed += 1
                print(f"  ERROR {name}\n        {type(e).__name__}: {e}")
                if args.verbose:
                    import traceback
                    traceback.print_exc()
                continue
            passed += 1
            print(f"  PASS  {name}")

    shutil.rmtree(_CAS_HOME, ignore_errors=True)
    print(f"\nformal module attributes: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
