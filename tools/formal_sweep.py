#!/usr/bin/env python3
"""Sweep every *.py / *.mojo under the repo through `build --formal` (arm64 Mach-O
by default; `--arch x86_64` sweeps the x86-64 machine subset instead).

Mojo is a Python superset, so .py files are valid inputs. Every file that did
not PASS gets one line, prefixed with the CLASS of its verdict; PASS lines are
counted but not printed. Summary at the end: the per-class counts, the
headline codegen-coverage rate over the files that could have answered, and
the CAS accounting. Exit 0 only if nothing was wrong in a way that is a finding
about the source; see EXIT STATUS below.

Built with --no-prove, so what this measures is the arm64 CODEGEN's language
coverage: which source constructs the model can lower. Proof generation and
Lean typechecking are a separate, much narrower capability with their own
coverage (and their own failures, several of them about function *shapes*
rather than about anything the code generator could not lower) — they are
exercised by test_formal.py / `make check-formal`, not by this sweep. With
proofs on, a single unmodellable shape anywhere in a file fails the whole
file and masks which codegen gaps are real.

CLASSES — why the pass rate is not just PASS/total
-------------------------------------------------
A build either says something about the SOURCE or it does not, and a sweep
that adds the two together is measuring the wrong thing. On the default repo
sweep 212 of 279 files used to be reported as one undifferentiated FAIL, and
about 170 of those were not codegen findings at all: they were one line,
repeated —

    build: fire.py imports 'os', which is a host module (CPython standard
    library), which has no Mojo source for this backend to compile

That is a fact about the TARGET, not about the backend's ability to lower a
construct, and formal/imports.py says so in its own comment ("a statement about
the target, not a module-resolution failure"). Folded into a single
FAIL bucket it did two kinds of damage at once: it buried the real findings,
and it made the headline a number whose denominator was mostly host-platform
facts. So every verdict now carries a class:

  pass                              built, and every symbol it binds is in a
                                    library on its own link line that dyld can
                                    load (see the probe's own comment for what
                                    that does and does not prove)
  codegen                           the backend REFUSED a construct in this
                                    file — THE FINDING, the only class whose
                                    count is a gap in the backend, in this file
  codegen/dependency                the backend refused a construct in a module
                                    THIS FILE IMPORTS, so this file did not
                                    build either. Counted separately, and
                                    never as a gap in this file: the class
                                    name, the printed line (which carries the
                                    whole chain and the terminal reason) and
                                    the summary's breakdown all say the gap is
                                    one level down. See THE CHAIN below for
                                    why it is in the denominator at all
  backend-crash                     the backend RAISED instead of refusing —
                                    a bug in the compiler's own plumbing, not
                                    a claim about the construct. Still a
                                    failure (exit 1), still printed, still
                                    never cached, and in no rate: a sweep that
                                    reported 74 files as `codegen: the backend
                                    raised: ValueError: not enough values to
                                    unpack` was reporting another agent's
                                    half-finished edit as a coverage gap
  not-answerable/host-import        imports a CPython host module that has no
                                    Mojo source anywhere: a fact about the
                                    TARGET, not a gap in the backend. The
                                    summary splits it into the modules a
                                    Mojo-side implementation could in
                                    principle provide (WORK — `os`, `sys`,
                                    `math`, `struct`, `time`, `json`, `re`)
                                    and the ones that need a host process, an
                                    embedded interpreter or a kernel object
                                    this image does not have (permanent:
                                    `subprocess`, `ctypes`, `asyncio`,
                                    `threading`, `socket`). Both are
                                    not-answerable today and NEITHER is in
                                    any rate; the split sizes the work and
                                    changes no number on purpose, because
                                    moving the first group into the
                                    denominator would improve the headline
                                    without anyone writing code
  not-answerable/unresolved-import  imports a module that is neither host nor
                                    present in this backend's module set
                                    (a sibling module the resolver cannot see
                                    from this file's directory, a third-party
                                    package). Also unanswerable here, but the
                                    reason is NOT provable from the file
                                    alone, so it is reported separately with
                                    the module named rather than merged into
                                    the host class
  not-answerable/unresolved-extern  builds, but no library on its link line
                                    provides a symbol it binds, so the image
                                    is refused at load (or at the first call to
                                    the symbol). Real, and not coverage — a
                                    call to a runtime the image never links,
                                    typically, rather than a codegen gap
  not-answerable/target-limit       calls an entry point of the gimple C
                                    runtime (`mojo_print`, `mojo_sqlite3_open`,
                                    …) by name, which a freestanding image
                                    cannot bind: the backend refuses it
                                    instead of emitting a call to a symbol
                                    nothing defines, and the refusal is a fact
                                    about the TARGET (libSystem and nothing
                                    else), not a gap in the backend
  not-answerable/system-module-call  CALLS into a host module that has no Mojo
                                    source on any path. The sibling of
                                    host-import one level down, and its own
                                    class for a specific reason: the fallback
                                    for a build message that names no module
                                    is `codegen`, the class whose count IS a
                                    gap in the backend and the class that
                                    fails a run — so a fact about the target
                                    arriving there is the most expensive
                                    misclassification this tool can make. It
                                    is 0 on this tree (the resolver always
                                    reaches the import first) and the rule
                                    behind it is live
  tool                              timeout, unreadable file, or an internal
                                    exception in the sweep or the build
                                    driver — no verdict about the source was
                                    reached at all. Also the two ways a file
                                    is killed by THIS TOOL's per-file memory
                                    ceiling rather than by its source:
                                    `memory-killed` (memcap reported a breach,
                                    with the measured peak) and `wrapper-died`
                                    (memcap itself was killed before it
                                    reported anything, so the build's own
                                    verdict was never observed — see
                                    CAUSE_WRAPPER_DIED)
  unknown                           a message shape this tool does not
                                    recognise. Deliberately its own bucket
                                    rather than a fallback into `codegen`:
                                    a new wording from formal/ must show up as
                                    a visible hole in the classifier, never as
                                    silent coverage

Only `pass`, `codegen` and `codegen/dependency` are ANSWERABLE — the classes in
which the backend actually got to look at constructs. The headline is therefore
the codegen-coverage rate over the answerable files, and the summary says in
words which files those are. Nothing is hidden: the other classes keep their
own counts, every one of their files keeps its own printed line, and the
per-class counts sum to the total.

THE CHAIN — a refusal in a dependency, and what it is for the importer
-----------------------------------------------------------------------
formal/build.py reports the whole import chain when a dependency fails to
build, once per level:

    build: write.mojo imports 'std.format', which cannot be built either:
    binary_heap.mojo: formal dylib has no public functions: …

That is strictly better diagnostics than the message it replaced, and it is
also a shape the classifier had never been taught: it read the outermost layer,
saw an import it could not resolve, and filed 204 stdlib files as `unknown` —
the largest class in the default sweep, all of it the instrument throwing away
the terminal reason, which is the only part of the message that says anything
about the backend. Those 204 files were in no rate at all, so the headline was
computed on a population that silently dropped 35% of the sweep.

The position this tool takes, stated once so a reader does not have to infer it
from a class name: a chained refusal is a FAILURE of the importing file, and
the importer belongs in the answerable denominator, but it is NOT a finding
about that file.

  · In the denominator, because a file that did not build is not a file the
    backend can handle, and because the alternative — leaving these files out
    of every rate, which is the bug being fixed here — reports a number whose
    population is a third of the sweep and says nothing about why.
  · Not a finding about the importer, because the construct the backend
    refused is not in it. Reporting it as `codegen` would point a reader at a
    file that is fine; `codegen/dependency`, the printed chain, and the
    per-family breakdown say where the gap actually is, and `report_history`
    will name any file whose class moves when a rule changes.
  · The terminal reason still decides the class when it is a fact about the
    TARGET (a host import, an unresolvable module, a `mojo_*` runtime call):
    then the importer is unanswerable for the same reason, because it cannot
    be built here either.


SCOPE — why the not-answerable files are still swept
----------------------------------------------------
They stay. The alternative (prune them from the default scope) would shrink
the denominator in exactly the way this tool's scope reporting exists to
prevent — a run that quietly covered fewer files looks like a clean run — and
it would delete data to improve a number, which is the one move that makes a
coverage report worthless. The facts that put a file in that class are also
permanent rather than per-run noise (`os` is not going to grow a Mojo source
next week), so the class is stable, countable, and worth keeping in front of
the reader. What changes is only that these files stop being counted as
failures.

VERDICT HISTORY
---------------
Each run publishes a ledger of path -> class and, when it finds one from an
earlier run, prints how the verdicts moved: every file whose class changed is
accounted for by name, in both directions, so a rule change can never quietly
turn a reported failure into a differently-counted one.

EXIT STATUS
-----------
  0  no codegen finding (in a file or in a dependency), no backend crash, no
     `tool` failure, no `unknown` verdict
  1  at least one of those (a real finding, a backend that fell over, or a
     file the sweep could not answer for a reason that is its own problem)
  2  the sweep did not run (no input files, or another sweep of the same
     architecture holds the lock)
  3  the sweep was INTERRUPTED (SIGINT/SIGTERM). Everything it classified was
     printed and published, and the summary says how much of the scope it
     reached. Its own status rather than 1's because "you stopped it" and "it
     found something" are different facts, and a caller retrying on 1 alone
     would retry a run that needs no retrying

`not-answerable` never affects the exit status in either direction: it is a
permanent property of the source and the target, so failing a run over it (or
passing one because of it) would both be wrong. This is a deliberate change
from the older contract, where any FAIL at all meant exit 1 — with 170
permanent facts in the FAIL bucket that contract could not distinguish "the
backend regressed" from "this file imports os".


SURVIVING, and why a sweep needs to
------------------------------------
Two things here exist because of one measured failure, and both are worth
stating as mechanisms rather than as features.

A sweep is `jobs` compiler processes at once, and a compiler process recurses
through a module closure. Nothing about that is bounded, so ONE file could take
the whole run down with it — and on 2026-10-01 one did: the arm64 sweep died of
an external SIGKILL and its output file was the 5-line header and nothing else,
so 623 files produced no classifications at all. The fix is the per-file
ceiling (`-M`, MEMCAP_GB): every build runs under `tools/memcap.py`, a file
that exceeds
it is killed and classified `tool`/`memory-killed` WITH its measured peak, and
the sweep continues. It is not a timeout wearing another name: a timeout says
raise -t, a memory kill says this file's build is a different shape from every
other one and running it wider will not help. Measured on the tree where the
sweep was killed, no file exceeded 0.2 GB and the whole -j18 sweep peaked at
1.97 GB, so the 4 GB default is an order of magnitude above everything observed
— it is here for the file nobody has run yet.

And a run that is killed anyway must not lose what it already knows. Results are
printed as each file is classified, and printed with an explicit flush, because
a redirected stdout is a block-buffered FILE: the previous design built the whole
table and printed it after the pool drained, so an interrupted run printed
nothing at all however far it had got, which is precisely what made the 2026-10-01
kill undiagnosable. A partial run publishes a ledger under its own extension
and marks itself partial, so the next run's history diff is against the last
COMPLETE run and a missing file is never reported as a verdict that changed.

And a run that is TOLD to stop must stop, which is a different property and was
also false: every file is submitted up front, so the executor's queue is the
whole run, and a plain `return` from the reporting loop let `__exit__`'s
`shutdown(wait=True)` walk that queue to the end (measured: builds still
starting ten minutes after the signal, and a second SIGTERM needed to die).
SIGINT/SIGTERM now cancels what has not started, refuses to start a build once
the flag is set, and then collects the `-j` builds that were in flight — which is
the half that keeps the partial ledger and the CAS from disagreeing about how
far the run got, since `run_one` publishes before it returns. See
`_stream_results`.

Verdicts are cached in the CAS (cas.formal_build_key: source bytes + the
formal backend's own sources + the interpreter + the build flags + this tool's
own bytes — see _criteria_id — + the IMPORT CLOSURE the build reads, see
_imports_digest), so a re-run with nothing changed reads a file per file
instead of recompiling. Editing anything under formal/, the parser, mojo/middle/,
or any module in the file's own import closure invalidates it. The cache stores
the raw build verdict; the
class is recomputed from it on every run, so a cached entry can never be
reported under a class the current rules would not assign it — which is the
half of the contract that matters now that a class is a function of the stored
TEXT: a verdict written under older rules is re-read and re-classified by the
rules in force now, and the stored bytes contain no class to go stale. A crash
is not stored at all (the traceback that decides its class is not in the
stored bytes), so it stays a miss until the key changes; a stale `ok` must
never outlive the crash that replaced it.

The one thing deliberately NOT published is a verdict for an image that links
a formal dylib, because that verdict depends on the dylib and the dylib is not
in the key (it lives at a fixed path keyed by module name alone, so the two
architectures overwrite each other's copy). Such a file is rebuilt every run —
one file today — and the accounting line says so rather than leaving the
count unexplained. This narrows what is cached; nothing new is.

The default scope is this repo plus the stdlib's std/ (the stdlib tree lives
outside the repo and is far larger); pass --no-stdlib for the repo alone, or
name roots explicitly:

  python3 tools/formal_sweep.py -t 300 /path/to/mojo/stdlib

`-t` is a bound PER POPULATION, which is the point of the two of them being
different populations at all (see `Timeouts` for the measurements that put them
apart): `-t SECONDS` is one bound for the whole run, `-t POP=SECONDS`
is one population's, and a run that gives both gets a repo-root sweep and a
stdlib sweep that are each measured at a bound that means something:

  python3 tools/formal_sweep.py -t repo=600 -t stdlib=120

The architecture is a cache-key input, not a global: `--arch` adds
`--backend=<arch>` to the build flags, and those flags are what
cas.formal_build_key folds in, so an arm64 verdict is never served for an
x86_64 sweep (or the reverse).

Usage:
  python3 tools/formal_sweep.py [-j N] [-t SECONDS | -t POP=SECONDS]
                                [--arch x86_64] [paths...]
"""
import argparse
import collections
import concurrent.futures
import ctypes
import datetime
import importlib
import json
import os
import re
import signal
import struct
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cas
import procrun
from formal import macho_linker as ML

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRE = os.path.join(REPO, "fire.py")
# The per-file memory ceiling, as an EXECUTABLE and not a copy of one: see
# MEMCAP_GB below for why this is tools/memcap.py and not a private watchdog.
MEMCAP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memcap.py")

# Every build flag that changes the artifact, and therefore the cache key
# (cas.formal_build_key folds them in). The arch is one of them: the two
# backends lower the same AST to different code, so a verdict from one says
# nothing about the other, and folding `--backend=` in here is what keeps the
# two sweeps' verdicts in separate cache entries. The same tuple drives both
# the cache key and the argv below, so the two cannot drift apart.
def build_flags(arch: str) -> tuple:
    return ("--formal", "--no-prove", f"--backend={arch}")


def interpreter_diagnosis() -> str:
    """Empty when this interpreter can load the backend; the diagnosis if not.

    Every file in a sweep is answered by `fire.py build --formal` in a child of
    THIS interpreter, so an interpreter that cannot import the backend cannot
    answer one file, and it fails in the least visible way there is: each child
    dies on the same exception inside an import, the classifier reads a
    traceback ending in a build failure as `backend-crash`, and the run comes
    back as N findings about the compiler's own plumbing and zero about any
    source. Measured on this machine with the `python3` a shell finds by
    default — Xcode's 3.9.6, because it is what `python3` resolves to before
    any Homebrew directory is on PATH:

        $ python3 tools/formal_sweep.py --no-stdlib --arch x86_64 -j2
        BACKEND-CRASH: abfulltest_driver.mojo  (the backend raised: TypeError:
          unsupported operand type(s) for |: 'type' and 'NoneType')
        ... 392 of them, one per file, in about a minute ...
        backend-crash                 392

    which reads as "this backend is broken in every file at once" and is
    actually "no file was built at all". The refusal is not in the backend's
    coverage and must not be counted in it, so the check is here, before any
    build, and it exits 2 — the documented status for a sweep that did not run.

    It imports the module rather than testing `sys.version_info` against a
    number, because the number is not written down anywhere in this repository
    and a hard-coded floor would be a second, wrong one: what the sweep needs is
    "the backend imports", and that is a fact this interpreter can answer.
    """
    try:
        importlib.import_module("formal.build")
    except Exception as e:
        return (
            f"this python cannot import the formal backend, so no file in this "
            f"sweep could have been built: {type(e).__name__}: {e}\n"
            f"  interpreter: {sys.executable} (python "
            f"{sys.version.split()[0]})\n"
            f"  the backend needs a python that can evaluate a PEP 604 "
            f"annotation (`str | None`) at def time — 3.10 or newer. On macOS "
            f"`python3` is Apple's 3.9 unless a newer one comes first on PATH, "
            f"so run this with the interpreter the suite uses, e.g.\n"
            f"    /opt/homebrew/bin/python3 {sys.argv[0]} ...\n"
            f"  (or put that directory first on PATH). Nothing was swept and "
            f"nothing was cached; every file would have been classified "
            f"`backend-crash`, which is a fact about this interpreter and not "
            f"about any source.")
    return ""


def _criteria_id() -> str:
    """This tool's own content, as a cache-key input.

    A cached entry is a verdict, and a verdict is a function of the source AND
    the rules this tool applies to it. Without this in the key, tightening a
    check (e.g. also requiring the image's imports to be dyld-resolvable)
    silently keeps serving every verdict the OLD rules produced — which is how
    a file with 31 unresolvable imports stayed scored PASS after the check
    that would have caught it was added."""
    with open(os.path.abspath(__file__), "rb") as f:
        return cas.hash_parts(f.read())


def _imports_digest(path: str) -> str:
    """The digest of every source this file's build reads BESIDES itself.

    `formal/imports.py`'s, called here rather than reimplemented, because it
    walks the closure with the SAME `imported_modules` / `resolve_module_path`
    pair the build walks with and cannot therefore resolve a module the build
    would not have compiled. `formal_fingerprint()` is a `.py` glob over
    `formal/**`, so `formal/hostmods/*.mojo` — the one place a module edit
    lands in practice — was not in the key at all, and a sweep run right after
    a fix to one of them reported the fix as having done nothing.

    Returned as `''` if the walk itself cannot run, which leaves the key equal
    to the pre-fix one rather than failing the file: the build is the authority
    on whether a file is answerable, and this must never be the thing that
    decides it. (`import_closure_digest` already returns `''` for an unreadable
    or unparseable file, which is the common case here.)
    """
    try:
        from formal.imports import import_closure_digest
        return import_closure_digest(path)
    except Exception as e:  # noqa: BLE001 — see the docstring
        if os.environ.get("FORMAL_SWEEP_VERBOSE_IMPORTS"):
            print(f"  (import digest unavailable for {path}: "
                  f"{type(e).__name__}: {e})", file=sys.stderr)
        return ""


# ── Verdict classes ──────────────────────────────────────────────────────────
# See the module docstring for why a verdict is not a boolean. The rule the
# whole design turns on: only `pass` and `codegen` are classes in which the
# backend actually got to look at the file's constructs, so only those two are
# ANSWERABLE, and the headline rate is over exactly those.
#
# WHERE THESE RULES LIVE, AND WHY THAT IS THE CACHE KEY'S BUSINESS
# ------------------------------------------------------------------
# A classification rule is a tightening of what counts as coverage, which is
# precisely the thing _criteria_id() exists for: it hashes this file's own
# bytes into every key, so these rules are in the key AUTOMATICALLY — there is
# no rule list anywhere that could be added to without being remembered, which
# is the failure mode that mechanism was built to make impossible. Editing a
# rule (or a comment) below invalidates every cached verdict, and that is the
# intended behaviour, not a cost to work around.
#
# The second half is that the rules are applied AFTER the cache, never inside
# it. The CAS entry is the raw build verdict (ok, detail); classify() re-derives
# the class from it on every run, hits included. So the invalidation above is
# belt-and-braces rather than the only thing standing between a stale rule and
# a wrong report: a stale entry left over from older rules cannot be reported
# under a class the current rules would not assign it, because the current
# rules are what assign it.
CLASS_PASS = "pass"
# BUILT, and it rests on ADMITTED HOST CONTRACTS.  A separate class from
# `pass` because a `pass` is a claim this backend can make on its own -- the
# image built and every symbol it binds is on its own link line -- and a file
# that also needed a second process, a thread or a dynamic loader has not had
# that claim made for it.  Counting it as a `pass` would make the headline rate
# a measure of how much the sweep was willing to believe.
#
# It IS in ANSWERABLE, deliberately: the backend got to look at the file's
# constructs and answered them.  What it is NOT is in the numerator, so the
# rate can only go DOWN as more of the tree is admitted against, which is the
# direction a rate about provability has to move in.
CLASS_ADMITTED = "built-with-admitted-contracts"
CLASS_CODEGEN = "codegen"
CLASS_CODEGEN_DEP = "codegen/dependency"
CLASS_HOST = "not-answerable/host-import"
CLASS_UNRESOLVED = "not-answerable/unresolved-import"
CLASS_EXTERN = "not-answerable/unresolved-extern"
CLASS_TARGET = "not-answerable/target-limit"
CLASS_SYSCALL = "not-answerable/system-module-call"
CLASS_TOOL = "tool"
CLASS_CRASH = "backend-crash"
CLASS_UNKNOWN = "unknown"

# Report order: the findings first, then the reasons there is none, then the
# buckets that mean the tool itself did not finish the job.
CLASS_ORDER = (CLASS_PASS, CLASS_ADMITTED, CLASS_CODEGEN, CLASS_CODEGEN_DEP,
               CLASS_HOST, CLASS_UNRESOLVED, CLASS_EXTERN, CLASS_TARGET,
               CLASS_SYSCALL, CLASS_CRASH, CLASS_UNKNOWN, CLASS_TOOL)
# ANSWERABLE = the classes in which the backend got to look at the file's
# constructs and returned a verdict about them. `codegen/dependency` is in it
# deliberately (see the position taken in the module docstring): a file whose
# DEPENDENCY the backend refused did not produce a binary and would have if
# the backend lowered that construct, so counting it as a file the backend can
# handle would be a false PASS by omission. `backend-crash` is NOT in it: a
# crash is the backend's own plumbing falling over, which says nothing about
# the construct it was looking at, and letting it into the denominator would
# report a compiler bug as a coverage gap (B4's 74-file sweep, in which every
# one was a mid-edit artefact of another agent's work).
ANSWERABLE = frozenset((CLASS_PASS, CLASS_ADMITTED, CLASS_CODEGEN,
                        CLASS_CODEGEN_DEP))
# Classes that make the run exit non-zero. A codegen finding (in this file or
# in a dependency it needs) is real; CLASS_CRASH is real too and is counted and
# printed like any other finding, because a crash that is allowed to pass
# quietly is how a broken backend gets reported as a clean sweep.
# CLASS_UNKNOWN is a gap in this file's rules (visible, because absorbing it
# into `codegen` would invent coverage) and CLASS_TOOL is a gap in the run (a
# file nobody answered for is not a file that passed).
DIRTY = frozenset((CLASS_CODEGEN, CLASS_CODEGEN_DEP, CLASS_CRASH,
                   CLASS_UNKNOWN, CLASS_TOOL))

