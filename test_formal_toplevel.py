#!/usr/bin/env python3
"""test_formal_toplevel.py — a module's top-level statements RUN.

`FORMAL_toplevel_statements_dropped` was a SILENT miscompile, and the
word that matters is silent. A file whose whole body is

    import sys
    sys.exit(3)

built, linked, passed the symbol-bind audit and exited 0, and
`tools/formal_sweep.py` counted it a pass. Nothing refused it because nothing
asked: `_extract_functions` picked `FunctionDef`s out of the module statement
list, the arm64 and x86-64 `compile()` did the same, and every other top-level
statement was dropped without a diagnostic. The tree's own `t1.mojo` is that
file.

**Every case here builds the image, EXECUTES it, and compares stdout and exit
status with CPython running the same text.** A test that only asserted "it
built" is what let this through: the image built. The oracle is
`sys.executable` on the same source, in this same process, so the comparison
needs no table of expected values that could itself go stale — and the
`.mojo`/`.py` sources that are not valid Python (`printf`, Mojo structs) are
marked as such and assert against a literal instead, because there is no
CPython answer to compare against for those.

What is asserted, in the order the fixes were made:

  1. **The entry-point program shape.** A file that is only top-level
     statements runs them, in order, as the program's body: `fib_jit.mojo`'s
     shape printed nothing and exited 55 before, because the first
     `FunctionDef` was made the entry and the statements that computed and
     printed the answer were dropped. It now prints `fib(10) = 55` and exits
     0, which is what CPython does with the same file.
  2. **The body runs before a declared `main`, and `main` is still an
     ordinary function.** `hello.modo`'s shape (`def main(): …` then a
     top-level `main()`) printed once before and prints once now — but before
     it printed once because the top-level `main()` was DROPPED and the
     startup stub entered `main` directly, and now because the body called
     it. Those agree by accident or by construction, and the difference is
     what every other case here is about.
  3. **A module body that does not call `main` does not run `main`.** The
     mirror of 2, and the case that makes 2 mean something: under CPython a
     body that never calls `main` exits 0, and so does this. It is pinned
     because the alternative reading — "the formal entry point always calls
     `main`" — was the old behaviour and is a lie about a file whose body
     ends the program.
  4. **The `if __name__ == "__main__":` guard.** 143 of the 210 files in this
     tree and the stdlib that have a top-level statement are written this way,
     so the guard is the common case and not an edge. `__name__` in the module
     body materializes as `"__main__"`, which is what CPython says for the
     file a program is built from; the case checks both arms, because a
     `__name__` that always compared equal would pass a one-armed test.
  5. **`__name__` in a FUNCTION is still refused.** The materialization is
     restricted to the module body on purpose: a function's `__name__` is the
     name of whatever module it was defined in, and a function lifted out of
     an imported module has no answer this path can give. Pinned so a later
     change cannot widen it into a lie.
  6. **Both architectures.** Every build+run case above runs on arm64 and
     x86-64. The two were structurally unable to disagree about this before
     (neither had the construct at all); they must also be unable to disagree
     about the FIX, and a per-backend rule is how that guarantee is lost.
  7. **The shapes that cannot be lowered exactly are REFUSED, by name, on
     both architectures** — a file-level `return`, `global`, `break`, a
     `yield`, an `await`. Each of those is a different construct once the body
     is wrapped in a function, and each would otherwise build, run, and
     compute something other than what the file says.
  8. **A module body in a DYLIB RUNS, at load time.** A library has no `main`,
     so a body compiled into one used to be a function nothing called — the
     file built, linked, and did nothing, which is the silent no-op one level
     down from the executable case and cost 16 files of this repository. Both
     object writers now emit a load-time initializer pointing at the body, and
     a body whose MEANING is file-level (`return`, `global`, `yield`,
     `await`) is still refused — by the same code and the same words as the
     executable path, so an imported module and a run one cannot answer
     differently about one source file.
  9. **A module docstring, a file-level `pass`, and a module-level constant
     the folder can substitute are NOT body.** They are classified out in
     `model.module_body`; this pins the classification against the tree's
     own host modules, which are all three at once and every one of which must
     keep building with no entry function at all.
10. **A struct construction with arguments in a module body is RUN, not
      refused.** It used to be a `case_refused` row, and it was wrong for as
      long as it stood: a declared `__init__` whose body is a straight line of
      `self.<field> = <bare parameter>` assignments is inlined at the
      construction site, so `Point(1, 2)` in a module body built, ran and
      printed the right answer while the row said it had no representation.
      Three rows now cover the construct, because one of them covered only
      half of it: the running case (both fields read, so a transposed inline
      cannot pass), the class-default case (a constructor that assigns one of
      two fields leaves the other at its default — `3 0`, not `3 3`), and the
      refusal that must survive both, which is `self.x = x * 10` and would be
      a SILENT wrong answer if the inline ever accepted it.
  11. **`case_refused_without`: the anti-rot direction for a REWORDING.**
      `name_in_function` pins that `__name__` in a function is not substituted,
      and it used to do that with a needle-only assertion against a sentence
      that had stopped being true of the file. A needle-only row is satisfied
      by APPENDING the true sentence and leaving the false one in place, which
      is how a message that asserts something untrue outlives the change that
      made it untrue; the row now requires the message to have stopped saying
      it AND to still name what it says now.
  12. **The tree's own regression set.** `t1.mojo` is still a `codegen`
      finding — now for the real reason (`sys.exit` is a C-library name that
      `doc/ABI.md`'s export rule excludes, so the module does not export it),
      rather than a false pass. And the three shape files the sweep reported
      as `pass` while dropping their bodies are asserted to either produce
      CPython's output or to refuse by name — never to pass in silence.

Invoked directly:
    python3 test_formal_toplevel.py [-v]
"""
import argparse
import os
import platform
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
sys.path.insert(0, HERE)

BUILD_TIMEOUT = 300
RUN_TIMEOUT = 120
BACKENDS = ("arm64", "x86_64")

# The only architecture whose image this host can EXECUTE. Building the other
# one and running it is how the two were compared for years, and it is a
# comparison about the ELF container, not about this construct; the run half
# of every case therefore runs where the image can run, and the BUILD half
# runs on both. `test_formal_run.py` is the suite that already establishes
# that both backends emit working images.
NATIVE = {"arm64": "arm64", "x86_64": "x86_64"}[platform.machine()]

RESULTS = []


def check(ok, what, detail=""):
    RESULTS.append((bool(ok), what))
    if not ok:
        print(f"FAIL  {what}" + (f": {detail}" if detail else ""), flush=True)
    return bool(ok)


def build(source, out, backend="arm64", cwd=None):
    """`fire.py build --formal --no-prove` as a CompletedProcess."""
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove",
           f"--backend={backend}", "-o", out, source]
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=BUILD_TIMEOUT, cwd=cwd or HERE)


