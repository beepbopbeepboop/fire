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
                                    reached at all
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
  2  the sweep did not run (no input files)

`not-answerable` never affects the exit status in either direction: it is a
permanent property of the source and the target, so failing a run over it (or
passing one because of it) would both be wrong. This is a deliberate change
from the older contract, where any FAIL at all meant exit 1 — with 170
permanent facts in the FAIL bucket that contract could not distinguish "the
backend regressed" from "this file imports os".

Verdicts are cached in the CAS (cas.formal_build_key: source bytes + the
formal backend's own sources + the interpreter + the build flags + this tool's
own bytes — see _criteria_id), so a re-run with nothing changed reads a file
per file instead of recompiling. Editing anything under formal/, the parser,
or mojo/middle/ invalidates it. The cache stores the raw build verdict; the
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

The architecture is a cache-key input, not a global: `--arch` adds
`--backend=<arch>` to the build flags, and those flags are what
cas.formal_build_key folds in, so an arm64 verdict is never served for an
x86_64 sweep (or the reverse).

Usage:
  python3 tools/formal_sweep.py [-j N] [-t SECONDS] [--arch x86_64] [paths...]
"""
import argparse
import collections
import concurrent.futures
import ctypes
import datetime
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cas
from formal import macho_linker as ML

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRE = os.path.join(REPO, "fire.py")

# Every build flag that changes the artifact, and therefore the cache key
# (cas.formal_build_key folds them in). The arch is one of them: the two
# backends lower the same AST to different code, so a verdict from one says
# nothing about the other, and folding `--backend=` in here is what keeps the
# two sweeps' verdicts in separate cache entries. The same tuple drives both
# the cache key and the argv below, so the two cannot drift apart.
def build_flags(arch: str) -> tuple:
    return ("--formal", "--no-prove", f"--backend={arch}")


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
CLASS_ORDER = (CLASS_PASS, CLASS_CODEGEN, CLASS_CODEGEN_DEP, CLASS_HOST,
               CLASS_UNRESOLVED, CLASS_EXTERN, CLASS_TARGET, CLASS_SYSCALL,
               CLASS_CRASH, CLASS_UNKNOWN, CLASS_TOOL)
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
ANSWERABLE = frozenset((CLASS_PASS, CLASS_CODEGEN, CLASS_CODEGEN_DEP))
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
# failed import. Both raise ImportBuildError with one wording for one
# condition (build.py's own comment says two messages for one cause is how a
# real failure ends up filed under the wrong heading), so these two markers
# partition that error space between them. Matching the wording rather than
# re-deriving the condition is deliberate: formal/ owns the condition, and a
# second copy of HOST_MODULES here would be a list that silently rots.
# Nothing keys off the exact template — an unrecognised shape falls into
# CLASS_UNKNOWN below rather than being guessed at.
_HOST_MARK = "host module (CPython standard library)"
_UNRESOLVED_MARK = "not a stdlib or sibling module"
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
    # The same disagreement, stated as a placement failure rather than as a
    # slot.
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
    ("MLIR attribute template", "MLIR construct"),
    ("MLIR dialect construct", "MLIR construct"),
    ("__mlir_", "MLIR construct"),
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
        unreachable = frozenset(n for n in I.HOST_MODULES
                                if I.host_module_tier(n) == 'unreachable')
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

    Two authorities, in order, and no list of our own: formal.imports's
    HOST_MODULES (the set the build itself consults, so the two agree by
    construction) and then the running interpreter's own
    sys.stdlib_module_names. The second one is not redundant: on this tree
    `__future__`, `ctypes`, `asyncio` and `concurrent.futures` are all CPython
    standard-library modules that HOST_MODULES does not list, so the build
    words those failures "not a stdlib or sibling module" and 36 of them would
    otherwise be filed as unresolved imports — implying a defect in the source
    that does not exist. Reading the interpreter's own table keeps that
    classification correct as CPython grows, with nothing to maintain here.
    """
    top = name.split(".")[0]
    try:
        from formal.imports import HOST_MODULES
        if name in HOST_MODULES or top in HOST_MODULES:
            return True
    except Exception:
        pass
    names = getattr(sys, "stdlib_module_names", None)
    return bool(names) and top in names


