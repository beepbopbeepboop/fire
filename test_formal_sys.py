#!/usr/bin/env python3
"""Tests for the formal backend's `sys` module and the module-call lowering
it is the first real user of.

`formal/hostmods/sys.mojo` is the Mojo source `formal/imports.py`
resolves `import sys` to, so `sys` is no longer in `HOST_MODELLED` and no
file in this tree is refused for importing it. That is worth nothing on its
own — a module nothing can call is a rock — so what is asserted here is the
part that makes it a module:

  1. `import sys` resolves to `formal/hostmods/sys.mojo`, in the resolver's own
     order, and `sys` is not in `HOST_MODELLED` any more;
  2. a program calls it by its REAL Python spelling — `sys.maxsize()`, the
     dotted name `import sys` binds — and gets the right answers, on BOTH
     backends;
  3. a `str` returned across the dylib boundary comes back as a string. It
     did not: the result was unclassified, so `print(sys.version())` printed
     the pointer's own value (measured 4335747904 for a string that says
     "darwin"). The manifest already declared `char *` and nothing read it;
  4. the dotted spelling resolves by MODULE IDENTITY — two modules that both
     export `helper` cannot cross-bind through it — and a MODULE can call
     another module, so the same contract holds inside a dylib's own
     compilation and not only inside the program's;
  5. a dotted call the module does NOT export is refused, naming the module
     and what it does export, instead of emitting a `BL` against a symbol
     nothing defines. `sys.exit(3)` is the real instance and is pinned
     because the answer is a settled decision, not an accident;
  6. the spelling the module's docstring tells a program to use instead —
     `exit(3)`, libSystem's own — builds and exits 3;
  7. the sweep classifies a `sys.argv` refusal as `codegen`, the finding it
     is, rather than as the host-import refusal it used to be. The
     classifier's quoted-name rule asks the BUILD's resolver whether the
     module has a source, and this is the case that made that necessary;
  8. a string literal's escapes are DECODED on this path, as CPython
     decodes them, and the byte counts the module's two writers return say
     so. This one used to be the module's headline limitation, measured and
     pinned as such — until 9023031b moved the escape decoder into
     `fire_compiler.decode_c_escapes` and gave the formal backends the same
     one every other engine already used. It is kept as a test rather than
     dropped because it is the only place the module's writers are checked
     against CPython's own answer for a literal with an escape in it;
  9. and a literal inside a MODULE — a dylib, which is where every host
     module's literals live — is decoded the same way. The program case above
     is not evidence about the module case: they are separate compilations,
     and half a dozen files in this tree still carry a comment saying a `\t`
     in a `.mojo` file is two characters because it used to be. That was
     `bugs/FORMAL_sys_mojos_escape_note_is_stale.md`, whose consequence was to
     check those corpora; 10 says the check's answer, on both architectures.

Invoked directly:
    python3 test_formal_sys.py [-v]
"""
import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
# The module source, at the ONE place the formal resolver finds it. Read from
# `formal/imports.py` rather than spelled out, so this test follows the module
# if the search root moves — and so a path typed here cannot be a second,
# quietly-stale copy of the answer the test is about.
HOSTMODS = os.path.join(HERE, "formal", "hostmods")
SYS_MODULE = os.path.join(HOSTMODS, "sys.mojo")

sys.path.insert(0, HERE)

# The independent driver and the assertion helper live in the dylib suite;
# imported rather than copied so a fix to either cannot leave a second,
# quietly different one behind.
from test_formal_dylib import (TestFailure, check, parse_macho,  # noqa: E402
                               run_fire)

# A CAS of this file's own. A module dylib is cached by content, so a stale
# one from an earlier run could mask a regression, and this file must not
# delete libraries out from under a parallel job in a shared bucket.
_CAS_HOME = tempfile.mkdtemp(prefix="formal_sys_cas_")
os.environ["GMOJO_HOME"] = _CAS_HOME

ARCHES = ("arm64", "x86_64")

# A program that uses the module the way Python spells it: `import sys`, then
# `sys.<name>()`. Every value here is a fixed property of the target, so the
# expected stdout is a constant and not something recomputed by the test.
USE_SYS = """\
import sys

def main():
  print(sys.version())
  print(sys.maxsize())
  print(sys.byteorder())
  print(sys.version_info_major())
  print(sys.getdefaultencoding())
  print(sys.getrecursionlimit())
  return 0
"""