# `run_one` reports WHY an outcome is not one of the build's own diagnostics,
# rather than this function trying to recognise a timeout or a traceback inside
# a free-text string. The build's message shapes are the only thing classified
# by matching.
CAUSE_TIMEOUT = "timeout"
CAUSE_UNREADABLE = "unreadable"
CAUSE_TOOL_ERROR = "tool-error"
# The build was KILLED for memory, by this tool's own per-file ceiling. This is
# the cause that makes the sweep survivable at all, and it is its own label
# rather than a flavour of `timeout` because the two demand opposite responses:
# a timeout says raise -t, a memory kill says this file's build is a different
# shape from every other one, and re-running it wider will not help.
#
# 2026-10-01: the arm64 sweep died of an external SIGKILL with nothing in its
# output but the 5-line header, so not one file was classified. One file's
# build being able to take the whole run down with it is what that made
# possible, and the fix is the ceiling that produces this label: the file is
# killed, classified, and the sweep continues — `TestPerFileMemoryCeiling`
# in `test_formal_sweep.py`.
CAUSE_MEMORY = "memory-killed"
# The per-file ceiling's WRAPPER died before it reported an outcome: memcap
# printed its banner and nothing else, so the build's own verdict was never
# observed. A machine fact, in `tool` for the same reason a timeout is, and its
# own label because the two are told apart by evidence rather than by shape: a
# breach is memcap saying the ceiling fired, this is memcap not saying anything,
# and a reader who is told "killed at the ceiling" about a build that was never
# measured against it will go and look for a memory bug that is not there.
#
# 2026-10-02: six files per architecture in the b6 sweep carried memcap's
# banner as their `codegen` "refusal" — the class whose count is a gap in the
# backend — and were PUBLISHED to the CAS, so a machine fact survived the run
# that observed it. The files are not memory hogs: `bit/mask.mojo`, one of the
# six, builds in 0.1 GB and is refused for a real reason in three minutes.
# bugs/FORMAL_sweep_memcap_death_is_filed_as_codegen.md.
CAUSE_WRAPPER_DIED = "wrapper-died"
# The image BUILDS, but this host cannot check whether its imports resolve.
# Not a finding about the image and not a fact about the target: it is a gap in
# the RUN. Its own label because the neighbouring classes give the opposite
# advice — an `unresolved-extern` says the link line is wrong, which would send
# someone to fix an image that is already correct.
#
# 2026-10-01: this label meant "the dylibs are of the other architecture, and
# dlopen can only load this process's own", and the fix was to say so instead of
# calling it a load failure. That was necessary and not sufficient: refusing to
# answer filed 7 correct x86-64 images with no verdict at all, so the x86-64
# pass count was a floor rather than a number, and the answer was still sitting
# in the file.
#
# 2026-10-02: a dylib this process cannot dlopen is now looked up in its
# EXPORT TRIE — the same table dyld resolves against — so being of the other
# architecture no longer leaves a name unchecked (`_exports`). What is left here
# is what really is unknowable from this process: an export table this host
# could not read, or a host architecture it could not establish. Each row names
# which, because the advice differs and the old wording would have described
# neither.
CAUSE_FOREIGN_ARCH = "unverifiable-here"
# The build driver raised instead of refusing a construct. Which side of the
# line that falls on is decided by the DEEPEST frame of the traceback, not by
# the message: fire.py prints `build: {e}` for a FormalBuildError *and* for
# any other exception, so the message shape cannot tell the two apart, but the
# traceback can, and it is the difference between "the backend cannot lower
# this" (a finding) and "the compiler's own plumbing broke" (not one).
CAUSE_BACKEND_CRASH = "backend-crash"
CAUSE_DRIVER_CRASH = "driver-crash"

_TRACEBACK_MARK = "Traceback (most recent call last)"
_FRAME_RE = re.compile(r'^\s+File "([^"]+)"', re.M)

# Substrings of the messages formal/build.py and formal/imports.py raise for a
# failed import. All raise ImportBuildError with one wording for one condition
# (build.py's own comment says two messages for one cause is how a real failure
# ends up filed under the wrong heading), so these markers partition that error
# space between them. Matching the wording rather than re-deriving the condition
# is deliberate: formal/ owns the condition, and a second copy of HOST_MODULES
# here would be a list that silently rots. Nothing keys off the exact template —
# an unrecognised shape falls into CLASS_UNKNOWN below rather than being guessed
# at. There are THREE markers rather than two because
# `formal/imports.py::unresolvable_import_error` has three wordings, not two.
_HOST_MARK = "host module (CPython standard library)"
_UNRESOLVED_MARK = "not a stdlib or sibling module"
# THE THIRD of the three wordings `formal/imports.py::unresolvable_import_error`
# can produce, and the one this pair of markers above did not know about. It is
# the SAME class of fact — a CPython stdlib module with no Mojo source in this
# tree — said apart from `_HOST_MARK`'s on purpose, because the two differ in
# something a reader acts on: a name in `host_module_tier`'s `modelled` or
# `admitted` tier has an owner and a next step, and a name in NO tier has
# neither (`bugs/FORMAL_stdlib_module_names_are_not_classified.md` is the queue;
# `formal/imports.py`'s own comment says the split is deliberate).
#
# Measured on the 2026-10-03 sweep, and the cost of not having this marker was
# four files in `unknown` — a class that is in NO rate — with the reason printed
# in full on the row: `test_ast_formal.py` and `test_no_new_container_casts.py`
# (`tokenize`), `test_formal_platform.py` (`plistlib`), `tools/codeindex.py`
# (`sqlite3`). The backend was RIGHT about all four; this tool could not read it.
# Classified as CLASS_HOST, which is the not-answerable bucket the fact belongs
# to, and deliberately NOT added to `IN_REACH_HOST_MODULES`: this sweep reports
# a build's verdict and does not claim a tier for a name the build says it cannot
# classify. A name that gains a tier moves out of here on its own, because the
# next build stops refusing it.
_STDLIB_UNCLASSIFIED_MARK = "a CPython standard-library module"
_EXTERN_MARK = "import(s) dyld cannot resolve"
# The SAME fact, caught a step earlier. `formal/build.py`'s bind audit refuses a
# build whose image would bind a symbol no linked library provides, and says so
# in these words; the marker above is this tool's OWN post-build probe finding
# the same thing in a binary that was produced anyway. Both are
# "no library on the link line provides a symbol this image binds", so both
# belong in CLASS_EXTERN — which is `not-answerable`, and is in neither the
# answerable denominator nor DIRTY.
#
# Without this rule the build-time refusal falls through to `codegen`, and that
# is the most expensive misclassification this tool can make: it counts as a gap
# in the backend, it deflates the coverage rate, it makes the run exit 1, and it
# points the next reader at a construct the backend could not lower when the
# backend was in fact RIGHT to refuse. The dylib path has always produced this
# message; the executable path (`build --formal`) started producing it when
# agent [4] extended the same audit there, so the classifier was half-fixed
# before and is now fully wrong.
_EXTERN_BUILD_MARK = "symbol(s) that nothing provides"
_IMPORT_RE = re.compile(r"imports '([^']+)'")
# ONE message naming SEVERAL of a file's unresolvable imports, one indented
# line each, which is what `formal/imports.py`'s `unresolvable_import_errors`
# produces when a file has more than one. It exists because `_IMPORT_RE` alone
# cannot read it: `mods[-1]` below is right for a CHAIN (the innermost import is
# the one with no source) and wrong for this shape, where every name is at the
# SAME level and the last one is whatever sorted last. That is the measurement in
# `bugs/FORMAL_admitted_contracts_sweep_measurement.md` — a per-module
# breakdown drawn from a diagnostic that named one of a file's blockers decided
# by the order its imports are written in.
#
# Matched on the LEAD, which is the part only this shape has, so a chained
# message (one import wrapping another) cannot be read as a list of siblings.
_MULTI_IMPORT_RE = re.compile(
    r"imports (?P<n>\d+) modules this backend cannot build[^\n]*\n"
    r"(?P<body>(?:[ \t]+.*\n?)*)")
# A quoted dotted identifier, whatever the sentence around it says. Used only
# as a CANDIDATE, confirmed against the file's own source below — a codegen
# diagnostic quotes nothing of this shape (`self.<field>` is in backticks), and
# guessing from a message template alone is how a reworded error silently
# becomes coverage.
_QUOTED_NAME_RE = re.compile(r"'([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)'")
_EXTERN_COUNT_RE = re.compile(r"(\d+) import\(s\) dyld cannot resolve")
_EXTERN_BUILD_COUNT_RE = re.compile(r"(\d+) symbol\(s\) that nothing provides")

# ── The dependency chain ─────────────────────────────────────────────────────
# formal/build.py wraps a DEPENDENCY's own error inside the importer's, once
# per level, so one message can be a chain:
#
#   build: write.mojo imports 'std.format', which cannot be built either:
#   binary_heap.mojo imports '.collections', which cannot be built either:
#   _heap.mojo: formal dylib has no public functions: …
#
# Wave 1 added that wrapper because it is better diagnostics (the old message
# named a module that resolves perfectly well). The cost was here: the
# classifier read the OUTERMOST layer, saw an import, and filed 204 stdlib
# files as `unknown` — discarding the terminal reason, which is the only part
# of the message that says anything about the backend. So the chain is peeled
# before anything is classified, and it is peeled as a SHAPE, not as a list of
# messages: one hop pattern, applied until it stops matching, at any depth.
_CHAIN_RE = re.compile(
    r"^(?:build: )?[\w.+-]*\s*imports '(?P<mod>[^']+)', which cannot be built "
    r"either: ")
# formal/imports.py prefixes a dependency's own error with the file it came
# from (`f"{os.path.basename(source_path)}: {e}"`), so the innermost layer is
# "<file>: <reason>". Stripped for matching only; the printed line keeps it,
# because the file the refusal is really about is the useful half of it.
_FILE_PREFIX_RE = re.compile(r"^(?P<file>[\w.+-]*\.(?:mojo|py)):\s+")
# fire.py's own prefix on a build error, whichever way it exited.
_BUILD_PREFIX = "build: "

# ── Refused by name, outside the freestanding target ────────────────────────
# B3 made both backends REFUSE a call to the gimple C runtime's own entry
# points (`mojo_print`, `mojo_sqlite3_open`, …) instead of emitting a BL to a
# symbol nothing defines. That is a fact about the TARGET — a formal image is
# freestanding and links libSystem only — so by this file's own definitions it
# is `not-answerable`, not a gap in the backend, and filing it as `codegen`
# overstates what backend work would buy.
#
# Keyed on formal/model.py, not on the wording: the name is taken from the
# message and handed to `is_gimple_runtime_builtin` (the predicate both
# backends themselves call), and the text is then required to BE that name's
# refusal, asked of formal/model.py rather than matched here. So a reworded
# message cannot silently change class — it fails this test and falls to
# `unknown`, which is the whole point of keeping that class. What is NOT
# copied into this file is the `mojo_` prefix: a second copy of it would be a
# list that silently rots the day formal/ changes it.
_TARGET_LEAD_RE = re.compile(r"^([A-Za-z_]\w*) is an entry point of")
_TARGET_PROBE = 40      # characters of the model's own text to require

# ── Construct refusals, by family ───────────────────────────────────────────
# The class of every one of these is `codegen`; the family is what makes the
# per-class breakdown say WHY, and it is the vocabulary the summary groups by.
# Built from the distribution the backend actually produces (the stdlib sweep's
# 204 unclassifiable files reduce to four families: a method call on a value,
# `multi-index subscript`, `has no representation on this path`, and
# `has no public functions`), not from a list of every message formal/ can
# raise. An unrecognised refusal is still a refusal — the class comes from the
# shape (no import, no target limit, the build spoke about the code) and the
# family defaults to "other", which keeps the bucket honest instead of
# pretending the table is complete.
_SYSCALL_MARK = "no Mojo source on any path"
_MEMBER_RE = re.compile(r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)")

# The frame-address families, grouped. Measured on the arm64 sweep of
# 2026-09-28: 130 in-file codegen findings, 104 distinct message texts, which
# reduced to 13 shapes. Before this pass 123 of the 130 were ONE bucket called
# "other refusal", so the sweep could not answer "what is left" — it could only
# say that 26.0% of the denominator was blocked and name none of it.
#
# Most of what it found is ONE design defect wearing five costumes, and the
# families below are ordered so that the *distinction that changes what you
# would do* wins over the one that does not. All five are recorded in
# bugs/FORMAL_wide_receiver_by_reference.md; they are separated here because
# they have different fixes:
#
#   * the address ESCAPES (returned, or aliased out of a method) — the caller
#     holds a pointer into a frame that is gone. A use-after-free, and a wrong
#     NUMBER rather than a crash, so nothing reports it.
#   * the address is PASSED where the callee wants the value — the callee is a
#     builtin like len() or origin_of() that is lowered as an operation on a
#     value and dereferences what it is handed.
#   * the address is STORED in a field slot, so the disagreement is between
#     every binding of one name rather than at a call.
#   * the address is passed to a callee that is a NAME with no definition in
#     hand — which is not a receiver problem at all and was being counted as
#     one, which is how 7 findings hid inside a receiver bucket.
#
# Markers are substrings of the message, and every one is quoted from a message
# the backend actually produced. A marker that matches nothing is not an error
# -- the family is simply unused -- but a marker that is a GENERIC phrase
# ("receiver", "frame") would swallow the distinctions above it, so each is
# specific to the shape it names. Ordered most specific first; first match wins.
_FRAME_ESCAPES = (
    # The callee is a name this image has no definition for. This is NOT a
    # receiver problem and used to be counted as one: the message begins "a X
    # receiver is passed to <name>(), which is a name with no definition in
    # hand", so the "receiver is passed to" marker below claimed it. 7 of the
    # arm64 findings were hiding in a receiver bucket, which is the specific
    # way a taxonomy can be worse than none — it puts a number in the wrong
    # column. Matched FIRST, on the clause that actually says it, and the
    # comment sits here rather than further down precisely because position in
    # this tuple is what makes it work.
    ("which is a name with no definition in hand",
     "callee has no definition on this path"),
    # Returned from the function that created it: 18 of 130, and the 18
    # messages are VERBATIM IDENTICAL apart from the type name, so there is
    # nothing finer to split on. See the note above on why that is left one
    # bucket rather than divided by type.
    ("is returned from the function that created it",
     "frame address escapes: returned by its creator"),
    # Returned from a METHOD that received the address as its receiver — a
    # different and slightly worse shape, because the escape is not even from
    # the frame's own function.
    ("did not create the frame",
     "frame address escapes: aliased out of a method"),
    # A frame address handed to a builtin that wants the value. Split from
    # "receiver is passed to" because the callee decides the fix: len() needs
    # the value, and no rewriting of the receiver will make it want the
    # address.
    ("frame address is passed to", "frame address passed where a value is wanted"),
    # A receiver passed at argument position 0, i.e. `self`, to a call.
    ("receiver is passed to", "receiver passed as an argument"),
    # A field slot holding a frame address, so two bindings of one name
    # disagree about what lives where.
    ("hands the word in the slot", "field slot holds a frame address"),
    # A member read of a name that is a METHOD of the receiver's own struct,
    # in a VALUE position. Not a frame question at all: a bound method is not
    # a word, so there is no slot to read it out of. `formal/model.py`'s
    # `member_read_without_a_field` says so where the old message claimed two
    # layouts disagreed when there was one, and WITHOUT this family the five
    # files it fixed fall into "other refusal" — which is the specific thing
    # this table exists to prevent, introduced by fixing a diagnostic.
    ("which is a METHOD of", "member read of a method used as a value"),
    # A member read of a name the receiver's struct does not have. One
    # candidate and no disagreement, so there was nothing to disagree about;
    # the same five-file note applies.
    ("has no field", "member read of a name the struct does not have"),
    # The same disagreement, stated as a placement failure rather than as a
    # slot. Matches ONLY the two-candidate wording now, which is the only case
    # it was ever true of.
    ("cannot be placed", "name has two disagreeing shapes"),
)


_REFUSAL_FAMILIES = (
    # The frame-address shapes go FIRST, ahead of the generic
    # "is a method call on a value" marker, because "a X receiver is passed
    # to Y" would otherwise be claimed by whichever generic rule comes first
    # and the distinctions — which are the ones with different fixes — would
    # be lost. Order here is load-bearing; see _FRAME_ESCAPES above.
) + _FRAME_ESCAPES + (
    ("is a method call on a value", "method call on a value"),
    ("is a method on a string", "method call on a string"),
    ("is a real method of String", "string method needing a length"),
    ("multi-index subscript", "multi-index subscript"),
    # A call through a VALUE, in three shapes with three fixes: the callee's
    # declared type, the bracket, the keyword. Ahead of everything below
    # because each message contains "a call through a VALUE" and the generic
    # markers further down would otherwise claim them without distinguishing
    # the three.
    ("a word that is not a code address is nothing to branch through",
     "value call: declared type cannot hold a function"),
    ("read as a value", "function value into a declared non-function"),
    ("is a bracketed call through a VALUE",
     "value call: bracket unreadable"),
    ("no declaration to bind it by NAME",
     "value call: keyword unreadable"),
    ("has no representation on this path", "value with no representation"),
    ("has no public functions", "module exports nothing"),
    ("would bind", "dependency binds what nothing provides"),
    ("cannot be lowered", "cannot be lowered"),
    ("is not supported on the formal", "not supported on this path"),
    # The four wordings below are one family (an AST node this backend has no
    # case for) and are listed separately because each embeds the ARCH in its
    # text, so a single marker would have to name one backend and go stale on
    # the other.
    ("unsupported expression", "unsupported node"),
    ("unsupported statement", "unsupported node"),
    ("unsupported unary operator", "unsupported node"),
    ("unsupported call target", "unsupported node"),
    # MLIR. Three different wordings reach this bucket: the attribute template
    # itself, the dialect operation, and the bare builtin spelling.
    #
    # The dialect operation marker is `dialect OPERATION`, not the old "MLIR
    # dialect construct": `formal/model.py`'s `mlir_dialect_op_refusal` now
    # classifies the operation by what it DENOTES (an effect, an elementwise
    # arithmetic result, or a value needing a fact this path lacks), so its
    # messages name the operation and no longer contain that phrase. The OLD
    # marker is kept because it is still reachable — a call site that knows only
    # the `__mlir_` name and no operation still emits it — and because a marker
    # list that drops the wording it is currently matching is how a family
    # silently empties. `test_refusal_taxonomy.py` has a sample per wording.
    ("MLIR attribute template", "MLIR construct"),
    ("MLIR dialect construct", "MLIR construct"),
    ("dialect OPERATION", "MLIR construct"),
    ("__mlir_", "MLIR construct"),
    # The two halves of an MLIR TEMPLATE that name something with no value here
    # rather than a dialect attribute: a `__mlir_type` is a TYPE, and the
    # current target is a target. Both used to be reported as "MLIR attribute
    # template", which is false of every `__mlir_type` binding in the stdlib —
    # including `std/sys/info.mojo`'s `_TargetType`, the module that heads this
    # family. Same bucket, because the repair is the same (a value model that
    # can hold a type or a target); distinct markers, because a message that
    # names the construct is the only thing a reader of a file nobody has read
    # can act on.
    ("names an MLIR TYPE", "MLIR construct"),
    ("asks for the current TARGET", "MLIR construct"),
    # A `#kgen.param.expr<…>` QUESTION the build cannot answer, as opposed to
    # the attribute templates above, which are answers with nowhere to go. Its
    # OWN family because the fix is different and specific: this build states
    # the architecture it emits and the container it wraps it in, and a field
    # or a CPU feature outside those two needs an input the backend does not
    # have. One marker for the whole class, so the three specific wordings
    # behind it (a field with no source, a per-CPU question, an operand that
    # does not fold) are counted as the limit they are rather than falling
    # through to whatever matches next.
    ("this build cannot answer this target query", "target query not answerable"),
    # A read through a nested frame, e.g. `self._a._b._c`: the outer frame slot
    # holds a frame address and the inner one is then read through it.
    ("out of a nested", "nested frame field read"),
    ("reads a field of a field", "nested frame field read"),
    # A comptime binding that does not fold, so there is no value to
    # materialise. Two wordings: the binding form and the local form.
    ("does not fold to a compile-time constant", "comptime does not fold"),
    # A `...` standing where the lowering needs real instructions.
    ("stands where this path needs", "unimplemented intrinsic"),
    ("this path has no variadic ABI", "variadic call has no ABI"),
    # A construct this compiler refuses at the PARSE. Named rather than
    # lumped into "other" because it is the one family where the answer is
    # "the source uses something unsupported", not "the backend cannot lower
    # something" -- and after the comptime fix in fire_compiler.py that is a
    # meaningful distinction to be able to count.
    ("parse error:", "unsupported construct (parse error)"),
    ("does not fold to a compile-time constant", "comptime value does not fold"),
    # `self` compiled as a frame holder at one call site and as a plain value
    # at another. Its own bucket rather than a receiver one because the
    # severity is different: this one SEGFAULTS (measured, exit 139 on both
    # architectures) instead of computing a wrong number, so it is the only
    # frame-address family that crashes rather than lies.
    ("and something that is not a frame address at",
     "self has two kinds of value across call sites"),
    # Construction with arguments needs a real `__init__` body, and this path
    # does not run one.
    ("is a call to a user-defined `__init__`",
     "construction with arguments needs __init__"),
    # A receiver put in a container, which has no layout for a frame address.
    ("is stored in a container, which has no layout",
     "receiver stored in a container"),
    # A one-field struct's MUTATING method, where the receiver is the struct
    # itself, so the callee hands the receiver back and the caller has to store
    # it. FOUR wordings and one family, because one mechanism refuses all four
    # and the family's own marker would be a phrase ("a mutating method") that
    # no message contains. Each wording is its own row in the fix's message.
    #
    # **All four markers were re-pointed on 2026-10-03** and the family was
    # RENAMED, because the mechanism underneath them changed: the receiver is
    # now handed over by reference (`model.receiver_writeback_name`, mechanism in
    # its docstring) rather than returned in the return register, which removed
    # the refusal that used to be the headline of this family ("both changes its
    # receiver and returns a value" — `BinaryHeap.pop`) and left three narrower
    # ones. A marker list that keeps matching a wording nothing emits is the
    # same rot as one that drops the wording it IS matching: this family would
    # have read as three live findings for a message no build produces.
    #
    # The rename is the honest half. "no return convention" named the DEFEAT —
    # there was no way to write the answer back — and the mechanism now has a
    # convention, so the family is about the shapes the convention does not
    # cover. The four wordings, in the order `model.py` raises them:
    ("declares no return type, so the call has no value",
     "one-field mutator receiver hand-off"),
    ("is not a place this path can take the address of",
     "one-field mutator receiver hand-off"),
    ("is called in the same argument list that reads",
     "one-field mutator receiver hand-off"),
    ("two hidden-word conventions",
     "one-field mutator receiver hand-off"),
    # A method on a value whose receiver is a frame address, stated as a
    # description of the call rather than as a receiver placement.
    ("is a method on a", "method call on a value"),
    # A name bound at module level. A formal value lives in a function's own
    # stack scratch, which is reclaimed on return, so a name that must outlive
    # every frame has nowhere to live. Distinct from every frame family above:
    # the address is not the problem, the ABSENCE of storage is.
    ("has no module-global storage for it",
     "module-global name has no storage"),
    ("takes exactly one value to convert", "wrong argument count"),
    # Reachable from `codegen` only through a rule that has not fired yet; it
    # is here so the breakdown has a name for the day it does, and so a future
    # message that does not match it lands in "other refusal" — visible —
    # rather than in a family that already claimed the ground.
    (_SYSCALL_MARK, "call into a system module"),
)
_REFUSAL_OTHER = "other refusal"