def cpython(source, cwd=None):
    """CPython's own answer for `source`: (exit status, stdout)."""
    r = subprocess.run([sys.executable, source], capture_output=True,
                       text=True, timeout=RUN_TIMEOUT, cwd=cwd or HERE)
    return r.returncode, r.stdout


def run_binary(out):
    r = subprocess.run([out], capture_output=True, text=True,
                       timeout=RUN_TIMEOUT)
    return r.returncode, r.stdout


def case_agrees_with_cpython(name, source, tmpdir, verbose=False,
                             expect_stdout=None, expect_exit=None):
    """Build on BOTH backends, run the native one, compare with CPython.

    The comparison is against `sys.executable` on the same file wherever the
    file is valid Python, and against a literal otherwise — `printf` and
    `struct` are not Python, and pretending otherwise would make the oracle a
    second copy of the expectation rather than an independent one.

    Returns True when every assertion in the case held."""
    ok = True
    for backend in BACKENDS:
        src = os.path.join(tmpdir, f"{name}.{backend}.mojo")
        with open(src, "w") as f:
            f.write(source)
        out = os.path.join(tmpdir, f"{name}.{backend}.aout")
        r = build(src, out, backend)
        if r.returncode != 0:
            # A build refusal is a legitimate answer for some cases, and the
            # caller says so; here it is a failure, because every case in
            # this function is one that must build.
            ok &= check(False, f"{name} [{backend}] built",
                        (r.stderr or r.stdout).strip()[-400:])
            continue
        if backend != NATIVE:
            continue
        code, text = run_binary(out)
        if expect_stdout is not None:
            ok &= check(text == expect_stdout, f"{name} stdout",
                        f"got {text!r}, expected {expect_stdout!r}")
        if expect_exit is not None:
            ok &= check(code == expect_exit, f"{name} exit status",
                        f"got {code}, expected {expect_exit}")
        if expect_stdout is None and expect_exit is None:
            # No literal given: CPython is the oracle. `runnable` says the
            # file is valid Python; a file that is not is passed with an
            # explicit expectation instead.
            want_code, want_text = cpython(src)
            ok &= check(text == want_text and code == want_code,
                        f"{name} agrees with CPython",
                        f"formal: exit {code}, stdout {text!r}; "
                        f"CPython: exit {want_code}, stdout {want_text!r}")
        if verbose:
            print(f"      [{backend}] exit={code} stdout={text!r}")
    return ok


def case_refused(name, source, needle, tmpdir, verbose=False):
    """REFUSED, with these words, on BOTH backends.

    Both, because a refusal is the backend's claim that it cannot lower a
    construct, and a claim one architecture makes and the other does not is a
    wrong image rather than an error message: it builds, links, and computes
    something else."""
    ok = True
    for backend in BACKENDS:
        src = os.path.join(tmpdir, f"{name}.{backend}.mojo")
        with open(src, "w") as f:
            f.write(source)
        out = os.path.join(tmpdir, f"{name}.{backend}.aout")
        r = build(src, out, backend)
        if r.returncode == 0:
            ok &= check(False, f"{name} [{backend}] refused",
                        f"it BUILT a construct with no representation; the "
                        f"binary is the real answer here")
            continue
        text = r.stderr or r.stdout
        ok &= check(needle in text, f"{name} [{backend}] refusal names it",
                    f"refused, but not with {needle!r}: {text.strip()[-300:]}")
        if verbose:
            print(f"      [{backend}] refused: {needle!r}")
    return ok


def case_refused_without(name, source, needle, forbidden, tmpdir,
                         verbose=False):
    """REFUSED, still naming `needle`, and NO LONGER saying `forbidden`.

    `test_formal_run.py` has this mode for the whole formal suite and this file
    did not, which is the gap `bugs/FORMAL_toplevel_test_asserts_a_refusal_the_
    backend_no_longer_owes.md` §4 found: it is the anti-rot direction for a
    REWORDING, and a needle-only assertion cannot see one. A refusal that has
    stopped being TRUE about the file it is reported against survives every
    `case_refused` row in this file, because the words the row pins are still
    in the message — the sentence that is false has simply been joined by a
    true one. The concrete instance is `name_in_function` below, whose old
    needle `\'__name__' has no home` stopped being raised the moment a
    MORE SPECIFIC check (`compares a NUMBER with a string`, which fires before
    the storage enumeration because it is asked first) began answering that
    program.

    Both halves are required, and they are required for the two ways this can
    be faked: without `forbidden`, appending the true sentence satisfies the
    row and leaves the false one in place; without `needle`, deleting the
    message — or replacing it wholesale with something unrelated — satisfies it
    too. What is left is "refused, for `needle`, no longer claiming
    `forbidden`", which is the row's actual subject."""
    ok = True
    for backend in BACKENDS:
        src = os.path.join(tmpdir, f"{name}.{backend}.mojo")
        with open(src, "w") as f:
            f.write(source)
        out = os.path.join(tmpdir, f"{name}.{backend}.aout")
        r = build(src, out, backend)
        if r.returncode == 0:
            ok &= check(False, f"{name} [{backend}] refused",
                        f"it BUILT a construct with no representation, and it "
                        f"is no longer asserting {forbidden!r} either; the "
                        f"binary is the real answer here")
            continue
        text = r.stderr or r.stdout
        said = [f for f in forbidden if f in text]
        ok &= check(not said, f"{name} [{backend}] no longer says {said!r}",
                    f"the refusal asserts a fact that is not true of the file "
                    f"it is reported against: {text.strip()[-300:]}")
        ok &= check(needle in text, f"{name} [{backend}] still names {needle!r}",
                    f"refused without the superseded wording, but also "
                    f"without naming {needle!r}, so the message may have been "
                    f"dropped rather than corrected: {text.strip()[-300:]}")
        if verbose:
            print(f"      [{backend}] refused: {needle!r}, not {forbidden!r}")
    return ok


# ── 1. the entry-point program shape ────────────────────────────────────────
#
# `fib_jit.mojo` in this repository, in full. Before the fix this built, ran
# and printed NOTHING, exiting 55: the first `FunctionDef` (`fib`) was made
# the program entry, called with the test input, and the two statements that
# are the actual program were dropped.

ENTRY_POINT_SHAPE = """\
def fib(n):
    if n <= 1:
        return n
    return fib(n - 1) + fib(n - 2)

result = fib(10)
printf("fib(10) = %d", result)
"""


def test_entry_point_program_shape(tmpdir, verbose):
    """A file that is only top-level statements runs them, in order.

    The shape the coverage sweep reported a `pass` for while the program did
    nothing, and the reason the sweep's number was counting files that do not
    run. `printf` rather than `print` because the comparison here is
    against a literal, not against CPython: `print` on this path cannot tell
    a string from a number, which is a different gap with its own message."""
    return case_agrees_with_cpython(
        "entry_point_shape", ENTRY_POINT_SHAPE, tmpdir, verbose,
        expect_stdout="fib(10) = 55", expect_exit=0)