USE_SYS_EXPECT = ("3.14.6 (fire formal backend)\n"
                  "9223372036854775807\n"
                  "little\n"
                  "3\n"
                  "utf-8\n"
                  "0\n")

# The two writers, checked through the module and by their return value, so a
# `write(2)` that returned -1 could not pass as "it printed something".
#
# The source holds a real backslash and an `n`, and CPython decodes that to a
# newline — measured, `sys.stderr.write("to stderr\n")` returns 10 and leaves
# the nine characters plus a real line break on the descriptor. So the counts
# printed here are 10 and 10 and not the 11 and 11 this test asserted while
# the literal reached the image undecoded (before 9023031b).
WRITE_SYS = """\
import sys

def main():
  n = sys.write_stderr("to stderr\\n")
  m = sys.write_stdout("to stdout\\n")
  print(n)
  print(m)
  return 0
"""

# `sys.exit` is deliberately not an export; see the module's own docstring and
# bugs/FORMAL_known_limits.md 1.1 for the settled decision.
CALL_UNEXPORTED = """\
import sys

def main():
  sys.exit(3)
  return 0
"""

# The spelling the module documents instead: libSystem's own `exit`.
CALL_LIBC_EXIT = """\
def main():
  print("before")
  exit(3)
  return 0
"""

# A three-level chain, so the module-call contract is tested where it is
# hardest: program -> midy.dylib -> leafy.dylib -> libSystem, with a `str`
# crossing BOTH dylib boundaries. A module that itself calls another module is
# the dylib path's own version of the same contract, and it is a different
# call site from the program's: `compile_formal_dylib` resolves its
# dependencies and hands their export tables to its emitter, and the name it
# needs there is the same shape.
LEAFY = """\
def base(x) -> int:
  return x * 2


def label(x: int) -> str:
  if x > 10:
    return "big"
  return "small"
"""

MIDY = """\
import leafy


def twice(x) -> int:
  return leafy.base(x) * 2


def tag(x: int) -> str:
  return leafy.label(x)
"""

CHAIN = """\
import midy


def main():
  print(midy.twice(21))
  print(midy.tag(30))
  return 0
"""

# Two modules, one exported name, to pin that the dotted spelling resolves by
# module identity. `left` and `right` both define `which`; a program that
# called `left.which()` must get left's answer and `right.which()` right's.
LEFT = """\
def which() -> str:
  return "left"
"""

RIGHT = """\
def which() -> str:
  return "right"
"""

BOTH = """\
import left
import right

def main():
  print(left.which())
  print(right.which())
  return 0
"""

# The same pair under names this file's other test does not use, so the two
# tests can run in either order without sharing a module file.
BOTH_SPELLED = """\
import lefty
import righty

def main():
  print(lefty.which())
  print(righty.which())
  return 0
"""

# A string escape, which IS interpreted on this path: the bytes are what
# CPython makes of the source. The count the writer returns is checked too,
# so a backend that decoded the escape but still counted the source's
# characters cannot pass.
ESCAPES = """\
import sys

def main():
  n = sys.write_stderr("a\\nb")
  print(n)
  return 0
"""

# The same escape, but inside a MODULE rather than in the program. Every stale
# statement about undecoded escapes in this tree is about module code — they are
# in `formal/hostmods/ast.mojo`, `argparse.mojo`, `os/__init__.mojo` and
# `re.mojo`, all of which are compiled into dylibs, and all of which used to
# spell an awkward byte with `memset` because a literal could not hold one. A
# decoder that works only in the program would leave every one of those true,
# so the module case is its own measurement rather than a corollary.
LITERAL_IN_MODULE = """\
import sys

def size() -> int:
  return sys.write_stderr("a\\nb")

def tabbed() -> int:
  return sys.write_stderr("p\\tq")

def quoted() -> int:
  return sys.write_stderr('y')
"""

MODULE_CALLS_LITERAL = """\
import sys
import litmod

def main():
  print(litmod.size())
  print(litmod.tabbed())
  print(litmod.quoted())
  return 0
"""


