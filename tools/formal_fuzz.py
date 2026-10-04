#!/usr/bin/env python3
"""DIFFERENTIAL FUZZING for the formal backend: CPython vs a built image.

`test_formal_x86_64_parity.py` asserts that a program which WAS THOUGHT OF gets
the same answer on both architectures as it does on CPython.  Every case in it is
a construct somebody already knew to be interesting, which makes it a good place
to pin a fix and a bad place to find the next one: the class of silent
miscompiles that survives such a file is exactly the class nobody wrote a case
for.  This tool closes that gap the only way that scales — generate programs
nobody designed, run each one three ways, and require the answers to be equal.

    python3 tools/formal_fuzz.py --count 200 --backends x86_64,arm64 --jobs 6

Three answers per program:

  * CPython — the SOURCE's meaning, computed here, now, by running the same
    text.  Not a constant anyone wrote down: a reference that cannot run
    asserts nothing, and a golden value recorded against a lowering is an
    assertion about the lowering made against itself.
  * the built image, under `arch -x86_64` on this host (the x86-64 backend's
    whole subject is an image that RUNS, so "built" and "ran" are separate
    properties and only the second one is compared);
  * the same program built for arm64, when `--backends` names it — the
    arm64-vs-x86-64 disagreement, which is a miscompile the CPython
    comparison alone can miss whenever both machines are wrong the same way.

A program is generated ONCE and both engines run the SAME TEXT.  The only
difference between the two files is a prelude of type-name aliases
(`Int64 = Int32 = int`, `String = str`) that CPython needs because it
evaluates a `def`'s annotations, and a `main()` call — so a divergence is a
divergence of ANSWERS, never of dialects.  `var`, and any other spelling Mojo
accepts and Python does not, is deliberately absent from the generator.

WHAT IS AND IS NOT A FINDING
----------------------------
  match                both images agree with CPython.  The common case.
  MISMATCH-X86         the x86-64 image disagrees with CPython: a silent
                       miscompile.  Minimised and reported.
  MISMATCH-ARM64       the arm64 image disagrees with CPython.  Reported, and
                       left to whoever holds the arm64 claim unless the x86-64
                       image agrees with it (which makes it a semantics gap in
                       both, not an x86-64 bug).
  ARM64-DIVERGES       the two images disagree with each other.  UNREACHABLE as
                       `classify` is ordered today: both answers are compared
                       against the same CPython output first, so "both agree with
                       CPython and differ from each other" cannot happen, and the
                       shape is reported as a `MISMATCH-*` naming the engine that
                       is wrong about the program.  Kept because it is the
                       verdict that shape deserves and because it becomes
                       reachable the moment the ordering changes — but do not
                       expect to see it in a tally.
  KNOWN:…              the image disagrees with CPython, and the disagreement
                       reduces to a construct `KNOWN_DIVERGENCES` names.
                       Counted apart from a finding so a sweep of two thousand
                       programs stays readable, and reported with the
                       reproducer like any other.
  trapped              the stack-floor guard stopped the program (`exit 2`,
                       `formal/model.py`'s `STACK_TRAP_STATUS`).  A documented
                       limit of this path and not a disagreement: CPython has
                       no such bound and ran the same text.
  CPYTHON-TIMEOUT     the ORACLE did not finish the program, so nothing was
                       compared and nothing is claimed.  Its own verdict rather
                       than a crash: `cpython_answer` answers `None` for it, and
                       a caller that read "not an error tuple" as "has an
                       answer" died with `TypeError: cannot unpack non-iterable
                       NoneType object` — measured, in a `signed` sweep, on a
                       program whose recursion runs CPython past its own
                       recursion limit.
  refusal             the compiler said no.  Not a finding: a construct with
                       no representation is CORRECTLY refused, and a fuzzer
                       that counted those as bugs would spend its whole budget
                       re-discovering `bugs/FORMAL_known_limits.md`.  Counted by
                       message so the construct mix stays visible.
  codegen-crash        the compiler raised something that is not a refusal
                       (a traceback, or a signal).  THIS is a finding: a
                       backend that dies on a source it merely cannot model is
                       a crash the sweep classifies separately, and it is never
                       cached, so it costs a build on every sweep until it is
                       gone.

THE KNOWN DIVERGENCES, AND WHY GENERATING THEM IS THE POINT
-----------------------------------------------------------
Three constructs in this subset are known to disagree with CPython today, and
they are in `KNOWN_DIVERGENCES` with the document that owns each.  The
generator emits them DELIBERATELY — `--mix signed` spells a division with two
signed operands, which is the whole of the floor-versus-truncate disagreement,
and `--mix strings` reads `s[i]`, which is a byte rather than a one-character
string.  A generator that avoided them would be quieter, and quiet here means
blind: a construct the corpus cannot produce cannot be noticed the day it is
fixed, which is precisely the moment the tool exists for.

What keeps them from drowning a sweep is ATTRIBUTION, not avoidance.  A
disagreement is minimised first, and then the reduced program is re-tested with
each known construct swapped out — the operator for one of the same arity and
the same operand types, so no name goes unbound and the program stays a
program.  Only a candidate that then AGREES with CPython counts as evidence, and
the set that explains it is shrunk one construct at a time, so what the summary
prints is a MINIMAL explanation rather than "every known bug in the file".  If
removing all of them does NOT make the program agree, nothing is blamed and the
disagreement stays a finding: "there is a known bug in here too" is not a
reason to miss this one.

**What the blame cannot do, stated rather than hidden.** Neutralisation is a
TEXTUAL substitution, and a substituted program can stop being a runnable
program — swapping `%` for `+` can make an argument large enough that CPython
hits its own recursion limit.  A candidate that does not run counts as no
evidence in either direction, so a disagreement whose only explanation needs
such a substitution is reported as unexplained even when it is a known
construct's.  That is the direction to err in — one extra report rather than
one hidden bug.  Each construct is also tried on its OWN after the whole set
fails, because two truncating divisions in one program means neither alone is
the whole cause and calling that unexplained would be a false positive on the
tool rather than on the backend.

EXIT STATUS
-----------
0 when there is nothing unexplained: no `MISMATCH-*`, no `ARM64-DIVERGES`, no
`REFUSAL-DIVERGES-*`, no `codegen-crash` and no generator error.  1 when at
least one is unexplained.  A tool that returned 0 while a program computed the
wrong number would be worse than no tool.

A `REFUSAL-DIVERGES-*` counts, and it is the newest member of that list.  A
refusal on its own is not a finding — a construct with no representation is
CORRECTLY refused, and counting those would spend the whole budget on
`bugs/FORMAL_known_limits.md`.  A refusal on ONE architecture while ANOTHER
answers the same program is a different thing: the construct is representable,
one machine says so by running the program, and this one declines it.  That is
the divergence `test_formal_x86_64_parity.py` exists to keep closed, and while
this tool reported it as a plain `refusal` it was invisible — the corpus kept
generating the program, kept saving it, and counted the run as clean.

THE VALUE DISCIPLINE, and the one place it is deliberately broken
-----------------------------------------------------------------
The generator stays inside the modelled subset almost everywhere: `//` and `%`
in `--mix core` are emitted with a provably positive divisor and a
non-negative dividend, because Python FLOORS and the backends truncate toward
zero BY DESIGN — see `formal/model.py`'s `fold_literal_expr`; and integers are
masked back into a small range because CPython integers are unbounded and a
formal value is one 64-bit word.  A generator that ignored either fact would
report the word-size model and the floor-division decision as miscompiles,
hundreds of times, and the signal would be worthless.

`--mix signed` is the exception and it exists on purpose: it drops both
disciplines for division only, into the SIGNED variable family, which is
bounded rather than unbounded.  That is where the truncation bug was found.

    python3 tools/formal_fuzz.py --minimize path/to/prog.mojo [--kind x86]

ONE TOOL, BOTH ARCHITECTURES
---------------------------
`--backends x86_64,arm64` (the default) is the whole of the differential claim:
each program is built twice and the two images are compared with each other as
well as with CPython, because a bug both machines share is invisible to a
CPython-only check whenever CPython is what is wrong about the MODEL. Run it
with `--backends x86_64` (or `--arch x86_64`, which is the same statement) to
halve the cost when only one architecture is in scope. The arm64 and x86-64
fuzz claims are this file with a different `--backends`; a second generator
would be a second set of oracle bugs.

DETERMINISM
-----------
`make_program(seed, index, mix, stmts)` is a pure function of its arguments, so
a program reproduces byte for byte on any machine and any run, and a
disagreement reported here is re-reportable from the seed and the index alone.
`--print-program N` prints one program's source and exits, which is how a
reported index becomes something you can read and minimise by hand.

WHAT IS COVERED, AND WHAT IS NOT, so the next reader does not have to measure it
-----------------------------------------------------------------------------
`--mix` names the construct families, and the list is the CORPUS's, not the
backend's: a family is here because the corpus can produce it and a case
somebody thought of cannot. Two groups.

The arithmetic and control half: `core` (arithmetic, comparisons, loops,
augmented assignment), `signed` (division with two signed operands, which is
where the floor/truncate disagreement lives), `calls` (module-level helpers,
nested calls, tail recursion), `classes` (a `class` with fields and methods, so
the frame receiver), `globals` (module-level `__DATA` slots, read through a
local and written by a helper through its own `global`), `generics` (`def
f[T](x: T, …)` called at more than one type, which is what monomorphisation
acts on), `environ` (`os.getenv` against a FIXED process environment,
`FIXED_ENV`).

The value-model half: `strings` (binding, `len`, comparison, the byte
subscript), `strmeth` (the five methods this path lowers — `count`, `find`,
`startswith`, `endswith`, `lstrip`), `lists`, `containers` (dict pair blobs,
tuples, and `append`).

Every one of the last five was added because a DIFFERENTIAL SWEEP found
something in it, and the ledger is `bugs/FORMAL_fuzz_ledger.md`: `containers`
because `for k in d` read `k0, v0, k1` on BOTH architectures (exit 0) and
because a membership test's bound was its own needle on x86-64;
`generics`/`globals`/`strmeth`/`environ` because they were newly lowered and
had no coverage at all, which is the state in which a bug is cheapest to
introduce and most expensive to find.

Deliberately absent, each for a stated reason:

  * `struct` with DECLARED fields (`var a: int`) — `var` is a keyword CPython
    cannot parse, so the two engines would stop running the same text. `class`
    covers the same frame-receiver machinery in a spelling both accept.
  * pointers and `malloc` — every value is a word here; `Pointer[Int32]` and
    the augmented-assignment ladder are in `test_formal_x86_64_parity.py`.
  * floats — this path is int-only (a float literal truncates), so a `double`
    is a word and a fuzz oracle built on one would be testing the model, not
    the lowering.
  * STRING CONCATENATION and the length-dependent methods — refused, with the
    measurement in the refusal (`model.string_concat_refusal`): a string is a
    bare `char *` and `+` is integer addition of two addresses, which printed
    `[]` on arm64 and segfaulted on x86-64. `strmeth` is the surface that IS
    lowered, so the corpus spends its string budget where answers exist.
  * GROWING a container — `d[k] = v` for a key the table does not have is a
    key scan that misses, and the miss signal on this path is `exit(1)` with
    nothing printed; `xs.append(v)` inside a loop overflows the blob's
    capacity, which is the number of append SITES in the function that built
    it. Both are limits with a diagnostic rather than defects, and both are
    measured: `bugs/FORMAL_a_dict_store_of_a_new_key_is_a_run_time_miss.md`.
  * a variadic `printf` with more than five operands — arm64 refuses a variadic
    call whose arguments pass the register file, so a program with more than
    seven of them is not a two-architecture case at all. The stack-argument
    convention is covered by `test_formal_run.py`'s `BOTH_ARCH_CASES` ladder.
  * file descriptors, dylibs, `comptime` — the families the module suites own;
    a fuzz program that opened a file would make the comparison depend on the
    filesystem. (`import` IS generated, for `os.getenv` only.)

THE COST OF A MIX, because it decides how large a sweep of it is worth running:
`core` and `calls` run at about 1.9 programs/second at `-j 2`, `containers` and
`globals` at 0.7-1.1, and `environ` at 0.14 — a program that imports `os` pays
for the host module's dylib on every build, which no cache in this tool covers.
A sweep of `environ` is therefore a tenth the size of a sweep of `core` for the
same number of builds.
"""
import argparse
import json
import os
import platform
import random
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRE = os.path.join(HERE, "fire.py")

BUILD_TIMEOUT = 120
RUN_TIMEOUT = 30
PY_TIMEOUT = 30

# The status the formal runtime exits with when a recursive call chain runs off
# the stack floor the prologue guards (`formal/model.py`'s `STACK_TRAP_STATUS`).
# CPython has no such bound, so a program that recurses a few hundred deep runs
# there and stops here. It is a verdict about the program rather than a verdict
# about a bug, and it is counted as its own status so a sweep's numbers stay
# readable — a deep recursion is a documented limit of this path
# (`bugs/FORMAL_stack_floor_does_not_guard_an_acyclic_chain.md`), not a silent
# wrong answer.
#
# Reading it off the exit status is sound for THIS generator because `main`
# always `return 0`: the entry function's return value IS the process exit
# status, so 2 cannot be an answer the program computed. `--min-kind any`
# preserves it deliberately, so a reproducer for the guard is not minimised into
# one that no longer trips it.
STACK_TRAP_STATUS = 2

# `known feature` -> (one line, the document that owns it). The feature markers
# are matched against the MINIMISED program, so a marker names a construct that
# is present in the smallest reproducer rather than in the program it came from.
#
# **A row here is a CLAIM that the tool still measures the construct.** The
# anti-rot is the row's own life: delete the construct's row in the same commit
# that fixes it, or the corpus stops covering the day the bug goes away and the
# table becomes a list of things nobody looks for. `bugs/
# FORMAL_floor_division_on_a_signed_operand_is_truncated.md` §5 says so with its
# own row as the example.
KNOWN_DIVERGENCES = {
    "floordiv": (
        "`//` truncates toward zero instead of flooring (bugs/"
        "FORMAL_floor_division_on_a_signed_operand_is_truncated.md)"),
    "modulo": (
        "`%` takes the sign of the DIVIDEND instead of the divisor (same doc as "
        "`floordiv`)"),
    "str_subscript": (
        "`s[i]` is a byte, not a one-character string (bugs/"
        "FORMAL_string_value_model.md)"),
}

# The constructs that make a feature marker true. Checked against the minimised
# program's text; a marker is only blamed when removing every occurrence of one
# of its spellings makes the program agree.
FEATURE_PATTERNS = {
    "floordiv": (r"//",),
    "modulo": (r"(?<![\w)])%(?![a-zA-Z_(])",),
    # Decided by `features_of`, not by a pattern: a subscript is correct on a
    # list and wrong on a string, and only the binding says which. An empty
    # pattern tuple is how this table says "handled specially", and keeping the
    # KEY is what lets the neutraliser and the summary find it by name.
    "str_subscript": (),
}

# How to take one known construct out of a program WITHOUT changing its shape:
# the operator is swapped for one with the same arity and the same operand
# types, or the offending line is replaced by an equivalent one. Shape matters
# because the alternative — deleting the statements that mention the construct —
# takes the definitions with them, so the program then fails for a reason that
# has nothing to do with the disagreement and nothing is learned. Swapping `//`
# for `-` leaves every name bound and every statement in place, so if the
# program agrees afterwards then the division is what was wrong.
NEUTRALISERS = {
    "floordiv": [(r"//", "-")],
    "modulo": [(r"(?<![\w)])%(?![a-zA-Z_(])", "+")],
    # The index is `-?\d+` and not `\d+` because the minimiser's literal pass
    # rewrites an index to `0`, `1` or `-1` and takes whichever still
    # reproduces — so a reproducer that has been reduced by one line is the
    # common case, not the exception, and a pattern that only matched a
    # non-negative one could not take the very programs it is most often asked
    # about apart.
    "str_subscript": [(r"print\((\w+)\[(-?\d+)\]\)", r"print(1)")],
}

