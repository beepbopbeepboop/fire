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
                       the CONSTRUCT the message names, and audited — see "THE
                       REFUSAL AUDIT" below, which is the part that decides
                       whether the message is true.
  CODEGEN-INTERNAL    the backend reported an internal inconsistency of its own
                       (its label table, its allocation walk) where a reader
                       would be told about the PROGRAM.  A finding, and its own
                       verdict: a refusal is a claim about the source, so
                       counting an internal error as one reports a compiler bug
                       as a documented limit.  Measured: x86-64 refused every
                       image containing an `int(s, base)` with "internal: label
                       'main_ip1_end' is defined twice, at 0x… and at 0x…".
  codegen-crash        the compiler raised something that is not a refusal
                       (a traceback, or a signal).  THIS is a finding: a
                       backend that dies on a source it merely cannot model is
                       a crash the sweep classifies separately, and it is never
                       cached, so it costs a build on every sweep until it is
                       gone.

THE REFUSAL AUDIT — is the message true, and does it name the construct?
------------------------------------------------------------------------
A refusal is a claim about the program: "this construct has no representation
here, and here it is".  Three ways that claim can be worthless, all of which
used to reach a sweep's tally as a clean `refusal`:

  * the diagnostic is about the COMPILER rather than the program (`internal: …`)
    — its own verdict above, not a refusal's;
  * it names something the PROGRAM DOES NOT CONTAIN, which sends the reader
    looking for a construct that is not there — `REFUSAL-UNNAMED`, a finding;
  * the two machines DISAGREE about it, whether one declines what the other
    lowered (`REFUSAL-DIVERGES`) or both decline it in different words — the
    second shape is new, and it is the one that hid the `int(s, base)` pair.

One of those is not a disagreement about the program. The two container budgets
are 8x apart — `formal/model.py::CONTAINER_BUDGET` is the smaller, and is the
one a program has to fit to build on both — so a literal between the two
ceilings is refused by one machine and lowered by the other BY DESIGN. That
keeps the `REFUSAL-DIVERGES` prefix and its per-architecture suffixes, and adds
`-FRAME-BUDGET` so a tally can subtract it.

A fourth, for the families whose message makes a claim ABOUT CPython — "CPython
raises UnboundLocalError for that program" is a promise the interpreter can be
asked to keep — is `REFUSAL-FALSE`, and the check is in `REFUSAL_CLAIMS`.

What the audit CANNOT do is decide whether a construct really is outside the
modelled subset: that is a property of `formal/model.py`, not of the message.
So every family with no checkable claim is reported as `no-predicate` and
COUNTED in the summary, never silently absent — a sweep that says
`refusal audit: true=13, unnamed=0, false=0, no-predicate=0` and one that
printed no audit line at all must not look the same.

THE KNOWN DIVERGENCES, AND WHY GENERATING THEM IS THE POINT
-----------------------------------------------------------
One construct in this subset is known to disagree with CPython today, and it is
in `KNOWN_DIVERGENCES` with the document that owns it.  The generator emits it
DELIBERATELY — `--mix strings` reads `s[i]`, which is a byte rather than a
one-character string.  A generator that avoided it would be quieter, and quiet
here means blind: a construct the corpus cannot produce cannot be noticed the
day it is fixed, which is precisely the moment the tool exists for.

The floor-versus-truncate pair (`//` and `%` over two signed operands) was in
that table until the day both backends floored them, and was DELETED in that
commit — see `KNOWN_DIVERGENCES`' own note, because a row naming a construct
that is now RIGHT forgives the next disagreement that happens to contain it.
The corpus keeps generating the operators regardless, and what replaced the row
is `MIX_MUST_GENERATE`, which says the weaker and still-load-bearing thing:
**the mix must still produce a signed-over-signed division**.  That is a
property of the GENERATOR and stays true while the backend is right; it is also
the only thing that notices the day a change to the signedness decision stops
emitting one, at which point this corpus would report the same clean tally
either way.

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