def workdir(tmp, name) -> str:
    """A directory of this test's own, for the programs it writes.

    Under the temp root and never the repository: `sys.mojo` is found from a
    program anywhere, because `formal/imports.py`'s `_search_roots` appends
    `formal/hostmods/` to every file's roots, so a program in a temp directory
    resolves `import sys` exactly as one in the tree does — and nothing this
    file writes lands in the checkout.
    """
    root = os.path.join(tmp, name)
    os.makedirs(root, exist_ok=True)
    return root


def build_and_run(root, name, source, expect_exit=0):
    """Write `source` as `<root>/<name>.mojo`, build it formal, run it.

    Returns the run's CompletedProcess. A build that did not succeed raises,
    so no test here can assert on the output of a program that was never
    produced, and `expect_exit` is checked so a program that died in the loader
    cannot pass by printing nothing.
    """
    path = os.path.join(root, name + ".mojo")
    with open(path, "w") as f:
        f.write(source)
    out = os.path.join(root, name + ".aout")
    built = run_fire(["build", "--formal", "--no-prove", "-o", out, path],
                     cwd=root)
    check(built.returncode == 0,
          f"build of {name}.mojo failed: "
          f"{(built.stderr or built.stdout).strip()[-500:]}")
    check(os.path.isfile(out), f"no executable written at {out}")
    ran = subprocess.run([out], capture_output=True, text=True, timeout=60)
    check(ran.returncode == expect_exit,
          f"{name}.mojo exited {ran.returncode}, expected {expect_exit}; "
          f"stderr: {(ran.stderr or '').strip()[-300:]}")
    return ran


def sys_dylib(arch="arm64"):
    """The built `sys` library, from the CAS this file owns."""
    import glob
    found = sorted(glob.glob(os.path.join(
        _CAS_HOME, "cas", "formal-imports", arch, "sys.*.dylib")))
    check(bool(found), f"no sys module dylib built under {_CAS_HOME}")
    return found[-1]


def sys_exports(arch="arm64"):
    """`{name: entry}` from the sys dylib's own manifest."""
    path = sys_dylib(arch) + ".manifest.json"
    with open(path) as f:
        payload = json.load(f)
    return {e["name"]: e for e in payload.get("exports") or []}


# ── resolution ─────────────────────────────────────────────────────────────

def test_sys_resolves_to_the_module_source(tmp, _shared):
    """`import sys` finds `formal/hostmods/sys.mojo`, in the resolver's own order.

    Pass 1 of `resolve_module_path` is Mojo source in a search root, and it
    wins over the host-module list — so this is the assertion that says the
    module is reachable at all, from a file in a SUBDIRECTORY as well as from
    the root, which is the property that makes one shared search root the only
    place it could live.

    The location itself is asserted, not just the resolution: a module source
    back at the repository root resolves from here too, and the whole point of
    `formal/hostmods/` is that NOTHING ELSE in the tree can see it. See
    `test_hostmods_are_invisible_to_every_other_resolver` in
    `test_formal_link_accounting.py` for that half.
    """
    from formal.imports import HOST_MODELLED, resolve_module_path
    check(resolve_module_path("sys", relative_to=os.path.join(HERE, "t1.mojo"))
          == SYS_MODULE,
          "`import sys` from the repository root did not resolve to "
          f"{SYS_MODULE}, got "
          f"{resolve_module_path('sys', relative_to=os.path.join(HERE, 't1.mojo'))!r}")
    nested = os.path.join(HERE, "tools", "ci_line.py")
    check(resolve_module_path("sys", relative_to=nested) == SYS_MODULE,
          "`import sys` from tools/ did not resolve to sys.mojo — the "
          "hostmods root is appended to every file's search roots")
    check("sys" not in HOST_MODELLED,
          "sys is still in HOST_MODELLED: a Mojo source wins over that set, "
          "so the entry no longer describes anything the build does")