# The CPython side of the SAME TEXT.  A `def`'s annotations are evaluated when
# the def executes, so `-> Int32` needs the name to exist; a local annotation
# inside a function body is NOT evaluated (PEP 526), which is why the generator
# can annotate locals without these aliases.
PRELUDE = (
    "import sys\n"
    "Int = Int32 = Int64 = UInt = UInt32 = UInt64 = Bool = int\n"
    "String = str\n"
)


# ── the harness ────────────────────────────────────────────────────────────

def build(src, out, backend, timeout=BUILD_TIMEOUT):
    """Compile `src` for `backend`; (rc, diagnostic).

    The diagnostic is stderr or stdout, whichever carries text — a refusal is
    printed where the build found it, and the two are not the same stream on
    every failure.
    """
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove",
           f"--backend={backend}", "-o", out, src]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, cwd=HERE)
    except subprocess.TimeoutExpired:
        return 124, f"BUILD TIMEOUT after {timeout}s"
    return p.returncode, (p.stderr or p.stdout or "")


def run(path, backend, timeout=RUN_TIMEOUT):
    """Execute a built image — under Rosetta when it is an x86-64 one.

    Selected by the BACKEND, not applied to whatever was built: on an arm64
    host `arch -x86_64 <an arm64 image>` is "Bad CPU type in executable", which
    is a failure that reads as the host's fault and is really the harness
    asking the wrong machine to run the program.

    Under `FIXED_ENV`, like the CPython reference (`cpython_answer`), and for
    the reason `FIXED_ENV` gives: a program that reads the environment reads
    the PROCESS, so an inherited block makes the comparison depend on the shell
    that started the sweep. `arch` passes the environment through, so both
    architectures still see the same one.
    """
    argv = [path]
    if (backend == "x86_64" and platform.machine() in ("arm64", "aarch64")
            and sys.platform == "darwin"):
        argv = ["arch", "-x86_64", path]
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           env=dict(FIXED_ENV))
    except subprocess.TimeoutExpired:
        return None, f"RUN TIMEOUT after {timeout}s"
    return (p.returncode, p.stdout), p.stderr


# The CPython driver, and why `main`'s return value is REPORTED rather than
# used AS the exit status.
#
# On both backends `main`'s return value IS the process exit status — that is
# what the formal runtime's entry stub does, and `test_formal_run.py`'s
# `BOTH_ARCH_CASES` assert it for every row. The obvious driver,
# `...\nmain()\n`, throws that value away: CPython then always exits 0, so an
# image whose `main` returned 1 compares 1 against 0 and is reported as a
# silent miscompile forever. It is not visible on a freshly generated program
# because `main` returns 0 and the minimiser only reaches a non-zero one after
# it has shrunk something else away — which is exactly when a reproducer is
# being read.
#
# Reporting it on stderr, rather than raising `SystemExit(_rc)`, is what keeps
# the two failure modes apart. With `SystemExit(_rc)` a non-zero status is
# AMBIGUOUS: it is either the program's answer or CPython's own traceback, and
# this function has to tell those apart because only the first is a verdict. A
# sentinel line the driver writes only on success makes them disjoint — the
# traceback case exits non-zero with no sentinel.
_RC_TAG = "__FORMAL_FUZZ_RC__"
_RC_RE = re.compile(r"^%s (-?\d+)$" % _RC_TAG, re.M)
# `@PROGRAM@` and `@TAG@` rather than `%`-formatting, because the driver itself
# is full of `%` — it has to be, it is a modulo — and escaping those through a
# second layer of formatting is how a driver quietly stops printing its own
# answer.
PY_DRIVER = (
    PRELUDE + "@PROGRAM@"
    "\nimport sys as _sys\n"
    "_rc = main()\n"
    "_sys.stderr.write('@TAG@ %d\\n' % _rc)\n"
)


def has_oracle(ref):
    """Whether `cpython_answer` produced an ANSWER rather than one of its two
    non-answers.

    It has THREE, which is the whole reason this is a function: an answer is an
    `(exit, stdout)` tuple, a generator error is `("error", …)`, and a CPython
    TIMEOUT is `None`.  "not an error tuple" is therefore not "has an oracle",
    and every caller that read it that way crashed on the timeout with
    `TypeError: cannot unpack non-iterable NoneType object` — measured in a
    `signed` sweep, minimising a program whose recursion runs CPython past its
    own recursion limit.  A tool that dies on its own oracle reports nothing
    about the backend, and its exit status says nothing either.
    """
    return bool(isinstance(ref, tuple) and ref and ref[0] != "error")


def cpython_answer(text, tmpdir, name):
    """(exit, stdout) for `text` + `main()`, run by the interpreter here."""
    py = os.path.join(tmpdir, name + ".ref.py")
    with open(py, "w") as f:
        f.write(PY_DRIVER.replace("@PROGRAM@", text).replace("@TAG@", _RC_TAG))
    try:
        p = subprocess.run([sys.executable, py], capture_output=True, text=True,
                           timeout=PY_TIMEOUT, env=dict(FIXED_ENV))
    except subprocess.TimeoutExpired:
        return None, "CPYTHON TIMEOUT"
    m = _RC_RE.search(p.stderr or "")
    if m:
        # `& 0xFF` because a process exit status is EIGHT BITS wide and
        # `main`'s return value is not: `return 347` exits 91, and
        # `test_formal_run.py`'s comment on its own expected values says so.
        # Without the mask a negative or wide return reads as a disagreement
        # that is really an arithmetic identity — `return -3` exits 253.
        return (int(m.group(1)) & 0xFF, p.stdout), ""
    if p.returncode != 0:
        # A generated program that CPython rejects is a GENERATOR bug (a
        # ZeroDivisionError, say), not a finding about the backends.  Returned
        # with its stderr so the caller can say so rather than silently drop it.
        return ("error", p.stderr.strip()[-400:]), ""
    # Exited 0 with no sentinel: `main` returned something that is not an int,
    # which the generator's own `return 0` cannot do and the minimiser's
    # sub-expression pass cannot reach.  Said rather than answered as 0.
    return ("error", "the CPython driver printed no %s sentinel" % _RC_TAG), ""


def run_on(backend, text, tmpdir, name):
    """Everything ONE backend says about `text`: built? ran? printed what?

    Returns a dict whose `verdict` is one of `ok`, `refusal`, `crash`,
    `timeout`; `ok` carries the exit status and stdout that the comparison
    needs, and every verdict carries enough text to reproduce the report line.
    """
    src = os.path.join(tmpdir, f"{name}.mojo")
    out = os.path.join(tmpdir, f"{name}.{backend}")
    with open(src, "w") as f:
        f.write(text)
    rc, diag = build(src, out, backend)
    if rc != 0:
        # A crash is a traceback or a signal; a refusal is a sentence.  The
        # distinction matters because only one of them is a defect: `formal`
        # raises CodegenError with prose for a construct it declines to model.
        crashed = ("Traceback (most recent call last)" in diag
                   or "codegen-crash" in diag
                   or rc < 0
                   or rc in (134, 139, 136, 132, 133, 135, 137))
        return {"verdict": "crash" if crashed else "refusal", "rc": rc,
                "diag": diag.strip()[-400:]}
    if not os.path.isfile(out):
        return {"verdict": "crash", "rc": rc,
                "diag": "reported success and wrote no binary"}
    got, err = run(out, backend)
    if got is None:
        return {"verdict": "timeout", "rc": rc, "diag": err}
    exit_code, stdout = got
    if exit_code is not None and exit_code < 0:
        return {"verdict": "crash", "rc": exit_code,
                "diag": f"image died with signal {-exit_code}: "
                        f"{err.strip()[:200]}"}
    if exit_code is not None and exit_code > 128:
        return {"verdict": "crash", "rc": exit_code,
                "diag": f"image exited {exit_code} (signal "
                        f"{exit_code - 128}): stdout={stdout[:120]!r}"}
    if exit_code == STACK_TRAP_STATUS:
        # Asked BEFORE the comparison, and the reason it is its own verdict is
        # that CPython cannot produce it: this path's `main` always `return 0`,
        # so a status of 2 is the stack-floor guard and nothing else. Left as an
        # `ok` it would be reported forever as a disagreement about a recursion
        # depth that is a documented limit.
        return {"verdict": "trapped", "rc": exit_code, "stdout": stdout,
                "stderr": err,
                "diag": f"the stack-floor guard stopped it (exit "
                        f"{STACK_TRAP_STATUS}); CPython ran the same text"}
    return {"verdict": "ok", "rc": exit_code, "stdout": stdout, "stderr": err}



# ── the generator ───────────────────────────────────────────────────────────
#
# One text, two engines.  Everything below emits the intersection of Mojo and
# Python: no `var`, no `struct`/`fn`, no `^` ownership marker (a borrow-check
# annotation in Mojo and a bitwise xor in Python — the one operator in the
# language whose two readings differ), no comprehension, no f-string.  The
# construct mix is weighted towards what a compiler gets wrong QUIETLY rather
# than what it refuses loudly.
#
# The value discipline is the part that decides whether this tool is worth
# anything, and it exists for three measured reasons:
#
#   * CPython integers are unbounded; a formal value is ONE 64-bit word.  So
#     every growing expression is masked back into `0..0xFFFF` and every
#     multiplication masks its own operands.  Without that the word-size model
#     reports itself as a miscompile on almost every program.
#   * Python's `//` and `%` FLOOR; the backends truncate toward zero BY DESIGN
#     (`formal/model.py`'s `fold_literal_expr` says so).  So a divisor is made
#     odd (`| 1`, hence non-zero) and a dividend is masked non-negative: a
#     documented disagreement and a ZeroDivisionError are not findings, and a
#     generator that produces either reports the same non-bug hundreds of
#     times.
#   * A local the program only sometimes assigns is a NameError in CPython and
#     a zero on this path, which is not a disagreement about codegen at all.
#     So EVERY local is declared up front, in one preamble, with the initial
#     value CPython would otherwise not have.
#
# Those three are the whole difference between a fuzzer that finds bugs and one
# that finds its own generator.

STRINGS = ["ab", "cd", "ef", "gh", "", "a", "xyz", "pqrs"]

#: The process environment every engine — and CPython — is RUN with, for the
#: `environ` mix. A FIXED one, and it replaces the inherited block rather than
#: adding to it, because an inherited environment cannot answer a differential
#: test at all: a shell adds `_` to a child's block and cannot add it to a parent
#: that has already started, so the same text under two parents sees two blocks
#: and a disagreement is undecidable. `test_formal_os_backing.py` §7 makes the
#: same argument for the same object and puts `__CF_USER_TEXT_ENCODING` in its
#: fixed dict for a second reason: an x86-64 image run through Rosetta is
#: launched with that variable whether the parent put it there or not, so
#: declaring it is what makes the two architectures compare the SAME block.
FIXED_ENV = {
    "__CF_USER_TEXT_ENCODING": "0x1F9:0x0:0x0",
    "FORMAL_FUZZ_PLAIN": "one",
    "FORMAL_FUZZ_TWO": "two words",
    # A value containing `=`: the split is at the FIRST `=`, so this is key
    # `FORMAL_FUZZ_EQUALS` and value `a=b=c`. It is in the table because a
    # second `=` is the one place a hand-rolled split answers something
    # plausible and wrong.
    "FORMAL_FUZZ_EQUALS": "a=b=c",
}

# Which construct families appear, with weights.  `core` is the
# arithmetic/control/comparison half — signedness, loop counters, augmented
# assignment; `calls` adds user functions and nesting; `strings` and `lists`
# add the two container halves of the value model.
MIXES = {
    "core": (("assign", 5), ("arith", 4), ("augassign", 5), ("shift", 3),
             ("cmp", 4), ("logic", 2), ("if", 5), ("while", 3), ("for", 3),
             ("div", 2), ("pow", 1), ("break", 1), ("cond_expr", 2)),
    "calls": (("assign", 3), ("arith", 3), ("augassign", 3), ("cmp", 3),
              ("if", 3), ("while", 2), ("for", 2), ("call", 5),
              ("nested_call", 4), ("recursion", 2), ("arg_expr", 3)),
    "strings": (("assign", 2), ("str_assign", 3), ("str_print", 3),
                ("str_len", 2), ("str_cmp", 2), ("str_subscript", 3),
                ("if", 3), ("call", 2)),
    # The SIGNED division family, and the one place the value discipline above
    # is deliberately dropped — because dropping it is how the truncation bug
    # was found. `div_signed` and `mod_signed` write a SIGNED dividend over a
    # SIGNED divisor into the `smalls` family, so the disagreement is visible;
    # both operands stay bounded (`smalls` are `-32..32`, literals are single
    # digits) and the divisor is forced non-zero by `| 1`, which keeps the sign
    # and cannot produce a zero. A mix that left this out of the corpus could
    # not notice the day the backend's `//` was fixed, which is the only moment
    # the tool is for.
    "signed": (("assign", 3), ("div_signed", 5), ("mod_signed", 5),
               ("cmp", 3), ("logic", 2), ("if", 4), ("while", 2), ("for", 2),
               ("print", 2)),
    "lists": (("assign", 2), ("list_build", 3), ("list_read", 3),
              ("list_write", 2), ("list_len", 2), ("if", 3), ("while", 2),
              ("list_in_loop", 2)),
    # A struct spelled as a `class`, because that spelling is valid in BOTH
    # engines (`test_formal_x86_64_parity.py`'s `aug_division_through_a_frame_
    # slot` is the same construct) and it is the only way this generator can
    # reach the frame-receiver machinery: a receiver that is a frame ADDRESS
    # rather than a value, whose fields live in the callee's own slots.
    "classes": (("obj_new", 3), ("field_read", 3), ("field_cmp", 3),
                ("field_write", 3), ("method_call", 5),
                ("method_call_in_arg", 3), ("assign", 2), ("if", 3),
                ("while", 1), ("augassign", 2)),
    # The PAIR blob and the blob beside it.  This mix exists because the `lists`
    # half above walks a `[count][e0][e1]…` at one stride and every walk over a
    # dict is the SAME walk at a different one — and `for k in d` reading
    # `k0, v0, k1` (both architectures, exit 0) is exactly the class of defect a
    # corpus that cannot produce a dict cannot notice.  Membership is here for
    # the same reason: it is the same walk with a needle and it had its own two.
    "containers": (("assign", 2), ("dict_build", 3), ("dict_read", 3),
                   ("dict_write", 2), ("dict_len", 2), ("dict_in", 3),
                   ("dict_iter", 4), ("dict_comp_count", 2),
                   ("tuple_build", 2), ("tuple_read", 2), ("tuple_len", 2),
                   ("tuple_iter", 2), ("list_build", 2), ("list_read", 2),
                   ("list_write", 1), ("list_append", 2),
                   ("if", 3), ("while", 1), ("for", 2)),
    # Module-level state: a `__DATA` slot rather than a frame slot, which is a
    # different owner, a different lifetime and a different store from every
    # other local in this generator.
    "globals": (("assign", 2), ("global_read", 4), ("global_write", 3),
                ("global_bump", 4), ("global_container", 2), ("if", 3),
                ("while", 1), ("for", 2), ("augassign", 2), ("print", 2)),
    # The five string METHODS this path lowers, which is the whole of what a
    # string can do here: `+` and the length-dependent methods are refused (see
    # `strmeth_stmt`), so `count`/`find`/`startswith`/`endswith`/`lstrip` plus
    # `len` is the surface, and it was entirely uncovered.
    "strmeth": (("str_bind", 3), ("str_count", 3), ("str_find", 3),
                ("str_startswith", 3), ("str_endswith", 3), ("str_lstrip", 2),
                ("str_meth_len", 2), ("if", 3), ("call", 2), ("print", 2)),
    # Monomorphisation.  One generic definition called at more than one type is
    # the whole subject (`formal/monomorph.py`), and a corpus whose every call
    # site agrees cannot tell a monomorphising backend from one that ignores
    # the argument's type entirely.
    "generics": (("generic_define", 3), ("generic_call", 5), ("assign", 2),
                 ("if", 3), ("while", 1), ("for", 2), ("augassign", 2)),
    # The process environment, against a FIXED one (`FIXED_ENV`).
    "environ": (("environ_get", 4), ("environ_len", 3), ("environ_cmp", 3),
                ("if", 2), ("assign", 2), ("augassign", 2)),
}