# ── Reach: which host modules a Mojo-side implementation could in principle
# provide, and which need a host process this target does not have ───────────
#
# CLASS_HOST's own blurb calls a host import "outside this backend's reach, and
# not fixable", and that sentence is FALSE of `os`, `sys`, `math`, `struct`,
# `time`, `json` and `re` — none of those needs a host process or an embedded
# interpreter, and a Mojo implementation of each is a thing a person could
# write. It is true of `subprocess`, `ctypes`, `asyncio`, `threading`, `socket`
# and `tempfile`. So the class as it stands mixes a permanent property of the
# target with a work item, and a sweep that counts them together cannot size
# either.
#
# THE OWNERSHIP, and why there is a list here at all. formal/imports.py owns the
# split — it is the module the build itself consults, and duplicating its
# membership would be a second list that rots the day it gains an entry. So the
# split is READ from there (`_host_tiers`), under any of the names an owner
# might reasonably give it, and this file's copy is a FALLBACK that exists only
# for the window before it lands. A fallback that can silently disagree with the
# authority is worse than no fallback, so `test_formal_sweep_truth.py` fails if
# the two ever differ — the mirror cannot rot unnoticed, and the day [4]'s split
# lands this constant becomes dead code that the same test tells you to delete.
# THE REACH SPLIT IS NOT WRITTEN HERE. `formal/imports.py` owns it — it is the
# module the build itself consults, so a second copy in this file is a list that
# rots the day an entry is added, and the original plan for this file said so.
# It is read through `host_module_tier()`, which is the accessor the owner
# publishes.
#
# This constant is a DERIVED VIEW of that authority, not a copy of it, and the
# difference is the whole point: it cannot disagree with `formal/imports.py`,
# because it is computed from it. It exists only because
# `test_formal_sweep_truth.py` reads it by name, and it can be deleted the moment
# that test does.
#
# WHY THIS WAS A REAL BUG AND NOT A NICETY, measured: an earlier version GUESSED
# at the owner's attribute names from a table of five plausible spellings and
# fell back to a pinned 7-name mirror when none matched. `formal/imports.py`
# publishes `HOST_MODELLED` / `HOST_UNREACHABLE` and a `host_module_tier()`
# function, so none of the five matched, the fallback engaged, and the summary
# reported 7 in-reach modules when the authority has 49. `argparse`, `ast`,
# `dataclasses`, `collections`, `itertools`, `pathlib` and `typing` were all
# called PERMANENT when each is a thing a person could write. The mirror's own
# anti-rot test stayed green throughout, because it compared the mirror against
# the same broken reader.
#
# THE FALLBACK IS EMPTY, deliberately. If `formal.imports` cannot be imported at
# all, this file cannot classify a host module either (`_is_cpython_stdlib`
# needs the same import), so the sweep is already degraded — and an empty
# in-reach set says "cannot size the work", which is true, where 7 hand-picked
# names would say "7 modules are reachable", which understates the work by 42
# and is the exact failure being fixed.
def _in_reach_from_authority() -> frozenset:
    """Every host module a Mojo-side implementation could in principle provide.

    Read from `formal/imports.py` through its own accessor, so the rule that
    decides it — does implementing this need a second process, a thread, a
    socket, a dynamic loader for foreign code, an embedded CPython, a terminal,
    or a library outside libSystem — is stated in exactly one place and is not
    restated as a list of names that can fall out of step with it.
    """
    try:
        from formal import imports as I
    except Exception:
        return frozenset()
    try:
        return frozenset(n for n in I.HOST_MODULES
                         if I.host_module_tier(n) == 'modelled')
    except Exception:
        return frozenset()


IN_REACH_HOST_MODULES = _in_reach_from_authority()


def _admitted_host_modules() -> frozenset:
    """Every host module that ANSWERS under a declared contract.

    A third bucket, read from `formal/imports.py`'s own `host_module_tier`, and
    separate because the two existing ones could not describe these: `subprocess`
    is not a gap with an owner (it has a model) and it is not unreachable (it
    builds), so a two-way split called it one or the other and both were false.
    The reach line below reads it so a file that moved out of `host-import`
    because its host module now answers is not silently missing from the report.
    """
    try:
        from formal import imports as I
        return frozenset(n for n in I.HOST_MODULES
                         if I.host_module_tier(n) == 'admitted')
    except Exception:
        return frozenset()


def _host_tiers() -> tuple:
    """(in_reach, unreachable, where) — the split, and which file said so.

    `where` names the authority the answer came from, so the summary can tell a
    reader whether they are looking at a measurement or at a degraded state; an
    estimate presented as an authority is the failure mode this function exists
    to prevent. With the split landed it is always `formal/imports.py`, and the
    empty set it can return on failure is the honest "cannot size this" rather
    than a smaller number that reads like a measurement.
    """
    in_reach = _in_reach_from_authority()
    if not in_reach:
        return set(), set(), None
    try:
        from formal import imports as I
        unreachable = frozenset(
            n for n in I.HOST_MODULES
            if I.host_module_tier(n) == 'unreachable'
            # An ADMITTED module is not unreachable: it has a model and it
            # builds.  Counting it here would put it in the "permanent fact about
            # the target" bucket of the reach line, which is the claim that made
            # the sweep's largest bucket look unfixable, and it would be false of
            # every one of the five.
            and I.host_module_tier(n) != 'admitted')
    except Exception:
        unreachable = frozenset()
    return set(in_reach), set(unreachable), "formal/imports.py"


def _is_cpython_stdlib(name: str) -> bool:
    """Whether `name` names a CPython standard-library module.

    Used only to sharpen a verdict the build already reached: when the build
    says an import does not resolve, it has already established that no Mojo
    source for it exists anywhere, so the only open question is WHY, and for a
    name this returns True for, the answer is "it is the host's own standard
    library" — a fact about the target, not a gap in the backend.

    **A DELEGATION, and it used to be a second reader of the same fact.** This
    copy existed because the build's own diagnostic consulted only the
    hand-classified tiers and so worded `binascii`, `ctypes`, `asyncio` and 219
    other CPython modules as "not a stdlib or sibling module"; the sweep then
    read `sys.stdlib_module_names` to correct the verdict the build had already
    printed, which is a report disagreeing with the message it is reporting on.
    `formal/imports.py::is_cpython_stdlib` now asks the oracle in the place that
    decides the WORDING, so the two cannot come apart, and this answers from it.
    An import that cannot be had at all still answers False, which narrows
    nothing and raises nothing: the caller keeps its own behaviour.
    """
    try:
        from formal.imports import is_cpython_stdlib
        return bool(is_cpython_stdlib(name))
    except Exception:
        return False


def _short(detail: str, limit: int = 68) -> str:
    """A one-line reason for the per-class breakdown."""
    text = " ".join(detail.split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _module_has_source(name: str, path) -> bool:
    """Whether this backend has a source it could compile for module `name`.

    The build's own answer, from the build's own resolver
    (`formal.imports.resolve_module_path`), resolved from the file that was
    swept so the search roots are the ones the build used. True means the
    module EXISTS for this file and any refusal naming it is about a construct
    rather than about a missing module.

    False for a module with no path (nothing to resolve against) and for a
    resolver that cannot be imported: both leave the caller's rule exactly as
    it was, which is the right direction — this narrows a rule, and a rule
    that cannot answer should not narrow anything.
    """
    if not name or not path:
        return False
    try:
        from formal.imports import resolve_module_path
        return resolve_module_path(name, relative_to=path) is not None
    except Exception:
        return False


def _source_imports(source, name: str) -> bool:
    """Whether `source` really does import module `name`.

    The structural half of the import test, and the part that cannot rot: if a
    message quotes a module this file imports, then whatever the sentence says
    around it, the build refused on an IMPORT — which is never a codegen
    finding. This is what lets classify() survive a reworded import error
    without having to recognise the new wording.

    Paired with `_module_has_source`, which is the other half and the one that
    became necessary when a host module stopped being a host module: a name
    that is BOTH quoted and imported is only an import failure if the backend
    has no source for it.
    """
    if not source:
        return False
    top = re.escape(name.split(".")[0])
    return re.search(rf"^[ \t]*(?:import|from)[ \t]+{top}\b", source,
                     re.M) is not None


def _declared_host() -> frozenset:
    """formal.imports.HOST_MODULES — the set the build itself consults.

    Read, never copied: a second list of host modules here is a list that
    silently goes stale the next time formal/imports.py gains one.
    """
    try:
        from formal.imports import HOST_MODULES
        return HOST_MODULES
    except Exception:
        return frozenset()


def _import_class(mod: str) -> tuple:
    """The not-answerable class for an import the build refused to resolve."""
    if _is_cpython_stdlib(mod):
        declared = _declared_host()
        # The suffix is not decoration: it says WHY this one needed the
        # interpreter's table rather than the build's own, which is the
        # actionable part (formal/imports.py's HOST_MODULES is missing it).
        known = mod in declared or mod.split(".")[0] in declared
        return CLASS_HOST, mod if known else f"{mod} (CPython stdlib)"
    return CLASS_UNRESOLVED, mod


def _split_chain(detail: str) -> tuple:
    """(hops, terminal) for formal/build.py's dependency-error wrapper.

    `hops` is the list of modules the chain passed through, outermost first;
    `terminal` is the innermost message, which is the only part that says
    anything about the backend. Peeling is by shape (one pattern, any depth),
    so a chain two or five levels long needs nothing added here, and a message
    that is not a chain peels zero times and comes back whole — which is what
    keeps every unchained case on exactly the rules it was on before.
    """
    hops, rest = [], detail
    while True:
        m = _CHAIN_RE.match(rest)
        if not m:
            return hops, rest
        hops.append(m.group("mod"))
        rest = rest[m.end():]


def _terminal_reason(term: str) -> str:
    """The terminal message with the noise in front of it stripped off.

    Two prefixes, both of them somebody else's formatting: fire.py's
    `build: ` on the way out, and formal/imports.py's `<file>: ` on the way in
    (`f"{os.path.basename(source_path)}: {e}"`). Stripped for MATCHING only —
    the printed line keeps both, because the file the refusal really came from
    is the useful half of it.
    """
    if term.startswith(_BUILD_PREFIX):
        term = term[len(_BUILD_PREFIX):]
    return _FILE_PREFIX_RE.sub("", term, count=1)


_EXPORT_GATE_MODULE_RE = re.compile(r"is imported from `([^`]+)`")
"""The module a call's DEFINING module is named by, in prose.

`formal/model.py::imported_callee_refusal` says it in a sentence rather than
in a `<file>: ` prefix, so `_refuser` answers "" for the largest refusal row in
the corpus — 170 of the 710 files on the 2026-10-04 b10 sweep, all of them
carrying this one sentence. The backtick span is the module name as the build's
own resolver spells it: `std.format._utils`, `std.math`, `..fstat`, `.path`.

ONE reader, because two tools now want it and a second spelling rule would be a
second thing to keep right: `tools/formal_sweep_causes.py` (whose `uses:`
column could not be measured for that row until it existed — see
`bugs/FORMAL_std_os_io_round2_scope_is_one_refusal_shape.md` §6.1) and
`tools/formal_chain_probe.py`, whose `_EXPORT_GATE_RE` is this same pattern.
"""


def refusing_module(msg: str) -> str:
    """The dotted module name a message says a call is imported from, or "".

    A NAME, not a path: answering "which module do I stub to break this link"
    and answering "which module declares these names" are two questions, and
    only the second needs a file. `formal.imports.resolve_module_path` is the
    resolver for both, and a caller that wants the file says so.
    """
    m = _EXPORT_GATE_MODULE_RE.search(msg or "")
    return m.group(1) if m else ""


def _refuser(term: str) -> str:
    """The file the innermost message came from, or "" if it names none.

    This is the file a reader has to open to fix anything, and it is NOT the
    file the sweep swept — which is the whole distinction the dependency class
    exists to keep visible.
    """
    m = _FILE_PREFIX_RE.match(term)
    return m.group("file") if m else ""


def _refusal_family(term: str) -> str:
    """Which family of construct refusal this is, for the breakdown only."""
    for marker, family in _REFUSAL_FAMILIES:
        if marker in term:
            return family
    return _REFUSAL_OTHER


def _target_limit(term: str):
    """(class, reason) when `term` is about the gimple runtime namespace.

    `term` is the terminal message with the prefixes already stripped. Returns
    None when the message is not about that namespace at all, and otherwise a
    class:

      · CLASS_TARGET when the text IS formal/model.py's own refusal for the
        name it leads with — the name goes through `is_gimple_runtime_builtin`
        (the same predicate both backends call before refusing) and the text is
        compared against `gimple_runtime_refusal(name)` rather than against a
        copy of its wording here. A message that merely MENTIONS a `mojo_*`
        name is not this class, and formal/model.py owns the words.

      · CLASS_UNKNOWN when the name is in the namespace but the wording is not
        the one formal/model.py produces today — i.e. formal/ was edited under
        this file. Deliberately neither answer: this file knows the shape (a
        `mojo_*` name led the sentence) and not the meaning, and guessing
        would put either a target fact into the gap count or a gap into the
        excluded population. `unknown` is the class that says so out loud.
    """
    m = _TARGET_LEAD_RE.match(term)
    if not m:
        return None
    name = m.group(1)
    try:
        from formal import model as M
        if not M.is_gimple_runtime_builtin(name):
            return None
        probe = M.gimple_runtime_refusal(name)
    except Exception:
        return None
    if term.startswith(probe[:_TARGET_PROBE]):
        return CLASS_TARGET, name
    return (CLASS_UNKNOWN,
            f"gimple-runtime refusal in wording this tool does not know: "
            f"{name}")


# ── A call into a system module with no Mojo source on any path ─────────────
#
# The sibling of CLASS_HOST, one level down. CLASS_HOST is "this file IMPORTS a
# module no Mojo source exists for", which the resolver says before anything is
# lowered. This is "this file CALLS into one" — and it is a DIFFERENT fact for
# the sweep, because a construct refusal is `codegen`, the one class whose count
# is a gap in the backend, the class in the answerable denominator, and the
# class that makes a run exit 1. So a message that is really about the target
# arriving in `codegen` is the most expensive misclassification this tool can
# make: it inflates the finding count, it deflates the coverage rate, and it
# points the next reader at a construct in a file that could not have built even
# with that construct lowered.
#
# Nothing on this tree raises such a message today — the resolver always gets
# there first, which is why the class is empty and why the rule below is a
# forward-looking one rather than a measured one. It is here anyway, and it is
# here as a CLASS rather than as a family in the breakdown, because a family
# would still be counted as a finding. `test_formal_sweep_truth.py` pins the
# rule against a real build message, and the summary says the count so a reader
# can see that it is zero rather than inferring that the rule is dead.
#
# STRUCTURAL, not a wording match, for the same reason the import rules are:
# formal/ owns the message, and a template here would change class the day it is
# reworded. The test is that the message NAMES a member of a host module this
# file imports — `os.getenv`, `json.dumps` — because a construct refusal never
# does otherwise. `Traceback (most recent call last)` is why the member form has
# to be dotted and followed by an identifier: `traceback` is a host module and
# the word appears in every crash this tool prints.
def _system_module_call(term: str, source=None) -> str:
    """The host module a refusal is really about, or "" if it is not one.

    Two ways to fire, and the first is deliberately weaker so the second does
    not have to be right on its own:

      * the build SAYS so — a refusal whose subject is a system module with no
        Mojo source anywhere, whatever it calls that. This is the shape
        `formal/` would emit if it wanted the message to be self-describing, and
        it is a substring rather than a template so a reworded sentence keeps
        working while a rewording of the surrounding text cannot break it;

      * the build NAMES one — a construct refusal that mentions `mod.member`
        for a host module `mod` this file actually imports. Structural, and
        the file's own source is the confirmation, so a coincidental `a.b` in a
        diagnostic cannot put a file in a class its own text contradicts.

    **The second way asks the TIER and not membership of `HOST_MODULES`, and
    that is the fix, not a refinement.** `HOST_MODULES` is
    `HOST_UNREACHABLE | HOST_MODELLED | HOST_ADMITTED`, so it answers "does the
    backend know this name", and a name in the `modelled` or `admitted` tier
    HAS a `formal/hostmods/` source — which makes this class's own sentence,
    "no Mojo source on any path", false of it. Measured on the 2026-10-03
    sweep: 11 files whose refusal is

        line 324: `subprocess.TimeoutExpired` is a handler arm with a body this
        path cannot put in the image, so it is refused rather than dropped: …

    were filed `not-answerable/system-module-call`, on the strength of the
    mention — `subprocess` is in `HOST_MODULES`, being admitted, and the file
    does import it. Every clause of the class's claim is false of that row:
    nothing is CALLED, `subprocess` answers under declared contracts, and the
    refusal is a construct refusal (`FORMAL_except_arm_is_never_emitted`,
    another worker's row) which this class had just hidden from the codegen
    count. `host_module_tier` is the authority the sweep's own reach split and
    its own test suite already read for exactly this question, so the fix is one
    reader of one table rather than a second copy of the division.

    `test_formal_sweep_truth.py` states the rule this now implements: "a name in
    `HOST_MODULES` that is MODELLED or ADMITTED answers, so a refusal naming it
    is about a construct in a module this build compiles and not a fact about
    the target". The first arm is untouched on purpose: when the BUILD says "no
    Mojo source on any path", that is the backend talking about itself and this
    tool does not get to have an opinion about it.
    """
    if _SYSCALL_MARK in term:
        m = _MEMBER_RE.search(term)
        return m.group(1) if m else "a system module"
    if not source:
        return ""
    try:
        from formal.imports import HOST_UNREACHABLE, host_module_tier
    except Exception:
        return ""
    for mod, member in _MEMBER_RE.findall(term):
        if (mod in HOST_UNREACHABLE or host_module_tier(mod) == "unreachable") \
                and _source_imports(source, mod):
            return mod
    return ""


def _crash_cause(err: str):
    """CAUSE_* for a build that raised, or None if it refused cleanly.

    A refused build (FormalBuildError) prints one `build: …` line and no
    traceback; anything else that fails prints a traceback too. That is the
    whole test — deliberately not the message's shape, because fire.py
    prefixes both with `build:`.

    The deepest frame decides which class this is. formal/build.py frames sit
    between the driver and the emitter, so "some frame is in formal/" would
    call every parser or driver bug a codegen finding; the frame the exception
    actually came out of is what says whether the BACKEND raised.
    """
    if _TRACEBACK_MARK not in err:
        return None
    frames = _FRAME_RE.findall(err)
    frame = os.path.normpath(frames[-1]) if frames else ""
    parts = frame.split(os.sep)
    return (CAUSE_BACKEND_CRASH
            if frame.endswith(".py") and "formal" in parts
            else CAUSE_DRIVER_CRASH)


def _admitted_reason(path):
    """Why this file is `built-with-admitted-contracts`, or '' if it is not.

    The contracts are the BUILD's, read through the build's own walk:
    `formal/imports.py`'s `admitted_contracts`, which is the same function
    `formal/build.py` calls to fill `result["admitted"]` and the same one
    `fire.py`'s `trust:` line renders.  Reading them here rather than computing a
    second answer is the whole reason the three agree: a classifier that walked the
    closure a second time could classify a file as trusting nothing while the
    build's own line named six contracts, and the sweep is the one a reader would
    believe over the build.

    THE REASON WHY THE TRUST BOUNDARY IS A CLASS AT ALL, and not a note on the
    `pass` line: a `pass` is this tool's claim that the image built and every
    symbol it binds is on its own link line.  A file that also asked a second
    process to answer a question has not had that claim made for it, and the
    report's job is to say which of its rows rest on what.  The alternative --
    folding these into `pass` and mentioning the contracts in prose -- is exactly
    how a file that cannot be proved at all becomes indistinguishable from one
    that can, which is the confusion `FORMAL_known_limits.md` records as "a false
    PASS, the worst outcome this project has".

    NOT CACHED with the verdict, and that is deliberate in the same direction.
    `run_one`'s `.result` blob records `(ok, detail)` and `classify` re-derives
    the class on every run INCLUDING a cache hit -- the rules are applied after
    the cache, never inside it (the comment above `CLASS_PASS` says why).  So a
    verdict recorded before this class existed is still classified correctly the
    first time it is read, with no key change and no re-run.

    A failure to walk is NOT a pass.  It returns '' and the caller falls through to
    `CLASS_PASS`, which is the wrong answer, and it is the wrong answer the tool
    already makes elsewhere when it cannot read a file (`CAUSE_UNREADABLE`).
    Reading the build's OWN answer is what avoids that: a build that succeeded
    published its `trust:` line, and this re-derivation can only disagree with it
    if `formal/imports.py` changed, in which case `cas.formal_fingerprint()` has
    moved and every `.result` is a miss anyway.
    """
    if not path:
        return ''
    try:
        from formal import imports as I
        contracts = I.admitted_contracts(path)
    except Exception:                            # noqa: BLE001
        return ''
    if not contracts:
        return ''
    mods = sorted({c.module for c in contracts})
    return (f"{len(contracts)} admitted host contract(s) from "
            f"{', '.join(mods)}")


def classify(ok: bool, detail: str, cause=None, source=None,
             path=None) -> tuple:
    """(class, reason) for one build outcome. Message matching is pure; the
    one I/O is `_module_has_source`, which asks the build's own resolver
    whether a quoted module exists.

    `cause` is run_one's own account of the outcome not being one of the
    build's diagnostics (a timeout, an unreadable file, an internal exception)
    and short-circuits the message matching: if the sweep never got the build's
    own answer, there is nothing to read a class off, and no string matching
    should be allowed to guess one. The one exception is a crash inside the
    backend itself, which IS a finding — see CLASS_CRASH.

    `source` is the file's own text, and it is what makes the import test
    structural rather than a template match (see _source_imports). Without it
    the function can only recognise the wordings it already knows, and the
    first wording it does not know would be counted as codegen coverage.

    A CHAIN (a dependency's error wrapped in the importer's) is peeled first
    and the TERMINAL reason is what gets classified, because that is the only
    layer that describes the backend. What the importer's own class then is
    depends on the terminal's, and that is the position this tool takes:

      · terminal is an import refusal (host, unresolved) or a target limit →
        the importer is unanswerable for the SAME reason. It cannot be built
        here either, and the reason is a fact about the target.
      · terminal is a construct refusal → `codegen/dependency`. The importer
        produced no binary and would have if the backend had lowered that
        construct, so it belongs in the answerable denominator (a file that
        does not build is not a file the backend handles), but it is NOT
        reported as a gap in itself: the class name, the printed line and the
        summary's breakdown all say the gap is one level down. Calling these
        plain `codegen` would send a reader to a file that is fine, and
        dropping them from every rate is what made 204 files invisible.
    """
    if ok:
        admitted = _admitted_reason(path)
        if admitted:
            return CLASS_ADMITTED, admitted
        return CLASS_PASS, ""
    if cause == CAUSE_BACKEND_CRASH:
        # Not `codegen`, and the difference is not cosmetic. A refusal is a
        # claim about a construct: the backend looked at it and said no. A
        # crash is the backend's own plumbing falling over, which is a bug in
        # the compiler, not a limit of the language it implements — B4 caught a
        # sweep reporting 74 files as `codegen: the backend raised: ValueError:
        # not enough values to unpack`, every one of them an artefact of
        # another agent half-way through an edit. It stays a failure (it is in
        # DIRTY, so the run exits 1), it stays printed, and it is never cached
        # (run_one publishes no verdict when there is a cause) — but it is in
        # no rate, because a rate is a claim about constructs.
        #
        # run_one has already said "the backend raised" in the detail it hands
        # over (that is the line the report prints); do not say it twice.
        said = "the backend raised: "
        return CLASS_CRASH, (detail if detail.startswith(said)
                             else said + _short(detail))
    if cause:
        return CLASS_TOOL, cause

    hops, terminal = _split_chain(detail)
    cls, reason = _classify_terminal(terminal, source, path)
    if not hops or cls != CLASS_CODEGEN:
        return cls, reason
    # The refusal is one level down. Name the file that refused and the family
    # it refused in, so the breakdown groups by what a reader would have to fix
    # rather than by which file happened to import it; the whole chain, and the
    # terminal reason in full, stay in the printed line above.
    return CLASS_CODEGEN_DEP, _short(
        f"{len(hops)} import(s) deep: "
        f"{_refuser(terminal) or hops[-1]}: "
        f"{_refusal_family(_terminal_reason(terminal))}")


def _classify_terminal(detail: str, source=None, path=None) -> tuple:
    """(class, reason) for the innermost message of a build's own answer."""
    if _EXTERN_MARK in detail or _EXTERN_BUILD_MARK in detail:
        m = (_EXTERN_BUILD_COUNT_RE if _EXTERN_BUILD_MARK in detail
             else _EXTERN_COUNT_RE).search(detail)
        caught = ("nothing on the link line provides it, caught when the build "
                  "refused the image" if _EXTERN_BUILD_MARK in detail
                  else "nothing on the link line provides it")
        return CLASS_EXTERN, (f"{m.group(1)} unresolved extern(s) — {caught}"
                              if m else _short(detail))
    # A refusal by name, outside the freestanding target. Before the import
    # rules, because `mojo_list_len` and friends are not modules and no
    # reading of the import rules would place them.
    target = _target_limit(_terminal_reason(detail))
    if target:
        return target
    # SEVERAL of this file's own imports, all at one level. Handled before the
    # single-import rule below, which would take the last name in the message —
    # and here the last name is the alphabetically last one, so the class and
    # the breakdown would be decided by sorting rather than by the file.
    multi = _MULTI_IMPORT_RE.search(detail)
    if multi:
        names = sorted(set(_IMPORT_RE.findall(multi.group("body"))))
        if names:
            # The WORST of the reasons the build gave, not the best: a file that
            # imports one host module and one module that does not exist at all
            # is blocked by the second, and calling the whole file host-import
            # would file a missing-module finding under "not fixable here".
            if _UNRESOLVED_MARK in multi.group("body"):
                cls = CLASS_UNRESOLVED
            elif _HOST_MARK in multi.group("body") \
                    or _STDLIB_UNCLASSIFIED_MARK in multi.group("body"):
                cls = CLASS_HOST
            else:
                # A wording this tool has not learned to read, kept in its own
                # bucket for the reason the single-import rule keeps one: the
                # backend refused for a reason that was not recognised, and
                # counting that as coverage is what this classification exists
                # to prevent.
                cls = CLASS_UNKNOWN
            return cls, (", ".join(names) if cls != CLASS_UNKNOWN
                         else f"import message not recognised: {_short(detail)}")
    mods = _IMPORT_RE.findall(detail)
    if mods:
        # The build's own two wordings, which partition the ImportBuildError
        # space between them, and one message can carry several: formal/
        # wraps a dependency's own error inside the importer's ("x.py imports
        # 'fire_compiler', which cannot be built either: fire_compiler.py
        # imports 're', which is a host module …"). The LAST `imports '…'` is
        # the innermost one — the import that actually has no source — so it
        # is the one to report; naming the outer module instead would blame a
        # module that resolves perfectly well.
        mod = mods[-1]
        if _HOST_MARK in detail or _STDLIB_UNCLASSIFIED_MARK in detail:
            return CLASS_HOST, mod
        if _UNRESOLVED_MARK in detail:
            return _import_class(mod)
        # Recognisably an import refusal, in a wording this tool does not
        # know. Its own bucket, never `codegen`: the backend did not fail to
        # lower a construct, it refused for a reason this tool has not learned
        # to read, and counting that as coverage is the exact failure this
        # whole classification exists to prevent.
        return CLASS_UNKNOWN, f"import message not recognised: {_short(detail)}"
    # No `imports '…'`. Before concluding this is about a construct, check
    # whether the message names a module this file ACTUALLY imports — that
    # makes it an import failure whatever the wording is, and the host table
    # then says which kind. Matching templates alone is how a reworded import
    # error silently starts counting as coverage, and templates are exactly
    # what another agent editing formal/ will change.
    #
    # …and the name must be a module this backend has NO SOURCE for, which is
    # a question with an authority rather than a template. `sys` has a Mojo
    # source (`formal/hostmods/sys.mojo`), so a refusal that quotes `sys` — a
    # module attribute read, a `mod.fn()` whose module exports no such `fn` —
    # is a refusal about a construct IN A MODULE THAT EXISTS, and filing it as
    # host-import put 14 real files in the not-answerable bucket for a reason
    # that had stopped being true. `resolve_module_path` is the build's own
    # resolver, in the
    # build's own order (Mojo source > host module > sibling > stdlib loader),
    # so the sweep does not get to have an opinion about what exists.
    #
    # With no path to resolve against — `classify` called without one, which
    # is every call in the test suite that does not name a file — the test is
    # skipped and the rule is the one it always was.
    for name in _QUOTED_NAME_RE.findall(detail):
        if _source_imports(source, name) and not _module_has_source(name, path):
            return _import_class(name)
    if _HOST_MARK in detail or _UNRESOLVED_MARK in detail:
        # Recognisably about an import, but with no module named to classify
        # by. Its own bucket rather than a guess.
        return CLASS_UNKNOWN, (f"import message with no module named: "
                               f"{_short(detail)}")
    # A call into a system module, checked before the construct fallback
    # because the fallback is the expensive mistake: it files a fact about the
    # target as a gap in the backend.
    sysmod = _system_module_call(detail, source)
    if sysmod:
        return CLASS_SYSCALL, f"{sysmod} has no Mojo source on any path"
    # The build spoke, and it spoke about a construct in the file. This is the
    # signal, and it is the fallback precisely because a backend that refuses
    # to lower something is exactly what this sweep exists to find.
    return CLASS_CODEGEN, _short(detail)


# cas.stats is a process-global dict and the sweep bumps it from every worker,
# so `stats[k] += 1` here is a read-modify-write that can lose an update and
# make hits+misses stop summing to the file count — which is the one property
# the accounting line exists to show.
_STATS_LOCK = threading.Lock()


def _bump(kind: str) -> None:
    with _STATS_LOCK:
        cas.stats[kind] += 1


# Files whose verdict this run declined to cache because it depends on a
# formal dylib that is not in the cache key. Counted here rather than in
# cas.stats because cas's own dict is a fixed two-key record of ITS lookups
# and this is a fact about this tool's publication decision, not a lookup.
_DYLIB_LINKED = 0


def _bump_dylib_linked() -> None:
    global _DYLIB_LINKED
    with _STATS_LOCK:
        _DYLIB_LINKED += 1


SKIP_DIRS = {
    ".git", ".pixi", "output", "build", "__pycache__", ".mypy_cache",
    ".pytest_cache", "node_modules",
}
# NOTE: "stdlib" is deliberately NOT pruned by name, and that is load-bearing
# rather than tidiness. It used to be in this set, to keep the default walk
# from wandering into the external stdlib tree — but the set is applied to
# EXPLICIT roots too, so naming a root whose own subtree is called `stdlib`
# (or whose parent contains one) silently dropped every file under it and
# reported a smaller sweep as if it had run. `stdlib <…/mojo/stdlib>` gave
# 669 files and `stdlib <…/mojo>` gave 263, with no warning either way. The
# external tree lives outside this repo, so the default walk never reached it
# anyway; the stdlib is now a first-class default ROOT (see default_roots),
# which is the honest way to include it.
# Mojo is a Python superset, so both extensions are valid inputs to the
# compiler; the stdlib tree is almost entirely .mojo.
SUFFIXES = (".py", ".mojo")
# Same expression, and for the same reason, as test_formal.py's DEFAULT_JOBS:
# these are CPU-bound subprocess builds, so more workers than cores only adds
# contention, and an unbounded default on a 96-core box would launch 96
# concurrent `fire.py` processes. Kept identical to that suite on purpose (two
# sweeps of the same machine should not fight over it), not re-derived here.
DEFAULT_JOBS = max(4, min(os.cpu_count() or 8, 20))
# A timeout is a property of this machine's load, so it is never cached and a
# file that hits it lands in the `tool` class — counted, printed, and in no
# rate. That is why this default can stay modest: the cost of being too small
# is now visible instead of silent. It is still too small for the larger
# stdlib modules, which is what the -t help text says.
DEFAULT_TIMEOUT = 30

# …and a timeout is a bound PER POPULATION, which is the half of the
# `-t` argument that used to be missing.
#
# The two populations are separated by one measured fact, not by taste: a stdlib
# module imports a few stdlib modules, while a repository-root `.py` imports the
# repository's OTHER ROOT `.py` files, so one repo file's build is the SUM of its
# import closure's builds
# (measured on one tree: a 135-line repo file passes inside 30 s, a 185-line one
# crashes inside 600 s, a 5 645-line one is still running at 5 400 s — all three
# in the same run under one `-t`.)
# What that measurement also rules out is a bound proportional to the closure:
# four files that
# cannot be told apart by line count — one that crashes inside 600 s, two that
# pass inside 30 s, and two that no `-t` answers — share ONE import closure of
# identical size, so a bound proportional to closure size cannot separate them
# either. The population is the axis that can, which is why `-t` takes it and why
# both defaults below are the same number: this is a knob, not a change of
# behaviour, and a run that passes no `-t` still times out every file at 30 s.
POPULATIONS = ("repo", "stdlib")


class Timeouts:
    """`-t`, resolved into a per-file bound.

    One object rather than a number threaded through the run, because the
    question it answers is PER FILE — "which population is this file in, and
    what did the reader ask for in that population" — and a reader who has to
    ask that question outside this class is reading a number that does not
    exist. It also holds the stdlib root, so the population is decided once at
    construction instead of by every caller that wants a bound.

    `seconds` is a partial mapping and an absent population takes
    `DEFAULT_TIMEOUT`: `-t repo=180` is a complete, sensible command, and
    making the reader spell out the population they did not mean would be a
    worse interface than the default it falls back to.
    """

    def __init__(self, seconds=None, stdlib_root=None):
        self.seconds = {p: DEFAULT_TIMEOUT for p in POPULATIONS}
        for pop, value in (seconds or {}).items():
            if pop not in self.seconds:
                raise ValueError(
                    f"unknown timeout population {pop!r}; "
                    f"known: {', '.join(POPULATIONS)}")
            self.seconds[pop] = int(value)
        self.stdlib_root = (os.path.abspath(stdlib_root)
                            if stdlib_root else None)

    def population(self, path):
        """`stdlib` for a file under the stdlib root, `repo` for everything else.

        A prefix test on the resolved root, and it is deliberately the ONLY
        thing that decides this. The alternative — asking the resolver what the
        file imports and calling a file with several swept imports "the other
        population" — is the closure-proportional bound §2 measured and rejected:
        `imports.py`, `monomorphize.py`, `reflect.py` and `gimple_codegen.py`
        have the SAME closure of the same size and differ by a factor of twenty
        in what a build of them costs, so a rule that reads the closure would
        hand all four the same bound and be wrong about three of them.

        `repo` is the fallback for everything the stdlib root does not contain,
        which is the whole of an explicit-path sweep of this repository and the
        whole of `--no-stdlib`. There is no third population and no guessing:
        a file outside the stdlib tree is a repo file, and if that is wrong the
        reader says so with `--stdlib` on a different root.
        """
        if not self.stdlib_root:
            return "repo"
        try:
            inside = os.path.commonpath(
                (os.path.abspath(path), self.stdlib_root)) == self.stdlib_root
        except ValueError:          # different drives: not under the root
            inside = False
        return "stdlib" if inside else "repo"

    def for_file(self, path):
        """The bound for one file, in seconds."""
        return self.seconds[self.population(path)]

    def uniform(self):
        """True when both populations share one number (what a bare `-t 90` means)."""
        return len(set(self.seconds.values())) == 1

    def describe(self):
        """How the run's bounds read on the header line.

        A bare number when the two agree, because that is what the run is
        actually doing and a reader comparing this line with a previous run's
        wants to see whether anything CHANGED.
        """
        if self.uniform():
            return f"{self.seconds['repo']}s"
        return " ".join(f"{pop}={self.seconds[pop]}s" for pop in POPULATIONS)

    def retry_arg(self, pop):
        """The `-t` argument that re-answers a file in `pop`, larger than the one that failed.

        Twice the bound, or a minute more than it, whichever is larger: the
        point is a NUMBER THAT IS NOT THE ONE THAT JUST FAILED, and a run that
        used no `-t` at all still gets a usable one. A uniform run gets the
        bare spelling, because suggesting `-t repo=90` at a reader who wrote
        `-t 90` is noise; a per-population run gets the spelling that raises
        THIS file's population and leaves the other one alone, which is the
        reason the flag exists.
        """
        now = self.seconds[pop]
        bigger = max(int(now or 0) * 2, int(now or 0) + 60)
        return f"-t {bigger}" if self.uniform() else f"-t {pop}={bigger}"

    def populations_with_seconds(self):
        return {pop: self.seconds[pop] for pop in POPULATIONS}


def _timeout_arg(text):
    """One `-t` value: `SECONDS` for both populations, or `POPULATION=SECONDS`.

    argparse `type=`, so the error a reader gets for a typo names the two
    spellings that work rather than a traceback.
    """
    raw = str(text).strip()
    if "=" not in raw:
        try:
            seconds = int(raw)
        except ValueError:
            raise argparse.ArgumentTypeError(
                f"-t {raw!r} is neither SECONDS nor POPULATION=SECONDS; "
                f"populations are {', '.join(POPULATIONS)}")
        return {pop: seconds for pop in POPULATIONS}
    pop, _, raw_seconds = raw.partition("=")
    pop = pop.strip()
    if pop not in POPULATIONS:
        raise argparse.ArgumentTypeError(
            f"-t names population {pop!r}; known: {', '.join(POPULATIONS)}")
    try:
        seconds = int(raw_seconds.strip())
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"-t {pop}= needs a whole number of seconds, not {raw_seconds!r}; "
            f"the populations are {', '.join(POPULATIONS)}")
    if seconds <= 0:
        raise argparse.ArgumentTypeError(
            f"-t {pop}={seconds} is not a bound: the build is killed at "
            f"`subprocess`'s own deadline, so every file in that population "
            f"would be reported `timeout` having built nothing. Omit -t for "
            f"the default ({DEFAULT_TIMEOUT}s).")
    return {pop: seconds}