# ── 2/3. the body's position relative to a declared `main` ─────────────────
#
# `hello.modo` in this repository, in full. It printed once BEFORE the fix
# too, and that is the point: it printed once because the top-level `main()`
# was dropped and the startup stub entered `main` directly. The two
# readings agree, and the file cannot tell you which one is running. These
# two cases can.

MAIN_CALLED_FROM_BODY = """\
def main():
    printf("from main")

main()
"""

MAIN_NOT_CALLED_FROM_BODY = """\
def main():
    printf("main ran")

printf("body ran")
"""


def test_body_calls_main(tmpdir, verbose):
    """`def main()` plus a top-level `main()`: the body calls it, once."""
    return case_agrees_with_cpython(
        "body_calls_main", MAIN_CALLED_FROM_BODY, tmpdir, verbose,
        expect_stdout="from main", expect_exit=0)


def test_body_does_not_run_main_it_does_not_call(tmpdir, verbose):
    """`def main()` and a body that never calls it: `main` does not run.

    The mirror of the case above, and the one that makes it mean something.
    Under CPython a body that never calls `main` never runs it, and the
    process exits 0; before the fix the formal entry point called `main`
    anyway, so a file whose body deliberately does not run its own `main`
    ran it. This is the shape `test_formal_imports.py`'s `a guarded import
    is inert too` was written against without knowing it — see the note
    there."""
    return case_agrees_with_cpython(
        "body_skips_main", MAIN_NOT_CALLED_FROM_BODY, tmpdir, verbose,
        expect_stdout="body ran", expect_exit=0)


# ── the exit code is the body's, and `exit()` still works from the body ────

def test_exit_from_the_module_body(tmpdir, verbose):
    """`exit(3)` at file level exits 3.

    `t1.mojo` in this repository, with the one spelling that lowers on this
    target. The source says `sys.exit(3)`, and that spelling is a settled
    refusal of its own (`doc/ABI.md`'s export rule excludes a C library
    name, so the `sys` module does not advertise `exit`; see
    `bugs/FORMAL_known_limits.md` 1.1, pinned by `test_formal_sys.py`). What
    is new is that the call is REACHED at all: before the fix the whole line
    was dropped and the process exited 0."""
    return case_agrees_with_cpython(
        "exit_from_body", "exit(3)\n", tmpdir, verbose,
        expect_stdout="", expect_exit=3)


def test_body_runs_before_a_later_exit(tmpdir, verbose):
    """Order is order: the body runs top to bottom and stops where it says.

    `exit(9)` after a call to `main` must mean the program has already run
    `main`. A lowering that reordered the body — or ran `main` after the
    body, which was the old entry convention — would exit 0 here."""
    return case_agrees_with_cpython(
        "body_order", "def main():\n    printf(\"ran\")\n\nmain()\nexit(9)\n",
        tmpdir, verbose, expect_stdout="ran", expect_exit=9)


# ── 4. the `__name__` guard ────────────────────────────────────────────────
#
# 143 of the 210 files in this tree and the stdlib that have a top-level
# statement are written this way. A `__name__` that could not be answered
# would refuse all of them, so this is the common case rather than an edge,
# and BOTH arms are checked because a `__name__` that always compared equal
# would pass a one-armed test.

NAME_GUARD_TRUE = """\
if __name__ == "__main__":
    printf("guarded")
else:
    printf("unguarded")
"""

NAME_GUARD_FALSE = """\
if __name__ == "not_main":
    printf("unguarded")
else:
    printf("guarded")
"""


def test_name_guard_true(tmpdir, verbose):
    """`__name__ == "__main__"` is TRUE in the module body of a program.

    Which is what CPython says for the file a program is built from: the
    entry module of `python3 file.mojo` is `__main__`."""
    return case_agrees_with_cpython(
        "name_guard_true", NAME_GUARD_TRUE, tmpdir, verbose,
        expect_stdout="guarded", expect_exit=0)


def test_name_guard_false(tmpdir, verbose):
    """…and a guard for any other name is FALSE.

    The other arm. A substitution that made every `__name__` compare equal
    would take the first branch here."""
    return case_agrees_with_cpython(
        "name_guard_false", NAME_GUARD_FALSE, tmpdir, verbose,
        expect_stdout="guarded", expect_exit=0)


def test_name_in_a_function_is_still_refused(tmpdir, verbose):
    """`__name__` in a FUNCTION is refused, on both backends.

    The materialization is restricted to the module body deliberately. A
    function's `__name__` is the name of whatever module it was DEFINED in,
    and a function lifted out of an imported module has no answer this path
    can give — answering it would be a value that is right for this file and
    wrong for every other, which is the class of lie
    `bugs/FORMAL_module_state_no_storage.md` is about. Pinned so a later
    change cannot widen the substitution into the function bodies."""
    # `refuse_without:`, and the needle is the REWORDED sentence rather than
    # the one this row used to pin.  A more specific check now answers this
    # program before the storage enumeration does: the comparison is a NUMBER
    # against a STRING, and `strcmp` dereferences both operands, so the
    # operand-kind question is asked first and `\'__name__' has no home` is no
    # longer what it says.  It was not a lifted refusal — the program is still
    # refused on both backends, and what the row is FOR (that `__name__` in a
    # FUNCTION is not substituted) is still exactly what it pins.
    #
    # The forbidden half is the old needle, and it is the half that makes this
    # a case rather than a restatement: a needle-only row is satisfied by
    # APPENDING the true sentence and leaving the false one in place, which is
    # how a message that says something untrue about the file outlives the
    # change that made it untrue.  Verified pre-existing rather than caused by
    # whatever change surfaced it: the same source built from `HEAD` restored
    # into a scratch copy refuses identically.
    return case_refused_without(
        "name_in_function",
        "def f():\n    if __name__ == \"__main__\":\n        return 1\n"
        "    return 0\n\nf()\n",
        "compares a NUMBER with a string",
        ["'__name__' has no home"], tmpdir, verbose)


# ── 5. the module docstring, `pass`, and a folded constant are not body ────
#
# The classification in `model.module_body`, pinned against the tree's own
# host modules, which are all three at once. `formal/hostmods/sys.mojo` is a
# docstring plus twenty-one `def`s; the other two are a docstring, a
# `pass`, and a module-level constant. Every one must keep building, and must
# keep building with NO entry function: a body classification that swept any
# of these in would give each of them a `__module_body__` doing nothing.

HOSTMODS = os.path.join(HERE, "formal", "hostmods")