def _short(detail: str, limit: int = 68) -> str:
    """A one-line reason for the per-class breakdown."""
    text = " ".join(detail.split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _source_imports(source, name: str) -> bool:
    """Whether `source` really does import module `name`.

    The structural half of the import test, and the part that cannot rot: if a
    message quotes a module this file imports, then whatever the sentence says
    around it, the build refused on an IMPORT — which is never a codegen
    finding. This is what lets classify() survive a reworded import error
    without having to recognise the new wording.
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
    """
    if _SYSCALL_MARK in term:
        m = _MEMBER_RE.search(term)
        return m.group(1) if m else "a system module"
    if not source:
        return ""
    declared = _declared_host()
    try:
        from formal.imports import HOST_MODULES
    except Exception:
        return ""
    for mod, member in _MEMBER_RE.findall(term):
        if (mod in HOST_MODULES or mod.split(".")[0] in HOST_MODULES) \
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


def classify(ok: bool, detail: str, cause=None, source=None) -> tuple:
    """(class, reason) for one build outcome. Pure: no I/O, no globals read.

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
    cls, reason = _classify_terminal(terminal, source)
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


def _classify_terminal(detail: str, source=None) -> tuple:
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
        if _HOST_MARK in detail:
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
    for name in _QUOTED_NAME_RE.findall(detail):
        if _source_imports(source, name):
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
#   3. look the name up in THAT library alone — dlopen it, then dlsym.
#
# So the answer is dyld's own two-level lookup, minus dyld.
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
_MEMO: dict = {}            # (dylib path, name) -> bool, for the whole run

# The two CPU types this tool ever sees an image or a library built for, named
# so the "why" a finding prints is readable. Anything else falls back to the
# number, which is still an answer.
_CPU_NAMES = {ML.CPU_TYPE_ARM64: "arm64", ML.CPU_TYPE_X86_64: "x86_64"}


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


def _loadable_for(path: str, cputype: int) -> str:
    """"" for a library this image's dyld could load, else why not.

    dlopen is deliberately NOT the test — it is happy to load a library built
    for the other architecture, which is precisely the case dyld refuses
    ("Library not loaded: … (mach-o file, but is an incompatible architecture
    (have 'arm64', need 'x86_64'))") and precisely the case that would turn
    this probe into a false PASS. The architecture is checked first, from the
    file's own header; cpusubtype is not, because dyld accepts a mismatch
    there and matching it more strictly would invent findings.

    libSystem short-circuits to "loadable" without either check: it is answered
    from the host process (see the block comment above), and on this system
    /usr/lib/libSystem.B.dylib is a shared-cache stub with no header to read —
    so the arch test below would report every image as unloadable, which is the
    false-finding direction.
    """
    if path == _LIBSYSTEM:
        return ""                       # ordinal 1, answered from the host
    types = _macho_cputypes(path)
    if not types:
        return f"cannot read a Mach-O header at {path}"
    if cputype not in types:
        have = "/".join(sorted(_cpu_name(t) for t in types))
        return (f"{path} is built for {have}, which this "
                f"{_cpu_name(cputype)} image cannot load")
    if path in _LIBS:
        return _LIBS[path]
    try:
        _LIBS[path] = ""
        ctypes.CDLL(path)
    except OSError as e:
        _LIBS[path] = f"dyld cannot load {path} here: {e}"
    return _LIBS[path]


def _exports(path: str, name: str) -> bool:
    """Whether the library at `path` exports `name`, which is spelled bare.

    `hasattr` on a CDLL is a dlsym, and dlsym re-adds the leading underscore
    the Mach-O symbol carries — so the name the bind stream holds (bare, as
    macho_linker writes it) is exactly what dlsym wants. libSystem is the one
    exception to "the library at `path`": it is answered from the HOST process
    (see the block comment above for why that is the same library), and
    CDLL(None) searches the global namespace, which is why the lstrip is not
    optional here.
    """
    key = (path, name)
    if key not in _MEMO:
        lib = ctypes.CDLL(None) if path == _LIBSYSTEM else ctypes.CDLL(path)
        _MEMO[key] = hasattr(lib, name.lstrip("_"))
    return _MEMO[key]


def _resolvable(ordinal: int, name: str, dylibs: list, cputype: int) -> str:
    """Why dyld cannot bind `name` from dylib `ordinal`, or "" if it can.

    See the block comment above: the answer is read out of the image's own load
    commands and bind stream, and looked up in the one library dyld would use.
    "" is the only success value, so a caller cannot mistake a partial answer
    for a resolution.
    """
    if not dylibs:
        return "the image has no load commands"
    if ordinal < 1 or ordinal > len(dylibs):
        return (f"the bind names dylib ordinal {ordinal}, which the image's "
                f"{len(dylibs)} load command(s) do not define")
    path = dylibs[ordinal - 1]
    bad = _loadable_for(path, cputype)
    if bad:
        return f"{bad}; nothing in it binds"
    if not _exports(path, name):
        return f"{name} is not exported by {path}"
    return ""


# A name the image binds that no loadable library provides, and the reason —
# so the printed finding says WHICH library was consulted and what was wrong
# with it, rather than only how many names there were.
Missing = collections.namedtuple("Missing", "name why")


def _unresolved_imports(binary: bytes) -> list:
    """The names the image binds that dyld cannot bind, with the reason each.

    A name here means the image builds and then dyld refuses to load it (or
    would, at the first call to it): that is not coverage and is not a codegen
    finding, so it is reported in its own class. See the block comment above
    for what this does and does not prove.
    """
    dylibs = _load_dylib_names(binary)
    if not dylibs and binary[:4] not in _MACHO_MAGICS:
        # A real image of this project always loads libSystem, so no load
        # commands at all means the header was not readable — NOT "there is
        # nothing to bind", which would be a false pass produced by the
        # failure of the reader itself. Said out loud instead.
        return [Missing("<unreadable image>",
                        f"{len(binary)} bytes with no Mach-O header, so what "
                        f"it binds could not be read at all")]
    cputype = struct.unpack_from("<i", binary, 4)[0]
    return [Missing(name, why) for ordinal, name in _binds(binary)
            for why in [_resolvable(ordinal, name, dylibs, cputype)] if why]


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


def run_one(path, timeout, flags) -> Verdict:
    """Build one file and classify the outcome. See Verdict.

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
    backend's sources + the interpreter + BUILD_FLAGS + _criteria_id()), so a
    re-run with nothing changed is a file read per file instead of a compile.
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
    changed.
    """
    def verdict(ok, detail, cause, cached):
        cls, reason = classify(ok, detail, cause, source)
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
    key = cas.formal_build_key(source, path, flags, criteria)
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
            proc = subprocess.run(
                [sys.executable, FIRE, "build", *flags, "-o", out, path],
                capture_output=True, text=True, timeout=timeout, cwd=REPO,
            )
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
                names = sorted({m.name for m in missing})
                ok, detail = False, (
                    f"builds, but {len(missing)} import(s) dyld cannot "
                    f"resolve: {', '.join(names[:3])}"
                    + (" ..." if len(names) > 3 else "")
                    + f" [{missing[0].why}]")
            else:
                ok, detail = True, ""
        else:
            err = (proc.stderr or proc.stdout or "").strip()
            # keep the last non-empty line — that's the formal build's message
            lines = [ln for ln in err.splitlines() if ln.strip()]
            # No message at all still counts as the build's own verdict: with
            # no traceback there is no evidence of a crash, and a silent death
            # is far more often a refusal whose message went to stdout. The
            # fallback is deliberately the finding side (a codegen row: exit 1,
            # printed, in the denominator) — a crash we cannot see must not be
            # able to hide, and a false FAIL only sends someone to look.
            detail = lines[-1] if lines else f"exit {proc.returncode}"
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
        return verdict(False, f"timeout (> {timeout}s)", CAUSE_TIMEOUT, False)
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


def publish_ledger(arch: str, files, verdicts: dict) -> None:
    body = json.dumps(
        {"arch": arch, "total": len(verdicts),
         "when": datetime.datetime.now().isoformat(timespec="seconds"),
         "verdicts": verdicts},
        sort_keys=True).encode("utf-8")
    cas.publish(ledger_key(arch, files), LEDGER_EXT, body)


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
                "link line that dyld can load",
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
    CLASS_TOOL: "no verdict reached: timeout, unreadable file, or an internal "
                "exception in the sweep or build driver",
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-j", "--jobs", type=int, default=DEFAULT_JOBS,
                    help=f"parallel workers (default {DEFAULT_JOBS})")
    ap.add_argument("-t", "--timeout", type=int, default=DEFAULT_TIMEOUT,
                    help="per-file build timeout in seconds "
                         f"(default {DEFAULT_TIMEOUT}; raise it for the "
                         "much larger stdlib modules). A file that hits it is "
                         "reported in the `tool` class — counted, printed, "
                         "and in no rate — never as a pass or a finding")
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
    ap.add_argument("paths", nargs="*",
                    help="files or dirs (default: this repo plus the stdlib's "
                         f"{','.join(DEFAULT_STDLIB_SUBTREES)}/ — the roots "
                         "are printed before the sweep starts)")
    args = ap.parse_args()
    arch = "x86_64" if args.arch in ("x86-64", "amd64") else args.arch
    flags = build_flags(arch)

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

    jobs = max(1, args.jobs)
    print(f"Sweeping {len(files)} files through build --formal "
          f"[{arch}] ({jobs} workers, {args.timeout}s timeout)...",
          file=sys.stderr)
    print("Every file is classified (pass / codegen / codegen-dependency / "
          "not-answerable / backend-crash / tool / unknown); the two codegen "
          "classes are the gaps in the backend, and only the first of them is "
          "in the file itself.", file=sys.stderr)

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as ex:
        futs = {ex.submit(run_one, p, args.timeout, flags): p
                for p in files}
        for fut in concurrent.futures.as_completed(futs):
            path = futs[fut]
            try:
                results[path] = fut.result()
            except Exception as e:
                # run_one catches its own failures; this is the belt to that
                # braces, and a whole sweep must not die because one future
                # did. It is reported as `tool`, never as a verdict.
                results[path] = Verdict(
                    False, f"sweep worker raised: {e}"[:200], CAUSE_TOOL_ERROR,
                    False, CLASS_TOOL, CAUSE_TOOL_ERROR)

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
    codegen = counts[CLASS_CODEGEN]
    codegen_dep = counts[CLASS_CODEGEN_DEP]
    answerable = passed + codegen + codegen_dep

    # Every file that did not pass is still printed, one line each, under its
    # class. Nothing that used to print as `FAIL:` stops printing: a file
    # reclassified out of FAIL is still here, with the class that says where
    # it went, and report_history() below names the move in both directions.
    #
    # `detail` is printed WHOLE, deliberately, and this is the settled
    # position rather than an oversight (it was ~20 KB for a 263-field
    # diagnostic; that generator now bounds its own text and the longest line
    # in a 280-file run is under 800 bytes, with the whole report ~70 KB).
    # `reason` above is the bounded one-line form, and it is what the per-class
    # breakdown uses. Truncating here would hide the actionable half of a
    # message from the one class the report exists for — and it would buy
    # nothing: the full text is in the CAS entry this same run published
    # (cas.lookup(cas.formal_build_key(...), ".result")), and for a build
    # refusal it is the build's own message, reproducible with the `fire.py
    # build --formal` line this file prints at the top of the run.
    for r, cls, _reason, detail in rows:
        print(f"{cls.upper()}: {r}  ({detail})")

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
        print("    `os` and `sys` are most of it. None of this is close, and "
              "none of it is in the rate above: the point is to size the work, "
              "not to improve the number")

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
    print(f"  ({passed} pass + {codegen} codegen + {codegen_dep} "
          f"codegen/dependency = {answerable}), i.e. every "
          f"swept file EXCEPT the {una} in a not-answerable or tool class "
          f"[{una_parts}].")
    print("  A not-answerable file is a fact about the target, not a gap in "
          "the backend, so it neither raises nor lowers this number.")

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
    if counts[CLASS_TOOL]:
        print(f"  note: {counts[CLASS_TOOL]} file(s) got no verdict at all "
              f"(timeout/unreadable/tool error) and are in NO rate; a "
              f"too-small -t is the usual cause — this run used "
              f"-t {args.timeout}")
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