def merge_timeout_args(values):
    """Fold repeated `-t` values into one mapping; a later value wins.

    `-t 90 -t repo=600` is a reader changing their mind about one population,
    and last-wins is what every other option in this tool does.
    """
    merged = {}
    for value in values or ():
        merged.update(value)
    return merged


# The stdlib subtrees swept when no paths are given. `std/` is the library
# itself — the code a real program links against. The stdlib's own `test/`
# (350 files, larger than everything else combined) and `benchmarks/` are left
# out of the default on purpose: they exercise the stdlib rather than measuring
# what the formal backend can lower, and including them would more than double
# the default sweep for very little extra signal. Ask for them by name
# (`--stdlib-subtrees std,test`) or pass roots.
DEFAULT_STDLIB_SUBTREES = ("std",)


def find_stdlib_path():
    """The external stdlib root, or None if it cannot be found.

    module_loader owns the discovery strategy (MOJO_STDLIB, then the known
    checkout, then an upward search), so the sweep does not grow a fourth,
    slightly different copy of it."""
    try:
        from module_loader import STDLIB_PATH
        if STDLIB_PATH and os.path.isdir(STDLIB_PATH):
            return os.path.abspath(STDLIB_PATH)
    except Exception:
        pass
    return None


def default_roots(stdlib_subtrees=DEFAULT_STDLIB_SUBTREES,
                  stdlib_path=None) -> tuple:
    """(roots, notes) for a no-argument sweep: this repo, plus the stdlib.

    `notes` carries anything the caller should print rather than swallow — a
    stdlib that could not be found, or a requested subtree that is not there.
    A silently narrower sweep is the failure mode that matters here: it looks
    like a clean run."""
    roots, notes = [REPO], []
    if not stdlib_subtrees:
        return tuple(roots), notes
    base = stdlib_path or find_stdlib_path()
    if not base:
        notes.append("stdlib not found (set MOJO_STDLIB or pass paths "
                     "explicitly) - swept the repo only")
        return tuple(roots), notes
    for sub in stdlib_subtrees:
        path = os.path.join(base, sub)
        if os.path.isdir(path):
            roots.append(path)
        else:
            notes.append(f"stdlib subtree {sub!r} not found under {base}")
    return tuple(roots), notes


def find_source_files(roots):
    if roots:
        files = []
        for root in roots:
            root = os.path.abspath(root)
            if os.path.isfile(root) and root.endswith(SUFFIXES):
                files.append(root)
            elif os.path.isdir(root):
                for dirpath, dirnames, filenames in os.walk(root):
                    dirnames[:] = [
                        d for d in dirnames
                        if d not in SKIP_DIRS and not d.startswith(".")
                    ]
                    for fn in filenames:
                        if fn.endswith(SUFFIXES):
                            files.append(os.path.join(dirpath, fn))
        return sorted(set(files))

    files = []
    for dirpath, dirnames, filenames in os.walk(REPO):
        dirnames[:] = [
            d for d in dirnames
            if d not in SKIP_DIRS and not d.startswith(".")
        ]
        for fn in filenames:
            if fn.endswith(SUFFIXES):
                files.append(os.path.join(dirpath, fn))
    return sorted(files)


def rel(path):
    return os.path.relpath(path, REPO)