def test_every_declared_name_is_exported(tmp, _shared):
    """Every public function in sys.mojo reaches a dylib's export table.

    The export rule (`doc/ABI.md`, via `reflect.collect_exports_src`) is what
    `exit` loses, so a name added here without checking it would produce a
    module that builds and cannot be called. The assertion is over the module's
    OWN declaration list, read from its source, so it fails on the name rather
    than on a count.
    """
    sys.path.insert(0, HERE)
    import fire_compiler as F
    with open(SYS_MODULE) as f:
        stmts = F.Parser(F.py_tokenize(f.read())).parse_module()
    declared = {s.name for s in stmts
                if isinstance(s, F.FunctionDef) and not s.name.startswith("_")}
    check(declared, "sys.mojo declares no public function")
    build_and_run(workdir(tmp, "probe"),
                  "sys_probe", "import sys\n\ndef main():\n"
                               "  return 0\n")
    exported = sys_exports()
    missing = sorted(declared - set(exported))
    check(not missing,
          f"sys.mojo declares {missing} but the export table does not "
          f"advertise {'it' if len(missing) == 1 else 'them'}: a name "
          f"doc/ABI.md's rule excludes is a module nothing can call")


# ── calling it ─────────────────────────────────────────────────────────────

def test_the_python_spelling_runs(tmp, _shared):
    """`sys.maxsize()` — the dotted name `import sys` binds — computes right.

    arm64, which is the architecture the module is written for: on x86-64 a
    module dylib that calls out to libSystem cannot be SIGNED on this host
    (`codesign`: "main executable failed strict validation"), so no program
    linking `sys` can be built for that target at all. That is a pre-existing
    defect with a two-line reproduction and it is filed as
    bugs/FORMAL_x86_64_dylib_externs_unsigned.md; the cross-architecture half
    of the contract is checked by
    `test_the_dotted_spelling_runs_on_both_backends` below, with a module that
    makes no extern calls.
    """
    ran = build_and_run(workdir(tmp, "use"), "sys_use", USE_SYS)
    check(ran.stdout == USE_SYS_EXPECT,
          f"sys.<fn>() printed {ran.stdout!r}, expected {USE_SYS_EXPECT!r}")


def test_the_dotted_spelling_runs_on_both_backends(tmp, _shared):
    """`mod.fn()` resolves and returns a string, on arm64 AND on x86-64.

    The dotted resolution is implemented twice -- `_extern_symbol` and
    `_callee_kind` in each emitter -- and the contract is ONE contract, so a
    test that only ran the host architecture would be a test of half of it. A
    module with no extern calls is used because that is the shape both
    architectures can link (see the test above for the one that cannot).
    """
    if platform.machine() not in ("arm64", "aarch64", "x86_64"):
        print("        SKIP: no Darwin host to run the x86-64 image on")
        return
    src_root = workdir(tmp, "both-src")
    for name, text in (("lefty", LEFT), ("righty", RIGHT)):
        with open(os.path.join(src_root, name + ".mojo"), "w") as f:
            f.write(text)
    prog = os.path.join(src_root, "bothy.mojo")
    with open(prog, "w") as f:
        f.write(BOTH_SPELLED)
    for arch in ARCHES:
        out = os.path.join(workdir(tmp, f"both-{arch}"), "bothy.aout")
        built = run_fire(["build", "--formal", "--no-prove",
                          f"--backend={arch}", "-o", out, prog], cwd=src_root)
        check(built.returncode == 0,
              f"{arch}: build failed: "
              f"{(built.stderr or built.stdout).strip()[-500:]}")
        check(os.path.isfile(out), f"{arch}: no executable written at {out}")
        ran = subprocess.run([out], capture_output=True, text=True, timeout=60)
        check(ran.returncode == 0,
              f"{arch}: the image exited {ran.returncode}; "
              f"stderr: {(ran.stderr or '').strip()[-300:]}")
        check(ran.stdout == "left\nright\n",
              f"{arch}: printed {ran.stdout!r}: a dotted call did not reach "
              f"the module it names, or its `char *` return came back as a "
              f"number")


def test_a_module_can_call_another_module(tmp, _shared):
    """program -> midy -> leafy, and a string comes back across both.

    The same contract one level down: `midy`'s own dylib calls `leafy`'s, so
    the dotted resolution and the return kind are exercised inside a LIBRARY's
    compilation rather than only inside the program's. `tag` returns the
    `char *` that `leafy.label` returned, so one string crosses two dylib
    boundaries and is classified at each hop -- print the pointer instead of
    `big` and this fails.

    arm64, for the reason in `test_the_python_spelling_runs`: a dylib with a
    dependency cannot be codesigned for x86-64 on this host
    (bugs/FORMAL_x86_64_dylib_externs_unsigned.md).
    """
    root = workdir(tmp, "chain")
    for name, text in (("leafy", LEAFY), ("midy", MIDY)):
        with open(os.path.join(root, name + ".mojo"), "w") as f:
            f.write(text)
    ran = build_and_run(root, "chain", CHAIN)
    check(ran.stdout == "84\nbig\n",
          f"printed {ran.stdout!r}: expected 84 (21 * 2 * 2, through two "
          f"modules) and then the string leafy.label returned")