# The growing augmented operators, and the bound each one's RIGHT-HAND side is
# held to.  `*=` and `<<=` are the two that can leave 16 bits very fast, and
# both operands are masked so that a loop body which runs five times still
# cannot reach the 64-bit ceiling: `0xFFFF * 0xF` per step is under 2^20, five
# steps under 2^24.
GROWTH_MASK = {"+=": "0xF", "-=": "0xF", "*=": "0xF", "<<=": "3"}

#: How many helper functions one program may define, including the ones its
#: helpers define (see `define_function`), and how many classes it may define.
MAX_FUNCS = 5
MAX_CLASSES = 2


class Gen:
    """One random program, emitted as text.

    `words` are masked and non-negative; `smalls` are signed and stay small.
    Both families are read by comparisons against each other, which is how a
    signed/unsigned disagreement in a lowering becomes an observable answer
    rather than a variable nobody looks at.
    """

    def __init__(self, rng, mix="core", stmts=(5, 12)):
        self.rng = rng
        self.mix_name = mix
        # How many statements `main`'s body carries.  The default range is
        # deliberately small; `--stmts 40 60` is how the SPILL paths get
        # reached, because x86-64 has 15 usable general registers and a
        # function with twenty live locals has to put some of them in its
        # frame — a lowering that reads a spilled slot at the wrong offset is
        # silent, and a twelve-statement program never has enough live values
        # to spill one.
        self.stmt_lo, self.stmt_hi = stmts
        self.weights = dict(MIXES.get(mix, MIXES["core"]))
        self.mix = set(self.weights)
        self.words = []       # masked, 0..0xFFFF
        self.smalls = []      # signed, small
        self.strings = []     # String locals
        self.strings_text = {}  # String local -> the literal it was bound to
        self.lists = []       # (name, length) list locals of ints
        self.dicts = []       # (name, key kind, keys) dict locals
        self.tuples = []      # (name, length) tuple locals of ints
        self.globals = []     # (name, initial value) module-level INT names
        self.global_containers = []   # (name, length) module-level list names
        self.generics = []    # (name, arity, returns a String) generic defs
        self.classes = []     # (name, fields, methods) definitions
        self.objs = []        # (var, class name, fields, methods) instances
        self.fields = []      # field names, inside a method body
        self.funcs = []       # (name, [parameter names])
        self.decls = []       # (name, initial value text) for the preamble
        self.defs = []        # module-level function definitions
        self.out = []         # the body being emitted
        self.toplevel = []    # module-level statements, outside every body
        self.main_globals = []   # names `main` declares `global`, in order
        self.loop_depth = 0
        self.counter = 0
        self.defined = 0      # functions defined SO FAR, shared with children

    # ── plumbing ──
    def fresh(self, prefix):
        self.counter += 1
        return f"{prefix}{self.counter}"

    def emit(self, indent, text):
        self.out.append("    " * indent + text)

    def emit_top(self, text):
        """A MODULE-level statement, outside every function body.

        `self.out` is `main`'s body while the body is being emitted, and a
        module-level binding emitted into it would land inside `main` — where
        CPython reads it as a local and the backends read it as a frame slot,
        which is precisely the difference the globals family exists to measure.
        """
        self.toplevel.append(text)

    def pick(self, *kinds):
        """One construct family, by weight, restricted to this mix."""
        pool = [k for k in kinds if k in self.mix]
        if not pool:
            pool = ["assign"]
        return self.rng.choices(pool, weights=[self.weights.get(k, 1)
                                              for k in pool])[0]

    def declare(self, name, value):
        """Reserve a local and remember its initialiser for the preamble."""
        self.decls.append((name, value))
        return name

    # ── expressions ──
    def lit(self):
        r = self.rng.random()
        if r < 0.3:
            return str(self.rng.randint(-9, 9))
        if r < 0.5:
            return str(self.rng.choice([0, 1, 2, 7, 10, 16, 100, 255, 1000]))
        return str(self.rng.randint(-32, 32))

    def small_expr(self, depth=1):
        """An expression over the SMALL family only.

        Bounded by construction — smalls are `-32..32`, literals are single
        digits, there is no `*` and the depth is one — so the value cannot
        leave the range CPython and a 64-bit word agree on.  This is what a
        signed variable is written from, which is the only way a NEGATIVE
        number reaches a comparison.
        """
        if depth <= 0 or self.rng.random() < 0.4:
            if self.smalls and self.rng.random() < 0.6:
                return self.rng.choice(self.smalls)
            return str(self.rng.randint(-9, 9))
        op = self.rng.choice(["+", "-"])
        return f"({self.small_expr(depth - 1)} {op} {self.small_expr(depth - 1)})"

    def word_expr(self, depth=2):
        """An expression over the WORD family, already masked to 16 bits.

        Every multiplication masks its own operands (`0..0xFFFF` times
        `0..0xFF`), so a nested product cannot climb to the 64-bit ceiling and
        turn CPython's unbounded integer into a "miscompile".
        """
        if depth <= 0 or self.rng.random() < 0.35:
            if self.words and self.rng.random() < 0.7:
                return self.rng.choice(self.words)
            if self.smalls and self.rng.random() < 0.4:
                return self.smalls[-1]
            return str(self.rng.randint(0, 64))
        kind = self.rng.choice(["add", "mul", "paren", "bit", "cond"])
        if kind == "add":
            op = self.rng.choice(["+", "-"])
            return f"({self.word_expr(depth - 1)} {op} {self.word_expr(depth - 1)})"
        if kind == "mul":
            return (f"(({self.word_expr(depth - 1)} & 0xFFFF) * "
                    f"({self.word_expr(depth - 1)} & 0xFF))")
        if kind == "bit":
            op = self.rng.choice(["&", "|", "^"])
            return (f"({self.word_expr(depth - 1)} {op} "
                    f"{self.rng.choice([1, 3, 7, 15, 255, 4095])})")
        if kind == "cond":
            # A bool is a WORD on this path (`model.print_format`: a bool is an
            # integer by the time it is a value), so a boolean is never stored
            # or printed bare — it is a condition, or the 1/0 a conditional
            # expression produces.
            return f"(1 if {self.cond(depth - 1)} else 0)"
        return f"({self.word_expr(depth - 1)})"

    def int_expr(self, depth=2):
        """Any integer-valued expression, still safe to compute in both."""
        if depth <= 0 or self.rng.random() < 0.45:
            pool = self.words + self.smalls
            if pool and self.rng.random() < 0.8:
                return self.rng.choice(pool)
            return self.lit()
        r = self.rng.random()
        if r < 0.35:
            return self.word_expr(depth)
        if r < 0.55:
            return self.small_expr(1)
        if r < 0.7:
            op = self.rng.choice(["&", "|", "^"])
            return (f"({self.int_expr(depth - 1)} {op} "
                    f"{self.rng.choice([1, 3, 7, 255])})")
        if r < 0.85:
            return (f"(1 if {self.cond(depth - 1)} else "
                    f"{self.int_expr(0)})")
        n = self.rng.randint(0, 15)
        return (f"(({self.int_expr(depth - 1)} & 0xFFFF) "
                f"{self.rng.choice(['<<', '>>'])} {n})")

    def pos_div_expr(self):
        """`a // b` / `a % b` with a non-negative dividend and an odd divisor.

        See the module docstring: flooring versus truncation is a documented
        decision and a zero divisor is a trap, so neither may be generated.
        """
        a = f"({self.int_expr(1)} & 0xFFFF)"
        b = f"(({self.int_expr(1)} & 0xFF) | 1)"
        return f"({a} {self.rng.choice(['//', '%'])} {b})"

    def signed_div_expr(self, op):
        """`a <op> b` with a SIGNED dividend and a SIGNED divisor.

        The one expression in this generator that breaks both halves of the
        value discipline, and it exists for the reason the `signed` mix's
        comment gives. `| 1` on the divisor is what keeps this a program rather
        than a trap: an odd divisor is never zero, and `| 1` preserves the
        sign of the operand, so the divisor really can be negative — which is
        the entire question, because Python FLOORS a remainder and the backends
        TRUNCATE it and the two agree only when one operand's sign is fixed.

        Both operands are drawn from `small_expr`, which is `-32..32` with `+`
        and `-` only and no recursion past depth one, so the dividend cannot be
        the unbounded integer that would turn the word-size model into a
        thousand false positives.
        """
        a = self.small_expr(1)
        b = f"(({self.small_expr(1)}) | 1)"
        return f"({a} {op} {b})"

    def cond(self, depth=2):
        """A boolean-valued expression.

        Comparisons MIX the two families on purpose (`w < s` with `w >= 0` and
        `s < 0` is the shape a signedness bug answers wrongly and a fuzz run
        hits by accident rather than by design), and a chained comparison
        `a < b < c` is here because it is a different lowering from `a < b`:
        the middle operand is read once in one and twice in the other.
        """
        if depth <= 0:
            pool = self.words + self.smalls
            return self.rng.choice(pool) if pool else "1"
        kind = self.rng.choice(["cmp", "cmp", "chain", "logic", "not",
                                "div_cmp", "truth"])
        if kind == "truth":
            pool = self.words + self.smalls
            return f"({self.rng.choice(pool) if pool else '1'})"
        if kind == "cmp":
            op = self.rng.choice(["<", "<=", ">", ">=", "==", "!="])
            pool = self.words + self.smalls
            if pool and self.rng.random() < 0.6:
                return (f"({self.rng.choice(pool)} {op} "
                        f"{self.rng.choice(pool)})")
            return f"({self.int_expr(1)} {op} {self.int_expr(1)})"
        if kind == "chain":
            op = self.rng.choice(["<", "<=", ">", ">=", "==", "!="])
            pool = self.words + self.smalls
            if len(pool) < 3:
                return self.cond(depth - 1)
            a, b, c = (self.rng.choice(pool) for _ in range(3))
            return f"({a} {op} {b} {op} {c})"
        if kind == "logic":
            op = self.rng.choice(["and", "or"])
            return f"({self.cond(depth - 1)} {op} {self.cond(depth - 1)})"
        if kind == "not":
            return f"(not {self.cond(depth - 1)})"
        # A division compared against a literal: the quotient's SIGN is decided
        # by the division, so this is where a truncating division and a
        # flooring one cannot both be right.
        op = self.rng.choice(["<", ">", "==", "!="])
        return (f"(({self.int_expr(1)} & 0xFFFF) {op} "
                f"{self.rng.randint(0, 40)})")

    # ── statements ──
    def new_word(self, indent):
        name = self.declare(self.fresh("w"), "0")
        self.words.append(name)
        self.emit(indent, f"{name} = ({self.word_expr(2)}) & 0xFFFF")
        return name

    def new_small(self, indent):
        name = self.declare(self.fresh("s"), "0")
        self.smalls.append(name)
        self.emit(indent, f"{name} = {self.rng.randint(-32, 32)}")
        return name

    def stmt(self, indent, budget=2):
        kind = self.pick(
            "assign", "arith", "augassign", "shift", "cmp", "logic", "if",
            "while", "for", "div", "pow", "break", "cond_expr", "call",
            "nested_call", "recursion", "arg_expr", "str_assign", "str_print",
            "str_len", "str_cmp", "str_subscript", "list_build", "list_read",
            "list_write", "list_len", "list_in_loop", "obj_new", "field_read",
            "field_cmp", "field_write", "method_call", "method_call_in_arg",
            "div_signed", "mod_signed", "print",
            "dict_build", "dict_read", "dict_write", "dict_len", "dict_in",
            "dict_iter", "dict_comp_count", "tuple_build", "tuple_read",
            "tuple_len", "tuple_iter", "list_append",
            "str_bind", "str_count", "str_find", "str_startswith",
            "str_endswith", "str_lstrip", "str_meth_len",
            "global_build", "global_read", "global_write", "global_bump",
            "global_container", "generic_define", "generic_call",
            "environ_get", "environ_len", "environ_cmp")
        if budget <= 0 and kind in ("if", "while", "for", "call",
                                    "nested_call", "recursion",
                                    "list_in_loop", "dict_iter",
                                    "tuple_iter"):
            # A walk is a LOOP: it is what `budget` exists to bound, since a
            # nest of them is a nest of stack frames rather than a nest of
            # branches. Folding one into an assignment keeps the depth of the
            # generated control flow inside what the corpus means to measure.
            kind = "assign"
        if kind in ("assign", "arith", "cmp", "logic", "cond_expr"):
            self.assign_stmt(indent)
        elif kind == "augassign":
            self.augassign_stmt(indent)
        elif kind == "shift":
            self.shift_stmt(indent)
        elif kind == "div":
            # `words` ONLY, and the dividend is RE-MASKED in the statement
            # before the division. Both halves are load-bearing: a `small` is
            # signed, and a `word` is only non-negative until something writes
            # a negative into it — `w |= s` with s = -22 is one line — so
            # "words are non-negative" is an invariant the generator has to
            # restore rather than one it can assume. Without the mask, a
            # negative dividend under a truncating division is the documented
            # floor/truncate disagreement (CPython answered -1 where both
            # images answered 0) and the fuzzer reports its own invariant.
            if not self.words:
                self.new_word(indent)
            else:
                target = self.rng.choice(self.words)
                self.emit(indent, f"{target} = {target} & 0xFFFF")
                self.emit(indent, f"{target} "
                                  f"{self.rng.choice(['//=', '%='])} "
                                  f"(({self.int_expr(1)} & 0xFF) | 1)")
        elif kind == "pow":
            pool = self.words + self.smalls
            if not pool:
                self.new_word(indent)
            else:
                self.emit(indent, f"{self.rng.choice(pool)} = "
                                  f"{self.rng.choice([2, 3])} ** "
                                  f"{self.rng.randint(0, 5)}")
        elif kind == "if":
            self.emit(indent, f"if {self.cond(2)}:")
            self.block(indent + 1, budget - 1)
            if self.rng.random() < 0.5:
                self.emit(indent, "elif " + self.cond(2) + ":")
                self.block(indent + 1, budget - 1)
            if self.rng.random() < 0.7:
                self.emit(indent, "else:")
                self.block(indent + 1, budget - 1)
        elif kind == "while":
            self.while_loop(indent, budget)
        elif kind == "for":
            self.for_loop(indent, budget)
        elif kind == "break":
            self.terminator(indent)
        elif kind == "call":
            self.call_stmt(indent)
        elif kind == "nested_call":
            self.nested_call_stmt(indent)
        elif kind == "recursion":
            self.recursion_stmt(indent)
        elif kind == "arg_expr":
            self.arg_expr_stmt(indent)
        elif kind in ("str_assign", "str_print", "str_len", "str_cmp",
                      "str_subscript"):
            self.string_stmt(indent, kind)
        elif kind in ("div_signed", "mod_signed"):
            self.signed_div_stmt(indent, kind)
        elif kind == "print":
            self.print_stmt(indent)
        elif kind in ("dict_build", "dict_read", "dict_write", "dict_len",
                      "dict_in", "dict_iter", "dict_comp_count"):
            self.dict_stmt(indent, kind)
        elif kind in ("tuple_build", "tuple_read", "tuple_len", "tuple_iter"):
            self.tuple_stmt(indent, kind)
        elif kind == "list_append":
            self.list_append_stmt(indent)
        elif kind in ("str_bind", "str_count", "str_find", "str_startswith",
                      "str_endswith", "str_lstrip", "str_meth_len"):
            self.strmeth_stmt(indent, kind)
        elif kind in ("global_build", "global_read", "global_write",
                      "global_bump", "global_container"):
            self.global_stmt(indent, kind)
        elif kind in ("generic_define", "generic_call"):
            self.generic_stmt(indent, kind)
        elif kind in ("environ_get", "environ_len", "environ_cmp"):
            self.environ_stmt(indent, kind)
        elif kind in ("obj_new", "field_read", "field_cmp", "field_write",
                      "method_call", "method_call_in_arg"):
            self.object_stmt(indent, kind)
        else:
            self.list_stmt(indent, kind)

    def print_stmt(self, indent):
        """A `print` of one bounded integer, which is how the `signed` mix makes
        a value OBSERVABLE: a `div_signed` whose target is never printed is a
        disagreement nobody sees, and one printed straight into `print` is the
        shape the neutraliser has to be able to take apart."""
        if not (self.words or self.smalls):
            self.new_small(indent)
            return
        self.emit(indent, f"print({self.rng.choice(self.words + self.smalls)})")

    def signed_div_stmt(self, indent, kind):
        """One signed-over-signed division, stored into a `small`.

        The target is a `small` and not a `word` because a word's next write is
        masked to 16 bits: the truncation this generates is a low-bit
        difference, and a mask would hide half of it behind an unsigned
        comparison. `declare` gives the preamble a copy so a read before this
        statement runs is zero on both engines rather than a NameError.
        """
        name = self.declare(self.fresh("s"), "0")
        self.smalls.append(name)
        op = "//" if kind == "div_signed" else "%"
        self.emit(indent, f"{name} = {self.signed_div_expr(op)}")

    def assign_stmt(self, indent):
        """A write to an EXISTING local, or a fresh one.

        A write to a `word` is masked (that is what keeps the value inside the
        range CPython and a word agree on); a write to a `small` is over the
        small family only, so a negative value stays negative and stays small.
        """
        if self.rng.random() < 0.35 or not (self.words or self.smalls):
            if self.rng.random() < 0.5 or not self.smalls:
                self.new_word(indent)
            else:
                self.new_small(indent)
            return
        if self.words and (not self.smalls or self.rng.random() < 0.7):
            target = self.rng.choice(self.words)
            if self.rng.random() < 0.5:
                self.emit(indent, f"{target}: Int64 = "
                                  f"({self.word_expr(2)}) & 0xFFFF")
            else:
                self.emit(indent, f"{target} = ({self.word_expr(2)}) & 0xFFFF")
        else:
            self.emit(indent, f"{self.rng.choice(self.smalls)} = "
                              f"{self.small_expr(1)}")

    def augassign_stmt(self, indent):
        """An augmented write, with the growing operators' RIGHT-HAND side
        bounded so the accumulated value cannot reach 2^63 (see GROWTH_MASK)."""
        if not (self.words or self.smalls):
            self.new_word(indent)
            return
        op = self.rng.choice(["+=", "-=", "*=", "&=", "|=", "^="])
        target = self.rng.choice(self.words + self.smalls)
        if op in ("*=", "+=", "-=") and target in self.smalls:
            # A `small` is only given the non-growing half of the set: `*=` on
            # a signed small is the one combination that can leave the range
            # both engines agree on within a handful of loop iterations.
            op = self.rng.choice(["+=", "-="])
        if op in GROWTH_MASK:
            rhs = (f"(({self.int_expr(0)}) & {GROWTH_MASK[op]})"
                   if op != "<<=" else self.rng.randint(1, 3))
        else:
            rhs = self.int_expr(0)
        self.emit(indent, f"{target} {op} {rhs}")
        if op in GROWTH_MASK:
            # The mask is what bounds the ACCUMULATED value, and it is a second
            # statement because an augmented assignment cannot carry one: a
            # `*=` in a loop body that runs twenty times multiplies by 15 each
            # time, and CPython's integer climbs where a 64-bit word wraps.
            # That is the word-size model, not a miscompile, and a fuzzer that
            # generates it reports its own bug.
            self.emit(indent, f"{target} = {target} & 0xFFFF")

    def shift_stmt(self, indent):
        if not (self.words or self.smalls):
            self.new_word(indent)
            return
        target = self.rng.choice(self.words + self.smalls)
        # A count of at most 7 on a `small` (so a shift cannot run away) and 15
        # on a `word` (whose next write is masked anyway).
        limit = 7 if target in self.smalls else 15
        op = self.rng.choice(["<<=", ">>="])
        self.emit(indent, f"{target} {op} {self.rng.randint(0, limit)}")
        if op == "<<=":
            # A left shift is the one growing statement with no mask on its
            # right-hand side to bound it, and `<<= 9` in a loop body that runs
            # twelve times is 2^108 — CPython's integer climbs and both images
            # wrap.  Measured: a generated `w6 <<= 9` in a nested loop printed
            # a 38-digit number on CPython and 0 on both images.
            self.emit(indent, f"{target} = {target} & 0xFFFF")

    def terminator(self, indent):
        """`break`/`continue`, or a harmless statement when there is no loop.

        A `break` outside a loop is a CPython SyntaxError, so the depth check
        is not tidiness — it is the difference between a program that runs and
        a generator error.
        """
        if self.loop_depth:
            self.emit(indent, self.rng.choice(["break", "continue"]))
        else:
            self.new_small(indent)

    def block(self, indent, budget):
        """One to three statements, and never ZERO of them.

        An empty block is an `IndentationError` in CPython and a syntax error in
        the parser, so a construct that can decline to emit — `define_generic`
        and `define_class` both return None when their budget of definitions is
        spent, and a `global_write` inside a loop-nested branch is the same
        shape — must not be the only statement in a block. `pass` is the
        fallback because it is the one statement that lowers on both backends
        and changes no value (measured: an `if`/`else` of two `pass` statements
        builds and runs on both), and because it cannot perturb the comparison
        the way a synthesised assignment could.
        """
        before = len(self.out)
        for _ in range(self.rng.randint(1, 3)):
            self.stmt(indent, budget)
        if len(self.out) == before:
            self.emit(indent, "pass")

    def while_loop(self, indent, budget):
        """A `while` whose trip count is bounded BY CONSTRUCTION.

        A `while` with an unbounded condition is a generator bug waiting to
        happen: both engines would be killed by their timeouts and the
        comparison would report a TIMEOUT as if it were an answer.  The
        counter is a fresh local incremented in the body, so the loop runs at
        most `n` times whatever the condition says — and the condition is
        still free to be false on the first test, which is the case that
        separates a lowered compare from a lowered branch.
        """
        guard = self.declare(self.fresh("g"), "0")
        limit = self.rng.randint(1, 5)
        self.emit(indent, f"{guard} = 0")
        self.emit(indent, f"while {guard} < {limit} and ({self.cond(2)}):")
        self.emit(indent + 1, f"{guard} = {guard} + 1")
        self.loop_depth += 1
        self.block(indent + 1, budget - 1)
        self.loop_depth -= 1

    def for_loop(self, indent, budget):
        name = self.fresh("i")
        lo = self.rng.randint(0, 3)
        hi = lo + self.rng.randint(1, 4)
        self.emit(indent, f"for {name} in range({lo}, {hi}):")
        self.loop_depth += 1
        self.block(indent + 1, budget - 1)
        if self.rng.random() < 0.3:
            self.emit(indent + 1, self.rng.choice(["break", "continue"]))
        self.loop_depth -= 1

    # ── functions ──
    def define_function(self):
        """A helper at MODULE level with 0..3 int parameters.

        Module level, not nested: a `def` inside `main` is a closure, and a
        closure's environment is a different subject with its own refusals —
        worth fuzzing, and not worth mixing into a run whose findings are all
        supposed to be about plain calls.

        Annotations are left OFF the parameters and the return.  An
        unannotated parameter is this path's DEFAULT_INT_TYPE, which is what
        most of the corpus is written with, and the annotated spelling is
        already pinned by `test_formal_x86_64_parity.py`.
        """
        # A helper's own body may want a helper, and that recursion is
        # unbounded unless something counts: `nested_call` -> define ->
        # body -> `nested_call` -> define -> … reached Python's recursion limit
        # on program 3 of the `calls` mix before this bound existed.  The
        # limit is on the NUMBER of functions, not on the depth, because a
        # chain of callers is the interesting part and a tree of definitions
        # is not.
        if self.defined >= MAX_FUNCS:
            return None
        self.defined += 1
        name = self.fresh("f")
        nargs = self.rng.randint(0, 3)
        params = [self.fresh("p") for _ in range(nargs)]
        # A helper of a CLASS program is generated from the `core` mix: a
        # function body that defines a class would emit it after the classes
        # that call it, which CPython resolves at call time and this path does
        # not have to care about but the text would no longer be one program.
        body = Gen(self.rng, "core" if "classes" in self.mix else self.mix_name)
        body.counter = self.counter
        body.defined = self.defined
        body.decls = []
        body.defs = []
        body.out = []
        body.stmt(1, 1)
        body.stmt(1, 1)
        self.counter = body.counter
        # A helper the BODY defined comes FIRST, or the body's own call to it
        # is a NameError: the child's `defs` list was being dropped on the
        # floor. That is a generator bug which reads exactly like a compiler
        # bug — the CPython reference dies with `NameError: name 'f14' is not
        # defined` while the image would have answered — and it took 200 of 250
        # programs in the `calls` mix before it was found.
        self.defs.extend(body.defs)
        lines = [f"def {name}({', '.join(params)}):"]
        for dname, dval in body.decls:
            lines.append(f"    {dname} = {dval}")
        lines.extend(body.out)
        if body.smalls and self.rng.random() < 0.6:
            # Half the helpers return a SIGNED value and half return a masked
            # word, because a caller cannot know which it got and a lowering
            # that decided the question differently on the two machines would
            # only show up where a signed value is returned through a mask.
            lines.append(f"    return {body.small_expr(1)}")
        else:
            lines.append(f"    return ({body.word_expr(2)}) & 0xFFFF")
        self.defs.extend(lines)
        self.funcs.append((name, params))
        return name, params

    def call_args(self, name, params):
        """The argument list for a call to `name`.

        A RECURSIVE callee's arguments are masked to 3 bits, wherever the call
        sits: `print(rec4(f6()))` recurses once per unit of `f6()`'s return,
        which is a word, so the depth is up to 65535 — a 16 KB stack overflow on
        both images and CPython's recursion limit on the reference. The seed
        mask in `recursion_stmt` bounds the call THIS statement makes; this
        bounds every other statement that happens to call a `rec`.
        """
        return [(f"(({self.int_expr(1)}) & 7)" if name.startswith("rec")
                 else self.int_expr(1)) for _ in params]

    def call_stmt(self, indent):
        if not self.funcs or self.rng.random() < 0.4:
            if self.define_function() is None:
                self.new_word(indent)
                return
        name, params = self.rng.choice(self.funcs)
        args = ", ".join(self.call_args(name, params))
        # `print(<call>)` — the call's RESULT is what is compared, and a call
        # in argument position is where a register/stack ABI disagreement
        # hides.
        self.emit(indent, f"print({name}({args}))")

    def nested_call_stmt(self, indent):
        """A call whose ARGUMENT is itself a call.

        Two frames are live at once, so a caller's argument that lands in the
        outgoing area — or a callee's parameter read out of the wrong slot —
        shows up in the answer instead of passing quietly.
        """
        while len(self.funcs) < 2 and self.define_function() is not None:
            pass
        if len(self.funcs) < 2:
            self.call_stmt(indent)
            return
        outer, outer_params = self.rng.choice(self.funcs)
        inner, inner_params = self.rng.choice(self.funcs)
        if not outer_params:
            self.call_stmt(indent)
            return
        args = self.call_args(outer, outer_params)
        pos = self.rng.randrange(len(outer_params))
        args[pos] = (f"{inner}("
                     f"{', '.join(self.call_args(inner, inner_params))})")
        if outer.startswith("rec"):
            # The argument of a recursive callee is masked AFTER the inner call
            # is spliced in, or `rec4(f6())` — whose argument is a call and so
            # carries no mask of its own — recurses once per unit of `f6()`'s
            # word. `call_args` masks what it generates; this masks what was
            # generated for somebody else.
            args = [f"(({a}) & 7)" for a in args]
        self.emit(indent, f"print({outer}({', '.join(args)}))")

    def arg_expr_stmt(self, indent):
        """A call written into an ARGUMENT of another expression — the shape
        where the inner call's value has to survive the outer's own frame."""
        if not self.funcs and self.define_function() is None:
            self.new_word(indent)
            return
        name, params = self.rng.choice(self.funcs)
        args = ", ".join(self.call_args(name, params))
        self.emit(indent, f"print({name}({args}) + {self.int_expr(1)})")

    def recursion_stmt(self, indent):
        """A tail-recursive helper with a DECREASING counter.

        The depth is bounded by the SEED rather than by a limit in the source,
        so the program terminates in both engines without a guard that would
        hide the thing being tested: a chain of frames, and the register
        save/restore across it.
        """
        name = self.fresh("rec")
        p = self.fresh("n")
        step = self.rng.randint(1, 5)
        self.defs.append(f"def {name}({p}):")
        self.defs.append(f"    if {p} <= 0:")
        self.defs.append(f"        return {self.rng.randint(0, 9)}")
        self.defs.append(f"    return ({name}({p} - 1) + {step}) & 0xFFFF")
        self.funcs.append((name, [p]))
        # The seed is masked to 3 bits, and it has to be: an image's stack is
        # 16 KB (`model.STACK_FLOOR_BUDGET_BYTES`), so a recursion 65535 deep
        # — which is what an unmasked word gives — is a stack overflow on both
        # machines and CPython's own recursion limit besides. Three different
        # failures for one shape, none of them about the lowering.
        self.emit(indent, f"print({name}(({self.int_expr(1)}) & 7))")

    # ── strings and lists ──
    def string_stmt(self, indent, kind):
        if kind == "str_assign" or not self.strings:
            name = self.declare(self.fresh("t"), '"ab"')
            self.strings.append(name)
            self.strings_text[name] = "ab"
            if self.rng.random() < 0.4:
                self.emit(indent, f"{name}: String = {self.str_expr()}")
            else:
                self.emit(indent, f"{name} = {self.str_expr()}")
            return
        if kind == "str_print":
            self.emit(indent, f"print({self.str_expr()})")
            return
        if kind == "str_len":
            # `len` of a string is the one container answer available for a
            # `char *` on this path; every other string method needs a buffer
            # it does not have (`model.string_concat_refusal`).
            self.emit(indent, f"print(len({self.str_expr()}))")
            return
        if kind == "str_subscript":
            # `s[i]` is a BYTE on this path, not a one-character string, so this
            # is generated ON PURPOSE: it is the shape `KNOWN_DIVERGENCES`'
            # `str_subscript` row names, and a corpus that could not produce it
            # could not notice the day the byte came back as a character. Two
            # constraints make the row's neutraliser able to take it apart: the
            # read is spelled `print(<name>[<literal>])` exactly, because that
            # is what `NEUTRALISERS["str_subscript"]` rewrites; and the string
            # it indexes is bound by its OWN statement, unannotated, because
            # that is the binding `features_of` recognises as a string.
            # A list subscript in the same position is CORRECT, so the two are
            # never confused for one another -- `list_read` reads a list and is
            # not part of this mix.
            word = self.rng.choice(STRINGS) or "a"
            name = self.declare(self.fresh("t"), f'"{word}"')
            self.strings.append(name)
            self.strings_text[name] = word
            self.emit(indent, f'{name} = "{word}"')
            self.emit(indent, f"print({name}[{self.rng.randrange(len(word))}])")
            return
        self.emit(indent, f"if {self.str_expr()} == {self.str_expr()}:")
        self.emit(indent + 1, f"print({self.rng.randint(0, 99)})")
        if self.rng.random() < 0.5:
            self.emit(indent, "else:")
            self.emit(indent + 1, f"print({self.rng.randint(0, 99)})")

    def str_expr(self):
        if self.strings and self.rng.random() < 0.6:
            return self.rng.choice(self.strings)
        return repr(self.rng.choice(STRINGS))

    # ── dicts and tuples: the PAIR blob, and the blob beside it ──
    #
    # A dict is `[count][k0][v0][k1][v1]…` and a tuple is `[count][e0][e1]…`,
    # so both are "one thing per count" containers with different strides —
    # which is the whole of what a walk over them has to get right, and the
    # reason they are one family here rather than two.
    #
    # Three disciplines, each of them a measured refusal rather than tidiness:
    #
    #   * a SUBSCRIPT is read into a local and the local is printed.
    #     `print(d["a"])` is refused on both backends — "print() cannot tell
    #     whether SubscriptExpr is a string or a number" — and a family that is
    #     95% refused is a family that finds nothing.
    #   * a STORE may name a key no table wrote, and half the time it does. That
    #     is CPython's INSERT and this path lowers it as one now — reserved pair,
    #     pair written at the count, count bumped — so it is a construct the
    #     corpus can measure rather than a limit it had to route around. The
    #     other half still names a written key, because that is the arm the
    #     SCAN takes and the two must keep disagreeing about nothing.
    #   * a dict with MIXED key kinds claims nothing, so a table here has one
    #     kind of key throughout — a string-keyed table and an integer-keyed
    #     one, never both. See `model.dict_literal_key_kind`'s gate.
    def dict_stmt(self, indent, kind):
        if kind == "dict_build" or not self.dicts:
            self.build_dict()
            return
        var, key_kind, keys = self.rng.choice(self.dicts)
        if kind == "dict_read":
            # Through a local, and the local joins `words` so later statements
            # can compare against it — a subscripted value is an ordinary word
            # once it is in hand.
            tmp = self.declare(self.fresh("w"), "0")
            self.emit(indent, f"{tmp} = {var}[{self.rng.choice(keys)}]")
            self.emit(indent, f"print({tmp})")
            self.words.append(tmp)
            return
        if kind == "dict_write":
            # Half the time a key NO table in this program wrote, because
            # `d[k] = v` for an absent key is CPython's INSERT and this path now
            # lowers it as one: the pair blob is reserved at the literal for the
            # pairs it wrote plus one per store SITE
            # (`formal/model.py`'s `dict_store_capacity`), the miss arm writes
            # the pair at the count and bumps it, and `len(d)` afterwards is one
            # more than it was. Before that it was a key scan that missed and
            # stopped the program having printed nothing, which is why the
            # `containers` mix stayed on the half that worked and reported the
            # limit as a `MISMATCH-*` finding on every program that contained it
            # (`bugs/FORMAL_a_dict_store_of_a_new_key_is_a_run_time_miss.md`,
            # deleted with the fix).
            key = (self.absent_key(key_kind) if self.rng.random() < 0.5
                   else self.rng.choice(keys))
            self.emit(indent, f"{var}[{key}] = {self.rng.randint(0, 40)}")
            return
        if kind == "dict_len":
            self.emit(indent, f"print(len({var}))")
            return
        if kind == "dict_in":
            # A key that is IN the table and a key that is NOT, because the two
            # exits of the scan are the two ways it can be wrong: a scan bounded
            # by the wrong thing never reaches the "not found" exit at all.
            key = (self.rng.choice(keys) if self.rng.random() < 0.6
                   else self.absent_key(key_kind))
            self.emit(indent, f"print(1 if {key} in {var} else 0)")
            return
        if kind == "dict_comp_count":
            # A dict COMPREHENSION: the pair blob built at RUN time, so nothing
            # in the source states its keys. Iteration and `len` are the only
            # readers of it that work — a subscript of one has no initializer to
            # take a kind from, and is refused. The trip COUNT is still a real
            # observation: it is the number of pairs the comprehension built.
            name = self.fresh("D")
            self.emit(indent, f"{name} = {{10 + i: 100 + i "
                              f"for i in range({self.rng.randint(1, 4)})}}")
            self.emit(indent, f"print(len({name}))")
            guard = self.declare(self.fresh("g"), "0")
            self.emit(indent, f"{guard} = 0")
            self.emit(indent, f"for kk in {name}:")
            self.emit(indent + 1, f"{guard} = {guard} + 1")
            self.emit(indent, f"print({guard})")
            # Deliberately NOT in `self.dicts`: it has no literal keys, so every
            # statement that subscripts or tests membership needs one would have
            # nothing to name.  It is observed through `len` and through the
            # trip count, which are the two readers a run-time-built pair blob
            # has.
            return
        # dict_iter: the walk itself, observed two ways.
        target = self.fresh("dk")
        self.emit(indent, f"for {target} in {var}:")
        self.loop_depth += 1
        if key_kind == "str":
            # A string key through `len`, which is the observation that needs
            # the loop target's KIND to be a string: `print(k)` would answer a
            # `char *` formatted as a word, and `len(k)` refuses rather than
            # guessing, so it is the stronger of the two.
            self.emit(indent + 1, f"print(len({target}))")
        else:
            acc = self.declare(self.fresh("w"), "0")
            self.emit(indent + 1, f"{acc} = ({acc} + {target}) & 0xFFFF")
            self.loop_depth -= 1
            self.emit(indent, f"print({acc})")
            self.words.append(acc)
            return
        self.loop_depth -= 1

    def build_dict(self):
        """One dict local, string-keyed or integer-keyed, never mixed.

        The keys are the SPELLINGS the rest of the generator uses to READ,
        test and iterate, and they are collected as such: a table whose key list
        disagrees with its own text is a program that reads a key the table does
        not have, which is a run-time miss on this path and a KeyError in
        CPython — an oracle failure, not a finding. A `dict_write` may still
        store a key from OUTSIDE this list, because that is an insert and both
        engines perform one; see `dict_stmt`.
        """
        name = self.fresh("D")
        key_kind = self.rng.choice(["str", "int"])
        n = self.rng.randint(1, 3)
        keys, values = [], []
        for _ in range(n):
            if key_kind == "str":
                # Distinct, NON-EMPTY literals: a table that spells one key twice
                # states two values for one word and the model's unanimity gate
                # then claims nothing about either (see `REFUSALS` in
                # `test_formal_value_model.py`), and an empty key is a string
                # whose every method answers about nothing.
                key = repr(self.rng.choice(
                    [w for w in STRINGS if w and repr(w) not in keys]
                    or ["ab"]))
            else:
                key = str(self.rng.choice(
                    [v for v in range(1, 40) if str(v) not in keys]))
            keys.append(key)
            values.append(self.rng.randint(0, 40))
        literal = "{" + ", ".join(f"{k}: {v}" for k, v in zip(keys, values)) + "}"
        # Bound ONCE, in the preamble, and never rebound by the body — which is
        # the one asymmetry with `list_stmt`, and it is a MODEL rule rather than
        # a stylistic one. `model._note_dict_init` keeps the dict literal a name
        # was bound to, and a SECOND literal for the same name retracts it: a
        # name with two tables has two homes and a kind read off either is a
        # claim about one instruction. So a program that spelled the same table
        # twice — which is what a preamble copy plus a rebinding statement is —
        # has no answerable key kind, and `for k in d: print(len(k))` inside it
        # is refused as "len() of a value classified as 'int'" about a string.
        # Measured on both architectures; it cost 15 of 40 programs in the first
        # sweep of this mix before the rebinding statement went.
        #
        # The preamble is also where every other binding in this generator goes,
        # so the cost is that a `dict_build` inside a branch is hoisted: the
        # table exists from the first statement of `main` whichever way the
        # branch went. That is the conservative direction for an oracle, and the
        # refusal stays visible in the tally rather than being generated.
        self.declare(name, literal)
        self.dicts.append((name, key_kind, keys))
        return name

    def absent_key(self, key_kind):
        """A key spelling of `key_kind` that no table in this program wrote.

        Half of `dict_in`'s cases, and the half that reaches the scan's
        "not found" exit. The literal is derived from the key SPACE rather than
        drawn at random, because a random string is absent from every table and
        a random integer could be a key of one — which is the same oracle
        mistake as an unguarded divisor.
        """
        if key_kind == "int":
            return str(self.rng.randint(41, 99))
        written = {k for _v, kind, keys in self.dicts if kind == "str"
                   for k in keys}
        pool = [repr(w) for w in STRINGS if w and repr(w) not in written]
        return self.rng.choice(pool or ["'zz'"])

    def tuple_stmt(self, indent, kind):
        if kind == "tuple_build" or not self.tuples:
            name = self.fresh("T")
            n = self.rng.randint(1, 4)
            items = ", ".join(str(self.rng.randint(0, 40)) for _ in range(n))
            # Same LENGTH in the preamble, for the reason `list_build` gives, and
            # a TRAILING COMMA when there is one element: `(10)` is the integer
            # 10 in CPython, not a one-element tuple, so `len(T)` and
            # `for x in T` then fail in the ORACLE — a generator error, not a
            # finding, and one that cost six of forty programs before the comma
            # was here.
            comma = "," if n == 1 else ""
            self.declare(name, "(" + ", ".join(["0"] * n) + comma + ")")
            self.emit(indent, f"{name} = ({items}{comma})")
            self.tuples.append((name, n))
            return
        name, n = self.rng.choice(self.tuples)
        if kind == "tuple_len":
            self.emit(indent, f"print(len({name}))")
            return
        if kind == "tuple_iter":
            target = self.fresh("tk")
            acc = self.declare(self.fresh("w"), "0")
            self.emit(indent, f"for {target} in {name}:")
            self.loop_depth += 1
            self.emit(indent + 1, f"{acc} = ({acc} + {target}) & 0xFFFF")
            self.loop_depth -= 1
            self.emit(indent, f"print({acc})")
            self.words.append(acc)
            return
        idx = self.rng.randrange(n)
        tmp = self.declare(self.fresh("w"), "0")
        self.emit(indent, f"{tmp} = {name}[{idx}]")
        self.emit(indent, f"print({tmp})")
        self.words.append(tmp)

    def list_append_stmt(self, indent):
        """`xs.append(v)` — STRAIGHT LINE only.

        The capacity of a list blob is the number of append SITES in the
        function that built it, and every EXECUTION of a site counts against it,
        so an append inside a loop overflows on the second trip: measured on
        both architectures, `xs = [1]; for i in range(3): xs.append(i)` exits
        with "list.append overflowed 'xs': its capacity is 2". Keeping appends
        out of loops is what keeps this family measuring the append and not the
        overflow diagnostic.
        """
        if self.loop_depth or not self.lists:
            self.list_stmt(indent, "list_build" if not self.lists else "list_len")
            return
        name, n = self.rng.choice(self.lists)
        self.emit(indent, f"{name}.append({self.rng.randint(0, 40)})")

    # ── the lowered string METHODS, which are not string arithmetic ──
    #
    # `count`, `endswith`, `find`, `lstrip` and `startswith` are the five this
    # path lowers (the refusal for a sixth names them), and they are the whole
    # of what a string can DO here: `+` is refused because a string is a bare
    # `char *` and concatenation needs a buffer nothing here has
    # (`model.string_concat_refusal`), and so are `upper`, `replace` and `join`.
    #
    # Two disciplines. Every method here returns either an INTEGER or a BOOL,
    # and a bool is a word on this path: `print(s == "ab")` prints `1` where
    # CPython prints `True` (`model.print_format` says why), so a boolean result
    # is always routed through `1 if … else 0` — the same rule `word_expr`'s
    # `cond` arm follows. And the needle is a LITERAL: `find`/`count` compare
    # raw 64-bit words, so a needle built at run time is a comparison against a
    # word the source never wrote.
    def strmeth_stmt(self, indent, kind):
        if kind == "str_bind" or not self.strings:
            name = self.declare(self.fresh("t"), '"ab"')
            word = self.rng.choice([w for w in STRINGS if w] or ["ab"])
            self.strings.append(name)
            self.strings_text[name] = word
            self.emit(indent, f'{name} = "{word}"')
            return
        recv = self.rng.choice(self.strings)
        if kind == "str_count":
            self.emit(indent, f'print({recv}.count("{self.needle(recv)}"))')
            return
        if kind == "str_find":
            self.emit(indent, f'print({recv}.find("{self.needle(recv)}"))')
            return
        if kind == "str_startswith":
            self.emit(indent, f'print(1 if {recv}.startswith('
                              f'"{self.needle(recv)}") else 0)')
            return
        if kind == "str_endswith":
            self.emit(indent, f'print(1 if {recv}.endswith('
                              f'"{self.needle(recv)}") else 0)')
            return
        if kind == "str_lstrip":
            self.emit(indent, f"print({recv}.lstrip())")
            return
        self.emit(indent, f"print(len({recv}))")

    def needle(self, recv):
        """A substring of the literal `recv` was bound to, or a non-matching one.

        A needle that is present and one that is ABSENT are both generated,
        because `find` answers `-1` for the second and a method that always
        answered a position would pass a corpus that only ever found things.
        The substring is cut from the receiver's own text so the two agree
        about what the string is.
        """
        text = self.strings_text.get(recv) or "ab"
        if self.rng.random() < 0.5:
            i = self.rng.randrange(len(text))
            j = self.rng.randint(i + 1, len(text))
            return text[i:j]
        return self.rng.choice(["zz", "qq", " "])

    # ── module-level state ──
    #
    # A module-level name is a `__DATA` slot rather than a frame slot, and every
    # question about it is a different question from the local one: who owns the
    # slot, how long it lives, and what a function that both reads and writes it
    # sees. Two shapes are generated, because they are two different paths:
    #
    #   * an int global, read into a local and printed (a bare `print(g)` is
    #     refused — "print() cannot tell whether IdentExpr is a string or a
    #     number"), written from `main` through its own `global`, and mutated by
    #     a helper that declares `global`;
    #   * a module-level LIST mutated by index from a helper, which is a store
    #     through a pointer into another frame's blob rather than a store into
    #     one of this frame's slots.
    #
    # The `global` statement is spelled in BOTH engines and is required by
    # CPython: a function that assigns a module-level name without it creates a
    # LOCAL, and the reference would then disagree with an image for a reason
    # that has nothing to do with codegen.
    def global_stmt(self, indent, kind):
        """One module-level binding, and one read/write of it.

        INT globals and CONTAINER globals are kept in separate tables, and the
        reason is the oracle rather than the model: `global_bump` writes
        `(GL + 3) & 0xFFFF` into whatever name it is handed, so a name bound to
        a list is a `TypeError` in CPython — "can only concatenate list (not
        \"int\")" — while the images would have gone on to add a word to a blob's
        header. Every other statement in this generator keeps the two families
        apart for the same reason (`words` versus `lists`), and a global is just
        another binding with a different owner.
        """
        if kind == "global_container" or (kind == "global_build"
                                         and self.rng.random() < 0.3):
            name = self.fresh("GL")
            n = self.rng.randint(1, 3)
            items = ", ".join(str(self.rng.randint(0, 40)) for _ in range(n))
            self.emit_top(f"{name} = [{items}]")
            self.emit(indent, f"print(len({name}))")
            # Written through a helper, which is the store into ANOTHER frame's
            # blob rather than into one of this frame's slots — measured working
            # on both architectures before this family existed.
            if self.rng.random() < 0.6:
                fn = self.fresh("bump")
                param = self.fresh("p")
                self.defs.append(f"def {fn}({param}: Int32) -> Int32:")
                self.defs.append(f"    {name}[{param} % {n}] = "
                                 f"{name}[{param} % {n}] + 1")
                self.defs.append(f"    return {name}[{param} % {n}]")
                self.emit(indent, f"print({fn}({self.rng.randrange(6)}))")
            self.global_containers.append((name, n))
            return
        if kind == "global_build" or not self.globals:
            name = self.fresh("G")
            value = self.rng.randint(0, 60)
            self.globals.append((name, value))
            self.emit_top(f"{name} = {value}")
            return
        name, value = self.rng.choice(self.globals)
        if kind == "global_read":
            # Through a local: `print(g)` is refused on both backends ("print()
            # cannot tell whether IdentExpr is a string or a number"), so the
            # read goes through a slot whose kind the preamble already stated.
            tmp = self.declare(self.fresh("w"), str(value))
            self.emit(indent, f"{tmp} = {name}")
            self.emit(indent, f"print({tmp})")
            self.words.append(tmp)
            return
        if kind == "global_write":
            # The DECLARATION goes at the top of `main`'s body, not here, and
            # that is CPython's rule rather than a style choice: `global x` must
            # precede every use of `x` in the function, so a `global_read` above
            # this line makes the program a SyntaxError — "name 'G7' is used
            # prior to global declaration". `program()` writes them out, in the
            # order the names were first written, above the body.
            if name not in self.main_globals:
                self.main_globals.append(name)
            self.emit(indent, f"{name} = {self.rng.randint(0, 60)}")
            return
        fn = self.fresh("bump")
        param = self.fresh("p")
        self.defs.append(f"def {fn}({param}: Int32) -> Int32:")
        self.defs.append(f"    global {name}")
        self.defs.append(f"    {name} = ({name} + {param}) & 0xFFFF")
        self.defs.append(f"    return {name}")
        self.emit(indent, f"print({fn}({self.rng.randint(0, 9)}))")

    # ── a generic function, monomorphised at the call site ──
    #
    # `def f[T](x: T) …` is PEP 695, so CPython 3.12+ parses and RUNS the same
    # text — which is what makes a generic a differential case here rather than
    # a Mojo-only construct. What the backend does with it is monomorphisation
    # (`formal/monomorph.py`), so the interesting programs are the ones with
    # more than one specialisation of one definition: the same `f` called with
    # an integer and with a string.
    #
    # `T` is NOT used arithmetically, and that is the measured shape rather than
    # a timidity: `T` is a type parameter, so a use of it is classified by what
    # the PARAMETER is, not by what the argument was — measured on both
    # architectures, `len(f("ab", "cde"))` for `def f[T](x: T, y: T) -> T` is
    # refused as "len() of a value classified as 'int', and an integer has no
    # length" and `List[T]` is refused the same way. So the body works on a
    # second, ORDINARY parameter and the type parameter is carried by the
    # signature, which is what makes one definition serve two specialisations.
    def generic_stmt(self, indent, kind):
        if kind == "generic_define" or not self.generics:
            self.define_generic()
            return
        name, arity, ret_string = self.rng.choice(self.generics)
        args = []
        for i in range(arity):
            # Only the TYPE-PARAMETER position may take a string or a list: the
            # body adds the OTHER parameter to an integer, so passing it a blob
            # is `TypeError: unsupported operand type(s) for +: 'int' and
            # 'list'` in CPython — the oracle's own traceback, and half of this
            # mix's corpus before the two positions were told apart.
            args.append(self.generic_arg(i == 0))
        joined = ", ".join(args)
        if ret_string:
            self.emit(indent, f'print({name}({joined}))')
        else:
            tmp = self.declare(self.fresh("w"), "0")
            self.emit(indent, f"{tmp} = {name}({joined})")
            self.emit(indent, f"print({tmp})")
            self.words.append(tmp)

    def define_generic(self):
        """One `def f[T](…)`, and the table of what may be passed for `T`.

        Two return shapes, because they reach different lowering: one returns an
        `Int32` (so the call's value is a word and can be printed, compared and
        accumulated) and one returns a `String` (so the call's value is a
        `char *`, and a fix that lost the specialisation's return type would
        print an address).
        """
        if self.defined >= MAX_FUNCS:
            return None
        self.defined += 1
        name = self.fresh("gen")
        ret_string = self.rng.random() < 0.4
        params = [self.fresh("q") for _ in range(2)]
        # The FIRST parameter is the one whose type is `T`, so the signature
        # carries the type parameter on a real parameter: `def f[T](x: T, y)`.
        # Spelled `(T, y)` — a parameter with no name — CPython raises
        # `TypeError: function definition argument name must be a string`, so
        # the oracle cannot even import it.
        sig = ", ".join([f"{params[0]}: T"] + params[1:])
        lines = [f"def {name}[T]({sig}) -> {'String' if ret_string else 'Int32'}:",
                 f"    acc = {self.rng.randint(1, 9)}",
                 f"    acc = (acc + {params[-1]}) & 0xFFFF"]
        # Two parameters, always, and the reason is the one above in the other
        # direction: the body's arithmetic is on the SECOND parameter, so a one
        # parameter definition would have to do it on the `T` one — where the
        # operand may be a string at a call site, which is `TypeError` in CPython
        # and a refusal here.  The `T` parameter is carried by the SIGNATURE and
        # by the specialisation, which is what monomorphisation acts on.
        if ret_string:
            words = [w for w in STRINGS if w] or ["ab"]
            lines.append(f"    return {self.rng.choice(words)!r}")
        else:
            lines.append("    return acc")
        self.defs.extend(lines)
        self.generics.append((name, len(params), ret_string))
        return name

    def generic_arg(self, is_t_position):
        """An argument for one parameter of a generic.

        `is_t_position` marks the TYPE-PARAMETER position, and only there does
        anything but an integer appear: at least one call passes something else,
        because one specialisation is not monomorphisation and a corpus whose
        every call site agrees cannot tell a monomorphising backend from one
        that ignores the argument's type entirely. A string is the interesting
        second type here — it is a `char *` where an integer is a word, so a
        specialisation that lost its return type prints an ADDRESS.
        """
        if is_t_position and self.rng.random() < 0.45:
            return repr(self.rng.choice([w for w in STRINGS if w] or ["ab"]))
        if self.rng.random() < 0.5:
            return str(self.rng.randint(0, 60))
        if not (self.words or self.smalls):
            return "0"
        return f"(({self.int_expr(0)}) & 0xFFFF)"

    # ── the process environment, against a FIXED one ──
    #
    # `os.getenv(k)` is a call into the C library's environment, so the answer is
    # a fact about the PROCESS rather than about the program — and an inherited
    # environment cannot answer a differential test: a shell adds `_` to a
    # child's block, so the same text under two parents sees two blocks. So the
    # harness runs every engine (and CPython) with `env=FIXED_ENV`
    # (`run`/`cpython_answer`), which is what makes this family reproducible at
    # all, and the generator reads only keys `FIXED_ENV` declares.
    #
    # A key that is ABSENT is not generated: `os.getenv` is `getenv(3)`, which
    # cannot tell an unset variable from an empty one, so CPython prints `None`
    # where this path prints `""`. That is a documented difference
    # (`bugs/FORMAL_os_environ_is_a_view_and_the_sweep_row_behind_it.md`) and
    # generating it would report the model, not a lowering.
    def environ_stmt(self, indent, kind):
        key = self.rng.choice(sorted(FIXED_ENV))
        if kind == "environ_len":
            self.emit(indent, f"print(len(os.getenv({key!r})))")
            return
        if kind == "environ_cmp":
            self.emit(indent, f"print(1 if os.getenv({key!r}) != \"\" else 0)")
            return
        self.emit(indent, f"print(os.getenv({key!r}))")

    def list_stmt(self, indent, kind):
        if kind == "list_build" or not self.lists:
            name = self.fresh("L")
            n = self.rng.randint(1, 4)
            items = ", ".join(str(self.rng.randint(0, 40)) for _ in range(n))
            # The PREAMBLE copy has the same LENGTH as the one the body
            # assigns, because a loop over `range(n)` may run before that
            # assignment does, and a blob of a different length is an
            # IndexError in CPython — a generator error, not a finding.
            self.declare(name, "[" + ", ".join(["0"] * n) + "]")
            self.emit(indent, f"{name} = [{items}]")
            self.lists.append((name, n))
            return
        name, n = self.rng.choice(self.lists)
        idx = self.rng.randrange(n)
        if kind == "list_read":
            self.emit(indent, f"print({name}[{idx}])")
        elif kind == "list_write":
            self.emit(indent, f"{name}[{idx}] = {self.rng.randint(0, 40)}")
        elif kind == "list_len":
            self.emit(indent, f"print(len({name}))")
        elif kind == "list_in_loop":
            i = self.fresh("i")
            self.emit(indent, f"for {i} in range({n}):")
            self.loop_depth += 1
            self.emit(indent + 1, f"{name}[{i}] = {name}[{i}] + 1")
            self.emit(indent + 1, f"print({name}[{i}])")
            self.loop_depth -= 1

    # ── a class, and the frame receiver it makes ──
    #
    # Spelled `class`, not `struct`, and with TWO fields minimum: a one-field
    # struct's receiver IS its field rather than a frame address
    # (`model.struct_fits_one_word` says the same), and an oracle that used one
    # would be measuring that documented shape rather than the one it means to.
    # Fields are ASSIGNED in `__init__` rather than declared, which is the
    # spelling both engines accept without a `var` — and `var` is a keyword
    # CPython cannot parse, so a generator that emitted it would need two
    # different programs and could no longer claim they are the same text.
    def define_class(self):
        if len(self.classes) >= MAX_CLASSES:
            return None
        name = self.fresh("C")
        fields = [self.fresh("f") for _ in range(self.rng.randint(2, 3))]
        lines = [f"class {name}:", "    def __init__(self):"]
        for f in fields:
            lines.append(f"        self.{f} = {self.rng.randint(-30, 60)}")
        methods = []
        for _ in range(self.rng.randint(1, 3)):
            mname = self.fresh("m")
            params = [self.fresh("q") for _ in range(self.rng.randint(0, 2))]
            sig = ", ".join(["self"] + params)
            body = Gen(self.rng, "core")
            body.counter = self.counter
            body.defined = MAX_FUNCS        # a method body defines no functions
            body.decls = []
            body.defs = []
            body.out = []
            body.smalls = []                # fields are read through `self.`
            body.words = [f"self.{f}" for f in fields]
            for _ in range(self.rng.randint(1, 3)):
                field = self.rng.choice(fields)
                if self.rng.random() < 0.6:
                    # A method MUTATES a field through `self.x = …`, which is
                    # the store into the callee's OWN frame slot — the path a
                    # value receiver never takes, and the one a two-field
                    # struct exists to reach.
                    body.emit(0, f"self.{field} = (self.{field} "
                                 f"{self.rng.choice(['+', '-'])} "
                                 f"{self.rng.randint(1, 9)}) & 0xFFFF")
                else:
                    # Through a declared local, for the same reason main's
                    # `field_read` does it: `print(self.f)` is the refused
                    # spelling on both backends.
                    tmp = body.declare(body.fresh("w"), "0")
                    body.emit(0, f"{tmp} = (self.{field}) & 0xFFFF")
                    body.emit(0, f"print({tmp})")
            if params:
                body.emit(0, f"return (self.{self.rng.choice(fields)} "
                             f"{self.rng.choice(['+', '-'])} "
                             f"{params[0]}) & 0xFFFF")
            else:
                body.emit(0, f"return (self.{self.rng.choice(fields)}) "
                             f"& 0xFFFF")
            self.counter = body.counter
            lines.append(f"    def {mname}({sig}):")
            lines.extend("        " + line for line in body.out)
            methods.append((mname, params))
        self.defs.extend(lines)
        self.classes.append((name, fields, methods))
        return name, fields, methods

    def object_stmt(self, indent, kind):
        if not self.classes:
            self.define_class()
        if kind == "obj_new" or not self.objs:
            name, fields, methods = self.rng.choice(self.classes)
            var = self.fresh("o")
            # `declare` with the CONSTRUCTOR call as the initialiser, so the
            # preamble and the first assignment agree — an object the program
            # only sometimes constructs is an AttributeError in CPython and
            # whatever the slot held on this path.
            self.declare(var, f"{name}()")
            self.emit(indent, f"{var} = {name}()")
            self.objs.append((var, name, fields, methods))
            return
        var, _cname, fields, methods = self.rng.choice(self.objs)
        if kind == "field_read":
            # Through a WORD, never straight into `print`.  `print(obj.field)`
            # is refused on both architectures with "print() cannot tell
            # whether MemberExpr is a string or a number" — 284 of 300
            # generated class programs were that one refusal — and a refusal
            # is not a finding, so a family that is 95% refused is a family
            # that finds nothing.  Reading the field into a typed word and
            # printing that is the same read through the path the model can
            # answer.
            field = self.rng.choice(fields)
            tmp = self.declare(self.fresh("w"), "0")
            self.emit(indent, f"{tmp} = ({var}.{field}) & 0xFFFF")
            self.emit(indent, f"print({tmp})")
            self.words.append(tmp)
            return
        if kind == "field_cmp":
            # A field in a CONDITION, which is the other way a field is read:
            # no `print` kind question, and the compare is decided against the
            # field's own type.
            field = self.rng.choice(fields)
            self.emit(indent, f"if {var}.{field} == "
                              f"{self.int_expr(1)}:")
            self.emit(indent + 1, f"print({self.rng.randint(0, 9)})")
            if self.rng.random() < 0.5:
                self.emit(indent, "else:")
                self.emit(indent + 1, f"print({self.rng.randint(0, 9)})")
            return
        if kind == "field_write":
            self.emit(indent, f"{var}.{self.rng.choice(fields)} = "
                              f"({self.word_expr(1)}) & 0xFFFF")
            return
        if not methods:
            tmp = self.declare(self.fresh("w"), "0")
            self.emit(indent, f"{tmp} = ({var}.{self.rng.choice(fields)}) "
                              f"& 0xFFFF")
            self.emit(indent, f"print({tmp})")
            self.words.append(tmp)
            return
        mname, params = self.rng.choice(methods)
        if kind == "method_call_in_arg" and params and self.objs:
            # A method call in ARGUMENT position: two frame receivers live at
            # once, which is the shape that finds a parameter read out of the
            # wrong slot.
            inner_var, _c, _f, inner_methods = self.rng.choice(self.objs)
            # Same ARITY, or the outer call is made with the wrong number of
            # arguments — a TypeError on the reference and nothing a compiler
            # could be blamed for.
            arity = [m for m in inner_methods if len(m[1]) == len(params)]
            if arity:
                om, oparams = self.rng.choice(arity)
                # A LIST of expressions, joined here: `call_args` returns one,
                # and formatting that list straight into the call spelled it
                # `m11(['expr'])` — which CPython answers with a TypeError on
                # `int - list` and which no compiler would ever be blamed for.
                args = ", ".join(self.call_args(om, oparams))
            else:
                args = ", ".join(f"{var}.{self.rng.choice(fields)}"
                                 for _ in params)
        else:
            args = ", ".join(self.int_expr(1) for _ in params)
        self.emit(indent, f"print({var}.{mname}({args}))")

    # ── the program ──
    def program(self):
        if "calls" in self.mix:
            for _ in range(self.rng.randint(1, 3)):
                self.define_function()
        if "classes" in self.mix:
            for _ in range(self.rng.randint(1, 2)):
                self.define_class()
        # The two families that need a module-level binding BEFORE `main` runs,
        # emitted here rather than by the body: a dict comprehension and a
        # `import` the body will use, and a first global so `global_read` has
        # something to read even in a program whose statements are all in
        # branches.  `environ` needs the import whether or not the body reached
        # its own `environ_get`, because an unused import is cheaper than a
        # program that references `os` with nothing in scope.
        if "global_build" in self.mix:
            self.global_stmt(0, "global_build")
        if "environ_get" in self.mix:
            # `self.mix` is the set of construct FAMILIES, so the mix NAME is
            # not in it — `environ_get` is, and asking for the name here found
            # out the hard way: every generated program referenced `os` with
            # nothing in scope, and CPython answered `NameError` on all of them.
            self.emit_top("import os")
        saved, self.out = self.out, []
        for _ in range(self.rng.randint(2, 4)):
            self.new_small(1)
        for _ in range(self.rng.randint(1, 3)):
            self.new_word(1)
        for _ in range(self.rng.randint(self.stmt_lo, self.stmt_hi)):
            self.stmt(1, 2)
        # A trailing observation of EVERY value, printed a few at a time: a
        # variadic call keeps 8 arguments in registers on arm64 and 6 on
        # x86-64, so a print with several operands is the cheapest probe there
        # is of the two conventions disagreeing.  Five is under both.
        watched = self.words + self.smalls
        for i in range(0, len(watched), 5):
            chunk = watched[i:i + 5]
            if chunk:
                self.emit(1, "print(" + ", ".join(chunk) + ")")
        body, self.out = self.out, saved
        # `defs` before `toplevel`: a helper's body may use a global the body
        # binds, and CPython resolves a global at RUN time, so either order
        # works there — but the backends fold a module-level name to a slot when
        # they see the binding, and keeping the definitions first is the order
        # the stdlib itself is written in.
        lines = list(self.defs) + list(self.toplevel)
        lines.append("def main() -> Int32:")
        # Above the preamble: a `global` declaration has to precede every use of
        # the name in the function, and the preamble's initialisers are uses of
        # the same locals the body goes on to assign, so the two orders that
        # could collide are both real and only this one is legal.
        for gname in self.main_globals:
            lines.append(f"    global {gname}")
        for dname, dval in self.decls:
            lines.append(f"    {dname} = {dval}")
        lines.extend(body)
        lines.append("    return 0")
        return "\n".join(lines) + "\n"