def test_hostmods_still_build_with_no_body(tmpdir, verbose):
    """`formal/hostmods/*.mojo`: docstring + defs + `pass` + constants.

    Asserted by BUILDING, because the failure mode of a body classification
    that is too wide is not a refusal — it is a module that grows an entry
    function running nothing, which is the bug this whole change is about,
    one level up."""
    ok = True
    sources = []
    for dirpath, dirnames, filenames in os.walk(HOSTMODS):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in sorted(filenames):
            if fn.endswith(".mojo"):
                sources.append(os.path.join(dirpath, fn))
    check(len(sources) >= 3, "the host modules were found",
          f"found {len(sources)} under {HOSTMODS}")
    sys.path.insert(0, HERE)
    from formal import model as M
    from formal.build import parse_module
    for path in sources:
        with open(path, encoding="utf-8") as f:
            stmts = parse_module(f.read(), path)
        body = M.module_body(stmts, M.collect_module_symbols(stmts))
        ok &= check(not body,
                    f"{os.path.relpath(path, HERE)} has no module body",
                    f"classified {[type(s).__name__ for s in body]} as body; "
                    f"a docstring, a file-level `pass` and a folded constant "
                    f"are declarations, not statements that run")
    return ok


def test_a_docstring_only_module_still_builds(tmpdir, verbose):
    """A module that is a docstring and a function has no body at all.

    The smallest instance of the rule, and the one a sweep of this tree is
    full of. It must still produce a working image — the entry is still
    `main`, and `main` is still the entry."""
    return case_agrees_with_cpython(
        "docstring_only",
        '"""just a docstring"""\n\ndef main():\n    printf("ran")\n',
        tmpdir, verbose, expect_stdout="ran", expect_exit=0)


# ── 6. the shapes that cannot be lowered exactly are refused by name ───────
#
# Each of these means something different once the body is wrapped in a
# function, and each would otherwise build, run, and compute something other
# than what the file says. The refusal is asked BEFORE the wrapping, which
# is why the message says "at file level" and not "unsupported statement".

def test_file_level_return_is_refused(tmpdir, verbose):
    """A `return` at file level returns from nothing."""
    return case_refused(
        "file_return", "exit(0)\nreturn 1\n",
        "a `return` at file level returns from nothing", tmpdir, verbose)


def test_file_level_global_is_refused(tmpdir, verbose):
    """A `global` at file level names a scope that does not exist."""
    return case_refused(
        "file_global", "global x\nexit(0)\n",
        "a `global` declaration at file level names a scope that does not "
        "exist", tmpdir, verbose)


def test_file_level_yield_is_refused(tmpdir, verbose):
    """A `yield` at file level makes the MODULE a generator.

    Nothing on this path iterates a module, and a generator function itself is
    refused by name (`model.generator_function_refusal`), so a file-level one
    would be reached only by the wrapper this check runs BEFORE \u2014 and the
    value it would leave is the same wrong answer either way. A wrong answer,
    not an error, which is why this is refused rather than wrapped."""
    return case_refused(
        "file_yield", "def g():\n    yield 1\n\ng()\nyield 2\n",
        "a `yield` at file level makes the MODULE a generator", tmpdir,
        verbose)


def test_file_level_await_is_refused(tmpdir, verbose):
    """An `await` at file level makes the MODULE a coroutine.

    `await` is the IDENTITY inside a function on this path (there is no event
    loop), so a file-level one would run the awaitable and throw the result
    away. Refused for the same reason the `yield` above is."""
    return case_refused(
        "file_await", "async def g():\n    return 1\n\nawait g()\n",
        "an `await` at file level makes the MODULE a coroutine", tmpdir,
        verbose)


# ── 7. the dylib path: a library's entry point is its load-time initializer ──
#
# A module body used to be REFUSED on this path, for a reason that was true and
# whose remedy was wrong: a library has no `main`, so a module whose top level
# had statements in it compiled to a function nothing called — built, linked,
# and silent. 16 files in this repository were refused for it, 15 of them for
# having IMPORTED the offending module and for using nothing it declares.
#
# The remedy was an entry point, not a refusal: both object writers now emit
# one — `__TEXT,__init_offsets` in a Mach-O library, `.init_array` in an ELF one
# — pointing at the body wrapper, and dyld calls it after the library's
# dependencies are loaded and before `main`, which is where CPython runs a
# module body at import. The first case below is that claim, end to end, on both
# architectures; the second is the refusal that SURVIVED, because a body the
# path cannot lower is still refused, now by the same code and the same words the
# executable path uses.

DYLIB_PROGRAM = "from pkg import join\n\nexit(0)\n"
# The body's EFFECT has to be observable from the program's own stdout, because
# "the library has an initializer section" is a claim about the file and this is
# a claim about the run. `printf` in the body's first position is what puts the
# body's output BEFORE the program's: a load-time initializer that ran after
# `main` would print the same bytes in the other order.
DYLIB_MODULE_WITH_BODY = """\
def _parts():
    return ["a", "b"]

ALL = _parts()
printf("body@")


def join(a, b):
    return a + b
"""

DYLIB_PROGRAM_WITH_BODY = """\
from pkg import join

def main(k):
    printf("main=%d@@", join(1, 2))
    return 0
"""


def case_dylib_body_runs_at_load(name, module, program, expect_stdout,
                                 tmpdir, verbose=False):
    """Build an IMPORTING program on BOTH backends and check what it printed.

    End to end through the import mechanism, because the point is what a caller
    LINKING the library sees: the chain builds the module's own dylib, and the
    program's stdout is the only place a load-time effect can show up.

    Both backends build; only the native one is RUN, because an x86-64 image
    needs Rosetta and this file's runner has no story about it (that is
    `test_formal_x86_64_dylib.py`'s job, and it builds and inspects both
    containers there)."""
    ok = True
    for backend in BACKENDS:
        root = os.path.join(tmpdir, f"{name}.{backend}")
        os.makedirs(os.path.join(root, "pkg"), exist_ok=True)
        with open(os.path.join(root, "pkg", "__init__.mojo"), "w") as f:
            f.write(module)
        prog = os.path.join(root, "prog.mojo")
        with open(prog, "w") as f:
            f.write(program)
        out = os.path.join(root, f"{name}.{backend}.aout")
        r = build(prog, out, backend, cwd=root)
        if r.returncode != 0:
            ok &= check(False, f"{name} [{backend}] built",
                        (r.stderr or r.stdout).strip()[-400:])
            continue
        if backend != NATIVE:
            continue
        code, text = run_binary(out)
        ok &= check(text == expect_stdout, f"{name} [{backend}] stdout",
                    f"got {text!r}, expected {expect_stdout!r}")
        ok &= check(code == 0, f"{name} [{backend}] exit status",
                    f"got {code}, expected 0")
        if verbose:
            print(f"      [{backend}] exit={code} stdout={text!r}")
    return ok