def test_a_string_comes_back_as_a_string(tmp, _shared):
    """A `char *` return crosses the dylib boundary as a string.

    The regression this pins: `ValueKinds` classified a call by asking what
    its callee returns, and a callee that is not a function of the unit being
    compiled had no answer, so the result of `sys.version()` was an
    unclassified word and `print` formatted it as an integer — the pointer,
    printed as 4335747904 where the program meant to print the version. The
    manifest entry says `char *` and nothing was reading it.
    """
    ran = build_and_run(workdir(tmp, "str"), "sys_str", USE_SYS)
    check(ran.stdout.splitlines()[0] == "3.14.6 (fire formal backend)",
          "the first line is not the version string, so a `char *` return is "
          f"not being classified as a string: got {ran.stdout.splitlines()[:1]}")
    # And not a number that happens to look like one: the pointer form is a
    # 9-or-10-digit word in the 4-billion range on this target.
    check(not ran.stdout.splitlines()[0].isdigit(),
          "the version line is digits, which is the miscompiled shape")


def test_the_two_writers_reach_the_right_descriptors(tmp, _shared):
    """`sys.write_stderr` writes to 2 and `sys.write_stdout` to 1.

    The byte count is checked as well as the text, because a `write(2)` that
    failed returns -1 and prints nothing, and "the program produced no
    complaint" is not the same as "it wrote". The count is 10 — the nine
    characters of the text plus the newline the source's `\\n` decodes to —
    and CPython returns 10 for the same call, so the two agree. It was 11
    while a literal reached the image undecoded, before 9023031b; see the
    escape test below, which is where that decoding is pinned.
    """
    ran = build_and_run(workdir(tmp, "write"), "sys_write", WRITE_SYS)
    check(ran.stderr == "to stderr\n",
          f"stderr was {ran.stderr!r}, expected the nine characters and the "
          f"newline the source's escape decodes to")
    check(ran.stdout == "to stdout\n10\n10\n",
          f"stdout was {ran.stdout!r}: expected the decoded text, then the "
          f"two byte counts 10 and 10")


def test_dotted_calls_resolve_by_module_identity(tmp, _shared):
    """`left.which()` and `right.which()` are two different functions.

    The safety property of the dotted table, and the reason it is keyed by
    module rather than by the leaf name: two modules exporting the same name
    must not be able to reach each other's, or `mod.f` would be a coin flip
    decided by link order.
    """
    root = workdir(tmp, "identity")
    for name, text in (("left", LEFT), ("right", RIGHT)):
        with open(os.path.join(root, name + ".mojo"), "w") as f:
            f.write(text)
    ran = build_and_run(root, "sys_identity", BOTH)
    check(ran.stdout == "left\nright\n",
          f"got {ran.stdout!r}: a dotted call did not reach the module it "
          f"names")


def test_a_dotted_call_the_module_does_not_export_is_refused(tmp, _shared):
    """`sys.exit(3)` is refused by name, with the reason in the message.

    `exit` is a C library symbol and `doc/ABI.md`'s export rule does not
    advertise one (`reflect._CLIB_SYMS`; measured and settled in
    bugs/FORMAL_known_limits.md 1.1), so no module dylib can be called by that
    name. Before this the call fell through to the bare name and emitted a
    `BL` against a symbol nothing defines — an image that built, passed every
    static check, and died in the loader. A refusal that names the module and
    what it does export is the whole difference.
    """
    root = workdir(tmp, "unexported")
    path = os.path.join(root, "sys_unexported.mojo")
    with open(path, "w") as f:
        f.write(CALL_UNEXPORTED)
    out = os.path.join(root, "sys_unexported.aout")
    built = run_fire(["build", "--formal", "--no-prove", "-o", out, path],
                     cwd=root)
    detail = (built.stderr or built.stdout).strip()
    check(built.returncode != 0,
          "`sys.exit(3)` built: a module dylib is not called by a name "
          "doc/ABI.md's export rule does not advertise, so the image would "
          "have a call to bind with nothing behind it")
    check("sys.exit()" in detail and "exports no" in detail,
          f"the refusal does not name the call and the reason: {detail}")