def make_program(seed, index, mix="core", stmts=(5, 12)):
    """Program `index` of `seed` — a pure function of the two.

    Which is what makes a run reproducible, resumable, and order-independent:
    the work can be spread over `--jobs` workers and still be re-run exactly,
    and a program reported by index can be regenerated without the file that
    produced it.
    """
    return Gen(random.Random(f"{seed}:{index}:{mix}"), mix, stmts).program()

# ── the run ────────────────────────────────────────────────────────────────

def check_one(index, args, tmpdir, lock=None):
    text = make_program(args.seed, index, args.mix, args.stmts)
    name = f"p{index}"
    ref, err = cpython_answer(text, tmpdir, name)
    results = {}
    if isinstance(ref, tuple) and ref and ref[0] == "error":
        return {"index": index, "verdict": "generator-error",
                "detail": ref[1], "text": text}
    if not has_oracle(ref):
        # A CPython TIMEOUT is not a generator error — it is the oracle being
        # unable to finish a program that is about to be handed to two
        # compilers, and it gets its own verdict rather than a crash or a
        # `generator-error` that names a traceback it never produced.
        return {"index": index, "verdict": "CPYTHON-TIMEOUT", "detail": err,
                "text": text}
    want_exit, want_out = ref
    for backend in args.backends:
        results[backend] = run_on(backend, text, tmpdir, name)
    finding = classify(results, want_exit, want_out, args)
    rec = {"index": index, "verdict": finding, "text": text,
           "want": {"exit": want_exit, "stdout": want_out}, "results": results}
    if finding.startswith(("MISMATCH", "ARM64-DIVERGES", "CODEGEN-CRASH",
                           "REFUSAL-DIVERGES")):
        # Attribution runs on the MINIMISED program, never on this one: a blame
        # over a forty-statement program names every construct it contains,
        # which is the "there is a known bug in here too" reading this exists to
        # avoid. The minimised text is kept on the record so the reproducer on
        # disk is the one the verdict is about.
        small, _steps = shrink(text, args)
        if small == text:
            # The shrink found nothing to remove, which is common when the
            # disagreement is a single statement. Nothing to do about it — the
            # verdict is still attributed over the program itself, and the
            # record says so rather than claiming a reduction that did not
            # happen.
            small = text
        rec["reduced_from"] = len(text)
        rec["reduced_to"] = len(small)
        rec["text"] = small
        got = blame(small, args, tmpdir, name)
        if got:
            rec["verdict"] = "KNOWN:" + "+".join(got)
            rec["blame"] = list(got)
    if args.save_all or rec["verdict"] != "match":
        d = os.path.join(args.work, "programs")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{name}.mojo"), "w") as f:
            f.write(rec["text"])
    return rec