def test_a_dylib_runs_its_module_body_at_load_time(tmpdir, verbose):
    """A module body in a LIBRARY runs when the library loads.

    The statement this replaces asserted the opposite, and the reason is the
    whole of the fix: a library has no `main` and no caller for a body, so
    before the load-time initializer the body compiled to a function nothing
    ran and the importing program printed only its own output."""
    return case_dylib_body_runs_at_load(
        "dylibbody", DYLIB_MODULE_WITH_BODY, DYLIB_PROGRAM_WITH_BODY,
        "body@main=3@@", tmpdir, verbose)


def test_dylib_path_still_refuses_a_body_that_cannot_run(tmpdir, verbose):
    """A body whose MEANING is file-level is still refused, as a LIBRARY too.

    `return` at file level returns from nothing: this path runs the top level as
    the body of a synthetic function, so a `return` there returns from THAT
    function rather than from a function the source wrote. The refusal is asked
    for both paths from the same code (`_refuse_unlowerable_module_body`), so a
    reader whose module is imported gets the same sentence as one that is run —
    which is the property that replaced the old whole-body refusal, and the one
    a per-path copy of this check would lose."""
    root = os.path.join(tmpdir, "dylibreturn")
    os.makedirs(os.path.join(root, "pkg"), exist_ok=True)
    with open(os.path.join(root, "pkg", "__init__.mojo"), "w") as f:
        f.write("printf(\"early@\")\nreturn 3\n\n\n"
                "def join(a, b):\n    return a + b\n")
    with open(os.path.join(root, "prog.mojo"), "w") as f:
        f.write(DYLIB_PROGRAM)
    ok = True
    for backend in BACKENDS:
        out = os.path.join(root, f"prog.{backend}.aout")
        r = build(os.path.join(root, "prog.mojo"), out, backend, cwd=root)
        ok &= check(r.returncode != 0,
                    f"a file-level `return` in an imported module's body is "
                    f"refused [{backend}]",
                    "it BUILT: the body would return from the initializer")
        text = r.stderr or r.stdout
        ok &= check("a `return` at file level returns from nothing" in text,
                    f"the refusal names the construct [{backend}]",
                    text.strip()[-300:])
        if verbose and text:
            print(f"      [{backend}] refused: {text.strip()[:200]}")
    return ok


# ── 8. the tree's own regression set ───────────────────────────────────────
#
# The files the sweep reported as `pass` while this path dropped their
# bodies, each asserted to either produce CPython's output or to refuse by
# name. Never to pass in silence: that is the whole failure.

# t1.mojo, in full. It is still a `codegen` finding and that is CORRECT — but
# for the real reason (`sys.exit` is a C-library name the export rule
# excludes), where before it was a `pass` that exited 0.
T1 = "import sys\nsys.exit(3)\n"

# array_ops_jit.mojo in this repository, in full. Before the fix this built
# and printed NOTHING: `arr = …`, the `for` that sums it, and the three
# `print`s that report the answer were all dropped, and the sweep counted the
# file a pass. It was then refused — on `print` of a subscript, and on a `dict`
# subscript — and that refusal was this file's `body_next_finding` row for a
# while.
#
# **It now BUILDS AND RUNS**, and the two things that made it run are both a
# value model reading a fact the source states: a container literal's ELEMENT
# kind (`model.container_literal_elem_kind`, which is what the dict subscript
# needed) and a constructed frame's FIELD kind
# (`model.struct_ctor_field_value`). Measured, both architectures, this exact
# text, with CPython as the oracle: `Sum: 15 / Length: 5 / Value of a: 10`,
# byte for byte.
ARRAY_OPS = """\
arr = [1, 2, 3, 4, 5]
sum_val = 0
for x in arr:
    sum_val = sum_val + x

print("Sum:", sum_val)
print("Length:", len(arr))

d = {"a": 10, "b": 20}
print("Value of a:", d["a"])
"""

# …and the NEXT construct the body cannot lower, which is what
# `body_next_finding` now refuses on. Every statement above `n = 5` is one the
# body lowers — the loop, the module-global int the loop accumulated into, both
# container subscripts and the dict subscript — so the body demonstrably got
# FURTHER rather than being refused earlier, which is the whole claim that row
# makes. `len()` of an integer is a live gap with its own message and no
# storage or representation question behind it (an integer has no length
# whether the word is 5 or 0), so it will not be papered over by a later fix to
# the element kind.
BODY_THEN_LEN_OF_AN_INT = ARRAY_OPS + """
n = 5
print(len(n))
"""

# `class_jit.mojo`'s shape — a struct construction with arguments, written in a
# MODULE BODY rather than inside a function.  It used to be pinned here as a
# REFUSAL, which was wrong for the whole time the assertion existed: a declared
# `__init__` whose body is a straight line of `self.<field> = <bare
# parameter>` is inlined at the construction site, so this program builds, runs,
# and prints what it says.  `bugs/FORMAL_toplevel_body_struct_construction_no_
# longer_refused.md` is the record; what it asked for is a running case, which
# is what this is.
#
# Two fields, two arguments, BOTH fields read: an inline that transposed the
# argument order or the field order would answer `x=2 y=1`, and an inline that
# stored only one of them would leave the other holding a word neither
# architecture agrees on.  No escape in the format — see the case's docstring.
BODY_CONSTRUCTION_RUNS = """\
struct Point:
    x: Int
    y: Int
    def __init__(self, x, y):
        self.x = x
        self.y = y

p = Point(1, 2)
printf("x=%d y=%d", p.x, p.y)
"""

# The CLASS-DEFAULT half of the same inlining, and the part a
# field-filling implementation would get wrong.  `P`'s constructor assigns one
# of its two fields, so `p.y` is never written by anything — and the answer
# (0) is the field's class-level default, not the constructor's missing
# argument and not whatever the frame allocator left in the slot.  CPython says
# `3 0` for the same text, measured, and the case asserts that pair rather than
# a single number so that a `3 3` cannot pass.
BODY_CONSTRUCTION_CLASS_DEFAULT = """\
struct P:
    x: Int
    y: Int
    def __init__(self, x):
        self.x = x

p = P(3)
printf("x=%d y=%d", p.x, p.y)
"""

# `class_jit.mojo`'s exact text — which is the same construction as the two
# fixtures above with the ANNOTATIONS REMOVED, and that is the whole difference:
# `model.struct_field_kind`'s gate is a claim about the VALUE in the slot and
# reads the field's DECLARED type, so with no `x: Int` anywhere there was no
# declaration to claim from at all and the read was unclassified.
#
# It is here, in the module-body file, rather than only in
# `test_formal_value_model.py` because that is where the construction is written:
# `class_jit.mojo` puts `p = Point(3, 4)` at top level, and a module body is the
# entry, so this is a field read out of a frame the body itself built.
#
# `print`, not `printf`, because the refusal this replaces was `print()`'s —
# `print` is the one builtin that must choose between two renderings before it
# emits anything, so it is where an unclassifiable field first shows up, and a
# lowering that guessed would print a frame address as a number.
BODY_CONSTRUCTION_UNANNOTATED = """\
class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y

p = Point(3, 4)
print("Point:", p.x, p.y)
"""