def test_the_documented_spelling_exits(tmp, _shared):
    """`exit(3)` — libSystem's own — builds, runs, and exits 3.

    The other half of the previous test, and the reason that one is a settled
    decision rather than a hole: a formal program CAN end with a status, by
    calling the C library directly, and `sys.mojo` says so where a reader of
    `sys` will find it.
    """
    ran = build_and_run(workdir(tmp, "libcexit"), "sys_libc_exit",
                        CALL_LIBC_EXIT, expect_exit=3)
    check(ran.stdout == "before\n", f"stdout was {ran.stdout!r}")


# ── string literals: the escapes are decoded, as CPython decodes them ──────

def test_string_escapes_are_interpreted_as_cpython_does(tmp, _shared):
    """`"a\\nb"` is three bytes and a newline, not a backslash and an `n`.

    This was the module's headline limitation and the reason its two writers
    were documented as needing a REAL newline in the source. 9023031b fixed
    it: `fire_compiler.decode_c_escapes` is now the one decoder every engine
    calls, so the formal backends decode what `fire.py run`, `fire.py build`
    and CPython have always decoded. Checked against CPython's own answers —
    `sys.stderr.write("a\\nb")` writes three bytes and returns 3 — because
    "the escapes are decoded" is only half the claim; the module has to
    measure the DECODED length too, or `strlen` is counting the source.
    """
    ran = build_and_run(workdir(tmp, "escape"), "sys_escape", ESCAPES)
    check(ran.stderr == "a\nb",
          f"stderr was {ran.stderr!r}: expected a real newline between the two "
          f"letters, the way CPython decodes this literal")
    check(ran.stdout == "3\n",
          f"stdout was {ran.stdout!r}: expected the write(2) byte count 3 — "
          f"three decoded bytes, not the five characters of the source")


def test_a_literal_inside_a_module_is_decoded_too(tmp, _shared):
    """`"a\\nb"` in a MODULE is three bytes as well, and `'y'` is one.

    The program case above is not the case the host modules are in. Every one of
    them is compiled into a dylib, and every one of them used to spell an
    awkward byte by writing it with `memset`, because a string literal on this
    path was interned verbatim: `ast.mojo`'s character sets, `argparse.mojo`'s
    separators, `os.linesep`, and `re`'s escape tables all carry a comment
    saying a `\\t` in a `.mojo` file was two characters. That was true until
    9023031b and is false now, in the place that matters — a module — so the
    corpora that were written around it may be simplified and the comments that
    state it as a constraint are wrong.

    Pinned here, on both architectures, because a decoder that reached only the
    program would leave all four of those files telling the truth while this
    suite stayed green: the program and the module are separate compilations,
    and a literal in one is not evidence about the other.

    The three cases are the three spellings those corpora needed and could not
    use: `\\n` (a control byte), `\\t` (a second one), and a single-quoted
    one-character literal (`ast.mojo` says `'x = 'y''` lexed its opening quote
    as a one-character OP, which is why it builds its two-byte quote set with
    `str_alloc` + `memset`).
    """
    root = workdir(tmp, "inmodule")
    for arch in ARCHES:
        with open(os.path.join(root, "litmod.mojo"), "w") as f:
            f.write(LITERAL_IN_MODULE)
        ran = build_and_run(root, "sys_inmodule", MODULE_CALLS_LITERAL)
        check(ran.stderr == "a\nbp\tqy",
              f"[{arch}] stderr was {ran.stderr!r}: expected the module's "
              f"literals decoded — a real newline, a real tab — the way CPython "
              f"decodes them")
        check(ran.stdout == "3\n3\n1\n",
              f"[{arch}] stdout was {ran.stdout!r}: expected the DECODED byte "
              f"counts 3, 3 and 1 across the dylib boundary; 5, 5 and 4 would "
              f"be the source's characters")