def classify(results, want_exit, want_out, args):
    """The one question: did every engine that produced an ANSWER produce the
    SAME answer?  A verdict names the engines that disagreed, because a
    finding that does not say which image is wrong is a re-run."""
    def answer(backend):
        r = results.get(backend) or {}
        return (r["rc"], r.get("stdout")) if r.get("verdict") == "ok" else None

    x86 = answer("x86_64")
    arm = answer("arm64")
    if x86 is not None and (x86[0] != want_exit or x86[1] != want_out):
        return "MISMATCH-X86"
    if arm is not None and (arm[0] != want_exit or arm[1] != want_out):
        return "MISMATCH-ARM64"
    if x86 is not None and arm is not None and x86 != arm:
        return "ARM64-DIVERGES"
    if any(r.get("verdict") == "crash" for r in results.values()):
        return "CODEGEN-CRASH"
    if any(r.get("verdict") == "timeout" for r in results.values()):
        return "TIMEOUT"
    if any(r.get("verdict") == "trapped" for r in results.values()):
        return "trapped"
    # A REFUSAL is not a finding — a construct with no representation is
    # CORRECTLY refused, and a fuzzer that counted those as bugs would spend
    # its whole budget re-discovering `bugs/FORMAL_known_limits.md`.  That is
    # true of a refusal EVERY engine agrees on, and false of one engine
    # refusing what another lowered: then the construct IS representable, one
    # machine says so by running the program, and this one declines it.  That
    # is the divergence `test_formal_x86_64_parity.py` exists to keep closed,
    # and reporting it as a plain `refusal` is a hole in this tool rather than
    # a fact about the backend: the corpus keeps generating the program, it
    # keeps saving it, and it counts as a clean run.
    #
    # Measured on the tree this landed on: `containers` seeds 1000-1499, where
    # arm64 built and answered a program x86-64 refused with "main: '_cb0' has
    # no home: the register allocator collected no home for it, so the emitter
    # and the allocation walk disagree about this function's locals".
    refusals = [b for b, r in results.items() if r.get("verdict") == "refusal"]
    answered = [b for b in results if answer(b) is not None]
    if refusals and answered:
        return "REFUSAL-DIVERGES-" + "+".join(
            "X86" if b == "x86_64" else "ARM" for b in refusals)
    if refusals:
        return "refusal"
    return "match"