# Container magics, as the BYTES they sit as. A fat header is big-endian
# (0xCAFEBABE) and a Mach-O header is little-endian (0xFEEDFACF), so reading
# either one as an integer through the other's byte order silently fails —
# which is why these are bytes and not numbers. In both kinds the CPU type is
# the second 4-byte field of the entry, at the same offset.
_MACHO_FAT = (b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf")
_MACHO_THIN = (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf")
_MACHO_MAGICS = _MACHO_THIN


def _load_commands(binary: bytes) -> list:
    """(cmd, offset) for every load command in a Mach-O image, in order.

    Total on purpose: a buffer too short to hold a header yields no commands
    rather than raising, because the callers must be able to ANSWER "I cannot
    read this image" — an exception here would surface as a `tool` verdict,
    which says nothing about the file, where a stated reason says the image
    could not be examined at all.
    """
    if len(binary) < 32:
        return []
    ncmds = struct.unpack_from("<I", binary, 16)[0]
    off, out = 32, []
    for _ in range(ncmds):
        if off + 8 > len(binary):
            break
        cmd, cmdsize = struct.unpack_from("<II", binary, off)
        if not cmdsize:
            break                       # a zero cmdsize would loop forever
        out.append((cmd, off))
        off += cmdsize
    return out


def _load_dylib_names(binary: bytes) -> list:
    """The LC_LOAD_DYLIB paths, in the image's own order.

    Order is the whole point: this emitter writes libSystem first and the
    linked formal libraries after it, and the bind stream's dylib ordinals are
    1-based over exactly this list (ordinal 1 = libSystem, ordinal k+2 =
    dylibs[k]). That is macho_linker.build_macho_executable_extern's own stated
    contract, and the same one its dylib layout follows ("libSystem is 1, then
    deps in the order recorded"), so there is no second numbering here to keep
    in step with the linker's.
    """
    names = []
    for cmd, off in _load_commands(binary):
        if cmd != ML.LOAD_DYLIB_CMD:
            continue
        # dylib_command: cmd, cmdsize, name.offset (into this command), …,
        # then the NUL-terminated name.
        name_off = struct.unpack_from("<I", binary, off + 8)[0]
        start = off + name_off
        if not off + 24 <= start < len(binary):
            continue                     # a name offset outside the command
        end = binary.find(b"\0", start)
        if end < 0:
            continue
        names.append(binary[start:end].decode("utf-8", "replace"))
    return names


def _binds(binary: bytes) -> list:
    """[(dylib ordinal, symbol name)] from the image's bind stream, in order.

    The images carry no LC_SYMTAB (the linker never emits one), so neither
    `nm -u` nor `dyld_info -imports` can list what they need — the names live
    only in the classic dyld bind opcodes, which this project writes itself
    (macho_linker._bind_info), so walking them here is exact rather than a
    heuristic. Opcode constants come from the linker, so the two cannot drift.

    The ordinal is read rather than assumed, and kept, because it is what dyld
    itself will use: a two-level-namespace bind is resolved in ONE named
    library, so the question "is this name available?" is only meaningful
    relative to the library the image said provides it.
    """
    # LC_DYLD_INFO_ONLY gives the bind stream's file offset and size.
    bind_off = bind_size = None
    for cmd, off in _load_commands(binary):
        if cmd == ML.DYLD_INFO_ONLY_CMD:
            # dyld_info_command: cmd, cmdsize, rebase_off, rebase_size,
            # bind_off, bind_size, … — bind_off is the FIFTH field.
            (_c, _cs, _ro, _rs, bind_off,
             bind_size) = struct.unpack_from("<IIIIII", binary, off)
            break
    if not bind_size:
        return []
    # Walk the opcodes. This emitter's own layout (macho_linker._bind_info),
    # per bound symbol:
    #     BIND_SET_DYLIB_ORDINAL_IMM|n, BIND_SET_SYMBOL_TRAILING_FLAGS_IMM,
    #     <flags byte>, <name>\0, BIND_SET_TYPE_IMM|…, BIND_SET_SEGMENT_AND_
    #     OFFSET_ULEB|seg, <ULEB offset>, BIND_DO_BIND
    # and a trailing BIND_DONE. The flags byte is what a walker that assumes
    # the plain SET_SYMBOL form gets wrong: it reads it as the first
    # character of the name.
    stream = memoryview(binary)[bind_off:bind_off + bind_size]
    # dyld's documented default when no ordinal has been set is "this image",
    # which is never what the formal linker emits — it writes
    # BIND_SET_DYLIB_ORDINAL_IMM before every single name — so the default here
    # is libSystem (ordinal 1), and a stream that ever relied on the default
    # would report every one of its names against the wrong library.
    i, ordinal, out = 0, 1, []
    while i < len(stream):
        byte = stream[i]
        i += 1
        if (byte & 0xF0) == ML.BIND_SET_DYLIB_ORDINAL_IMM:
            ordinal = byte & 0x0F         # BIND_OPCODE_MASK / _IMMEDIATE_MASK
        elif byte == ML.BIND_SET_SYMBOL_TRAILING_FLAGS_IMM:
            i += 1                       # the trailing-flags byte
            start = i
            while i < len(stream) and stream[i] != 0:
                i += 1
            if i > start:
                name = bytes(stream[start:i]).decode("utf-8", "replace")
                out.append((ordinal, name))
            i += 1                       # the NUL
        elif (byte & 0xF0) == ML.BIND_SET_SEGMENT_AND_OFFSET_ULEB:
            while i < len(stream) and stream[i] & 0x80:      # ULEB offset
                i += 1
            i += 1
        # every other opcode this emitter writes carries no operand
    return out


def _bind_symbols(binary: bytes) -> list:
    """The external symbol names a Mach-O image binds, in bind-stream order."""
    return [name for _ordinal, name in _binds(binary)]


# ── Can dyld bind what this image binds? ─────────────────────────────────────
#
# The question, stated exactly: for THIS image, at load time, can the dynamic
# linker find every name in its bind stream?
#
# The probe this replaces answered a different question — "is this name visible
# in the sweeping python process right now?" — and the two come apart in BOTH
# directions, which is what made it unfit to decide a verdict:
#
#   * FALSE POSITIVE, and the one that made this tool lie. A formal import is
#     resolved into a real dylib that goes on the link line (formal/build.py's
#     _resolve_imports), so the image's LC_LOAD_DYLIB names it and dyld binds
#     the call from there. The helper symbol is in no library this python has
#     loaded, so the probe said "unresolvable" and reported the exact success
#     the import machinery exists to produce: `example_imports.mojo`, whose
#     image builds, loads, and exits 40.
#   * FALSE PASS, which is worse and is why the probe could not simply be
#     widened to "search every library the process has". `ctypes.CDLL(None)`
#     searches the whole global namespace, so a name exported by the python
#     binary, or by anything else already loaded, read as "resolvable" even
#     when nothing on this image's link line defines it.
#
# The method here answers the question asked, from the image's own bytes:
#
#   1. read the image's LC_LOAD_DYLIB list, in order (_load_dylib_names);
#   2. read each bind as the (ordinal, name) pair dyld itself will use (_binds);
#   3. look the name up in THAT library alone — by dlopen+dlsym where this
#      process can load it, and otherwise by reading the library's EXPORT
#      TRIE, which is the same table dyld consults and which needs no load at
#      all (_exports).
#
# So the answer is dyld's own two-level lookup, minus dyld. Step 3's two arms
# are not interchangeable and are not a preference between them. `dlopen` can
# only ever load a library of THIS process's architecture, so on an arm64 host
# an x86-64 image's own perfectly good x86-64 dylibs could not be looked up at
# all, and until 2026-10-02 the tool answered that by refusing to answer —
# which cost 7 correct images their verdict outright and made the x86-64 sweep's
# pass count a floor rather than a number
# (bugs/FORMAL_sweep_work_map_2026-10-01.md §4). Reading the trie answers the
# same question from the same bytes, on any host. `formal/build.py`'s
# `macho_dylib_exports` is already this project's independent reader of that
# format (an independent one deliberately: `formal/macho_linker.py` writes these
# images, and asking a writer to read its own output is how its bugs hide), so
# the sweep calls that rather than growing a second reader.
#
# What this DOES prove: for every name the image binds, there is a library on
# its link line that loads here and exports that name.
#
# What this does NOT prove, spelled out so nobody reads a `pass` as more than
# it is:
#   * libSystem is answered from the HOST process's libSystem
#     (`ctypes.CDLL(None)`), which is the same library the image will load and
#     the same one an x86-64 image's dyld resolves against under Rosetta 2 —
#     same library, same exports, different slice. A name the two slices
#     disagreed on would be missed; the formal backends emit no such name.
#   * dlopen happily accepts a library whose architecture is not the image's,
#     so that is checked separately (_loadable_for): an arm64 dylib on an
#     x86-64 image's link line exports exactly the right names and still
#     cannot be loaded. That is a real load failure, reported as one.
#   * For a library this process cannot dlopen, loadability is established from
#     that library's own header and the name lookup from its export trie — so
#     "the image's dyld could actually LOAD it" is not among the things checked
#     for it. A corrupt, truncated or otherwise unsatisfiable dylib of the other
#     architecture would read here as a resolution. The trie is exactly what
#     dyld resolves against, so this is a small gap rather than a different
#     question, but the direction to be honest about is named: it can only
#     overstate coverage, never understate it, and the run prints how many
#     binds were answered this weaker way so a reader of a `pass` can tell.
#   * Nothing about behaviour. This says the image can be loaded and its
#     symbols bound; it does not say the program computes the right answer.
#     `make check-formal-run` is what runs images. Note the direction of the
#     remaining error: dyld binds function calls LAZILY, so an image that never
#     calls a missing symbol would run clean, and this probe still calls it
#     unresolved — the conservative direction, never the flattering one.
#
# A test that builds two real images through `fire.py build --formal` — one
# with a genuinely imported helper, one whose extern nothing defines — and
# settles every case against what dyld does when it loads them, lives in
# test_formal_sweep.py (TestDyldProbe). It is the only thing standing between
# this and a silent inversion.
_LIBSYSTEM = ML.LIBSYSTEM_PATH.decode().rstrip("\0")
_LIBS: dict = {}            # dylib path -> "" if it loads here, else the reason
_MEMO: dict = {}            # (dylib path, name) -> bool, for the whole run.
                            # The dlopen arm's memo ONLY: a statically-read
                            # table is memoised per LIBRARY in _EXPORT_TABLES
                            # instead, since one parse answers every name in it.

# The two CPU types this tool ever sees an image or a library built for, named
# so the "why" a finding prints is readable. Anything else falls back to the
# number, which is still an answer.
_CPU_NAMES = {ML.CPU_TYPE_ARM64: "arm64", ML.CPU_TYPE_X86_64: "x86_64"}


def _host_cputype():
    """The CPU type of the PROCESS doing the probing, or None if unreadable.

    Read from the running interpreter's own Mach-O header rather than from
    `platform.machine()`, because the question is not "what is this machine
    called" but "what will this process's dlopen accept" — and those are the
    same question with one fewer way to be wrong (a Rosetta-translated shell on
    an arm64 host reports the translated name).

    This is the fourth fact the probe needs, and until 2026-10-01 it was missing:
    the probe `dlopen`s each library on the image's link line, and dlopen can
    only ever load a library of THIS process's architecture. So on an arm64
    host, an x86-64 image's own perfectly good x86-64 dylibs could not be
    opened, and the resulting OSError was reported as the finding
    `dyld cannot load <path> here: ... (mach-o file, but is an incompatible
    architecture (have 'x86_64', need 'arm64'))` — a claim about the image,
    derived entirely from a limitation of the instrument. Measured: it is the
    whole of the arm64-vs-x86-64 pass difference, all 7 files, every one of them
    an image that builds and links correctly for its architecture
    (bugs/FORMAL_sweep_work_map_2026-10-01.md §4).

    It then became a SECOND limitation, having stopped being the first: the same
    mismatch made the tool decline to look the names up at all, filing those 7
    as `tool` with no verdict. So as of 2026-10-02 this fact decides only WHICH
    ARM of the lookup runs — `dlopen`+`dlsym` where this process can load the
    library, the library's export trie where it cannot (see `_exports`). It is
    still read from the interpreter's own Mach-O header rather than from
    `platform.machine()`, because the question it now answers is the same one:
    what can this process's loader open.
    """
    global _HOST_CPUTYPE
    if _HOST_CPUTYPE is _UNSET:
        _HOST_CPUTYPE = None
        for exe in (sys.executable, sys.prefix):
            types = _macho_cputypes(exe) if exe and os.path.exists(exe) else set()
            if len(types) == 1:
                _HOST_CPUTYPE = next(iter(types))
                break
    return _HOST_CPUTYPE


_UNSET = object()
_HOST_CPUTYPE = _UNSET


def _host_arch_name() -> str:
    """This process's architecture, in the spelling the report uses."""
    host = _host_cputype()
    return _cpu_name(host) if host is not None else "unknown-architecture"


def _cpu_name(cputype: int) -> str:
    return _CPU_NAMES.get(cputype, f"cpu type {cputype}")


def _macho_cputypes(path: str) -> set:
    """Every CPU type in the Mach-O file at `path` (empty if unreadable).

    Fat and thin both: a system library can be a fat file whose slice is
    chosen by dyld, and a thin one is what this project's linker emits. An
    unreadable or unrecognised file yields the empty set, which _loadable_for
    treats as "not provably loadable" — the direction that produces a finding
    rather than a pass. (See _MACHO_FAT/_MACHO_THIN for why the magics are
    compared as bytes.)
    """
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
            if magic in _MACHO_FAT:
                n = struct.unpack(">I", f.read(4))[0]
                table = f.read(32 * n)     # fat_arch_64 covers fat_arch too
                return {struct.unpack_from(">i", table, 32 * i + 4)[0]
                        for i in range(n)}
            if magic in _MACHO_THIN:
                f.seek(4)
                return {struct.unpack("<i", f.read(4))[0]}
            return set()
    except OSError:
        return set()


def _loadable_for(path: str, cputype: int):
    """`(state, foreign, why)` for a library this image's dyld could load.

    FOUR states, and the fourth is the one added on 2026-10-02. `foreign` is the
    architecture a host would need in order to answer by LOADING the library,
    and is None for the other three:

      ("loadable",    None, "")     the image could load it, and a load says so
      ("header-only", arch, "")      the image could load it — its own header
                                    says so — but this process cannot dlopen it
                                    to confirm, so `_exports` must read its
                                    export trie instead
      ("unloadable",  None, why)    the image could NOT load it — a real failure
      ("unprovable",  None, why)    this PROCESS cannot find out at all

    dlopen is deliberately NOT the test for the third — it is happy to load a
    library built for the other architecture, which is precisely the case dyld
    refuses and precisely the case that would turn this probe into a false PASS.
    The architecture is checked first, from the file's own header; cpusubtype is
    not, because dyld accepts a mismatch there and matching it more strictly
    would invent findings.

    `header-only` is separated from `unloadable` because "this image cannot load
    it" and "I cannot check whether this image can load it" are different facts
    and the tool conflated them. A `dlopen` failure on a library of the HOST's
    architecture is a fact about the image (the image's dyld runs in the same
    world). A `dlopen` failure on a library of the OTHER architecture says
    nothing at all about the image — the image's dyld would be a different
    process on a different slice. Reporting it as a load failure filed 7 correct
    x86-64 images as `not-answerable/unresolved-extern` on an arm64 host.

    `header-only` is then separated from `unprovable` because the NAME lookup
    does not need a load either: dyld resolves a bind against the library's
    export trie, which is bytes in a file this process is perfectly able to
    read whatever it is built for. So "I cannot dlopen it" stops being the end
    of the answer and becomes the choice of which arm of the lookup to run
    (`_exports`). `unprovable` survives for what is genuinely unknowable here:
    this process's own architecture cannot be established, or the trie could
    not be read.

    libSystem short-circuits to "loadable" without any of the checks: it is
    answered from the host process (see the block comment above), and on this
    system /usr/lib/libSystem.B.dylib is a shared-cache stub with no header to
    read — so the arch test below would report every image as unloadable, which
    is the false-finding direction.
    """
    if path == _LIBSYSTEM:
        return "loadable", None, ""       # ordinal 1, answered from the host
    types = _macho_cputypes(path)
    if not types:
        return "unloadable", None, f"cannot read a Mach-O header at {path}"
    if cputype not in types:
        have = "/".join(sorted(_cpu_name(t) for t in types))
        return ("unloadable", None,
                f"{path} is built for {have}, which this "
                f"{_cpu_name(cputype)} image cannot load")
    host = _host_cputype()
    if host is None:
        # Cannot establish what this process can dlopen, so which arm of the
        # lookup below is the right one is unknown. Refusing to answer is the
        # direction that cannot invent a finding.
        return ("unprovable", None,
                f"cannot establish this host's architecture, so whether "
                f"{path} could be loaded here is unknown")
    if host not in types:
        foreign = "/".join(sorted(_cpu_name(t) for t in types))
        return ("header-only", foreign,
                f"{path} is built for {foreign}, which this "
                f"{_cpu_name(host)} host cannot dlopen — so the loadability "
                f"above is the file's own header rather than a load, and its "
                f"exports are read from its trie rather than dlsym'd")
    if path in _LIBS:
        return ("loadable" if not _LIBS[path] else "unloadable"), None, _LIBS[path]
    try:
        _LIBS[path] = ""
        ctypes.CDLL(path)
    except OSError as e:
        _LIBS[path] = f"dyld cannot load {path} here: {e}"
    return ("unloadable" if _LIBS[path] else "loadable"), None, _LIBS[path]


# The export trie of each library read statically, as (exports or None, why).
# Read once per library per run: an image binds the same helper dylib for every
# one of its imports, and the parse is the only part of this probe that is not
# O(bytes of a load command). Keyed by path, so a library swapped under a run is
# still one answer — and the swap is caught by the CAS key, not by this memo.
_EXPORT_TABLES: dict = {}

# Binds answered from an export trie rather than by dlopen, and the files they
# were in. Its own counters beside `_DYLIB_LINKED`, for `_DYLIB_LINKED`'s
# reason: these are facts about how this tool reached a verdict, not CAS
# lookups, and the summary prints them because a `pass` reached this way is
# weaker than one confirmed by a load (see the block comment above).
_STATIC_BINDS = 0
_STATIC_FILES = 0


def _bump_static_probe(nbinds: int) -> None:
    global _STATIC_BINDS, _STATIC_FILES
    with _STATS_LOCK:
        _STATIC_BINDS += nbinds
        _STATIC_FILES += 1


def _static_exports(path: str):
    """`(exports, why)` for a library's EXPORT TRIE — the table dyld consults.

    `exports` is None when the trie could not be read, and `why` then says why.
    Read through `formal.build.macho_dylib_exports`, which is this project's
    own reader of the format and RAISES rather than answering partially: a name
    quietly missing from that dict is a bind called unresolvable, and a name
    quietly added is a bind whose ordinal points at the wrong library, so a
    truncated answer is the one thing worse than none.

    Every exception is caught, and this is deliberate in a way the rest of the
    probe is not: an unreadable table must be able to become a stated "I cannot
    find out" (which `_resolvable` files as `unprovable`, no verdict) and must
    never become a resolution or an accusation. Both of those would be
    inventions about the image derived from a reader that failed.
    """
    if path not in _EXPORT_TABLES:
        try:
            from formal.build import macho_dylib_exports
            _EXPORT_TABLES[path] = (macho_dylib_exports(path), "")
        except Exception as e:                    # see the docstring
            _EXPORT_TABLES[path] = (None, f"{path}: its export table could not "
                                          f"be read ({e})")
    return _EXPORT_TABLES[path]


def _macho_symbol(bind_name: str) -> str:
    """The Mach-O EXPORT NAME dyld forms from a bind-stream name.

    Exactly one leading underscore, and it is dyld's: the bind stream carries
    the C name (`macho_linker._bind_info` writes it as given), while the export
    trie — and every other lookup table in the format — carries the Mach-O name,
    which is that C name with one `_` in front. `_os__syscalls_str_alloc_9f63a2`
    is the export; the bind says `os__syscalls_str_alloc_9f63a2`.

    `macho_linker.macho_export_name` IS that mapping, and this asks it rather
    than repeating it: the probe exists to corroborate the build's own symbol
    accounting against the loader, so a fourth independent spelling of the rule
    would be able to disagree with the three that produce the image — and did,
    in the one case where it mattered, which is why the two ends of the rule now
    live in one function.

    The dlopen arm gets this for free: on macOS `ctypes` prepends the same
    underscore before calling `dlsym`, so it is handed the bind name unchanged.
    The static arm has no such shim, so it applies the mapping here — and gets
    it wrong in the worst direction if it does not, looking up a name the trie
    cannot hold and reporting a load failure for an image that loads. Measured:
    that is what the first version of the static arm did, on
    `formal/hostmods/ast.mojo`, whose three binds all came back "not exported"
    from a dylib that exports all three.
    """
    from formal.macho_linker import macho_export_name
    return macho_export_name(bind_name)


def _libsystem_provides(name: str) -> bool:
    """Whether the C library provides `name`, asked the way the build asks.

    Delegated rather than re-implemented, and the delegation is the point: there
    were two answers to this question on this tree, and they disagreed on
    exactly one architecture's worth of names. `formal/build.py`'s
    `_is_libsystem` asks about `model.libc_source_name(name)` — the name the
    SOURCE spells — because macOS's C library exports the whole
    directory-and-stat family twice (`readdir` and `readdir$INODE64`) and which
    one a given target's calls bind is the TARGET's choice, decided in
    `model.target_libc_symbol`. This probe used to hand the bind name straight
    to `dlsym`, and on this host that is the host's libSystem, so every
    x86-64 image was asked about a spelling the host does not have. Measured,
    and it is the whole of the arm64-vs-x86-64 difference in the 2026-10-02
    sweep: `formal/hostmods/os/_syscalls.mojo`, which binds five `$INODE64`
    names on x86-64 and none on arm64, was reported
    `not-answerable/unresolved-extern` on x86-64 and `pass` on arm64 — an image
    that builds, links and loads, measured by running it: `arch -x86_64` on the
    x86-64 image exits with an empty stderr (the code is the module's own; the
    arm64 one exits 64 and this one 80), where the refusal had said dyld could
    not bind five of its symbols.

    Two things come with the delegation and both are wanted. The C library is
    asked through a handle on the library itself rather than through
    `ctypes.CDLL(None)`, which searches this process's whole global namespace —
    the false-PASS direction `_libsystem_handle`'s own docstring measures on
    this machine (`sqlite3_open` and `inflate` are visible there and are not in
    libSystem). And every C function name in a real formal image answers the
    same on both handles, measured, so nothing that passed before stops
    passing; only the names this process loaded for its own reasons change
    answer, and those are exactly the ones that should.
    """
    from formal.build import _is_libsystem
    return _is_libsystem(name)


def _exports(path: str, name: str, static: bool = False):
    """`(state, why)` for whether the library at `path` exports `name`.

    `state` is `"exported"`, `"not-exported"`, or `"unprovable"` — the third for
    the static arm only, and it exists so a table this tool could not read is
    never silently the same answer as a table that does not carry the name.

    TWO WAYS TO ASK, and which one is right is a fact about this process rather
    than a preference. `static=False` is `dlopen` + `dlsym`, which is what the
    host can do for its own architecture and what libSystem is always answered
    from. `static=True` reads the library's export trie: the same table dyld
    resolves against, read out of the file rather than through a load, so it
    answers for a library of ANOTHER architecture too — which is the whole
    reason it exists (2026-10-02; before that, an x86-64 image probed from an
    arm64 host got no verdict at all, see the block comment above).

    A DYLIB's name goes to dlsym EXACTLY as the image's bind stream spells it,
    and that is the whole contract. The stream already carries the C name —
    `macho_linker._bind_info` takes off the single leading underscore that is
    dyld's rather than the name's, and dyld puts it back on when it forms the
    symbol it looks up — so the name read back out of the image is already the
    spelling `dlsym` wants, and this must not normalise it a second time.

    It used to, with `lstrip("_")`, which is wrong in the direction that
    invents findings. A formal module's ABI prefix can begin with an
    underscore — `abi_module_name('._syscalls')` is `__syscalls`, so EVERY
    relative import produces one — and stripping "the" underscore turned the
    bind name `_syscalls_fs_chdir_9f63a2` into `syscalls_fs_chdir_9f63a2`,
    which dlsym resolved against `__syscalls_fs_chdir_9f63a2` and did not find.
    The sweep then reported a load failure for an image that loads: measured on
    `formal/hostmods/os/__init__.mojo` and `formal/hostmods/os/path/__init__.mojo`,
    both classified `unresolved-extern` on a build that links and runs. See
    `bugs/FORMAL_relative_submodule_abi_prefix_off_by_one.md`. A dylib's name is
    therefore still not normalised, and the static arm still applies exactly the
    one mapping that IS correct on macOS (`_macho_symbol`).

    libSystem is the exception, and for the opposite reason: its name is not
    this project's to spell. See `_libsystem_provides`.

    `macho_dylib_exports` lists ORDINARY exports only, and the omission is
    deliberate rather than tidy: a thread-local or an absolute is not something
    an image can call at this bind, so its absence is the answer. A RE-EXPORT is
    the one kind where dyld would have kept looking (into the re-exporting
    library's own dependencies) and this table does not, so a library that
    forwarded a name would be reported unresolved when dyld would have bound
    it. It cannot arise here and the reason is worth stating rather than
    assuming: `formal/macho_linker.py`'s `_export_trie` writes every terminal
    with flags 0, `EXPORT_SYMBOL_FLAGS_KIND_REGULAR`, and that is the only
    emitter of a dylib on this link line. So the gap is documented, closed, and
    would need reopening only if a re-exporting library ever entered the path.
    """
    if static:
        exports, why = _static_exports(path)
        if exports is None:
            return "unprovable", why
        found = _macho_symbol(name) in exports
    elif path == _LIBSYSTEM:
        found = _libsystem_provides(name)
    else:
        key = (path, name)
        if key not in _MEMO:
            lib = ctypes.CDLL(path)
            _MEMO[key] = hasattr(lib, name)
        found = _MEMO[key]
    if found:
        return "exported", ""
    return "not-exported", f"{name} is not exported by {path}"


def _resolvable(ordinal: int, name: str, dylibs: list, cputype: int):
    """`(state, foreign, why)` for whether dyld can bind `name` from `ordinal`.

    See the block comment above: the answer is read out of the image's own load
    commands and bind stream, and looked up in the one library dyld would use.

    `state` is the whole of the answer and `"resolved"` is the only success, so
    a caller cannot mistake a partial answer — including "this host cannot find
    out" — for a resolution. `foreign` on a `resolved` is a qualifier, never a
    second outcome: it names the architecture of the library when the lookup was
    a static export-trie read because this process could not dlopen it, so a
    caller that wants to count the verdicts reached the weaker way can, and one
    that only reads `state` cannot be misled by it.
    """
    if not dylibs:
        return "unresolved", None, "the image has no load commands"
    if ordinal < 1 or ordinal > len(dylibs):
        return ("unresolved", None,
                f"the bind names dylib ordinal {ordinal}, which the image's "
                f"{len(dylibs)} load command(s) do not define")
    path = dylibs[ordinal - 1]
    state, foreign, bad = _loadable_for(path, cputype)
    if state == "unprovable":
        # Propagated as itself rather than folded into "unresolved": the caller
        # files the two differently, and that difference is the whole point.
        return state, foreign, bad
    if state == "unloadable":
        return state, None, f"{bad}; nothing in it binds"
    found, why = _exports(path, name, static=(state == "header-only"))
    if found == "unprovable":
        return "unprovable", foreign, why
    if found == "not-exported":
        return "unresolved", None, why
    return "resolved", foreign, ""


# A name the image binds that no loadable library provides, and the reason —
# so the printed finding says WHICH library was consulted and what was wrong
# with it, rather than only how many names there were.
#
# `unprovable` is a third answer beside "dyld cannot bind this" and "dyld binds
# this": it means the sweep ran on a host that cannot answer, so the name is
# neither bound nor unbound as far as this run knows. Carried on the record
# rather than encoded in the message, because run_one files the two differently
# and a caller that had to tell them apart by reading prose would eventually
# read them the same way round.
Missing = collections.namedtuple("Missing", "name why unprovable foreign")


def _unresolved_imports(binary: bytes) -> list:
    """The names the image binds that dyld cannot bind, with the reason each.

    A name here means the image builds and then dyld refuses to load it (or
    would, at the first call to it): that is not coverage and is not a codegen
    finding, so it is reported in its own class. See the block comment above
    for what this does and does not prove.

    `Missing.unprovable` marks the names this host could not check at all; see
    _loadable_for's fourth state. Both kinds are returned so a caller can see
    that a name was looked for, and the caller is what decides that one is a
    finding and the other is a gap in the run.

    Counts this image's statically-read lookups, because a resolved name found
    in an export trie is a weaker fact than one dlsym'd out of a loaded library
    and the summary has to be able to say how many verdicts rest on it (see
    `_bump_static_probe`).
    """
    dylibs = _load_dylib_names(binary)
    if not dylibs and binary[:4] not in _MACHO_MAGICS:
        # A real image of this project always loads libSystem, so no load
        # commands at all means the header was not readable — NOT "there is
        # nothing to bind", which would be a false pass produced by the
        # failure of the reader itself. Said out loud instead.
        return [Missing("<unreadable image>",
                        f"{len(binary)} bytes with no Mach-O header, so what "
                        f"it binds could not be read at all", False, None)]
    cputype = struct.unpack_from("<i", binary, 4)[0]
    out = []
    static = 0
    for ordinal, name in _binds(binary):
        state, foreign, why = _resolvable(ordinal, name, dylibs, cputype)
        if state == "resolved":
            # A `resolved` with `foreign` set was read out of an export trie
            # rather than dlsym'd out of a loaded library, because this process
            # cannot dlopen a library of the image's architecture. That is a
            # real answer — it is the table dyld resolves against — but it is
            # the weaker of the two, so it is counted for the summary.
            if foreign is not None:
                static += 1
            continue
        out.append(Missing(name, why, state == "unprovable", foreign))
    if static:
        _bump_static_probe(static)
    return out


def _verdict_bytes(ok, detail):
    return b"ok\n" if ok else b"fail\n" + detail.encode("utf-8", "replace")


def _verdict_from_bytes(raw):
    ok, _, detail = raw.decode("utf-8", "replace").partition("\n")
    return (ok == "ok"), detail.strip()


# What run_one returns. Named rather than a tuple because it has five fields
# and every reader of it has to know which is which: `ok` alone is the thing
# this tool used to return, and the whole point of the record is that `ok` is
# not enough to report on. `cls`/`reason` are filled in by classify() from the
# other three plus the file's own source, so the classification happens where
# the source is in hand — once per file, on cache hits as much as on misses.
Verdict = collections.namedtuple(
    "Verdict", "ok detail cause cached cls reason")

# What one build invocation produced. A named type rather than a
# subprocess.CompletedProcess with attributes hung off it, because the two facts
# that are not on a CompletedProcess (`mem_killed`, `peak_gb`) are the two a
# reader of this file has to be unable to miss: they are why a file has no
# verdict, and what it cost. `returncode`/`stdout`/`stderr` carry their usual
# meanings, and `stdout`+`stderr` are the BUILD's streams — memcap's own
# accounting is read off them in _run_build and not passed on, so nothing
# downstream can match a `memcap:` line as if the build had printed it.
BuildRun = collections.namedtuple(
    "BuildRun", "returncode stdout stderr mem_killed peak_gb wrapper_died")


# ── Per-file memory ceiling ──────────────────────────────────────────────────
# The sweep launches `jobs` builds at once and, until 2026-10-01, ran each one
# with nothing between it and the machine. That is the structural reason the
# arm64 sweep could be killed outright by one file: 18 unbounded children, no
# per-file ceiling, and a build driver that will happily recurse through a
# module closure. Measured on that tree, no single file exceeded 0.2 GB and the
# whole -j18 sweep peaked at 1.97 GB — so the ceiling below is generous by an
# order of magnitude against every file measured, and it is here for the file
# nobody has run yet rather than to bound anything observed.
#
# It is deliberately the SHARED implementation (tools/memcap.py, whose
# measurement and kill are in tools/procrun.py) rather than a second copy of a
# process walk here: a second RSS-threading-and-killing implementation is a
# second set of ways to get the tree walk wrong, and `formal-sweep` is
# registered in the suite under a `small` memclass precisely because memcap is
# what enforces it.
#
# `MEMCAP_GB` is measured against the per-file peaks above and the 3-4 GB
# standard in bugs/PERF_memory_over_4gb_is_a_bug.md: over 4 GB for one file's
# build is a debt, so 4 GB is both a real bound and a claim worth making.
MEMCAP_GB = 4.0


def _build_argv(path, out, flags, mem_gb):
    """The argv for one file's build, under `memcap` when a ceiling is set.

    `mem_gb` <= 0 means no ceiling, and then this is the bare build. That is a
    real mode rather than a degenerate one: a ceiling of 0 would also be read as
    "off" by memcap itself, so the two would agree by accident, and a caller that
    passes 0 deserves the un-capped build it asked for rather than a child that
    is killed instantly.
    """
    build = [sys.executable, FIRE, "build", *flags, "-o", out, path]
    if not mem_gb or mem_gb <= 0:
        return build
    return [sys.executable, MEMCAP, "--limit-gb", str(mem_gb),
            "--label", os.path.basename(path), "--"] + build


def _as_text(value) -> str:
    """`str(value)` for a pipe's output, which may be bytes or str.

    `subprocess`'s timeout path hands back bytes even where the pipes were
    opened in text mode, so every reader of a `TimeoutExpired` would otherwise
    have to ask. One place that asks.
    """
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _run_build(path, out, flags, timeout, mem_gb):
    """Run one file's build under its memory ceiling. Returns a BuildRun.

    The child gets its own process group (`start_new_session`), which is what
    makes both bounds here whole-tree rather than direct-child: `subprocess.run`'s
    timeout SIGKILLs the process it started, and a build that has spawned a
    compiler of its own would leave that compiler running and still holding the
    memory the kill was meant to release. Under memcap that is moot — memcap
    walks and kills the tree itself — but the timeout fires on the memcap
    wrapper, and the wrapper's own group is this one, so the two bounds nest
    correctly rather than fighting.

    `mem_killed` is the whole point of the exercise and it is carried as a
    FIELD rather than left to be re-derived from the exit code, because the exit
    code cannot carry it: memcap's 125 is also what a build that exits 125 by
    itself produces, and procrun.memcap_verdict exists to refuse exactly that
    conflation. The peak travels with it so the report can name the number the
    ceiling was measured against rather than only saying a kill happened.

    `Popen` + `kill_group` rather than `subprocess.run(timeout=…)`, and the
    difference is the whole of the timeout's reach. `subprocess.run` SIGKILLs
    the process it started and nothing below it, so a timeout here killed the
    memcap WRAPPER and left its child — the build — running, unmonitored, still
    holding the memory the ceiling exists to bound. The child was already in its
    own session (which is what makes a group kill possible at all); nothing was
    using it. `procrun.kill_group` is the same call `tools/suite.py` makes on
    every job it times out, and its docstring is why it walks the tree before
    killing the group: a group kill aimed at the wrapper stops AT the wrapper,
    which would recreate the runaway the ceiling exists to prevent.

    stdout and stderr stay SEPARATE (the classifier prefers stderr), so this is
    `procrun.spawn` — which merges them — plus an explicit `Popen` rather than
    the shared helper. The `TimeoutExpired` is re-raised rather than returned as
    a `BuildRun`, because that is the contract `run_one` reports a timeout
    through (and a timeout is deliberately never published — see there).
    """
    argv = _build_argv(path, out, flags, mem_gb)
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True,
                            cwd=REPO, start_new_session=True)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as e:
        # The tree goes down FIRST, and the wait for its output comes after, so
        # what the build printed before it died is not lost to the pipe: a file
        # that refused a construct and then hung should still show the refusal.
        procrun.kill_group(proc)
        try:
            stdout, stderr = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", ""
        # `communicate(timeout=…)` puts BYTES on the exception even with
        # text=True on this interpreter, and a caller that concatenates
        # `.output` with a str gets a TypeError instead of the message.
        raise subprocess.TimeoutExpired(
            argv, timeout, output=stdout or _as_text(e.output),
            stderr=stderr or _as_text(e.stderr)) from None
    mem_killed, peak, wrapper_died = False, None, False
    if mem_gb and mem_gb > 0:
        # memcap's own accounting goes to stdout, where it would otherwise be
        # mistaken for the build's message. It is read here, off the CHILD's
        # streams, rather than stripped from what the classifier sees: the
        # classifier must not be able to match a `memcap:` line as a build
        # refusal, and the build's real message is the one it should read.
        mem_killed, peak = procrun.memcap_verdict(
            (stdout or "") + (stderr or ""))
        wrapper_died = procrun.memcap_wrapper_died(
            (stdout or "") + (stderr or ""))
    return BuildRun(proc.returncode, stdout, stderr, mem_killed, peak,
                    wrapper_died)


def _timeout_detail(timeout, population=None) -> str:
    """The `tool` detail for a build that hit its bound.

    One place, because the number and the population name are the same fact
    split in two: the summary counts this string's cause and the per-file row
    prints it, and a wording that named the population in one and not the other
    would leave the summary unable to answer the question the row raised.
    """
    if population:
        return f"timeout (> {timeout}s, {population} population)"
    return f"timeout (> {timeout}s)"


def run_one(path, timeout, flags, mem_gb=MEMCAP_GB, population=None) -> Verdict:
    """Build one file and classify the outcome. See Verdict.

    `timeout` is this FILE's bound in seconds, already resolved from `-t` by
    `Timeouts.for_file` — the caller owns the population question and this
    function owns none of it. `population` is that same file's name, and it
    appears in the timeout row because the bound it hit is only half the fact:
    a reader who sees `timeout (> 30s)` on `imports.py` cannot tell whether the
    30 was the stdlib default or a repo-file bound they chose, and the two want
    different next steps. It is optional so a caller with no `Timeouts` in hand
    (a test harness, a one-file probe) gets the older wording.

    `cause` is non-None when the outcome is not one of the build's own
    diagnostics — a timeout, an unreadable file, an internal exception in the
    sweep, or an exception the build raised instead of refusing a construct.
    That distinction is the whole reason this returns more than a boolean:
    "the build refused" and "I never got a usable answer" are different facts
    about a file, and folding them into one `False` is what made a timeout
    indistinguishable from a finding. `cached` says whether this verdict came
    from (or went into) the CAS, so the accounting line can account for every
    input file rather than only the ones that reached the cache.

    `flags` is the build flag tuple (see build_flags) — required, not defaulted,
    because it is simultaneously the cache key's input and the argv: a wrong
    default would publish one architecture's verdict under the other's key.

    Cached in the CAS under cas.formal_build_key (source bytes + the formal
    backend's sources + the interpreter + BUILD_FLAGS + _criteria_id() + this
    file's IMPORT CLOSURE digest), so a re-run with nothing unchanged is a
    file read per file instead of a compile — and a change to a module this
    build COMPILES is a miss rather than a replay of the verdict that module's
    previous contents produced.

    The entry is the RAW build verdict (ok, detail); the class is derived from
    it by classify() on every run, for hits as much as for misses, so no cached
    entry can ever be reported under a class the current rules would not assign
    it, and the classification rules cannot go stale in the store even in the
    window before _criteria_id() invalidates the key. That double mechanism is
    deliberate: _criteria_id() is what makes a rule change take effect (and
    costs a rebuild), and re-deriving the class on every run is what makes a
    stale entry harmless if it ever survives.
    A timeout is a property of this machine's load, not of the source, so it is
    never published — it would otherwise pin a file at "timeout" until the key
    changed. Neither is a memory kill, for the same reason and one more: the
    ceiling that produced it is a flag on THIS run, so publishing would pin a
    file at "memory-killed" under a key that says nothing about which flag set
    it.
    """
    def verdict(ok, detail, cause, cached):
        cls, reason = classify(ok, detail, cause, source, path)
        return Verdict(ok, detail, cause, cached, cls, reason)

    source = None
    try:
        with open(path, "rb") as f:
            source = f.read().decode("utf-8", "replace")
    except OSError as e:
        return verdict(False, str(e)[:200], CAUSE_UNREADABLE, False)
    try:
        criteria = _criteria_id()
    except OSError as e:
        # No criteria id means no trustworthy key. Better to say so for this
        # one file than to publish a verdict under a key that cannot tell it
        # apart from a differently-built one.
        return verdict(False, f"cannot fingerprint this tool: {e}"[:200],
                       CAUSE_TOOL_ERROR, False)
    key = cas.formal_build_key(source, path, flags, criteria,
                               imports=_imports_digest(path))
    hit = cas.lookup(key, ".result")
    if hit is not None:
        _bump("hits")
        try:
            with open(hit, "rb") as f:
                ok, detail = _verdict_from_bytes(f.read())
            return verdict(ok, detail, None, True)
        except OSError:
            pass    # unreadable cache entry: fall through and rebuild
    _bump("misses")
    try:
        # -o into a temp dir so we don't scatter .aout across the tree
        with tempfile.TemporaryDirectory(prefix="formal_sweep_") as td:
            out = os.path.join(td, "a.out")
            proc = _run_build(path, out, flags, timeout, mem_gb)
            if proc.returncode == 0:
                with open(out, "rb") as f:
                    binary = f.read()
        if proc.returncode == 0:
            missing = _unresolved_imports(binary)
            # Whether the image links anything but libSystem decides whether
            # its verdict may be published at all — see the publish guard
            # below, which is the whole reason this is computed here.
            linked = [d for d in _load_dylib_names(binary) if d != _LIBSYSTEM]
            cause = None
            if missing:
                # Split first, because the two kinds need different files. A
                # name the probe could not check is NOT a fact about the image,
                # and reporting it as one is how 7 correct x86-64 images came
                # to be filed `not-answerable/unresolved-extern` on an arm64
                # host. If every unprovable name is unprovable, the file gets no
                # verdict at all and says why; if some are real, the real ones
                # are the finding and the unchecked ones are counted beside it,
                # because a reader has to know the finding is not the whole
                # story.
                unprovable = [m for m in missing if m.unprovable]
                real = [m for m in missing if not m.unprovable]
                names = sorted({m.name for m in real or unprovable})
                if not real:
                    # The reason is the PROBE'S, and is quoted rather than
                    # described: it is now "this host cannot dlopen a dylib of
                    # the image's architecture" for the loadability and "its
                    # export table could not be read" for the name, and a
                    # sentence written here would go on describing the first
                    # after the second had replaced it. Naming the architecture
                    # that a host WOULD need is kept, because that is the one
                    # thing a reader acts on.
                    need = unprovable[0].foreign
                    return verdict(
                        False,
                        f"builds, but this {_host_arch_name()} host cannot "
                        f"check the {len(unprovable)} import(s) it binds "
                        f"({', '.join(names[:3])}"
                        + (" ..." if len(names) > 3 else "")
                        + "): "
                        + unprovable[0].why
                        + (f". Re-run on a {need} host, or take this as "
                           f"unproven rather than as a failure" if need
                           else ". This run reports no verdict rather than a "
                                "failure"),
                        CAUSE_FOREIGN_ARCH, False)
                ok, detail = False, (
                    f"builds, but {len(real)} import(s) dyld cannot "
                    f"resolve: {', '.join(names[:3])}"
                    + (" ..." if len(names) > 3 else "")
                    + f" [{real[0].why}]"
                    + (f" ({len(unprovable)} further name(s) could not be "
                       f"checked from this host at all — see "
                       f"'{CAUSE_FOREIGN_ARCH}')" if unprovable else ""))
            else:
                ok, detail = True, ""
        else:
            # A memory kill outranks every reading of the message. memcap
            # SIGKILLed the tree, so there is no build message to read — whatever
            # the child managed to print before it died is not a verdict about
            # the source, and classifying it as one (a `codegen` row, via the
            # silent-death fallback below) would file a machine fact as a finding
            # about this file. It is checked FIRST, and it names the peak, so
            # the report says what happened rather than only that something did.
            if proc.mem_killed:
                return verdict(
                    False,
                    f"killed at the {mem_gb:g} GB per-file ceiling"
                    + (f" (peak {proc.peak_gb:.1f} GB)" if proc.peak_gb else ""),
                    CAUSE_MEMORY, False)
            err = (proc.stderr or proc.stdout or "").strip()
            # keep the last non-empty line — that's the formal build's message
            lines = [ln for ln in err.splitlines() if ln.strip()]
            # …but memcap's own accounting is not the build's message, and the
            # namedtuple's docstring above promises nothing downstream can
            # match one. It is separated here rather than only in the branch
            # below, because a build that printed NOTHING leaves the wrapper's
            # `done, … child exit -9` line as the last line there, and that is
            # how "the ceiling wrapper's bookkeeping" becomes a file's alleged
            # refusal. `build_lines` is empty exactly when the build said
            # nothing at all.
            build_lines = [ln for ln in lines
                           if not ln.startswith("memcap: ")]
            if proc.wrapper_died and not build_lines:
                # The wrapper started the build and never reported how it
                # ended, so there is no verdict about the source to report —
                # not a refusal, and not a memory kill either, since nothing was
                # measured against the ceiling. Not published, for the reason a
                # timeout and a memory kill are not: it is a fact about this
                # run's machine, and a verdict published under this key would
                # pin the file here until the key changed.
                #
                # The signal is NAMED, read off the wrapper's own exit status,
                # because "what killed the wrapper" used to be an open question
                # for exactly this state (six files per architecture, 2026-10-02,
                # `bugs/FORMAL_sweep_memcap_death_is_filed_as_codegen.md`) and an
                # exit status answers it without anybody reproducing it. memcap
                # handles SIGTERM and SIGINT (it reports `interrupted`, kills its
                # tree and exits 130/143), so the only signal that can leave this
                # state behind is SIGKILL — and in this repository the only thing
                # that sends one is `tools/control.py guard`, aimed at the largest
                # process in a worker tree once the tree's RSS sum passes its
                # budget. So the row now names its own cause instead of leaving
                # a reader to guess which of the two it was.
                sig = (-proc.returncode if proc.returncode is not None
                       and proc.returncode < 0 else None)
                who = ("killed by SIGKILL, which nothing here can catch: in this "
                       "tree that is tools/control.py guard, aimed at the "
                       "largest process in a worker worktree once the tree's "
                       "RSS sum passes its budget"
                       if sig == 9 else
                       f"killed by signal {sig}" if sig else
                       "gone, and its exit status says nothing about how")
                return verdict(
                    False,
                    f"the {mem_gb:g} GB per-file wrapper (tools/memcap.py) died "
                    f"before it reported an outcome — {who} — so its banner is "
                    f"in the output with no breach and no completion and this "
                    f"build's own verdict was never observed. A fact about this "
                    f"run's machine, not about the source; not cached, so "
                    f"re-running re-measures it",
                    CAUSE_WRAPPER_DIED, False)
            # No message at all still counts as the build's own verdict: with
            # no traceback there is no evidence of a crash, and a silent death
            # is far more often a refusal whose message went to stdout. The
            # fallback is deliberately the finding side (a codegen row: exit 1,
            # printed, in the denominator) — a crash we cannot see must not be
            # able to hide, and a false FAIL only sends someone to look.
            detail = (build_lines[-1] if build_lines
                      else f"exit {proc.returncode}")
            ok = False
            cause = _crash_cause(err)
            if cause == CAUSE_BACKEND_CRASH:
                # Say so in the printed line: the raw last line of a traceback
                # reads as a Python error in the file, when what happened is
                # the backend hitting an AST shape it has no case for.
                detail = f"the backend raised: {detail}"
            elif cause == CAUSE_DRIVER_CRASH:
                detail = f"the build driver raised: {detail}"
        # A crash is NOT published as if it were a verdict: the traceback that
        # decides its class is not in the cached bytes, so a re-read of this
        # entry would classify it as a plain build refusal. It stays a miss
        # until the key changes, which is the honest outcome — this file's
        # verdict depends on stderr this tool does not cache.
        if cause:
            return verdict(ok, detail, cause, False)
        if proc.returncode == 0 and linked:
            # A verdict about an image that links a formal dylib DEPENDS ON
            # that dylib, and the dylib is not part of the cache key: it lives
            # at a fixed path under the CAS dir, keyed by module name only, so
            # an arm64 sweep and an x86-64 sweep overwrite each other's copy
            # (formal/imports.py's build_module_dylib picks no per-arch name).
            # Publishing here would let a stale `ok` survive a dylib being
            # replaced by one of the wrong architecture — a false PASS, the one
            # outcome worse than being wrong in the other direction. So these
            # files are rebuilt every run instead, and the accounting line says
            # so rather than leaving a reader to wonder what "not cached"
            # means. This NARROWS what is cached; it caches nothing new.
            _bump_dylib_linked()
            return verdict(ok, detail, None, False)
        cas.publish(key, ".result", _verdict_bytes(ok, detail))
        return verdict(ok, detail, None, True)
    except subprocess.TimeoutExpired:
        # Deliberately not published (see the docstring): it is a property of
        # this machine's load, and caching it would pin the file here until
        # the key changed. It is a named class, not a silent skip, so a
        # too-small -t shows up in the report instead of shrinking coverage.
        return verdict(False, _timeout_detail(timeout, population),
                       CAUSE_TIMEOUT, False)
    except Exception as e:
        # An exception in the sweep or the build driver is not a verdict about
        # the file, so it is CAUSE_TOOL_ERROR and lands in `tool`, not in the
        # codegen count.
        return verdict(False, str(e)[:200], CAUSE_TOOL_ERROR, False)


# ── Verdict history ──────────────────────────────────────────────────────────
# A ledger of path -> class, published once per complete run. Its only job is
# to make a change of CLASS impossible to perform silently: if a rule change
# turns 170 reported failures into a differently-named bucket, the next run
# says so, by count and by file, instead of the reader inferring it from a
# percentage that moved.
#
# Deliberately NOT keyed on _criteria_id(). The ledger is not a build artifact
# — it is a record of what the last run REPORTED — and the run whose history
# matters most is the first one after the rules change, which is exactly the
# run whose _criteria_id() differs from every earlier run's. Keying it that way
# would guarantee the ledger is empty exactly when it is needed. So the key is
# the architecture and the file list: stable across rule changes, distinct per
# arch, and it moves when the scope moves (so a narrowed sweep does not diff
# itself against a wider one).
LEDGER_EXT = ".ledger"
LEDGER_PARTIAL_EXT = ".ledger.partial"
LEDGER_MAGIC = b"formal-sweep-ledger-v1"


def ledger_key(arch: str, files) -> str:
    return cas.hash_parts(LEDGER_MAGIC, arch.encode("utf-8"), *sorted(
        rel(f).encode("utf-8", "replace") for f in files))


def load_ledger(arch: str, files):
    """The previous run's ledger for this arch+scope, or None."""
    path = cas.lookup(ledger_key(arch, files), LEDGER_EXT)
    if path is None:
        return None
    try:
        with open(path, "rb") as f:
            data = json.loads(f.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("verdicts"), dict):
        return None
    return data


def publish_ledger(arch: str, files, verdicts: dict, partial=False) -> None:
    """Record this run's path -> class, for the next run to diff against.

    `partial=True` writes a DIFFERENT extension, and that is the whole design of
    the interrupted case rather than a detail of it. A partial run classified
    some files and never reached others, so a class "change" against it is
    mostly the arithmetic of what was not run — diffing a complete run against
    one would report hundreds of files as having moved when nothing about them
    changed. Writing it under its own extension means load_ledger (which looks
    for the complete one) cannot see it at all, so the next run's report_history
    is a diff against the last COMPLETE run and says so, and a reader who wants
    the partial record goes and reads the partial file, which is named for what
    it is.
    """
    body = json.dumps(
        {"arch": arch, "total": len(verdicts), "partial": bool(partial),
         "when": datetime.datetime.now().isoformat(timespec="seconds"),
         "verdicts": verdicts},
        sort_keys=True).encode("utf-8")
    cas.publish(ledger_key(arch, files),
                LEDGER_PARTIAL_EXT if partial else LEDGER_EXT, body)


def report_history(prev, verdicts: dict) -> None:
    """Print how every verdict moved since the last run of this arch+scope.

    Both directions are accounted for: a file that gained a class as well as
    one that lost it. Without the second direction this is exactly the check
    that would let a rule change quietly promote a real failure to `pass`.
    """
    if not prev:
        print("verdict history: none for this arch+scope (first classified "
              "run — nothing to compare against)")
        return
    old = prev.get("verdicts", {})
    moved, added, gone, same = {}, [], [], 0
    for path, cls in verdicts.items():
        before = old.get(path)
        if before is None:
            added.append(path)
        elif before != cls:
            moved.setdefault((before, cls), []).append(path)
        else:
            same += 1
    gone = sorted(set(old) - set(verdicts))
    print(f"verdict history: previous report {prev.get('when', '?')} "
          f"[{prev.get('arch', '?')}], {prev.get('total', len(old))} files")
    for (before, after), paths in sorted(moved.items()):
        print(f"  {before} -> {after}: {len(paths)}")
    print(f"  unchanged: {same}")
    if added:
        print(f"  not in the previous report (new/renamed file): {len(added)}")
    if gone:
        print(f"  in the previous report, not swept this time: {len(gone)}")


# What each class means, in the summary. Long on purpose: the class names are
# the tool's contract with a reader who has not read this file, and a bare
# count of 170 files called `not-answerable/host-import` is only honest if the
# report also says what that is.
CLASS_BLURB = {
    CLASS_PASS: "built, and every symbol it binds is in a library on its own "
                "link line of the image's own architecture — checked by "
                "loading that library where this host can, and by reading its "
                "export trie (what dyld resolves against) where it cannot; the "
                "summary below counts the ones read rather than loaded",
    CLASS_ADMITTED: "built, and it ALSO rests on declared assumptions about a "
                    "host this image does not have -- a second process, a "
                    "thread, a dynamic loader for foreign code -- each named in "
                    "its own `trust:` line and counted as a `sorry` in its "
                    "proof. In the denominator, NOT in the numerator: a pass is a "
                    "claim this backend made on its own",
    CLASS_CODEGEN: "THE FINDING: the backend refused a construct IN THIS FILE",
    CLASS_CODEGEN_DEP: "the backend refused a construct in a module this file "
                       "imports, so this file did not build either — a failure "
                       "in the denominator, NOT a gap in this file",
    CLASS_HOST: "imports a CPython host module that has no Mojo source: a fact "
                "about the TARGET, not a gap in the backend — and NOT all of it "
                "permanent; the reach line below splits the work from the "
                "impossible",
    CLASS_UNRESOLVED: "imports a module that is neither host nor in this "
                      "backend's module set (reason not provable from the file)",
    CLASS_EXTERN: "builds, but no library on its link line provides a symbol it "
                  "binds (the printed line names the library and why)",
    CLASS_SYSCALL: "CALLS into a host module that has no Mojo source on any "
                   "path: a fact about the TARGET, not a construct the backend "
                   "failed to lower — its own class because the fallback would "
                   "have counted it as a gap in the backend",
    CLASS_TARGET: "calls a gimple-runtime `mojo_*` entry point that a formal "
                  "image cannot bind — because a type crossing the boundary is "
                  "not one 64-bit word, or because the per-architecture "
                  "`mojo_*` library on this image's link line does not export "
                  "the name (it carries the core runtime, the coroutine runtime "
                  "and the async scheduler; the optional sqlite3/zlib/ssl/"
                  "ncurses units are not in it). Either way a limit of the "
                  "TARGET, not a gap in the backend — the printed line names "
                  "the call and which of the two it is",
    CLASS_CRASH: "the backend RAISED rather than refusing: a bug in the "
                 "compiler, in no rate, exit 1 — never cached, so it re-runs",
    CLASS_UNKNOWN: "a build message this tool does not recognise — the "
                   "classifier needs updating, not the backend",
    CLASS_TOOL: "no verdict reached, and therefore NO CLAIM either WAY about the "
            "file: the build timed out (its answer is unknown at that -t, not "
            "absent), blew this tool's per-file memory ceiling, its wrapper "
            "died before reporting, was unreadable, or the sweep or build "
            "driver raised. The summary splits this bucket by cause, with each "
            "cause's share of the scope and what answers it",
}


# ── Running the pool, and surviving not finishing it ──────────────────────────
def _stream_results(files, jobs, timeouts, flags, mem_gb, results) -> bool:
    """Classify every file, printing each as it lands. True if interrupted.

    `timeouts` is a `Timeouts`, not a number: each file's bound is looked up in
    the population that file belongs to, in the worker that is about to build
    it, so no caller has to know which population a file is in.

    Prints, does not returns, because the printing is the point: an interrupted
    run has to leave the files it classified on the output, and the only way to
    guarantee that is to write them down at the moment they are known rather than
    reconstructing them from a dict afterwards.

    A signal handler rather than only a `try`, because the two interruptions are
    not the same event. SIGINT/SIGTERM is a person or a watchdog asking the run
    to stop, and the handler turns it into a clean drain: the files that had NOT
    started building are cancelled, the `-j` builds already in flight are waited
    for and their verdicts recorded and printed, and the exit status says the
    run was cut short. A SIGKILL cannot be caught at all — that is why the
    per-file ceiling above exists, to make sure the only thing a SIGKILL can
    take is the tool's OWN process and not a build that had already been
    classified and thrown away.

    What the drain does is chosen, not incidental, and it is the opposite of what
    this used to do. Every file is submitted up front, so the executor's queue is
    the WHOLE run; a plain `return` left the `with` block, whose `__exit__` calls
    `shutdown(wait=True)` with `cancel_futures=False`, so each worker kept
    pulling the next queued file until it reached the sentinel `shutdown` appends
    — a stopped sweep built every file it had been told to stop building, which
    is what `ps` showed ten minutes after the signal (children younger than it,
    each with almost no CPU). Cancelling the queue alone is not enough either,
    because a worker that returns from one file picks up the next immediately
    while the main thread is still waiting to hear that it should stop, so
    `build` refuses to START a file once the flag is set. It is also why the
    numbers had to be reconstructed from the CAS: `run_one` publishes before it
    returns, so those builds wrote verdicts that `results` never heard about.
    Hence the collection of what was in flight — that is what makes the log and
    the cache agree again. What remains is the delay the builds in flight cost
    (bounded by one `-t`), which is the honest price of not throwing away a build
    that may be seconds from a verdict AND of not losing its published verdict.
    """
    stop = threading.Event()

    def _on_signal(signum, _frame):
        # Signal handlers must not do work; set the flag and let the loop notice.
        # A second signal is left to the default disposition so an operator who
        # wants out NOW gets out, rather than being held by a handler that is
        # only going to drain politely.
        if stop.is_set():
            signal.signal(signum, signal.SIG_DFL)
            os.kill(os.getpid(), signum)
            return
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _on_signal)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as ex:
            def build(path):
                """One file's build, unless the run was told to stop first.

                The check is HERE, at the one place a build is launched, and not
                only in the reporting loop, because the loop's own cancellation
                cannot be prompt enough on its own: a worker that returns from
                one file picks up the next one immediately, and the main thread
                only learns that it should stop when a verdict arrives. Without
                this, a signal landing mid-build still buys one more file per
                worker — measured as "thirteen children ten minutes after the
                signal" on the b6 sweep. `None` means not reached, which the
                caller records as nothing at all rather than as a verdict.
                """
                if stop.is_set():
                    return None
                return run_one(path, timeouts.for_file(path), flags, mem_gb,
                               timeouts.population(path))

            futs = {ex.submit(build, p): p for p in files}

            def collect(fut):
                """One build's verdict: recorded in `results` and printed.

                One function for the streaming loop and for the drain below, so
                a verdict that arrives during the drain is reported exactly like
                one that arrived during the run — `run_one` published both to the
                CAS, and a run whose log and cache disagree is the state this
                whole function exists to prevent.
                """
                path = futs[fut]
                if fut.cancelled():
                    # Never built, so there is nothing to record. Reaching here
                    # means the queue was drained after a stop, which is the
                    # queue being thrown away rather than walked.
                    return None
                try:
                    v = fut.result()
                except Exception as e:
                    # run_one catches its own failures; this is the belt to that
                    # braces, and a whole sweep must not die because one future
                    # did. It is reported as `tool`, never as a verdict.
                    v = Verdict(False, f"sweep worker raised: {e}"[:200],
                                CAUSE_TOOL_ERROR, False, CLASS_TOOL,
                                CAUSE_TOOL_ERROR)
                if v is None:
                    # The build declined to start because the run was stopped;
                    # nothing is claimed about this file, which is what
                    # _report_partial's "not reached" has to mean.
                    return None
                results[path] = v
                if v.cls != CLASS_PASS:
                    # `v.detail or v.reason`, because a class whose diagnosis is
                    # not a build MESSAGE has an empty detail: `built-with-
                    # admitted-contracts` is decided from the file's import
                    # closure rather than from anything the build said, so
                    # printing only the detail would print a line with nothing
                    # in it for every admitted file.
                    print(f"{v.cls.upper()}: {rel(path)}  "
                          f"({v.detail or v.reason})", flush=True)
                return v

            for fut in concurrent.futures.as_completed(futs):
                collect(fut)
                if stop.is_set():
                    # Stop BUILDING the rest of the scope, then keep what was
                    # already running. Both halves are needed: the queue is the
                    # whole run, so cancelling it is what makes a stopped sweep
                    # stop, and collecting the in-flight builds is what keeps the
                    # partial ledger and the CAS from disagreeing about how far
                    # the run got.
                    ex.shutdown(wait=False, cancel_futures=True)
                    _drain_in_flight(futs, collect)
                    return True
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, signal.SIG_DFL)
    return False