# ── the sweep's verdict ────────────────────────────────────────────────────

def test_the_sweep_calls_a_sys_refusal_a_codegen_finding(tmp, _shared):
    """`sys.argv` is `codegen`, not the host-import refusal it was.

    The sweep's classifier treats a message that quotes a module the file
    imports as an import failure, whatever the wording — a rule that made it
    survive a reworded import error. It became wrong the moment `sys` stopped
    being a host module: the module exists, the build resolved it, and what it
    refused is a construct (`model.module_global_refusal`: a name with no
    storage). The rule now asks the build's own resolver whether the module
    has a source, and this is the case that made that necessary.

    Called through `classify` with the swept file's PATH, because the path is
    what the resolver needs and what the sweep passes.
    """
    sys.path.insert(0, os.path.join(HERE, "tools"))
    import formal_sweep as S
    with open(os.path.join(HERE, "t_argv.mojo")) as f:
        source = f.read()
    detail = ("build: main: 'sys' is imported from `sys`, so it is a "
              "module-level name of another module. This path compiles an "
              "import into a dylib, and a module-level name is not exported "
              "as a word — there is no storage for it here")
    cls, _reason = S.classify(False, detail, source=source,
                              path=os.path.join(HERE, "t_argv.mojo"))
    check(cls == S.CLASS_CODEGEN,
          f"a `sys.argv` refusal is classified {cls!r}; with sys.mojo in the "
          f"tree it is a codegen finding, not a fact about the target")
    # And a module with NO source still classifies as the host import it is —
    # the narrowing must not reach past the case that needed it. Each name this
    # paragraph has used stopped being usable the day its module was written,
    # which is the same fact the assertion is about: `os` first, then `math` when
    # `formal/hostmods/math.mojo` landed, and `math`'s place is taken by
    # `decimal`, which is in `HOST_MODELLED` with no source anywhere in the tree.
    # A resolver that finds `math.mojo` classifies the refusal as `codegen`, so
    # using it here made this check report a `codegen` where it wanted a
    # `not-answerable/host-import`.
    host_cls, _ = S.classify(
        False, detail.replace("'sys'", "'decimal'"),
        source="import decimal\n", path=os.path.join(HERE, "t_argv.mojo"))
    check(host_cls == S.CLASS_HOST,
          f"a module with no source is classified {host_cls!r}; the "
          f"resolver-backed test must narrow only the modules that HAVE one")


TESTS = [
    ("`import sys` resolves to the module source", test_sys_resolves_to_the_module_source),
    ("every declared name is exported", test_every_declared_name_is_exported),
    ("the Python spelling runs", test_the_python_spelling_runs),
    ("the dotted spelling runs on both backends",
     test_the_dotted_spelling_runs_on_both_backends),
    ("a module can call another module", test_a_module_can_call_another_module),
    ("a string comes back as a string", test_a_string_comes_back_as_a_string),
    ("the two writers reach the right descriptors",
     test_the_two_writers_reach_the_right_descriptors),
    ("dotted calls resolve by module identity",
     test_dotted_calls_resolve_by_module_identity),
    ("a dotted call the module does not export is refused",
     test_a_dotted_call_the_module_does_not_export_is_refused),
    ("the documented spelling exits", test_the_documented_spelling_exits),
    ("string escapes are interpreted as CPython does",
     test_string_escapes_are_interpreted_as_cpython_does),
    ("a literal inside a module is decoded too",
     test_a_literal_inside_a_module_is_decoded_too),
    ("the sweep calls a sys refusal a codegen finding",
     test_the_sweep_calls_a_sys_refusal_a_codegen_finding),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    passed = failed = 0
    import shutil
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            for name, fn in TESTS:
                try:
                    fn(tmpdir, None)
                except TestFailure as e:
                    failed += 1
                    print(f"  FAIL  {name}\n        {e}")
                    continue
                except Exception as e:          # unexpected: report, do not mask
                    failed += 1
                    print(f"  ERROR {name}\n        {type(e).__name__}: {e}")
                    if args.verbose:
                        import traceback
                        traceback.print_exc()
                    continue
                passed += 1
                print(f"  PASS  {name}")
    finally:
        shutil.rmtree(_CAS_HOME, ignore_errors=True)
    print(f"\nformal sys: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