def shorten(text, limit=160):
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 3] + "..."


def report(rec, args):
    v = rec["verdict"]
    if v == "match":
        return None
    if v == "refusal":
        return f"  refusal  #{rec['index']}"
    if v.startswith("REFUSAL-DIVERGES"):
        lines = [f"  {v}  #{rec['index']}",
                 "      one architecture refused what the other lowered"]
        if "reduced_from" in rec:
            lines.append(f"      reduced {rec['reduced_from']} -> "
                         f"{rec['reduced_to']} bytes")
        for backend, r in rec["results"].items():
            if r["verdict"] == "ok":
                lines.append(f"      {backend:<7} exit={r['rc']} "
                             f"{shorten(r['stdout'])!r}")
            else:
                lines.append(f"      {backend:<7} {r['verdict']}: "
                             f"{shorten(r['diag'], 220)}")
        return "\n".join(lines)
    if v == "CPYTHON-TIMEOUT":
        return (f"  CPYTHON-TIMEOUT  #{rec['index']}  (the oracle did not "
                f"finish; nothing was compared)")
    if v == "trapped":
        return f"  trapped #{rec['index']}  (the stack-floor guard; CPython ran "
    lines = [f"  {v}  #{rec['index']}"]
    if v == "generator-error":
        lines.append(f"      CPython rejected the generated program: "
                     f"{shorten(rec['detail'])}")
        return "\n".join(lines)
    if v.startswith("KNOWN:"):
        # The construct(s), the document that owns each, and the two answers —
        # so the row says WHY it was set aside rather than merely that it was.
        why = "; ".join(KNOWN_DIVERGENCES.get(part, part)
                        for part in v[len("KNOWN:"):].split("+"))
        lines.append(f"      attributed to {why}")
        if "reduced_from" in rec:
            lines.append(f"      reduced {rec['reduced_from']} -> "
                         f"{rec['reduced_to']} bytes")
    want = rec["want"]
    lines.append(f"      want  exit={want['exit']} {shorten(want['stdout'])!r}")
    for backend, r in rec["results"].items():
        if r["verdict"] == "ok":
            lines.append(f"      {backend:<7} exit={r['rc']} "
                         f"{shorten(r['stdout'])!r}")
        else:
            lines.append(f"      {backend:<7} {r['verdict']}: "
                         f"{shorten(r['diag'], 220)}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-n", "--count", type=int, default=50,
                    help="how many programs to generate")
    ap.add_argument("-s", "--seed", type=str, default="formal-fuzz",
                    help="the seed; program i is a pure function of (seed, i)")
    ap.add_argument("--start", type=int, default=0,
                    help="first program index (for resuming or extending a run)")
    ap.add_argument("--seeds", default=None, metavar="A-B",
                    help="a contiguous program-index range; exactly "
                         "--start A --count B-A+1, spelled this way because a "
                         "sweep is nearly always a range and the recorded "
                         "commands in bugs/ say so")
    ap.add_argument("--arch", choices=("x86_64", "arm64"), default=None,
                    help="one architecture, which is --backends with one entry; "
                         "it also sets --min-kind to match")
    ap.add_argument("--print-program", type=int, default=None, metavar="INDEX",
                    help="print one generated program's source and exit")
    ap.add_argument("-j", "--jobs", type=int, default=4)
    ap.add_argument("--backends", default="x86_64,arm64",
                    help="comma list; both, to check the two images against "
                         "each other as well as against CPython")
    ap.add_argument("--mix", default="core", choices=sorted(MIXES))
    ap.add_argument("--stmts", nargs=2, type=int, metavar=("LO", "HI"),
                    default=(5, 12),
                    help="how many statements main's body carries; a wide "
                         "range is how the register-spill paths get reached")
    ap.add_argument("--work", default=os.path.join(HERE, ".tmp", "formal_fuzz"))
    ap.add_argument("--save-all", action="store_true",
                    help="write every program to --work, not only findings")
    ap.add_argument("--minimize", metavar="PROG",
                    help="shrink one program to a minimal reproducer and print it")
    ap.add_argument("--min-kind", default=None, choices=["x86", "arm", "any"],
                    help="which disagreement --minimize and the attribution "
                         "must preserve; default follows --backends, and is "
                         "`any` as soon as more than one is in play")
    ap.add_argument("--max-min-steps", type=int, default=400)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    if args.arch:
        # `--arch` is the one-backend statement of `--backends`, and it wins
        # over it rather than adding to it: the two say the same thing in
        # different vocabularies and a run that honoured both would build two
        # architectures while the screen claimed one.
        args.backends = [args.arch]
    else:
        args.backends = [b.strip() for b in args.backends.split(",")
                         if b.strip()]
    if not args.backends:
        print("ERROR: --backends named no architecture", file=sys.stderr)
        return 2
    for b in args.backends:
        if b not in ("x86_64", "arm64"):
            print(f"ERROR: unknown backend {b!r}", file=sys.stderr)
            return 2
    if args.seeds:
        lo, _, hi = args.seeds.partition("-")
        try:
            args.start, last = int(lo), int(hi)
        except ValueError:
            print(f"ERROR: --seeds wants A-B, not {args.seeds!r}",
                  file=sys.stderr)
            return 2
        if last < args.start:
            print(f"ERROR: --seeds {args.seeds!r} runs backwards",
                  file=sys.stderr)
            return 2
        args.count = last - args.start + 1
    args.min_kind = resolve_min_kind(args)
    if sys.version_info < (3, 10):
        print("ERROR: the formal backend needs python3 >= 3.10 "
              "(export PATH=/opt/homebrew/bin:$PATH first)",
              file=sys.stderr)
        return 2
    os.makedirs(args.work, exist_ok=True)

    if args.print_program is not None:
        sys.stdout.write(make_program(args.seed, args.print_program, args.mix,
                                      tuple(args.stmts)))
        return 0

    if args.minimize:
        with open(args.minimize) as f:
            text = f.read()
        return minimize(text, args)

    started = time.time()
    counts = {}
    blamed = {}
    findings = []
    tmpdir = tempfile.mkdtemp(prefix="formalfuzz.", dir=args.work)
    try:
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            recs = list(pool.map(
                lambda i: check_one(i, args, tmpdir),
                range(args.start, args.start + args.count)))
        for rec in recs:
            counts[rec["verdict"]] = counts.get(rec["verdict"], 0) + 1
            line = report(rec, args)
            if line and rec["verdict"] != "refusal":
                print(line, flush=True)
            elif line and not args.quiet:
                print(line, flush=True)
            if rec["verdict"].startswith("KNOWN:"):
                key = rec["blame"][0] if len(rec["blame"]) == 1 else "+".join(
                    rec["blame"])
                blamed[key] = blamed.get(key, 0) + 1
            elif rec["verdict"].startswith(("MISMATCH", "ARM64-DIVERGES",
                                            "CODEGEN-CRASH", "generator",
                                            "REFUSAL-DIVERGES")):
                findings.append(rec)
    finally:
        subprocess.run(["rm", "-rf", tmpdir])

    with open(os.path.join(args.work, "findings.json"), "w") as f:
        json.dump({"args": vars(args), "counts": counts,
                   "findings": [{k: v for k, v in r.items() if k != "text"}
                                for r in findings],
                   "programs": {str(r["index"]): r["text"]
                                for r in findings}},
              f, indent=1)
    elapsed = time.time() - started
    print(f"\nformal_fuzz seed={args.seed} mix={args.mix} "
          f"backends={','.join(args.backends)} "
          f"programs={args.count} in {elapsed:.1f}s "
          f"({args.count / max(elapsed, 0.01):.1f}/s, jobs={args.jobs})")
    # The three that are a MEASUREMENT are always printed, zero included: "0
    # trapped" is a fact about the corpus and "no line" is not, and a reader
    # (or a regression suite) cannot tell a run that saw no traps from a run
    # whose summary never mentioned traps. Everything else is printed only when
    # it happened, because its absence IS the good news.
    for v in ALWAYS_REPORTED:
        print(f"  {v:<18} {counts.get(v, 0)}")
    for v, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        if v not in ALWAYS_REPORTED:
            print(f"  {v:<18} {n}")
    if blamed:
        print("  known constructs blamed (the MINIMAL set that explains each):")
        for key, n in sorted(blamed.items(), key=lambda kv: -kv[1]):
            why = "; ".join(KNOWN_DIVERGENCES.get(part, part)
                            for part in key.split("+"))
            print(f"    {n:5d}  {key}: {why}")
    print(f"findings written to {args.work}/findings.json "
          f"({len(findings)} program{'s' if len(findings) != 1 else ''})")
    return 1 if findings else 0