def _drain_in_flight(futs, collect) -> None:
    """Record the builds that were ALREADY RUNNING when the run was stopped.

    Called after `shutdown(cancel_futures=True)`, so every future that had not
    started is already cancelled and this only ever waits on the `-j` builds the
    pool had taken. Each of those publishes its verdict to the CAS before
    `run_one` returns, so a drain that ignored them would leave verdicts in the
    cache that the run's own output never mentions — which is what forced
    `bugs/FORMAL_sweep_work_map_2026-10-02_b6.md` §2.3 to reconstruct a run's
    numbers from the cache instead of reading its log.

    Waited for rather than killed, and the cost is bounded: each in-flight build
    has its own `-t` already running, so the drain costs at most one more `-t`.
    That is the price of not discarding a build that may be seconds from a
    verdict, and of not losing the verdict it is about to publish.
    """
    running = [f for f in futs if not f.done() and not f.cancelled()]
    if not running:
        return
    concurrent.futures.wait(running)
    for fut in running:
        collect(fut)


def _report_tool_causes(done, results, timeouts, mem_gb, arch, emit,
                        indent="  "):
    """The `tool` bucket, one line per CAUSE, each with its share of the scope.

    The bucket is "no verdict was reached", and lumping it into one sentence is
    what made it read as a verdict: it hid a real backend crash
    (`AttributeError: 'str' object has no attribute 'name'`, the same defect
    `test_dataclasses_formal.py` was failing on) that never appeared in the
    ledger at all, because its file hit the default `-t 30` first and the tool
    said "21 files got no verdict" about it in the same breath as the files that
    genuinely have none. A `tool` row is a file this run says NOTHING about; the
    cause says what stopped the answer, and the causes want opposite responses
    (raise `-t`, write the module, look at the machine, look at the file).

    So each line carries three things the reader cannot otherwise get: the count
    by cause, that count as a FRACTION OF THE CLASSIFIED SCOPE (a `tool` row
    read as "not a finding" is a very different claim over 3 files than over
    300), and what the file's answer therefore is. `timeout` gets the command
    that answers it, because it is the one cause a reader can do something about
    immediately.

    Shared by the complete run's summary and by an interrupted run's, because
    they answer the same question and a second copy is a second wording for a
    reader to be told two things by. The fraction is over the files this run
    CLASSIFIED, because that is the denominator every count above it is over; an
    interrupted run has already said how much of the scope it never reached.

    Counted from `results` by CAUSE, never by matching the detail text: the
    cause is a field the classifier set, and re-deriving it from the message it
    formatted would be the second implementation of the same question.

    The timeout row is the one that is SPLIT BY POPULATION, because it is the
    one cause whose answer is a number and the two populations do not want the
    same one: measured on one tree, a 135-line repo file passes inside 30 s
    while a 185-line one crashes inside 600 s and a 5 645-line one is still
    running at 5 400 s, and all three live in the same run under one `-t`. One
    retry command over both populations would either spend the big bound on the
    stdlib or hide the repo files' cost, so each population gets the command
    that raises ITS OWN bound and leaves the other where it was.
    """
    by_cause = collections.Counter(results[p].cause for p in done
                                   if results[p].cls == CLASS_TOOL)
    if not by_cause:
        return False
    scope = len(done)
    emit(f"{indent}note: {sum(by_cause.values())} of the {scope} classified "
         f"file(s) ({_pct(sum(by_cause.values()), scope)}) got no verdict at all "
         f"and are in NO rate. Each one is a file this run says NOTHING about, "
         f"which is not the same as a file it has cleared:")
    for cause in (CAUSE_TIMEOUT, CAUSE_MEMORY, CAUSE_WRAPPER_DIED,
                  CAUSE_UNREADABLE, CAUSE_TOOL_ERROR):
        n = by_cause.get(cause, 0)
        if not n:
            continue
        emit(f"{indent}  {cause:<22} {n:>4} file(s) "
             f"({_pct(n, scope)} of the classified scope) — "
             f"{_CAUSE_BLURB[cause].format(mem_gb=f'{mem_gb:g}')}")
    if by_cause.get(CAUSE_TIMEOUT):
        # Grouped by population, in POPULATIONS order rather than arrival order,
        # so two runs of the same sweep print the same lines in the same places
        # and a reader diffing them is not reading a reordering as a change.
        by_pop = collections.defaultdict(list)
        for p in done:
            if results[p].cause == CAUSE_TIMEOUT:
                by_pop[timeouts.population(p)].append(rel(p))
        for pop in POPULATIONS:
            timed_out = by_pop.get(pop) or []
            if not timed_out:
                continue
            paths = " ".join(timed_out) if len(timed_out) <= 8 else ""
            cmd = _RETRY_CMD.format(arch=arch, timeout=timeouts.retry_arg(pop),
                                    paths=paths)
            emit(f"{indent}  re-answer the {len(timed_out)} {pop} file(s) with "
                 f"a larger -t: {cmd}"
                 + ("" if paths else "  [the paths are the `timeout` rows "
                                     "above]"))
    return True