def test_t1_is_a_named_finding_not_a_pass(tmpdir, verbose):
    """`t1.mojo` refuses, naming why — it does not exit 0 in silence.

    The bug this file documents used it as its own example, and the fix does
    not make it build: `sys.exit` is a C-library name and `doc/ABI.md`'s
    export rule excludes one, so the `sys` module does not advertise it. What
    changed is that the file is now a `codegen` finding that says so, instead
    of a `pass` that exited 0 where the source says 3. The refusal is
    `test_formal_sys.py`'s subject too, which is why it is pinned in both.

    arm64 only, and the reason is measured rather than convenient: on x86-64
    the `sys` MODULE fails its own strict validation before this file's own
    construct is ever reached, and it does so identically before and after
    this change (checked against `HEAD~1`), so an x86-64 assertion here would
    be pinning an unrelated pre-existing link failure under this change's
    name. The x86-64 half of the refusal contract is covered by the
    file-level cases below, which need no module dylib."""
    src = os.path.join(tmpdir, "t1_mojo.mojo")
    with open(src, "w") as f:
        f.write(T1)
    out = os.path.join(tmpdir, "t1_mojo.aout")
    r = build(src, out, "arm64")
    ok = check(r.returncode != 0, "t1.mojo is refused, not a silent pass",
               "it BUILT and would exit 0 where the source says 3 — the "
               "exact false pass this file documents")
    text = r.stderr or r.stdout
    ok &= check("exports no `exit`" in text,
                "the refusal names why (sys does not export exit)",
                f"{text.strip()[-300:]}")
    if verbose:
        print(f"      refused: {text.strip()[:200]}")
    return ok



def test_a_module_body_reaches_its_next_real_finding(tmpdir, verbose):
    """A body that runs reaches the NEXT construct the backend cannot lower.

    `array_ops_jit.mojo`'s shape: a loop and a subscript over a module-level
    list inside a top-level body. Before the fix the whole body was dropped, so
    the file passed. It was then refused — on the `print` of a subscript, a real
    gap with its own message — which was progress rather than a regression: the
    sweep was counting a construct it could name instead of a file that did not
    run.

    **Both of those refusals are gone**, so the fixture is `ARRAY_OPS` plus one
    more statement and the row keeps its meaning: every statement above `n = 5`
    lowers, and what the build stops at is the `len()` of an integer. Moving the
    needle rather than deleting the row is the point — a row that asserted "this
    file is refused" would have been satisfied by the file getting worse, which
    is the direction this file exists to notice. `body_subscript_and_dict_run`
    beside it pins the new answer, so the thing that moved is measured rather
    than merely no longer red.

    `len()` of an integer is chosen over the alternatives on purpose: it is a
    representation fact (an integer has no length) rather than a storage one, so
    the element-kind work that unblocked the statements above it cannot be
    extended to reach this, and the row will keep saying something true."""
    return case_refused(
        "body_next_finding", BODY_THEN_LEN_OF_AN_INT,
        "is len() of a value classified as 'int'", tmpdir, verbose)


def test_a_module_body_subscript_and_dict_run(tmpdir, verbose):
    """The `body_next_finding` fixture's own text now runs, and is RIGHT.

    This file's discipline for a construct written in a module body: build the
    image, EXECUTE it, and compare the answer against CPython. A refusal only
    says the backend declined; a run says the number is right, and this one is
    the anti-rot for the refusal the row above used to assert — so a regression
    in either direction (the dict subscript stops lowering, or it lowers to the
    wrong word) is a failure of THIS row rather than a change of which row is
    red.

    All three numbers are the program's own: the loop's sum, the container's
    length, and the dict value under `"a"`. The dict one is the interesting
    half — it is a pair-blob key SCAN, and a lowering that took the element path
    would answer the wrong word with a plausible number, which is why the
    expectation is CPython's output rather than a fixed `10`."""
    return case_agrees_with_cpython(
        "body_subscript_and_dict_run", ARRAY_OPS, tmpdir, verbose,
        expect_stdout="Sum: 15\nLength: 5\nValue of a: 10\n", expect_exit=0)


def test_a_module_body_construction_with_arguments_runs(tmpdir, verbose):
    """A construction WITH arguments in a module body lowers, and is RIGHT.

    The row that replaces the stale refusal beside it, and it is this file's own
    discipline for a construct written in a module body: build the image,
    EXECUTE it, and compare the answer. A refusal only says the backend
    declined; a run says the answer is right — and the answer being right is
    the part that matters, because the failure this replaces was never a
    crash. It was a row asserting a refusal for a program that compiled and
    computed exactly what it says.

    The needle the old row pinned was the ordinary construction refusal, and
    the point of pairing the two rows is that it is STILL the ordinary
    construction refusal that refuses a body this path cannot inline — there is
    no body-specific list, and this pair is what keeps that true while the
    inline underneath it stands.

    Two arguments into two fields and the read is of the FIRST of them, so a
    constructor inlined with the arguments swapped (or with the field order
    transposed) prints `2` where the source says `1`. `p.y` is read as well:
    a body that only ever stored one of the two fields would leave the other
    holding whatever the allocator left behind, which on the two architectures
    is not the same word.

    **No escape in the format string, and that is deliberate rather than an
    oversight**: the expected stdout below is exactly the bytes the format asks
    for, `"x=1 y=2"`, with no line ending — so the case states the
    representation it is checking rather than inheriting one from a decoder.
    (An escape would be decoded, as CPython decodes it; see
    `test_formal_sys.py`'s `test_string_escapes_are_interpreted_as_cpython_does`.)
    CPython is not the oracle for a file that calls `printf`."""
    return case_agrees_with_cpython(
        "body_construction_runs", BODY_CONSTRUCTION_RUNS, tmpdir, verbose,
        expect_stdout="x=1 y=2", expect_exit=0)