# ── attribution ─────────────────────────────────────────────────────────────
#
# A disagreement is only a FINDING if it is not a construct already known to
# disagree with CPython. Two things have to be true for the known list to be
# usable at all: the reduction has to have got the program down to a couple of
# lines, and the tool has to be able to tell whether this disagreement IS that
# known bug or something else. The second is done by NEUTRALISING the suspect
# construct in place and asking whether the program then agrees — see `blame`.

# A name bound to a string literal. Needed because `x[0]` is CORRECT for a list
# and wrong for a string, and the two differ only in what `x` was bound to — a
# pattern that matched every subscript would blame the known string divergence on
# every list subscript in the corpus, which is the over-attribution this whole
# mechanism exists to avoid. The annotation spelling (`t: String = "ab"`) is
# recognised too, because `str_assign` emits it half the time and a table that
# only read the bare one would attribute nothing at all.
STR_ASSIGN = re.compile(r"^ *(\w+) *(?::[^=\n]*)?= *\"", re.M)


def features_of(source):
    """The known-divergent constructs the text uses."""
    strs = STR_ASSIGN.findall(source)
    out = set()
    for name, pats in FEATURE_PATTERNS.items():
        if name == "str_subscript":
            if any(re.search(r"\b%s\s*\[" % re.escape(n), source) for n in strs):
                out.add(name)
            continue
        if any(re.search(p, source) for p in pats):
            out.add(name)
    return out