The nine the fuzz-3 sweep added, one per construct the corpus could not produce
at all, each PROBED ON BOTH ARCHITECTURES before it was written down (so a mix
measures a lowering and not a refusal it would spend its budget re-deriving):
`loopelse` (`while`/`for` with an `else` arm, which is the shape where the arm
depends on whether a `break` did), `closures` (a `def` inside `main`, called
again after the captured local is REASSIGNED, which is what separates a cell
from a copy), `argshape` (default parameters and keyword arguments at the call
site), `slicing` (`xs[a:b]`, `xs[a:b:c]`), `unpack` (`a, b, c = t`, whose
targets hold ELEMENTS — the one family that found a backend defect rather than
confirming one), `bignum` (word-boundary literals under `& | ^ >> <<`, every
result masked back into 16 bits so the word-size MODEL is not what is being
measured), `chains` (`a < b < c` as a condition and as a value), `strfmt` (the
five lowered string methods as a formatting surface) and `fstrings` (an
interpolated literal alone in its mix, because it is a documented REFUSAL and a
mix that expected answers could only report refusals — see
`test_formal_fuzz.py`'s `MIXES_NOT_LOWERED`).

Every one of the last five was added because a DIFFERENTIAL SWEEP found
something in it, and the ledger is `bugs/FORMAL_fuzz_ledger.md`: `containers`
because `for k in d` read `k0, v0, k1` on BOTH architectures (exit 0) and
because a membership test's bound was its own needle on x86-64;
`generics`/`globals`/`strmeth`/`environ` because they were newly lowered and
had no coverage at all, which is the state in which a bug is cheapest to
introduce and most expensive to find.

The same rule produced the nine above, and two of them paid for themselves the
way `containers` did: `unpack` found a construct the corpus could not produce
that was REFUSED on both architectures (`a, b, c = t` bound every target to the
CONTAINER's kind, so `print(a)` said the source did not say what the operand
holds), and `fstrings` found one that BUILDS and LIES (an interpolated literal
printed its own source spelling, exit 0, on both). The other six are coverage
with nothing found yet, which is the state a row is worth having in.

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
    it. Both are limits with a diagnostic rather than defects, and the append
    one was measured as such. The dict half is no longer a limit: `d[k] = v`
    for an absent key is CPython's INSERT, the pair blob is reserved at the
    literal for the pairs it wrote plus one per store SITE
    (`formal/model.py`'s `dict_store_capacity`), and the two stores the
    `containers` mix generates here are therefore programs the corpus
    measures.
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

# `tools/formal_sweep_parity.py`'s architecture-label fold, imported rather than
# copied: it is the normaliser the sweep's parity tool settled by measurement
# (its own comment says 12 of 542 rows differed for no reason other than a
# machine name), and the two tools answer the same question about the same two
# messages. A missing sibling is a loud ImportError on purpose — a silent
# fallback would be a second normaliser, which is the thing being avoided.
import formal_sweep_parity as _SWEEP_PARITY  # noqa: E402

#: The head of `formal/model.py::frame_blob_refusal`'s message — the ONE
#: sentence both backends emit for "this container does not fit in the frame".
#: It is spelled here rather than imported because it is a STRING, and a string
#: that lives in the tool is exactly what `formal_sweep_causes.py`'s samples are
#: cut from, for the same reason: `test_refusal_taxonomy.py` fails if the model's
#: wording moves out from under a copy. The check that keeps these two copies
#: honest is `test_formal_fuzz.py::test_the_frame_budget_head_is_the_models_own`.
FRAME_BLOB_REFUSAL_HEAD = "does not fit in the frame: it needs "

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRE = os.path.join(HERE, "fire.py")

# The compiler's own frame budgets, so this corpus is sized by the tree rather
# than by a number typed here: `formal/model.py::CONTAINER_BUDGET` is the
# smaller of the two and the one a program has to fit to build on both machines.
# `HERE` is the repository root, which is not on `sys.path` when this file is
# run as `tools/formal_fuzz.py`, so the root goes on it the way it does for the
# other tools in this directory that read the backend.
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from formal import model as M  # noqa: E402

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
# table becomes a list of things nobody looks for.
#
# **`floordiv` and `modulo` were deleted in the commit that fixed
# `//`-floors-and-`%`-takes-the-sign-of-the-divisor** (both backends, with
# `model.division_floors` as the one decision and `fdiv64`/`frem64` as the model
# the source is checked against). Leaving them would have been worse than
# useless: a disagreement the corpus still produces is neutralised by a
# construct that is no longer wrong, so a REAL floor bug found later would be
# explained away by a fixed one. What replaces them is not a row but
# `MIX_MUST_GENERATE` below: `--mix signed` must still GENERATE a
# signed-over-signed division, which `test_formal_fuzz.py::_check_generation`
# asserts over its own index range, so deleting the rows without the mix would
# pass here and measure nothing.
#
# `str_subscript` is the row still standing, and it is the shape of the claim
# the other two carried: `bugs/FORMAL_string_value_model.md` owns it.
KNOWN_DIVERGENCES = {
    "str_subscript": (
        "`s[i]` is a byte, not a one-character string (bugs/"
        "FORMAL_string_value_model.md)"),
}

# The constructs that make a feature marker true. Checked against the minimised
# program's text; a marker is only blamed when removing every occurrence of one
# of its spellings makes the program agree.
FEATURE_PATTERNS = {
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
# has nothing to do with the disagreement and nothing is learned.
NEUTRALISERS = {
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

def build(src, out, backend, timeout=BUILD_TIMEOUT, test_input=None):
    """Compile `src` for `backend`; (rc, diagnostic).

    The diagnostic is stderr or stdout, whichever carries text — a refusal is
    printed where the build found it, and the two are not the same stream on
    every failure.

    `test_input` is the formal path's `-n`, and it is `None` here by default so
    that this corpus keeps measuring the images the CLI builds by default.  It
    is a parameter because the OTHER caller of this function — the proof-layer
    fuzzer `tools/formal_proof_fuzz.py` — measures programs whose entry takes an
    argument, and the input is BAKED INTO THE IMAGE by the startup stub
    (`formal/build.py`'s `test_input`), so a corpus that could not vary it would
    be a corpus measuring one input and calling it a program.  Passing it here
    rather than writing a second build command in that file is what keeps the
    refusal/crash classification below the single place that decides it.
    """
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove",
           f"--backend={backend}", "-o", out]
    if test_input is not None:
        cmd += ["-n", str(test_input)]
    cmd.append(src)
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


def cpython_answer(text, tmpdir, name, args=""):
    """(exit, stdout) for `text` + `main(args)`, run by the interpreter here.

    `args` is the argument list the driver calls `main` with, spliced into the
    driver verbatim so a caller can pass one value (`"5"`), several (`"5, 7"`)
    or nothing at all (the default, which is this corpus: every program it
    generates is `main()`).  It exists for `tools/formal_proof_fuzz.py`, whose
    programs take the input the image has baked into it — a second CPython
    driver there would be a second oracle, which is the one thing this tool's
    docstring refuses to have.
    """
    py = os.path.join(tmpdir, name + ".ref.py")
    driver = PY_DRIVER.replace("_rc = main()", "_rc = main(%s)" % args)
    with open(py, "w") as f:
        f.write(driver.replace("@PROGRAM@", text).replace("@TAG@", _RC_TAG))
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


# ── the refusal audit ───────────────────────────────────────────────────────
#
# A refusal is a CLAIM about the program: "this construct has no representation
# on this path, and here is which one".  Three things can make the claim
# worthless, and every one of them used to reach a sweep's tally as a clean
# `refusal` — the verdict that means "correctly refused, not a finding":
#
#   * THE DIAGNOSTIC IS NOT ABOUT THE PROGRAM.  Both assemblers raise
#     `CodegenError` for their own internal consistency checks, so an
#     `internal: …` sentence is a claim about the compiler wearing a refusal's
#     clothes.  `run_on` gives it its own verdict now (`codegen-internal`,
#     above); this is where the sentence stops being one.
#   * THE MESSAGE NAMES SOMETHING THE PROGRAM DOES NOT CONTAIN.  A reader who
#     is sent looking for a construct that is not there has been handed a worse
#     outcome than a refusal: a wrong answer about their own source.  The check
#     below is mechanical — the diagnostic has to quote a token that is in the
#     program, or name an AST node — and it is deliberately the WEAKEST possible
#     reading of "names the construct", because a stronger one is a judgement
#     about prose and this file refuses to make judgements it cannot re-run.
#   * THE TWO MACHINES DISAGREE ABOUT IT.  `classify` compares two-sided
#     refusals now, with architecture labels folded, so "one machine refuses the
#     construct" and "the other machine refuses it in different words" are both
#     findings instead of one clean run.
#
# WHAT THE AUDIT CANNOT DECIDE, said here rather than left to be discovered:
# whether a construct really is outside the modelled subset.  That is a
# property of `formal/model.py`, not of the message, and the only mechanical
# witnesses available here are the two architectures (which is the third item
# above) and CPython.  So a family with no CPython-checkable claim is reported
# as `no-predicate` and COUNTED, never silently absent: a sweep whose refusals
# were all unaudited says so in its summary, which is the difference between "the
# refusals were true" and "nothing looked at the refusals".

#: A build diagnostic that is the COMPILER talking about itself.  Both
#: assemblers use this one prefix, from their own duplicate-label check, and it
#: is matched here rather than spelled per backend because there is one prefix to
#: match: a second spelling would be a second thing to keep in step.
INTERNAL_DIAG_RE = re.compile(r"\binternal: ")

#: What a refusal quotes: `'x'`, `` `x` `` and `"x"`.  The three because the
#: messages use all three — `read_before_store_refusal` writes `'y'`, the string
#: method refusals write `` `s.upper()` ``, and `printf_format_refusal` writes a
#: format string in double quotes.
QUOTED_RE = re.compile(r"'([^'\n]{1,160})'|`([^`\n]{1,160})`|\"([^\"\n]{1,160})\"")

#: An AST node name, which is how a refusal names a construct the source spells
#: with punctuation: "print() cannot tell whether `SliceExpr` is a string or a
#: number" is about a slice, and `xs[1:3]` does not contain the word.
AST_NODE_RE = re.compile(r"\b([A-Z]\w*(?:Expr|Stmt))\b")

#: An identifier, for the check that a quoted token really is IN the program.
IDENT_RE = re.compile(r"[A-Za-z_]\w*")

#: The words of a message that are the CONSTRUCT rather than the prose around
#: it — every identifier in the first sentence is a candidate, which is how
#: `d.keys() is a method call on a value` is read as naming `d.keys()` while
#: `the image would bind 1 symbol(s)` is not read as naming `symbol`.
STOPWORDS = frozenset("""
a an the this that these those it its is are was were be been being of to in on at
by for from with without as and or not no if then than so such which what when where
while do does did doing have has had having here there one two both either neither
can cannot could may might must shall should will would you your they them their
he she we us i me my mine ours yours theirs but because about into over under again
""".split())


def _message_head(diag, limit=400):
    """The first sentence or two of a diagnostic — where the construct is named.

    Bounded rather than exact: a message that puts its construct in the third
    sentence must not be failed for that, and one that puts it in the first must
    not depend on where the prose happens to break.  Two sentences and a cap is
    the measure; the whole message is scanned too where that is cheap (see
    `audit_refusal`), so this only decides which tokens get priority.
    """
    flat = " ".join(diag.split())
    cut = 0
    for _ in range(2):
        # Not `:` — a refusal's site prefix is a colon (`main: 'y' is read at
        # line 2 …`, `line 5: a bare `except:` …`) and breaking there left the
        # head as the bare word `main:`, which is the FUNCTION and not the
        # construct.  The prefix is stripped by `refusal_construct` instead.
        m = re.search(r"(?<=[.!?])\s", flat[cut:])
        if not m:
            break
        cut += m.end()
    return flat[:cut or limit]


#: The site prefix a refusal opens with — `main: `, `line 29: `,
#: `p7.mojo: ` — stripped before the construct is read off, because it names
#: WHERE and the construct is WHAT. `\s?\d*` is what allows `line 29: ` to be
#: one prefix and not two tokens, and a bare word pattern that lacked it left
#: five of `limits`' ten programs filed under the construct `line`.
SITE_PREFIX_RE = re.compile(r"^(?:[A-Za-z_][\w./]*\s?\d*: )+")

#: Construct NAMES that no token of a program can match, because the message
#: names the construct as a PROSE noun phrase and the program contains no such
#: word: "a list literal does not fit in the frame: it needs 17608 bytes" names
#: the construct `list` and the program is 2100 bare integers. Measured on the
#: twelve shapes `limits` produces; small on purpose, because every word here
#: WEAKENS the check — a word that appears in a message that names nothing lets
#: that message pass — so it holds only words this backend's own refusals use to
#: name a construct.
CONSTRUCT_WORDS = (
    "list", "dict", "tuple", "string", "slice", "comprehension", "lambda",
    "closure", "pointer", "float", "double", "struct", "descriptor",
    "generator", "frame", "container", "blob",
)
# …a TUPLE and not a set, because the answer is the word that appears EARLIEST in
# the message and a set has no order: "a list literal does not fit in the frame"
# has to be filed under `list` and not under whichever of the two the hash table
# happened to yield first, because a construct mix whose rows move between runs
# is a mix nobody can compare against the last one.


def _is_construct_token(tok):
    """Whether one whitespace-separated token of a message names a construct.

    Quoted always (`read_before_store_refusal` writes `'y'` and means it),
    a punctuation run usually (`s.upper()`, `print()`, `'+'`, `frame:`), and a
    capitalised AST node name always (`SliceExpr`). A bare lower-case word is
    never one — those are the prose between the construct and the explanation,
    and treating them as candidates is what made every message name something.
    """
    quoted = len(tok) >= 2 and tok[0] in "'`\"" and tok[-1] == tok[0]
    core = tok.strip("`'\"")
    if not core:
        return False
    if quoted:
        return True
    if AST_NODE_RE.fullmatch(core):
        return True
    return any(ch in core for ch in "()[]{}.,:+-*/%<>=!&|^~@#'")


def refusal_construct(diag, text=None):
    """The construct a refusal names, for the tally; `unnamed` when it names none.

    This is the CONSTRUCT MIX a sweep produces, which the docstring above has
    always promised ("counted by message so the construct mix stays visible") and
    which `classify` did not do: every refusal landed in one bucket, so a sweep
    of two thousand programs could not say whether it had met one limit thirteen
    times or thirteen limits once.

    `text` is the program, and it is what decides: a candidate that is not in the
    program is not this program's construct, so the search continues and
    `unnamed` is the honest answer when none of them is. That is the same rule
    `audit_refusal` applies and for the same reason — "the image would bind 1
    symbol(s) that nothing provides: sum" has four plausible leading tokens and
    none of them is the call in the source, because the message never says what
    `sum` is.
    """
    body = SITE_PREFIX_RE.sub("", _message_head(diag), count=1)
    for cand in body.split():
        if not _is_construct_token(cand):
            continue
        core = cand.strip("`'\"")
        # A CALL spelling matches its callee: the message's leading token for a
        # slice refused by `print()` is `print()`, and no program contains that
        # substring — it contains `print(xs[1:3])`. Without the `()` half of the
        # test the message's own construct fell through to the AST node further
        # along the sentence and the blob refusal's to the word `string`.
        if text is None or core in text or core.rstrip("()") in text:
            return core[:40]
    hits = [(body.find(word), word) for word in CONSTRUCT_WORDS
            if re.search(r"\b%s\b" % word, body)]
    return min(hits)[1] if hits else "unnamed"


def _identifiers_in(text):
    """Every identifier the program contains.

    Identifiers ONLY, and not operators: an operator arrives inside a quoted
    token that has no identifier word in it at all (`'+'`, `'<<='`), and that
    case is decided by asking whether the quoted spelling is a SUBSTRING of the
    program — which is the right test for punctuation, because the program
    contains `s + "cd"` and never contains the token `+` as a word. A set of
    punctuation runs was here first and produced `b"`, `d"` and `n(` alongside
    the operators, which is three more things to be wrong about and no case the
    substring test does not already cover.
    """
    return set(IDENT_RE.findall(text))


def audit_refusal(text, diag, cpython=None):
    """Is this refusal honest? `(verdict, detail)`; see the block comment above.

    Four verdicts, and the point of naming the unhelpful ones is that a sweep
    must be able to say how much of its refusal surface it actually checked:

      ``true``          the message names a construct of this program, and every
                        CPython-checkable claim in it holds.
      ``unnamed``       it names nothing in the program — a finding: the reader
                        is sent looking for a construct that is not there.
      ``false``         it names a construct and a CPython-checkable claim in it
                        is refuted by running the program — a finding.
      ``no-predicate``  it names its construct and no claim in it is checkable
                        here.  Counted, printed, never a finding: this verdict
                        is what keeps the other three honest.

    `cpython` is `cpython_answer`'s three-way answer, passed in rather than run
    again so a caller that already has it pays for it once — and so the audit has
    no way to demand an oracle it did not get.
    """
    # ── 1. does the message name something the program contains? ──
    prog = _identifiers_in(text)
    named = []
    for m in QUOTED_RE.finditer(diag):
        quoted = m.group(1) or m.group(2) or m.group(3) or ""
        for word in IDENT_RE.findall(quoted):
            if word in prog and word.lower() not in STOPWORDS:
                named.append(word)
                break
        else:
            stripped = quoted.strip()
            if stripped and stripped in text:
                named.append(stripped)
                break
    for m in AST_NODE_RE.finditer(diag):
        named.append(m.group(1))
    # The head's LEADING TOKEN, which is where half of these messages put the
    # construct and where they put it unquoted: `s.upper()` is a method call on a
    # value, `d.keys()` is a method call on a value, and neither is written with
    # quotes anywhere in the sentence. Matched against the program as a SPELLING
    # rather than word by word, because a dotted call is one token to a reader
    # and several to a word matcher.
    #
    # And it is what the link audit does NOT have: "sum.mojo: the image would
    # bind 1 symbol(s) … : sum" leads with a FILE NAME and mentions the symbol
    # unquoted in the middle, so nothing in it is a construct of the program. That
    # is the measured shape of a refusal which names no construct at all, and it
    # is why the rule is a spelling against the program rather than "does the
    # message contain an identifier".
    lead = refusal_construct(diag, text)
    if lead != "unnamed":
        named.append(lead)
    if not named:
        return "unnamed", ("the diagnostic quotes nothing this program "
                           "contains, so it does not name the construct: "
                           + shorten(diag, 160))

    # ── 2. the claims that CPython can refute ──
    for pattern, check in REFUSAL_CLAIMS:
        claim = pattern.search(diag)
        if not claim:
            continue
        if cpython is None:
            return "no-predicate", (f"{claim.group(0)!r} makes a claim about "
                                    f"CPython and the oracle was not run")
        ok, why = check(text, cpython)
        if not ok:
            return "false", f"{claim.group(0)!r}: {why}"
    return "true", ", ".join(dict.fromkeys(named))


#: Claims a refusal makes ABOUT CPython, and the check that refutes one.  Each
#: row is (pattern, check) and the check is `(text, cpython_answer) -> (ok, why)`,
#: because "the message promises something and the reference disagrees" is the
#: only kind of falsehood this tool can decide on its own.
#:
#: `read_before_store_refusal` is the row that matters, because its message
#: spells the promise out — "CPython raises UnboundLocalError for that program
#: (NameError at module level)" — and a message that names the exception it
#: cannot raise is checkable against the interpreter this tool already runs.
#: `cpython_answer` answers `("error", stderr)` when CPython rejects the text, so
#: the check reads the exception out of the oracle's own traceback.
#:
#: BOTH classes are accepted rather than the one the first sentence names,
#: because the message itself says which is which: demanding `UnboundLocalError`
#: of a MODULE-LEVEL read would report a true statement as a lie, and an audit
#: that cries wolf on the module-level case teaches a reader to ignore it.
#:
#: The corpus cannot generate this family (every local is declared up front, so
#: a read before its store is a `generator-error` rather than a program), so the
#: row is reached from `--audit` on a saved program rather than from a sweep of
#: `core`.  It is here because the row is TRUE and the alternative is an audit
#: that silently skips the one claim it can check.
def _cpython_raises_any(ref, classes):
    """(`error`, stderr) from `cpython_answer`, and whether it raised one of them."""
    if not (isinstance(ref, tuple) and ref and ref[0] == "error"):
        return None, f"CPython answers this program with {ref!r}, and raises nothing"
    return any(c in ref[1] for c in classes), ref[1].strip().splitlines()[-1][:120]


REFUSAL_CLAIMS = [
    (re.compile(r"CPython raises (UnboundLocalError|NameError)"),
     lambda text, ref: _cpython_raises_any(ref, ("UnboundLocalError", "NameError"))),
]


def fold_arch(text):
    """Architecture labels folded to `<arch>`, from the sweep's own normaliser.

    Delegated rather than re-spelled: `tools/formal_sweep_parity.py` measured
    these rules against real logs (12 of 542 rows differed for no reason other
    than a machine name), and a second copy here is a second thing to keep in
    step — the same argument as `build()` being the one place the
    refusal/crash classification lives for both fuzzers.
    """
    return _SWEEP_PARITY.fold_arch(text)


def run_on(backend, text, tmpdir, name):
    """Everything ONE backend says about `text`: built? ran? printed what?

    Returns a dict whose `verdict` is one of `ok`, `refusal`, `codegen-internal`,
    `crash`, `timeout`; `ok` carries the exit status and stdout that the
    comparison needs, and every verdict carries enough text to reproduce the
    report line.
    """
    src = os.path.join(tmpdir, f"{name}.mojo")
    out = os.path.join(tmpdir, f"{name}.{backend}")
    with open(src, "w") as f:
        f.write(text)
    rc, diag = build(src, out, backend)
    if rc != 0:
        # THREE shapes of build failure, and only the first two are the same
        # thing.  A crash is a traceback or a signal; a refusal is a sentence;
        # and an INTERNAL sentence is neither, because it is a claim about the
        # COMPILER rather than about the program.
        #
        # `internal:` is the two assemblers' own consistency check speaking
        # (`formal/arm64.py`'s and `formal/x86_64.py`'s `Assembler.label`: a
        # label name defined twice), and it is the exact shape a fuzzer must not
        # file as a refusal.  Measured: x86-64 refused every image containing an
        # `int(s, base)` with "internal: label 'main_ip1_end' is defined twice,
        # at 0x… and at 0x…", which named a label and named no construct, and
        # `classify` counted it as a correctly-refused construct — so a sweep
        # reported a clean `refusal` over a parser-lowering bug that only x86-64
        # had.  "A message that is false about the file is worse than no
        # message" (`bugs/FORMAL_known_limits.md`) applies twice over here: once
        # because the message was false about the FILE, and again because the
        # tally said the file was outside the modelled subset.
        crashed = ("Traceback (most recent call last)" in diag
                   or "codegen-crash" in diag
                   or rc < 0
                   or rc in (134, 139, 136, 132, 133, 135, 137))
        if crashed:
            verdict = "crash"
        elif INTERNAL_DIAG_RE.search(diag):
            verdict = "codegen-internal"
        else:
            verdict = "refusal"
        # The WHOLE diagnostic, not its tail.  A refusal names its construct in
        # its first sentence, and the audit below reads that sentence; the tail
        # is the remedy, which is what a screen line wants and what an audit
        # does not.
        return {"verdict": verdict, "rc": rc, "diag": diag.strip()}
    if not os.path.isfile(out):
        return {"verdict": "crash", "rc": rc,
                "diag": "reported success and wrote no binary"}
    got, err = run(out, backend)
    if got is None:
        # A TIMEOUT is a claim about the MACHINE as much as about the program,
        # and this measurement is what made that cost a row: `--mix strfmt`,
        # seed `sweep19c`, indexes 7400-7499, `--stmts 30 50` reported five
        # `TIMEOUT` verdicts out of a hundred, and all five run in 0.58 s or less
        # — every one of them re-ran as a `match` the moment the sweep was asked
        # for those five indexes alone, on both architectures, repeatedly. The
        # five were concurrent with other work on a shared box, and a 0.01 s
        # program does not become a 30 s one.
        #
        # So a timeout is believed only after a SECOND run disagrees with the
        # first, which costs one extra run per timeout and turns the verdict
        # into a statement about the program rather than about the scheduler. A
        # program that times out twice is still a timeout and is still not a
        # finding (`classify` counts it apart), but it is now one.
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
    #
    # **They are STILL HERE after both were fixed**, and the reason is
    # `MIX_MUST_GENERATE`: the operators did not stop being the interesting
    # thing about this mix, they stopped being a KNOWN_DIVERGENCE. A signed
    # `//` is where `formal/model.py::division_floors` (the one decision both
    # emitters ask) has to be right, and a mix that dropped the only construct
    # that exercises it would go on reporting a clean tally if it were deleted
    # from the backend by mistake. Deleting the ROW was the fix's anti-rot;
    # deleting the MIX would have been the fix's own coverage hole.
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
# The REFUSAL half of the corpus: constructs OUTSIDE the modelled subset,
    # emitted on purpose, because nothing else here can reach a refusal. Every
    # one of the mixes above emits something the path is supposed to LOWER,
    # which is the right discipline for finding miscompiles and the wrong
    # one for measuring limits — measured: 4032 programs over the thirteen sweeps
    # `bugs/FORMAL_fuzz_ledger.md` records produced 13 refusals and all 13 were
    # one bug (`_cb0` has no home), so the refusal surface had no coverage at all
    # and neither did the audit below have anything to audit.
    #
    # So a sweep of THIS mix is a sweep of the messages: does each machine
    # refuse, do both refuse the same construct in the same words, and does each
    # message name something the program contains. The weights are chosen so the
    # mix reaches every family rather than the loudest one, and `unknown_callee`
    # and `big_blob` are IN it although they are known to produce findings: a
    # family that produces a finding is a family that measures, and a corpus
    # tuned to be green is a corpus that has stopped.
    #
    # Its slice member is `slice_print` and NOT `slice_read`, which is the
    # `slicing` mix's name for the other half of the same construct: this one
    # prints the slice EXPRESSION (`print(L[1:3])`), which both backends refuse
    # because `print` cannot tell a string slice from a number, and that refusal
    # is what this mix is here to census. `slice_read` binds the slice to a local
    # first and then measures the LOWERING (`slice_stmt`), which is a family that
    # answers. Two programs, two names, one dispatch arm each — they were the
    # same name on two branches, and a name that two generators answer to is a
    # name whose arm depends on which one the `elif` chain reached first.
    #
    # `variadic_define` and `variadic_call` are here for the reason
    # `bugs/FORMAL_a_variadic_parameter_read_has_no_abi.md` §5 step 5 records and
    # measured: a function that DECLARES `*rest` and READS it was unreachable
    # from this generator, so nothing here could notice the day it was fixed.
    # Both halves are needed for a verdict — the read is what
    # `formal/build.py::_refuse_variadic_reads` fires on, and a definition with
    # no call site is dead code — and the call site varies the COUNT, because
    # the doc's own measurement is that the empty answer is right exactly when
    # no extra argument was passed and wrong otherwise: a corpus whose every
    # call passes zero extras cannot tell the two apart either.
    "limits": (("str_concat", 4), ("str_new_method", 6), ("slice_print", 4),
               ("dict_method", 3), ("try_handler", 3), ("unknown_callee", 3),
               ("big_blob", 2), ("variadic_define", 3), ("variadic_call", 4),
               ("assign", 2), ("if", 2), ("print", 2)),
    # ── the nine families the fuzz-3 sweep added ──
    #
    # Every one of them is a construct the corpus could not produce at all, and
    # each was probed on both architectures BEFORE it was written down here, so
    # that a mix measures a lowering rather than a refusal it would have spent
    # its budget re-deriving (`bugs/FORMAL_fuzz_ledger.md` §2 and §5). What each
    # one is here to reach:
    #
    #   loopelse  `while`/`for` with an `else` arm, which is the shape where the
    #             arm runs only when NO `break` did — so `break` and `continue`
    #             stop being interchangeable. Both lower on both architectures
    #             (probed), and CPython's rule is the oracle's own.
    #   closures  a `def` inside `main` reading an enclosing local, and a call
    #             to it AFTER that local has been reassigned: a closure that
    #             captures the CELL answers the new value, one that copied it at
    #             definition time answers the old one, and both build and exit 0.
    #   argshape  default parameters and KEYWORD arguments at the call site —
    #             the two halves of a call signature, and the only place a
    #             missing argument's default is filled in.
    #   slicing   `xs[a:b]`, `xs[a:]`, `xs[a:b:c]` on a list, which is a NEW blob
    #             with the same element kind (a string slice is refused; the
    #             corpus spends its budget where answers exist).
    #   unpack    `a, b, c = t` — the element-kind family, found by this mix:
    #             it was refused outright by `print` on both architectures
    #             (fixed in `formal/model.py`'s `_unpacked_element_kind`).
    #   bignum    word-boundary integers under the operations that agree on them
    #             — and the discipline that IS the family, because getting it
    #             wrong produces a `MISMATCH` that is about the CORPUS rather
    #             than about a backend: CPython's integers are unbounded and a
    #             formal value is ONE 64-bit word, so a literal that does not fit
    #             is WRAPPED rather than refused (measured on both
    #             architectures: `print(18446744073709551615)` prints `-1`,
    #             `print(2147483647 << 33)` prints `-8589934592`) and a family
    #             that generated one would report that deliberate wrapping
    #             hundreds of times. `big_expr` carries the measurement.
    #   chains    `a < b < c` as a CONDITION and as a VALUE, which is a
    #             different lowering from `a < b`: CPython evaluates the middle
    #             operand ONCE, so a lowering that re-reads it answers a
    #             different question about the same source.
    #   strfmt    string formatting that this path LOWERS: the five methods
    #             (`count`, `find`, `startswith`, `endswith`, `lstrip`) plus
    #             `len`, which is the whole of what a string can do here.
    #   fstrings  an f-string / t-string literal, ALONE in its mix and for the
    #             reason `MIXES_NOT_LOWERED` names: it is a REFUSAL now
    #             (`model.interpolated_literal_refusal`) because composition has
    #             no buffer here, so a mix that also expected answers could only
    #             report refusals for the family it exists to measure. It was a
    #             silent wrong answer before that refusal — the literal's own
    #             source spelling, printed, exit 0, on both architectures — and
    #             the fuzz-3 sweep found it by generating it.
    "loopelse": (("loop_else", 6), ("loop_nested", 3), ("assign", 3),
                 ("if", 3), ("print", 2), ("augassign", 2), ("chain_cmp", 2)),
    "closures": (("closure_def", 5), ("closure_call", 6), ("assign", 2),
                 ("if", 3), ("print", 3), ("augassign", 2), ("list_build", 2)),
    "argshape": (("arg_define", 4), ("arg_call", 7), ("assign", 2),
                 ("if", 3), ("print", 3), ("augassign", 2)),
    "slicing": (("slice_read", 7), ("slice_step", 3), ("list_build", 3),
                ("list_len", 2), ("assign", 2), ("if", 3), ("print", 2)),
    "unpack": (("unpack_bind", 6), ("unpack_dict", 4), ("tuple_build", 3),
               ("list_build", 2), ("tuple_read", 2), ("assign", 2), ("if", 3),
               ("print", 3)),
    "bignum": (("big_int", 7), ("big_shift", 3), ("assign", 2), ("cmp", 3),
               ("if", 3), ("print", 3), ("augassign", 2)),
    "chains": (("chain_cmp", 7), ("assign", 2), ("cmp", 3), ("if", 3),
               ("print", 3)),
    #   tryfinally  a `try`'s `finally` arm, which is the half of `try` this
    #             path lowers — a handler with a body is REFUSED
    #             (`unemitted_handler_arm`), so a corpus that generated one would
    #             measure a refusal and not a lowering. The arm has three exits
    #             to run on (fall through, `break` out of an enclosing loop,
    #             `return` out of the function) and the emitters run the pending
    #             arms from three places, so each is its own family.
    "tryfinally": (("try_finally", 5), ("try_finally_loop", 4),
                   ("try_finally_return", 4), ("assign", 2), ("if", 3),
                   ("print", 2)),
    #   strfmt  the SAME five lowered string methods `strmeth` above draws,
    #             under the fuzz-3 session's own name and weights.  Both mixes
    #             stay because a mix name is part of the program's SEED
    #             (`make_program` seeds on `f"{seed}:{index}:{mix}"`), so
    #             collapsing them would make every row
    #             `bugs/FORMAL_fuzz_ledger.md` records under one of the two
    #             names a row about programs this tool can no longer generate.
    #             Two SELECTIONS of one generator is what the table is for —
    #             `core` and `signed` share half their kinds too.
    "strfmt": (("str_bind", 3), ("str_count", 3), ("str_find", 3),
               ("str_startswith", 3), ("str_endswith", 2), ("str_lstrip", 2),
               ("str_meth_len", 2), ("if", 3), ("print", 2)),
    "fstrings": (("str_interp", 5), ("assign", 2), ("print", 2)),
}

#: mix -> (a pattern the mix must still PRODUCE, why it must).
#:
#: **This is a different table from `KNOWN_DIVERGENCES` and the difference is
#: the whole point.**  A known-divergence row is a claim that the backend gets
#: this construct wrong, and it must be DELETED the day that stops being true —
#: a row naming a construct that is now right forgives the next disagreement
#: that happens to contain it.  A row here is a claim about the GENERATOR: that
#: this mix still emits a shape nothing else does.  That claim is unaffected by
#: whether the backend is right about the shape, which is why it survives the
#: fix that deleted the corresponding `KNOWN_DIVERGENCES` row and outlives it.
#:
#: `signed` is the row that matters today.  `--mix signed` is the only place a
#: signed-over-signed `//` and `%` are generated at all, and that is where
#: `formal/model.py::division_floors` — the one decision both emitters read —
#: is exercised.  A change that made the signedness uniform, or dropped the
#: operators from the mix, would leave every sweep reporting the same clean
#: tally with one fewer thing measured, which is the failure mode
#: `bugs/FORMAL_fuzz_ledger.md` §1 calls out: "a mix that stops producing a
#: construct reports the same clean tally as one that never produced it".
MIX_MUST_GENERATE = {
    "signed": (r"//|(?<![\w)])%(?![a-zA-Z_(])",
               "`--mix signed` is the only place a signed-over-signed division "
               "is generated, and it is where `model.division_floors` is "
               "exercised; the operators stay in the pool after both were "
               "fixed precisely so a regression there is visible as a "
               "coverage hole rather than as a quieter corpus"),
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
#: The same bound for the two families that define a function from INSIDE a body
#: (`closure_def`) or with a signature of its own (`arg_define`), kept apart
#: rather than folded into `MAX_FUNCS` because the bound that matters is
#: different: a closure nests, so two of them can put four `def` lines on the
#: stack, and a signature with defaults is a longer definition per function.
MAX_CLOSURES = 2
MAX_ARGFUNCS = 3
#: The same bound for the `try_finally_return` helper: it is a module-level
#: definition like `define_function`'s, and it exists to carry a `return` that
#: must not end `main` (a `return` in `main` truncates the program there and
#: every statement after it is dead code on both engines).
MAX_TRYFUNCS = 2


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
        self.closures = []    # (name, params, captured, outer, is_nested)
        self.closure_defs = []   # the `def` lines, spliced into main's body
        self.argfuncs = []    # (name, params, required count, defaults)
        self.tryfuncs = []    # (name, param) helpers with a return in a try
        self.closure_blobs = {}   # captured list name -> the index its body reads
        self.variadics = []   # (name, fixed arity) `*rest` defs
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
"environ_get", "environ_len", "environ_cmp",
            "str_concat", "str_new_method", "slice_print", "dict_method",
            "try_handler", "unknown_callee", "big_blob",
            "loop_else", "loop_nested", "closure_def", "closure_call",
            "try_finally", "try_finally_loop", "try_finally_return",
            "arg_define", "arg_call", "slice_read", "slice_step",
            "unpack_bind", "unpack_dict", "big_int", "big_shift", "chain_cmp",
            "str_interp", "variadic_define", "variadic_call")
        if budget <= 0 and kind in ("if", "while", "for", "call",
                                    "nested_call", "recursion",
                                    "list_in_loop", "dict_iter",
                                    "tuple_iter", "loop_nested",
                                    "loop_else", "closure_def",
                                    "try_finally", "try_finally_loop"):
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
        elif kind in ("str_concat", "str_new_method", "slice_print",
                      "dict_method", "try_handler", "unknown_callee",
                      "big_blob"):
            self.limits_stmt(indent, kind)
        elif kind in ("variadic_define", "variadic_call"):
            self.variadic_stmt(indent, kind)
        elif kind in ("obj_new", "field_read", "field_cmp", "field_write",
                      "method_call", "method_call_in_arg"):
            self.object_stmt(indent, kind)
        elif kind in ("loop_else", "loop_nested"):
            self.loop_else_stmt(indent, kind)
        elif kind in ("try_finally", "try_finally_loop", "try_finally_return"):
            self.try_stmt(indent, kind)
        elif kind in ("closure_def", "closure_call"):
            self.closure_stmt(indent, kind)
        elif kind in ("arg_define", "arg_call"):
            self.argshape_stmt(indent, kind)
        elif kind in ("slice_read", "slice_step"):
            self.slice_stmt(indent, kind)
        elif kind == "unpack_bind":
            self.unpack_stmt(indent)
        elif kind == "unpack_dict":
            self.unpack_dict_stmt(indent)
        elif kind in ("big_int", "big_shift"):
            self.bignum_stmt(indent, kind)
        elif kind == "chain_cmp":
            self.chain_stmt(indent)
        elif kind == "str_interp":
            self.str_interp_stmt(indent)
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
            # limit as a `MISMATCH-*` finding on every program that contained
            # it. (The doc that recorded that limit is deleted with the fix,
            # which is the repository's rule for a fixed bug.)
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
    def variadic_stmt(self, indent, kind):
        """A function that DECLARES `*rest` and a call site for it.

        The construct `formal/build.py::_refuse_variadic_reads` exists for, and
        the one this generator could not reach: a `*rest` DEFINITION on its own
        is dead code and a `*rest` READ with no definition is a NameError, so the
        two kinds are one feature and the call site is not optional.

        **The read is `len(rest)` and not `rest[0]`** because CPython has to be
        able to ANSWER it. `len(rest)` is the shape the doc's reproducer uses and
        the one whose wrong-but-exit-0 answer is measurable: a backend that
        lowered the parameter as the empty sequence would print 0 here where
        CPython prints the number of extras passed, and the corpus has to be able
        to SEE that. `rest[0]` on an empty tuple is an IndexError in CPython,
        which is a legitimate program but an oracle that errors takes the whole
        program's verdict with it.
        """
        if kind == "variadic_define" or not self.variadics:
            self.define_variadic()
            return
        name, fixed = self.rng.choice(self.variadics)
        extras = self.rng.randint(0, 3)
        args = [str(self.rng.randint(0, 60)) for _ in range(fixed + extras)]
        self.emit(indent, f'print({name}({", ".join(args)}))')

    def define_variadic(self):
        """One `def v(a, *rest)` whose body is `return len(rest)`.

        One fixed parameter before the star and `len` of the star in the body:
        both are load-bearing rather than taste. **The fixed parameter** is what
        makes the star a VARIADIC rather than the only parameter, so a call site
        can pass a known count and an unknown one in the same program — and the
        refusal's own message reports the two numbers ("this module's call sites
        pass 3..3 argument(s), against 1 fixed parameter(s)"), so a corpus that
        never varied the count could not read it. **The read is in the RETURN**
        because a `comptime`-folded body would be a different construct.
        """
        if self.defined >= MAX_FUNCS:
            return None
        self.defined += 1
        name = self.fresh("var")
        fixed = self.rng.randint(1, 2)
        params = ", ".join(self.fresh("w") for _ in range(fixed))
        self.defs.append(f"def {name}({params}, *rest):")
        self.defs.append("    return len(rest)")
        self.variadics.append((name, fixed))
        return name

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

    # ── the OUT-OF-SUBSET half: `limits` ──
    #
    # Every other statement in this generator emits something the formal path is
    # supposed to LOWER, because a corpus of constructs the backend refuses
    # measures nothing — which is what `test_formal_fuzz.py`'s
    # `check_mix_builds` exists to say, and it says it about every mix but this
    # one.  The refusal surface is therefore not covered at all: 4032 programs
    # over the thirteen sweeps `bugs/FORMAL_fuzz_ledger.md` records produced 13
    # refusals, and all thirteen were one bug.  That is not a corpus measuring
    # the limits; it is a corpus that cannot reach them.
    #
    # So this family emits constructs OUTSIDE the modelled subset on purpose, and
    # the sweep's job is the audit: does each machine refuse, do both refuse the
    # SAME construct in the SAME words, and does the message name something the
    # program contains.  Every construct here is valid CPython, so the oracle
    # answers it and the refusal is a claim about a program that demonstrably
    # means something.
    #
    # What CPython answers is not recorded per construct — the sweep's verdict
    # already carries it, and a constant here would be an assertion about the
    # backend made against itself.
    def limits_stmt(self, indent, kind):
        # A string, a list and a dict to work on, built if absent. Declared the
        # way `strmeth_stmt` does it: a bound name, so the construct under test
        # is never "a name that does not exist", which is a different refusal
        # and one the corpus already covers elsewhere.
        if kind == "str_concat":
            if not self.strings:
                self.limit_bind_string(indent)
            recv = self.rng.choice(self.strings)
            self.emit(indent, f'{recv} = {recv} + "cd"')
            return
        if kind == "str_new_method":
            if not self.strings:
                self.limit_bind_string(indent)
            recv = self.rng.choice(self.strings)
            # The five methods this path DOES lower are `strmeth`'s subject, and
            # the point of this row is a method outside them. `upper`, `strip`,
            # `title`, `swapcase` and `zfill` are spellings of one refusal (a NEW
            # string of the same length, with no buffer to put it in) and
            # `split`/`rsplit` are the other one (a SEQUENCE of strings, whose
            # element count is only known at run time), so they are a choice
            # among names rather than seven rows to keep.
            meth = self.rng.choice(["upper", "lower", "strip", "title",
                                    "swapcase", "split", "rsplit"])
            self.emit(indent, f"print({recv}.{meth}())")
            return
        if kind == "slice_print":
            if not self.lists:
                self.limit_bind_list(indent)
            # `self.lists` holds (name, length) TUPLES, so the name is the
            # first field; choosing the tuple itself emits `('L5', 3)[1:3]`,
            # which is a subscript of a tuple literal and is not this row.
            name = self.rng.choice(self.lists)[0]
            lo = self.rng.randint(0, 1)
            hi = lo + self.rng.randint(1, 2)
            self.emit(indent, f"print({name}[{lo}:{hi}])")
            return
        if kind == "dict_method":
            if not self.dicts:
                self.limit_bind_dict(indent)
            name = self.rng.choice(self.dicts)[0]
            meth = self.rng.choice(["keys", "items"])
            self.emit(indent, f"print({name}.{meth}())")
            return
        if kind == "try_handler":
            # A handler arm with a body, which is refused rather than DROPPED:
            # the image would build, exit 0, and not be the program that was
            # written. `pass` in the arm is the shape that still builds, so this
            # is deliberately not that one.
            in_try = self.declare(self.fresh("q"), "0")
            in_arm = self.declare(self.fresh("q2"), "0")
            self.emit(indent, "try:")
            self.emit(indent + 1, f"{in_try} = 1")
            self.emit(indent, "except:")
            self.emit(indent + 1, f"{in_arm} = 2")
            self.emit(indent, f"print({in_try})")
            return
        if kind == "unknown_callee":
            # A name that is neither a function in the image nor a C symbol
            # anything provides. Measured on both architectures: this does NOT
            # reach a refusal about `sum`; it reaches the LINK AUDIT, which
            # reports that the image would bind a symbol nothing provides and
            # then says, in its own words, that it cannot decide whether that
            # symbol is a call the codegen emitted. So the construct is refused
            # and the message names a file and a symbol rather than the call —
            # `REFUSAL-UNNAMED` in every sweep, and
            # `the link audit's naming of an unlowered callee (landed in ee704916)`
            # is where that is written down.
            # Arity is CPython's, so the oracle can answer: `abs` takes ONE
            # operand and `max`/`min` take two or more, and a generated program
            # that calls either with the wrong number is a `generator-error` —
            # the tool's verdict for a program its own generator got wrong, and
            # a generator error would hide every refusal in the same program.
            # `sum` needs a LIST: `sum(3)` is a TypeError in CPython, and a
            # generator error would take the whole program's verdict with it.
            lists = [n for n, _k in self.lists]
            # Never `sum` in the two-argument branch: `sum(a, b)` is a TypeError
            # in CPython, so a fallback that reached it turned a program into a
            # `generator-error` instead of a refusal — measured, on `limits`
            # seeds 8000-8009 (2 of 10 programs).
            callee = self.rng.choice(
                ["sum", "max", "min", "abs"] if lists
                else ["max", "min", "abs"])
            if callee == "sum":
                self.emit(indent, f"print(sum({self.rng.choice(lists)}))")
            elif callee == "abs":
                self.emit(indent, f"print(abs({self.int_expr(3)}))")
            else:
                self.emit(indent, f"print({callee}({self.int_expr(3)}, "
                                  f"{self.int_expr(5)}))")
            return
        if kind == "big_blob":
            # A container literal past ONE architecture's frame budget and
            # inside the other's, so the measured shape is a
            # `REFUSAL-DIVERGES` rather than a bug in either lowering — a
            # construct refused on one machine and lowered on the other, which
            # is this fuzzer's definition of a parity finding, and
            # `bugs/FORMAL_the_two_architectures_have_different_container_
            # budgets.md` is what it was filed as.
            #
            # The SIZE is computed from `formal/model.py::CONTAINER_BUDGET` —
            # the SMALLER of the two budgets, and the number the model declares
            # as the one that decides — rather than being a literal here. That
            # is the whole of that doc's "one number in the tree": a program in
            # this corpus that is meant to fit has to fit the budget both
            # machines share, and this row is the one place a corpus picks a
            # size, so a budget that moves moves it.
            #
            # `+1` element past the ceiling, and the ceiling is the one the
            # model prints in the refusal itself: a word-element blob is
            # `[count][element...]`, so 8 bytes of the budget are the count.
            # `blob_ceiling()` in `formal/model.py` is that arithmetic, and it
            # is shared with the refusal message so the corpus and the message
            # cannot disagree about where the edge is.
            #
            # The row is deliberately NOT sized to make both machines refuse:
            # the next size past the LARGER budget is 16384 elements, ~80 KB of
            # text per program, and a refusal has to be readable in its source
            # to be believed. So this stays a divergence, and `classify`
            # names WHICH one (see `frame_budget_divergence`) rather than
            # leaving a reader to re-derive two budgets out of a comment.
            if getattr(self, "_big_blob_done", False):
                # ONE per program, and the reason is the program's own size: a
                # 2400-element literal is ~12 KB of text, two of them are 24 KB,
                # and a refusal has to be read in its source to be believed. The
                # first one already answers the question this row asks.
                self.emit(indent, f"print({self.int_expr(0)})")
                return
            self._big_blob_done = True
            n = M.blob_ceiling(M.CONTAINER_BUDGET) + self.rng.choice([1, 128, 256])
            elems = ", ".join(str((i * 7) % 100) for i in range(n))
            name = self.fresh("BL")
            self.emit(indent, f"{name} = [{elems}]")
            self.emit(indent, f"print(len({name}))")
            return
        # unreachable: `stmt` only dispatches kinds this family owns
        raise AssertionError(kind)

    # The three bindings `limits` needs, and why they go in the PREAMBLE rather
    # than at the statement's own indent: a binding emitted inside a branch is
    # not a binding. `limits` emits `try:`/`except:` arms and nested `if`s, so a
    # `D = {10: 100}` written under `if (w3 <= w4):` left `D` at its declared
    # `0` for every path that did not take the branch, and the `d.keys()` two
    # statements later was `AttributeError: 'int' object has no attribute
    # 'keys'` in CPython — a `generator-error`, which is the tool's verdict for a
    # program its own generator got wrong and which takes the program's real
    # verdict with it. (`strmeth_stmt` and `list_stmt` bind the same way and can
    # hit it the same way; see
    # `bugs/TOOLS_a_generator_binding_emitted_inside_a_branch_is_not_a_binding.md`.)
    # `declare` puts the initialiser in the preamble, which is emitted once at
    # the top of `main` before any branch runs.
    def limit_bind_string(self, indent):
        name = self.declare(self.fresh("t"), '"ab"')
        self.strings.append(name)
        self.strings_text[name] = "ab"
        return name

    def limit_bind_list(self, indent):
        name = self.declare(self.fresh("L"), "[1, 2, 3]")
        self.lists.append((name, 3))
        return name

    def limit_bind_dict(self, indent):
        name = self.declare(self.fresh("D"), "{10: 100, 20: 200}")
        self.dicts.append((name, "int", [10, 20]))
        return name

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

    # ── a `try`'s `finally` arm ──
    #
    # The one half of `try` this path lowers. A handler arm with a BODY is
    # REFUSED (`formal/model.py`'s `unemitted_handler_arm`, measured on both
    # architectures: a `try` whose handler printed built, ran, printed nothing
    # and exited 0), so a corpus that generated one would measure a refusal; an
    # arm whose body is `pass` BUILDS and does nothing, which is also not
    # generatable here — this path has no exception VALUES, so the only way to
    # reach a handler is an operation that TRAPS (a division by zero exits 1 on
    # both architectures where CPython would have taken the handler and printed
    # `0`), and a program whose answer depends on a trap is not a differential
    # test.
    #
    # `finally` is the opposite: it is unconditional, it is lowered, and it has
    # three exits it has to run on — falling out of the `try`, a `break` out of
    # an enclosing loop, and a `return` out of the function. The emitters keep
    # the pending arms in a list and run them from three places
    # (`arm64_codegen._flush_pending_finally`: depth 0 for a return, the loop's
    # entry depth for `break`/`continue`), so all three are the same bug class
    # and all three build and exit 0 when they are wrong. Every family below is
    # one of those three exits, and the observable is always the ORDER of the
    # prints: a `finally` that runs late or not at all reorders the output.
    def try_stmt(self, indent, kind):
        acc = self.declare(self.fresh("w"), "0")
        self.words.append(acc)
        marker = self.rng.randint(1, 99)
        if kind == "try_finally_return":
            # A `return` INSIDE the `try`, with the marker printed by the
            # `finally` after it — in a HELPER, because a `return` in `main`
            # ends the program there and every statement after it is dead code
            # (which both engines agree about, so it measures nothing). The
            # only observable is whether the arm ran BEFORE the return, which is
            # why the marker is a `print` and not a store: a store into a local
            # the function has already left is invisible on both engines.
            if len(self.tryfuncs) >= MAX_TRYFUNCS:
                self.emit(indent, "try:")
                self.loop_depth += 1
                self.emit(indent + 1,
                          f"{acc} = ({acc} + 3) & 0xFFFF")
                self.loop_depth -= 1
                self.emit(indent, "finally:")
                self.emit(indent + 1, f"{acc} = ({acc} + 100) & 0xFFFF")
                self.emit(indent + 1, f"print({marker}, {acc} & 0xFF)")
                return
            name = self.fresh("tf")
            param = self.fresh("q")
            self.defs.append(f"def {name}({param}):")
            self.defs.append(f"    acc = 0")
            self.defs.append(f"    try:")
            self.defs.append(f"        acc = ({param} + 7) & 0xFFFF")
            self.defs.append(f"        return acc & 0xFF")
            self.defs.append(f"    finally:")
            self.defs.append(f"        print({marker})")
            self.tryfuncs.append((name, param))
            self.emit(indent, f"print({name}({self.rng.randint(0, 200)}))")
            return
        self.emit(indent, "try:")
        self.loop_depth += 1
        self.emit(indent + 1, f"{acc} = ({acc} + {self.rng.randint(1, 9)})"
                              f" & 0xFFFF")
        if kind == "try_finally_loop":
            counter = self.fresh("i")
            self.emit(indent + 1, f"for {counter} in range(2):")
            self.emit(indent + 2, f"{acc} = ({acc} + {counter}) & 0xFFFF")
            self.emit(indent + 2, "try:")
            self.emit(indent + 3, f"print({acc} & 0xFF)")
            if self.rng.random() < 0.5:
                self.emit(indent + 3, "break")
            self.emit(indent + 2, "finally:")
            self.emit(indent + 3, f"print({marker})")
            self.loop_depth -= 1
            self.emit(indent, "finally:")
            self.emit(indent + 1, f"print({marker})")
            return
        self.emit(indent, "finally:")
        self.emit(indent + 1, f"{acc} = ({acc} + 100) & 0xFFFF")
        self.emit(indent + 1, f"print({marker}, {acc} & 0xFF)")

    # ── a loop's `else` arm, and the loop that decides it ──
    #
    # `while c: … else: …` runs the `else` when the loop finished WITHOUT a
    # `break`, which makes the arm the one construct in control flow whose
    # reaching depends on something that happened earlier in the body rather
    # than on a condition. A lowering that treats `break` and `continue` alike,
    # or that emits the arm unconditionally, computes something else and exits
    # 0 — and `continue` is the shape that tells them apart, because CPython
    # runs the `else` after a `continue` too.
    #
    # Every trip count is bounded BY CONSTRUCTION (`while_loop`'s counter, or
    # `range(lo, hi)`) for the reason that docstring gives, and the `else` body
    # is never empty: an empty block is an `IndentationError` in CPython and a
    # syntax error in the parser, so it goes through `block` like every other.

    def loop_else_stmt(self, indent, kind):
        if kind == "loop_nested":
            inner = self.fresh("j")
            outer = self.fresh("i")
            acc = self.declare(self.fresh("w"), "0")
            self.words.append(acc)
            lo = self.rng.randint(0, 2)
            self.emit(indent, f"for {outer} in range({lo}, {lo + 2}):")
            self.loop_depth += 1
            # The inner loop carries its OWN arm, and it is a loop rather than
            # an `if` because the arm has to belong to a construct that CAN
            # break: an `else` after a plain statement is a syntax error in
            # CPython (measured — 48 of the first 80 `loopelse` programs), and
            # the family that exists to measure an arm is not the family that
            # measures a syntax error.
            self.emit(indent + 1,
                      f"for {inner} in range({self.rng.randint(1, 3)}):")
            self.loop_depth += 1
            self.emit(indent + 2, f"{acc} = ({acc} + {inner}) & 0xFFFF")
            if self.rng.random() < 0.6:
                # A `break` in the INNER loop decides the INNER arm only, which
                # is the whole of what nesting two of them measures: the outer
                # arm must still run.
                self.emit(indent + 2, "break")
            self.loop_depth -= 1
            self.emit(indent + 1, "else:")
            self.emit(indent + 2, f"{acc} = ({acc} + 10) & 0xFFFF")
            self.emit(indent, "else:")
            self.emit(indent + 1, f"{acc} = ({acc} + 100) & 0xFFFF")
            self.emit(indent + 1, f"print({acc})")
            self.loop_depth -= 1
            return
        # The `while` half and the `for` half are both generated: their `else`
        # arms are reached by different code (a counter test against a bound,
        # and a walk's completion), and a lowering that emits one of them is not
        # evidence about the other.
        if self.rng.random() < 0.5:
            guard = self.declare(self.fresh("g"), "0")
            limit = self.rng.randint(1, 4)
            self.emit(indent, f"{guard} = 0")
            self.emit(indent, f"while {guard} < {limit}:")
            step = f"{guard} = {guard} + 1"
            witness = guard
        else:
            lo = self.rng.randint(0, 2)
            hi = lo + self.rng.randint(1, 3)
            counter = self.fresh("i")
            self.emit(indent, f"for {counter} in range({lo}, {hi}):")
            step = f"print({counter})"
            witness = counter
        self.loop_depth += 1
        self.emit(indent + 1, step)
        if self.rng.random() < 0.5:
            # A `break` half the time and a `continue` the other half, and BOTH
            # are followed by the arm: the pair is what says which one the
            # backend understood, because they differ only in whether the arm
            # runs. CPython runs the `else` after a `continue`.
            self.emit(indent + 1, self.rng.choice(["break", "continue"]))
        else:
            self.block(indent + 1, 0)
        self.loop_depth -= 1
        self.emit(indent, "else:")
        acc = self.declare(self.fresh("w"), "0")
        self.words.append(acc)
        self.emit(indent + 1,
                  f"{acc} = ({self.int_expr(1)} + {witness}) & 0xFFFF")
        self.emit(indent + 1, f"print({acc})")

    # ── a closure: a `def` that reads an enclosing local ──
    #
    # Module level is where `define_function` puts its helpers, deliberately:
    # a `def` inside `main` is a CLOSURE, and a closure's environment is a
    # different subject — the flattened cell (`formal/build.py`'s
    # `_rewrite_closures_in_body`) either shares the enclosing slot or copies
    # it, and only a program that REASSIGNS the captured name after the `def`
    # can tell. CPython reads the cell at call time, so a copy answers the
    # value from before the reassignment, and both engines exit 0 either way.
    #
    # The definition goes into `closure_defs` and `program()` splices it into
    # `main`'s body BETWEEN the preamble and the body, for two reasons that are
    # both CPython's rules rather than taste: a `def` inside `main` at module
    # level is a syntax error, and a call emitted BEFORE the `def` reached is a
    # `NameError` in the oracle. Splicing after the preamble is what lets the
    # closure read a name the preamble declares, which is the only reason the
    # capture is guaranteed to be bound on every path.
    def closure_stmt(self, indent, kind):
        if kind == "closure_def" or not self.closures:
            if len(self.closures) >= MAX_CLOSURES:
                self.new_word(indent)
                return
            if not (self.words or self.smalls):
                self.new_small(indent)
            capture = self.rng.random() < 0.3
            if capture and not self.lists:
                # The captured container is built HERE rather than left to the
                # mix's weights to have happened by now: a list that exists only
                # when some other statement made it first would make the
                # captured-container shape a function of statement order rather
                # than of the draw, and the whole point of the shape is that it
                # is always available to be measured.
                self.new_list_of_two(indent)
            cap = (self.rng.choice(self.lists)[0] if capture
                   else self.rng.choice(self.words + self.smalls))
            name = self.fresh("cf")
            param = self.fresh("k")
            if capture:
                # The captured CONTAINER, and the body reads an ELEMENT of it —
                # the closure half of the same question a tuple unpack asks
                # (`_unpacked_element_kind`), at two levels of indirection: a
                # rewrite that lifted the closure into a function of its own
                # would have to carry the blob across, and a copy of the blob
                # would answer the element from before the store.
                idx = self.rng.randrange(dict(self.lists)[cap])
                self.closure_blobs[cap] = idx
                self.closures.append((name, [param], cap, None, False))
                self.closure_defs.append(f"    def {name}({param}):")
                self.closure_defs.append(
                    f"        return {cap}[{idx}] + {param}")
                self.new_word(indent)
                return
            if self.rng.random() < 0.35:
                # TWO levels, because the flattening is recursive and one level
                # does not reach it: the inner `def` reads a name the middle
                # one captured, and a rewrite that lifts only the outermost
                # closure leaves the inner one reading a slot that does not
                # exist.
                inner = self.fresh("df")
                self.closures.append((inner, [param], cap, name, True))
                self.closure_defs.append(f"    def {name}({param}):")
                self.closure_defs.append(f"        def {inner}({param}):")
                self.closure_defs.append(
                    f"            return ({cap} + {param}) & 0xFFFF")
                self.closure_defs.append(
                    f"        return {inner}(({param} + 1) & 0xF)")
            else:
                self.closures.append((name, [param], cap, None, False))
                self.closure_defs.append(f"    def {name}({param}):")
                self.closure_defs.append(
                    f"        return ({cap} + {param}) & 0xFFFF")
            self.new_word(indent)
            return
        name, params, cap, outer, deep = self.rng.choice(self.closures)
        if outer is not None:
            # A nested closure is called through the OUTER one, which is the
            # only way its own body runs.
            self.emit(indent, f"print({outer}({self.rng.randint(0, 9)}))")
            return
        if cap in self.closure_blobs:
            # A captured CONTAINER, which is the shape where "shares the slot"
            # and "copied the value" cannot be told apart from an integer: the
            # closure reads an ELEMENT, so a copy taken at definition time
            # answers the old element while CPython — and this path, measured —
            # answers the new one. The store goes through an index that is
            # inside the list's length, so the two engines are comparing the
            # same program and not one of them is faulting.
            idx = self.closure_blobs[cap]
            # The closure's own PARAMETER is not in scope here — it belongs to
            # the `def`, and spelling it in `main`'s body is a NameError in the
            # oracle. What the caller has is an integer literal, which is what
            # makes the two answers differ at all: the second print sees the
            # store only if the closure and the caller share the blob.
            k = self.rng.randint(0, 9)
            self.emit(indent, f"print({cap}[{idx}] + {k})")
            self.emit(indent, f"{cap}[{idx}] = ({cap}[{idx}] + 9) & 0xFFFF")
            self.emit(indent, f"print({cap}[{idx}] + {k})")
            return
        self.emit(indent, f"print({name}({self.rng.randint(0, 9)}))")
        if self.rng.random() < 0.6:
            # The reassignment AFTER the `def`: the statement that separates a
            # cell from a copy. Emitted by the family itself, so no mix has to
            # remember to do it and a closure the corpus generates is always one
            # a copy would get wrong.
            self.emit(indent, f"{cap} = ({self.rng.randint(0, 200)}) & 0xFFFF")
            self.emit(indent, f"print({name}({self.rng.randint(0, 9)}))")

    # ── a call signature: default parameters and keyword arguments ──
    #
    # Two halves of one contract, and the halves are lowered in different
    # places: the default is a value the DEFINITION carries and the callee reads
    # when no argument arrived, and a keyword argument is a NAME the call site
    # spells which the emitter has to bind to a POSITION. A lowering that
    # filled a missing argument from the wrong slot, or that took keyword
    # arguments positionally, computes a different program and exits 0.
    #
    # Parameters with defaults come after the ones without — CPython's own rule,
    # and it is a SyntaxError rather than a wrong answer to test, so a family
    # that could produce it would be measuring the oracle's traceback. The body
    # returns, for the same reason: a helper with no `return` yields a word on
    # this path where CPython yields `None`
    # (`bugs/FORMAL_a_function_with_no_return_yields_a_word_where_cpython_yields_None.md`),
    # and a family that printed such a call would spend its budget on a bug this
    # corpus cannot fix.
    def argshape_stmt(self, indent, kind):
        if kind == "arg_define" or not self.argfuncs:
            if len(self.argfuncs) >= MAX_ARGFUNCS:
                self.new_word(indent)
                return
            name = self.fresh("af")
            required = self.rng.randint(1, 2)
            optional = self.rng.randint(1, 2)
            params = [self.fresh("q") for _ in range(required + optional)]
            defaults = [self.rng.randint(0, 40) for _ in range(optional)]
            sig = ", ".join(params[:required]
                             + [f"{p}={d}" for p, d
                                in zip(params[required:], defaults)])
            self.defs.append(f"def {name}({sig}):")
            self.defs.append(f"    return ({' + '.join(params)} + "
                             f"{self.rng.randint(0, 30)}) & 0xFFFF")
            self.argfuncs.append((name, params, required, defaults))
            return
        name, params, required, defaults = self.rng.choice(self.argfuncs)
        optional = list(params[required:])
        how = self.rng.choice(["all", "some", "kw", "mixed", "none"])
        if how == "none":
            args = [self.int_expr(0) for _ in params[:required]]
            self.emit(indent, f"print({name}({', '.join(args)}))")
            return
        if how == "all":
            args = [self.int_expr(0) for _ in params]
            self.emit(indent, f"print({name}({', '.join(args)}))")
            return
        if how == "some":
            take = self.rng.randint(0, len(optional))
            args = [self.int_expr(0) for _ in params[:required + take]]
            self.emit(indent, f"print({name}({', '.join(args)}))")
            return
        # The keyword half. A keyword argument may name a parameter the call has
        # not filled, and CPython binds it by NAME — so the argument list is
        # built as "the required ones, positionally, then the named ones", and a
        # call that names a parameter twice is a TypeError in the oracle.
        if how == "kw":
            names = [p for p in params if self.rng.random() < 0.7]
            for req in params[:required]:
                if req not in names:
                    names.insert(0, req)
            args = [f"{p}={self.int_expr(0)}" for p in names]
            self.emit(indent, f"print({name}({', '.join(args)}))")
            return
        args = [self.int_expr(0) for _ in params[:required]]
        pick = optional or params
        args.append(f"{self.rng.choice(pick)}={self.int_expr(0)}")
        self.emit(indent, f"print({name}({', '.join(args)}))")

    # ── a list slice: a NEW blob with the source's element kind ──
    #
    # `xs[1:3]` is not an index and not a name: it builds a blob whose count is
    # the number of elements selected, so the walk, the stride and the element
    # kind all have to be re-derived from the BOUNDS rather than read off the
    # base. The corpus could produce a subscript and a container and nothing in
    # between.
    #
    # Bounds are inside the list's length and `lo <= hi` (a reversed pair is an
    # empty slice in CPython and a count this path has no reason to get wrong,
    # but an out-of-range bound is an IndexError in the oracle and a generator
    # error rather than a finding), and the slice is bound to a local whose
    # length the preamble already states so a later statement cannot read it
    # before the assignment runs.
    def slice_stmt(self, indent, kind):
        sources = [pair for pair in self.lists if pair[1] >= 2]
        if not sources:
            self.new_list_of_two(indent)
            sources = [pair for pair in self.lists if pair[1] >= 2]
        src, n = self.rng.choice(sources)
        step = self.rng.choice([None, None, 2, 3]) if kind == "slice_step" else None
        # Bounds are SPELLED three ways, and the third is the one that is its
        # own lowering: `xs[a:b]` names two offsets, `xs[a:]` runs to the end
        # (which is a new blob whose count is `n - a`) and `xs[a:b:c]` walks.
        # A NEGATIVE bound is generated too — CPython counts from the end, so
        # `xs[-2:]` is the last two elements and an emitter that reads `-2` as
        # an offset reads two words before the blob's header.
        shape = self.rng.choice(["pair", "open", "negative"])
        if shape == "negative" and n >= 3:
            hi = self.rng.randint(1, n - 1)
            bound = f"-{n - hi}:"
            count = hi
        elif shape == "open" and n >= 3:
            lo = self.rng.randint(1, n - 2)
            bound = f"{lo}:"
            count = n - lo
        else:
            lo = self.rng.randint(0, n - 2)
            # `hi` is at least `lo + 1`, so the slice is never EMPTY: an empty
            # slice has no element to read and its length is the one number a
            # lowering could get right by accident, so a corpus that generated
            # it would be measuring the degenerate case.
            hi = self.rng.randint(lo + 1, n)
            if step:
                bound = f"{lo}:{hi}:{step}"
                count = len(range(lo, hi, step))
            else:
                bound = f"{lo}:{hi}"
                count = hi - lo
        # The PREAMBLE copy has the slice's own LENGTH, for the reason
        # `list_build` gives and because it is measurable: `S = []` classifies as
        # the BARE list prefix (`_kind_of_elements` of nothing is nothing), so the
        # body's `S = L5[0:2]` binds it a second time with a different kind, the
        # scan calls that a conflict and withdraws the answer — and the first
        # thing a conflict costs is `len(S)`, which is the statement this family
        # exists to run. Measured: 2 of 2 programs of `--mix slicing` were refused
        # for exactly this.
        name = self.declare(self.fresh("S"), "[" + ", ".join(["0"] * count) + "]")
        self.emit(indent, f"{name} = {src}[{bound}]")
        self.emit(indent, f"print(len({name}))")
        # The ELEMENT, read through a local: `print(S[0])` is refused on both
        # backends ("print() cannot tell whether SubscriptExpr is a string or a
        # number") — the same discipline `dict_stmt` states, and for the same
        # reason: a family that is 95% refused measures nothing.
        elem = self.declare(self.fresh("w"), "0")
        self.words.append(elem)
        self.emit(indent, f"{elem} = {name}[0]")
        self.emit(indent, f"print({elem})")

    def new_list_of_two(self, indent):
        name = self.fresh("L")
        self.declare(name, "[0, 0]")
        self.emit(indent, f"{name} = [{self.rng.randint(0, 40)}, "
                          f"{self.rng.randint(0, 40)}]")
        self.lists.append((name, 2))

    # ── tuple unpacking: what each TARGET holds is an ELEMENT ──
    #
    # The one family whose first version found a backend defect rather than
    # confirming one: `a, b, c = t` bound every name to the CONTAINER's kind,
    # so `print(a)` was refused on both architectures with a sentence false
    # about the source (fixed in `formal/model.py`'s `_unpacked_element_kind`,
    # pinned by `test_formal_value_model.py`). It stays in the corpus because a
    # corpus that drops a construct the day it is fixed cannot notice the day
    # something else breaks it.
    #
    # The right-hand side is always a LITERAL of integers, for the reason the
    # value discipline gives in general: a tuple whose elements disagree has no
    # element kind to bind, so half the corpus would be refused for a reason
    # that is about the corpus rather than the lowering, and CPython's answer
    # (a `str` element printed with `%d`) is a different program.
    def unpack_stmt(self, indent):
        n = self.rng.randint(2, 3)
        items = ", ".join(str(self.rng.randint(0, 60)) for _ in range(n))
        tname = self.fresh("U")
        self.declare(tname, "(" + ", ".join(["0"] * n) + ")")
        self.emit(indent, f"{tname} = ({items})")
        names = [self.declare(self.fresh("u"), "0") for _ in range(n)]
        for nm in names:
            self.words.append(nm)
        self.emit(indent, f"{', '.join(names)} = {tname}")
        # Observed through an ARITHMETIC expression rather than through a bare
        # `print(name)`, so what the comparison reads is the sum the unpack fed
        # and not one element — a lowering that paired the wrong element with
        # the wrong name still changes the sum.
        self.emit(indent, "print(" + " + ".join(
            f"({nm} * {i + 1})" for i, nm in enumerate(names)) + ")")

    def unpack_dict_stmt(self, indent):
        """`k, v = d` — a DICT on the right, which binds its KEYS.

        The half of the element-kind family that is a different lowering rather
        than a different value: a dict is a PAIR blob, so the unpack steps by
        the pair where every other container steps by the element
        (`model.walk_stride`), and the targets hold the KEYS rather than one
        element each. It was found by hand and fixed — `formal/model.py`'s
        `_unpacked_element_kind` and both emitters' blob unpack — and it is here
        so a regression is a `MISMATCH` instead of a silent answer again.

        **The two targets are declared as STRINGS in the preamble**, which is not
        tidiness: the value scan is flow-INsensitive and a name two statements
        bind two ways is a conflict that claims nothing, so `k = 0` followed by
        `k, v = d` (where `k` is a key) is refused by `print` — correctly, and
        for a program the model genuinely cannot classify. Declaring them as the
        kind they will hold is what makes this family a DIFFERENTIAL TEST rather
        than a refusal census, and it is why the keys are string literals: an
        integer-keyed dict makes the same two names integers and needs the same
        declaration.
        """
        # Two DISTINCT non-empty keys, and the distinctness is measured rather
        # than assumed: `rng.choice` drew `""` twice in 21 of the first 100
        # programs, a dict literal with a duplicate key has ONE pair, and the
        # 2-element unpack then fails in the ORACLE with "not enough values to
        # unpack" — 21 `generator-error`s in a sweep, which is a corpus bug and
        # not a finding about anything. `sample` from the non-empty words cannot
        # collide with itself, and `""` is out because it is a key no reader
        # distinguishes.
        keys = self.rng.sample([w for w in STRINGS if w] or ["ab"], 2)
        items = ", ".join(f'"{w}": {self.rng.randint(0, 40)}' for w in keys)
        dname = self.fresh("D")
        # The preamble copy carries the SAME two keys, for the reason every other
        # preamble copy in this generator does: the corpus reads a blob before
        # the statement that fills it on some paths, and a dict's pair count is
        # what a walk and an unpack both read first.
        self.declare(dname, '{"%s": 0, "%s": 0}' % (keys[0], keys[1]))
        self.emit(indent, f"{dname} = {{{items}}}")
        targets = [self.declare(self.fresh("k"), '""') for _ in range(2)]
        self.strings.extend(targets)
        self.emit(indent, f"{', '.join(targets)} = {dname}")
        self.emit(indent, f"print({targets[0]}, len({targets[1]}))")

    # ── word-boundary integers, under the operations that agree on them ──
    #
    # CPython's integers are unbounded and a formal value is ONE 64-bit word,
    # so a program that lets a big number grow reports the word-size MODEL as a
    # miscompile — hundreds of times, and the signal is worthless. What IS
    # answerable is the boundary arithmetic itself: `&`, `|`, `^` and `<<`/`>>`
    # are bit-for-bit the same on both sides for any pattern that FITS the word,
    # and a `>>` of a negative is an arithmetic shift in both.
    #
    # **Every literal here is inside the word, and that is the measured part
    # rather than the obvious one.** The first version of this family masked its
    # operands with `& 0xFFFFFFFFFFFFFFFF` and included 2**64-1, and the sweep
    # (`--mix bignum`, seed `sweep19c`, index 7000) found it in one program of
    # a hundred:
    #
    #     B = (((18446744073709551615 & 0xFFFFFFFFFFFFFFFF) >> 63) & 0xFFFF)
    #     print(B)        CPython 1     both images 65535
    #
    # Both halves of that are the corpus's invariant, not a lowering: the literal
    # does not fit a signed word, so it is WRAPPED to -1 (measured directly:
    # `print(18446744073709551615)` prints `-1` on both architectures), and
    # `-1 >> 63` is an arithmetic shift — while CPython's shift of the
    # UNBOUNDED 2**64-1 is logical and answers 1. `& 0xFFFFFFFFFFFFFFFF` made it
    # worse rather than better: in CPython that mask is the IDENTITY on a
    # non-negative value and in this path the mask itself is already wrapped to
    # -1, so it moved a negative operand to a positive one on one side only.
    # The mask that belongs here is the one at the END, which folds the answer
    # back inside 16 bits where the two representations agree again.
    #
    # The literals that survive are the ones with a real boundary to find:
    # 2**31-1, 2**31, 2**32-1, 2**32, 2**63-1, -2**31, -2**63+1, and two
    # arbitrary patterns. A shift count is at most 63 because CPython answers a
    # larger one and this path has to answer the same way — a count of 64 is a
    # different question, not a boundary of this one.
    BIG_WORDS = (0x7FFFFFFF, 0x80000000, 0xFFFFFFFF, 0x100000000,
                 0x7FFFFFFFFFFFFFFF, -0x80000000, -0x7FFFFFFFFFFFFFFF,
                 0xDEADBEEF, 0x123456789ABC)

    def big_expr(self):
        a = self.rng.choice(self.BIG_WORDS)
        b = self.rng.choice(self.BIG_WORDS)
        op = self.rng.choice(["&", "|", "^"])
        return f"(({a} {op} {b}) & 0xFFFF)"

    def bignum_stmt(self, indent, kind):
        name = self.declare(self.fresh("B"), "0")
        self.words.append(name)
        if kind == "big_shift":
            # A shift count near the word width is the boundary that matters: a
            # count of 63 on a one-bit value is 2**63 in CPython and the sign
            # bit here, and both wrap the same way once the low 16 bits are read
            # back out.
            src = self.rng.choice(self.BIG_WORDS)
            count = self.rng.choice([1, 7, 31, 32, 63])
            op = self.rng.choice(["<<", ">>"])
            self.emit(indent, f"{name} = (({src} {op} {count}) & 0xFFFF)")
            return
        self.emit(indent, f"{name} = {self.big_expr()}")

    # ── a comparison CHAIN ──
    #
    # `a < b < c` is a different lowering from `a < b`: CPython evaluates the
    # middle operand ONCE, `b`, and compares `a < b` then `b < c`, so a lowering
    # that re-evaluates the middle — or that reads it after a store — answers a
    # different question about the same source. `cond` has emitted a chain for a
    # long time as one of seven condition shapes; what this family adds is the
    # chain as a VALUE and the chain whose operands are a function CALL, which
    # is the shape where re-evaluating the middle operand is observable rather
    # than invisible.
    def chain_stmt(self, indent):
        pool = self.words + self.smalls
        if len(pool) < 3:
            self.new_small(indent)
            self.new_word(indent)
            return
        a, b, c = (self.rng.choice(pool) for _ in range(3))
        op = self.rng.choice(["<", "<=", ">", ">=", "==", "!="])
        op2 = self.rng.choice(["<", "<=", ">", ">=", "==", "!="])
        chain = f"{a} {op} {b} {op2} {c}"
        if self.rng.random() < 0.5:
            self.emit(indent, f"if {chain}:")
            self.emit(indent + 1,
                      f"print({self.rng.randint(0, 99)})")
            if self.rng.random() < 0.5:
                self.emit(indent, "else:")
                self.emit(indent + 1, f"print({self.rng.randint(0, 99)})")
            return
        # As a value, routed through `1 if … else 0` for the reason
        # `strmeth_stmt` gives: a bool is a WORD here, so a bare `print(chain)`
        # answers `1` where CPython answers `True` and the disagreement would be
        # the model rather than the lowering.
        self.emit(indent, f"print(1 if {chain} else 0)")

    # ── an f-string / t-string literal ──
    #
    # Generated ON PURPOSE, for the reason `--mix signed` is: it used to be a
    # SILENT wrong answer on both architectures — the literal's own source
    # spelling, printed, exit 0 — and it is a refusal now
    # (`model.interpolated_literal_refusal`). A corpus that dropped it with the
    # fix could not notice the day interpolation is implemented, which is the
    # only moment the row is for; and a corpus that never had it would have
    # called the fix unnecessary.
    #
    # The field is an INTEGER EXPRESSION, never a string, because this path has
    # no `%` conversion for a string operand and an f-string of a string would
    # be refused for a second reason (the oracle's own `TypeError`).
    def str_interp_stmt(self, indent):
        if not (self.words or self.smalls):
            self.new_small(indent)
            return
        pool = self.words + self.smalls
        literal = self.rng.choice(pool)
        prefix = self.rng.choice(["f", "F", "t", "T"])
        quote = self.rng.choice(['"', "'"])
        self.emit(indent, f'print({prefix}{quote}v={{{literal}}} '
                          f'{quote})')

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
        # The CLOSURE definitions, between the preamble and the body: a nested
        # `def` at module level is a syntax error, and a call emitted before the
        # `def` is a `NameError` in the oracle, so this is the one order every
        # generated call site is legal in — and it is also the order that lets a
        # closure read a name the preamble has already bound, which is what makes
        # the capture total rather than path-dependent.
        lines.extend(self.closure_defs)
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
    if finding == "refusal":
        # Every refusal every engine agreed on is AUDITED here, and the audit's
        # verdict is what the record carries — a clean `refusal` with no audit
        # behind it is indistinguishable from a clean `refusal` whose message
        # names a construct that is not in the program, which is the whole thing
        # this is for.
        audits = {}
        for backend, r in results.items():
            if r.get("verdict") != "refusal":
                continue
            verdict, detail = audit_refusal(text, r["diag"], ref)
            audits[backend] = (verdict, detail)
        rec["audit"] = {b: {"verdict": v, "detail": d} for b, (v, d) in audits.items()}
        rec["construct"] = {b: refusal_construct(results[b]["diag"])
                            for b in audits}
        bad = sorted({v for v, _ in audits.values()} & {"unnamed", "false"})
        if bad:
            # A refusal whose message names nothing in the program, or whose
            # CPython-checkable claim the reference refutes, is a FINDING — the
            # same sentence the tool's own docstring uses about a wrong
            # comparison: a message that is false about the file is worse than
            # no message, and a message that is silent about the file is the
            # same failure with one fewer word in it.
            rec["verdict"] = "REFUSAL-" + "+".join(v.upper() for v in bad)
    if finding.startswith(("MISMATCH", "ARM64-DIVERGES", "CODEGEN-",
                           "REFUSAL-DIVERGES")):
        # …and NOT for a `REFUSAL-UNNAMED`/`REFUSAL-FALSE`, which are findings
        # without a reproducer to shrink: the subject of the finding is a
        # MESSAGE about the program, so shrinking the program is destroying the
        # evidence, and `blame` would then attribute a message defect to a
        # construct the minimiser had just deleted.
        # Attribution runs on the MINIMISED program, never on this one: a blame
        # over a forty-statement program names every construct it contains,
        # which is the "there is a known bug in here too" reading this exists to
        # avoid. The minimised text is kept on the record so the reproducer on
        # disk is the one the verdict is about — and the record's `want` /
        # `results` are the ORIGINAL's answers, which is the half of that
        # sentence that was false: a 1966-byte finding whose file on disk is
        # 894 bytes cannot print the `3\n` the record quotes, and a reader who
        # takes the reproducer at its word spends an afternoon on a defect that
        # is not in it. So the reduction's OWN answers are measured and
        # recorded beside the original's, in `record_reduction`.
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
        record_reduction(rec, text, small, args, tmpdir, name)
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
        # …and the program the record's `want`/`results` are about, when it is
        # not the file beside it. Two files and the record is re-derivable end
        # to end; one file and the reader has to guess which of the two halves
        # of the record the reproducer is.
        original = rec.get("original_text")
        if original is not None and original != rec["text"]:
            with open(os.path.join(d, f"{name}.original.mojo"), "w") as f:
                f.write(original)
    return rec


def record_reduction(rec, original, small, args, tmpdir, name):
    """Put the reduction's OWN answers on the record, beside the original's.

    The record is about a program and its answers, and the minimiser changes the
    program while leaving the answers in place. That is a real record of a real
    verdict — the shrinker's predicate is `(verdict, diagnostic)` per backend, so
    the reduction fails the same way — and it is not a reproducer: the file on
    disk is not the program `want` and `results` describe. Both halves are
    therefore kept:

    * `original_text` — the program the verdict is about, so nothing in the
      record needs a program this file does not have;
    * `reduced_want` / `reduced_results` — what CPython and each backend say
      about the reduction, measured rather than assumed to be the same, which
      costs one build per backend on a finding (rare by construction) and buys
      the answer to the question a reader actually has;
    * `reduced_verdict` — the reduction run through the SAME `classify`, so a
      reduction that stopped disagreeing is visible in `findings.json` instead
      of in the next reader's afternoon. It is a report and never changes
      `verdict`: the finding is about the program that produced it.

    A reduction CPython cannot run has no answers at all, and that is recorded
    as such rather than as an empty answer.
    """
    rec["original_text"] = original
    ref, _err = cpython_answer(small, tmpdir, name)
    if has_oracle(ref):
        rec["reduced_want"] = {"exit": ref[0], "stdout": ref[1]}
        results = {b: run_on(b, small, tmpdir, name) for b in args.backends}
        rec["reduced_results"] = results
        rec["reduced_verdict"] = classify(results, ref[0], ref[1], args)
    else:
        rec["reduced_want"] = None
        rec["reduced_results"] = None
        rec["reduced_verdict"] = ("CPYTHON-TIMEOUT" if ref is None
                                  else "generator-error")


def frame_budget_divergence(results, refusals):
    """Whether a one-machine-refuses divergence is a fact about the FRAME.

    It very often is, and reporting it as an unqualified parity finding costs a
    reader the only thing a reader needs: whether the two backends DISAGREE about
    the program or one of them simply has less room in it. arm64's frame scratch
    is 8x x86-64's blob region (`formal/model.py::CONTAINER_BUDGET` is the
    smaller), so any container literal between the two ceilings is refused on
    x86-64 and lowered on arm64 — by design, and stated in both emitters.

    So this is a named question with a mechanical test: EVERY refusing machine
    refused with `formal/model.py::frame_blob_refusal`, and the machine that
    answered did not hit any other wall. Not "the message mentions a frame", which
    `dynamic_splat_capacity`'s capacity refusals and the spill refusals would
    also match; this is the ONE message, matched by identity of the wording the
    model builds, so a reword that moves the phrase out of it re-classifies the
    finding as a capability divergence — which is the correct failure, because
    then it IS unclassified again.

    It is a classification and not an exemption: the verdict keeps its
    `REFUSAL-DIVERGES` prefix and its per-architecture suffixes, the program is
    still saved, and `report` still prints both machines' answers. What changes is
    that a tally can subtract this class and be left with the parity findings
    that are about the language.

    Pinned by `test_formal_fuzz.py::check_frame_budget` (both emitters read the
    model's constants, the needle below is the model's own message,
    `CONTAINER_BUDGET` is the minimum, and the corpus's blob is past the smaller
    ceiling and inside the larger one) and by the two `classify` rows either side
    of this one, which are red under the un-refined classifier.
    """
    if not refusals:
        return False
    return all(FRAME_BLOB_REFUSAL_HEAD in results[b].get("diag", "")
               for b in refusals)


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
    if any(r.get("verdict") == "codegen-internal" for r in results.values()):
        # The backend talking about ITSELF — its own label table, its own
        # allocation walk — where a reader is told about the PROGRAM. Its own
        # verdict rather than a refusal's because a refusal is a claim about the
        # source and this is a claim about the compiler, so counting it as one
        # reports a compiler bug as a documented limit. See the refusal-audit
        # block above for the measurement.
        return "CODEGEN-INTERNAL"
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
        which = "+".join("X86" if b == "x86_64" else "ARM" for b in refusals)
        if frame_budget_divergence(results, refusals):
            return f"REFUSAL-DIVERGES-FRAME-BUDGET-{which}"
        return "REFUSAL-DIVERGES-" + which
    if refusals:
        # BOTH machines refusing is not automatically agreement. The two
        # architectures are ONE language implementation, so the words have to be
        # the same ones — which is what `test_formal_x86_64_parity.py`'s
        # `refuse:` rows already require of a hand-picked construct and what
        # nothing required of a GENERATED one until now. A construct one machine
        # declines in different words is a finding for the same reason a
        # construct one machine declines altogether is: the two do not agree
        # about what the program is, and one of them is wrong about it.
        #
        # Measured, and it is not a hypothetical: x86-64 refused every image
        # containing an `int(s, base)` with "internal: label 'main_ip1_end' is
        # defined twice …" while arm64 answered the program, and this branch
        # reported one clean `refusal` over the pair. The labels are folded
        # first, because "on the formal arm64 path" and "on the formal x86-64
        # path" are one sentence told by two machines and reporting them as a
        # difference would be a difference in this function rather than in the
        # backend.
        folded = {b: fold_arch(results[b].get("diag", "")) for b in refusals}
        if len(set(folded.values())) > 1:
            return "REFUSAL-DIVERGES-" + "+".join(
                "X86" if b == "x86_64" else "ARM" for b in refusals)
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
        # The construct, because one bucket called `refusal` cannot say whether
        # a sweep met one limit thirteen times or thirteen limits once — and
        # which one it was is the first thing a reader wants.
        names = sorted(set(rec.get("construct", {}).values()))
        return f"  refusal  #{rec['index']}  {', '.join(names) or 'unnamed'}"
    if v.startswith("REFUSAL-UNNAMED") or v.startswith("REFUSAL-FALSE"):
        lines = [f"  {v}  #{rec['index']}",
                 "      the refusal is a claim about the program, and this one "
                 "does not hold up"]
        for backend, r in rec["results"].items():
            if r["verdict"] == "refusal":
                a = rec["audit"][backend]
                lines.append(f"      {backend:<7} {a['verdict']}: "
                             f"{shorten(a['detail'], 200)}")
                lines.append(f"      {'':<7} said: "
                             f"{shorten(r['diag'], 200)}")
        return "\n".join(lines)
    if v.startswith("REFUSAL-DIVERGES"):
        lines = [f"  {v}  #{rec['index']}"]
        both_refused = all(r["verdict"] == "refusal"
                           for r in rec["results"].values())
        if both_refused:
            lines.append("      both refused it in different words")
        elif "FRAME-BUDGET" in v:
            # The one divergence that is a fact about the FRAME and not about
            # the two backends disagreeing about the program. Said in the line
            # rather than left for the reader to infer from the verdict name,
            # because the verdict name is the only thing a TALLY aggregates and
            # this is the only line anybody reads: it names both budgets, so
            # the next reader does not have to go and count a frame.
            lines.append(f"      one machine has less room ({M.frame_budget_phrase()}), "
                         f"so this is not a capability difference")
        else:
            lines.append("      one architecture refused what the other lowered")
        for backend, r in rec["results"].items():
            if r["verdict"] == "ok":
                lines.append(f"      {backend:<7} exit={r['rc']} "
                             f"{shorten(r['stdout'])!r}")
            else:
                lines.append(f"      {backend:<7} {r['verdict']}: "
                             f"{shorten(r['diag'], 220)}")
        lines.extend(reduction_lines(rec))
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
    if v == "CODEGEN-INTERNAL":
        # Said plainly, because the verdict is a compiler claim wearing a
        # refusal's clothes and the reader has to know that is what happened.
        lines.append("      the backend reported an internal inconsistency, "
                     "where a reader would be told about the PROGRAM")
    if v.startswith("KNOWN:"):
        # The construct(s), the document that owns each, and the two answers —
        # so the row says WHY it was set aside rather than merely that it was.
        why = "; ".join(KNOWN_DIVERGENCES.get(part, part)
                        for part in v[len("KNOWN:"):].split("+"))
        lines.append(f"      attributed to {why}")
    want = rec["want"]
    lines.append(f"      want  exit={want['exit']} {shorten(want['stdout'])!r}")
    for backend, r in rec["results"].items():
        if r["verdict"] == "ok":
            lines.append(f"      {backend:<7} exit={r['rc']} "
                         f"{shorten(r['stdout'])!r}")
        else:
            lines.append(f"      {backend:<7} {r['verdict']}: "
                         f"{shorten(r['diag'], 220)}")
    lines.extend(reduction_lines(rec))
    return "\n".join(lines)


def reduction_lines(rec):
    """The reduction's own answers, printed under the original's.

    The two blocks above are the ORIGINAL program's, and the file
    `programs/pN.mojo` is the reduction, so printing only the first is what
    §4.12 of `bugs/FORMAL_fuzz_ledger.md` measured: a reproducer on disk that
    cannot print what the record says it prints. This line is the difference
    visible without opening `findings.json`, and it says so when the reduction
    stopped reproducing — which is a fact about the SHRINKER, worth seeing here
    precisely because it does not change the finding.
    """
    if "reduced_verdict" not in rec:
        return []
    if rec["reduced_want"] is None:
        return [f"      reduced {rec['reduced_from']} -> {rec['reduced_to']} "
                f"bytes: CPython {rec['reduced_verdict']}, so the reduction has "
                f"no answers to compare"]
    lines = [f"      reduced {rec['reduced_from']} -> {rec['reduced_to']} "
             f"bytes; the reduction itself is {rec['reduced_verdict']}"]
    want = rec["reduced_want"]
    lines.append(f"      reduced  want  exit={want['exit']} "
                 f"{shorten(want['stdout'])!r}")
    for backend, r in rec["reduced_results"].items():
        if r["verdict"] == "ok":
            lines.append(f"      reduced  {backend:<7} exit={r['rc']} "
                         f"{shorten(r['stdout'])!r}")
        else:
            lines.append(f"      reduced  {backend:<7} {r['verdict']}: "
                         f"{shorten(r['diag'], 220)}")
    return lines


def audit_program(text, args):
    """`--audit`: what every architecture says about ONE program, audited.

    A sweep audits the refusals its corpus produces, and the corpus's whole
    value discipline is that it stays inside the modelled subset — so the
    interesting refusals are the ones it cannot generate, and this is how they
    are reached.  The three verdicts it can return are the three the audit can
    fail on, and a program that ANSWERS on both machines is not an audit
    failure: it is a program the path supports, which is the good outcome and is
    printed as one.

    CPython is asked first and its answer is what refutes a claim, so a
    `--audit` of a program CPython rejects still audits — that is the
    `REFUSAL_CLAIMS` case, where the message promises the exception CPython
    raises and this is where that promise is kept or broken.
    """
    tmpdir = tempfile.mkdtemp(prefix="formalaudit.", dir=args.work)
    try:
        ref, err = cpython_answer(text, tmpdir, "audit")
        print(f"CPython: {' '.join(str(ref).split())[:200]}")
        if ref is None:
            print("         the oracle TIMED OUT; a claim about CPython cannot "
                  "be checked against nothing")
        elif not has_oracle(ref):
            print("         CPython rejects this program, which is what a "
                  "claim about the exception it raises is checked against")
        bad = []
        folded = {}
        for backend in args.backends:
            r = run_on(backend, text, tmpdir, "audit")
            print(f"{backend}: {r['verdict']}"
                  + (f" exit={r['rc']} {shorten(r.get('stdout', ''), 80)!r}"
                     if r["verdict"] == "ok" else ""))
            if r["verdict"] == "ok":
                if has_oracle(ref) and r["stdout"] != ref[1]:
                    print(f"          MISMATCH: CPython prints "
                          f"{shorten(ref[1], 120)!r}")
                    bad.append("answer")
                continue
            if r["verdict"] != "refusal":
                print(f"          {' '.join(r['diag'].split())[:240]}")
                bad.append(r["verdict"])
                continue
            folded[backend] = fold_arch(r["diag"])
            verdict, detail = audit_refusal(text, r["diag"], ref)
            print(f"          construct: {refusal_construct(r['diag'])}")
            print(f"          audit: {verdict}: {detail[:240]}")
            print(f"          said: {' '.join(r['diag'].split())[:240]}")
            if verdict in ("unnamed", "false"):
                bad.append(f"{backend}:{verdict}")
        if len(set(folded.values())) > 1:
            print("REFUSAL-DIVERGES: the two machines refused it in different "
                  "words (architecture labels folded)")
            bad.append("words")
        return 1 if bad else 0
    finally:
        subprocess.run(["rm", "-rf", tmpdir])


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
    ap.add_argument("--audit", metavar="PROG",
                    help="audit ONE program's refusals on both architectures: "
                         "each engine's verdict, the construct its message "
                         "names, and whether that name is in the program "
                         "(see THE REFUSAL AUDIT).  Exits 1 when a message "
                         "names nothing, promises something CPython refutes, "
                         "or the two machines refuse it in different words")
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

    if args.audit:
        with open(args.audit) as f:
            text = f.read()
        return audit_program(text, args)

    started = time.time()
    counts = {}
    blamed = {}
    findings = []
    constructs = {}
    audits = {}
    refusals = []
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
            # The refusal MIX and its AUDIT, counted whatever the verdict turned
            # out to be.  A refusal that became a finding is still a refusal the
            # corpus produced, and a construct mix that only counts the ones that
            # passed is a mix that hides the construct it just failed on.
            for backend, what in rec.get("construct", {}).items():
                key = (backend, what)
                constructs[key] = constructs.get(key, 0) + 1
                verd = rec["audit"][backend]["verdict"]
                audits[verd] = audits.get(verd, 0) + 1
                refusals.append({"index": rec["index"], "backend": backend,
                                 "construct": what, "audit": verd,
                                 "detail": rec["audit"][backend]["detail"],
                                 "diag": rec["results"][backend]["diag"]})
            if rec["verdict"].startswith("KNOWN:"):
                key = rec["blame"][0] if len(rec["blame"]) == 1 else "+".join(
                    rec["blame"])
                blamed[key] = blamed.get(key, 0) + 1
            elif rec["verdict"].startswith(("MISMATCH", "ARM64-DIVERGES",
                                            "CODEGEN-", "generator",
                                            "REFUSAL-")):
                findings.append(rec)
    finally:
        subprocess.run(["rm", "-rf", tmpdir])

    with open(os.path.join(args.work, "findings.json"), "w") as f:
        json.dump({"args": vars(args), "counts": counts,
                   "refusal_audit": audits,
                   "findings": [{k: v for k, v in r.items() if k != "text"}
                                for r in findings],
                   "refusals": refusals,
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
    if constructs:
        print("  refusals by construct (the mix this corpus reached, per backend):")
        for (backend, what), n in sorted(constructs.items(),
                                         key=lambda kv: (-kv[1], kv[0])):
            print(f"    {n:5d}  {backend:<7} {what}")
        # The audit's own tally, `no-predicate` included and always: a sweep that
        # says nothing about how much of its refusal surface it checked is
        # indistinguishable from one that checked all of it and found nothing.
        print("  refusal audit: " + ", ".join(
            f"{v}={audits.get(v, 0)}" for v in AUDIT_VERDICTS))
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

#: The refusal audit's own verdicts, in the order a summary prints them.  Named
#: here rather than derived from the records so the line is the SAME four fields
#: whether the sweep saw four kinds of refusal or none: a run that audited
#: nothing has to be able to say so, and a field that appears only when it is
#: non-zero cannot.
AUDIT_VERDICTS = ("true", "unnamed", "false", "no-predicate")



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