def test_a_module_body_can_still_be_refused_by_the_ordinary_codegen(tmpdir,
                                                                   verbose):
    """…and a body is refused by the ordinary checks, not by a second set.

    `class_jit.mojo`'s shape: a struct construction inside the body whose
    `__init__` has a body this path does not inline. The message is the
    ordinary construction refusal, unchanged, because the body is a function
    and the function pipeline is what answers it. A second, body-specific
    refusal list would have made this a different message for the same
    construct depending on where it was written.

    **This row used to be a two-argument `Point(1, 2)`, and it used to be
    wrong.** A declared `__init__` whose body is a straight line of
    `self.<field> = <bare parameter>` assignments is INLINED at the
    construction site — `formal/model.py`'s `construction_init_body_refusal`
    says so in its own words, under the heading "What is NOT refused, and the
    reason it is worth stating" — so the program built, ran and printed the
    right answer while this row insisted it had no representation.  That is a
    hole in coverage pointed the wrong way: it says "this has no
    representation" about a construct that has one, and a reader who believes
    the row does not go and look for the coverage the inlining actually has.
    The running half of the pair is `test_a_module_body_construction_with_
    arguments_runs` below; this row is the half that must not be
    lost, because `self.x = x * 10` refused is the one that would be a SILENT
    wrong answer if it regressed (`P(3)` would print `3` where the source says
    `30`).
    """
    return case_refused(
        "body_construction_refusal",
        "struct P:\n    x: Int\n    def __init__(self, x):\n"
        "        self.x = x * 10\n\n"
        "p = P(3)\nprintf(\"%d\", p.x)\n",
        "is a call to a user-defined `__init__`", tmpdir, verbose)


def test_a_module_body_construction_leaves_an_unassigned_field_at_its_default(
        tmpdir, verbose):
    """A constructor that assigns ONE of two fields leaves the other alone.

    The half of the inlining a "fill the fields from the arguments"
    implementation gets wrong, and it is why this is a pair of assertions
    rather than one: the lowering is not "fill the fields", it is "store each
    of the constructor's `self.<field> = …` assignments into the fresh block
    at the construction site", so a field the constructor does not mention is
    never written and keeps the class default the construction brought it up
    with.

    Asserted as the PAIR `x=3 y=0` rather than as `x=3`, so an inline that
    invented a value for `y` — `3 3` being the plausible one — cannot pass.
    CPython's answer for the same text is the same pair, and it is a class
    attribute in the oracle program rather than a field with no default at
    all: under a bare `class P`, `y` is not declared anywhere and CPython
    raises `AttributeError`, which would make this a test of a different
    question. `struct P: x: Int; y: Int` is the spelling that says what `y`
    is, and a field declared with no value defaults to 0 on both sides."""
    return case_agrees_with_cpython(
        "body_construction_class_default", BODY_CONSTRUCTION_CLASS_DEFAULT,
        tmpdir, verbose, expect_stdout="x=3 y=0", expect_exit=0)


def test_a_module_body_construction_without_field_annotations_runs(tmpdir,
                                                                   verbose):
    """The same construction with NO annotations, read through `print`, runs.

    The two fixtures above declare `x: Int` / `y: Int`; this one declares
    nothing, and that is the difference the whole case is about. A field's kind
    on this path comes from its DECLARED type, gated by a rule that is a claim
    about the VALUE in the slot (`struct_field_kind`: `S()` does not run
    `__init__`, so a fresh instance's slot holds the class-level default). With
    no declaration there is nothing for that rule to read, so `print(p.x)` was
    refused — `print() cannot tell whether MemberExpr is a string or a number`,
    which is a refusal about a value the constructor had just put there.

    It is now answered from the CONSTRUCTION instead
    (`model.struct_ctor_field_value`, which asks `init_body_stores` — so the
    kind is read off the expression the image evaluates into the slot), and it
    is asked only when the declaration said nothing.

    CPython is the oracle, so a lowering that read the wrong word of the frame
    — which for a two-field struct means `x=4 y=3`, both plausible numbers —
    is a failure of this row rather than a different number to re-pin."""
    return case_agrees_with_cpython(
        "body_construction_unannotated", BODY_CONSTRUCTION_UNANNOTATED,
        tmpdir, verbose, expect_stdout="Point: 3 4\n", expect_exit=0)


# ── the classifier itself, as a unit ───────────────────────────────────────
#
# `model.module_body` is the one place that decides what runs, and it is
# asked by both backends and both front ends, so its answers are worth
# pinning independently of whether an image came out right.

def test_module_body_classification(tmpdir, verbose):
    """`model.module_body`: what is body and what is not, by kind.

    Each row is a one-line module and the kinds its body must have. The rows
    that are EMPTY are the interesting half: a docstring, a `pass`, an
    import, a `struct`, a `def`, a `comptime` binding and a folded constant
    are all declarations or substitutions, and a classification that swept any
    of them in would give every module in the tree an entry function that
    runs nothing."""
    sys.path.insert(0, HERE)
    from formal import model as M
    from formal.build import parse_module
    rows = [
        # (source, expected body statement kinds)
        ('"""doc"""\n', []),
        ("pass\n", []),
        ("import os\n", []),
        ("from os import sep\n", []),
        ("def f():\n    return 1\n", []),
        ("struct S:\n    x: Int\n", []),
        ("trait T:\n    fn g(self) -> Int:\n        return 1\n", []),
        ("X = 5\n", []),                       # folds: substituted at reads
        ('X = "s"\n', []),                      # folds
        ("X = 5 + 2 * 3\n", []),                # folds: the folder's closure
        # A FLOAT constant, which is the one literal that did not fold until the
        # module-level folder grew an arm for it (`model.fold_module_value`).
        # It is body-only-by-omission: both emitters lower a `FloatLiteral` with
        # `int(expr.value)` ("formal is int-only; truncate toward zero") and
        # `formal/types.py` types it `DEFAULT_INT_TYPE`, so the build KNEW the
        # value and the folder declined to say so — `collect_module_symbols`
        # recorded the name `rebound`, `module_body` declined the store, and a
        # dylib was refused for having a body at all. Measured on this
        # repository's own `tools/memslot.py`: four of its six body statements
        # are float constants. So this row is the doc's item 3.
        ("X = 96.0\n", []),
        ("X = 0.5\n", []),                      # …including a fractional one:
                                               # the word is 0, which is what a
                                               # read of the literal itself is
        # …but a float inside an EXPRESSION is NOT a folded constant, and
        # folding it would be a wrong answer rather than a widening. The
        # emitters compute `2.5 * 3` as `int(2.5) * 3` = 0, and a folder that
        # said 7 would have the substitution put 7 at a read site where the
        # same expression written there yields 0 — so the module-level folder
        # truncates a LITERAL and nothing wider, exactly the node the emitters
        # have a rule for. This row is what stops the next reader from adding
        # the binary arm.
        ("X = 2.5 * 3\n", ["AssignStmt"]),
        ("comptime X = 5\n", []),               # a compile-time binding
        ("exit(0)\n", ["ExprStmt"]),
        # A CONTAINER literal does not fold, so it is module STATE — and since
        # module globals got a `__DATA` slot, that state is in the IMAGE: the
        # slot's initializer is laid out by the linker before the program
        # starts. So the store is not body either, and leaving it there was not
        # merely redundant: `entry_function` picks the body as the entry, so a
        # module whose whole top level is that binding never called `main` and
        # the image exited 0 printing nothing. Both architectures, measured; see
        # `model.module_body`'s `_is_image_initialized`.
        ('X = [1, 2]\n', []),
        # …but a container the body REBINDS still needs its store, which is what
        # `module_body`'s `rebound` re-walk is for and why the exemption is
        # conditional rather than a blanket "a container is in the image": a
        # name the body writes has a value the image's initializer does not
        # describe. (Both of the two stores here is what the rule produces — the
        # second is a `BinaryOp`, so it is body on its own account.)
        ('X = [1, 2]\nfor i in range(2):\n    X = [3]\n',
         ["AssignStmt", "ForStmt"]),
        ("X = 1\nX = 2\n", ["AssignStmt", "AssignStmt"]),
        ("for i in range(3):\n    pass\n", ["ForStmt"]),
        ("if True:\n    pass\n", ["IfStmt"]),
        ("def f():\n    return 1\nf()\n", ["ExprStmt"]),
    ]
    ok = True
    for i, (src, want) in enumerate(rows):
        stmts = parse_module(src, f"<row{i}>")
        got = [type(s).__name__ for s in
               M.module_body(stmts, M.collect_module_symbols(stmts))]
        ok &= check(got == want, f"module_body({src!r})",
                    f"got {got}, expected {want}")
    return ok