def neutralise(source, feature):
    """`source` with `feature`'s construct swapped out, or None if it has none."""
    edits = NEUTRALISERS.get(feature)
    if not edits:
        return None
    out = source
    before = out
    for pat, repl in edits:
        out = re.sub(pat, repl, out, flags=re.M)
    if out == before:
        return None
    return out


def _neutralise_all(source, features):
    """`source` with every one of `features` swapped out, or None if nothing
    changed — which means the construct is present by pattern but not in a form
    the neutraliser can reach, and the honest answer is that it cannot be
    blamed rather than that it was ruled out."""
    out = source
    for name in features:
        if out is None:
            return None
        out = neutralise(out, name)
    return out


def _every_engine_agrees(text, args, tmpdir, name):
    """Whether CPython and EVERY backend in `--backends` print the same thing.

    "Every" and not "one": a neutralised candidate that one machine answers and
    another refuses is not evidence in either direction, and a known construct
    that only one backend has is still a known construct only if BOTH stop
    disagreeing once it is taken out. A candidate that refuses, times out or
    will not run under CPython returns False — the direction the module
    docstring calls erring towards one extra report rather than one hidden bug.
    """
    ref, _err = cpython_answer(text, tmpdir, name)
    if not has_oracle(ref):
        return False
    want_exit, want_out = ref
    for backend in args.backends:
        r = run_on(backend, text, tmpdir, name)
        if r["verdict"] != "ok":
            return False
        if r["rc"] != want_exit or r["stdout"] != want_out:
            return False
    return True


def blame(text, args, tmpdir, name="blame"):
    """The smallest SET of known constructs that explains this disagreement.

    Neutralise them all, rebuild, and ask: does the program now agree with
    CPython? If it does, shrink the set one construct at a time and keep the
    result, so what the summary prints is a MINIMAL explanation rather than
    "every known bug in the file" — a program with two truncating divisions in
    it is explained by the divisions, and saying so is more useful than naming
    both plus a third thing that had nothing to do with it.

    The shrink is what keeps this from being a dismissal. If removing all of
    them does NOT make the program agree, nothing is blamed and the
    disagreement stays a finding; and the minimal set is what gets printed, so a
    reader can see what was set aside and check the reproducer, which is written
    either way.

    Returns a tuple of feature names, or `None` — which is the only answer that
    makes the run's exit status non-zero.
    """
    present = sorted(features_of(text))
    if not present:
        return None

    def _agrees(features):
        cand = _neutralise_all(text, features)
        if not cand or not cand.strip():
            return False
        return _every_engine_agrees(cand, args, tmpdir, name)

    if not _agrees(present):
        # Neutralising them ALL together can also be what breaks it while any
        # ONE of them is the whole cause — two divisions in a program, one of
        # which is the only thing wrong. So each is tried on its own before the
        # program is called unexplained.
        for one in present:
            if _agrees([one]):
                return (one,)
        return None
    kept = present
    for name_ in list(kept):
        smaller = [f for f in kept if f != name_]
        if smaller and _agrees(smaller):
            kept = smaller
    return tuple(kept)


# ── minimisation ───────────────────────────────────────────────────────────
#
# Delta debugging over STATEMENTS, then over sub-expressions.  A miscompile
# report is only useful if it is small: the first thing a reader does with a
# 40-statement program is delete statements by hand, and the whole point of
# reporting it automatically is that the answer is already smaller than the
# question.  The predicate is the SAME comparison the sweep made — CPython
# against the image — so a shrunk program still demonstrates the disagreement.

# Which backend's disagreement `--minimize` and the attribution shrink must
# keep. `None` means "follow `--backends`", and resolving it that way is not a
# convenience: a two-backend run whose shrink only watched x86-64 would shrink
# an `ARM64-DIVERGES` reproducer into one that no longer diverges, and report a
# reproducer for the wrong machine.
MIN_KINDS = {"x86_64": "x86", "arm64": "arm"}

# The verdicts the summary prints whether or not they happened, and the rest are
# printed only when they do.
#: Printed even when zero, because "0 CPYTHON-TIMEOUT" is a fact about the
#: corpus and "no line" is not — the same reason `match`/`trapped`/`refusal`
#: are here.  A CPython timeout is the ORACLE's verdict and says nothing about
#: the backends, which is why it is neither a finding nor counted as one.
ALWAYS_REPORTED = ("match", "trapped", "refusal", "CPYTHON-TIMEOUT")


def resolve_min_kind(args):
    """`args.min_kind`, resolved against `--backends` when it was not said."""
    if args.min_kind:
        return args.min_kind
    if len(args.backends) == 1:
        return MIN_KINDS.get(args.backends[0], "any")
    return "any"


def _still_fails(text, args, want=None):
    """Whether `text` still demonstrates the disagreement being minimised.

    The predicate is the SAME comparison the run made — CPython against the
    image — so a shrunk program still demonstrates the disagreement rather than
    merely still building.

    `want` is the ORIGINAL program's `{backend: (verdict, diagnostic)}` map, and
    it is what makes a REFUSAL divergence reducible at all: without it the
    minimiser has nothing to preserve a refusal against, and reports that a
    program which still fails "does not fail here any more".
    """
    # A candidate that does not PARSE cannot demonstrate anything, and it can
    # reach here: `_statement_spans` builds a span from a block's opening line
    # to each line inside it, so deleting the first statement of a body deletes
    # the `def` line with it and leaves an indented file.  Measured on the
    # refusal-divergence path — the reproducer came back as two unindented-
    # context lines with no `def`, because a file that does not compile is
    # "refused" by both the parser and the compiler and so satisfied the
    # predicate.  The oracle cannot run such a program either, which is why the
    # existing mismatch path rejected it by accident rather than by a rule.
    try:
        compile(PY_DRIVER.replace("@PROGRAM@", text).replace("@TAG@", _RC_TAG),
                "<shrink candidate>", "exec")
    except SyntaxError:
        return False
    name = "min"
    kind = resolve_min_kind(args)
    standalone = []
    verdicts = {}
    diags = {}
    with tempfile.TemporaryDirectory(dir=args.work) as td:
        ref, _err = cpython_answer(text, td, name)
        have_oracle = has_oracle(ref)
        want_exit, want_out = ref if have_oracle else (None, None)
        for backend in args.backends:
            if kind == "x86" and backend != "x86_64":
                continue
            if kind == "arm" and backend != "arm64":
                continue
            r = run_on(backend, text, td, name)
            verdicts[backend] = r["verdict"]
            diags[backend] = (r.get("diag") or "")[:60]
            if (have_oracle and r["verdict"] == "ok"
                    and (r["rc"] != want_exit or r["stdout"] != want_out)):
                return True
            # A CRASH is a finding in its own right, so it is preserved even
            # where the oracle comparison cannot see it (the image died, so it
            # produced no answer).  A TRAP is not: exit 2 is the stack-floor
            # guard's verdict about the PROGRAM — a runaway recursion — which
            # the module docstring calls a documented limit rather than a
            # silent wrong answer, and which is a SMALLER program than any real
            # disagreement. Preserving it let the shrink walk out of a
            # `s[i]`-is-a-byte disagreement and into `def f(): print(f())`,
            # which is 26 bytes, traps on both images and raises
            # `RecursionError` on CPython — and then reported the byte
            # divergence as unexplained, because the reproducer no longer
            # contained it. Measured on the `strings` mix, seeds 4000-4011:
            # 7 of 9 KNOWN-attributed programs were right and 2 came back
            # `MISMATCH-X86` with a recursion for a reproducer.
            if r["verdict"] == "crash":
                standalone.append(r["verdict"])
        # A REFUSAL DIVERGENCE has to survive the shrink as itself: one engine
        # refused while another answered.  Preserved here rather than in
        # `classify` because a minimiser that only knows about wrong ANSWERS
        # reduces this reproducer to nothing — measured, and it reports "the
        # program does not fail here any more" about a program that still fails,
        # because the failure is a refusal rather than an answer.
        #
        # With ONE backend there is nothing to diverge from, so the refusal is
        # the whole predicate.  That is only sound because `--minimize` is
        # driven by hand: the caller is the one who ran both architectures and
        # saw one of them answer, and `--min-kind x86` says which refusal to
        # preserve.  A program both backends refuse minimises happily under
        # this rule, which costs a `--minimize` invocation and nothing else.
        # …preserved as ITSELF: the same backend must still refuse, with the
        # same sentence, while another still answers.  "Still refuses" alone is
        # NOT enough, and measured: with a single backend under `--min-kind x86`
        # any refusal satisfies it, so the shrink walked out of `_cb0 has no
        # home` and into "D7 is read before anything in this function stores
        # it" — a real refusal, about a real program, and a different bug.
        # Sixty characters of the diagnostic is the key: long enough to name
        # the construct, short enough that a line number or a temp's suffix
        # moving does not lose the reproducer.
        want_refusals = {b: d for b, (v, d) in (want or {}).items()
                         if v == "refusal"}
        if want_refusals:
            still = all(verdicts.get(b) == "refusal"
                        and diags.get(b, "")[:40] == d[:40]
                        for b, d in want_refusals.items() if b in verdicts)
            return bool(still) and ("ok" in verdicts.values()
                                    or len(want_refusals) == len(verdicts))
        if "refusal" in verdicts.values() and (
                len(verdicts) == 1 or "ok" in verdicts.values()):
            return True
    # No oracle at all — a program CPython itself refuses to run, which is what
    # a recursion past ITS limit looks like. There is then nothing to compare
    # against, so a mismatch cannot be the predicate; but `--min-kind any` still
    # preserves a CRASH, because that verdict is about the IMAGE rather than
    # about a difference between two of them. A generated corpus never reaches
    # here (a recursion that deep is refused before it is built); this is the
    # path a hand-written reproducer takes.
    return kind == "any" and bool(standalone)


def _statement_spans(text):
    """(start, end) line spans of every statement in the file, outermost first.

    A span is a line that opens a block plus the block it owns, so deleting one
    removes a whole `if` with its arms — which is the unit a reader deletes,
    and the unit whose deletion can change a program's meaning (a `continue`
    that stops skipping the rest of a loop body).
    """
    lines = text.split("\n")
    opens = []
    spans = []
    for i, line in enumerate(lines):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        while opens and opens[-1][1] > indent:
            opens.pop()
        if opens:
            spans.append((opens[-1][0], i))
        opens.append((i, indent))
    return lines, spans


def _verdict_map(text, args):
    """`{backend: (verdict, diagnostic)}` for `text`, over `args.backends`.

    Measured once per shrink rather than once per candidate: every candidate
    already runs every backend, and this is the ONE extra run that tells the
    refusal predicate which refusal it is preserving.
    """
    out = {}
    with tempfile.TemporaryDirectory(dir=args.work) as td:
        for backend in args.backends:
            r = run_on(backend, text, td, "want")
            out[backend] = (r["verdict"], (r.get("diag") or "")[:60])
    return out


def shrink(text, args):
    """The smallest sub-program that still fails; `(text, steps)`.

    Separate from `minimize` because `check_one` needs the RESULT, not a print
    — the attribution reads a minimised program, because a blame over a
    forty-statement program names every known construct it contains. One
    implementation of the shrink, two callers, which is the only reason there is
    not a second copy of it in the attribution path.
    """
    steps = 0
    want = _verdict_map(text, args)
    # 1. statements, largest first (a big `if` goes before the one line inside
    #    it, so the shrink converges on the OUTER construct when both work)
    changed = True
    while changed and steps < args.max_min_steps:
        changed = False
        lines, spans = _statement_spans(text)
        for start, end in sorted(spans, key=lambda s: s[1] - s[0],
                                 reverse=True):
            if steps >= args.max_min_steps:
                break
            cand = "\n".join(lines[:start] + lines[end + 1:])
            if not cand.strip():
                continue
            steps += 1
            if _still_fails(cand, args, want):
                text = cand
                changed = True
                break
    # 2. sub-expressions: replace each parenthesised group with its operands
    while steps < args.max_min_steps:
        m = re.search(r"\(([^()]*)\)", text)
        if not m:
            break
        inner = m.group(1)
        alts = [a for a in re.split(r"[-+*/%&|^<>]=?|\band\b|\bor\b", inner)
                if a.strip()]
        if len(alts) < 2:
            break
        for a in alts:
            steps += 1
            cand = text[:m.start()] + a.strip() + text[m.end():]
            if _still_fails(cand, args, want):
                text = cand
                break
        else:
            break
    # 3. literals: shrink the numbers that are left.
    #
    # Re-found after every ACCEPTED substitution, never iterated from one list
    # of offsets captured up front. That is not tidiness, it is a correctness
    # requirement for the whole tool: an accepted substitution changes the
    # text, so a stale offset points at a different literal — and one that now
    # sits past the end APPENDS its replacement after the program, so the
    # candidate is `...\n    return 0\n1`. Both engines then answer that by
    # printing nothing, `_still_fails` is happy, and the minimiser has
    # manufactured the very disagreement it was asked to shrink. Measured on
    # `--mix strings`, program 11: the shrunk reproducer carried a trailing `1`
    # and its image printed nothing at all, which is what left that program's
    # attribution unexplained.
    changed = True
    while changed and steps < args.max_min_steps:
        changed = False
        for m in list(re.finditer(r"(?<![\w.])(-?\d+)", text)):
            if steps >= args.max_min_steps:
                break
            v = m.group(1)
            for repl in ("0", "1", "-1"):
                if repl == v:
                    continue
                steps += 1
                cand = text[:m.start()] + repl + text[m.end():]
                if _still_fails(cand, args, want):
                    text = cand
                    changed = True
                    break
            if changed:
                break
    return text, steps


def minimize(text, args):
    """`--minimize PROG`: shrink one program and print the reproducer."""
    if not _still_fails(text, args):
        print("the program does not fail here any more — nothing to minimize",
              file=sys.stderr)
        return 2
    text, steps = shrink(text, args)
    print("--- minimized reproducer "
          f"({steps} candidate tests, --min-kind={resolve_min_kind(args)}) ---")
    print(text)
    print("--- end ---")
    with open(os.path.join(args.work, "minimized.mojo"), "w") as f:
        f.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())