def _pct(n, total):
    return f"{100.0 * n / total:.1f}%" if total else "n/a"


# What each `tool` cause means for the file it is on. One sentence each, and
# each says what the run does NOT know — which is the whole point of the split.
_CAUSE_BLURB = {
    CAUSE_TIMEOUT:
        "the build did not finish inside its population's -t — the bound is PER "
        "POPULATION, because a repo-root file's build is the sum of its import "
        "closure's and a stdlib module's is its own — so what it WOULD have "
        "answered is unknown at that bound. A file that turns out to crash says "
        "so in `backend-crash` instead, and that is never cached, so it "
        "re-measures every run; a file that is merely slow to build is the "
        "other reading",
    CAUSE_MEMORY:
        "killed at this tool's {mem_gb} GB per-file ceiling — a real cost "
        "finding about that file (see bugs/PERF_memory_over_4gb_is_a_bug.md), "
        "NOT something a wider run fixes, and not cached, so re-running "
        "re-measures it",
    CAUSE_WRAPPER_DIED:
        "this tool's per-file memory wrapper died before it reported an "
        "outcome, so no peak was ever measured against the ceiling and this is "
        "not a memory finding — a fact about the machine, not cached, "
        "re-measured by re-running",
    CAUSE_UNREADABLE:
        "the file could not be read, so nothing about it was asked",
    CAUSE_TOOL_ERROR:
        "this tool or the build driver raised, so the run lost the answer it "
        "would otherwise have had",
}

# `{timeout}` is the WHOLE `-t` argument, not a number: `Timeouts.retry_arg`
# decides between the bare spelling (one bound for both populations) and
# `-t <pop>=<seconds>`, and putting that decision here would be a second place
# that has to know it.
_RETRY_CMD = ("python3 tools/formal_sweep.py --arch {arch} {timeout} "
              "{paths}")


def _report_partial(arch, files, results, timeouts=None, mem_gb=0.0) -> None:
    """Say what an interrupted run managed to classify, and publish it.

    The counts are over the files that were classified, NOT over `files`, and
    the two are printed as separate numbers on purpose. A partial run that
    reported "623 files: PASS=113" would be claiming a denominator it does not
    have; the honest form is "113 of 623 classified" with the tally over the
    113. A reader comparing the two numbers can see exactly how much of the sweep
    the interruption cost, which is the fact that makes a partial run worth
    reading at all.
    """
    done = [p for p in files if p in results]
    counts = {}
    for p in done:
        counts[results[p].cls] = counts.get(results[p].cls, 0) + 1
    print("", file=sys.stderr)
    print(f"[{arch}] INTERRUPTED: {len(done)} of {len(files)} files "
          f"classified; the rest were not reached and nothing is claimed about "
          f"them", file=sys.stderr)
    for cls in CLASS_ORDER:
        if counts.get(cls):
            print(f"    {cls:<28} {counts[cls]:>4}", file=sys.stderr)
    _report_tool_causes(done, results, timeouts or Timeouts(), mem_gb, arch,
                        emit=lambda s: print(s, file=sys.stderr))
    sys.stderr.flush()
    # Publish the partial ledger under a key that says PARTIAL, so it can never
    # be read as a complete run's history by the next one. Same shape, so
    # load_ledger finds it and report_history can still say what moved; the
    # `partial` flag is what a reader (and report_history) check before
    # treating a class change as a fact about the tree.
    try:
        publish_ledger(arch, files, {rel(p): results[p].cls for p in done},
                       partial=True)
    except Exception as e:            # noqa: BLE001
        print(f"  (could not publish the partial ledger: {e})", file=sys.stderr)


# ── One sweep per architecture ───────────────────────────────────────────────
# Keyed by ARCH, not by scope and not by the file list, and both exclusions are
# deliberate. Not by scope: a narrowed sweep (`-j6 <20 paths>` while bisecting)
# and a full one write the same dylibs and the same ledger, so a scope key would
# let exactly the pair that collides run together. Not by the file list: the
# dylib a sweep writes depends on the module a file IMPORTS, so two disjoint
# file lists still meet in the middle (and the owner's own two-at-once run was
# an arm64 and an x86-64 sweep, which this key correctly allows).
#
# The lock is `flock`, like formal/imports.py's `_dylib_lock` and for the same
# two reasons: advisory, and released by the kernel when the holder dies, so a
# killed sweep cannot wedge the next one. It is a LOCKFILE, so a second sweep
# can say which pid holds it instead of only that it is busy.
def sweep_lock_path(arch: str) -> str:
    return os.path.join(cas.CAS_DIR, f"formal-sweep-{arch}.lock")


# The held lock fd. Module-level and never closed, on purpose: the lock is held
# for the life of the process, and there is no code path that should release it
# early (releasing it would let a second sweep start while this one is still
# writing dylibs). Naming it here rather than returning it from _claim_arch says
# "this is held forever" instead of "the caller must remember to keep this".
_HELD_LOCK = None