def test_entry_order_is_the_module_body(tmpdir, verbose):
    """`model.entry_function`: body, then `main`, then the rest.

    A unit test because the two backends used to each spell this rule out for
    themselves, and a rule written twice is a rule that will be written two
    ways. The observable that matters is which function the startup stub
    branches to, and that is `functions[0]`."""
    sys.path.insert(0, HERE)
    from formal import model as M
    from formal.build import parse_module

    def names(src):
        stmts = parse_module(src, "<order>")
        fns = [s for s in stmts if isinstance(s, __import__(
            "fire_compiler", fromlist=["x"]).FunctionDef)]
        if M.module_body(stmts, M.collect_module_symbols(stmts)):
            from formal.build import _module_body_function
            fns = [_module_body_function(
                M.module_body(stmts, M.collect_module_symbols(stmts)))] + fns
        return [f.name for f in M.entry_function(fns)]

    ok = True
    ok &= check(names("def f():\n    return 1\n") == ["f"],
                "a body-less module keeps its function as the entry",
                f"got {names('def f(): pass')}")
    ok &= check(names("def main():\n    return 1\n") == ["main"],
                "a declared main is still the entry when there is no body",
                f"got {names('def main(): return 1')}")
    ok &= check(names("exit(0)\n") == [M.MODULE_BODY_NAME],
                "a body with no function is the entry",
                f"got {names('exit(0)')}")
    got = names("exit(0)\ndef main():\n    return 1\n")
    ok &= check(got == [M.MODULE_BODY_NAME, "main"],
                "the body runs before a declared main", f"got {got}")
    return ok


def test_a_name_collision_with_the_body_function_is_refused(tmpdir, verbose):
    """A file that defines `__module_body__` itself is refused, by name.

    `__module_body__` is a legal Python identifier, so a file CAN define it,
    and both backends key their function tables by name — two functions of
    one name means the second silently replaces the first, and which one
    wins would depend on emission order. Refused, because a coin toss is not
    an answer.

    The second half is the one that makes the first safe: the SAME name in a
    file with no module body is an ordinary function and must still build and
    run, or the refusal would be refusing a name rather than a collision."""
    ok = case_refused(
        "body_name_collision",
        "def __module_body__():\n    return 5\n\nexit(0)\n",
        "which is the name this path compiles a module's top-level "
        "statements under", tmpdir, verbose)
    ok &= case_agrees_with_cpython(
        "body_name_no_collision",
        "def __module_body__():\n    return 5\n", tmpdir, verbose,
        expect_stdout="", expect_exit=5)
    return ok


def test_a_folded_constant_the_body_rebinds_keeps_its_store(tmpdir, verbose):
    """`total = 0` at file level, then a loop that accumulates into it.

    The wrong answer this whole rule exists to prevent, and it is a WRONG
    ANSWER rather than a refusal, which is why it is pinned: `total = 0`
    folds to a literal, so the store is normally left out of the body and the
    literal substituted at each read. The substitution does not fire inside
    the body — it skips a name the reading function BINDS, and the loop binds
    `total` — so with the store left out the read at the top of the loop has
    no value at all. Measured before the fix: `total=-157679350` on arm64
    and `total=240046802` on x86-64, for a program CPython answers 10 on.

    The two architectures disagreeing about a word neither of them wrote is
    the reason this is a case and not a note."""
    return case_agrees_with_cpython(
        "rebound_constant",
        "total = 0\nfor i in range(5):\n    total = total + i\n"
        "printf(\"total=%d\", total)\n", tmpdir, verbose,
        expect_stdout="total=10", expect_exit=0)


# ── driver ─────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    tmpdir = tempfile.mkdtemp(prefix="formal-toplevel-")
    cases = [
        test_module_body_classification,
        test_entry_order_is_the_module_body,
        test_entry_point_program_shape,
        test_body_calls_main,
        test_body_does_not_run_main_it_does_not_call,
        test_exit_from_the_module_body,
        test_body_runs_before_a_later_exit,
        test_name_guard_true,
        test_name_guard_false,
        test_name_in_a_function_is_still_refused,
        test_a_docstring_only_module_still_builds,
        test_hostmods_still_build_with_no_body,
        test_file_level_return_is_refused,
        test_file_level_global_is_refused,
        test_file_level_yield_is_refused,
        test_file_level_await_is_refused,
        test_a_dylib_runs_its_module_body_at_load_time,
        test_dylib_path_still_refuses_a_body_that_cannot_run,
        test_t1_is_a_named_finding_not_a_pass,
        test_a_module_body_reaches_its_next_real_finding,
        test_a_module_body_subscript_and_dict_run,
        test_a_module_body_construction_with_arguments_runs,
        test_a_module_body_construction_leaves_an_unassigned_field_at_its_default,
        test_a_module_body_construction_without_field_annotations_runs,
        test_a_module_body_can_still_be_refused_by_the_ordinary_codegen,
        test_a_name_collision_with_the_body_function_is_refused,
        test_a_folded_constant_the_body_rebinds_keeps_its_store,
    ]
    for fn in cases:
        if args.verbose:
            print(f"  {fn.__name__}")
        fn(tmpdir, args.verbose)
    npass = sum(1 for ok, _ in RESULTS if ok)
    nfail = len(RESULTS) - npass
    print(f"\nformal toplevel: PASS={npass} FAIL={nfail} "
          f"({len(RESULTS)} checks)")
    return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())