def _claim_arch(arch: str, files) -> bool:
    """Take this architecture's sweep lock, or return False if it is held.

    Like formal/imports.py's `_dylib_lock`: `flock` is advisory and
    per-open-file-description, so the kernel releases it when the holder dies and
    a killed sweep cannot wedge the next one. A lockFILE rather than the ledger
    itself, because the ledger is replaced (so a second process would acquire a
    lock on a file the first is about to unlink) and because a reader can then be
    told which pid holds it.
    """
    import fcntl

    global _HELD_LOCK
    os.makedirs(cas.CAS_DIR, exist_ok=True)
    fd = os.open(sweep_lock_path(arch), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return False
    os.ftruncate(fd, 0)
    os.write(fd, ("%d\n%s\n" % (os.getpid(), " ".join(files[:3]))).encode())
    os.fsync(fd)
    _HELD_LOCK = fd
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-j", "--jobs", type=int, default=DEFAULT_JOBS,
                    help=f"parallel workers (default {DEFAULT_JOBS})")
    ap.add_argument("-t", "--timeout", action="append", metavar="SECONDS",
                    type=_timeout_arg, default=None,
                    help="per-file build timeout in seconds, PER POPULATION. "
                         "A bare `-t 90` is 90s for both; `-t repo=600` is 600s "
                         "for files under this repository and the default "
                         f"({DEFAULT_TIMEOUT}s) for stdlib files, and `-t` may "
                         "be repeated (a later value wins). The two "
                         "populations are separated because one of them needs "
                         "a different bound and the other must not pay for it: "
                         "a repository-root `.py` imports the repository's "
                         "other root `.py` files, so its build is the SUM of "
                         "its import closure's, while a stdlib module's build "
                         "is its own. A file that hits its bound is reported "
                         "in the `tool` class — counted, printed, and in no "
                         "rate — and it means THIS RUN SAYS NOTHING ABOUT "
                         "THAT FILE, never that the file is not a finding: a "
                         "build that would have CRASHED inside the bound is "
                         "reported in `backend-crash` instead, and the "
                         "summary's `tool` block names the timeout files, "
                         "which population each is in, and the command that "
                         "answers it")
    ap.add_argument("--arch", default="arm64",
                    choices=("arm64", "x86_64", "x86-64", "amd64"),
                    help="machine subset to sweep (default arm64; the "
                         "x86-64 spellings are accepted as aliases)")
    ap.add_argument("--stdlib", default=None, metavar="PATH",
                    help="stdlib root to sweep (default: discovered via "
                         "module_loader, i.e. MOJO_STDLIB or the known "
                         "checkout)")
    ap.add_argument("--stdlib-subtrees", default=None, metavar="A,B,C",
                    help="stdlib subtrees to sweep by default "
                         f"(default: {','.join(DEFAULT_STDLIB_SUBTREES)}; "
                         "use 'all' for every subtree under the stdlib root, "
                         "or pass paths positionally to choose exactly)")
    ap.add_argument("--no-stdlib", action="store_true",
                    help="sweep this repo only (the pre-stdlib default)")
    ap.add_argument("-M", "--mem-gb", type=float, default=MEMCAP_GB,
                    metavar="GB",
                    help="per-file memory ceiling for ONE file's build, in GB "
                         f"(default {MEMCAP_GB:g}; 0 disables it). A file that "
                         "exceeds it is killed, classified in `tool` as "
                         f"'{CAUSE_MEMORY}' with the measured peak, and the "
                         "sweep CONTINUES — one file's build cannot take the "
                         "run down with it. Not cached: a memory kill is a "
                         "property of this run's ceiling, not of the source. "
                         "If the wrapper itself is killed, the file is "
                         f"classified '{CAUSE_WRAPPER_DIED}' — also `tool`, and "
                         "also not cached, because it too is a fact about this "
                         "run's machine rather than about the source")
    ap.add_argument("--allow-concurrent", action="store_true",
                    help="sweep even if another sweep of the SAME architecture "
                         "is running. They share the formal module-dylib "
                         "directory and the ledger, and a manifest there is "
                         "rewritten in place, so a reader in one can see the "
                         "other's half-written JSON. Different architectures "
                         "are independent and never need this")
    ap.add_argument("paths", nargs="*",
                    help="files or dirs (default: this repo plus the stdlib's "
                         f"{','.join(DEFAULT_STDLIB_SUBTREES)}/ — the roots "
                         "are printed before the sweep starts)")
    args = ap.parse_args()
    arch = "x86_64" if args.arch in ("x86-64", "amd64") else args.arch
    flags = build_flags(arch)
    # The stdlib root is discovered ONCE, here, and handed to `Timeouts`: it is
    # what decides a file's population, and a per-file rediscovery would be a
    # per-file answer that could differ from the one the report used.
    timeouts = Timeouts(merge_timeout_args(args.timeout), find_stdlib_path())

    unusable = interpreter_diagnosis()
    if unusable:
        print(unusable, file=sys.stderr)
        sys.exit(2)

    # Roots: explicit paths win outright, otherwise repo + stdlib subtrees.
    notes = []
    if args.paths:
        roots = tuple(args.paths)
    elif args.no_stdlib:
        roots, notes = default_roots(())
    else:
        subs = args.stdlib_subtrees
        if subs == "all":
            base = args.stdlib or find_stdlib_path()
            subs = None                      # None => every subtree
        elif subs:
            subs = tuple(x.strip() for x in subs.split(",") if x.strip())
        else:
            subs = DEFAULT_STDLIB_SUBTREES
        if subs is None:
            if not base:
                notes.append("stdlib not found - swept the repo only")
            else:
                roots, extra = (REPO,), []
                for name in sorted(os.listdir(base)):
                    if os.path.isdir(os.path.join(base, name)):
                        roots += (os.path.join(base, name),)
                notes += extra
        else:
            roots, notes = default_roots(subs, args.stdlib)

    # Report the scope BEFORE sweeping. A run that quietly covered 263 files
    # because a root got pruned looks exactly like a clean run in the summary,
    # and the whole point of the sweep is that the denominator is trustworthy.
    print("Sweep roots:", file=sys.stderr)
    for r in roots:
        print(f"  {r}  ({len(find_source_files([r]))} files)", file=sys.stderr)
    for note in notes:
        print(f"  note: {note}", file=sys.stderr)

    files = find_source_files(list(roots))
    if not files:
        print("no .py/.mojo files found", file=sys.stderr)
        sys.exit(2)
    print(f"Total: {len(files)} files", file=sys.stderr)

    # One sweep per architecture, at a time. Taken AFTER the scope is resolved
    # (so the message can name what the other run is sweeping) and BEFORE any
    # build starts, because a lock acquired after the first build has run has
    # already lost the race it exists to arbitrate.
    if not args.allow_concurrent:
        held = _claim_arch(arch, files)
        if not held:
            print(f"another {arch} sweep is already running on this machine "
                  f"(lock: {sweep_lock_path(arch)}). Two sweeps of the SAME "
                  f"architecture share the formal module-dylib output "
                  f"directory (~/.gmojo/cas/formal-imports/{arch}/) and the "
                  f"ledger, and a manifest there is rewritten in place, so a "
                  f"reader in one sweep can see the other's half-written "
                  f"JSON — which is what a `json.decoder.JSONDecodeError` in "
                  f"the `tool` class is. The manifests are written through "
                  f"`formal/build.py`'s `_write_json_atomic` now, so this "
                  f"message is belt to that braces (`test_formal_manifest_atomic.py`). "
                  f"Two sweeps "
                  f"of DIFFERENT architectures are independent (separate dylib "
                  f"directories, separate cache keys) and are allowed; pass "
                  f"--allow-concurrent to override this one anyway.",
                  file=sys.stderr)
            sys.exit(2)

    jobs = max(1, args.jobs)
    mem_gb = args.mem_gb
    # The ceiling is in the HEADER, not only in --help, for the same reason the
    # root list is: a run whose log does not say what bound it cannot be
    # compared with a run that had a different bound. A `tool` row saying
    # "killed at the 4 GB per-file ceiling" is only readable next to a header
    # that says the ceiling was 4 GB.
    print(f"Sweeping {len(files)} files through build --formal "
          f"[{arch}] ({jobs} workers, {timeouts.describe()} timeout, "
          + (f"{mem_gb:g} GB per-file ceiling..." if mem_gb > 0
             else "NO per-file memory ceiling...")
          + ")", file=sys.stderr)
    print("Every file is classified (pass / codegen / codegen-dependency / "
          "not-answerable / backend-crash / tool / unknown); the two codegen "
          "classes are the gaps in the backend, and only the first of them is "
          "in the file itself.", file=sys.stderr)
    print("Results are printed as each file is classified, so an interrupted "
          "run keeps what it classified (and exits 3).", file=sys.stderr)

    results = {}
    # Every file that did not pass is printed AS IT IS CLASSIFIED, not at the
    # end. That is the difference between a sweep that is interrupted and a
    # sweep that produced nothing: this loop used to fill a dict and print
    # after the pool drained, so a run killed at file 600 of 623 left an output
    # file with a header and no classifications at all — 2026-10-01's arm64
    # sweep, whose whole log was the 5-line header, because the process died
    # before the one print statement that would have named a single file.
    #
    # `flush=True` on every line matters as much as the streaming: a redirected
    # stdout is a block-buffered FILE, so without it the lines would sit in a
    # buffer and an interrupted run would lose them anyway, which is the exact
    # failure this is here to fix. Ordering is arrival order, and that is
    # DELIBERATE: the deterministic order (`files`) is still what every count,
    # the headline, the family breakdown and the ledger are computed over, so
    # the parts a reader diffs run-to-run are unchanged. Only the interleaving
    # of the per-file lines moves, and the ledger — not this list — is the
    # run-to-run diff (see LEDGER).
    if _stream_results(files, jobs, timeouts, flags, mem_gb, results):
        # An interrupted run is still a run: it publishes what it classified,
        # marked partial, so the next run's report_history has something to
        # compare against instead of calling itself the first classified run.
        # Exit 3, distinct from 1 (findings) and 2 (did not run), because "you
        # killed it" and "it found something" and "it never started" are three
        # different facts and a caller that has to tell them apart should not
        # have to read the log to do it.
        _report_partial(arch, files, results, timeouts, mem_gb)
        sys.exit(3)

    # Every file gets exactly one class, and the classes sum to the file count
    # by construction: one entry per file, one class per entry. run_one has
    # already classified (it is the only place the file's source is in hand).
    rows = []           # (rel, class, reason, detail) for non-PASS, in order
    verdicts = {}       # rel -> class, every file, for the ledger
    counts = {c: 0 for c in CLASS_ORDER}
    for path in files:  # deterministic order
        v = results[path]
        counts[v.cls] += 1
        verdicts[rel(path)] = v.cls
        if v.cls != CLASS_PASS:
            rows.append((rel(path), v.cls, v.reason, v.detail))
    total = len(files)
    passed = counts[CLASS_PASS]
    admitted = counts[CLASS_ADMITTED]
    codegen = counts[CLASS_CODEGEN]
    codegen_dep = counts[CLASS_CODEGEN_DEP]
    answerable = passed + admitted + codegen + codegen_dep

    # Every file that did not pass was already printed, one line each under its
    # class, by _stream_results as it was classified — so this block only
    # BUILDS the table the summary reads, and prints nothing per file. The
    # reason that is the right split is in _stream_results: a per-file line
    # printed after the pool drains is a per-file line an interrupted run never
    # prints.
    #
    # `detail` is printed WHOLE, deliberately, and this is the settled position
    # rather than an oversight (it was ~20 KB for a 263-field diagnostic; that
    # generator now bounds its own text and the longest line in a 280-file run
    # is under 800 bytes, with the whole report ~70 KB). `reason` is the bounded
    # one-line form, and it is what the per-class breakdown uses. Truncating
    # would hide the actionable half of a message from the one class the report
    # exists for — and it would buy nothing: the full text is in the CAS entry
    # this same run published (cas.lookup(cas.formal_build_key(...),
    # ".result")), and for a build refusal it is the build's own message.
    print(f"[{arch}] {total} files: PASS={passed} not-pass={total - passed}")
    for cls in CLASS_ORDER:
        if not counts[cls]:
            continue
        mark = "  <-" if cls == CLASS_CODEGEN else "    "
        print(f"  {mark} {cls:<28} {counts[cls]:>4}   {CLASS_BLURB[cls]}")
    print(f"  (classes sum to {sum(counts.values())} = {total} files swept)")

    # WHY each unanswerable file is unanswerable. "170 files" is a number
    # without a cause; "170 files, 60 of them because of `os`" is the fact a
    # reader can act on (and the shape of the stdlib-host dependency this repo
    # has, which no amount of backend work will change).
    for cls in (CLASS_HOST, CLASS_UNRESOLVED, CLASS_TARGET):
        if not counts[cls]:
            continue
        tally = {}
        for _r, c, reason, _d in rows:
            if c == cls:
                tally[reason] = tally.get(reason, 0) + 1
        top = ", ".join(f"{k} x{v}" for k, v in
                        sorted(tally.items(), key=lambda kv: (-kv[1], kv[0])))
        print(f"  {cls} by {'call' if cls == CLASS_TARGET else 'module'}: {top}")

    # ── Reach, the thing CLASS_HOST's blurb gets wrong ──────────────────────
    # "164 files import a host module" is a number without a cause and with a
    # cause that is half false: `os` has no Mojo source today, but a Mojo-side
    # `os` is a thing a person could write, whereas `subprocess` needs a host
    # process this target does not have. Counting them together cannot size
    # either, and the class is the sweep's largest single bucket, so the
    # distinction is worth a line of its own.
    #
    # REPORT, NOT RECLASSIFY. Nothing below changes a class, a rate or an exit
    # status, and the in-reach files stay in `not-answerable`: they are
    # unanswerable TODAY, and moving them into the denominator would improve the
    # headline with work nobody has done. The point of the line is to size the
    # work, which is the opposite of improving the number.
    in_reach, unreachable, where = _host_tiers()
    host_modules = {m for _r, c, reason, _d in rows if c == CLASS_HOST
                    for m in (reason.split(" ")[0],)}
    reach_files = [m for m in sorted(host_modules)
                   if m.split(".")[0] in in_reach]
    n_reach = sum(1 for _r, c, reason, _d in rows if c == CLASS_HOST
                  and reason.split(" ")[0].split(".")[0] in in_reach)
    if counts[CLASS_HOST]:
        src = (f"from {where}" if where else
               "from this tool's pinned mirror (formal/imports.py publishes "
               "no reach split yet)")
        print(f"  of the {counts[CLASS_HOST]} host-import file(s), {n_reach} "
              f"import a module a Mojo-side implementation could in principle "
              f"provide and {counts[CLASS_HOST] - n_reach} one that needs a "
              f"host process, an embedded interpreter or a kernel object this "
              f"image does not have [{src}]")
        if reach_files:
            print(f"    in reach, and therefore WORK rather than a permanent "
                  f"fact: {', '.join(reach_files)}")
        admitted_mods = sorted(_admitted_host_modules())
        if admitted_mods:
            # Named here because the OTHER two halves of this line went quiet
            # when these five modules got models: a file that used to be reported
            # here stopped being reported anywhere, and a reader comparing two
            # runs would see the bucket shrink with nothing to say where the
            # files went.  They are not in `host-import` (they are not refused)
            # and they are not in `in reach` (nothing is left to write), so this
            # line is the only place their absence is explained.
            print(f"    neither, and not in this count at all: "
                  f"{', '.join(admitted_mods)} now have a formal/hostmods model "
                  f"and answer under DECLARED CONTRACTS -- files importing them "
                  f"are no longer refused, and a file that builds on one is "
                  f"counted as `{CLASS_ADMITTED}`, never as a pass")
        # The two names that used to be hardcoded here, and why neither is any
        # more: they were a standing editorial claim that `os` and `sys` were
        # "most of it", which is a statement about the WORK and goes stale the
        # moment one of them is written. `sys` now has a Mojo source
        # (`formal/hostmods/sys.mojo`), so it is not in the in-reach set at
        # all, and printing a name that is no longer there would be worse than
        # printing nothing.
        # What is left is the part that is still true whatever the set holds.
        print("    None of this is close, and none of it is in the rate "
              "above: the point is to size the work, not to improve the "
              "number")

    # ── A codegen finding in a file no backend change can make build ────────
    # A construct refusal is `codegen` and that is right: the construct is in
    # the file and the backend cannot lower it. What the class does not say is
    # that the file ALSO imports a host module, so it fails on the import the
    # moment the construct is fixed — closing the finding changes nothing about
    # the file. That makes the finding real and the implication false, and the
    # difference is invisible in the class counts, so it is measured here.
    #
    # This does NOT reclassify anything. Reclassifying would drop these from the
    # answerable denominator and raise the coverage rate from a bookkeeping
    # change, which is the move that makes a coverage report worthless; the
    # honest form of the finding is "the backend gap is real, and here is how
    # much of the `codegen` bucket is real in a way anyone can act on".
    if counts[CLASS_CODEGEN]:
        blocked = 0
        for r, c, _reason, _detail in rows:
            if c != CLASS_CODEGEN:
                continue
            try:
                with open(os.path.join(REPO, r), "r", errors="replace") as f:
                    text = f.read()
            except OSError:
                continue
            if any(_source_imports(text, m.split(".")[0])
                   for m in sorted(_declared_host())):
                blocked += 1
        if blocked:
            print(f"  {blocked} of the {counts[CLASS_CODEGEN]} codegen "
                  f"finding(s) are in files that also import a host module: the "
                  f"construct is a real gap, and the file could not build even "
                  f"with it lowered. Still counted as findings — reclassifying "
                  f"them would raise the rate without anyone writing code")

    if counts[CLASS_SYSCALL]:
        print(f"  {counts[CLASS_SYSCALL]} file(s) CALL into a host module with "
              f"no Mojo source on any path — a fact about the target, kept out "
              f"of the codegen count on purpose")
    else:
        print("  no build on this tree refused a call into a system module; "
              "the rule for that class is live and unfired (see "
              "not-answerable/system-module-call)")

    # WHY each codegen finding is a finding: the family, not the file. 57 (or
    # 110) files is not a finding list, and the same four or five families
    # repeating is the actionable part — a family nobody has looked at is a
    # backend feature nobody has scoped. Derived from the stored detail rather
    # than from `reason`, which is the message itself for a direct refusal.
    for cls in (CLASS_CODEGEN, CLASS_CODEGEN_DEP):
        if not counts[cls]:
            continue
        tally = {}
        for _r, c, _reason, detail in rows:
            if c == cls:
                fam = _refusal_family(_terminal_reason(detail))
                if cls == CLASS_CODEGEN_DEP:
                    # Which module refused is half the finding: four families
                    # over fourteen modules is fourteen things somebody can go
                    # and look at, and "method call on a value x204" is not.
                    hops, terminal = _split_chain(detail)
                    fam = f"{_refuser(terminal) or hops[-1]}: {fam}"
                tally[fam] = tally.get(fam, 0) + 1
        top = ", ".join(f"{k} x{v}" for k, v in
                        sorted(tally.items(), key=lambda kv: (-kv[1], kv[0])))
        print(f"  {cls} by family: {top}")
    if codegen_dep:
        print(f"    ({codegen_dep} of these failed to build because a MODULE "
              f"THEY IMPORT was refused, not because of anything in the file "
              f"itself — the {codegen} in `codegen` are refusals in the file. "
              f"Each printed line above carries the whole chain)")

    # The headline, with its denominator stated in words so it cannot be read
    # as a pass rate over the whole sweep. `codegen` and `codegen/dependency`
    # are the classes that are a gap in the backend, so a rate over anything
    # else is measuring the host platform rather than the codegen.
    una = total - answerable
    una_parts = ", ".join(f"{counts[c]} {c.split('/')[-1]}"
                          for c in CLASS_ORDER
                          if c not in ANSWERABLE and counts[c])
    if answerable:
        pct = 100.0 * passed / answerable
        print(f"codegen coverage: {passed}/{answerable} = {pct:.1f}%")
    else:
        pct = 0.0
        print("codegen coverage: no file could be answered by this backend")
    print(f"  denominator: the {answerable} swept file(s) whose build could "
          f"have answered")
    print(f"  ({passed} pass + {admitted} built-with-admitted-contracts + "
          f"{codegen} codegen + {codegen_dep} "
          f"codegen/dependency = {answerable}), i.e. every "
          f"swept file EXCEPT the {una} in a not-answerable or tool class "
          f"[{una_parts}].")
    print("  A not-answerable file is a fact about the target, not a gap in "
          "the backend, so it neither raises nor lowers this number.")
    if admitted:
        # The line that makes the class cost something.  Without it the headline
        # would read as though admitting trust were free, and it is not: these
        # files are in the denominator and not in the numerator, so every one of
        # them LOWERS the rate rather than raising it.
        print(f"  {admitted} of those {answerable} BUILT but rest on declared "
              f"assumptions about a host this image does not have, so they are "
              f"counted here and NOT as passes. Each file's `trust:` line names "
              f"them and each is a `sorry` in its proof; a file that builds with "
              f"no such admission is a `pass` and a file that does not build at "
              f"all is not in this denominator either.")

    # CAS accounting, complete: every input file lands in exactly one bucket.
    hits, misses = cas.stats["hits"], cas.stats["misses"]
    uncached = total - hits - misses
    print(f"cas: {hits} hit / {misses} miss / {uncached} not cached "
          f"({total} files)")
    if uncached < 0:
        print("  WARNING: hits+misses exceeds the file count — the counters "
              "lost an update; treat the cache line as unreliable")
    if _DYLIB_LINKED:
        print(f"  note: {_DYLIB_LINKED} file(s) link a formal dylib and are "
              f"rebuilt every run on purpose: the dylib is not in the cache "
              f"key, so publishing their verdict could outlive the dylib it "
              f"was measured against")
    # The `tool` bucket, by cause, with each cause's share of the scope — one
    # shared reporter with an interrupted run's, because it is the same question
    # and two copies of it would be two wordings for a reader to be told two
    # things by. The old single lumped sentence ("N file(s) got no verdict at
    # all (timeout/unreadable/memory-killed/tool error) … a too-small -t is the
    # usual cause") is what let a file whose build CRASHES at 42 s read as a file
    # that is merely slow at the default `-t 30`: the crash never reached the
    # ledger and the count said nothing about which files were unknown.
    _report_tool_causes(files, results, timeouts, mem_gb, arch, print)
    foreign_arch = sum(1 for p in files
                       if results[p].cause == CAUSE_FOREIGN_ARCH)
    if foreign_arch:
        # Said in the summary, not only on the rows, because it changes what the
        # headline IS. These files are in no rate, so the rate is unchanged —
        # but a reader comparing this arch's PASS count with another host's is
        # comparing a floor with a number, and the difference is exactly this
        # many files. The honest way to say that is in the sentence a reader
        # will actually read.
        #
        # Since 2026-10-02 this is NOT the ordinary cross-arch case any more:
        # a dylib this process cannot dlopen is read from its export trie
        # instead (_exports), so a correct x86-64 image on an arm64 host gets a
        # verdict rather than this row. What remains here is a library whose
        # export table could not be READ, or a host whose own architecture
        # could not be established — a much narrower thing, and the wording says
        # which, because "this host cannot dlopen it" is no longer a reason for
        # a file to go unanswered.
        print(f"  note: {foreign_arch} file(s) built, but this "
              f"{_host_arch_name()} host could not check whether their "
              f"imports resolve. They are in `tool`, in NO rate, and NOT "
              f"cached — so the {passed} pass(es) above is a FLOOR for this "
              f"arch on this host. Each row says why (an export table this host "
              f"could not read, or a host architecture it could not "
              f"establish); re-running on a host of the image's architecture is "
              f"what turns the floor into a number. This is the instrument's "
              f"limit, not a defect in those images")
    if _STATIC_BINDS:
        # The counterpart of the note above, and it is about the PASSES rather
        # than about the files in no rate. These binds WERE answered — from the
        # same export trie dyld resolves against, read out of the file rather
        # than through a load — so they are in the pass count. What was not
        # checked for them is that the image's own dyld could load the dylib at
        # all, so the count is stated rather than left implicit in a `pass`
        # that looks exactly like one confirmed by dlopen.
        print(f"  note: {_STATIC_BINDS} bind(s) across {_STATIC_FILES} file(s) "
              f"were resolved by reading their dylib's export trie rather than "
              f"by dlopen, because dlopen loads only this process's own "
              f"architecture ({_host_arch_name()}). The trie is what dyld "
              f"resolves against, so this is the image's own answer; a host of "
              f"the image's architecture would additionally confirm the dylib "
              f"can be loaded at all")
    if counts[CLASS_CRASH]:
        print(f"  note: {counts[CLASS_CRASH]} file(s) made the BACKEND RAISE "
              f"rather than refuse a construct. A crash is a bug in the "
              f"compiler, not a limit of the language, so it is in no rate "
              f"either way — but it is a failure (this run exits 1) and no "
              f"verdict for one was cached, so it re-runs until the cause is "
              f"gone. If a sweep suddenly reports many of these, another agent "
              f"is mid-edit in formal/ and the number is an artefact")
    if counts[CLASS_UNKNOWN]:
        print(f"  note: {counts[CLASS_UNKNOWN]} verdict(s) this tool cannot "
              f"classify; they are excluded from every rate rather than "
              f"guessed into one, and the run is not clean")

    # Verdict history, then the record of this run.
    report_history(load_ledger(arch, files), verdicts)
    publish_ledger(arch, files, verdicts)

    # The class printed is the row's OWN, not the alphabetically-first dirty
    # class: with `backend-crash` in DIRTY, `sorted(DIRTY)[0]` is a crash, and
    # labelling a codegen row "first backend-crash finding" would be a lie
    # about the only line in the report that points at a file to look at.
    dirty = [row for row in rows if row[1] in DIRTY]
    if dirty:
        r, cls, reason, _d = dirty[0]
        print(f"first {cls} finding: {r}  ({reason})")
    # Exit status: the not-answerable classes are permanent facts about the
    # target and never gate the run; a codegen finding, an unclassifiable
    # verdict, or a file nobody answered for all do. See EXIT STATUS in the
    # module docstring — this is a deliberate change from "any FAIL means 1",
    # which could not tell a backend regression from `import os`.
    sys.exit(1 if dirty else 0)


if __name__ == "__main__":
    main()
