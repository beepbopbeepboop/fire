#!/usr/bin/env python3
"""The one runner for everything this repo checks: named buckets, driver
dispatch, dependency order, and a single pass/fail count at the end.

Why this exists
---------------
`make check` and `make bootstrap` used to be two independent piles of shell:
each `check-*` target carried its own copy of the input-file list that feeds
`checked_run.py`'s cache key, and `bootstrap` was ~180 lines of `for f in ...;
do ...; done` inside a Make recipe. Three things went wrong with that, and
this file is the fix for all three:

1. **The memory ceiling was opt-in per recipe.** `tools/memcap.py` exists
   because the whole-transitive-closure self-compile has been measured at
   192 GB and had to be killed by hand; macOS will not reliably pick what to
   kill, and `ulimit`/`RLIMIT_AS` gives no usable cap. It was wired into
   exactly one target (`check-native-dumpfull`) and into nothing else — while
   `bootstrap` ran the *same class of workload* (`stage2/mojo --dump-full`,
   `gcc -fgimple` over the 40 MB closure) three more times, uncapped, in the
   one target a developer is told to run before committing. The set of things
   that need a ceiling is a fact about the workloads, not about which recipe
   somebody remembered, so it lives in one table here (`MEMCLASS` plus each
   test's `mem=` field) and `--list` prints it.
   Two rounds later the same audit found the coverage was still 8 of 73: the
   `mem` driver capped, `cmd` and `make` did not, so whether a compiler ran
   under a ceiling was decided by which driver a test happened to pick. Now
   every job is wrapped, `cmd`/`make` jobs that name no class get
   `DEFAULT_MEMCLASS`, and a spec that can reach a whole-closure compile must
   name a class (test_suite.py enforces both). A side effect worth having: the
   peak is measured for every job, because measuring it is what the wrapper
   does.

   A ceiling still is not a bound on the machine. On 2026-09-29 the
   `bootstrap-stage*-dumps` fanouts ran about thirty items at once, each
   inside its own 24 GB ceiling, until the box collapsed — thirty jobs each
   *allowed* 24 GB is 720 GB of allowance, whatever any one of them measured.
   So the ceiling is also a RESERVATION: every job takes its
   memclass out of one machine-wide budget (`tools/memslot.py`, strict FIFO)
   before it is spawned, and gives it back when it exits. That is what makes
   "18 x 24 GB" mean "four at a time", and it counts the other worktrees and
   the developer's own terminal as well as this run.

2. **Ordering and dependencies were Make's job, and Make could only see
   targets.** `stage1 -> stage2/mojo -> stage2 dumps -> transitive -> stage3
   -> verify` is a real dependency graph, with a "must not run concurrently
   with anything else" edge on it (two 55 GB jobs on one 128 GB box is a
   different test from one 55 GB job). Expressing that needs per-test
   metadata, so it is expressed as per-test metadata now, and `bootstrap` is
   an ordered bucket of named steps rather than one 180-line recipe. The Make
   targets (`stage1`, `stage2`, `verify`, `validate-all`, `bootstrap`) remain
   and now just call this, so nothing that used to work stopped working.

3. **There was no single count.** Seven `check-*` targets each printed their
   own PASS/FAIL lines, and `make check` printed a hand-written ✓ that did not
   depend on any of them. Every run now ends with one tally and one exit code.

Usage
-----
    tools/suite.py                      # the `check` bucket, -j ncpu
    tools/suite.py bootstrap            # the ordered 3-stage self-host chain
    tools/suite.py gate                 # check + every heavy CLAUDE.md gate step
    tools/suite.py check selfhost       # two buckets
    tools/suite.py gimple               # one test, by name
    tools/suite.py -j1 bootstrap        # strictly serial, output streamed live
    tools/suite.py --list               # the registry: drivers, memclasses, deps
    tools/suite.py --dry-run check      # the plan and its ordering, run nothing

`MEMLIMIT_GB` still works exactly as the Makefile documented it, and now
applies to every capped job rather than to one target:

    MEMLIMIT_GB=96 tools/suite.py gate       # raise every ceiling
    MEMLIMIT_GB=0  tools/suite.py gate       # no ceiling at all; watch it

It is also the answer to a class that no longer fits its workload: the
per-job classes are assigned from MEASURED peaks, and a run that legitimately
needs more says so with the override rather than by editing the table.

Drivers
-------
A test says what kind of thing it is and the runner works out how to launch
it, so nobody has to remember which wrapper a given test needs:

    cmd      a plain subprocess
    mem      the same, wrapped in tools/memcap.py at its memclass's ceiling
    make     `make -j<J> <target>`, for the targets whose parallelism is
             Make's own job server (the per-file A/B sweep in ab.mk)
    fanout   one `mem` job per item in a file list, scheduled individually so
             it gets real parallelism and a real per-item verdict, aggregated
             into one test result

`mem` is now only a way of SAYING the class out loud: every job is wrapped in
tools/memcap.py, at `DEFAULT_MEMCLASS` unless the test names a class, and
`MEMLIMIT_GB=0` is the single switch that turns the whole thing off. The `mem`
driver is kept because "this job's ceiling is deliberate" is worth being able
to write down, and because a test that names a class is a test whose number a
reviewer can see.

Memory classes
--------------
Two mechanisms, and the second is the one that bounds the machine.

A **ceiling** is per process tree: every job that runs a `mojoc` binary, or a
whole-closure compile standing in for one, is capped by `tools/memcap.py` at
the ceiling its `memclass` names — `tiny` 4 GB, `small` 8, `module` 24,
`program` 55, `stage` 96 (the `MEMCLASS` table says which is which). Every
class is assigned from the job's MEASURED peak (`MEASURED_PEAK_GB`, read off a
real run's log by the same wrapper that does the killing) rather than from the
shape of the workload it resembles, so a class is sized to what the job does
and not to the worst thing the runner has ever seen; a class above the 4 GB
line has to say why, in `memwhy`, and `--list` prints it.

A **reservation** is per machine, and it is not optional. A ceiling bounds one
tree and says nothing about how many may run at once, which is not a bound at
all: on 2026-09-29 about thirty compiler processes, every one of them inside
its own ceiling, collapsed the box. (This sentence used to say "30-43 GB each",
which does not reproduce; see the admission comment below for the measurement
that replaced the number and kept the shape.) So every job takes its
memclass out of ONE machine-wide budget (`tools/memslot.py`, strict FIFO,
`~/.gmojo/memslot`, `MEMSLOT_BUDGET_GB`, default 96) *before* it is spawned,
and gives it back when it exits — so "18 x 24 GB" means four at a time, and
the count includes the other worktrees and your own terminal. The classes being
measured is what makes the reservation cheap: a class that is 20x the job's
peak is not a safety margin, it is twenty other jobs that cannot run.

Exclusive tests are dispatched only when nothing else is running, and while
one is running nothing else is started. That is a statement about jobs in THIS
run racing on a shared artifact (`./mojoc`, `fire.ci`, the stdlib dylib), and
it is what makes a big job safe to leave running without anyone having to
remember not to start two at once. It is not a machine-wide claim: an
exclusive job reserves its class like any other, and a job that really needs
the machine to itself is one whose class is over half the budget, which the
ledger's arithmetic already enforces.

Disabled tests
--------------
A test can be REGISTERED AND NOT RUN. `test('x', ..., disabled='bugs/<doc>.md')` is
in `--list`, in its buckets, in the plan and in the tally, and it spawns
nothing: no process, no memory ceiling, no reservation, no wall time, no peak.
It reports as its own status, `DISABLED`, with the doc, and does not fail the
run.

It is for a known failure whose test is more expensive than its verdict is
worth — a job that measures 20.5 GB, takes the `program` class (55 of a 96 GB
machine budget) and is exclusive in the run, to be told what its own marker
already says. Its cheap sibling is `expect=`, which still RUNS the test so its
anti-rot (an expected-fail that starts passing is a FAILURE) keeps working; the
two are not combinable and the registry refuses to load if a job carries both.

The anti-rot is mechanical rather than a matter of remembering: the bug doc IS
the switch, because a fixed bug's doc is DELETED (CLAUDE.md's bug-doc policy),
so the doc disappearing is exactly the event "the bug is fixed". A disabled test
whose doc is gone stops the runner, by name, with the fix spelled out — so a fix
cannot land without re-enabling its test, and a disabled test cannot stay off
forever. A doc that never existed is a typo and fails the same way, with its
own message.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PY = sys.executable
DEFAULT_LOG = 'build/suite.log'

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import cas                                                       # noqa: E402
import memslot                                                   # noqa: E402
import procrun                                                   # noqa: E402

# ── Paths, mirroring what the Makefile used to spell out ─────────────────────
RUNTIME_SRC = 'runtime/fire_runtime.c'
RUNTIME_HDR = 'runtime/fire_runtime.h'
CORO_RUNTIME = [
    'runtime/fire_coro.c', 'runtime/fire_coro.h', 'runtime/fire_coro_ctx.h',
    'runtime/fire_coro_ctx_aarch64.S', 'runtime/fire_coro_ctx_generic.c',
    'runtime/fire_coro_gen.c', 'runtime/fire_async_sched.c',
    'runtime/test_fire_coro.c', 'runtime/test_fire_coro_ctx.c',
    'runtime/test_fire_coro_exc_stub.c',
    # test_coro_runtime.py's own remaining two subjects. They were missing
    # here, so `coro`'s checked_run cache key did not cover them: editing
    # either one replayed a recorded PASS instead of re-running it, which is
    # the same class of hole as the two unregistered generator suites.
    'runtime/test_fire_coro_gen.c', 'runtime/test_fire_async_sched.c',
    'runtime/test_fire_future.c',
]
MOJO_MAIN = 'fire.py'
PY_FILES = ['fire.py', 'fire_compiler.py', 'myinterpreter.py',
            'module_loader.py', 'fire_main.py', 'generated_dispatch.py']


# Whether the last `tracked_mojo_files()` call really enumerated git's index
# rather than falling back to a directory glob. Recorded because the two
# produce item lists that differ in exactly the way that caused the flake
# (transients included), and a log that cannot tell them apart is a log that
# cannot be used to explain one.
_MOJO_FILES_ARE_TRACKED = False


def _glob_mojo_files(root: str) -> list:
    """The pre-git enumeration, kept as the fallback. One definition, called
    from both failure paths below, so the fallback cannot drift into a third
    shape."""
    return sorted(
        [os.path.basename(p) for p in glob.glob(os.path.join(root, '*.mojo'))]
        + [os.path.relpath(p, root)
           for p in glob.glob(os.path.join(root, 'mojo', '*.mojo'))])


def tracked_mojo_files(root: str = REPO) -> list:
    """Every top-level and `mojo/`-level `*.mojo` that GIT TRACKS, sorted.

    This replaced a `glob.glob(REPO + '/*.mojo')`, and the glob was one half of
    a real flake (the other half was the writer it raced; see
    test_ab_native.py's scratch-dir handling). A glob enumerates whatever is
    *in the directory* at plan time, and this repo root is a shared, writable
    scratch surface: the `ab-native` job writes `_abt_<case>.mojo` here while
    it runs. So a plan built during that window listed one of those transients
    as a `bootstrap-stage*-dumps` item, and the job that then deleted it (its
    `finally`, or a `memcap` kill of the whole tree) failed that item with
    `Error reading ../_abt_minimal_main.mojo: [Errno 2]` — which SKIPPED the
    entire bootstrap chain behind it. Measured 2026-09-29, integrator gate
    round 6.

    `git ls-files` is the fix rather than a scratch-pattern exclusion list, for
    a reason beyond the obvious one. An exclusion list is a denylist that has
    to learn the name of every future transient, and the next one would come
    from some job that never heard of the list; "is this file tracked source?"
    is a property that holds for every item and needs no maintenance. It also
    does not hide the other way a tracked file goes missing — a worktree that
    never had it, or one deleted between the plan and the launch — which
    `Fanout.items_are_files` now reports as a named per-item FAIL, so the
    enumeration and the existence check reinforce each other rather than one
    masking the other.

    `:(top,glob)` is load-bearing, not decoration: a git pathspec matches at
    any depth by default, so a bare `*.mojo` would also pull in all 54
    `formal/examples/*.mojo` and every stdlib file, silently turning a 41-item
    sweep into a 664-item one. Sorted explicitly because the fan-out's job
    order is the plan's order, and a reproducible plan is worth more than
    git's incidental ordering.

    Falls back to the glob where git is unavailable (a source tarball, a
    vendored copy) because refusing to run would be a worse failure than the
    one being fixed — and `_MOJO_FILES_ARE_TRACKED` makes the fallback visible
    in the run log, so such a run is never mistaken for a tracked one.
    """
    global _MOJO_FILES_ARE_TRACKED
    out = subprocess.run(
        ['git', '-C', root, 'ls-files', '-z', '--',
         ':(top,glob)*.mojo', ':(top,glob)mojo/*.mojo'],
        capture_output=True, text=True)
    if out.returncode == 0:
        found = sorted(p for p in out.stdout.split('\0') if p)
        if found:
            _MOJO_FILES_ARE_TRACKED = True
            return found
        # An empty result from a SUCCESSFUL ls-files is indistinguishable from
        # a pathspec this git does not understand, and `plan_for` raises on a
        # fan-out with no items — which would read as a bug in the runner.
        # Fall through to the glob rather than fail opaquely.
    _MOJO_FILES_ARE_TRACKED = False
    return _glob_mojo_files(root)


# Every source the bootstrap stages dump: the tracked top-level `*.mojo`, the
# tracked `mojo/*.mojo` (currently none), and the core .py files.
MOJO_FILES = tracked_mojo_files()
BOOTSTRAP_INPUTS = MOJO_FILES + PY_FILES

# Codegen sources: an edit to any of these can change every generated .ci, so
# they belong in every cached check's key. This is now the only copy of the
# list the Makefile called GIMPLE_SOURCES.
GIMPLE_SOURCES = (
    ['gimple_codegen.py', 'ownership_check.py', 'ownership_destruct.py']
    + sorted(os.path.relpath(p, REPO)
             for p in glob.glob(os.path.join(REPO, 'mojo', 'middle', '*.py')))
    + sorted(os.path.relpath(p, REPO)
             for p in glob.glob(os.path.join(REPO, 'mojo', 'backend_gimple', '*.py'))))

# ── Named memory buckets ─────────────────────────────────────────────────────
# Ceilings in GB, applied to a job's whole process TREE (memcap sums the tree
# because mojoc spawns `gcc -fgimple` children, and a cap that watched only
# the parent would let the real cost hide in a child). Every test that runs a
# mojoc binary — or a whole-closure compile standing in for one — names a class
# here, including the ones whose measured peak is well under 10 GB: a cheap
# cap on a small job costs nothing, and it turns a future 2x regression into a
# RESOURCE verdict instead of a machine-destroying one.
#
# THE NUMBERS ARE CEILINGS, NOT TARGETS, and a ceiling is also a RESERVATION
# (see `reserved_gb`): a job reserves its class out of one machine-wide budget
# before it is spawned. So a class is a claim on the machine, and a class that
# is 25x the job's measured peak is not a safety margin — it is 25 other jobs
# that cannot run at the same time. That is why every job's class below is
# assigned from a MEASUREMENT (`MEASURED_PEAK_GB`) rather than from the shape
# of the workload it resembles, and why the class ladder has a rung below
# `small` at all:
#
#   tiny     4 GB. A python check, a snippet compile, or a single `--dump` of
#            one source file. The measured peaks at this end of the registry
#            are 0.2-1.5 GB (`MEASURED_PEAK_GB`), so 4 covers the largest of
#            them with 2.7x. It exists because `small` was the floor, and that
#            floor was documented for a mojoc run over the A/B corpus — the
#            one workload in the tree that turned out not to fit it (9.4 GB on
#            2026-09-29, a guaranteed RESOURCE, and a class that still had to
#            keep covering the cheap end).
#   small    8 GB. A mojoc run over a snippet-sized input, a pure-python check
#            that compiles snippet-sized programs, and the whole-closure
#            self-compile as it measures TODAY (`selfhost` 3.7 GB, `mojoc`
#            3.7 GB). It is also the class a job that names nothing gets.
#   module   24 GB. One module of the compiler's own closure compiled by a
#            compiler we did not measure here, plus the honest "we do not know
#            how much of a compiler this runs" class: `prooflib` hands the job
#            to LEAN, whose 27 MB .olean is a real typechecker's memory, and
#            `tools/ab_run_one.py` caps each per-file A/B compile at this same
#            number for the same reason.
#   program  55 GB. The measured peak of `native-dumpfull` (31.3 GB) with
#            headroom — the largest job in the registry that still completes.
#   stage    96 GB. Kept as the ceiling for a genuine whole-transitive-closure
#            self-compile plus a `gcc -fgimple` over the resulting 40 MB
#            translation unit. NO JOB IS IN THIS CLASS ANY MORE: the workloads
#            it was written for measure 1.2-3.7 GB (below), which is 26-80x
#            under it. It stays because the number is the documented ceiling
#            for that shape and MEMLIMIT_GB=96 has to mean something; it is a
#            debt, and bugs/PERF_memory_over_4gb_is_a_bug.md says so.
#
# `program` and `stage` used to be justified by "55.8 GB healthy / 192 GB
# runaway" and "the largest footprint ever observed completing a self-compile
# is ~96 GB". Those are real observations — 2026-09-25/26, days before the gate
# below — but the second is a *footprint* probe and every ceiling here is
# enforced against summed RSS, and neither has been re-measured since. The
# measurement a ceiling is actually enforced against is in `MEASURED_PEAK_GB`,
# read off the run log by the same wrapper that does the killing.
#
# Override with MEMLIMIT_GB (absolute, all classes) or MEMLIMIT_GB=0 (no cap at
# all, loudly).
MEMCLASS = {
    'tiny': 4,
    'small': 8,
    'module': 24,
    'program': 55,
    'stage': 96,
}

# The line above which a class is a DEBT rather than a ceiling. The owner's
# standard is that anything over 3-4 GB in this compiler is a bug, not a fact
# about the workload, so a job that has to be given more than this carries a
# `memwhy` naming the reason and pointing at the doc that says the class should
# not have to be that big. Enforced by test_suite.py, not by a comment: a
# comment is a promise nobody checks, and this one is the difference between a
# reservation and a wish.
MEM_DEBT_GB = 4.0
MEM_DEBT_DOC = 'bugs/PERF_memory_over_4gb_is_a_bug.md'


def needs_memwhy(spec) -> bool:
    """Must this job carry a `memwhy`?

    Two ways to be over the debt line, and neither of them is "the class table
    has a big number in it":

      * the job is MEASURED above the line, so it really does use that much
        (`native-dumpfull` at 31.3 GB), or
      * the job is given a class above `small` with nothing measured behind it
        — an unbacked claim on the machine, which is the same thing wearing a
        different hat.

    A job on `DEFAULT_MEMCLASS` is neither: the default is one documented
    decision, sized for a snippet-sized python check, taken once for the 57
    jobs that inherit it. Requiring a reason there would be requiring 57
    copies of the same sentence, and a rule that fires on almost everything is
    a rule nobody reads.
    """
    peak = measured_peak(getattr(spec, 'name', ''))
    if peak:
        return peak[0] > MEM_DEBT_GB
    return MEMCLASS[memclass_for(spec)] > MEMCLASS[DEFAULT_MEMCLASS]

# ── Measured peaks: the ratchet's input ──────────────────────────────────────
# Peak RSS in GB of a job's whole process tree, as `tools/memcap.py` measured it
# — which is the same instrument that enforces the ceiling, so these are the
# numbers the ceilings are compared against, not a `ps` reading taken after the
# fact. Read off the run log's `MEMORY:` table.
#
# `MEASURED_RUN` names the run they came from, and it is the first line of the
# table for a reason: a measurement with no run attached is a rumour, and a
# ratchet built on a rumour is how a 55 GB workload ends up capped at 4 GB. The
# next full `make gate` replaces this table wholesale, and the floor check in
# test_suite.py (a class must cover its recorded peak) is what notices if
# somebody adds a measurement and forgets to move the class.
MEASURED_RUN = ('the last green full `gate`, 2026-09-30, master 86d862f, '
                'build/suite.log\'s MEMORY: table')

# `measured`: read off that run for this job.
# `derived`:  the same command over the same inputs by the same engine, so the
#             measurement is the same measurement — `stage3`'s fanout is
#             `stage2`'s argv with a different path prefix, and a per-file
#             dump cannot cost more than the whole-closure dump of the same
#             sources. Labelled rather than silently merged, because "derived"
#             is a weaker claim and a reader is entitled to see which is which.
MEASURED_PEAK_GB = {
    'native-dumpfull':             (31.3, 'measured'),
    'ab-native':                   (20.5, 'measured'),
    'selfhost':                    (3.7,  'measured'),
    'mojoc':                       (3.7,  'measured'),
    'stdlib-syntax':               (1.5,  'measured'),
    'sqliteruntime':               (1.3,  'measured'),
    'bootstrap-stage1-transitive': (1.2,  'measured'),
    'bootstrap-stage2-cc':         (1.2,  'measured'),
    'bootstrap-stage2-dumps':      (0.5,  'measured'),   # per item
    'ptrreg':                      (0.4,  'measured'),
    'ptrreg-boxed-str':            (0.2,  'measured'),
    'runtimediff':                 (0.3,  'measured'),
    'interp-tokenizer-oracle':     (0.1,  'measured'),   # 67 texts, ~1 s
    'modcache':                    (0.3,  'measured'),
    'stdlib-dylib':                (0.2,  'measured'),
    'bootstrap-stage1-dumps':      (1.2, 'derived'),    # from stage1-transitive
    'bootstrap-stage2-transitive': (1.2, 'derived'),    # from stage1-transitive
    'bootstrap-stage3-dumps':      (0.5, 'derived'),    # from stage2-dumps
    'bootstrap-stage3-transitive': (1.2, 'derived'),    # from stage1-transitive
    # The eight formal host-module suites, measured one at a time under
    # `tools/memslot.py --gb 8` on 2026-09-30, arm64, python 3.14.7. The peak
    # is memcap's own poll of the whole process tree (`procrun.tree_rss`, the
    # shared measurement memcap enforces with) — the same instrument as every
    # row above, and the reason these are 0.04-0.21 GB rather than the 24 or 96
    # their shape ("builds a compiler, links it") would have earned.
    #
    # Recorded to two decimals because that poll has a 0.5 s sample and a whole
    # case is 4-7 s, so a tenth-of-a-GB reading is three or four samples. The
    # ladder's floor class covers 0.21 GB 19x over, so the precision is not
    # load-bearing for the class — it is here so `--list` prints a number
    # somebody measured instead of one somebody guessed.
    'formal-argparse':  (0.21, 'measured'),   # 11 images, the largest of the eight
    'formal-hashlib':   (0.10, 'measured'),   # 390 s cold, 36 s warm
    'formal-struct':    (0.08, 'measured'),
    'formal-os':        (0.06, 'measured'),
    'formal-sys':       (0.06, 'measured'),
    'formal-time':      (0.06, 'measured'),
    'formal-frame-len': (0.05, 'measured'),
    'formal-toplevel':  (0.04, 'measured'),
    # The four that arrived after that count, measured the same way the same
    # day (arm64, python 3.14.7, one at a time under `tools/memslot.py --gb 8`).
    # `formal-os-backing` is the cheapest formal suite in the tree and
    # `formal-dataclasses` the most expensive of these four, and neither is
    # close to a class boundary — which is the point of writing the number
    # down rather than inheriting a class from a resemblance.
    'formal-os-backing':   (0.06, 'measured'),
    'formal-module-attr':  (0.07, 'measured'),
    'llm-reference':       (0.07, 'measured'),   # 31 cases of pure CPython
    'formal-dataclasses':  (0.10, 'measured'),
    # Five that were registered and in NO BUCKET, so nothing ran them; each was
    # measured once, alone, the same way, before being given a class and a
    # bucket. The two at 0.01 are under what a 0.5 s poll resolves across a
    # 0.5 s job, and are written down rather than rounded up to look measured.
    'arm64-encoders':      (0.04, 'measured'),   # 15.1 s of `as` round-trips
    'cli-usage-text':      (0.04, 'measured'),   # 1.1 s
    'ownership-destruct':  (0.01, 'measured'),   # 0.5 s, 113 fixture cases
    'x86-decode':          (0.01, 'measured'),   # 0.5 s, one round-trip check
    'md2html':             (0.01, 'measured'),   # 0.5 s, 14 unittest cases
    # The ten the batch merge left unregistered, measured 2026-10-01 on this
    # tree the same way — one at a time under `tools/memslot.py --gb 8`, arm64,
    # python 3.14.7 — except that `tools/memcap.py`'s own report rounds to
    # 0.1 GB and eight of the ten are under it, so the peak here is
    # `procrun.tree_rss` polled every 50 ms instead: the same instrument memcap
    # enforces its ceiling with, at a finer interval. Two decimals for the same
    # reason the rows above carry two.
    #
    # `formal-json` is 4.5x every other one of the ten and is still `tiny`, which
    # is the number worth having written down: a class assigned from "it builds
    # images like the others" would have been a guess, and a guess here is a
    # machine-wide reservation.
    'formal-json':            (0.37, 'measured'),   # 31 s, 10 groups
    'formal-pathlib':         (0.08, 'measured'),   # 15 s, 7 groups
    'formal-target-queries':  (0.08, 'measured'),   # 5 s, 25 cases
    'formal-small-hosts':     (0.08, 'measured'),   # 5 s, 4 groups
    'formal-specialization':  (0.07, 'measured'),   # 1 s, 6 cases
    'formal-method-param-field': (0.07, 'measured'),  # 9 s, 14 cases
    'formal-external-call':   (0.08, 'measured'),   # 3 s, 29 cases
    'formal-receiver-position': (0.07, 'measured'),  # 2 s, 12 cases
    'formal-value-model':     (0.07, 'measured'),   # 9 s, 19 cases
    'formal-x86-dylib':       (0.09, 'measured'),   # 2 s, 9 cases
    # The x86-64 MACHINE MODEL against the hardware, which had never been run
    # by anything: `formal/x86_64_model_test.py` is spelled `*_test.py` and the
    # estate check's walk counted only `test_*.py`, so it was in no bucket and
    # no suite. Measured one at a time under `tools/memslot.py --gb 8` on
    # 2026-10-02, arm64 host (the job itself is x86-64 + Rosetta), ~20 min for
    # 45 sequential formal builds, 45 Rosetta runs and one `lean` `#eval!` over
    # all 180 runs. 1.4 GB is memcap's own tree poll — the instrument every
    # other row here uses — and it is 2.9x under `tiny`, which is the number
    # worth having: this is the job whose SHAPE (45 builds plus a Lean
    # interpreter run) argues for `stage`, and its measurement says `tiny`.
    'formal-x86-machine-model': (1.4, 'measured'),
    # The eleven `expect=`-marked tests that were registered and in NO BUCKET,
    # so no run ever executed them and no `expect=` anti-rot could fire on any
    # of them (that bug's doc, deleted with its fix). Same
    # instrument and the same day as the rows above: one at a time under
    # `tools/memslot.py --gb 8`, `procrun.tree_rss` polled every 50 ms, because
    # all eleven are under what memcap's own 0.1 GB report resolves.
    #
    # Every one is `tiny` by 20x or more, which is the number worth having
    # written down: each of these compiles and RUNS real programs (they are the
    # compiled-path async/await and coroutine coverage), so a class assigned
    # from what they resemble would have been `module` or `small` — a
    # machine-wide reservation of 8-24 GB for a job that peaks at 0.18.
    'async-runtime-scaffold':  (0.18, 'measured'),   # 1.0 s, 2 cases
    'mutable-async-capture':   (0.14, 'measured'),   # 2.8 s
    'taskgroup':               (0.14, 'measured'),   # 3.4 s
    'transitive-closure-capture': (0.14, 'measured'),  # 2.6 s
    'async-void-return':       (0.12, 'measured'),   # 2.5 s
    'async-with-lock-guard':   (0.12, 'measured'),   # 2.8 s
    'coro-future-await':       (0.12, 'measured'),   # 15.4 s, 17 cases
    'nested-async-generic':    (0.12, 'measured'),   # 2.8 s
    'coro-detached-async':     (0.11, 'measured'),   # 1.8 s
    'x86-containers':          (0.06, 'measured'),   # 47.6 s, 60 cases x 2 backends
    'gimple-async-runner':     (0.04, 'measured'),   # 0.6 s, 38 cases
    # …and the three that were registered, ungated, and NOT expect-marked —
    # the wider census; that doc is deleted with its fix.
    # All three measured GREEN before being given a bucket, which is the only
    # reason they are cheap to gate: a registration nobody runs cannot be
    # known to pass.
    'metalgpu':                (0.37, 'measured'),   # 117 s cold, GPU + clang
    'x86-examples':            (0.05, 'measured'),   # 33 s, every formal/examples
    'new-syntax-parse':        (0.02, 'measured'),   # 0.1 s, 87 parser cases

    # Two suites the estate check caught with no spec naming them, measured
    # 2026-10-02 the same way (one at a time under `tools/memslot.py --gb 8`,
    # arm64, python 3.14.7) before being registered rather than excused: at
    # 8.5 s and 2.8 s they are the CHEAPEST formal coverage in the tree, and
    # `formal-receiver-position`'s own 2 s is the nearest neighbour. The
    # alternative — a 39th entry in `test_suite.py`'s UNREGISTERED — would
    # have been a permanent excuse for a test that costs less than the poll
    # that measures it.
    'formal-read-before-store': (0.08, 'measured'),  # 8.5 s, 61 cases, no builds
    'formal-receiver-spelling': (0.08, 'measured'),  # 2.8 s, 3 differential cases
    # …and the third the estate check caught, on the merge of the formal5 batch
    # (2026-10-02): `test_formal_core_hostmods.py`, measured one at a time
    # under `tools/memslot.py --gb 8` before being named, like the two above.
    'formal-core-hostmods':  (0.1,  'measured'),   # 25 s, 6 groups
    # …and the two `work/formal12-hostmods-subprocess` brought in, measured the
    # same way one at a time under `tools/memslot.py --gb 8` on 2026-10-03:
    # `tempfile` 35.8 s over 7 groups and `textwrap` 15.8 s over 4, both
    # building and RUNNING a formal image per group on both architectures.
    'formal-tempfile':       (0.051, 'measured'),
    'formal-textwrap':       (0.050, 'measured'),
    # …and the census instrument from `work/formal14-proofs-breadth`, measured
    # the same way: 7.9 s, no Lean, and the largest of the three new ones at
    # 0.135 GB because 22 of its 60 items compile a formal image.
    'formal-proof-breadth-tool': (0.135, 'measured'),
    # …and the one `work/formal13-1` brought in, a pure SOURCE check over
    # `HOST_OWNED_BLOBS` and the `hostmods` it describes: 0.036 GB and 0.63 s,
    # the same cost class as the two below it and measured the same way one at a
    # time under `tools/memslot.py --gb 8`.
    'formal-blob-contract':  (0.036, 'measured'),
    # …and `test_formal_monomorph.py`, which the estate check named on
    # `work/formal15-generic-monomorph` (2026-10-03) and which is registered
    # rather than excused for the reason the three above are: it is 9 s and
    # 0.1 GB across the process tree, it is the only coverage of
    # `doc/ABI.md` §Generics on this path at all, and the alternative would
    # have been a permanent UNREGISTERED entry for a test that costs less than
    # `formal-core-hostmods`'s 25 s.
    'formal-monomorph':      (0.1,  'measured'),   # 9 s, 11 cases
    # …and the five the estate check caught on the formal6 merge (2026-10-03),
    # which is the largest it has ever named at once: the eleven branches that
    # merge brought in landed five test FILES with no registration and no
    # excuse, so `suite-self-test` went red naming exactly those five and
    # nothing else — which is the check working, and is why the receipt is here
    # rather than in a doc.
    #
    # Measured the same way as every row above (one at a time under
    # `tools/memslot.py --gb 8`, this tree, python 3.14.7), and with the same
    # instrument for the same reason: `tools/memcap.py`'s own report rounds to
    # 0.1 GB and all five are under it, so the peak is `procrun.tree_rss`
    # polled every 20 ms. `formal-shutil`'s 34.5 s is the largest wall time of
    # the five and it is still a tenth of what `formal-hashlib` costs cold, so
    # the deciding number for every one of them is the same: `tiny`, and not
    # `UNREGISTERED`.
    'formal-admitted': (0.13, 'measured'),   # 10.5 s, 10 groups + the ratchet
    'formal-fcntl':    (0.07, 'measured'),   # 7.0 s, 5 groups, 30 constants
    'formal-math':     (0.09, 'measured'),   # 18.7 s, 8 groups, 20204 isqrts
    'formal-shutil':   (0.09, 'measured'),   # 34.5 s, 9 groups
    'formal-stat':     (0.10, 'measured'),   # 10.4 s, 4 groups, 65547 modes
}

# How much room above a measured peak a class must leave. 1.5x, and the reason
# it is not 1.0x: a ceiling is also the answer to "how much can this job grow
# before it is killed", and a machine's memory use is not a constant. It is not
# 2x either, and the ladder is the reason: 2x moves exactly one job
# (`native-dumpfull`, 31.3 → 62.6 GB, the only class that covers it), and the
# whole point of the ratchet is that `stage` should have no members at all.
# A headroom that pushed work up a rung would be a smaller ratchet with more
# steps in it.
PEAK_HEADROOM = 1.5

# A class this many times the measured peak is not covering a measurement, it is
# reserving the machine for one. Reported, not fatal: some jobs have a reason to
# be over (and say so in `memwhy`), and the list is the thing that has to be
# empty for the everyday jobs.
OVER_PROVISIONED_FACTOR = 8


def class_for_peak(peak_gb: float, classes=None) -> str:
    """The smallest class whose ceiling covers `peak_gb` with headroom.

    The ratchet, as code, so the numbers in the registry are checkable against
    the rule that justifies them instead of against the intention of whoever
    typed them. Ties go to the smaller ceiling, and an unknown peak is a
    `ValueError` rather than a guess: "assign a class from a measurement" has
    no meaning for a job with no measurement, and the honest answer for those
    is `unmeasured` — keep what it has.
    """
    if peak_gb is None or peak_gb <= 0:
        raise ValueError(f'no peak to size a class from ({peak_gb!r})')
    need = peak_gb * PEAK_HEADROOM
    for name, gb in sorted((classes or MEMCLASS).items(), key=lambda kv: kv[1]):
        if gb >= need:
            return name
    raise ValueError(f'no class covers {peak_gb} GB with {PEAK_HEADROOM}x '
                     f'headroom ({need:.1f} GB needed)')

# The class a `cmd` or `make` job runs under when it names none. This is the
# structural half of the coverage: before it, "is this job capped" was a
# question about the DRIVER (`mem` capped, `cmd`/`make` did not), so the answer
# for a new job was decided by which driver it happened to pick, and a job
# that ran the compiler uncapped looked exactly like one that did not. With a
# default there is no uncapped path except `MEMLIMIT_GB=0`, which says so
# loudly, and every job's peak is measured as a side effect of being capped.
#
# `small` (8 GB), and the owner of this table asked for exactly that split: a
# `module` for a cmd job that runs a compiler, `small` for a pure-python
# check, and a per-spec override wherever the workload is bigger. It used to
# be `module` (24) for everything unnamed, which is defensible as a CEILING
# and indefensible as a RESERVATION: 57 of the 73 registered jobs name no
# class, so a 24 GB default on a 96 GB machine-wide budget admits FOUR of them
# at a time, and the everyday `check` bucket would have gone from ncpu-wide to
# 4-wide to protect jobs whose largest measured peak is 2.1 GB
# (`formal-x86-endtoend`; `silentnoop`, the largest non-formal one, is 1.6).
# A reservation is a claim on the machine, so the default has to be sized for
# what the job IS rather than for the worst thing the runner has ever seen.
#
# The alternative reading — keep it at 24 until every job has a measured peak —
# was rejected for a reason that is not only about speed: 8 GB is 2.2x the
# largest peak actually measured anywhere in this registry (`selfhost`/`mojoc`,
# 3.7 GB — see MEASURED_PEAK_GB), and the checks in test_suite.py that would
# notice a job that outgrew the class are the ones that fire when it does. So
# the guess is bounded rather than hidden, and every job's peak is recorded
# (`report`'s peak table) so the next real gate replaces the 57 rows of this
# table's absence with measurements and drops the default.
DEFAULT_MEMCLASS = 'small'


def memlimit(cls: str) -> float:
    """Ceiling in GB for a memclass, honouring the MEMLIMIT_GB override.

    A float, not an int: `MEMLIMIT_GB=0.5` is a real (if unwise) ceiling, and
    truncating it to 0 would silently turn "cap at 0.5 GB" into "no cap at
    all" — the exact opposite of what was asked for. 0 still means no cap.
    """
    if cls not in MEMCLASS:
        raise KeyError(f"unknown memclass {cls!r}; known: {sorted(MEMCLASS)}")
    override = os.environ.get('MEMLIMIT_GB', '').strip()
    if override:
        return max(0.0, float(override))
    return float(MEMCLASS[cls])


def memclass_for(spec) -> str:
    """The class a spec's memory ceiling is measured against.

    A spec that names one gets it; a `cmd`/`make` spec that does not gets
    DEFAULT_MEMCLASS. Fanouts already require a class (a fanout runs the
    compiler once per item, so there is nothing to infer), so this is the
    only place the fallback lives.
    """
    return getattr(spec, 'mem', None) or DEFAULT_MEMCLASS


# ── Admission: memory is ALLOCATED to a job before it starts ─────────────────
# A per-job ceiling bounds ONE process tree. It says nothing about how many
# trees may run at once, so on its own it is not a bound on the machine at all:
# the three `bootstrap-stage*-dumps` fanouts are 47 items each, and `-j18` of
# them at the `module` class it used to be was 18 x 24 GB = 432 GB of ALLOWED
# ceiling on a 128 GB box. That is not hypothetical — on 2026-09-29 those
# fanouts ran about thirty items at once until the machine collapsed and a
# human killed them by hand. Every individual process was inside its own cap
# the whole time, which is exactly the point: a per-process ceiling cannot be
# defeated by width unless something bounds the SUM.
#
# The per-item figure this comment used to carry — "each observed between 30
# and 43 GB" — is GONE, because it does not reproduce and never did, on either
# side of the fanout. Measured 2026-10-01 through the same instrument, one at
# a time: the compiled side is 0.5 GB per item (`MEASURED_PEAK_GB`) and the
# PYTHON side is 0.04 GB for an actual fanout item and 0.09 GB for the worst
# case on it (dumping gimple_codegen.py / fire_compiler.py / myinterpreter.py
# through `fire.py --dump`, three of them, 4-5 s each). A tree state carrying
# the self-hosting pre-pass could have been 15-30 GB per call
# (BLOW.md §0), but that is not this tree, and a number that only held on a
# tree nobody can name is not a number to leave in a file people read. What is
# NOT in doubt is the SHAPE — width defeated a per-process cap — which is why
# the reservation below exists regardless of what any one item measured.
#
# So the ceiling is also a RESERVATION, taken out of one machine-wide budget
# before the job is spawned (`tools/memslot.py`, the ledger in
# ~/.gmojo/memslot). A 55 GB job takes 55 of the 96 GB budget, so a second one
# waits instead of running beside it; a 4 GB fanout item runs 24 at a time
# rather than four. MEMSLOT_BUDGET_GB is the whole-machine number (default
# 96, memslot's own default: it leaves ~30 GB of a 128 GB box for the OS).
#
# `excl` used to be the same mechanism carried one step further: an exclusive
# job reserved the WHOLE budget rather than its class, so it held the ledger
# and nothing anywhere on the machine was admitted while it ran. That conflated
# two different claims, and the conflation cost more than it bought.
#
#   * What `excl` is FOR, in this registry, is interference between jobs in
#     ONE run: all four exclusive jobs write a shared artifact another job
#     reads or links — `./mojoc`, `fire.ci`, `build/libmojostdlib.<arch>.dylib`
#     — and two of them racing on one name is a wrong answer, not a slow one.
#     That is a scheduling statement, and `execute()` already enforces it: an
#     exclusive job drains the pool first and nothing starts until it is done.
#
#   * What the whole-budget reservation added was a claim about the whole
#     MACHINE, sized by nothing. `mojoc` was marked exclusive while measuring
#     3.7 GB (MEASURED_PEAK_GB), so a 3.7 GB job held 96 of the machine's 96
#     GB and every other job on the box — every other worktree's gate, every
#     `smoke`, the developer's own test run — waited behind it. That is the
#     reservation version of the same mistake this whole table was corrected
#     for: a class is a claim, and a claim nobody measured is a queue.
#
# So `excl` now reserves its CLASS, like every other job, and says what it
# actually says: nothing else in this run starts while it runs. The machine-wide
# property is not lost, it is arithmetic: the ledger admits no set of jobs whose
# reservations sum past the budget, and the classes are now measured, so two
# jobs that together could hurt the machine still cannot both be admitted —
# 55 + 55 > 96 for the two `program` jobs, which is the case that mattered when
# `excl` was taking the whole ledger. A job that genuinely needs the machine to
# itself is a job whose class is more than half the budget, and that is
# expressed by its class rather than by a flag on top of it.
#
# An earlier attempt at a second bound lived here as `MEMBUDGET_GB`, a
# sum-of-ceilings the runner compared before launching. It was never wired to
# anything, and even wired it would have been the wrong tool: it bounds
# concurrency inside one runner and knows nothing about the other worktrees,
# which is where a hand-run `make mojoc` lives. One machine-wide ledger, not a
# second budget that only one process honours.
def memslot_budget() -> float:
    """The machine-wide reservation budget in GB, honouring MEMSLOT_BUDGET_GB.

    Read through `memslot` rather than restated, because the ledger's own
    default is the one number that has to agree across every worktree, and two
    spellings of it is one more number to drift.
    """
    return memslot.budget_gb()


def reserved_gb(spec) -> float:
    """The gigabytes a job takes out of the machine-wide budget before it starts.

    Its memclass — the same number the ceiling keeps, because a reservation is a
    PROMISE and the promise has to be the one the ceiling keeps, in both
    directions: the scheduler never admits more than the budget, and no
    admitted job may take more than it was given.

    Not the whole budget for an `excl` job, which is the one behaviour that
    changed when the classes were assigned from measured peaks: `excl` is a
    scheduling statement (nothing else in this run starts, enforced in
    `execute`), and the machine-wide bound is the ledger's arithmetic over
    classes that are now measured. See the note above `memslot_budget`.

    0 for a job with no ceiling, too. `MEMLIMIT_GB=0` is the run-wide "no
    memory bound anywhere" switch; reserving nothing for it is the honest
    reading, and reserving a token's worth would be a queue that admits
    everything, which is the collapse with extra steps.

    And 0 for a DISABLED job, which is the whole point of the marker: it
    reserves nothing because it runs nothing. A disabled job's memclass and
    measured peak are still recorded (they are what the job will cost the day
    it is turned back on, and they are what `--list` and the peak table read),
    but a class that is only a record must not be a claim on the machine — a
    55 GB reservation for a test that will never be spawned is the exact
    failure this field exists to stop.
    """
    if is_disabled(spec):
        return 0.0
    ceiling = memlimit(memclass_for(spec))
    return 0.0 if ceiling <= 0 else ceiling


def measured_peak(name: str):
    """`(peak_gb, provenance)` for a job, or None when there is no measurement.

    None is a real answer and not a failure: 57 of the registered jobs have no
    measured peak, they keep the class they have, and `memclass_report_lines`
    lists them as unmeasured so "we do not know" is visible rather than
    indistinguishable from "we checked".
    """
    return MEASURED_PEAK_GB.get(name)


def memclass_ratios():
    """`(name, peak, how, cls, ceiling, factor, want)` for every measured job.

    `want` is what the ratchet says the class should be (`class_for_peak`), so
    a class that has drifted away from its measurement is a COMPARABLE value and
    not a judgement call in a comment: `class_mismatches` is a one-liner over
    this table, and the report prints both columns side by side.

    Sorted by the factor — how much of the class the job actually used —
    biggest first, because that column is the one a reader is looking for: a
    factor near 1 is a class sized to a measurement, and a factor in the tens
    is a reservation.
    """
    rows = []
    for name, (peak, how) in MEASURED_PEAK_GB.items():
        spec = REGISTRY.get(name)
        cls = memclass_for(spec) if spec is not None else None
        ceiling = MEMCLASS.get(cls) if cls else None
        rows.append((name, peak, how, cls, ceiling,
                     ceiling / peak if peak and ceiling else None,
                     class_for_peak(peak)))
    return sorted(rows, key=lambda r: (-(r[5] or 0), r[0]))


def class_mismatches():
    """Measured jobs whose class is not the one the ratchet assigns.

    The one thing that must be true of the whole table, and deliberately a
    function rather than a comment on each registration: a class that has
    drifted from its measurement is invisible in a run — nothing fails, the
    machine is just slower or the job is killed for no visible reason — so it
    is checked in one place, by a test, with both numbers in the message.
    """
    return [(n, c, w) for n, _p, _h, c, _g, _f, w in memclass_ratios()
            if c != w]


def is_over_provisioned(peak_gb, ceiling, floor=None) -> bool:
    """Is a class of `ceiling` GB over-provisioned for a `peak_gb` GB peak?

    The warning rule, as a function of two numbers rather than of the table, so
    it can be checked on cases whose answer is computable by hand. `floor` is
    the smallest class in the ladder, and the exception it buys is the point
    rather than a loophole: a 0.3 GB job in the 4 GB floor class is 13x its
    peak, but the ladder has nothing below it, so the alternative is not a
    smaller reservation, it is a new rung. Those are counted separately, by
    `at_floor`, so "the class is too big" and "the ladder is too coarse" are two
    different findings and only the first is a job's fault.
    """
    floor = min(MEMCLASS.values()) if floor is None else floor
    return (bool(peak_gb) and peak_gb > 0 and ceiling > floor
            and ceiling / peak_gb > OVER_PROVISIONED_FACTOR)


def over_provisioned():
    """The measured jobs whose class is more than OVER_PROVISIONED_FACTOR their peak.

    A warning list, not a failure: a job with a recorded reason in `memwhy` is
    allowed to be over-provisioned on purpose, and the everyday jobs are not.
    It is the shape a regression takes when a class is left at a historical
    number — invisible in the run, since nothing fails, and visible here.
    """
    return [(n, p, c, g / p) for n, p, _h, c, g, _f, _w in memclass_ratios()
            if is_over_provisioned(p, g)]


def at_floor():
    """The measured jobs whose class is the smallest one there is."""
    floor = min(MEMCLASS.values())
    return [(n, p, f) for n, p, _h, _c, g, f, _w in memclass_ratios()
            if g == floor]


def unmeasured_jobs():
    """Registered jobs with no recorded peak, sorted: they keep their class."""
    return sorted(n for n in REGISTRY if n not in MEASURED_PEAK_GB)


def class_shortfalls(peaks):
    """`(name, peak, class, ceiling)` for every job whose class cannot cover `peak`.

    The floor, as a function of a `{name: peak_gb}` mapping, so the same check
    runs against a run's own measurements and against the peaks in a log left
    by an earlier run. Empty is the healthy answer and is the whole point: a
    job whose class has stopped covering its workload is a job memcap kills at
    its ceiling and the runner reports as RESOURCE — a verdict that says
    nothing about the output, which is exactly why it is worth catching in a
    test first, from a number, rather than on a machine mid-gate.
    """
    out = []
    for name, peak in sorted((peaks or {}).items()):
        spec = REGISTRY.get(name.split(':')[0])
        if spec is None or peak is None:
            continue
        cls = memclass_for(spec)
        ceiling = memlimit(cls)
        if ceiling > 0 and peak > ceiling:
            out.append((name, peak, cls, ceiling))
    return out


# The per-job line `report` writes, read back. Parsed here rather than in
# test_suite.py because the format is this module's own: a second copy of it is
# a second thing to forget to update when the line changes, and a parser that
# silently matches nothing is worse than no parser.
_JOB_LINE = re.compile(r'^\[\s*\d+/\d+\]\s+\S+\s+(\S+)\s+[0-9.]+s\s+'
                        r'\(\d+ running\)(?:\s+\[([^\]]*)\])?')
_PEAK_IN_TAIL = re.compile(r'peak ([\d.]+) GB')


def peaks_from_log(path):
    """`{job key: peak_gb}` for every job a run log recorded a peak for.

    Per job, the LARGEST peak seen — a fanout's 45 items are 45 lines with the
    same test name, and the class has to cover the worst of them, not the one
    that happened to finish first. Cached replays have no peak (they start no
    process), which is why a log is not a complete record of what a job needs:
    it is a record of what the jobs that actually ran needed.
    """
    peaks = {}
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            for line in f:
                m = _JOB_LINE.match(line)
                if not m:
                    continue
                key, tail = m.group(1), m.group(2) or ''
                p = _PEAK_IN_TAIL.search(tail)
                if p:
                    peaks[key] = max(peaks.get(key, 0.0), float(p.group(1)))
    except OSError:
        return {}
    return peaks


def peak_drift(measured):
    """`(name, this run, recorded)` for jobs whose measurement has moved.

    The table is a snapshot of one run, and a snapshot goes stale silently:
    a workload that grows keeps fitting its class until it does not, and one
    that shrinks keeps reserving 20x what it needs until someone notices. Both
    directions are reported, because both are how this file becomes a lie, and
    "the number in the table is from a run, and this is a newer one" is the
    only thing that keeps it honest.
    """
    out = []
    for key, peak in sorted((measured or {}).items()):
        name = key.split(':')[0]
        recorded = MEASURED_PEAK_GB.get(name)
        if recorded is None or peak <= 0:
            continue
        old = recorded[0]
        if peak > old * (1 + PEAK_HEADROOM) or peak < old / (1 + PEAK_HEADROOM):
            out.append((name, peak, old))
    return out


def memclass_report_lines():
    """The memclass table, measured where it can be — for `--list` and the log.

    One implementation, three readers: `--list` is what a reviewer checks a new
    registration against, the run log is where a reader looks up why a job
    reserved what it reserved, and test_suite.py asserts against the same
    numbers. A table printed in one place and asserted in another is a table
    that drifts.
    """
    out = [f'measured peaks: {MEASURED_RUN}',
           f'  assigned: the smallest class covering {PEAK_HEADROOM:g}x the '
           f'measured peak; over {OVER_PROVISIONED_FACTOR}x is reported, not fatal']
    # One decimal is enough for every peak the ladder had until the formal
    # host-module suites landed, and not enough after: a 0.04 GB job printed as
    # `0.0` is indistinguishable from a row with no measurement at all, in the
    # one table whose entire job is to tell those two apart. The precision
    # follows the smallest peak in the table rather than being typed, so the
    # next sub-0.1 measurement widens it without anybody deciding to.
    places = 1 if min(p for p, _h in MEASURED_PEAK_GB.values()) >= 0.1 else 2
    for name, peak, how, cls, ceiling, factor, want in memclass_ratios():
        out.append(f'  {name:<30} {peak:6.{places}f} GB {how:<8} -> {cls:<7} '
                   f'{ceiling:>5.0f} GB  {factor:5.1f}x'
                   + ('   MISMATCH: the ratchet assigns '
                      f'{want}' if cls != want else ''))
    over = over_provisioned()
    floor_jobs = at_floor()
    unmeasured = unmeasured_jobs()
    out.append(f'  {len(over)} over-provisioned (>'
               f'{OVER_PROVISIONED_FACTOR}x, and not already at the smallest '
               f'class): '
               + (', '.join(f'{n} {f:.0f}x' for n, _p, _c, f in over) or 'none'))
    out.append(f'  {len(floor_jobs)} at the floor class '
               f'({min(MEMCLASS.values()):g} GB; the ladder has nothing smaller, '
               f'so their ratio is the ladder\'s, not their fault): '
               + ', '.join(f'{n} {f:.0f}x' for n, _p, f in floor_jobs))
    out.append(f'  {len(unmeasured)} unmeasured (keep their class): '
               + ', '.join(unmeasured))
    return out


# ── Registry ─────────────────────────────────────────────────────────────────
class Spec:
    """One named test.

    driver  'cmd' | 'mem' | 'make'
    mem     memclass name; optional, and meaningful on EVERY driver. Omitted
            means DEFAULT_MEMCLASS — see why the default exists above. A
            `mem` driver with no class is refused, because `mem` says "this
            job's ceiling is deliberate" and a deliberate nothing is a
            contradiction; a `cmd` job that inherits the default is not
            saying nothing, it is saying "like everything else".
    memwhy  one line saying why this job needs the class it names, REQUIRED
            above MEM_DEBT_GB — see the table's own comment. Not enforced at
            registration (a synthetic spec in test_suite.py should not have to
            explain itself), enforced by the estate check that reads the real
            registry, and printed by `--list` next to the number it justifies.
    deps    test names that must pass first
    extra   files whose content affects the outcome (feeds checked_run's key)
    extraglob
            shell PATTERNS naming a set of inputs, for a subject that is not
            one file and not one directory — the repo's own `test_*.py`, which
            is 93 files in one directory and the subject of the estate check.
            A hand-kept `extra` list cannot express that without rotting on the
            file the next person adds, and a key that cannot see its own
            subject replays a recorded PASS over a change nobody can see.
    cache   wrap in checked_run.py so an unchanged input replays its result
    j       forward `-j <slots>` to a command that has its own -j
    excl    nothing else in THIS RUN may start while it runs. A scheduling
            statement about shared artifacts, not a memory claim: the
            reservation is the class, like every other job's, and a job that
            really needs the machine is one whose class is over half the
            budget. See `reserved_gb`.
    reject  fail if this pattern appears in the output even on exit 0
    cwd    run in this repo-relative directory
    env     extra environment for this test's process
    expect  this test is KNOWN to fail, and here is why; it is run, and a
            verdict of FAIL/ERROR is reported as EXPECTED instead
    disabled  this test is NOT RUN AT ALL, and `bugs/<doc>.md` is the switch:
              the doc is the marker, so deleting the doc (which is what a fix
              does — see the bug-doc policy) is what turns the test back on,
              and the registry refuses to load while a disabled test's doc is
              gone. Costs nothing: no process, no reservation. The two
              markers are not combinable, and `disabled` is the one to reach
              for when running the test would cost more than its verdict is
              worth — a 20 GB, minutes-long run to learn something already
              written down. See "Disabled tests" below, and CLAUDE.md,
              "Known failures: expect= or disabled=, decided by cost".
    artifact  a binary this step produces, cached by the content of its real
              inputs (see ArtifactCache); `inputs` are the files, on top of the
              self-host closure, that its key folds in
    dep     this registration is a DEPENDENCY of other tests, not a test in
              its own right, and deliberately belongs to no bucket. It is the
              one honest way out of "every registered test is in a bucket"
              (checked in test_suite.py), and it is a per-spec opt-out rather
              than a name list in the checker for exactly that reason: a list
              in the checker is an excuse table, and an excuse table is how
              nineteen registrations came to sit in the estate's inventory and
              in no run at all. The checker refuses a `dep` that NOTHING
              depends on, and a `dep` that is in a bucket after all (the
              marker is then not saying what it is for), so it cannot become a
              way to be ungated — it can only be the statement that this is run,
              as a dependency, on purpose. `prooflib` is the one: 27 MB, ~80 s,
              sixteen jobs `deps` on it.
    """
    __slots__ = ('name', 'cmd', 'driver', 'mem', 'memwhy', 'deps', 'extra',
                 'extraglob', 'cache', 'j', 'excl', 'reject', 'timeout',
                 'cwd', 'env', 'desc', 'artifact', 'inputs', 'expect',
                 'disabled', 'dep')

    def __init__(self, name, cmd, driver='cmd', mem=None, memwhy='', deps=(),
                 extra=(), extraglob=(), cache=False, j=False, excl=False,
                 reject=None, timeout=None, cwd=None, env=None, desc='',
                 artifact=None, inputs=(), expect='', disabled='', dep=False):
        self.name, self.cmd, self.driver, self.mem = name, cmd, driver, mem
        self.deps, self.extra, self.cache = tuple(deps), tuple(extra), cache
        self.extraglob = tuple(extraglob)
        self.j, self.excl, self.reject = j, excl, reject
        self.timeout, self.cwd = timeout, cwd
        self.env, self.desc = dict(env or {}), desc
        self.artifact, self.inputs = artifact, tuple(inputs)
        self.expect = expect
        self.disabled = disabled
        self.dep = dep
        self.memwhy = memwhy
        if driver not in ('cmd', 'mem', 'make'):
            raise ValueError(f"{name}: unknown driver {driver!r}")
        if driver == 'mem' and mem is None:
            raise ValueError(f"{name}: driver 'mem' without a memclass")
        if mem is not None and mem not in MEMCLASS:
            # Eager, so a typo is a registration error rather than a job that
            # dies inside memcap with a KeyError on a class name.
            raise ValueError(f"{name}: unknown memclass {mem!r}; "
                             f"known: {sorted(MEMCLASS)}")
        if artifact and not inputs:
            raise ValueError(f"{name}: an artifact cache with no inputs is a "
                             f"cache that cannot miss")



class Fanout:
    """One named test, expanded into one job per item.

    The items are independent by construction — that is the whole reason to
    fan them out — so each gets its own process, its own memory ceiling and
    its own verdict, and the bucket reports one result for the whole set.
    Never cached: the artifact a fanout produces *is* its output, so replaying
    a cached result would leave the artifact missing.

    `items_are_files` declares that every item names a file in the repo (the
    bootstrap sweeps do; a synthetic sweep over bare strings legitimately does
    not), which is what lets `run_job` turn "the file this item is supposed to
    read is not there" into a FAIL naming that item instead of whatever the
    compiler happens to say about a path it cannot open.
    """
    __slots__ = ('name', 'cmd', 'items', 'cwd', 'env', 'mem', 'memwhy',
                 'deps', 'excl', 'reject', 'timeout', 'desc', 'expect',
                 'disabled', 'items_are_files')

    def __init__(self, name, cmd, items, cwd=None, env=None, mem=None,
                 memwhy='', deps=(), excl=False, reject=None, timeout=None,
                 desc='', expect='', disabled='', items_are_files=False):
        self.name, self.cmd = name, list(cmd)
        self.items = list(items) if not callable(items) else items
        self.cwd, self.env, self.mem = cwd, dict(env or {}), mem
        self.deps, self.excl, self.reject = tuple(deps), excl, reject
        self.timeout, self.desc = timeout, desc
        self.expect = expect
        self.disabled = disabled
        self.memwhy = memwhy
        self.items_are_files = items_are_files

        if mem is None:
            raise ValueError(f"{name}: a fanout runs the compiler per item; "
                             f"it needs a memclass")


REGISTRY: dict[str, object] = {}

# The per-job timeout for any test that does not name its own. This used to be
# None, which meant a hang was UNBOUNDED for 82 of the 91 registered tests --
# and the only hang detector those tests had was whatever budget the test file
# itself happened to pass to `subprocess`, which is the wrong owner twice over:
# too tight to survive load (test_runner.py's 10 s failed the whole gate on a
# loaded box, while the same test passed 17/17 standalone), and unlabelled when
# it fired, so a timeout was indistinguishable from a miscompile in the tally.
#
# The runner already does the right thing when a timeout IS armed: it kills the
# job and records it as a failure in its own class, tagged [TIMEOUT], because a
# job killed at its timeout has reported nothing and a run that hangs a test and
# exits 0 has silently not run the thing it was asked to run (see the note above
# `Verdict`). So this is not a new policy, it is arming an existing one for every
# job instead of nine.
#
# 3600 s is ~6x the slowest healthy test measured across the last two full gates
# (gimplerunner, 607 s; then mojoc 417 s, selfhost 408 s, gimplegenerators
# 371 s), so it cannot fire on a healthy or merely loaded run, while a genuine
# wedge is caught in an hour instead of never. Per-test `timeout=` still wins,
# and `--timeout` still overrides everything.
DEFAULT_JOB_TIMEOUT_S = 3600.0


def test(*a, **kw) -> Spec:
    s = Spec(*a, **kw)
    REGISTRY[s.name] = s
    return s


def fanout(*a, **kw) -> Fanout:
    f = Fanout(*a, **kw)
    REGISTRY[f.name] = f
    return f


# ── The everyday gate ────────────────────────────────────────────────────────
# Same membership as the old `check:` prerequisite list, kept deliberately:
# adding a test to the default gate is a decision, not a side effect of
# reorganising the runner. `gate` below is the wider one.
test('gimple', [PY, 'test_gimple.py'], cache=True,
     extra=GIMPLE_SOURCES + ['test_gimple.py'],
     desc='GIMPLE unit suite (python-interpreted codegen)')
# Registered 2026-09-26. Both `test_gimple_runner.py` and
# `test_gimple_generator_runner.py` were in NO bucket — no `make check`, no
# `make gate` ran a single case in them — for as long as they existed. That
# is not a theoretical gap: on 2026-09-26 a correct fix sat RED in
# test_gimple_runner.py for a full pass (`gimple_escaping_capturing_lambda_
# still_lifted` expected "1" where the landed fix now correctly produces
# "8", CPython's answer) because nothing executed it, and a whole wave of
# new regression tests would likewise have gone in and never run. The
# Makefile's old `check-gimple-runner` was a stray alias nothing referenced.
# Registered here as `gimplerunner`/`gimplegenerators` (below, with `runner`
# and the rest) rather than right after `gimple` — see that comment for the
# full rationale and the `extra` cache-invalidation list.
test('runner', [PY, 'test_runner.py'], cache=True, timeout=1800,
     # `exec_budget.py` is imported by the test file, so it belongs in the key:
     # without it, raising a budget replays a recorded PASS and the change never
     # runs. The runner's cache is content-addressed over exactly `extra`.
     extra=['test_runner.py', 'exec_budget.py', 'myinterpreter.py', 'fire.py',
            'fire_main.py', RUNTIME_SRC, RUNTIME_HDR],
     desc='compile-and-execute runner over a hand-written corpus')
# `timeout=1800` on `runner` and `modcache` (2026-09-30): both jobs had NO
# suite-level timeout, so `spec.timeout or opts.timeout` was None and the only
# hang detector anywhere was the test's own per-executable `subprocess` budget
# -- 10 s in test_runner.py, 20 s in test_module_cache.py. Those binaries run
# in milliseconds, so the budgets were pure slack, except under load: at -j18
# with the machine-wide memslot queue, process startup alone exceeded 10 s and
# BOTH jobs failed with a spurious `FAIL ... timed out after 10 seconds`. Both
# pass standalone (runner 17/17, modcache 83/83), so it was never a miscompile.
#
# The fix is layering, not forgiveness. The runner already treats a hang as a
# FAILURE in its own class and tags it [TIMEOUT] (see the note above Verdict);
# it just was not armed for these two. Now it is, and the inner budgets are
# raised to sit far INSIDE it (60 s / 120 s), where they can no longer fire on
# load but still stop a wedged child long before the job is killed. Nothing is
# absorbed by an `expect=` marker: a real hang is still a red run.
# `mem='tiny'` (4 GB), down from `module` (24): measured peak 0.3 GB, so the
# ratchet assigns 0.3 x 1.5 = 0.45 GB and the smallest class that covers it is
# the new floor. The reason it NAMED a class at all is unchanged and is the one
# the estate check in test_suite.py exists to catch: it looks at a test file's
# CODE and finds `fire.build_executable(...)`, which is the whole-closure
# build's entry point. Here the closures are two- and three-file toy projects,
# so the class is not about this test's size — it is the statement that the
# class was chosen from a measurement rather than inherited.
test('modcache', [PY, 'test_module_cache.py'], mem='tiny', cache=True,
     timeout=1800,
     extra=GIMPLE_SOURCES + ['test_module_cache.py', 'exec_budget.py',
                             'myinterpreter.py', 'fire.py', 'fire_main.py'],
     desc='module cache end-to-end stages')
# Registered 2026-09-27. Found while implementing FORMAL.md phase 0:
# `reflect._PROTO_RE` could not match a pointer return (`char *name(...)` — the
# `*` is attached to the type with no space before the name), so it silently
# dropped every pointer-returning declaration: 210 of fire_runtime.h's 470, 7 of
# fire_sqlite3.h's 22, and most of fire_python.h. `build_stdlib_dylib.py` builds
# the stdlib dylib's reflection table with that function, so the shipped dylib
# was advertising 260 of its own 459 runtime entry points — a C client
# resolving `mojo_c_getenv` through reflection was told the symbol did not
# exist. On the gimple path, and predating FORMAL.md.
test('ptrreg', [PY, 'test_ptr_registry.py'], mem='tiny', cache=True,
     extra=['test_ptr_registry.py', RUNTIME_SRC, RUNTIME_HDR],
     desc='runtime unit test: pointer-registry table + inline-buffer lists (-O0/-O2/ASan)')
# The one group of the same harness that is allowed to be red, split out so it
# can be named instead of taking the green groups down with it. Registered
# 2026-09-30 when the harness's asserts were found to be compiled out by
# python3-config's -DNDEBUG (test_ptr_registry.py::_flags); with them live, a
# pre-existing crash appeared that had been sitting in the file the whole time.
test('ptrreg-boxed-str', [PY, 'test_ptr_registry.py', '--group', 'boxedstr'],
     mem='tiny', cache=True,
     extra=['test_ptr_registry.py', RUNTIME_SRC, RUNTIME_HDR],
     expect='an int64 dict key in [2^31, 2^47) is misread as a char* and '
            'dereferenced: `d[3000000000] = 1` segfaults. The scalar body model '
            'gives a char* and an int64_t the same 64 bits, so the shape test '
            'cannot be right; the fix is for the codegen to stop asking. See '
            'bugs/RUNTIME_int64_key_above_2gb_dereferenced_as_pointer.md',
     desc='a large integer dict key is not dereferenced as a pointer')
# The two instruments from the previous round, which existed and ran by nothing
# for the same reason until agent [5]'s estate check reported them. The taxonomy
# is what makes the coverage number honest, and `comptime` parity pins the one
# cell where it is silently 0 — an instrument nothing runs is a claim.
test('refusal-taxonomy', [PY, 'test_refusal_taxonomy.py'],
     deps=['preflight'],
     desc='the sweep\'s refusal families stay a taxonomy, and stay out of "other"')
# ~275 s, because it builds and runs real programs on both paths. `proofs`, not
# `check`: the everyday inner loop should not pay for it every time.
test('comptime-parity', [PY, 'test_comptime_parity.py'],
     deps=['preflight'],
     desc='comptime measured on both paths, including the one silent cell')
# [4]'s returned-frame layout, which existed and ran by NOTHING until agent
# [5]'s test-estate check reported it.  That is the whole argument for that
# check in one line: the test was written, it passes 10/10, and a suite with
# no inventory of test files could not tell you it was not running.
test('returned-frame-layout', [PY, 'test_returned_frame_layout.py'],
     deps=['preflight'],
     desc="a frame that outlives its creator has a place to live, or is refused by name")
test('rthdrscan', [PY, 'test_runtime_header_scan.py'], cache=True,
     extra=['test_runtime_header_scan.py', 'reflect.py', RUNTIME_SRC,
            RUNTIME_HDR, 'runtime/fire_sqlite3.h', 'runtime/fire_zlib.h',
            'runtime/fire_ssl.h', 'runtime/fire_ncurses.h',
            'runtime/fire_python.h'],
     desc='runtime header export scan sees every declaration')
# `mem='small'` (8 GB), down from `stage` (96) — the single biggest change in
# the ratchet, and the reason it needed a measurement to be safe.
# `test_selfhost.py` calls `fire.build_executable(fire.py)`, which is the
# whole-closure self-compile plus `gcc -O2 -fgimple` plus a link, so this job
# used to take the class documented on the 55.8 GB self-compile and reserve 96
# of the machine's 96 GB: the everyday `check` bucket serialised behind a job
# measured at 3.7 GB, twelve times a second, on every other worker's runs too.
# Measured peak 3.7 GB, so the ratchet assigns 5.55 and the smallest class that
# covers it is `small`. What replaced the 55.8 GB figure is
# MEASURED_PEAK_GB, read off a run's log by the same wrapper that enforces the
# ceiling — and note that the same measurement taken on 2026-09-29 for
# `bootstrap-stage1-transitive` (the same python closure dump) reads 1.1 GB, so
# the 55.8/96 numbers are not this workload's RSS on this tree. A build that
# genuinely needs more says so: MEMLIMIT_GB=96.
test('selfhost', [PY, 'test_selfhost.py'], mem='small', cache=True,
     extra=GIMPLE_SOURCES + ['fire_compiler.py', 'myinterpreter.py', 'fire.py',
                             'fire_main.py', 'test_selfhost.py'],
     desc='the compiler compiles itself to a linked binary, cleanly')
test('runtimediff', [PY, 'test_runtime_diff.py'], mem='tiny', cache=True,
     extra=GIMPLE_SOURCES + ['fire_compiler.py', 'myinterpreter.py', 'fire.py',
                             'test_runtime_diff.py'],
     desc='interpreter vs JIT: identical stdout and exit code')
# The interpreter's OWN output, against a directly-imported one: it runs
# `fire_compiler.py`'s `py_tokenize` twice, once imported and once reached
# THROUGH `myinterpreter.py`'s `Interpreter` executing that file's own source,
# and requires identical token streams AND identical exception types and
# messages over 67 corpus texts (18 snippets plus 49 whole files).
#
# It is the only check of its kind and the reason it exists is that an
# interpreter bug produces a WRONG ANSWER, not an exception: the compiled path
# is then wrong in the same direction and every engine-vs-engine diff in the
# tree stays clean. That is how `@classmethod`'s `cls` binding the first real
# ARGUMENT, and `@deco` being parsed and then never applied at all, stayed
# invisible (`bugs/UNTESTED.md` 3.2 -- and what `interporacle` was written for).
#
# It ran by NOTHING until 2026-10-02: it loaded `mojo/ast_nodes.mojo`,
# `mojo/tokenizer.mojo` and `mojo/parser.mojo`, none of which exists, and
# reported success while dying at its first `open()`. Repointed at
# `fire_compiler.py` rather than deleted, and the corpus grew from eight
# hand-written snippets to whole real files.
#
# `extra` names BOTH subjects, not just the test: the oracle is "the same
# function through two engines", so a change to either `fire_compiler.py`'s
# tokenizer or `myinterpreter.py`'s evaluation of it is exactly an input.
# Measured 0.1 GB peak through memcap's own report, one run alone under
# `tools/memslot.py --gb 8`, about a second -- `tiny`.
test('interp-tokenizer-oracle', [PY, 'test_myinterpreter_validation.py'],
     mem='tiny', cache=True,
     extra=['test_myinterpreter_validation.py', 'fire_compiler.py',
            'myinterpreter.py', 'formal/examples'],
     desc='the interpreter\'s tokenizer vs the imported one, over 67 texts')
test('metalgpu', [PY, 'test_metal_codegen.py'], cache=True, mem='tiny',
     extra=GIMPLE_SOURCES + ['test_metal_codegen.py',
                             'mojo/middle/metal_ops.py',
                             'mojo/backend_gimple/device_select.py',
                             'mojo/backend_gimple/emit_metal.py'],
     desc='Metal codegen: op tables, device-region selection, MSL emission, '
          'and the generated MSL compiled by Apple\'s real compiler and run '
          'on the GPU against a CPU reference')
test('md2html', [PY, 'test_md2html.py'], cache=True, mem='tiny',
     extra=['tools/md2html.py', 'test_md2html.py',
            'doc/GPU_OFFLOAD_PLAN.html', 'doc/METAL.html'],
     desc='the docs\' HTML generator keeps every word of its Markdown, and '
          'the committed HTML is not stale')
test('linkmode', [PY, 'test_link_mode.py'], cache=True,
     extra=GIMPLE_SOURCES + ['fire_compiler.py', 'myinterpreter.py', 'fire.py',
                             'driver.py', 'test_link_mode.py'],
     desc='the real driver.compile_program link-mode pipeline')
test('no-new-casts', [PY, 'test_no_new_container_casts.py'], cache=True,
     extra=GIMPLE_SOURCES + ['test_no_new_container_casts.py'],
     desc='grow-only allowlist on ad-hoc container casts (text scan)')
# The tool prints the name it was INVOKED as (fire / mojoc / stage2/mojo), not a
# hard-coded one. Registered by the integrator: the test landed with help-rename
# but in no bucket, which turned `suite-self-test`'s estate check red.
#
# `mem='tiny'` and in `check`, both added here rather than at registration:
# registering a test is not the same as running it, and 19 of this registry's
# members sat in NO bucket at all — named by a spec, in the estate's inventory,
# and executed by nothing. Every one is in a bucket now, and
# test_suite.py's `the buckets:` checks are what keeps it that way. This one is
# 1.1 s and 0.04 GB, which is what the everyday bucket is for.
test('cli-usage-text', [PY, 'test_cli_usage_text.py'], cache=True, mem='tiny',
     extra=['test_cli_usage_text.py', 'fire.py', 'fire_main.py', 'fire_compiler.py'],
     extraglob=['**/*.py'],
     desc='the tool prints the name it was invoked as, in usage, -v and every error')
# `extraglob=['**/*.py']` is the same hole `suite-self-test` documents, one
# subject over: `test_no_stale_command_name_in_prose` WALKS every `.py` file in
# the tree (it ratchets `mojo <command>` out of the prose, and its doc was
# deleted with the sweep that emptied it), so its subject is a SET that no
# entry in `extra` can name. Keyed on the four files above, adding the old
# command name to `module_loader.py` would move no key, the recorded PASS would
# be replayed, and the check written to catch exactly that would not run. A
# cached job is a promise that its inputs are its subject.

# The other ratchet, and the one with the larger corpus. CLAUDE.md deletes a bug
# doc when its bug is fixed, and every citation of that doc is left pointing at
# nothing: 480 of them, across 156 files, at last measurement. A `check()` over
# the corpus cannot land while it is that size — it would be red on arrival and
# in every branch that did not cause it — so this is the one shape that can:
# `--ratchet` fails only when a file GAINS a citation, against per-file ceilings
# in `tools/dangling_refs_baseline.py`. It is green today, and the campaign is
# 480 one-line prose edits that each of them now makes easier to bank.
#
# The key covers `**/*.md` and `**/*.py` because the walk's subject is every
# `.md` and `.py` in the tree — `fire_compiler.py` alone is 24 of the citations,
# and a key that cannot see a change there serves the last green run. Same
# promise `suite-self-test` makes with `**/test_*.py`.
test('doc-refs', [PY, 'tools/dangling_doc_refs.py', '--ratchet'], cache=True,
     extra=['tools/dangling_doc_refs.py', 'tools/dangling_refs_baseline.py',
            'checked_run.py'],
     extraglob=['**/*.md', '**/*.py'],
     desc='no file cites a deleted bug doc more than it used to')
# `nonlocal` on both execution paths. Its own test because the feature spans
# the parser (a new statement node), the interpreter (scope resolution) and
# the closure-capture pass (by-reference capture), and a regression in any one
# of the three is a SILENT wrong answer rather than a build failure — the
# compiled program used to exit 0 with the pre-`nonlocal` value.
test('nonlocal', [PY, 'test_nonlocal.py'], cache=True,
     extra=GIMPLE_SOURCES + ['test_nonlocal.py', 'myinterpreter.py',
                             'fire.py', 'fire_main.py', 'driver.py',
                             RUNTIME_SRC, RUNTIME_HDR],
     desc='nonlocal: interpreter and compiled paths agree with CPython')
# The two COMPILE-AND-RUN suites over generated C. They were unregistered,
# which is why the round-1 `yield from cls.<generator>` regression in
# `test_gimple_generator_runner.py` never ran in the gate at all: a real
# regression was invisible. `test_gimple` (above) is a UNIT suite — it
# inspects emitted text — and neither of these is covered by anything else in
# the registry, so each is its own test with its own input list.
#
# `extra` is the union of what can change their verdicts: the codegen sources
# (they drive codegen in-process), `build_config` (they pick the compiler),
# and — for the generator suite — the coroutine runtime sources it links
# against, which CORO_RUNTIME already enumerates. Both use `driver='cmd'`,
# not `'mem'`: they invoke gcc directly on a snippet-sized translation unit,
# the same `small`-workload shape `test_gimple.py` is, and a cap on a job
# that never loads the whole closure buys nothing (see the MEMCLASS note).
# Marked `expect=` rather than `disabled=`, and the reason is what the two
# markers are FOR: this job's answer is not known, only four of its 376 cases
# are, and it is the only instrument in the tree that compiles a real Mojo
# program and EXECUTES it. `disabled=` would stop all 376 for the sake of the
# 4, trading 372 passing rows of signal for a tidier screen — which is the
# coverage hole the marker exists to prevent, not create. Cost is not the
# blocker `disabled=` is for either: 0.2 GB and 270 s is not a machine-sized
# reservation being spent on a known answer.
#
# The 4 are not bugs in the branch that added them — each passes there — but
# interactions the merge of ten branches exposed, so the marker is a count-
# CHECKED claim: a 5th failure, or a fix that leaves 3, is a FAILURE rather
# than silently absorbed, and a run where all 4 are fixed reports "marked
# expect= … but it PASSES". Each has its reproduction and next step in
# bugs/MERGE_bugs4_gimplerunner_four_remaining.md.
test('gimplerunner', [PY, 'test_gimple_runner.py'], cache=True,
     extra=GIMPLE_SOURCES + ['test_gimple_runner.py', 'build_config.py',
                             'exec_budget.py',      # imported: must be in the key
                             RUNTIME_SRC, RUNTIME_HDR, 'gimple_codegen.py'],
     expect='4 of 376: compile-and-execute rows the merge of ten branches '
            'left red — none fails on the branch that added it; see '
            'bugs/MERGE_bugs4_gimplerunner_four_remaining.md',
     desc='compile-and-execute: plain programs, structs, closures, stdlib calls')
test('gimplegenerators', [PY, 'test_gimple_generator_runner.py'], cache=True,
     extra=GIMPLE_SOURCES + ['test_gimple_generator_runner.py',
                             'exec_budget.py',      # imported: must be in the key
                             'build_config.py', RUNTIME_SRC, RUNTIME_HDR]
         + CORO_RUNTIME,
     desc='compile-and-execute: every generator/coroutine shape, both backends')

# [1]'s round was "the silent no-op class", and this is the test that pins it.
# It is in `check` and not in a heavyweight bucket because it needs no Lean and
# no library -- 212 s measured, against `sqliteruntime`'s ~100 s, so it costs
# `check` about what an existing member already costs. The reason it cannot sit
# outside the everyday gate is the class itself: a silent wrong answer cannot be
# caught by an exit code, so a test that only runs in a bucket nobody runs daily
# is not guarding the property it was written for.
#
# `cache=True` with `extra=GIMPLE_SOURCES` is load-bearing rather than
# boilerplate. GIMPLE_SOURCES is gimple_codegen.py plus every mojo/middle/*.py
# and mojo/backend_gimple/*.py, which is exactly this test's surface -- and
# [1]'s three fixes were all in mojo/backend_gimple/emit_{loops,calls,infra}.py.
# Without those in the key a fix to emit_loops.py would serve a recorded PASS for
# a test whose whole subject is emit_loops.py, which is the one failure mode
# `extra` exists to prevent.
test('silentnoop', [PY, 'test_silent_noop_iter.py'], cache=True,
     deps=['preflight'], timeout=900,
     extra=GIMPLE_SOURCES + ['test_silent_noop_iter.py', 'build_config.py',
                             RUNTIME_SRC, RUNTIME_HDR],
     desc='the silent no-op class: no loop may iterate zero times, read a '
          'container as another kind, or drop reversed/findall order')
# The ORACLE's own suite: myinterpreter vs CPython, on programs written in the
# subset of syntax that is valid Mojo AND valid Python. Its own test because
# every other parity test here compares the two ENGINES with each other, which
# structurally cannot catch a bug they share — and a shared wrong answer is
# exactly what an interpreter bug produces. Two real ones went unnoticed for
# exactly that reason: a `@classmethod`'s `cls` binding the first real
# ARGUMENT, and `@deco` being parsed and then never applied at all (the
# compiled path ignored decorators too, so the diff was clean).
test('interporacle', [PY, 'test_interp_oracle.py'], cache=True,
     extra=['test_interp_oracle.py', 'fire_compiler.py', 'myinterpreter.py',
            'fire.py', 'fire_main.py'],
     desc='the interpreter oracle itself, diffed against CPython')
# Every `formal/examples/*.mojo` parses. Registered in `check` — not in the
# formal bucket its files feed — because this is a PARSER invariant whose
# failure mode is invisible from where the files are consumed.
#
# `19bc0dd` (merged in as part of ae9877d) made a decorator's parenthesised
# argument list a real parse where it had been skipped token by token. That
# is the right fix — `@deco` and `@deco(x)` had become indistinguishable, and
# every parameterised decorator was inert — but it also imposed Mojo
# call-argument syntax on a decorator whose arguments are not call arguments.
# `@spec(fact_spec; fact_spec 0 = 1; ...)` is a `;`-separated specification,
# so 4 of the 45 examples (`fact`, `fib`, `sum`, `count`) stopped parsing. `make check` stayed green
# throughout: the only consumers of these files are the `formal*` steps, the
# most expensive tests in the repo, and the only visible symptom was a
# coverage number that had quietly gone 41/4/0 -> 26/6/13. A 0.1s,
# toolchain-free, `expect`-free structural check turns the next one into a
# `check` failure. See test_examples_parse.py's docstring.
test('examples-parse', [PY, 'test_examples_parse.py'], cache=True,
     # The 45 example files are hashed as a DIRECTORY, not as 45 paths.
     # `fire_compiler.py` is redundant here — it is already in
     # cas._COMPILER_SOURCES, so cas.compiler_fingerprint() covers it — and it
     # was standing in for the real subject. `checked_run.py` hashes a
     # directory's whole recursive contents by relative path in sorted order,
     # so the 46th example is covered the day it is added and a rename moves
     # the key. Measured by [5]: this key read 48 repo files and 0 under
     # formal/examples/, so a SyntaxError in any of the 45 could not invalidate
     # it and a recorded PASS replayed. See bugs/UNTESTED.md 3.1.
     extra=['test_examples_parse.py', 'formal/examples'],
     desc='every formal/examples/*.mojo parses; decorator arg shapes distinct')


# ── the test estate, inventoried by [5] in bugs/UNTESTED.md ────────────────
#
# 50 test files were named by no registered spec, and 21 of those exited
# non-zero. Measured per file here rather than read out of a bug doc, because
# the two lists disagree: `test_x86_64_containers.py` appears in [5]'s Tier 1
# ("mostly green") AND its Tier 2, and it is red. Registering is still the
# right move in both directions -- a declared red is a report and an unrun red
# is silence -- and `expect=` is how a red is declared rather than silenced.
# The anti-rot then FAILS any of these that starts passing, which is the
# signal worth having.
# …and every one of them is in a BUCKET now, which is the other half of the
# same sentence. All of this block was registered in one commit and bucketed in
# none, so `--list` printed `[]` in the bucket column for nineteen of them and
# no run in the tree executed them. Eleven were `expect=`-marked, which is the
# worse half: a marker nobody can observe going stale is immortal, and a
# `coro` bucket that ran nothing for two rounds is what that looks like in this
# tree's own history. The buckets plus the `dep=True` field below are the fix;
# the `the buckets:` checks in test_suite.py are the part that stops the next
# one arriving the same way, and their bug docs are deleted with the fix rather
# than left with a Status history (CLAUDE.md, "Bug docs").
#
# The `mem=` on each row below is the ratchet's, from a measured run: every one
# of these is 0.0-0.2 GB, and at 0.2 GB the 1.5x rule that assigns a class puts
# them all at the floor, `tiny`. They were all `small` (8 GB) before, which is
# 40-80x their peak — see the "at the floor" list `make check-list` prints, and
# note that a class is a claim on the machine, so an 8 GB claim from eleven
# 0.2 GB jobs is eighty-four gigabytes of budget spent on nothing.
#
# The ungated cluster (eleven `expect=`-marked tests and three plain ones) is
# the same defect seen from the other side and is bucketed at the bottom of this
# file: `coroutine` for the eleven, `check`/`x86` for the three. Two of the
# markers below state their count (`mutable-async-capture`,
# `transitive-closure-capture`), which the runner now CHECKS against the run.
test('x86-examples', [PY, 'test_x86_64_examples.py'], mem='tiny',
     deps=['preflight'],
     desc='the x86-64 examples build, run and agree with the source')
test('arm64-encoders', [PY, 'test_arm64_encoders.py'], mem='tiny',
     deps=['preflight'],
     desc='every arm64 encoder: the immediate, the shifted, the REX forms')
test('x86-decode', [PY, 'test_x86_64_decode.py'], mem='tiny',
     deps=['preflight'],
     desc='the x86-64 decoder, byte at a time, against hand-written encodings')
test('ownership-destruct', [PY, 'test_ownership_destruct.py'], mem='tiny',
     deps=['preflight'],
     desc='an owned value is destructed exactly once')
# Registered 2026-09-30 with the new-modular work. Nine parser features landed
# that day (dotted literals, `__match` and its flat case layout, typed lambdas
# with capture/comptime blocks, explicit `def` capture lists, the `imm`
# convention, struct `where` clauses, multi-target `comptime`, function types in
# subscript position, decorated imports) and compile_stdlib went 356/610 ->
# 610/610 on them — with NO fixture for any of them, so a regression in any
# one would have shown up only as a compile_stdlib delta, days later, in a
# 610-file run. It already caught one real bug on the day it was written: the
# multi-target `comptime` consumed its own `=` and then looked for a second,
# silently dropping the binding (codepoint.mojo compiled with `char` and
# `num_bytes` bound to nothing).
test('new-syntax-parse', [PY, 'test_new_syntax_parsing.py'], cache=True, mem='tiny',
     # `fire_compiler.py` is the file under test and is NOT in GIMPLE_SOURCES
     # (that list is the CODEGEN sources); without it in the key, editing the
     # parser replayed a recorded PASS.
     extra=(['test_new_syntax_parsing.py', 'fire_compiler.py']
            + GIMPLE_SOURCES),
     desc="the new-modular syntax parses, and still does NOT parse where it "
          "must not (ellipsis, float literals, attribute access)")
test('x86-containers', [PY, 'test_x86_64_containers.py'], mem='tiny',
     deps=['preflight'],
     expect="1 of 60 on x86_64: the `with-statement` case is refused by the "
            "FORMAL backend's read-before-store rule: `with 7 as y: x = y` "
            "binds y, and the refusal says 'y is read at line 4 before "
            "anything in this function stores it'. Pre-existing in the "
            "batch-1 tree (the rule and its call site are byte-identical to "
            "b13a01b2), and NOT this job's construct — the nested-comprehension "
            "cluster this marker originally named is closed and its doc "
            "deleted. See bugs/FORMAL_a_local_read_before_its_first_"
            "assignment.md",
     desc='`with ... as` is refused by the read-before-store rule')
test('mutable-async-capture', [PY, 'test_mutable_async_capture.py'], mem='tiny',
     deps=['preflight'],
     expect='2 failing: async capture of a mutable binding — behaviour gap, '
            'not registered before this',
     desc='async capture of a mutable binding — behaviour gap, not registered before this')
test('transitive-closure-capture', [PY, 'test_transitive_closure_capture.py'],
     mem='tiny', deps=['preflight'],
     expect='2 failing: closure capture through a transitive import — '
            'behaviour gap',
     desc='closure capture through a transitive import — behaviour gap')
test('gimple-async-runner', [PY, 'test_gimple_async_runner.py'], mem='tiny',
     deps=['preflight'],
     expect='36 failing: the gimple async runner, an area with no gate '
            'coverage until now',
     desc='36 failing: the gimple async runner, an area with no gate coverage until now')
test('coro-future-await', [PY, 'test_coro_future_await.py'], mem='tiny',
     deps=['preflight'],
     expect='17 failing: `await` on a Future in the coroutine runtime',
     desc='17 failing: `await` on a Future in the coroutine runtime')
test('async-void-return', [PY, 'test_async_void_return.py'], mem='tiny',
     deps=['preflight'],
     expect='3 failing: an async function with no return value',
     desc='3 failing: an async function with no return value')
test('taskgroup', [PY, 'test_taskgroup.py'], mem='tiny',
     deps=['preflight'],
     expect='3 failing: TaskGroup',
     desc='3 failing: TaskGroup')
test('async-with-lock-guard', [PY, 'test_async_with_lock_guard.py'], mem='tiny',
     deps=['preflight'],
     expect='2 failing: `async with` holding a lock guard across a suspension',
     desc='2 failing: `async with` holding a lock guard across a suspension')
test('nested-async-generic', [PY, 'test_nested_async_generic.py'], mem='tiny',
     deps=['preflight'],
     expect='2 failing: a generic inside a nested async',
     desc='2 failing: a generic inside a nested async')
test('coro-detached-async', [PY, 'test_coro_detached_async.py'], mem='tiny',
     deps=['preflight'],
     expect='2 failing: a detached coroutine task',
     desc='2 failing: a detached coroutine task')
test('async-runtime-scaffold', [PY, 'test_async_runtime_scaffold.py'], mem='tiny',
     deps=['preflight'],
     expect='1 of 2: toolchain/runtime proof for step A of compiled-path async/await',
     desc='1 of 2: toolchain/runtime proof for step A of compiled-path async/await')

test('preflight', [PY, '-c',
                   'import fire_compiler, gimple_codegen; '
                   'assert fire_compiler.Parser; print("parser+codegen OK")'],
     desc='import-level smoke check of the parser and codegen')
# The runner tests itself. `make check` is a one-line recipe that hands the
# whole bucket to tools/suite.py, so a bug in the runner does not fail one
# test — it fails or falsely passes the entire gate. This is synthetic specs
# and synthetic commands: no toolchain, milliseconds, so it can be the first
# thing anyone runs when the runner itself is what changed.
#
# `extraglob` is load-bearing and not decoration, and it is the reason this
# registration is honest rather than merely present. This spec is `cache=True`,
# and it carries the estate check — the check that fails when a test file lands
# with neither a registration nor a reason. Keyed on the runner's own sources,
# ADDING `test_whatever.py` moved no key: the recorded PASS was replayed and
# the check written to catch exactly that never ran. A cached job is a promise
# that its inputs are its subject, and here the subject is a set of files that
# nothing in `extra` could name without a list that rots on the next one.
#
# `**/test_*.py` rather than `test_*.py`, and that `**` is the second half of
# the same bug found by the merge rather than by design: the flat pattern is a
# second copy of the top level, so when `test_llm/test_llm.py` landed the walk
# below found it and the cache key did not — the check that exists to report
# exactly that, not seeing it. `**` matches zero segments too, so one pattern
# still covers the root. `checked_run.expand_globs` drops `DERIVED_DIRS`
# (`build/`, `aside/`, `bside/`, `__pycache__`) because a glob recurses where a
# named directory does not have to, and the A/B copies under `aside/`/`bside/`
# are the same content under a second name; that list is shared with the walk
# in `test_suite.py`, so the two cannot drift about what a test file is.
#
# That is the whole of the bug this doc used to point at
# (that bug's doc, closed and DELETED with the fix) in one mechanism: the check existed, and the cache in
# front of it was a hole exactly the shape of the thing the check looks for.
#
# BOTH patterns, and that is the same reasoning applied a second time. The walk
# behind the check counts `test_*.py` AND `*_test.py` (one predicate,
# `test_suite.py`'s `is_test_file_name`, and four files were outside the
# inventory entirely before it: two registered `formal/*_test.py` suites the
# walk never saw, and `formal/x86_64_model_test.py`, the only check on
# `lib/X86.lean` that EXECUTES a machine model instead of typechecking it, run
# by nothing). A key that named one spelling would replay a recorded PASS over
# a change to a file in the other. `test_suite.py`'s
# `test_the_estate_check_is_in_a_gate_and_can_see_its_subject` asserts both
# patterns are present and that the glob and the walk agree, so the two cannot
# drift back apart.
test('suite-self-test', [PY, 'test_suite.py'], cache=True,
     extra=['test_suite.py', 'tools/suite.py', 'tools/procrun.py',
            'tools/memslot.py', 'tools/memcap.py', 'checked_run.py',
            'test_memslot.py', 'tools/dangling_doc_refs.py'],
     extraglob=['**/test_*.py', '**/*_test.py'],
     desc='the runner: drivers, deps, exclusivity, fanout, tally, log split')

# The ledger every job above reserves out of, tested on its own. In `smoke`
# rather than nowhere, which is where it was for a commit: `test_memslot.py`
# arrived untracked, was committed, and still had no spec and no bucket, so
# the estate check that exists to catch exactly that reported it — correctly.
# And it earns one. A bug in the ledger is not a failing test, it is a HUNG
# GATE: two reservations for one process tree deadlock (measured, see
# `covering` in tools/memslot.py), and every job in every bucket goes through
# it. Cheap — its own private ledger, a 10 GB budget of made-up gigabytes, and
# nothing compiled.
test('memslot', [PY, 'test_memslot.py'], cache=True,
     extra=['test_memslot.py', 'tools/memslot.py', 'tools/memcap.py'],
     desc='the machine-wide memory ledger: FIFO, budgets, crash, tree coverage')
test('coro', [PY, 'test_coro_runtime.py'], cache=True,
     extra=['test_coro_runtime.py'] + CORO_RUNTIME,
     desc='A3 stack-switch coroutine runtime, every backend at -O0 and -O2')
test('coro-nested-capture', [PY, 'test_coro_nested_async_capture.py'], cache=True,
     extra=['test_coro_nested_async_capture.py', 'gimple_codegen.py',
            'runtime/fire_async_runtime.cpp', 'runtime/fire_async_runtime.h'] + CORO_RUNTIME,
     desc='nested async-def mutable closure capture under MOJO_CORO=stackswitch '
          '(was 0/9, unregistered, naming the pre-rename mojo_*.c runtime files)')

# ── The self-hosted BINARY's own compiled codegen ───────────────────────────
# Everything here runs a mojoc process, so everything is capped, and
# everything that writes a .ci into the repo root is exclusive: two of them
# racing on the same fire.ci would diff two half-written files.
#
# `mojoc` and `stage2/mojo` are also the two steps whose artifact is a binary,
# and the only two that are cached by content — see ArtifactCache for why they
# are safe to cache and the stage trees are not.
#
# HISTORY OF THE MARKER ON THIS CLASS, because it moved twice and both moves are
# the anti-rot discipline rather than bookkeeping.
#
# `bootstrap-stage2-dumps` carried `SELFHOST_SEGV` ("the self-hosted binary
# segfaults on any input, exit 139"). That was MEASURED FALSE on 2026-09-27 and
# corrected rather than left to rot: the original SIGSEGV is fixed (BLOW.md §0),
# `./mojoc --dump-full` on a two-line program is exit 0 / 12.1 MB / 94.6 M
# instructions. It was replaced with `SELFHOST_STAGE2_STALL`, whose point was
# that a marker saying "segfault" would hide the real class — a
# `mojo_unsupported_iter` no-op the runner flags per sub-job and no exit code
# reports.
#
# 2026-10-03: that marker was STALE and the runner said so (a marker whose test
# passes is a FAILURE). Not because the class is fixed — because this fanout
# cannot see it. `reject=` is a regex over a child's output, the 47 sub-jobs no
# longer emit `mojo_unsupported_iter`, and `--dump` on the compiled binary now
# writes an EMPTY `.ci` while exiting 0, which prints nothing for a regex to
# match. So the marker moved to `bootstrap-verify` and `bootstrap-validate`,
# which compare the stage trees and therefore DO see it, and the fanout carries
# a comment saying so instead of a marker that would have to be a lie in one
# direction or the other. See `SELFHOST_STAGE2_EMPTY_DUMP` below and
# bugs/CODEGEN_bootstrap_stage2_dump_is_empty.md.
#
# RETIRED as a marker 2026-10-03, and NOT because the class is fixed. The
# marker said the per-item fanout "returns `mojo_unsupported_iter` no-ops or a
# wrong dump"; measured on that gate, the `mojo_unsupported_iter` half is GONE —
# which is why `bootstrap-stage2-dumps` passed and the runner correctly reported
# a marker whose test passes as a FAILURE. The "wrong dump" half is exactly what
# `bootstrap-verify` reports in the same run (87 stage1-vs-stage2 diffs, most of
# them a 0-byte `.ci`), so the class did not go away: its DETECTOR in this job
# went away with it. `reject=` is a regex over a child's OUTPUT and a child that
# writes nothing prints nothing, so this fanout cannot see an empty artifact
# however it is spelled.
#
# So the marker moves to the two jobs that DO compare what was produced, which
# is where a reader of the tally will actually see this. The constant is kept,
# renamed, because its text is still the truest short description of the class
# in the tree and `bootstrap-verify`/`bootstrap-validate` both cite it.
SELFHOST_STAGE2_EMPTY_DUMP = (
    'the self-hosted binary no longer segfaults (re-measured 2026-09-27: '
    'exit 0 on a two-line program, 12.1 MB, 94.6 M instructions) and no longer '
    'emits `mojo_unsupported_iter` (re-measured 2026-10-03: the per-item '
    'fanout rejects none), but `--dump` on the compiled binary writes a correct '
    '`.pyi`, an EMPTY `.ci` and NO `.tok`/`.ast`, and exits 0 — so '
    '`bootstrap-stage2-dumps` passes while 87 of its products are not dumps. A '
    'silent-wrong-answer class no exit code reports; stage2 and stage3 agree '
    'with each other exactly (0 diffs), so it is the binary computing something '
    'other than the reference, deterministically. See '
    'bugs/CODEGEN_bootstrap_stage2_dump_is_empty.md')
# `ab-native`/`native-dumpfull` no longer segfault (verified 2026-09-27,
# BLOW.md §0) but are STILL red for a different, real reason: their corpora
# legitimately trigger this compiler's self-hosting bootstrap pre-pass
# (a genuine, do_imports=True sibling-import compile whose sources live in a
# per-run scratch directory under the worktree — see test_ab_native.py's
# module docstring; they used to be placed in the repo root on purpose, which
# is what raced the fan-out enumeration and is no longer the case), and that
# pre-pass itself is extremely expensive per call
# (~15-30 GB, ~15-25s — see BLOW.md §0's "NOT closed" addendum for the
# measured repro and hot-stack profile: mojo_cstr_region_eq/
# mojo_set_add_int/_set_grow dominating, the same signature as the original
# bug this doc fixed, just now correctly SCOPED to only the cases that
# should trigger it at all). Update this reason (not just delete it) once
# that per-call cost is actually brought down — see BLOW.md for the
# specific next-step suggestions (cross-call caching across the three
# `_selfhost_*` seed passes within one process; degenerate-hashing check on
# the tokenizer's `MojoSet` usage).
#
# `native-dumpfull` carries this same reason and is LEFT on `expect=`; see its
# registration below for why that one is not switched too. This constant is
# also the whole of §4's subject matter: bugs/CODEGEN_ab_native_fails.md tables
# every `expect=` job in the registry with its measured peak, its class and its
# reservation, and a recommendation each.
SELFHOST_TOKENIZE_BLOWUP = (
    'no longer segfaults, but the self-hosting bootstrap pre-pass this '
    'corpus legitimately triggers costs ~15-30 GB / ~15-25s per call — see '
    'BLOW.md §0 "NOT closed" for the measured repro and root-cause status')
# `small` (8 GB), not `stage` (96): `fire.py build fire.py` is the
# whole-closure self-compile AND the `gcc -O2 -fgimple` over the resulting
# 40 MB translation unit, and it used to be given the class documented on the
# 55.8 GB self-compile, reserving the whole 96 GB machine budget. Measured
# peak 3.7 GB (MEASURED_PEAK_GB), so the ratchet assigns 3.7 x 1.5 = 5.55 GB
# and the smallest class covering it is `small`. The Makefile's recipe for this
# target names the same class, which is not tidiness: a recipe asking for MORE
# than the job reserved takes a second reservation inside a tree the first one
# is already accounted for, and that deadlocks rather than failing
# (tools/memslot.py's `covering`). test_suite.py checks the two cannot drift.
#
# `excl` for the artifact, not for the memory: `./mojoc` and `fire.ci` are
# written in the repo root and another job in this run links against them, so
# nothing else may start while this runs. The reservation is the class, like
# every other job's — see `reserved_gb`.
test('mojoc', ['mojoc'], driver='make', mem='small', excl=True,
     artifact='mojoc', inputs=[MOJO_MAIN] + PY_FILES + [RUNTIME_SRC, RUNTIME_HDR],
     desc='build the one managed native compiler (-O2 -g0)')
# `program` (55 GB), UP from `module` (24) — the one job the ratchet moves up,
# and the measurement is why: registered at `small` (8 GB) it was killed by its
# own ceiling on 2026-09-29 at a peak of 9.4 GB (a RESOURCE verdict, which is
# not a verdict on anything, on a test already marked expect=), and at `module`
# (24) the 2026-09-30 measurement is 20.5 GB — 85% of the ceiling, one more
# corpus file from a guaranteed kill. The ratchet asks for 1.5x, which is
# 30.75 GB, and the smallest class covering that is `program`.
#
# DISABLED, not `expect=` (was SELFHOST_TOKENIZE_BLOWUP, 2026-09-30), and the
# distinction is the whole point of the change. With `expect=` this job ran in
# full every gate: 20.5 GB measured, a `program` class reserving 55 of the
# machine's 96 GB, and `excl=True` so nothing else in the run started while it
# did — to be told the thing the marker already said, since its corpus was
# 30/30 byte-identical on 2026-09-21 and the divergence since then is
# downstream of the same pre-pass blowup. That is a known outcome bought at a
# machine-sized price, on the one heavy consumer's time, and everything queued
# behind it paid for the answer too.
#
# What it was, and what it is now, and nothing else changes: still registered,
# still in the `native` and `gate` buckets, still `excl`, still carrying its
# measured peak (MEASURED_PEAK_GB, 20.5 GB) and the class the ratchet assigns
# that peak (memwhy, `program`) so that the day it is turned back on the
# numbers are already sized and the artifact is still protected; not run, so no
# process, no ceiling, no reservation, no wall time. `reserved_gb` returns 0
# for it, which is the mechanism, and `tools/suite.py --dry-run native` prints
# the 0.
#
# The bug doc IS the switch: bugs/CODEGEN_ab_native_fails.md is what the test
# is waiting on, the repo's rule is that a fixed bug's doc is DELETED, and
# `disabled_problems` refuses to load this registry the moment that doc is
# gone — naming the job and saying to turn the test back on. So the test cannot
# stay off forever and a fix cannot land without re-enabling it. The
# alternative marker (`expect=`) is still right for the cheap ones; see
# CLAUDE.md, "Known-failing tests".
test('ab-native', [PY, 'test_ab_native.py'], driver='mem', mem='program',
     memwhy='measured 20.5 GB when it last ran: the self-hosting bootstrap '
            'pre-pass this corpus legitimately triggers (see '
            'bugs/CODEGEN_ab_native_fails.md), and 1.5x is 30.75 GB, so '
            '`module` (24) was 85% of what it uses. Recorded, not charged: the '
            'job is disabled, so this class is what it will cost the day it is '
            'turned back on, and it reserves 0 meanwhile. Over the 4 GB line '
            'because the workload is — see ' + MEM_DEBT_DOC,
     deps=['mojoc'], excl=True, cache=True, extra=['test_ab_native.py'],
     disabled='bugs/CODEGEN_ab_native_fails.md',
     desc='python vs native codegen, byte-for-byte, over the A/B corpus')
# NOT switched, deliberately, and the reason is per job rather than per
# principle: `native-dumpfull` and `bootstrap-stage2-dumps` carry the same
# blowup in their `expect=` reason and are the owner's call, because both are
# also the jobs whose runs produce the measurements the blowup work is steered
# by — a marker that cannot be observed going green is weak, and this is the
# case for not weakening it. §4 of bugs/CODEGEN_ab_native_fails.md tables both
# with their peak, class and reservation and a recommendation each, so the
# choice is a line rather than an investigation.
test('native-dumpfull', [PY, 'test_native_dumpfull.py'], driver='mem',
     mem='program',
     memwhy='measured 31.3 GB — the largest job in the registry that still '
            'completes, for the same pre-pass (SELFHOST_TOKENIZE_BLOWUP). '
            '1.5x is 47 GB, so `program` is the class the ratchet assigns; the '
            'class is already correct and the reason is recorded because it is '
            'over the 4 GB line — see ' + MEM_DEBT_DOC,
     expect=SELFHOST_TOKENIZE_BLOWUP,
     desc="the native --dump-full ARTIFACT, diffed against the reference")
# Peak-memory budgets for the self-hosted binary, as numbers (see the module
# docstring of test_selfhost_memory.py). `selfhost-memory` is the fixed cost of
# one invocation (17.6 GB before the 2026-09-30 leak hunt, 0.4 GB after);
# `selfhost-memory-fire` is the compiler compiling itself (37 GB, SIGSEGV ->
# 12 GB) and is excl because it reserves a program-sized slice of the ledger.
test('selfhost-memory', [PY, 'test_selfhost_memory.py', 'snippet'], driver='mem',
     mem='small', deps=['mojoc'], extra=['test_selfhost_memory.py'],
     desc='peak RSS of one self-hosted --dump-full (fixed cost), under budget')
test('selfhost-memory-fire', [PY, 'test_selfhost_memory.py', 'fire'], driver='mem',
     mem='module', deps=['mojoc'], excl=True, extra=['test_selfhost_memory.py'],
     memwhy='measured 12.2 GB when it last ran (doc/MEMORY.html section 11: '
            'the type-scan scratch pool and the shared one-character strings '
            'took the self-hosted compiler compiling fire.py from 34-47 GB to '
            '12.2 GB), so `module` (24) is the smallest class that covers it and '
            '1.5x is 36 GB. Over the 4 GB line and therefore a debt rather than '
            'a fact — see bugs/PERF_memory_over_4gb_is_a_bug.md. It is `excl` '
            'because at this size it is alone on the machine by arithmetic, not '
            'by choice.',
     desc='peak RSS of the self-hosted compiler compiling fire.py, under budget')

# ── stdlib ───────────────────────────────────────────────────────────────────
test('stdlib-tests', [PY, 'test_stdlib.py'],
     desc='every stdlib test/benchmark through interpreter and JIT')
# Fresh by design: reusing the built dylib would make "did this module fall
# back to source" unanswerable, and that skip count is the signal CLAUDE.md's
# gate step 2 asks for. The output path is now PER-ARCH --
# build/libmojostdlib.<arch>.dylib, not build/libmojostdlib.dylib -- because the
# architecture is part of the link key, so one file cannot hold both. Exclusive
# because it deletes and rewrites a shared artifact that other tests link
# against — an artifact, not a memory claim, so the reservation is the class
# like any other job's.
#
# `mem='tiny'` (4 GB), down from `program` (55): measured peak 0.2 GB, so the
# ratchet assigns 0.3 GB and the floor covers it. CAVEAT, and it is the reason
# the number is worth re-measuring rather than trusting: 0.2 GB is the peak of
# a python process, and a dylib build whose modules all "fell back to source"
# is cheap by construction — the same skip count CLAUDE.md's gate step 2 tells
# you not to let grow. If the next gate shows this step at a much higher peak,
# the measurement changed and the class follows it (test_suite.py fails the
# moment a recorded peak stops fitting its class).
test('stdlib-dylib', [PY, '-c',
                      'import build_stdlib_dylib as b; b.build_stdlib()'],
     mem='tiny', excl=True, timeout=3600,
     desc='from-scratch stdlib dylib; reports modules that fell back to source')
test('runtimedylib', [PY, 'test_runtime_dylib.py'],
     deps=['preflight'],
     desc='the runtime dylib: export table, per-arch link, cross-arch checks')

# test_sqlite3_runtime.py was deliberately left unregistered because an
# earlier version of it hung the gate: `fire.py build` on
# `test_sqlite3*.mojo` never linked the optional runtime units at all, so the
# built binary died at link time in a way this suite's own capture never
# noticed hanging. Re-verified 2026-09-28, after [1]/[2]/[3]/[4]/[5]'s
# optional-runtime-unit linking landed (21a82d6 and ancestors): the file now
# runs to completion three times in a row, ~100-105s each, exit 0, 64/64
# checks passing, both the `link` and `fallback` pipelines, all five
# test_sqlite3*.mojo sources. No infinite loop reproduces on this tree
# anymore -- it was the missing link, not the test.
test('sqliteruntime', [PY, 'test_sqlite3_runtime.py'], mem='tiny',
     deps=['preflight'], timeout=600,
     desc='optional-unit link mechanism: derivation, probe, and every '
          'test_sqlite3*.mojo built+linked+RUN on both pipelines')

# `mem='tiny'` (4 GB), down from `program` (55), and the aggregate is what the
# ceiling is still for: the per-file gcc here is small (a snippet-sized
# translation unit, `-fsyntax-only`), so what a ceiling on this job bounds is
# the AGGREGATE of `-j18` of them plus the driving process — the same reasoning
# as the A/B sweep below. A fan-out is bounded by its total, and its
# per-process bound is each child's own. Measured peak 1.5 GB (all 18 at once,
# on a 96 GB budget), so the ratchet assigns 2.25 GB and the floor covers it.
test('stdlib-syntax', [PY, 'compile_stdlib.py'], j=True, mem='tiny',
     timeout=7200,
     desc='gcc -fsyntax-only on the generated GIMPLE, whole stdlib tree')

# ── bootstrap: an ordered graph, not one recipe ─────────────────────────────
# Every step below runs a compiler, or the compiler over a whole closure, so
# every step names a memclass — and every one of them is now `tiny` except the
# artifacts, because the measurements say so (MEASURED_PEAK_GB: the whole
# python closure dump 1.2 GB, each per-file dump 0.5 GB, the gcc -O0 over the
# resulting 40 MB translation unit 1.2 GB). These are the classes the 2026-09-25
# footprint probe put at 24/55/96, and the ledger turned those numbers into a
# queue: a `stage` item reserved the whole 96 GB machine budget, and the three
# fanouts of 45 items each ran four wide.
test('bootstrap-clean', ['rm', '-rf', 'stage1', 'stage2', 'stage3'],
     desc='wipe the stage trees (see the Makefile note on stale artifacts)')

# `tiny` (4), from `bootstrap-stage1-transitive`'s measured 1.2 GB (a per-file
# dump cannot cost more than the whole-closure dump of the same sources, which
# is where the number comes from — MEASURED_PEAK_GB's 'derived' rows are exactly
# this kind of transfer, and they are labelled so a reader can see which rows
# are which). 45 items at 4 GB is 180 GB of ALLOWANCE on a 96 GB budget, and
# the ledger is what makes that safe rather than the other way round: it admits
# 24 at a time, and each measured at 0.5 GB.
fanout('bootstrap-stage1-dumps',
       [PY, '../fire.py', '--dump', '../{file}'],
       items=BOOTSTRAP_INPUTS, cwd='stage1',
       env={'PYTHONPATH': '..'}, mem='tiny',
       deps=['bootstrap-clean'], reject='mojo_unsupported_iter',
       items_are_files=True,
       desc='stage1: python dumps every .mojo and core .py source')
# Must stay AFTER the per-file dumps above: that loop writes fire.ci into
# stage1/ from fire.py as a single module, and this transitive-closure dump
# has to be the last writer of that name or stage2 links a skeleton.
#
# `tiny` (4), down from `program` (55). This is the step the "55.8 GB
# whole-closure self-compile" number was written about, and it is the direct
# measurement of that claim: 1.2 GB in the 2026-09-30 gate, 1.1 GB in the
# 2026-09-29 one, both through this same wrapper. What the older 55.8/96
# numbers were measuring (a macOS *footprint* probe, on a tree state weeks
# older) is not what memcap enforces: a ceiling is applied to summed RSS of
# the process tree, and that is 1.1-1.2 GB.
test('bootstrap-stage1-transitive',
     [PY, '../fire.py', '--dump-full', '../' + MOJO_MAIN],
     driver='mem', mem='tiny', cwd='stage1', env={'PYTHONPATH': '..'},
     deps=['bootstrap-stage1-dumps'],
     desc='stage1: the one transitive-closure fire.ci that stage2 compiles')

# The gcc -O0 -fgimple compile of the 40 MB closure into a real binary. Its
# artifact is cached by the content of stage1/fire.ci plus the runtime sources
# and the exact argv (BOOTSTRAP_OPT, the gcc, the link flags all fold in
# through the argv), which is a textbook content-addressed build: a miss costs
# a few minutes, and a wrong hit could not survive its own output being
# compared by `verify` a few steps later.
#
# `mem='tiny'` (4), down from `stage` (96) — the class that used to be
# documented on exactly this workload, "the largest footprint ever observed
# completing a self-compile". Measured peak 1.2 GB as the tree stands, so the
# ratchet assigns 1.8 GB. The Makefile's own `stage2/mojo` rule names the same
# class, so a hand-run `make stage2/mojo` and this step cannot disagree — and
# they must not, because a recipe asking for more than the job reserved takes a
# second reservation inside a tree the first already accounts for, which
# deadlocks instead of failing.
test('bootstrap-stage2-cc', ['stage2/mojo'], driver='make', mem='tiny',
     deps=['bootstrap-stage1-transitive'],
     artifact='stage2/mojo', inputs=['stage1/fire.ci', RUNTIME_SRC, RUNTIME_HDR],
     desc='gcc -fgimple + link: stage1/fire.ci -> stage2/mojo')

# `tiny` (4), down from `module` (24): 0.5 GB measured PER ITEM, the only
# fanout item peak in the table, so the ratchet assigns 0.75 GB. `module` was
# never close to this workload — it was ~48x it — and what made the number
# matter was never the ceiling, it was the reservation the class stands for.
#
# `expect=` WAS HERE until 2026-10-03 and is deliberately NOT here now. This
# fanout PASSES and cannot be made to fail by the defect it used to be marked
# for: `reject` is a regex over a child's OUTPUT (`run_job`), a child that opens
# a `.ci` and writes nothing into it prints nothing, and the measured shape is
# exactly that — a correct `.pyi`, a 0-byte `.ci`, no `.tok`/`.ast`, exit 0.
# Keeping the marker would have meant either a FAILURE every gate ("marked
# expect= but it PASSES") or dropping a claim that is still true of the
# capability; the marker is on `bootstrap-verify`/`bootstrap-validate` instead,
# which compare the trees and can see it. So do not read this row passing as
# evidence that the self-hosted binary dumps correctly — it is evidence that
# this row does not look at what it produced.
fanout('bootstrap-stage2-dumps',
       ['./mojo', '--dump', '../{file}'],
       items=BOOTSTRAP_INPUTS, cwd='stage2',
       env={'MOJO_HOME': '..', 'PYTHONPATH': '..'}, mem='tiny',
       deps=['bootstrap-stage2-cc'], reject='mojo_unsupported_iter',
       items_are_files=True,
       desc='stage2: the compiled binary dumps every source')
# Same ordering constraint as stage1's: the per-file loop writes fire.ci into
# stage2/ from a single-module dump, so the closure dump has to go last or
# `verify` compares a full closure against a skeleton.
test('bootstrap-stage2-transitive',
     ['./mojo', '--dump-full', '../' + MOJO_MAIN],
     driver='mem', mem='tiny', cwd='stage2',
     env={'MOJO_HOME': '..', 'PYTHONPATH': '..'},
     deps=['bootstrap-stage2-dumps'],
     desc='stage2: the compiled binary compiles itself, transitively')

fanout('bootstrap-stage3-dumps',
       ['../stage2/mojo', '--dump', '../{file}'],
       items=BOOTSTRAP_INPUTS, cwd='stage3',
       env={'MOJO_HOME': '..', 'PYTHONPATH': '..'}, mem='tiny',
       deps=['bootstrap-stage2-transitive'], reject='mojo_unsupported_iter',
       items_are_files=True,
       desc='stage3: same binary, fresh dir (idempotency)')
test('bootstrap-stage3-transitive',
     ['../stage2/mojo', '--dump-full', '../' + MOJO_MAIN],
     driver='mem', mem='tiny', cwd='stage3',
     env={'MOJO_HOME': '..', 'PYTHONPATH': '..'},
     deps=['bootstrap-stage3-dumps'],
     desc='stage3: same binary again (idempotency of the closure)')

# These two are the ONLY jobs that can see the class `SELFHOST_STAGE2_EMPTY_DUMP`
# names, and they became visible for a structural reason worth recording: they
# used to SKIP, because `bootstrap-stage2-dumps` failed and a failed dep skips
# its dependents. Its detector was then removed (the `mojo_unsupported_iter`
# no-op it rejected for is gone), so the fanout passed, and these two ran for the
# first time and reported the divergence the whole cluster exists to find.
#
# `expect=` and not `disabled=`, and the rule that decides it is cost: neither
# job is in `MEASURED_PEAK_GB` (both are in the unmeasured list, so they keep
# the default class) and both took 0.6 s in the 2026-10-03 gate — they are three
# `os.listdir`s and a byte compare, and all of their cost is in
# `bootstrap-stage3-transitive`. A known failure that is cheap runs, so that its
# anti-rot ("marked expect= but it PASSES") is alive on every gate; `disabled=`
# would buy nothing here and cost the machine a reservation to be told what the
# doc already says. The markers state NO count on purpose: 87 diffs / 256
# mismatches is a census of a class that shrinks as it is fixed, and a marker
# that pinned a number would fire the moment one file was repaired.
test('bootstrap-verify', [PY, 'tools/bootstrap_verify.py'],
     deps=['bootstrap-stage3-transitive'],
     expect=SELFHOST_STAGE2_EMPTY_DUMP,
     desc='stage1 == stage2 == stage3 for every generated file')
test('bootstrap-validate', [PY, 'bootstrap-validate.mojo'],
     deps=['bootstrap-stage3-transitive'],
     expect=SELFHOST_STAGE2_EMPTY_DUMP,
     desc='bootstrap-validate.mojo over the three stage trees')

# ── formal ───────────────────────────────────────────────────────────────────
# ── the Lean library, built ONCE and made a dependency ──────────────────────
# lib/ProofLib.olean is 27MB and takes ~80s to produce, and EVERY
# proof-checking path reaches `formal.lean.ensure_library`, which is a
# check-then-act on a shared filesystem. Run 16 of those concurrently — which
# is exactly what the proofs bucket does at -j18, since eight registered
# tests between them drive test_formal.py, test_formal_sweep.py and the four
# test_x86_64_* sub-suites — and on a cold content-addressed store every one
# of them misses the stamp, misses the cas, and starts its own `lean -o` on
# the SAME output path. Measured here before the fix: 3 concurrent callers,
# 3 simultaneous builds, peak 3 `lean` processes, all done at ~81s. Sixteen
# is sixteen. It is also a correctness hazard, not just a waste: concurrent
# unsynchronised writes to one .olean can interleave into a truncated file
# that every later typecheck then reads.
#
# Two fixes, and the second is this one. `formal/lean.py` now builds under an
# exclusive flock with the currency check repeated inside it, and writes via
# a private temp + os.replace, so concurrent callers cannot duplicate or
# corrupt a build (that is what makes the mechanism safe for ANY number of
# callers, including two humans and a fanout inside one test). This test is
# the other half: the lock still makes the 15 latecomers QUEUE, so the
# library is built as its own step, once, alone, before the proof fan-out is
# released — and the other 15 then find the stamp valid and return in
# ~0.1s without contending at all.
#
# Not `cache=True` on purpose: the .olean is already content-addressed twice
# over (the cas publish inside ensure_library, and the .srcsha256 stamp that
# makes a repeat run a stat rather than a hash), so a suite-level artifact
# cache would be a third cache in front of two that already work — and
# would go stale in a new way when the cas is shared between checkouts.
# `mem='module'`, and it is the one job the ratchet could not move: there is no
# measurement for it (it is UNMEASURED, and the peak table in the run log is
# what would replace this sentence). Every other unnamed job in the registry is
# a python check over snippet-sized programs, which is what `small` describes;
# this one hands the job to LEAN, whose 27 MB .olean is a real typechecker's
# real memory and is the only external tool in the everyday registry that this
# repo has no measurement for at all. A RESOURCE verdict here is not forgiven by
# anything (`expect` forgives FAIL and ERROR), and `prooflib` is a `deps` of the
# whole proofs bucket, so a ceiling that fired would SKIP sixteen proof runs
# and report a passing gate. `module` is the "we do not know, and it is not
# snippet-sized" answer — which is why it is the one job here that carries a
# `memwhy` and no number behind it.
test('prooflib', [PY, '-c',
                  'import os, formal.lean as L; '
                  'L.ensure_library(L.find_lean(), '
                  'os.path.join(L._default_root(), "lib"))'],
     mem='module', timeout=2400, dep=True,
     memwhy='unmeasured: the only job in the registry run by an EXTERNAL tool '
            '(Lean, a 27 MB .olean), so there is no peak to size a class from '
            'and `module` is the standing guess. Over the 4 GB line because we '
            'do not know, not because 24 GB was measured — one `make gate` '
            'replaces this with a number. See ' + MEM_DEBT_DOC,
     desc='build lib/*.olean once — 27MB, ~80s, and 16-way duplicated '
          'without this step. `dep=True`: a DEPENDENCY, not a test — see the '
          'field in `Spec`, and `test_suite.py` checks that it is the only '
          'registration allowed to be in no bucket')

# The eight gate tests that typecheck generated Lean were `disabled=` against
# `“The formal Lean proof checks in the gate have no time bound”` from 2026-10-02 to
# 2026-10-03, and the markers are gone.  The doc named two conditions and both
# are met:
#
#   1. ONE launcher bounding every Lean run in wall AND cpu, killing the
#      process tree, and reporting a breach as its own verdict rather than a
#      pass -- `formal/lean.py::run_lean`, `PROOF_WALL_S`/`PROOF_CPU_S` = 1500 s
#      from the measured slowest legitimate proof (297.8 s / 219.2 s,
#      `formal/examples/udivmod.mojo`).  `FORMAL.md` §12 is the policy.
#   2. The looping obligation found.  It was the per-export dylib contract: a
#      fourteen-fold nest of the runner's own `if pc = pc then .. else ..`
#      around the whole composed `Arm64State`, which `bv_decide`'s internal
#      normalisation cannot be configured out of, and three budgets were
#      measured failing to fire (`FORMAL.md` §12,
#      `bugs/FORMAL_dylib_export_loops_and_frame_bounds.md` §1).
#      `formal/arm64_proof_gen.py` now
#      emits the `if` resolved for every step it knows moves no pc, and keeps
#      it only for the closing `ret`, which `BlockCert` genuinely cannot
#      resolve.  Measured on the generated `triple` proof: 9.0 s wall /
#      14.4 s CPU / 1.63 GB peak, rc 0, 0 holes -- against "did not finish"
#      (177 s CPU in 80 s wall before `RLIMIT_CPU` fired).
#
# What re-enabling them is NOT is a measurement of all eight by the change
# author, and the honest split is worth keeping: `formal-dylib` is measured
# (14 PASS / 0 FAIL, `python3 test_formal_dylib.py`, and it is the one test
# the change can affect), `formal` and `formal-x86` are measured per example
# by `FORMAL.md` §12 (8.6 s - 297.8 s each, 1.5-3.0 GB), and
# `formal-call-proofgen`, `formal-imports`, `formal-sweep`,
# `formal-x86-endtoend` and `formal-x86-model` were NOT re-measured -- a light
# worker may not run `formal-sweep`, and `formal/x86_64_model_coverage_test.py`
# and `formal/x86_64_endtoend_test.py` write outside this worktree.  Those five
# run the same `run_lean` bounds as the 33 sibling tests in `proofs` that were
# never disabled, which is the argument for expecting them green; it is not the
# same as having seen them green.
test('formal', [PY, 'test_formal.py'], j=True,
     deps=['preflight', 'prooflib'],
     desc='every formal/examples/*.mojo typechecks its generated Lean proof')
test('formal-run', [PY, 'test_formal_run.py'], deps=['preflight'],
     desc='formal arm64 executables that actually build AND run (no lean)')
# Module-global state. Its own file rather than more rows in `formal-run`
# because it is the only formal test that runs each case THREE ways — the two
# backends' images plus the Mojo interpreter — and that is the assertion: a
# module global's correctness depends on a codegen, a linker and a segment
# agreeing about one address, and no single-backend run can see a disagreement
# between two codegens. It was worth its own file that it found three
# x86-64-only instruction-encoding bugs (`jne rel32` with a spurious ModRM, a
# `jne` guarding on flags `mov` never set, and the initializer flag stored
# before its value was in it) — all of which presented as a crash somewhere
# else entirely.
test('formal-globals', [PY, 'test_formal_globals.py'], deps=['preflight'],
     desc='module-global state: image + interpreter agree, on both backends')
# `deps=['preflight', 'prooflib']` and NOT in `check`: half this file's
# assertions are "Lean accepts the generated file", and without `prooflib` they
# SKIP -- which would be a silent coverage hole of exactly the kind `prooflib`
# exists to prevent. It is in `proofs` rather than `check` because that is the
# bucket whose members pay for the 27 MB library build, and CLAUDE.md is
# explicit that `make check` and `make gate` must not.
#
# No `cache=True`, deliberately: `formal/lean.py`'s `check_proof_cached` already
# memoises Lean verdicts on a key that digests the proof bytes AND the .olean
# files, which is strictly finer than anything a suite-level cache could key on.
# A second cache in front of that one could only add a way to go stale.
#
# The lib/*.lean entries in `extra` are not decoration. Agent [3]'s rewrite of
# lib/ changed what every generated proof typechecks against, and a test that
# generates its own proofs inside the run does not need the key to notice --
# but the recorded-PASS path does, and that is where a library change would
# have been served stale.
test('formal-call-proofgen', [PY, 'test_formal_call_proof_gen.py'],
     deps=['preflight', 'prooflib'], timeout=1200,
     extra=['test_formal_call_proof_gen.py', 'fire_compiler.py',
            'formal/arm64_proof_gen.py', 'formal/x86_64_proof_gen.py',
            'formal/arm64_codegen.py', 'formal/build.py', 'formal/lean.py',
            'formal/types.py', 'lib/ProofLib.lean', 'lib/Refine.lean',
            'lib/X86.lean', 'lib/work.lean'],
     desc='proof generation on programs that CALL: a call must not raise, the '
          'model must be the model of the call, and no declaration may be '
          'vacuous')
# `mem='tiny'` (4 GB) from a MEASURED peak, not from the shape of the workload.
# `test_formal_dylib.py` peaked at 1.7 GB across the process tree on
# 2026-10-03 (`python3 tools/memslot.py --gb 8 -- python3
# test_formal_dylib.py`, 14 PASS / 0 FAIL), of which the one Lean run is 1.63 GB
# -- the same figure the generated `triple` proof reports through `run_lean`.
# `small` was the unmeasured default, so this releases 4 GB of the machine's
# 96 GB budget for every claim on the job.
test('formal-dylib', [PY, 'test_formal_dylib.py'],
     deps=['preflight', 'prooflib'],
     mem='tiny',
     desc='formal dylib emission, Mach-O re-read, dlopen, prove')
test('formal-imports', [PY, 'test_formal_imports.py'],
     deps=['preflight', 'prooflib'],
     desc='formal import surface')
# The hostmod claim: `ast` left HOST_MODELLED, and this is what says the module
# behind it is CPython's tokenizer rather than a plausible one — every case run
# through the built arm64 image AND through this process's `tokenize`, with the
# known parse gaps PINNED rather than skipped. In `check` and not in `proofs`
# because it needs no `prooflib` (it asserts without Lean) and costs about four
# seconds, which is the same class as the other two formal claims in that
# bucket: `formal-link-accounting` says the NAME left the host set, this says
# the module that replaced it is right.
test('formal-ast', [PY, 'test_ast_formal.py'],
     deps=['preflight'],
     desc='formal/hostmods/ast.mojo tokenizes and validates like CPython\'s')
# No j=True: test_formal_sweep.py is a plain unittest.main() and has no -j of
# its own, so forwarding one makes it exit 2 on "unrecognized arguments".
# `j` is a claim about the tool, not a request — test_formal.py, which does
# parse -j, keeps it above.
test('formal-sweep', [PY, 'test_formal_sweep.py'],
     deps=['preflight', 'prooflib'],
     desc='the formal sweep')
# The two suites that pin the reach claims and the bind audit.  Unregistered
# until now, and the second is the one standing between a real backend defect
# and a `codegen` misclassification on the executable path, so its absence
# from the gate was the gap worth closing.  Neither needs `prooflib` to do
# anything: the one case that wants a library census SKIPs loudly without it.
test('formal-sweep-truth', [PY, 'test_formal_sweep_truth.py'],
     deps=['preflight'],
     desc='the sweep, measured against the interpreter: no invented coverage')
test('formal-link-accounting', [PY, 'test_formal_link_accounting.py'],
     deps=['preflight'],
     desc='every bound symbol is accounted for, on every container format')
# `formal/hostmods/re.mojo` against CPython's own `re`: 112 patterns, eight
# sections each, every integer compared.  In `proofs` rather than `check` for
# the reason it is slow and not the reason it is fast: it builds and EXECUTES
# ~140 arm64 images, and a suite that only checked the interpreter would miss
# the whole class of bug this one exists for (a silently wrong span is
# indistinguishable from a right one to anything downstream).
test('formal-re', [PY, 'test_re_formal.py'],
     deps=['preflight'],
     extra=['test_re_formal.py', 'formal/hostmods/re.mojo',
            'formal/hostmods/os/_syscalls.mojo', 'formal/imports.py'],
     desc='the `re` host module, span for span, against CPython')
# The gimple runtime's C library on a formal link line, and the three-way
# split a `mojo_*` call now takes: linked, refused for its TYPES, and refused
# because this library does not export the name. In `proofs` rather than
# `check` because it builds ~20 images across both architectures and needs
# `otool`; no `prooflib` dep because it asserts without Lean.
test('formal-runtime-link', [PY, 'test_formal_runtime_link.py'],
     deps=['preflight'],
     desc='the mojo_* runtime library is on a formal link line, and what is still refused')
# output/x86_64/ keeps these from colliding with the arm64 verdicts above, so
# they can share the machine with them.
test('formal-x86', [PY, 'test_formal.py', '--backend', 'x86_64'], j=True,
     deps=['preflight', 'prooflib'],
     desc='the x86-64 examples, built and proof-checked')
test('formal-x86-endtoend', [PY, 'formal/x86_64_endtoend_test.py'],
     deps=['preflight', 'prooflib'],
     desc='x86-64 whole run, every input, no sorry')
test('formal-x86-model', [PY, 'formal/x86_64_model_coverage_test.py'],
     deps=['preflight', 'prooflib'],
     desc='every byte the x86-64 emitter can produce is a step the model can step')
# The check that `lib/X86.lean` is a MODEL of the machine rather than a
# well-typed program: it builds every `formal/examples/*.mojo` for x86-64, RUNS
# each image under Rosetta, runs the same bytes through `x86_exec_exit` in the
# Lean interpreter and compares the value left in RAX. A machine model that has
# only been typechecked proves nothing — every definition in it is trivially
# well-typed — so this is the only thing on `lib/X86.lean` that can fail, and
# it ran by NOTHING: the file is spelled `*_test.py`, and the estate check's
# walk only counted `test_*.py`, so it was in no spec and in no `UNREGISTERED`
# (“The estate check only sees files named `test_*.py`”).
#
# `tiny` from a MEASUREMENT, not from the shape: one run alone under
# `tools/memslot.py --gb 8`, 1.4 GB peak across the whole tree (`procrun`'s own
# RSS poll), ~20 min wall — 45 sequential formal builds, 45 Rosetta runs, then
# ONE `lean` invocation `#eval!`-ing all 180 runs. `1.5 x 1.4 = 2.1`, so the
# ratchet picks `tiny` (4 GB) and the floor class covers the peak 2.9x. A class
# assigned from "it builds 45 images and runs Lean" would have been `stage` (96
# GB), which is a machine-wide reservation for a job whose measured peak is
# under a third of the cheapest rung.
#
# It is RED, and deliberately `expect=`-marked rather than left unregistered:
# `udivmod` disagrees with the hardware (real 4, model 7905747460161236410).
# A model bug on a file that has been running by nobody for as long as it has
# existed is exactly what an `expect=` marker is for — it says WHAT is red
# instead of leaving the file invisible. Fix the model and the marker flips
# loudly.
test('formal-x86-machine-model', [PY, 'formal/x86_64_model_test.py'],
     deps=['preflight', 'prooflib'], mem='tiny',
     extra=['formal/x86_64_model_test.py', 'formal/x86_64.py', 'lib/X86.lean'],
     expect='1 of 45 WRONG: udivmod — the x86-64 machine model returns '
            '7905747460161236410 where the hardware returns 4 '
            '(bugs/CODEGEN_x86_model_udivmod_disagrees_with_hardware.md). '
            'Found by running this file for the first time, 2026-10-02.',
     desc='lib/X86.lean EXECUTED against the hardware it models, every example')

# ── the formal host modules: built, EXECUTED, diffed against CPython ────────
# Eight test files that build a formal image per case and RUN it, comparing the
# answer with CPython's own rather than with a table of expected values. On
# 2026-09-30 they were named by no registered spec and were in no bucket, which
# is the defect CLAUDE.md tells `coro` about: the coro runtime was renamed
# `mojo_*` -> `fire_*` and 20 cases failed to compile for two rounds while
# nothing noticed, because the estate check that should have noticed was itself
# in no bucket. These eight are the same failure in a quieter form — eight
# claims about the formal backend, every one of them unbacked, and every one of
# them building and RUNNING images that nothing was executing.
#
# `mem='tiny'` on all eight, from MEASURED_PEAK_GB rather than from the shape
# of the workload. That shape is "builds a compiler and links it", which the
# ladder once answered with `module` (24 GB) and would answer with `stage`
# today; what it actually costs is 41-213 MB, because a case is a snippet and
# the snippet is the only thing the tree ever holds. Eight reservations of
# 24 GB would have admitted four of them at a time out of a 96 GB budget, to
# protect work measured at 0.06 GB.
#
# No `cache=True` on any of them, and the reason is the one `formal` and
# `formal-call-proofgen` already give: `fire.py build --formal` writes through
# the content-addressed store, so the expensive part — the generated C and the
# object — is already memoised on the content that produced it. A second cache
# in front of that one can only add a way to go stale. The `extra` lists are
# still written down, because they are the honest answer to "what changes this
# verdict" and they are what makes a future `cache=True` correct rather than
# wrong.
FORMAL_BUILD_INPUTS = (['fire.py', 'fire_main.py', 'fire_compiler.py',
                        'module_loader.py', 'reflect.py']
                       # The formal driver reaches the gimple tier through
                       # `module_loader`, whatever `fire.py`'s comment about
                       # isolation says, so an edit under mojo/ can change what
                       # these eight observe. Measured, not assumed: the repo
                       # modules a `fire.py build --formal` run really loads are
                       # fire_compiler, formal/*, module_loader, reflect and
                       # the whole gimple tier.
                       + GIMPLE_SOURCES)

# `os` and `os.path`, against the `posixpath`/`genericpath` they are a
# transcription of — 436 string answers, 75 real filesystem operations, 13
# environment answers, 22 constants, every one of them asked of CPython rather
# than stated. In `check` as well as `proofs` because it is the cheapest
# coverage in this group by an order of magnitude (4.2 s, 0.06 GB, 546
# assertions) and a transcription is exactly the kind of thing that is right on
# the inputs you tried.
test('formal-os', [PY, 'test_formal_os.py'], mem='tiny', deps=['preflight'],
     extra=['test_formal_os.py', 'formal'] + FORMAL_BUILD_INPUTS,
     desc='os and os.path built, run, and diffed against CPython\'s posixpath')
# `sys`, and with it the module-call lowering: a dotted name crossing a dylib
# boundary, a `str` coming back as a string rather than as a pointer's own
# value, and a module calling another module. 6.8 s.
test('formal-sys', [PY, 'test_formal_sys.py'], mem='tiny', deps=['preflight'],
     # `test_formal_dylib.py` because this file imports its Mach-O re-reader
     # and its `check`, and `tools/formal_sweep.py` because two of the twelve
     # cases are about how the sweep CLASSIFIES a sys refusal. Both are inputs
     # in the plain sense: edit either and this file's answers change.
     extra=['test_formal_sys.py', 'test_formal_dylib.py', 'tools/formal_sweep.py',
            'formal'] + FORMAL_BUILD_INPUTS,
     desc='sys: the module-call lowering, both backends, and a real string back')
# `len()` where the operand is a struct FRAME ADDRESS. It has to be
# `h.__len__()`, not a count-word load, and the slot at offset 0 of a frame is
# the struct's first field — so the wrong lowering produces a plausible number
# meaning nothing. 5.2 s.
test('formal-frame-len', [PY, 'test_formal_frame_len.py'], mem='tiny',
     deps=['preflight'],
     extra=['test_formal_frame_len.py', 'formal'] + FORMAL_BUILD_INPUTS,
     desc='len() on a frame address is the struct\'s own __len__')
# `time`, where a table of expected values would be a table of numbers that
# were right when it was written: every case is a RELATION against this
# process's own clock, and the one exact case (ns -> double) is checked against
# exact rational arithmetic because CPython's `ns / 1e9` double-rounds. 5.3 s.
test('formal-time', [PY, 'test_formal_time.py'], mem='tiny',
     deps=['preflight'],
     extra=['test_formal_time.py', 'formal'] + FORMAL_BUILD_INPUTS,
     desc='time: clocks as relations, and the ns->double conversion exactly')
# `argparse`, where the oracle is CPython's own argparse on 63 cases across 11
# parsers, each built as an arm64 image and run. The most expensive of the
# eight (43 s, and the only one over 0.1 GB) because it is the only one that
# builds eleven images; `proofs` rather than `check` for that reason, and
# because 43 s of image building is not what the everyday inner loop is for.
test('formal-argparse', [PY, 'test_formal_argparse.py'], mem='tiny',
     deps=['preflight'],
     extra=['test_formal_argparse.py', 'test_formal_dylib.py',
            'tools/formal_sweep.py', 'formal'] + FORMAL_BUILD_INPUTS,
     desc='argparse: 63 parses, 11 parsers, each run against CPython argparse')
# `hashlib`, and with it the only export in the tree with real arithmetic in
# it: BLAKE2b is computed from scratch in `formal/hostmods/hashlib.mojo`,
# because libSystem has none. 1128 digests byte-exact, over every message length
# from 0 to 139 and six digest sizes.
#
# `timeout=1800` is the one number here that is not a class. This job took 390 s
# on a cold content-addressed store and 36 s warm, and the cold figure is the
# one a fresh clone or a cleared `~/.gmojo/cas` pays; the runner has no default
# timeout, so without this a wedged build is unbounded.
test('formal-hashlib', [PY, 'test_formal_hashlib.py'], mem='tiny',
     deps=['preflight'], timeout=1800,
     extra=['test_formal_hashlib.py', 'formal'] + FORMAL_BUILD_INPUTS,
     desc='hashlib: sha/md5 from libSystem and BLAKE2b from scratch, byte-exact')
# `struct`, the module every Mach-O and ELF header in this tree is written
# through, and the reason its test compares BYTES rather than counting them: a
# subtly wrong byte packer produces a malformed binary that still links.
#
# GREEN, and it was registered RED. It carried
# `expect='“`struct.pack` for a format naming 8 values was refused at the CALL SITE” …'` because the two
# 8-value formats produced a 9-argument `pack()` call, which a formal arm64 call
# cannot make — the call was refused above `struct.mojo`'s own "return an empty
# list" decline, so the decline was unreachable. That test now hands the call
# exactly the five values the module has slots for, on the measured ground that
# the module answers the FORMAT it was given (`_nvalues(fmt)`) rather than the
# number of arguments that arrived, so "five supplied, more wanted" is exactly
# the state under test. Both ABIs have since grown their stack-argument
# convention, so the wall that doc pointed at is gone and the doc with it.
#
# `proofs` and not `check` for a reason the solo number hides: 43 s alone, and
# 201 s measured in a `-j4` run beside the other seven (it is 154 checks, most
# of them a build). A job's cost in a bucket is its cost beside the others, and
# that is the number the everyday loop would have paid.
#
# 154 and not 148 because `test_struct_formal.py` now carries a harness
# self-test (`test_the_harness_records_a_case_even_when_it_cannot_pass`, six
# checks, one of them a real build). It is there because the file's own total
# used to move with its own verdicts — 122, 127, 144, 145, 147, 148 across six
# runs of one tree — which is a suite a reader learns to re-run, and a re-run
# that comes back green is not evidence. Every case now costs a fixed number of
# checks whatever happened to it, so the denominator is a function of the cases.
test('formal-struct', [PY, 'test_struct_formal.py'], mem='tiny',
     deps=['preflight'],
     extra=['test_struct_formal.py', 'formal'] + FORMAL_BUILD_INPUTS,
     desc='struct: calcsize/pack/pack_into byte-for-byte against CPython struct')
# A module's top-level statements RUN. A file whose whole body was
# `import sys; sys.exit(3)` used to build, link, pass the symbol-bind audit
# and exit 0: every statement outside a `FunctionDef` was dropped without a
# diagnostic. That bug is closed and its doc deleted (6ad8efd5), so the
# durable record is this file, and its cases build the image, EXECUTE it, and
# compare stdout and exit status with CPython on the same text.
#
# The `expect=` this row carried (`FORMAL_toplevel_body_struct_construction_no_
# longer_refused.md`, 2 of 70) is gone with the two rows it described: the
# stale `case_refused` for a construction the backend inlines is now a
# build-and-RUN case plus the class-default case beside it, and the second
# row was a rewording of `name_in_function`, which `case_refused_without:`
# now pins in the direction a needle-only assertion cannot see.
test('formal-toplevel', [PY, 'test_formal_toplevel.py'], mem='tiny',
     deps=['preflight'],
     extra=['test_formal_toplevel.py', 'tools/formal_sweep.py',
            'formal'] + FORMAL_BUILD_INPUTS,
     desc='a module body runs: built, executed, and diffed against CPython')

# ── the formal backend's other three unregistered files, same shape ─────────
# Registered here rather than beside the eight above because they were not part
# of that count: they arrived on master AFTER it, each with a merged branch
# behind it, and the unregistered-test-files hole (closed and deleted with
# this) is the one they walked through one file at a
# time. `mem='tiny'` for the same reason the eight have it, and `proofs` rather
# than `check` because none of the three is in the everyday inner loop.

# `@dataclass` as a COMPILE-TIME transform: the annotation is read by the build
# and the generated `__init__`/`__repr__`/`__eq__` are emitted, so the test
# builds each case as an image, RUNS it, and compares with a CPython class using
# the same decorator. 50 checks, 11.9 s, 0.10 GB.
test('formal-dataclasses', [PY, 'test_dataclasses_formal.py'],
     mem='tiny', deps=['preflight'],
     extra=['test_dataclasses_formal.py', 'formal/dataclass_transform.py',
            'formal/build.py', 'formal/imports.py', 'formal/arm64.py',
            'formal/arm64_codegen.py', 'formal/model.py'] + FORMAL_BUILD_INPUTS,
     desc='@dataclass as a compile-time transform, against CPython')
# `mod.NAME`: a call, a RE-EXPORTED call, a submodule chain, and a module-level
# constant, each built for both architectures and run — plus the three shapes
# that must stay refused, each with a message that names its own reason, and the
# manifest that is the contract between the two. 18/18. 10.3 s, 0.07 GB.
#
# GREEN, and the marker is gone rather than relaxed: the one red case was a
# bracketed call to a private name, refused as a specialization whose brackets
# have nowhere to bind rather than as the export gap it is. The export rule is
# asked first now for a bracketed callee whose base name the defining module
# does not publish, so the two facts are told apart by the link line instead of
# being conflated (`formal/build.py`'s `_bracketed_export_gap`); a bracketed
# callee the module DOES publish keeps the brackets' own refusal, which is the
# sentence that is true of it.
test('formal-module-attr', [PY, 'test_formal_module_attr.py'], mem='tiny',
     deps=['preflight'],
     extra=['test_formal_module_attr.py', 'formal/model.py',
            'formal/imports.py'] + FORMAL_BUILD_INPUTS,
     desc='mod.NAME: calls, re-exports, chains, constants and attribute '
          'reads, on both backends')
# The REAL syscalls behind the `os` host module — the `_syscalls.mojo` layer and
# the images it builds — against the machine rather than against a table: 51
# cases (the file's own tally says so, and it is printed), on BOTH
# architectures, with CPython as the arbiter of every answer. The x86-64 half
# used to SKIP, for a reason that was false — "an `os` dylib that calls the C
# library is arm64-only on this backend", citing a bug doc that does not exist —
# and that skip is why a silently wrong `os.listdir` and a silently wrong
# `os.stat` survived on x86-64 (formal/model.py's `target_libc_symbol` is what
# binds the C names macOS spells twice; see the `formal-os-backing` cases'
# own commit). One case is still arm64-only and says why: the x86-64 backend
# refuses an augmented assignment through a subscript.
test('formal-os-backing', [PY, 'test_formal_os_backing.py'], mem='tiny',
     deps=['preflight'],
     extra=['test_formal_os_backing.py', 'formal/hostmods/os/_syscalls.mojo',
            'formal/model.py', 'formal/imports.py'] + FORMAL_BUILD_INPUTS,
     desc='the syscalls under the os host module, through real images')

# ── the ten the batch merge left unregistered ──────────────────────────────
# `suite-self-test`'s estate check is red with exactly these ten, and every one
# of them arrived in the batch that the integrator merged in one commit
# (`0aaf9806`, `git log --merges master..HEAD`) with a merged branch behind it
# and no registration. That is the same unregistered-test-files hole,
# opened and closed, walked through again one file at a time — which is what the check
# is FOR, and this paragraph is the receipt: it fired on the batch rather than
# on the next reader.
#
# Registered, not excused. `UNREGISTERED` in `test_suite.py` exists for a file
# that genuinely is not run, and every one of these is a build-and-RUN suite
# against CPython, so declaring ten of them unaccounted-for would be the estate
# check's own failure mode repeated on purpose. `mem='tiny'` because that is what
# they measure (0.065-0.373 GB, the table below), and `proofs` rather than
# `check` because they are not the everyday inner loop: `formal-json` alone is
# 31 s, and the rest are 1-15 s each.
#
# Peaks are MEASURED, not inferred from the shape, because the ratchet in
# `test_suite.py` compares each class against its recorded peak and a class is
# also a machine-wide reservation (`tools/memslot.py`). Measured one at a time on
# 2026-10-01 on this tree, each under `tools/memslot.py --gb 8`, with the peak
# read by polling `procrun.tree_rss` every 50 ms — the same instrument
# `tools/memcap.py` enforces its ceiling with, at a finer interval, because
# memcap's own report rounds to 0.1 GB and eight of these ten are under it.

# `external_call["sym", RetType](...)`: the construct that was the terminal
# refusal behind the largest single family in the sweep residue. 30 cases, and
# the needle half of the file is as load-bearing as the answer half: a refusal
# that stops being made is a wrong program, so both directions are pinned.
#
# NOT red any more. It carried `expect=` for one case — `env_round_trip`, which
# declares its `getenv` return type as `_CPointer[UInt8, UntrackedOrigin[mut=False]]`,
# where the tuple subscript in THAT ANNOTATION was refused as a value subscript
# before the `external_call` itself was ever read. The construct was right and
# it was being asked the question at the wrong moment: `model.type_position_nodes`
# now tells the module-symbols walk which brackets sit in a TYPE position, so it
# stops asking what they mean at runtime.
# NO `expect=`, and its removal is the anti-rot working rather than a coverage
# hole: this row carried one for two cases (`a_nested_bracket_in_the_type_
# argument_is_not_a_tuple_index` and `env_round_trip`, the same construct
# asked at two moments) and the merged tree is `PASS=45 FAIL=0`, because
# `formal/model.py`'s `type_position_nodes` now tells the module-symbols walk
# which brackets sit in a TYPE position instead of asking what they mean at
# runtime. A marker on a passing test is reported as a FAILURE, so it had to go;
# and the doc it cited was gone already, which is the other half of the same
# signal (`FORMAL_external_call_a_multiparameter_type_in_the_bracket`
# is not in the tree, and `suite-self-test`'s "every bug doc a registered
# reason cites exists" is what said so).
test('formal-external-call', [PY, 'test_formal_external_call.py'],
     mem='tiny', deps=['preflight'],
     extra=['test_formal_external_call.py', 'formal/build.py',
            'formal/model.py', 'formal/imports.py'] + FORMAL_BUILD_INPUTS,
     desc='external_call[sym, RetType]: both the answers and the refusals')
# The ELEVENTH of the section above, and the first one to arrive with a merge
# rather than with a batch: `work/formal8-4` added `test_formal_typed_flag.py`
# and neither registered it nor excused it, so `suite-self-test`'s estate check
# ("every test file is run by something, or says why not") was red on the merge
# of that branch. Registered rather than excused, for the reason the section
# above gives — it is a real test and it passes, and an `UNREGISTERED` entry for
# it would be the estate check's own failure mode repeated on purpose.
#
# It is also the CHEAPEST test in this section by an order of magnitude, which
# is why it is here rather than in `check`: it reads `formal/model.py`'s
# `uses_typed_model` flag over `formal/examples/` and prints the table — no
# build, no image, no Lean. Measured 2026-10-03 on this tree under
# `tools/memslot.py --gb 8`, peak read by polling `procrun.tree_usage` every
# 20 ms: **0.033 GB, 0.64 s wall**. `mem='tiny'` from that peak and not from
# the shape. `proofs` rather than `check` to stay with its neighbours; it is
# cheap enough that either is defensible and it is not worth the second argument.
test('formal-typed-flag', [PY, 'test_formal_typed_flag.py'],
     mem='tiny', deps=['preflight'],
     extra=['test_formal_typed_flag.py', 'formal/model.py', 'formal/types.py',
            'formal/build.py'],
     desc="the `typed` model flag: one definition, and not vacuous")
# `json`: RFC 8259 on the formal backend, every case computed twice — once
# through `fire.py build --formal` and executed, once through this process's own
# `json` — because a table of digests is a table that is wrong the moment
# someone transposes a character, which is the one mistake a byte-oriented
# module cannot be allowed to make. 10 groups, 31 s, and the largest peak of the
# ten (0.373 GB, still `tiny`).
test('formal-json', [PY, 'test_formal_json.py'], mem='tiny',
     deps=['preflight'],
     extra=['test_formal_json.py', 'formal/hostmods/json.mojo',
            'formal/build.py', 'formal/model.py',
            'formal/imports.py'] + FORMAL_BUILD_INPUTS,
     desc='json: RFC 8259 built, run, and diffed against CPython\'s json')
# `pathlib`, and the `PurePosixPath` half of it: a module whose every answer is
# short, which is exactly what makes a table of them dangerous — `name`, `stem`
# and `suffix` differ from each other by one rule each, and a transposed row in
# a table of expected values looks like a pass.
test('formal-pathlib', [PY, 'test_formal_pathlib.py'], mem='tiny',
     deps=['preflight'],
     extra=['test_formal_pathlib.py', 'formal/hostmods/pathlib.mojo',
            'test_formal_json.py', 'formal/build.py',
            'formal/model.py'] + FORMAL_BUILD_INPUTS,
     desc='pathlib: the pure half of PurePosixPath, against CPython\'s pathlib')
# A method parameter's field, established by its DECLARED type and nothing else.
# A method's other parameters were never seeded as frame holders, so
# `other.start` in `Slice.__eq__` read a slot nothing had written — and the
# neighbouring case that must STAY refused, a struct's frame where a one-field
# struct is declared, is in the same file because the two are one decision.
test('formal-method-param-field', [PY, 'test_formal_method_param_field.py'],
     mem='tiny', deps=['preflight'],
     extra=['test_formal_method_param_field.py', 'formal/build.py',
            'formal/model.py'] + FORMAL_BUILD_INPUTS,
     desc='a method parameter\'s field, from its declared type')
# A frame address at an ARGUMENT position of a comptime-specialized call —
# `f[T](r)` — which is not a method call at all, so none of the receiver-handoff
# family covers it.
#
# RED, and registered red rather than excused. 2 of 12, and BOTH are the same
# direction: a construct with no representation now BUILDS instead of being
# refused, once on the return side and once on a value-only callee reached
# through a specialization. A built image here is a wrong program (measured: the
# return case exits 0 where the source's answer is 7, and the callee case exits
# 8, which is a frame address read as an integer), so this is a real gap and not
# a stale expectation; see
# bugs/FORMAL_a_specialization_defeats_the_frame_escape_refusals.md.
test('formal-receiver-position', [PY, 'test_formal_receiver_position.py'],
     mem='tiny', deps=['preflight'],
     expect='bugs/FORMAL_a_specialization_defeats_the_frame_escape_refusals.md '
            '— 3 of 14: TWO of them are that doc — a specialized call with a '
            'frame address at an argument position bypasses both the '
            'returned-frame and the value-only-callee refusals and builds — '
            'and the THIRD is a different defect wearing this test: '
            '`refuse_a_dotted_specialized_callee_names_it` stops at a '
            'module-state refusal (`Box` has no home) before reaching the '
            'specialization refusal its needle wants, so it belongs to the row '
            'in bugs/FORMAL_module_state_no_storage.md. The leading number is '
            'the TOTAL and it is checked against the run, because a marker '
            'that forgives FAIL wholesale absorbs a new failure silently. '
            'Measured 2026-10-01; the marker said "2 of 12" until then and '
            'nothing could see the difference until 2026-10-01, when the '
            'stated count in an `expect=` reason became checkable against the '
            'run (`_apply_expectations` in this file, and its checks in '
            'test_suite.py).',
     extra=['test_formal_receiver_position.py', 'formal/build.py',
            'formal/model.py'] + FORMAL_BUILD_INPUTS,
     desc='a frame address at a specialization\'s argument position, refused')
# `io` and `typing`: four numeric constants and one function, which is the
# measurement behind why `typing` is one function — the formal backends ERASE
# annotations, so `from typing import Optional` resolves as soon as the module
# EXISTS and the name need not be in its export table at all.
test('formal-small-hosts', [PY, 'test_formal_small_hosts.py'], mem='tiny',
     deps=['preflight'],
     extra=['test_formal_small_hosts.py', 'test_formal_json.py',
            'formal/hostmods/io.mojo', 'formal/hostmods/typing.mojo',
            'formal/build.py', 'formal/model.py'] + FORMAL_BUILD_INPUTS,
     desc='io and typing, and the 38 names that must stay absent')
# A comptime SPECIALIZATION, `f[a, b](...)`, on both formal paths. The bracket
# is spelled like a subscript and both backends resolve it by flattening the
# callee to its base NAME, which is where everything that goes wrong here goes
# wrong — so the file also pins the shapes that must stay refused.
#
# The two EMITTERS are in the cache key (`extra`) because every assertion in
# this file is about what `_emit_call` decides, and the recorded PASS is
# replayed on unchanged inputs: a fix that changed only
# `formal/arm64_codegen.py` or `formal/x86_64_codegen.py` left this key
# untouched, so the suite would have reported the pre-fix PASS for a build the
# fix had just changed. Measured, not assumed — the refusals this file pins are
# raised from `_emit_call` in those two files, and `formal/build.py` +
# `formal/model.py` were the only two of the four it named.
test('formal-specialization', [PY, 'test_formal_specialization.py'],
     mem='tiny', deps=['preflight'],
     extra=['test_formal_specialization.py', 'formal/arm64_codegen.py',
            'formal/x86_64_codegen.py', 'formal/build.py',
            'formal/model.py'] + FORMAL_BUILD_INPUTS,
     desc='f[a, b](...): a specialization, and what must stay refused')
# `#kgen.param.expr<…>`: the family whose meaning is not an MLIR object at all
# but a QUESTION the build can answer. `std/sys/info.mojo` is built out of them
# and 35 of the 46 files in that family are blocked behind the construct.
test('formal-target-queries', [PY, 'test_formal_target_queries.py'],
     mem='tiny', deps=['preflight'],
     extra=['test_formal_target_queries.py', 'formal/build.py',
            'formal/model.py'] + FORMAL_BUILD_INPUTS,
     desc='#kgen.param.expr<…>: a build-time question, answered and executed')
# The value model's shapes, measured against CPython rather than pinned. Its
# `global`-write case is the one worth naming here: it was a REFUSAL until the
# batch, and it is a differential case now, because `formal-module-globals` gave
# the name a real `__DATA` slot and the refusal's premise went with it. The case
# carries that measurement and the two commits.
test('formal-value-model', [PY, 'test_formal_value_model.py'], mem='tiny',
     deps=['preflight'],
     extra=['test_formal_value_model.py', 'formal/build.py',
            'formal/model.py'] + FORMAL_BUILD_INPUTS,
     desc='the value model\'s shapes, against CPython on both backends')
# `enum` and `contextlib`, the two host modules whose whole content is one or two
# names whose answers are CPython's to give. Registered because
# `test_suite.py`'s estate check said so on the merge that brought the file:
# `test_formal_core_hostmods.py` arrived with `work/formal5-hostmods-core` and
# was named by nothing, which is the hole that check exists to close — a suite no
# gate runs cannot rot out either. Beside `formal-json` and `formal-pathlib`
# because it is the same shape (a hostmod differential, every answer computed
# twice, no `prooflib`), and `formal-link-accounting`'s `test_host_tiers` is what
# ties the two together: it requires every written `formal/hostmods/*.mojo` to
# name the test that keeps it honest, and these two were the entries it caught
# unregistered. Measured: 6 groups, 25 s, peak 0.1 GB.
test('formal-core-hostmods', [PY, 'test_formal_core_hostmods.py'], mem='tiny',
     deps=['preflight'],
     extra=['test_formal_core_hostmods.py', 'formal/hostmods/enum.mojo',
            'formal/hostmods/contextlib.mojo', 'formal/build.py',
            'formal/model.py', 'formal/imports.py'] + FORMAL_BUILD_INPUTS,
     desc='enum and contextlib: S.NAME.value/.name and nullcontext, against CPython')
# An x86-64 MODULE dylib that calls out: it must build, sign, load and RUN.
# Module dylibs are how every cross-module call reaches its definition on this
# backend, so a defect here is a whole class of link failures.
test('formal-x86-dylib', [PY, 'test_formal_x86_64_dylib.py'], mem='tiny',
     deps=['preflight'],
     extra=['test_formal_x86_64_dylib.py', 'formal/macho_linker.py',
            'formal/elf.py', 'formal/build.py',
            'formal/model.py'] + FORMAL_BUILD_INPUTS,
     desc='an x86-64 module dylib that calls out, built, signed and run')

# ── the two the estate check caught on master, 2026-10-02 ──────────────────
# The same check, the same hole, one landing later: `formal/model.py`'s CFG
# dominance fix (`f1ad7dc7`) and the ONE-rule-for-receiver change before it
# (`44e90eec`) each landed with a test file, and neither was registered, so
# `suite-self-test` went red naming exactly these two.
#
# Registered rather than excused, and the deciding number is the cost: 8.5 s
# and 2.8 s, both under 0.1 GB, so neither is anywhere near the "too expensive
# to run a known answer" line that `UNREGISTERED` exists for (the fifteen
# formal suites it already excuses build and RUN images for minutes each).
# `formal-receiver-position`, at 2 s, is the nearest registered neighbour and
# `formal-read-before-store` is the second-cheapest analysis suite in the tree.
#
# `read_before_store` is the more interesting of the two as a unit test: it
# asks the analysis directly and uses CPython as the oracle IN BOTH
# directions — a refusal must be one CPython also makes, and a non-refusal
# must be one CPython does not — so it covers shapes (`try`/`except` with a
# `return` in the `finally`, a `break` out of one arm, a wildcard `match` arm)
# that a build-and-run row would each cost a compiler invocation to reach.
test('formal-read-before-store', [PY, 'test_formal_read_before_store.py'],
     mem='tiny', deps=['preflight'],
     extra=['test_formal_read_before_store.py', 'formal/model.py'],
     desc='read-before-store dominance, against CPython in both directions')
# Every case is DIFFERENTIAL and each `this` case has a `self` twin that has
# to compute the same thing, which is what stops the file from passing for the
# wrong reason (a build that stopped taking ANY receiver would satisfy "the
# `this` case prints 31" if the two spellings were not compared). It builds
# and runs on both backends, so `FORMAL_BUILD_INPUTS` is in its key.
test('formal-receiver-spelling', [PY, 'test_formal_receiver_spelling.py'],
     mem='tiny', deps=['preflight'],
     extra=['test_formal_receiver_spelling.py', 'formal/model.py',
            'formal/build.py'] + FORMAL_BUILD_INPUTS,
     desc='a receiver spelled `this`, diffed against a `self` twin and CPython')
# `formal/imports.py`'s `HOST_OWNED_BLOBS` is the one place this tree says what
# the words of another module's pointer MEAN, and it is a declaration rather
# than something derived — `str_alloc` also returns a `malloc`'d block and the
# caller owns every word of that one, so what separates them is who frees the
# words, and a callee's own body does not say. A declaration that drifts from
# the module it describes is worse than none: the refusal it produces would
# refuse a store that is fine, or let one through that the module's `free` then
# walks as a pointer.
#
# So this one is a SOURCE check with no image in it — 30 assertions over
# `formal/hostmods/*.mojo` and the table — and the end-to-end half (the
# contract reaches a manifest, and an importer is refused by name) is
# `formal-os`'s `blob` group, which builds the real `os` dylib. The cheapest
# formal coverage in the tree and one of the two cheapest overall: measured
# 2026-10-03 under `tools/memslot.py --gb 8`, peak read by polling
# `resource.getrusage(RUSAGE_CHILDREN).ru_maxrss` over the same run: **0.036
# GB, 0.63 s wall**. `mem='tiny'` from that peak and not from the shape.
test('formal-blob-contract', [PY, 'test_formal_blob_contract.py'],
     mem='tiny', deps=['preflight'],
     extra=['test_formal_blob_contract.py', 'formal/imports.py',
            'formal/hostmods/os/__init__.mojo'],
     desc="HOST_OWNED_BLOBS is checked against the hostmods' own source")
# The two the `work/formal12-hostmods-subprocess` merge brought in, both of which
# that branch listed in `test_suite.py`'s `UNREGISTERED` with the note that the
# registering commit is the one that deletes the excuse. Registered rather than
# excused for the reason every other host-module suite here is: they build and
# RUN a formal image per group on BOTH architectures and diff every answer
# against this interpreter's own module, which is the coverage that catches a
# mirror drifting, and the deciding number is the cost.
#
# Measured 2026-10-03 one at a time under `tools/memslot.py --gb 8`, arm64 host,
# peak read by polling `resource.getrusage(RUSAGE_CHILDREN).ru_maxrss` over the
# same run: `formal-tempfile` **0.051 GB, 35.8 s** (7 groups, 128 differential
# cases), `formal-textwrap` **0.050 GB, 15.8 s** (4 groups). Both are the cost
# class of `formal-core-hostmods` (25 s, 0.1 GB) and `formal-pathlib` (15 s,
# 0.08 GB), which are both registered, so `tiny` is from the measurement.
test('formal-tempfile', [PY, 'test_formal_tempfile.py'], mem='tiny',
     deps=['preflight'],
     extra=['test_formal_tempfile.py', 'formal/hostmods/tempfile.mojo',
            'formal/hostmods/os/_syscalls.mojo', 'formal/hostmods/os/path',
            'formal/hostmods/shutil.mojo'] + FORMAL_BUILD_INPUTS,
     desc="tempfile's directory half, diffed against CPython on both backends")
test('formal-textwrap', [PY, 'test_formal_textwrap.py'], mem='tiny',
     deps=['preflight'],
     extra=['test_formal_textwrap.py', 'formal/hostmods/textwrap.mojo',
            'formal/hostmods/os/_syscalls.mojo'] + FORMAL_BUILD_INPUTS,
     desc="textwrap's dedent and indent, diffed against CPython on both backends")
# The instrument behind `bugs/FORMAL_proof_coverage_census_2026-10-03.md`, and
# only the instrument: `tools/formal_proof_breadth.py` takes 60 functions from
# this repository's own `*.py` through `compile_formal(prove=True, …)` on both
# architectures and reads Lean's verdict, and its numbers are quoted in a bug doc
# that says they will be re-quoted. So what is registered here is the check that
# those numbers stay COMPARABLE across runs — the 60 identifiers are a function
# of the tree rather than of the clock, every emitted program is a closed module
# that reads nothing it does not define, and three programs with known verdicts
# classify into the classes the census table depends on.
#
# That is 7 tests and NO Lean run, which is the point: the census's own
# Lean-dependent numbers are its ledger's business and the instrument is cheap
# and always available, so it can be checked on every change to itself.
# Measured 2026-10-03 on the merged tree under `tools/memslot.py --gb 8`, peak
# by `resource.getrusage(RUSAGE_CHILDREN).ru_maxrss`: **0.135 GB, 7.9 s**.
# `mem='tiny'` from that peak, and it is a `module`-class workload in the sense
# that matters here — 22 of the 60 items compile formal images — which is why
# `FORMAL_BUILD_INPUTS` is in its key: an edit under `mojo/` changes what it
# observes.
test('formal-proof-breadth-tool', [PY, 'test_formal_proof_breadth.py'],
     mem='tiny', deps=['preflight'],
     extra=['test_formal_proof_breadth.py', 'tools/formal_proof_breadth.py',
            'lib/ProofLib.lean'] + FORMAL_BUILD_INPUTS,
     desc='the proof-breadth census instrument: deterministic, closed, honest')
# `doc/ABI.md` §Generics on the formal path: a module declaring only
# `struct Pair[T]` has no boundary symbol, and each INSTANTIATION is one. The
# estate check named this file on `work/formal15-generic-monomorph`, and it is
# in `proofs` rather than `check` for the same reason as its neighbours
# `formal-specialization` and `formal-receiver-spelling` — it BUILDS and EXECUTES
# a multi-module program per case, on both backends, and the differential that
# makes it worth anything is against CPython running the same text. 9 s and
# 0.1 GB measured; `tiny` releases 4 GB of the machine's budget.
test('formal-monomorph', [PY, 'test_formal_monomorph.py'],
     mem='tiny', deps=['preflight'],
     extra=['test_formal_monomorph.py', 'formal/monomorph.py',
            'formal/imports.py', 'formal/build.py', 'formal/model.py',
            'monomorphize.py', 'elaborate.py', 'reflect.py'] + FORMAL_BUILD_INPUTS,
     desc="a generic's instantiations are its boundary symbols, differentially")

# ── the five the estate check named on the formal6 merge, 2026-10-03 ─────────
# The same check, the same hole, and the largest it has named at once: the eleven
# branches that merge brought in landed five test FILES
# (`test_formal_{admitted,fcntl,math,shutil,stat}.py`) with no registration and
# no entry in `UNREGISTERED`, so `suite-self-test` — registered in `check`,
# `gate` and `smoke`, and re-run for a change to ANY `**/test_*.py` — went red
# naming exactly those five and nothing else. The transcript and the reasoning
# are the two sections above; this paragraph is the receipt, for the same reason
# theirs is: a check that fires is worth a receipt, because "registered, not
# excused" is a decision somebody has to be able to audit later.
#
# Registered, not excused, and the deciding number is cost again. 7.0 s, 10.4 s,
# 10.5 s, 18.7 s and 34.5 s at 0.07-0.13 GB, against the line `UNREGISTERED`
# exists for ("minutes per job", and the formal suites it already excuses are
# minutes each). The nearest registered neighbour for the shape is
# `formal-core-hostmods` at 25 s, which is in `proofs` only, and these are the
# same kind of thing: a host module's ANSWERS, each computed twice — once
# through `fire.py build --formal` and executed, once through this process's own
# CPython — so `formal/build.py` is in the key and `FORMAL_BUILD_INPUTS` with it.
#
# `test_formal_dylib.py` and `test_formal_json.py` are in three of these keys
# because the file IMPORTS them (`run_fire`/`check`, and `Failure`), so a change
# to either changes what these observe; naming the import is the whole of the
# "one failure type, not two" discipline those two files' headers argue for.
test('formal-admitted', [PY, 'test_formal_admitted.py'], mem='tiny',
     deps=['preflight'],
     extra=['test_formal_admitted.py', 'test_formal_dylib.py',
            'test_formal_json.py',
            # The ratchet walks EVERY `formal/hostmods/` module for its count, so
            # the whole tree is this test's subject and a directory is the only
            # honest key: a named file would be a list that rots on the next
            # module. 14 contracts across 4 modules, 14 counted `sorry`.
            'formal'] + FORMAL_BUILD_INPUTS,
     desc='the ADMITTED host-contract ratchet, and everything not admitted')
# Registered rather than excused, and the measurement is why (2026-10-04, one
# at a time under `tools/memslot.py --gb 8`, arm64 host):
#
#   formal-field-walk   0.05 s, <0.05 GB   exit 0
#   formal-glob        31.8 s,  0.1 GB    `PASS=6 FAIL=0 (backends: arm64, x86_64)`
#
# Both arrived with master's formal20 batches and were in neither a bucket nor
# `UNREGISTERED`, which is what `test_suite.py`'s estate check reports — a FAIL
# on a test that is in `check`, so the tree was red in the everyday loop. The
# check asks for a declaration, and an excuse is the wrong one at this price:
# `formal-field-walk` is the cheapest test in the formal tier and pins
# `iter_statement_nodes` against the full walk, which is the difference between
# a field this struct has and two real fields sharing one slot.
#
# `proofs` rather than `check` for `formal-glob` because of what it is ABOUT,
# for `formal-tempfile`'s reason above: every group that builds an image builds
# it on BOTH backends, and 31.8 s is a third of a minute of two machines per
# gate. `formal-field-walk` builds nothing, so `check` is where it belongs —
# and it is in `proofs` too, so the bucket is the whole formal picture.
test('formal-field-walk', [PY, 'test_formal_field_walk.py'], mem='tiny',
     deps=['preflight'],
     extra=['test_formal_field_walk.py', 'formal/model.py',
            'formal/imports.py', 'formal/build.py',
            'tools/formal_field_walk_differential.py'] + FORMAL_BUILD_INPUTS,
     desc='iter_statement_nodes against the full walk, 61 statement shapes')
test('formal-glob', [PY, 'test_formal_glob.py'], mem='tiny',
     deps=['preflight'],
     extra=['test_formal_glob.py', 'test_formal_dylib.py',
            'formal/hostmods/glob.mojo', 'formal/build.py', 'formal/model.py',
            'formal/imports.py'] + FORMAL_BUILD_INPUTS,
     desc='glob: CPython\'s own glob, both backends, 6 groups')
test('formal-fcntl', [PY, 'test_formal_fcntl.py'], mem='tiny',
     deps=['preflight'],
     extra=['test_formal_fcntl.py', 'test_formal_dylib.py',
            'formal/hostmods/fcntl.mojo',
            'formal/hostmods/os/_syscalls.mojo',   # `fs_open_ro`, `fs_close`
            'formal/build.py', 'formal/model.py',
            'formal/imports.py'] + FORMAL_BUILD_INPUTS,
     desc='fcntl: flock(2) and CPython\'s whole constant surface, both backends')
test('formal-math', [PY, 'test_formal_math.py'], mem='tiny',
     deps=['preflight'],
     extra=['test_formal_math.py', 'test_formal_dylib.py',
            'formal/hostmods/math.mojo', 'formal/build.py', 'formal/model.py',
            'formal/imports.py'] + FORMAL_BUILD_INPUTS,
     desc='math: the integer-valued surface, against CPython on both backends')
test('formal-shutil', [PY, 'test_formal_shutil.py'], mem='tiny',
     deps=['preflight'],
     extra=['test_formal_shutil.py', 'test_formal_dylib.py',
            'formal/hostmods/shutil.mojo',
            'formal/hostmods/os/_syscalls.mojo',   # the 8 fs_* it calls
            'formal/build.py', 'formal/model.py',
            'formal/imports.py'] + FORMAL_BUILD_INPUTS,
     desc='shutil: copy, move, rmtree, copytree and which, over the real filesystem')
test('formal-stat', [PY, 'test_formal_stat.py'], mem='tiny',
     deps=['preflight'],
     extra=['test_formal_stat.py', 'formal/hostmods/stat.mojo',
            'formal/build.py', 'formal/model.py',
            'formal/imports.py'] + FORMAL_BUILD_INPUTS,
     desc='stat: the mode vocabulary, all 65547 modes against CPython')

# ── not the compiler: the CPU reference the Metal path is checked against ───
# `test_llm/` is a self-contained sub-project: a ~1M-parameter linear-attention
# character model in pure Python, with hand-written Metal kernels and a bench C
# program beside it, and it is what `mojo/middle/metal_ops.py`,
# `mojo/backend_gimple/device_glue.py` and `doc/GPU_OFFLOAD_PLAN.html` all cite
# as the reference their generated kernels are compared against. So it belongs
# to the tree, and `test_llm.py` is a `unittest` suite over it that nothing ran.
#
# `-m unittest <path>` rather than `python3 test_llm.py`, and the difference is
# the whole registration: the file's own `main()` TRAINS the full model and
# prints samples, which is a benchmark, not a test. Naming the path rather than
# the module name also keeps it visible to the estate check, which reads the
# `.py` in a spec's `cmd`.
#
# `check` and not `proofs`: it needs no compiler at all, so it has no business
# in the formal bucket, and 14.3 s of CPython arithmetic beside the GPU work is
# what the everyday bucket is for. 31 cases, 0.07 GB, no `deps` because nothing
# here reads a build artifact.
test('llm-reference', [PY, '-m', 'unittest', 'test_llm/test_llm.py'],
     mem='tiny', extra=['test_llm/test_llm.py'],
     desc='the pure-Python linear-attention reference model: 31 unittest cases')

# ── the A/B sweep: Make's own job server, so driver='make' ─────────────────
# Every `make` step names a class, and that is a RULE rather than a fact about
# these four: a make target's command line is not in the registry, so nothing
# can check what it runs, and `ab-clean` here is `rm -rf` while `bside` is 779
# real compiles. A `make` spec that names nothing is a spec whose ceiling
# nobody chose, so test_suite.py's coverage check refuses it.
test('ab-clean', ['ab-clean'], driver='make', mem='small',
     desc='drop aside/ bside/ ab.mk and the per-file locks')
# `program` for the AGGREGATE, and it stays there: each of these is a `make
# -j<N>` over the ~779-file corpus, and the total across N concurrent per-file
# compiles is what a ceiling on a `make` tree can see. The per-PROCESS bound is
# the one that matches "no compiler process may exceed 50 GB", and it is applied
# where the process is started: `tools/ab_run_one.py` wraps every single file's
# compile in memcap at `module` (24 GB). That per-file cap is deliberately NOT
# the fanouts' class — the two bound different things (one process vs one job's
# whole width), and giving them the same number was how `module` ended up
# meaning "24 GB, per process" and "24 GB, whole job" at once.
#
# UNMEASURED, so the ratchet does not touch them, and they are over the 4 GB
# line for that reason alone: a 779-file sweep has never been in a `gate` with
# the peak table, and one measurement of it would replace both numbers.
test('ab-aside', ['aside'], driver='make', mem='program', deps=['ab-clean'],
     memwhy='unmeasured: the 779-file A/B sweep has never run in a gate that '
            'records peaks, so the aggregate class is the standing guess (the '
            'per-file cap lives in tools/ab_run_one.py, which is a per-process '
            'bound, not this one). Over the 4 GB line because we do not know — '
            'see ' + MEM_DEBT_DOC,
     desc='per-file python-reference dumps for the whole A/B corpus')
test('ab-bside', ['bside'], driver='make', mem='program', deps=['ab-aside'],
     memwhy='unmeasured, for ab-aside\'s reason; also the one job that runs '
            '`mojoc`\'s recipe inside its own tree (`bside: ... mojoc ...`), '
            'so its class has to be at least `mojoc`\'s or that recipe takes a '
            'second reservation inside a tree the first one accounts for and '
            'the job deadlocks. See ' + MEM_DEBT_DOC,
     desc='per-file native dumps for the whole A/B corpus')
test('ab-compare', [PY, 'tools/ab_compare.py'], deps=['ab-bside'],
     desc='diff the two sides, print only the failures')

# ── Named buckets ───────────────────────────────────────────────────────────
# A bucket is a name for "a set of tests worth running together", and nothing
# more. A bucket may list other buckets, and expansion is transitive with each
# test scheduled exactly once per run — so `make gate`, which contains both
# `selfhost` and `bootstrap`, runs `mojoc` and `native-dumpfull` once, not
# twice, and there is no second copy of any test's name to keep in sync.
BUCKETS = {
    # The everyday green gate — parallel, no exclusive members, minutes.
    'check': ['gimple', 'runner', 'modcache', 'selfhost', 'runtimediff',
              'interp-tokenizer-oracle',
              'linkmode', 'no-new-casts', 'nonlocal', 'gimplerunner',
              'gimplegenerators', 'interporacle', 'examples-parse',
# `ptrreg-boxed-str` is master's split-out red group of the
              # pointer-registry harness and `formal-ast` is the batch's
              # hostmod claim for `ast`; each was added to this bucket on its
              # own side of the merge and both are named here, so a conflict
              # resolution that had to pick one would have quietly dropped a
              # test from the everyday loop.
              'rthdrscan', 'ptrreg', 'ptrreg-boxed-str', 'runtimedylib',
              'sqliteruntime', 'formal-sweep-truth', 'formal-link-accounting',
              'formal-ast', 'silentnoop',
              'refusal-taxonomy', 'returned-frame-layout',
              # Builds nothing and costs 0.05 s, so it belongs in the everyday
              # loop; `formal-glob` is deliberately NOT here (31.8 s, two
              # machines per group).
              'formal-field-walk',
              # The suite tests ITSELF, and so does the inventory of what runs.
              # Both were in `smoke`, which is in no bucket, so `make gate`
              # never executed either — and `suite-self-test` is where the
              # estate check lives, so a landing that added an unregistered
              # test file was reported green by the gate and discovered by
              # whoever ran `smoke` next. That is the whole of a doc that is
              # now closed and deleted, and the defect was a coverage check
              # outside every gate, which is how 50 test files became 94 one at
              # a time. `preflight` is here for the
              # same reason and the smaller one: it is a `deps` of seven
              # members of this bucket and of mojoc/ab-native/native-dumpfull,
              # so it already runs in almost every gate — as a dependency
              # rather than as a counted test, which is why an estate failure
              # is a FAIL on a test the tally does not mention.
'preflight', 'suite-self-test', 'doc-refs',
              # The four cheapest of the eight formal host-module suites, and
              # the only formal BUILD-AND-RUN coverage in the gate. 4-7 s and
              # 0.04-0.06 GB each, against the same two backends the proofs
              # bucket spends its minutes on. The other four
              # (`formal-argparse` 43 s, `formal-hashlib` 36 s warm and 390 s
              # cold, and the two that are RED) are in `proofs` only: the first
              # two are past what the everyday inner loop is for, and an
              # `expect` in this bucket would put a permanently-EXPECTED line
              # in the tally a developer reads to know their tree is fine.
              'formal-os', 'formal-sys', 'formal-frame-len', 'formal-time',
              # …and the pure-Python reference the Metal path is measured
              # against, which needs no compiler at all and so belongs on the
              # side of the line where the everyday loop can afford it. 14.3 s.
              'llm-reference',
              # …and `metalgpu`, the other half of that pairing, which was
              # registered and in NO bucket because "whether it passes needs a
              # real GPU and a full codegen run, which is not a thing a
              # registration can be assumed to be true of" — the honest answer
              # to which was to run it, not to keep it out of a bucket
              # (that census's doc, deleted with the fix). Measured GREEN on
              # 2026-10-01 (arm64, `--no-cache`,
              # 107 s, 0.37 GB peak), which is what makes putting it here safe
              # rather than a guess: `llm-reference` is its CPU reference and
              # these two disagreeing is the signal. The cost, stated where it
              # is paid: 107 s the first time and a cache replay after, against
              # a `check` that is otherwise minutes — and it is `cache=True`
              # with `extra=GIMPLE_SOURCES`, so any codegen edit re-runs it
              # rather than replaying a stale PASS. The GPU layer
              # (`@unittest.skipUnless` + `skipTest('no Metal device on this
              # machine')`) SKIPS itself where there is no device — "no GPU" is
              # a property of the machine, not a defect — so the bucket does
              # not become a claim that every machine has one.
              'metalgpu',
              # …and the four that were REGISTERED and in no bucket at all, so
              # the estate check counted them as covered while no run executed
              # them. Measured green one at a time before being named here
              # (1.1 s, 0.5 s, 0.5 s, 15.1 s), because "register it" is not the
              # same act as "run it" and the difference is invisible until
              # somebody reads `--list`. `md2html` joins them: it is the docs'
              # HTML-staleness check, which is precisely the thing a doc edit
              # should be caught by.
              'cli-usage-text', 'ownership-destruct', 'md2html',
              'arm64-encoders',
              # …and two more of the same kind, measured the same way before
              # being named. `new-syntax-parse` is the parser suite the whole
              # new-modular syntax landed with — registered 2026-09-30 with
              # that work and ungated since the day it was written, so the 87
              # cases it exists for had never run: 87 passed, 1.1 s, 0.0 GB,
              # beside `examples-parse`, the other parser suite, which is 0.1 s
              # and does no compiler work at all (and whose cache key had to be
              # widened to cover its own subject, `fire_compiler.py`).
              # `x86-examples` is the 45 `formal/examples/*.mojo` built for
              # BOTH backends and compared against each other, so it is the
              # only differential arm64-vs-x86-64 evidence for the examples —
              # measured 45/45 in 29.6 s at 0.1 GB. It is in `x86` too, where
              # the rest of the x86-64 picture already is.
              'new-syntax-parse', 'x86-examples',
              # …and the two the estate check named on 2026-10-02, measured at
              # 8.5 s and 2.8 s and at under 0.1 GB each, which is cheaper than
              # most of what is already here (`formal-sys` is 6.9 s,
              # `formal-ast` 1.4 s). Both are formal backend coverage, and both
              # are in `proofs` as well so that bucket stays the whole formal
              # picture; the reason to name a cheap test in two buckets is the
              # reason `x86-examples` is named in two.
              'formal-read-before-store', 'formal-receiver-spelling'],

    # CLAUDE.md's documented quality gate, in full: the everyday gate, plus
    # every step that is slow, memory-hungry, or both. The heavyweight steps
    # are exclusive, so `gate` is safe to leave running on a 128 GB box even
    # though it will touch it — and, since the classes were assigned from
    # measured peaks, what it touches is bounded by those measurements rather
    # than by the shape the workloads resemble.
    'gate': ['check', 'coroutine', 'stdlib', 'native', 'bootstrap'],

    # The 3-stage self-hosting chain and its verification, as a dependency
    # graph. `make bootstrap`.
    'bootstrap': ['bootstrap-clean', 'bootstrap-stage1-dumps',
                  'bootstrap-stage1-transitive', 'bootstrap-stage2-cc',
                  'bootstrap-stage2-dumps', 'bootstrap-stage2-transitive',
                  'bootstrap-stage3-dumps', 'bootstrap-stage3-transitive',
                  'bootstrap-verify', 'bootstrap-validate'],

    # The self-hosted binary's own compiled (native) codegen, as opposed to
    # the python-interpreted reference every other test drives. Overlaps
    # `bootstrap` in `mojoc` only, and running both runs it once.
    'native': ['mojoc', 'ab-native', 'native-dumpfull', 'selfhost-memory', 'selfhost-memory-fire'],

    # The two stdlib build gates: the from-scratch dylib (whose "fell back to
    # source" count is the signal) and the whole-tree syntax check.
    'stdlib': ['stdlib-dylib', 'stdlib-syntax'],
    # The stdlib test/benchmark corpus, through interpreter and JIT. Not part
    # of the gate: it is a much longer sweep than a build check.
    'stdlib-corpus': ['stdlib-tests'],

    'proofs': ['formal', 'formal-call-proofgen',
               'formal-run', 'formal-globals', 'formal-dylib', 'formal-imports',
               'formal-sweep', 'formal-sweep-truth',
               'formal-link-accounting', 'formal-re', 'formal-runtime-link',
               'refusal-taxonomy', 'comptime-parity',
               'returned-frame-layout', 'formal-x86',
               'formal-x86-endtoend', 'formal-x86-model',
               'formal-x86-machine-model',
               # The eight host-module suites registered above. The four in
               # `check` are named here too so `proofs` is the whole formal
               # picture in one bucket, which is what a reader of this list is
               # asking; expansion schedules each test once per run, so being
               # in both costs nothing.
               'formal-os', 'formal-sys', 'formal-frame-len', 'formal-time',
               'formal-argparse', 'formal-hashlib', 'formal-toplevel',
               'formal-struct',
               # The four that arrived after the count of eight, the same way:
               # the whole formal picture in one bucket, which is what a reader
               # of this list is asking. Expansion schedules each test once per
               # run, so being in `check` too costs nothing.
               'formal-dataclasses', 'formal-module-attr',
               'formal-os-backing',
               # …and the two that arrived with master's formal20 batches on
               # 2026-10-04 unregistered, registered above with their
               # measurement beside them.
               'formal-field-walk', 'formal-glob',
               # …and the two that arrived with the formal3 batch and were in
               # NO bucket and NO `UNREGISTERED`, which is what the estate check
               # in `suite-self-test` was reporting — and it is a FAIL on a test
               # that is in `check`, so it was red in the everyday loop and not
               # only in `make gate`. `formal-read-before-store` is a pure unit
               # test of `model.read_before_store` against CPython (61 shapes, no
               # builds); `formal-receiver-spelling` builds and runs three
               # images. Both measured green one at a time before being named
               # (10.9 s / 0.0 GB and 6.0 s / 0.1 GB), and both cost less than the
               # four formal host-module suites already in this list. Registering
               # rather than marking is the project's own rule; the bug doc that
               # asked for it is deleted with this.
              'formal-read-before-store', 'formal-receiver-spelling',
               # The ten the batch merge left unregistered, so `proofs` is
               # where the whole formal picture is and these were the ten
               # missing pieces of it. `formal-value-model` and
               # `formal-receiver-position` are two of the largest formal
               # bodies of test in the tree, so the gap was not marginal.
'formal-external-call', 'formal-json', 'formal-pathlib',
                'formal-method-param-field', 'formal-receiver-position',
                'formal-small-hosts', 'formal-specialization',
                'formal-monomorph',
                'formal-target-queries', 'formal-value-model',
                'formal-x86-dylib',
                # …and the two the estate check named on 2026-10-02, for the
                # same reason and with the same cost measurement: cheap enough
                # that `check` runs them and `proofs` is only naming them.
'formal-read-before-store', 'formal-receiver-spelling',
                # …and the one the estate check named on the merge of the
                # formal5 batch: `test_formal_core_hostmods.py` came with
                # `work/formal5-hostmods-core` and was named by no bucket.
                # `proofs` rather than `check` because it builds and EXECUTES a
                # formal image per group and its subject is a host module's
                # answers rather than a static shape; 25 s and 0.1 GB measured,
                # which is the cost class of `formal-json` above.
'formal-core-hostmods',
                # …and the one the estate check named on the merge of
                # `work/formal8-4` (2026-10-03): `test_formal_typed_flag.py`
                # came with that branch and was named by no bucket and by no
                # `UNREGISTERED` excuse. `proofs` rather than `check` to stay
                # with its neighbours; it is the cheapest formal test in the
                # tree (0.64 s, 0.033 GB, no build and no Lean) so `check`
                # would be defensible too, and the choice is not worth a
                # second argument.
                'formal-typed-flag',
                # …and `test_formal_blob_contract.py`, which came with
                # `work/formal13-1` and was named by no bucket. Same shape of
                # thing as the one above and the same cost: 0.63 s and 0.036 GB,
                # a source check with no image and no Lean, so there is no
                # argument for `check` that does not apply equally to
                # `formal-typed-flag`.
                'formal-blob-contract',
                # …and the two `work/formal12-hostmods-subprocess` brought,
                # which that branch excused in `test_suite.py` and this merge
                # registers instead. `proofs` rather than `check` for
                # `formal-core-hostmods`'s reason and not `check`'s: they build
                # and EXECUTE a formal image per group on both backends, so
                # 35.8 s and 15.8 s is real work rather than an analysis.
                'formal-tempfile', 'formal-textwrap',
                # …and the census instrument, for `formal-call-proofgen`'s
                # reason and not `check`'s: it runs `compile_formal` with
                # `prove=True` over 60 items, so 22 of them build an image and
                # the `proof-crash` vs `proof-refused` distinction it pins is
                # only observable with the generator actually running.
                'formal-proof-breadth-tool',
                # …and the five the estate check named on the formal6 merge,
                # which is the same reason stated once more because it is now
                # the fourth time: four host-module differentials and the
                # admitted-contract ratchet, 7.0-34.5 s and 0.07-0.13 GB
                # measured. `proofs`, for the shape `formal-core-hostmods`
                # above gives — an image per group, executed, against CPython —
                # and not for the clock, because the clock does not agree: a
                # 34.5 s `formal-shutil` argues for `proofs` on cost and a
                # 7.0 s `formal-fcntl`, cheaper than the `formal-sys` that is
                # in both buckets, argues for `check`. What a test costs and
                # what it is ABOUT are different questions, and only the second
                # one should decide where it lives.
                'formal-admitted', 'formal-fcntl', 'formal-math',
                'formal-shutil', 'formal-stat'],
    'x86': ['formal-x86', 'formal-x86-endtoend', 'formal-x86-model',
            'formal-x86-machine-model',
            # The decoder, which is x86-64 coverage with no image in it: half a
            # second and one round-trip check, and registered with no bucket,
            # which is the same hole as the five in `check`.
            'x86-decode',
            # …and the two x86-64 jobs that were registered and run by nothing.
            # `x86-examples` builds and RUNS every formal/examples/*.mojo for
            # BOTH backends and compares them with each other, so it is the
            # only arm64-vs-x86-64 differential the examples have: 45/45 in
            # 29.6 s at 0.1 GB. In `check` as well, and the reason to name a
            # cheap test in two buckets is the reason `formal-os` and friends
            # are named twice: expansion schedules each test once per run, so
            # it costs nothing and both lists stay whole.
            'x86-examples',
            # `x86-containers` is the one member of this list that is NOT in
            # `check`, and it is here for a cost reason rather than a
            # correctness one: 60 whole programs per backend, each one built
            # and executed, measured at 4 minutes and 0.1 GB. `formal-argparse`
            # at 43 s is already "past what the everyday inner loop is for" and
            # that is the precedent; this is six times that. It is also the
            # only file in the tree that executes an x86-64 container operation
            # and checks what it computed, so between these two the bucket's
            # reason for existing is more than a model check. It is
            # `expect=`-marked for one case (`with 7 as y: x = y`, refused by
            # the read-before-store rule) and the marker is the reason it must
            # be RUN somewhere: a known failure that nothing runs can never be
            # observed going green, which is the whole argument for the
            # `the buckets:` checks in test_suite.py. Its marker states its
            # count.
            'x86-containers'],
    # The compiled-path async/await and coroutine cluster: ten
    # `expect=`-marked suites that were registered and in no bucket, so the
    # gate walked past ~69 declared failing cases and reported nothing, and no
    # `expect=` anti-rot could fire on any of them
    # (that doc, deleted with the fix). They are the largest block of unrun
    # failures in the tree, and
    # every one of them is a real compile-and-run of Mojo source. All ten are
    # here rather than in `check` for one reason stated once: they are
    # `expect=`-marked, and an `expect` in `check` puts a permanently-
    # EXPECTED line in the tally a developer reads to know their tree is fine
    # (the same reasoning that keeps `formal-module-attr`,
    # `formal-external-call` and `formal-receiver-position` in `proofs` only). `coroutine` is in `gate`, so this IS gated — it is
    # just gated somewhere whose tally is a list of known reds rather than a
    # green/red verdict on the everyday loop.
    #
    # Measured one at a time under `tools/memslot.py --gb 8` before being named,
    # which is also what set their `mem` to `tiny` (0.0-0.2 GB each, against
    # the `small`/8 GB they carried while ungated):
    #   gimple-async-runner  1.2 s  0.0 GB   2 passed, 36 failing
    #   coro-detached-async  2.2 s  0.1 GB   2 failing
    #   async-with-lock-guard 2.7 s 0.1 GB   2 failing
    #   mutable-async-capture 2.7 s 0.1 GB   2 failing
    #   transitive-closure-capture 2.7 s 0.1 GB  2 failing
    #   async-void-return    3.3 s  0.1 GB   3 failing
    #   nested-async-generic 3.3 s 0.1 GB    2 failing
    #   taskgroup            3.2 s  0.2 GB   3 failing
    #   async-runtime-scaffold 1.7 s 0.2 GB  1 of 2
    #   coro-future-await   11.6 s  0.1 GB  17 failing
    # 34.6 s in total, against a gate whose slowest everyday members are
    # minutes each, so the added wall time is stated here rather than left to
    # be discovered.
    'coroutine': ['coro', 'coro-nested-capture',
                  'gimple-async-runner', 'coro-detached-async',
                  'async-with-lock-guard', 'mutable-async-capture',
                  'transitive-closure-capture', 'async-void-return',
                  'nested-async-generic', 'taskgroup',
                  'async-runtime-scaffold', 'coro-future-await'],
    'smoke': ['preflight', 'suite-self-test', 'memslot'],
    'ab': ['ab-clean', 'ab-aside', 'ab-bside', 'ab-compare'],
}

# A name that is both a bucket and a test would make `suite.py <name>` mean
# whichever one won the lookup, silently. There is no good reason to want one,
# so refuse it at import.
_clash = sorted(set(BUCKETS) & set(REGISTRY))
if _clash:
    raise SystemExit(f"suite.py: name(s) used for both a bucket and a test: "
                     f"{_clash}")
for _bucket, _members in BUCKETS.items():
    for _m in _members:
        if _m not in REGISTRY and _m not in BUCKETS:
            raise SystemExit(f"suite.py: bucket {_bucket!r} lists {_m!r}, "
                             f"which is neither a test nor a bucket")

# Environment variables forwarded to `make` for driver='make' tests, so
# `BOOTSTRAP_OPT=-O2 tools/suite.py bootstrap` keeps working through the
# runner instead of having to be re-implemented on this side.
MAKE_VARS = ['MEMLIMIT_GB', 'BOOTSTRAP_OPT', 'MOJO_OPT', 'GCC_MP15']


# ── Screen vs. log ───────────────────────────────────────────────────────────
# The screen answers one question — did anything break, and what — so it stays
# short enough to read while a 40-minute gate runs. The log file answers the
# other one ("what exactly happened, in order"), so it gets everything: a PASS
# line per job with its full argv, exit code, duration and measured peak, the
# complete output of anything that failed, the reason for every skip, and the
# environment the run happened in. Nothing that gets thrown away is lost, it
# just goes to the file.
class Log:
    def __init__(self, path, quiet=False):
        self.path = path
        self.quiet = quiet
        self.fh = None
        if path:
            os.makedirs(os.path.dirname(os.path.join(REPO, path)) or '.',
                        exist_ok=True)
            self.fh = open(os.path.join(REPO, path), 'w', encoding='utf-8')

    def line(self, msg=''):
        """Log only. PASS lines and per-job transcripts live here."""
        if self.fh:
            self.fh.write(str(msg).rstrip('\n') + '\n')
            self.fh.flush()

    def notice(self, msg='', force=False):
        """Log *and* print: anything the reader must see without opening a
        file — failures, skips, a resource breach, the tally.

        `force` ignores -q, for the cases where staying quiet would be
        actively misleading (a run that cannot proceed as asked).
        """
        self.line(msg)
        if force or not self.quiet:
            print(msg, flush=True)

    def raw(self, text):
        """Verbatim block into the log (a failing job's whole output)."""
        if self.fh and text:
            self.fh.write(text if text.endswith('\n') else text + '\n')
            self.fh.flush()

    def close(self):
        if self.fh:
            self.fh.close()
            self.fh = None


def env_state(opts, names) -> "list[tuple[str, str]]":
    """What has to be recorded for this run to be reproducible later."""

    def first(*cmd):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True,
                                 timeout=20).stdout.strip()
            return out.splitlines()[0] if out else ''
        except (OSError, subprocess.SubprocessError):
            return '?'

    dirty = 'clean'
    if first('git', 'rev-parse', '--git-dir'):
        porcelain = subprocess.run(['git', 'status', '--porcelain'],
                                   capture_output=True, text=True,
                                   timeout=60).stdout.strip()
        dirty = f'{len(porcelain.splitlines())} uncommitted path(s)' if porcelain else 'clean'
    # The project's own resolution, not `command -v gcc`: build_config.find_gcc
    # is what every test in this repo actually compiles with, and a log that
    # named a different compiler than the one that ran would be worse than no
    # log at all.
    try:
        sys.path.insert(0, REPO)
        from build_config import find_gcc
        gcc = find_gcc()
    except Exception:                            # noqa: BLE001
        gcc = first('sh', '-c', 'command -v gcc-15 || command -v gcc')
    return [
        ('date', time.strftime('%Y-%m-%d %H:%M:%S %Z')),
        ('host', first('uname', '-n')),
        ('platform', first('uname', '-srm')),
        ('git HEAD', first('git', 'rev-parse', '--short', 'HEAD') or 'not a repo'),
        ('git tree', dirty),
        ('python', sys.version.split()[0]),
        ('gcc', gcc),
        ('jobs', str(opts.jobs)),
        ('MEMLIMIT_GB', os.environ.get('MEMLIMIT_GB', '') or '(unset)'),
        ('MEMSLOT_GB', f'{memslot_budget():g} of one machine-wide budget '
                       f'(MEMSLOT_BUDGET_GB)'),
        ('memslot held', f'{memslot.reserved_gb():g} GB already reserved'),
        ('selected', ', '.join(names)),
    ]


# ── Jobs ─────────────────────────────────────────────────────────────────────
class Job:
    __slots__ = ('spec', 'label', 'key', 'cmd', 'cwd', 'env')

    def __init__(self, spec, label=None, cmd=None, cwd=None, env=None):
        self.spec, self.label = spec, label
        self.key = f"{spec.name}:{label}" if label else spec.name
        self.cmd = list(cmd) if cmd is not None else list(spec.cmd)
        self.cwd, self.env = cwd, dict(env or {})

    @property
    def excl(self):
        return self.spec.excl


PASS, FAIL, SKIP, RESOURCE, TIMEOUT, ERROR, EXPECTED, DISABLED = (
    'pass', 'fail', 'skip', 'resource', 'timeout', 'error', 'expected',
    'disabled')
# Worst-first, so one bad job decides a multi-job test's verdict. A plain FAIL
# outranks a RESOURCE one: a wrong answer is a more actionable report than a
# process that ran out of memory. DISABLED is deliberately NOT in here: it is
# not a verdict ON a job (no job ran), so there is nothing for a fanout's
# cumulative fold to rank it against, and it is seeded into `state` by
# `execute` rather than settled by a worker thread.
_RANK = {PASS: 0, SKIP: 1, RESOURCE: 2, TIMEOUT: 3, ERROR: 4, FAIL: 5}


# ── The tally ────────────────────────────────────────────────────────────────
# What the summary line and the screen do with each status. `report` RENDERS
# this table rather than naming statuses inline, because the defect it exists
# for was a status the runner produced, announced on the screen, and then
# counted nowhere.
#
# Real, measured on a `gate` run of 2026-09-29: the log carried
#     [ 76/177] TIMEOUT sqliteruntime 600.1s  (0 running)
# and the run finished
#     suite: 30 passed, 0 failed, 5 skipped, 1 resource-capped,
#            2 expected-failure  (177 jobs, 0 replayed from cache, ...)
# with exit 0. 30+0+5+1+2 = 38, and 39 tests ran: the hang was in no counter,
# in no screen section, and did not fail the run — a job that vanished, which
# is the one outcome a tally exists to make impossible.
#
# One row per COUNTER, in the order the summary line reads, so the summary, the
# screen sections and the exit code are all rendered from the same table and
# cannot disagree about which statuses they cover.
#
#   count   wording in the summary line. The three primary verdicts are printed
#           at zero, because "0 failed" is the number a reader looks for; the
#           exceptions — a resource breach, a known failure, a hang, a disabled
#           test — print only when non-zero, because their absence is the
#           normal case.
#   statuses  the statuses this counter counts. The FIRST is the plain reading
#           of the section; a member in any other one is tagged with its status
#           in the listing, so a hang sitting among the failures is named as a
#           hang rather than as one more failing test.
#   header  the screen section that lists this counter's members, or '' for one
#           that is never listed (a pass).
#   fails   whether a member makes the run exit non-zero.
#
# A counter holds more than one status where a reader cannot tell them apart:
# FAIL and ERROR have always been one number, and a TIMEOUT joins them because
# a hang IS a failure (its own class, because "killed at its timeout" and
# "produced the wrong answer" are different bugs and a tally that merged them
# would hide which one a fix has to address; a failure, because a job killed at
# its timeout has reported nothing at all, so a run that hangs a test and exits
# 0 has silently not run the thing it was asked to run).
#
# The two `fails=False, zero=False` rows at the end — `expected-failure` and
# `disabled` — are both "we know, and the knowing is recorded". `expected` is
# the verdict of a test that RAN and failed; `disabled` is the state of a test
# that did not run at all, and it exists as a row rather than as an absence
# precisely so a registered-but-not-run test is still counted: a test that
# vanishes from the summary is how the 2026-09-29 TIMEOUT became invisible,
# and "we chose not to run this" is a decision a reader has to see, not a
# number that quietly goes missing.
class Verdict:
    __slots__ = ('count', 'statuses', 'header', 'fails', 'zero')

    def __init__(self, count, statuses, header='', fails=True, zero=True):
        self.count, self.statuses = count, tuple(statuses)
        self.header, self.fails, self.zero = header, fails, zero


TALLY = (
    Verdict('passed', (PASS,), fails=False),
    Verdict('failed', (FAIL, ERROR, TIMEOUT), 'FAILED'),
    Verdict('skipped', (SKIP,), 'SKIPPED', fails=False),
    Verdict('resource-capped', (RESOURCE,),
            'RESOURCE-CAPPED (not a verdict on the output)', fails=False,
            zero=False),
    Verdict('expected-failure', (EXPECTED,),
            'EXPECTED (known-broken, tracked not hidden)', fails=False,
            zero=False),
    Verdict('disabled', (DISABLED,),
            'DISABLED (not run: expected to fail, turns on when its bug is '
            'fixed)', fails=False, zero=False),
)

# Every status the runner can produce is counted by exactly one row, and every
# status a row names is one the runner can produce. Checked at import rather
# than trusted: a status added to `_RANK` and not to the tally is exactly the
# defect above, and refusing to start is the strongest form of "counted" — the
# runner cannot be used, `--list` included, in a state where it cannot account
# for one of its own verdicts.
#
# `PRODUCIBLE` is the one list, and it is spelled out rather than derived from
# `_RANK` because two of the statuses are not per-job verdicts at all: EXPECTED
# is a post-run fold over a job's verdict (`_apply_expectations`) and DISABLED
# is the absence of a job. A test reads this name instead of re-deriving the
# set, which is how the tally invariant ends up with two spellings.
PRODUCIBLE = set(_RANK) | {EXPECTED, DISABLED}
TALLY_ROW = {s: row for row in TALLY for s in row.statuses}
_mismatch = sorted(PRODUCIBLE ^ set(TALLY_ROW))
if _mismatch or len(TALLY_ROW) != sum(len(r.statuses) for r in TALLY):
    raise SystemExit(
        f"suite.py: the tally and the runner disagree about these statuses: "
        f"{_mismatch or '(a status is listed in two rows)'}\n"
        f"  the runner can produce: {sorted(PRODUCIBLE)}\n"
        f"  the tally counts:      {sorted(TALLY_ROW)}\n"
        f"  Every status needs exactly one Verdict row in TALLY.")


class Result:
    __slots__ = ('status', 'secs', 'detail', 'cached', 'peak_gb', 'output')

    def __init__(self, status, secs=0.0, detail='', cached=False, peak_gb=None,
                 output=''):
        self.status, self.secs, self.detail = status, secs, detail
        self.cached, self.peak_gb = cached, peak_gb
        self.output = output


_NO_CAP_WARNED = False


def log_warn_no_cap(spec):
    """MEMLIMIT_GB=0 means "no ceiling anywhere" — say so once, loudly, at the
    point where a job would have been capped."""
    global _NO_CAP_WARNED
    if not _NO_CAP_WARNED:
        _NO_CAP_WARNED = True
        print(f'suite: {spec.name}: MEMLIMIT_GB=0 — running with NO memory '
              f'ceiling. Please watch the machine.', flush=True)


def build_cmd(job: Job, opts) -> list[str]:
    """The argv for a job, with its driver and memclass applied."""
    spec = job.spec
    cmd = list(job.cmd)
    fanout = isinstance(spec, Fanout)
    if fanout:
        pass                                    # already the bare command
    elif spec.driver == 'make':
        # Make's own job server, so a per-file A/B target gets real -j.
        # `spec.cmd` is the make TARGET(S) only, never the program: the argv
        # this builds already starts with `make`.
        cmd = (['make', f'-j{opts.jobs}']
               + [f'{v}={os.environ[v]}' for v in MAKE_VARS if os.environ.get(v)]
               + cmd)
    elif spec.cache:
        # Whole tests only, never a fanout item: a fanout's output artifact IS
        # its result, so a replayed cache hit would leave the artifact missing.
        # --rerun-failures: a cached PASS is replayed, a cached FAILURE is
        # re-run, because the cache key covers the files named in `extra` and
        # not the rest of the machine (a stale build/, a leftover module-cache
        # dir, the box itself).
        cmd = ([PY, 'checked_run.py', spec.name]
               + [a for f in spec.extra for a in ('--extra', f)]
               + [a for g in spec.extraglob for a in ('--extra-glob', g)]
               + ['--rerun-failures']
               + (['--no-cache'] if opts.no_cache else [])
               + ['--'] + cmd)
    if isinstance(spec, Spec) and spec.j:
        cmd = cmd + ['-j', str(opts.jobs)]
    # The ceiling goes on LAST, so it wraps the whole job as the runner
    # launched it: the `make` server and its `-j` children, the checked_run
    # cache wrapper, and the workload itself all sit inside the one tree
    # memcap measures. Every driver gets one, which is the point — a cap that
    # only the `mem` driver had made coverage a property of the DRIVER rather
    # than of the workload, and left peak measurement as a side effect
    # available to 5 of the 73 registered jobs.
    #
    # Fanout items included, which they were NOT: `build_cmd` guarded the whole
    # block with `isinstance(spec, Spec)`, so a fanout's `mem=` was validated,
    # printed by `--list`, and then never applied to anything. All three
    # `bootstrap-stage*-dumps` fanouts (45 jobs each, each one a `./mojoc
    # --dump` or `fire.py --dump` of one real source file) ran UNCAPPED while
    # the registry said `mem=module` — a cap that was documented in three
    # places and applied in none, which is worse than an absent one because it
    # reads as coverage.
    cls = memclass_for(spec)
    limit = memlimit(cls)
    if limit > 0:
        # ABSOLUTE, not repo-relative: a job may run in another directory
        # (bootstrap's stage1/stage2/stage3 trees), and `python3
        # tools/memcap.py` then resolves against THAT cwd and dies with
        # "can't open file .../stage1/tools/memcap.py" before the wrapped
        # command ever runs.
        cmd = [PY, os.path.join(HERE, 'memcap.py'),
               '--limit-gb', str(limit),
               '--label', job.key, '--'] + cmd
    elif not fanout or spec.mem:
        # A `cmd`/`make` job on the default class that resolves to 0 under
        # MEMLIMIT_GB=0 is the run-wide "no ceiling anywhere" switch, already
        # announced at startup; repeating it per job would be noise. A spec
        # that NAMED a class being overridden to nothing is worth a line, since
        # it means the number someone chose is not in force.
        log_warn_no_cap(spec)
    return cmd




# ── Content-addressed artifact cache ─────────────────────────────────────────
# For the steps whose product is a BINARY (`mojoc`, `stage2/mojo`), because
# that is where the minutes are and their inputs are exactly hashable. A miss
# costs a rebuild; a wrong hit is a wrong compiler, quietly, which is the worst
# failure a cache in this position can have — so the key is computed from the
# bytes of the real inputs plus the exact argv, never from a hand-maintained
# prerequisite list, and cas.selfhost_fingerprint() supplies the closure (see
# cas.py for why that is a different, and larger, input set than
# compiler_fingerprint(), and for the check that keeps it complete).
#
# What is deliberately NOT cached: the three stage trees. `verify`'s entire job
# is comparing stage1 against stage2 against stage3, so caching two of those
# three would make its comparison a fresh artifact against a copy of itself —
# the gate would pass by construction and stop detecting the byte-identity
# divergence it exists to detect. That is also not much of a loss, because it
# was measured: the 45-file per-stage sweeps cost 1.8 s in total, so all of
# bootstrap's ~32 minutes is the three whole-closure dumps plus the `gcc -O0`
# compile between them — and those artifacts must be produced fresh.
class ArtifactCache:
    def __init__(self, name, artifact, argv, inputs, fingerprint):
        self.artifact = artifact
        self.ext = os.path.splitext(artifact)[1] or '.bin'
        digests = []
        for p in inputs:
            full = os.path.join(REPO, p)
            digests += [p, cas.file_digest(full) if os.path.exists(full)
                        else 'missing']
        self.key = cas.hash_parts('suite-artifact-v1', name, fingerprint,
                                  *argv, *digests)

    def hit(self):
        """Materialise a cached artifact into place; True if there was one."""
        blob = cas.lookup(self.key, self.ext)
        if blob is None:
            return False
        dest = os.path.join(REPO, self.artifact)
        os.makedirs(os.path.dirname(dest) or '.', exist_ok=True)
        shutil.copyfile(blob, dest)
        os.chmod(dest, 0o755)                # these are executables
        return True

    def store(self):
        path = os.path.join(REPO, self.artifact)
        if not os.path.exists(path):
            return False
        with open(path, 'rb') as f:
            cas.publish(self.key, self.ext, f.read())
        return True


# ── Running one job ──────────────────────────────────────────────────────────
def run_job(job: Job, opts, log: Log) -> Result:
    spec = job.spec
    env = dict(os.environ)
    env.update(job.env)
    log.line(f'--- {job.key}')
    try:
        cmd = build_cmd(job, opts)
    except Exception as exc:                       # a bad registry entry
        return Result(ERROR, detail=f'bad command: {exc!r}')
    log.line('  argv: ' + ' '.join(shlex.quote(a) for a in cmd))
    if job.cwd:
        log.line(f'  cwd:  {job.cwd}')
    if job.env:
        log.line('  env:  ' + ' '.join(f'{k}={v}' for k, v in job.env.items()))
    # Every spec resolves to a memclass (a fanout is required to name one, a
    # cmd/make spec inherits DEFAULT_MEMCLASS), so the ceiling and the
    # reservation below are a property of the workload rather than of whichever
    # driver happens to launch it.
    cls = memclass_for(spec)
    log.line(f'  memcap: {cls} class'
             + (f' (default)' if not spec.mem else '')
             + f', ceiling {memlimit(cls)} GB')

    # A fan-out item that names a file which is not there is this item's
    # failure, and it is checked HERE, before the process is launched, so the
    # verdict names the item instead of relaying the compiler's own message
    # about a path it could not open. This is not defensive padding: the
    # 2026-09-29 round-6 flake was exactly this — `ab-native`'s transient
    # `_abt_minimal_main.mojo` was enumerated as a stage1-dumps item, deleted
    # out from under it, and the report was eight SKIPs with the one real
    # cause buried in an item's stderr. `tracked_mojo_files` stops the
    # transient from being enumerated at all; this catches the residue that
    # survives that (a tracked file absent from this worktree, a file deleted
    # between the plan and the launch) and, critically, keeps the damage
    # local: the item FAILs, the rest of the sweep still runs, and the tally
    # says 1 of 41 rather than reporting a chain that silently did not run.
    if isinstance(spec, Fanout) and spec.items_are_files and job.label:
        item_path = os.path.join(REPO, job.label)
        if not os.path.exists(item_path):
            return Result(FAIL, detail=(
                f'item file {job.label} does not exist — it was enumerated as '
                f'a tracked source but is not in this worktree (deleted after '
                f'the plan was built, or a checkout that never had it)'))

    # An artifact-cached step: a hit means the binary is already correct, so
    # the step does not run at all. Only whole steps are cached; a fanout's
    # items are never one artifact. --no-cache skips the LOOKUP but still
    # publishes, exactly as checked_run.py does, so a forced fresh run seeds
    # the next one.
    cache = None
    if getattr(spec, 'artifact', None):
        cache = ArtifactCache(spec.name, spec.artifact, cmd, spec.inputs,
                              cas.selfhost_fingerprint())
        log.line(f'  artifact cache: {spec.artifact} key {cache.key[7:19]}...')
        if not opts.no_cache and cache.hit():
            log.notice(f'  CACHED   {job.key}  ({spec.artifact} restored from '
                       f'the content-addressed store — inputs unchanged)')
            return Result(PASS, cached=True, detail=f'{spec.artifact} from cache')

    # ── Admission ────────────────────────────────────────────────────────────
    # The gigabytes this job is about to use, taken out of the machine-wide
    # budget, BEFORE anything of it is spawned. The ceiling (`build_cmd`) and
    # the reservation are the same number on purpose: the runner never admits
    # more than the budget, and an admitted job is never allowed to take more
    # than it was given. The single exception is in `reserved_gb`.
    #
    # After the artifact-cache check on purpose. A cache hit starts no process
    # and allocates nothing, so making it queue behind a long wait for a large
    # reservation would make `make gate` slower for no reason at all — the step
    # it is standing in for is already done.
    need = reserved_gb(spec)
    if need <= 0:
        # MEMLIMIT_GB=0. There is no number to reserve and no ceiling to keep,
        # so admission is skipped rather than faked with a zero-gigabyte
        # reservation, which would admit everything and claim to have
        # controlled it. Already announced at startup, loudly.
        log.line('  admission: none — no ceiling on this job, so nothing to '
                 'reserve (MEMLIMIT_GB=0)')
        slot = None
    else:
        slot = memslot.Slot(need, job.key, budget=memslot_budget())
        try:
            slot.acquire()
        except ValueError as exc:
            # A job whose class exceeds the whole budget can never be admitted.
            # That is a configuration fact, not a machine problem and not a
            # wrong answer, so it is an ERROR naming both numbers — the
            # alternative is a queue that never drains and a run that hangs
            # instead of reporting.
            log.line(f'  admission REFUSED: {exc}')
            return Result(ERROR, detail=f'cannot be admitted: {exc}')
        wait = slot.waited
        if wait > 0.5:
            log.line(f'  admission: waited {wait:.0f}s for {slot.gb:g} GB '
                     f'(budget {memslot_budget():g} GB)')
        log.line(f'  admitted:   reserved {slot.gb:g} GB, '
                 f'{max(0.0, memslot_budget() - slot.gb):g} GB left of '
                 f'{memslot_budget():g} GB'
                 + ('   [exclusive: nothing else in this run starts until '
                    'this is done]' if job.excl else ''))
        if slot.covered:
            # An ANCESTOR already holds this reservation, so the ledger was
            # not consulted for it. Real, and not a rare path: a `make` recipe
            # that is itself `memslot.py --gb N -- …` is spawned by a job this
            # runner just admitted for N, and two reservations for one tree
            # would deadlock. See tools/memslot.py.
            log.line('  admitted:   covered by the reservation this process '
                     'tree was started under')
        else:
            # The reservation has to reach the tree it covers, or a wrapper
            # inside that tree queues for a turn its own parent is holding.
            # The POOL is the other half of the same sentence: this job's
            # reservation is also the ceiling on everything its own fan-out
            # runs at once, so `make -j20 bside` — twenty concurrent compiles,
            # each wanting the per-file `module` class — is bounded by the
            # `program` class the job was admitted for instead of being twenty
            # times it. A child opts in (`memslot.Slot(..., pool=True)`); one
            # that does not is unaffected. See tools/memslot.py.
            env.update(memslot.held_env(slot.gb,
                                        pool=f'{job.key}:{os.getpid()}'))

    t0 = time.time()
    cwd = os.path.join(REPO, job.cwd) if job.cwd else REPO
    if job.cwd:
        # Created here, at execution time, rather than in the plan: a stage
        # directory has to exist by the time its first job runs, and the step
        # that wipes it (bootstrap-clean) runs before both.
        os.makedirs(cwd, exist_ok=True)
    run = None
    try:
        # `on_start` fires with the child's pid while it is ALIVE, which is the
        # only moment it is worth recording: the reservation outlives a killed
        # scheduler exactly as long as the process it started keeps running.
        # And t0 is AFTER admission, so a job's timeout is the job's: a `stage`
        # job can wait a long time for 96 GB on a busy machine, and a timeout
        # that counted the queue would kill jobs that had done nothing wrong.
        run = procrun.spawn(cmd, cwd=cwd, env=env,
                            timeout=spec.timeout or opts.timeout,
                            stream=(opts.jobs == 1 or opts.verbose),
                            on_start=slot.note_job if slot else None)
    except OSError as exc:
        return Result(ERROR, detail=f'could not launch: {exc}')
    finally:
        if slot is not None:
            slot.release()
    secs = time.time() - t0
    breached, peak = _memcap_verdict(run.out)
    log.line(f'  exit: {run.rc}   secs: {secs:.1f}'
             + (f'   peak: {peak:.1f} GB' if peak is not None else ''))

    if run.timed_out:
        res = Result(TIMEOUT, secs, f'still running after '
                                    f'{spec.timeout or opts.timeout}s — killed',
                     peak_gb=peak, output=run.out)
    elif breached or (run.rc == 125 and _was_capped(cmd)):
        # memcap's own verdict, read from its output rather than from the exit
        # code: `memcap_verdict` keys on memcap's BREACH line, and the exit-code
        # fallback is only for a job that was supposed to be wrapped (a `cmd`
        # job that happens to exit 125 by itself is a failure, and calling that
        # a memory cap files a real bug under a machine problem). A RESOURCE
        # failure is not a verdict: the process was killed for memory before it
        # finished, so it says nothing about whether the output was right.
        res = Result(RESOURCE, secs,
                     'memory ceiling reached before the job finished — this is '
                     'not a verdict on the output', peak_gb=peak, output=run.out)
    elif spec.reject and re.search(spec.reject, run.out):
        res = Result(FAIL, secs,
                     f'exit {run.rc}, but the output contains {spec.reject!r} — '
                     f'a real codegen gap that does not abort the compiler',
                     peak_gb=peak, output=run.out)
    elif run.rc != 0:
        res = Result(FAIL, secs, f'exit {run.rc}', peak_gb=peak, output=run.out)
    else:
        res = Result(PASS, secs, peak_gb=peak, output=run.out,
                     cached='cached result replayed' in run.out)

    if res.status != PASS:
        log.raw(run.out)                           # the whole transcript
    elif opts.keep_output:
        log.raw(run.out)
    if cache is not None and res.status == PASS and cache.store():
        log.line(f'  published {spec.artifact} to the cache under '
                 f'{cache.key[7:19]}...')
    return res


def _memcap_verdict(text):
    """`(breached, peak_gb)` for a job that ran under a ceiling.

    The reading itself is `procrun.memcap_verdict`, because the A/B harness
    needs the same two facts per file and there is one memcap, not two output
    formats. The rounding is this module's: a peak below 0.1 GB is reported as
    None, since memcap prints one decimal, so a 40 MB job reports "0.0 GB" and
    a stream of those is noise in a report whose whole point is that the big
    numbers stand out.
    """
    breached, peak = procrun.memcap_verdict(text)
    return breached, (peak if peak is not None and peak >= 0.1 else None)


def _was_capped(cmd) -> bool:
    """Did this argv actually go through memcap?

    Only used as a fallback for exit 125 with no BREACH line in the output —
    i.e. the wrapper died without reporting — so that a capped job is never
    filed as a plain failure, and an uncapped one that exits 125 by itself
    still is.
    """
    return any(os.path.basename(str(a)) == 'memcap.py' for a in cmd)


def _screen_excerpt(text, lines=8):
    """The tail of a failing job's output, for the screen. The rest is in the
    log; the point of the screen line is to be recognisable at a glance."""
    body = [ln for ln in str(text).rstrip().splitlines() if ln.strip()]
    return '\n'.join(body[-lines:])


# ── Selection and planning ───────────────────────────────────────────────────
def select(names, opts):
    """Resolve CLI arguments to an ordered, de-duplicated list of test names.

    A bucket may contain other buckets, so this expands transitively — and
    every test lands in the list exactly once however many buckets (or bucket
    references) reach it. That is what makes `make gate` correct: it contains
    both `native` and `bootstrap`, which share `mojoc`, and `mojoc` is
    scheduled one time.

    Naming a *test* brings that test's `deps` with it, before it. Naming a
    thing is naming what it needs in order to run, which is what a Make
    prerequisite means and what `preflight` is for. Without this, `walk`
    returned at the test and its deps were never selected, so the run died
    with `dependency not selected: preflight` — a failure of the runner
    rather than of the test, reported against whichever test was asked for.
    It hit all eight `deps=['preflight']` tests: every `make check-formal*`
    target, and the `proofs` bucket, which never listed `preflight` as a
    member either. Buckets that already spelled their deps out as members
    (`native` naming `mojoc`, `ab` naming `ab-clean`, `smoke` naming
    `preflight`) were relying on this by hand; they still work, because
    `add_test` de-duplicates.
    """
    chosen, seen = [], set()

    def add_test(n):
        if n not in seen:
            seen.add(n)
            chosen.append(n)

    def walk(name, stack):
        if name in stack:
            raise SystemExit("suite.py: bucket cycle: "
                             + " -> ".join(stack + [name]))
        if name in REGISTRY:
            # Deps first, so the list is ordered the way the graph runs and a
            # dep can never land after the test that needs it. `stack + [name]`
            # is what makes a dependency cycle an error rather than a hang.
            for dep in REGISTRY[name].deps:
                walk(dep, stack + [name])
            add_test(name)
            return
        if name not in BUCKETS:
            raise SystemExit(
                f"suite.py: no such bucket or test: {name!r}\n"
                f"  buckets: {', '.join(sorted(BUCKETS))}\n"
                f"  tests:   {', '.join(sorted(REGISTRY))}")
        for member in BUCKETS[name]:
            walk(member, stack + [name])

    for name in names:
        if name == 'all':
            for bucket in BUCKETS:
                walk(bucket, [])
        else:
            walk(name, [])

    if opts.only:
        for pat in opts.only:
            kept = [n for n in chosen if re.search(pat, n)]
            if not kept:
                raise SystemExit(f"suite.py: --only {pat!r} matched nothing")
            chosen = kept
    if not chosen:
        raise SystemExit("suite.py: nothing selected")
    return chosen


def plan_for(names, opts):
    """Expand selected test names into jobs, and validate the dep graph."""
    jobs, per_test = [], {}
    for name in names:
        spec = REGISTRY[name]
        if is_disabled(spec):
            # No job, so nothing is spawned, nothing is capped and nothing is
            # reserved — and `per_test` still carries the name with 0 jobs, which
            # is what `execute` reads to seed the DISABLED status and what keeps
            # the name in `report`'s counters. A fanout is the same case with 45
            # jobs' worth of `items` to not expand: expansion is skipped wholesale
            # rather than per item.
            per_test[name] = 0
            continue
        if isinstance(spec, Fanout):
            items = list(spec.items() if callable(spec.items) else spec.items)
            if not items:
                raise SystemExit(f"suite.py: fanout {name!r} has no items")
            for item in items:
                cmd = [a.replace('{file}', item) for a in spec.cmd]
                jobs.append(Job(spec, label=item, cmd=cmd,
                                cwd=spec.cwd, env=spec.env))
            per_test[name] = len(items)
        else:
            jobs.append(Job(spec, cwd=spec.cwd, env=spec.env))
            per_test[name] = 1

    for d in {d for j in jobs for d in j.spec.deps}:
        if d not in REGISTRY:
            raise SystemExit(f"suite.py: unknown dependency {d!r}")

    # Cycle check: a cycle would otherwise look like "waiting forever".
    colour: dict[str, int] = {}

    def visit(n, stack):
        if colour.get(n) == 2:
            return
        if colour.get(n) == 1:
            raise SystemExit("suite.py: dependency cycle: "
                             + " -> ".join(stack + [n]))
        colour[n] = 1
        for d in REGISTRY[n].deps:
            visit(d, stack + [n])
        colour[n] = 2

    for n in per_test:
        visit(n, [])
    return jobs, per_test


# ── Scheduling ───────────────────────────────────────────────────────────────
# The screen gets a heartbeat rather than a line per job: on a 40-minute gate
# the useful thing to watch is "still moving, nothing broken", and a PASS line
# per job is exactly the noise that makes people scroll past the one FAIL.
HEARTBEAT_SECONDS = 30

# The dep statuses a job may proceed on. PASS is the ordinary case; DISABLED is
# in here because a disabled test was never run, so it has no verdict to hand
# on — see "Disabled tests" for why its dependents run rather than skip.
DEP_SATISFIED = (PASS, DISABLED)


def execute(jobs, per_test, opts, log: Log):
    """Run the plan. Returns (state, results, wall, peak_gb)."""
    order = {j.key: i for i, j in enumerate(jobs)}
    # A disabled test has no job, so nothing will ever `settle` it: its status
    # is seeded here, BEFORE the scheduler starts, which is also what makes a
    # job depending on one eligible instead of waiting for a verdict that is
    # never coming (see "Disabled tests" for why a dependent is not skipped).
    state: dict[str, str] = {n: DISABLED for n, k in per_test.items() if k == 0}
    resolved = dict.fromkeys(per_test, 0)
    results: dict[str, Result] = {}
    waiting = {j.key: j for j in jobs}
    done = 0
    total = len(jobs)
    t0 = time.time()
    last_beat = t0
    peak_seen = 0.0
    lock = threading.Lock()

    def settle(name, status):
        """Fold one job's result into its test. A test is only as good as its
        WORST job, and the fold is cumulative, not last-writer-wins: with 45
        files in a fanout, taking only the last job to finish would report a
        sweep that failed on file 3 as green because file 45 passed.
        """
        resolved[name] += 1
        prev = state.get(name)
        state[name] = max([s for s in (prev, status) if s],
                          key=lambda s: _RANK.get(s, 0))

    with ThreadPoolExecutor(max_workers=opts.jobs,
                            thread_name_prefix='suite') as pool:
        running: dict[object, Job] = {}
        exclusive_running = False
        while waiting or running:
            for fut in [f for f in running if f.done()]:
                job = running.pop(fut)
                res = fut.result()
                with lock:
                    results[job.key] = res
                    done += 1
                    peak_seen = max(peak_seen, res.peak_gb or 0.0)
                    settle(job.spec.name, res.status)
                log.line(_line(job, res, done, total, len(running)))
                if res.status != PASS:
                    _announce(log, job, res, opts)
            exclusive_running = any(j.excl for j in running.values())

            ready, blocked = [], []
            for key in sorted(waiting, key=lambda k: order[k]):
                job = waiting[key]
                if any(d not in state for d in job.spec.deps):
                    continue                     # a dep is still running
                if all(state[d] in DEP_SATISFIED for d in job.spec.deps):
                    ready.append(job)
                else:
                    blocked.append(job)
            # A test whose dep failed never runs — make's behaviour, and the
            # reason a broken stage1 does not produce six confusing stage2
            # errors instead of one. DISABLED is in DEP_SATISFIED, not here:
            # a disabled dep produced no verdict to propagate, and skipping on
            # it would silently stop work that has nothing to do with the bug
            # the doc is tracking.
            for job in blocked:
                del waiting[job.key]
                failed = [d for d in job.spec.deps
                          if state[d] not in DEP_SATISFIED]
                res = Result(SKIP, detail='dependency did not pass: '
                             + ', '.join(f'{d}={state[d]}' for d in failed))
                with lock:
                    results[job.key] = res
                    done += 1
                    settle(job.spec.name, SKIP)
                log.line(_line(job, res, done, total, len(running)))

            if waiting and not running and not ready:
                # Nothing running, nothing ready: a dependency no job in this
                # plan can ever satisfy (a test whose dep was not selected).
                # Say so instead of spinning.
                job = sorted(waiting.values(), key=lambda j: order[j.key])[0]
                missing = [d for d in job.spec.deps if d not in state]
                res = Result(ERROR, detail='dependency not selected: '
                             + ', '.join(missing))
                del waiting[job.key]
                with lock:
                    results[job.key] = res
                    settle(job.spec.name, ERROR)
                _announce(log, job, res, opts)
                if not waiting:
                    break

            launch = []
            if ready and not exclusive_running:
                exclusive = [j for j in ready if j.excl]
                if exclusive and running:
                    # Drain first. Letting unrelated work start would mean the
                    # 55 GB job never gets a quiet machine, which is the one
                    # thing it needs.
                    pass
                elif exclusive:
                    first = exclusive[0]
                    launch = [first] + [j for j in ready
                                        if j.spec is first.spec and j is not first]
                else:
                    launch = ready
            # `not exclusive_running` above is the load-bearing half: once an
            # exclusive job is RUNNING, nothing else may start until it is
            # done. Without that, the three ordinary jobs that were already
            # eligible when the exclusive one launched would start right after
            # it, and the 55 GB job would share the machine after all.
            for job in launch[:max(0, opts.jobs - len(running))]:
                del waiting[job.key]
                log.line(f'  RUN     {job.key}'
                         + ('   [exclusive: alone in this run]'
                            if job.excl else ''))
                if job.excl:
                    log.notice(f'  RUN     {job.key}  (exclusive)')
                running[pool.submit(run_job, job, opts, log)] = job
            if not launch and (running or waiting):
                now = time.time()
                if now - last_beat > HEARTBEAT_SECONDS:
                    last_beat = now
                    with lock:
                        log.notice(f'  ... {done}/{total} jobs done, '
                                   f'{len(running)} running, '
                                   f'{now - t0:.0f}s elapsed')
                time.sleep(0.05)

    _apply_expectations(per_test, state, log, results)
    return state, results, time.time() - t0, peak_seen


# ── Expected failures ───────────────────────────────────────────────────────
# A test registered with `expect='<why>'` is a KNOWN failure, recorded rather
# than hidden: it reports as EXPECTED with its reason, and it does not fail
# the run. This exists because a gate that is red on five known-broken things
# is a gate nobody reads, and a gate that is green because the five were
# deleted is worse than either.
#
# The anti-rot half is load-bearing and is why this is not just "ignore the
# result": an `expect`-marked test that PASSES is reported as a FAILURE
# ("now passing — drop the marker"). A marker nobody revisits is a bug
# quietly re-introduced, and this is the same reasoning as `checked_run.py`
# re-running a recorded failure instead of replaying it.
#
# Deliberately narrow about WHICH outcomes it forgives: only FAIL and ERROR,
# the two verdicts that mean "this test's subject is broken". Not RESOURCE
# (a memory ceiling is a fact about the machine, not a known bug — swallowing
# it would hide exactly the regression the caps exist to catch) and not
# TIMEOUT (a hang is its own failure mode and has never been triaged as
# expected for any test here). A marker also cannot rescue a SKIP: a test
# skipped because its dep failed has not been shown to fail, so there is
# nothing to forgive and its dep's own verdict stands.
def _apply_expectations(per_test, state, log, results=None):
    for name in per_test:
        spec = REGISTRY.get(name)
        reason = getattr(spec, 'expect', '') or ''
        if not reason:
            continue
        status = state.get(name)
        if status in (FAIL, ERROR):
            state[name] = EXPECTED
            log.notice(f'  EXPECTED {name}  ({reason})', force=True)
            drift = _expect_count_drift(spec, reason, results)
            if drift:
                # A marker that forgives FAIL/ERROR wholesale absorbs a NEW
                # failure inside an already-marked test without a word, and the
                # tally still says EXPECTED. The marker states its count, so
                # the count is checkable, and this is the same signal as the
                # case below for the same reason: both mean the marker no
                # longer describes the test.
                state[name] = FAIL
                log.notice(f'  FAIL     {name}  ({drift})', force=True)
        elif status == PASS:
            state[name] = FAIL
            log.notice(f'  FAIL     {name}  (marked expect={reason!r} but it '
                       f'PASSES — drop the marker and fix whatever it was '
                       f'waiting for)', force=True)


# A marker states its failing-case count in the prose the registry already
# spells: "3 failing: …" or "2 of 12: …". Both shapes are read from the reason
# rather than from a second field, because a second spelling of a number that
# is already written down is a number that will disagree with it.
_MARKER_FAILURES = re.compile(
    r'^\s*(?:bugs/[\w./-]+\.md\s*[—–-]\s*)?'
    r'(?P<n>\d+)\s+(?:of\s+(?P<total>\d+)|failing)\b', re.I)

# …and the count the run actually produced, from the summary line the test
# files in this tree print. Three shapes, because three families of harness
# print three: `Results: 9 passed, 3 failed`, `[x86_64] PASS=59 FAIL=1 of 60`,
# and `146/148 checks passed` (total minus passed). The LARGEST count any
# summary line reports is the one used, so a harness that prints an interim
# tally cannot be under-counted, and one that prints only a final line is read
# exactly.
_SUMMARY_FAILURES = (
    re.compile(r'\b(\d+)\s+passed,\s*(\d+)\s+failed\b'),
    re.compile(r'\bPASS=(\d+)\s+FAIL=(\d+)\b'),
    re.compile(r'\b(\d+)/(\d+)\s+checks passed\b'),
)


def marker_failures(reason: str):
    """The failing-case count an `expect=` reason claims, or None.

    None means the marker states no count, and this is a real answer rather
    than a failure: four markers in the registry describe a whole-job
    condition (`native-dumpfull`'s bootstrap pre-pass cost,
    `bootstrap-stage2-dumps`' silent-wrong-answer class, `ptrreg-boxed-str`'s
    segfault, `formal-struct`'s arity refusal) where "how many cases" is not
    the question. What is NOT allowed is for a marker that does state a count
    to be unchecked, and that is what `observed_failures` below is for.
    """
    m = _MARKER_FAILURES.search(reason or '')
    return int(m.group('n')) if m else None


def observed_failures(output: str):
    """The failing-case count a job's own output reports, or None.

    None when the harness printed no summary shape this knows, which is a
    LIMITATION and is reported as one rather than read as agreement: a marker
    whose count cannot be checked is not a checked marker.
    """
    best = None
    for rx, subtract in ((_SUMMARY_FAILURES[0], False),
                         (_SUMMARY_FAILURES[1], False),
                         (_SUMMARY_FAILURES[2], True)):
        for m in rx.finditer(output or ''):
            groups = m.groups()
            n = (int(groups[1]) - int(groups[0])) if subtract else int(groups[1])
            best = n if best is None else max(best, n)
    return best


def _expect_count_drift(spec, reason, results):
    """Why this EXPECTED verdict is not the one its marker described, or ''.

    Returns a message when the marker's claimed failing-case count and the
    count the run produced disagree, and '' otherwise — including when either
    side is unavailable, which is why the message says which.
    """
    claimed = marker_failures(reason)
    if claimed is None:
        return ''
    seen = None
    for key, res in (results or {}).items():
        if key == spec.name or key.startswith(spec.name + ':'):
            seen = res.output if res.output and (seen is None or
                                                len(res.output) > len(seen)) \
                else seen
    got = observed_failures(seen)
    if got is None:
        return (f'marked expect={reason!r} for {claimed} failing case(s), '
                f'but the run printed no failure count this runner can read, '
                f'so that count is UNCHECKED — print one of '
                f'"N passed, M failed" / "PASS=N FAIL=M" / "N/M checks '
                f'passed", or drop the number from the marker')
    if got != claimed:
        return (f'marked expect={reason!r} for {claimed} failing case(s), but '
                f'the run produced {got} — a NEW failure inside an '
                f'already-marked test is absorbed silently otherwise, so '
                f'update the marker (and its doc) or fix the case')
    return ''


def _announce(log: Log, job: Job, res: Result, opts):
    """A non-PASS job, on the screen and in the log: the tag, why, and enough
    of the output to recognise it. The full transcript is already in the log."""
    # An ERROR is usually "the run cannot do what you asked" (a dependency
    # that was not selected, a command that would not launch). That is worth
    # saying out loud even under -q, which asks for less noise, not for less
    # information about a run that did not happen.
    force = res.status == ERROR
    log.notice(f'  {_TAG.get(res.status, res.status):<8} {job.key}  '
               f'({res.secs:.0f}s){"  " + res.detail if res.detail else ""}',
               force=force)
    if res.status == RESOURCE and res.peak_gb is not None:
        log.notice(f'           peak {res.peak_gb:.1f} GB — killed for memory '
                   f'before finishing, so this says nothing about correctness',
                   force=force)
    if res.status in (FAIL, ERROR, TIMEOUT):
        log.line(f'  --- output: last 40 lines of {job.key} ---')
        log.raw(_screen_excerpt(res.output, 40))


_TAG = {PASS: 'ok', FAIL: 'FAIL', SKIP: 'skip', RESOURCE: 'RESOURCE',
        TIMEOUT: 'TIMEOUT', ERROR: 'ERROR', EXPECTED: 'EXPECTED',
        DISABLED: 'DISABLED'}


# ── Disabled tests: registered, not run, and the bug doc is the switch ───────
# `expect=` above says "this test is known to fail"; it still RUNS it, every
# gate, to find out. That is the right trade for a cheap test and the wrong one
# for an expensive one. `ab-native` measured a 20.5 GB peak, held the `program`
# class — 55 of a 96 GB machine-wide budget — and was exclusive in the run while
# it did it, and it was registered `expect=` on top of a byte-parity divergence
# (30/30 identical on 2026-09-21, red since) that nobody was going to fix that
# day. So every gate paid 20 GB and minutes to be told the thing its own marker
# already said, and the jobs queued behind it paid for that too. A known failure
# must not be run at insane cost.
#
# `disabled='bugs/<doc>.md'` is the other half of that sentence: the test is
# REGISTERED (so it is in `--list`, in the plan, in the buckets, and in the
# tally) and NOT RUN (no process, no reservation, no wall time, no peak). It
# reports as its own status, DISABLED, with the doc, and it does not fail the
# run.
#
# The anti-rot is the part that makes this safe, and it is deliberately
# mechanical: the doc IS the switch. The repo's rule is that a fully fixed bug's
# doc is DELETED (CLAUDE.md, "Bug docs"), so the disappearance of the doc is
# exactly the event "the bug is fixed". `disabled_problems` turns that into a
# refusal to load the registry, with the fix spelled out — so a fix cannot land
# without turning the test back on, and a disabled test cannot stay off forever
# because nobody remembers it. A doc that never existed is the same missing file
# with the opposite meaning (a typo in the marker), so the two are told apart by
# asking git, and both fail.
#
# A dependency of a disabled test is NOT skipped by it, deliberately. A
# disabled test produced no verdict, so there is nothing to propagate and
# nothing to forgive: a dependent that treated DISABLED as a failure would be
# skipped behind a verdict that is never coming, which is how a decision about
# one test silently stops work that has nothing to do with it. It runs on its
# own merits. The case where that is wrong — a dependent that needs an artifact
# only a disabled step builds — is a registration error, not a scheduling one,
# and no such case exists in the registry (the one disabled job, `ab-native`,
# is a leaf that nothing depends on).
def is_disabled(spec) -> bool:
    """Is this spec registered but not to be run? One definition, read by the
    planner, the ledger, `--list`, `--dry-run` and the estate check, so "is it
    disabled" cannot have five answers."""
    return bool(getattr(spec, 'disabled', '') or '')


def disabled_reason(spec) -> str:
    """The one-line explanation a screen/section line carries for a disabled
    test. Its shape mirrors `expect`: a marker without a reason is a silenced
    test, and this one names both the cost saved and the switch. Tolerates a
    spec that is not in the registry (a synthetic name in a report test), so it
    degrades to the part that does not need the path rather than to a sentence
    with a hole in it."""
    doc = (getattr(spec, 'disabled', '') or '').strip()
    return (f'not run: known to fail'
            + (f' while {doc} is open' if doc else '')
            + ' — the doc is the switch, so deleting it (what a fix does) '
              'turns this test back on')


# `existed` is a parameter, not a global, and for one reason: telling "the doc
# was deleted because the bug was fixed" from "this path was never a file" is
# the only step here that has to leave the filesystem, and a seam for it is what
# lets the estate check in test_suite.py exercise both answers without needing a
# deleted file to exist on disk. Everything else is a pure function of the
# registry and a directory.
#
# Memoised because the check runs at import, and a repo whose history is long
# makes `git log -- <path>` a real walk: N disabled jobs would otherwise be N
# walks on every invocation of the runner, including `--list`. A miss is not
# re-asked within a process either way, since the answer cannot change while it
# is running.
_DOC_HISTORY: dict[tuple[str, str], 'bool | None'] = {}


def _doc_in_git_history(path, root) -> bool | None:
    """Did `path` ever exist in this repository's history? None if unknowable.

    None (git missing, not a repository, or the call failed) is not a pass and
    not a fail: the caller reports the weaker message, because "the doc is
    gone" is the finding either way and the typo reading is a refinement of it.
    """
    key = (root, path)
    if key not in _DOC_HISTORY:
        try:
            p = subprocess.run(['git', 'log', '--format=%H', '--', path],
                               cwd=root, capture_output=True, text=True,
                               timeout=30)
        except (OSError, subprocess.SubprocessError):
            p = None
        _DOC_HISTORY[key] = None if p is None or p.returncode != 0 \
            else bool(p.stdout.strip())
    return _DOC_HISTORY[key]


def disabled_problems(registry=None, root=None, existed=None) -> list[str]:
    """Every reason a `disabled=` marker in the registry is wrong, as text.

    All three rules in one function, called at import (so a stale marker stops
    the runner outright — the loudest form of the check, the same one the tally
    invariant uses) and asserted in test_suite.py against synthetic registries
    for each rule.

      1. a disabled test whose doc no longer EXISTS: the bug is fixed, so the
         test must be turned back on. This is the anti-rot, and it is the
         failure mode that would otherwise be invisible: a fixed bug leaves a
         doc nobody reads and a test nobody runs.
      2. a disabled test naming a doc that NEVER existed: the path is a typo,
         and a typo that reads as rule 1 would send the next reader to
         "re-enable a test whose bug was never filed".
      3. a job with BOTH `expect=` and `disabled=`: the two say opposite things
         about whether it runs, and a job that both runs and does not is a
         registration nobody can read. Pick one — `expect` for a cheap known
         failure (its anti-rot works), `disabled` for one too expensive to run.
    """
    registry = REGISTRY if registry is None else registry
    root = REPO if root is None else root
    if existed is None:
        existed = lambda p: _doc_in_git_history(p, root)        # noqa: E731
    out = []
    for name, spec in sorted(registry.items()):
        doc = (getattr(spec, 'disabled', '') or '').strip()
        if not doc:
            continue
        if (getattr(spec, 'expect', '') or '').strip():
            out.append(f'{name}: has BOTH expect= and disabled=; pick one — '
                       f'expect runs the test and forgives FAIL/ERROR, '
                       f'disabled does not run it at all')
            continue
        if os.path.isabs(doc) or doc.startswith('..'):
            out.append(f'{name}: disabled={doc!r} is not a repo-relative path '
                       f'pointing into bugs/')
            continue
        if os.path.exists(os.path.join(root, doc)):
            continue
        ever = existed(doc)
        if ever is False:
            out.append(f'disabled test {name}: its bug doc {doc} does not '
                       f'exist and never has — that is a typo in the marker, '
                       f'and a test disabled against a doc nobody wrote is a '
                       f'test nobody is tracking')
        else:
            out.append(f'disabled test {name}: its bug doc {doc} is gone, so '
                       f'the bug is fixed: turn the test back on (drop the '
                       f'disabled=, and expect= if it is red again)')
    return out


_disabled_problems = disabled_problems()
if _disabled_problems:
    raise SystemExit(
        'suite.py: the registry\'s `disabled=` markers are wrong:\n'
        + ''.join(f'  - {p}\n' for p in _disabled_problems)
        + '  A disabled test is one thing the bug doc is the switch for; see\n'
          '  "Disabled tests" above and CLAUDE.md, "Known-failing tests".')


def _line(job, res, done, total, active):
    extra = []
    if res.cached:
        extra.append('cached')
    if res.peak_gb is not None:
        extra.append(f'peak {res.peak_gb:.1f} GB')
    tail = f"  [{', '.join(extra)}]" if extra else ''
    return (f'[{done:>3}/{total}] {_TAG.get(res.status, res.status):<8} '
            f'{job.key:<44} {res.secs:7.1f}s  ({active} running){tail}')


# ── Reporting ────────────────────────────────────────────────────────────────
# The screen gets the failures and one tally. Everything per-test — a PASS
# line each, with argv, exit code, duration and measured peak — is in the log.
def report(names, state, results, wall, peak, opts, log: Log):
    # Group the run's tests into the tally's counters, one lookup per test, so
    # a test cannot end up in a bucket nobody reads.
    by_count = {row.count: [] for row in TALLY}
    unaccounted = []
    for name in names:
        row = TALLY_ROW.get(state.get(name))
        if row is None:
            unaccounted.append((name, state.get(name)))
        else:
            by_count[row.count].append(name)

    # The invariant, checked rather than assumed: the counters must add up to
    # the number of tests, and every test must be in one. This is the defect
    # the table above was rebuilt to prevent, and it is verified here so that a
    # summary that cannot count the run says so instead of looking authoritative.
    # A plain `if` and not an `assert`: an assertion is removed by `python -O`,
    # and the one thing this must never be is absent from a run.
    total = sum(len(m) for m in by_count.values())
    if unaccounted or total != len(names):
        for name, status in unaccounted:
            log.notice(f'  TALLY BUG  {name}  status={status!r}'
                       + ('   (no result at all)' if status is None
                          else '   (a status the tally has no row for)'),
                       force=True)
        log.notice(f'  TALLY BUG  the counters sum to {total} over {len(names)} '
                   f'tests, so this summary is NOT a count of the run.',
                   force=True)

    cached = sum(1 for r in results.values() if r.cached)
    secs = {n: max([r.secs for k, r in results.items()
                    if k.split(':')[0] == n] or [0.0]) for n in names}

    log.line('')
    log.line('=' * 78)
    log.line('PER-TEST')
    for name in names:
        rows = sorted((k, r) for k, r in results.items() if k.split(':')[0] == name)
        log.line(f'  {_TAG.get(state.get(name), "?"):<8} {name:<32} '
                 f'{len(rows)} job(s)')
        spec = REGISTRY.get(name)
        if state.get(name) == DISABLED:
            # No rows and no jobs, and that is the finding, not a gap: say so
            # here rather than printing an empty "0 job(s)" line that reads like
            # a test whose jobs all vanished.
            log.line(f'      {DISABLED:<8} not run — {disabled_reason(spec)}')
        for key, r in rows:
            extra = []
            if r.cached:
                extra.append('cached')
            if r.peak_gb is not None:
                extra.append(f'peak {r.peak_gb:.1f} GB')
            log.line(f'      {_TAG.get(r.status, r.status):<8} {key:<44} '
                     f'{r.secs:8.1f}s {", ".join(extra)}')
            if r.detail:
                log.line(f'               {r.detail}')

    parts = [f'{len(by_count[row.count])} {row.count}' for row in TALLY
             if by_count[row.count] or row.zero]
    # Every job's measured peak, ranked, once per run. The per-test table above
    # already records each one next to the job it belongs to, which is the
    # right place to look up "what did `formal-x86-endtoend` use"; this is the
    # right place to answer "how big is the biggest thing this runner starts,
    # and how close did it get to its class" — which is the question the
    # memclasses are guesses at, and which had no answer at all until every
    # job was wrapped. Without it, choosing a class is a round number.
    #
    # And it is the INPUT to the next round of choosing: a run whose peak
    # differs from `MEASURED_PEAK_GB` is a run that says a class is wrong, in
    # one of the two directions, and the peak line above is where the next
    # table comes from. Log, not screen: it is 20 lines of numbers nobody
    # wants during a failing run and everybody wants once the run is green.
    measured = sorted(((r.peak_gb, k) for k, r in results.items()
                       if r.peak_gb is not None), reverse=True)
    if measured:
        log.line('')
        log.line(f'MEMORY: peak RSS of every job, largest first '
                 f'({len(measured)} of {len(results)} measured; a cached hit '
                 f'starts nothing and has none)')
        for peak_gb, key in measured[:20]:
            spec = REGISTRY.get(key.split(':')[0])
            cls = memclass_for(spec) if spec is not None else '?'
            ceiling = memlimit(cls) if spec is not None else 0.0
            used = f'{100 * peak_gb / ceiling:3.0f}%' if ceiling > 0 else '  - '
            log.line(f'  {peak_gb:6.1f} GB  {key:<44} {cls:<7} '
                     f'ceiling {ceiling:>5.0f} GB  {used} of it')
        worst = measured[0]
        log.line(f'  worst: {worst[1]} at {worst[0]:.1f} GB')
        # The two things a reader can do with this run's numbers, both of which
        # used to be impossible: a class that this run's peak does not fit (a
        # RESOURCE verdict waiting to happen), and a recorded peak this run
        # contradicts (the table in MEASURED_PEAK_GB is a snapshot, and a
        # snapshot that nobody compares to the next run is a rumour).
        short = class_shortfalls({k: p for p, k in measured})
        drift = peak_drift({k: p for p, k in measured})
        for name, peak, cls, ceiling in short:
            log.line(f'  CLASS TOO SMALL: {name} peaked at {peak:.1f} GB and '
                     f'its {cls} class is {ceiling:.0f} GB — the next run will '
                     f'be RESOURCE-capped')
        for name, peak, old in drift:
            log.line(f'  PEAK DRIFT: {name} measured {peak:.1f} GB here, '
                     f'{old:.1f} GB in MEASURED_PEAK_GB — update the table (and '
                     f'the class with it)')

    # The test count is in the tail as well as the job count, because those are
    # the two numbers a reader adds up, and the job count alone is what made the
    # dropped TIMEOUT impossible to check by eye: that summary reported
    # "177 jobs" for 39 tests and nothing on the line said so.
    tail = (f'{len(names)} tests, {len(results)} jobs, {cached} replayed from '
            f'cache, {wall:.1f}s wall')
    if peak:
        tail += f', peak {peak:.1f} GB'
    tally = f'suite: {", ".join(parts)}  ({tail})'
    log.line('')
    log.line(tally)

    if not opts.quiet:
        print()
        print('─' * 78)
        # A counter can hold more than one status (FAILED holds FAIL, ERROR and
        # TIMEOUT). A member whose status is not the counter's plain one is
        # tagged, per member rather than per section: which of the failures was
        # the hang is the first thing a reader needs, and a section of names
        # cannot say it — nor can a section-level tag, which is absent exactly
        # when a section holds nothing but the one status worth naming.
        for row in TALLY:
            members = by_count[row.count]
            if not members or not row.header:
                continue
            print(f'{row.header}:')
            for name in members:
                spec = REGISTRY.get(name)
                why = (getattr(spec, 'expect', '') or ''
                       or (disabled_reason(spec) if is_disabled(spec) else ''))
                status = state[name]
                # A disabled test has no duration and no peak, and printing
                # "(0s)" for it would be a claim it ran in no time at all.
                # "not run" is the truth and the reason is on the same line.
                how = '(not run)' if status == DISABLED else f'({secs[name]:.0f}s)'
                print(f'  {name}  {how}'
                      + (f'  [{_TAG.get(status, "?")}]'
                         if status != row.statuses[0] else '')
                      + (f'  — {why}' if why else ''))
    print(tally + (f'   log: {log.path}' if log.path else ''))
    # Non-zero for any member of a counter that `fails`, and for a summary that
    # could not account for every test: a run that cannot count itself has not
    # earned an exit code of 0, whatever else it found.
    bad = (unaccounted or total != len(names)
           or any(by_count[row.count] and row.fails for row in TALLY))
    return 1 if bad else 0


def buckets_containing(name):
    """Every bucket that reaches `name`, directly or through another bucket."""
    out = []

    def reaches(bucket, target, seen):
        if bucket in seen:
            return False
        for m in BUCKETS[bucket]:
            if m == target or (m in BUCKETS and reaches(m, target, seen + (bucket,))):
                return True
        return False

    for b in BUCKETS:
        if reaches(b, name, ()):
            out.append(b)
    return out


def print_wrapper_prefix(which: str, label: str, cls: str) -> int:
    """The `tool ... --` prefix for one Makefile recipe, as a shell string.

    Printed for `$(call memslot,<label>,<class>)` so BOTH numbers come from
    this file — the memclass ceiling from MEMCLASS, and the reservation the
    ledger is asked for — rather than from numbers typed into recipes, which is
    how the coverage rotted in the first place: `make mojoc` and `make
    stage2/mojo` each had their own idea about memory and neither had any.

    Two wrappers, one spelling of each, and they compose: `memslot` reserves
    the gigabytes and then runs the job under `memcap` at exactly what it
    reserved, so a hand-run `make mojoc` both queues behind whatever the gate
    is doing and cannot exceed the gigabytes it was given.

    Empty output is meaningful and is the whole reason this is a function
    rather than a variable: `MEMLIMIT_GB=0` means "no ceiling anywhere", and
    a recipe that expanded to `memcap --limit-gb 0` would kill the first
    process it sampled — or to `memslot --gb 0`, which reserves nothing and
    therefore admits everything, i.e. exactly the collapse. The label is
    quoted because it is spliced into a shell command line.
    """
    try:
        limit = memlimit(cls)
    except KeyError as exc:
        print(f'suite.py: {exc}', file=sys.stderr)
        return 2
    if limit <= 0:
        return 0
    flag, tool = {'memslot': ('--gb', 'memslot.py'),
                  'memcap': ('--limit-gb', 'memcap.py')}.get(which, (None, None))
    if flag is None:
        print(f'suite.py: no wrapper {which!r}; known: memslot, memcap',
              file=sys.stderr)
        return 2
    return print(f'{shlex.quote(PY)} {shlex.quote(os.path.join(HERE, tool))}'
                 f' {flag} {limit:g} --label {shlex.quote(label)} --')


def print_list():
    print('MEMCLASS (GB ceiling, whole process tree; and what each job '
          'RESERVES from the machine-wide budget):')
    for name, gb in sorted(MEMCLASS.items(), key=lambda kv: kv[1]):
        print(f'  {name:<8} {gb:>4}')
    print(f'  a cmd/make test with no mem= runs under {DEFAULT_MEMCLASS!r}')
    print(f'  one machine-wide budget of {memslot_budget():g} GB '
          f'(MEMSLOT_BUDGET_GB); every job reserves its class before it starts, '
          f'and EXCLUSIVE means alone in THIS RUN (a shared-artifact '
          f'statement) — a class over half the budget already means alone on '
          f'the machine')
    print(f'  MEMLIMIT_GB=0 removes both the ceiling and the reservation')
    if os.environ.get('MEMLIMIT_GB'):
        print(f'  MEMLIMIT_GB={os.environ["MEMLIMIT_GB"]} overrides all of the above')
    for line in memclass_report_lines():
        print(line)
    print('\nTESTS:')
    for name in sorted(REGISTRY):
        spec = REGISTRY[name]
        cls = memclass_for(spec)
        # The ceiling, not the class name: `--list` is the thing a reader checks
        # a new registration against, and "mem=module" says nothing about
        # whether the number is 24 or an override of 96.
        cap = f'mem={cls}={memlimit(cls):g}GB'
        cap += '*' if not spec.mem else ''          # * = the default class
        peak = measured_peak(name)
        if peak:
            cap += f' peak={peak[0]:g}GB'
        if isinstance(spec, Fanout):
            how = f'fanout x{len(spec.items)} {cap}'
        else:
            how = f'{spec.driver:<4} {cap}'
        if spec.excl:
            how += ' EXCLUSIVE'
        if getattr(spec, 'cache', False):
            how += ' cached'
        if getattr(spec, 'j', False):
            how += ' -j'
        if getattr(spec, 'artifact', None):
            how += f' artifact={spec.artifact}'
        if getattr(spec, 'expect', ''):
            how += ' EXPECTED-FAIL'
        if is_disabled(spec):
            # The class and peak stay on the line above: they are what the job
            # will cost the day it is turned back on. What it costs TODAY is
            # this, and it is the reason the marker exists.
            how += ' DISABLED reserves 0'
        print(f'  {name:<30} {how:<34} ['
              f'{",".join(buckets_containing(name))}]')
        if spec.desc:
            print(f'  {"":<30} {spec.desc}')
        if getattr(spec, 'memwhy', ''):
            print(f'  {"":<30} mem={cls} is over the {MEM_DEBT_GB:g} GB line: '
                  f'{spec.memwhy}')
        if getattr(spec, 'expect', ''):
            print(f'  {"":<30} expected to fail: {spec.expect}')
        if is_disabled(spec):
            print(f'  {"":<30} DISABLED: {disabled_reason(spec)}')
        if spec.deps:
            print(f'  {"":<30} after: {", ".join(spec.deps)}')
    print('\nBUCKETS (a bucket may contain other buckets; each test runs once):')
    for b, members in BUCKETS.items():
        n = len(expand_bucket(b))
        print(f'  {b:<14} {n:>2} tests: {", ".join(members)}')
    return 0


def expand_bucket(name, _seen=None):
    """Every test name a bucket reaches, transitively, de-duplicated."""
    _seen = _seen or set()
    if name in _seen or name not in BUCKETS:
        return []
    _seen = _seen | {name}
    out = []
    for m in BUCKETS[name]:
        out += [m] if m in REGISTRY else expand_bucket(m, _seen)
    seen, uniq = set(), []
    for n in out:
        if n not in seen:
            seen.add(n)
            uniq.append(n)
    return uniq


def print_plan(names, opts):
    jobs, per_test = plan_for(names, opts)
    depth: dict[str, int] = {}

    def d(n, seen=()):
        if n not in depth:
            deps = [x for x in REGISTRY[n].deps if x not in seen]
            depth[n] = 0 if not deps else 1 + max(d(x, seen + (n,)) for x in deps)
        return depth[n]

    print(f'{len(per_test)} tests, {len(jobs)} jobs, -j{opts.jobs}\n')
    for n in names:
        k = per_test[n]
        spec = REGISTRY[n]
        if is_disabled(spec):
            # Planned, and explicitly not run: a name in the plan with no jobs
            # under it would read as an accident, and the reservation it does
            # NOT take is the thing a reader of this output needs to see.
            print(f'{"  " * d(n)}{n}  (DISABLED: not run, 0 jobs, reserves '
                  f'{reserved_gb(spec):g} GB)  — {disabled_reason(spec)}')
            continue
        mark = '  [exclusive]' if spec.excl else ''
        print(f'{"  " * d(n)}{n}  ({k} job{"s" if k != 1 else ""}){mark}')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='suite.py', description=__doc__.split('\n')[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('names', nargs='*', default=['check'],
                    help='buckets and/or test names (default: the check bucket)')
    ap.add_argument('-j', '--jobs', type=int, default=os.cpu_count() or 1,
                    help='parallel slots (default: ncpu). -j1 runs strictly '
                         "serially and streams each job's output live.")
    ap.add_argument('-v', '--verbose', action='store_true',
                    help="also stream every PASSing job's output")
    ap.add_argument('-q', '--quiet', action='store_true',
                    help='print the tally only')
    ap.add_argument('-o', '--log', default=DEFAULT_LOG,
                    help=f'per-run detail log (default {DEFAULT_LOG}; '
                         f'"-" to discard it)')
    ap.add_argument('--keep-output', action='store_true',
                    help="put PASSing jobs' output in the log too, not just "
                         'failures')
    ap.add_argument('--no-cache', action='store_true',
                    help='re-run cached tests instead of replaying them '
                         '(fresh results are still published)')
    ap.add_argument('--only', action='append', metavar='RE',
                    help='within the selected buckets, keep only tests whose '
                         'name matches RE (repeatable)')
    ap.add_argument('--timeout', type=float, default=DEFAULT_JOB_TIMEOUT_S,
                    help='per-job timeout in seconds (default: %d)' % DEFAULT_JOB_TIMEOUT_S)
    ap.add_argument('--list', action='store_true',
                    help='print the registry and exit')
    ap.add_argument('--prefix', nargs=3, metavar=('WRAPPER', 'LABEL', 'CLASS'),
                    help='print the wrapper prefix for LABEL at CLASS\'s ceiling '
                         '(empty when MEMLIMIT_GB=0), and exit. WRAPPER is '
                         'memslot or memcap; this is how the Makefile spells '
                         'the wrapper once instead of restating the class '
                         'table: memslot reserves the gigabytes out of the '
                         'machine-wide budget and runs the job under memcap '
                         'at exactly what it reserved.')
    ap.add_argument('--dry-run', action='store_true',
                    help='print the plan and its ordering, run nothing')
    opts = ap.parse_args(argv)
    if opts.jobs < 1:
        ap.error('-j must be >= 1')
    if opts.prefix:
        return print_wrapper_prefix(*opts.prefix)
    if opts.list:
        return print_list()
    names = select(opts.names, opts)
    if opts.dry_run:
        return print_plan(names, opts)

    log = Log(None if opts.log == '-' else opts.log, quiet=opts.quiet)
    try:
        return _run_all(names, opts, log)
    finally:
        log.close()


def _run_all(names, opts, log: Log):
    override = os.environ.get('MEMLIMIT_GB', '').strip()
    log.line('=' * 78)
    log.line(f'suite: {" ".join(sys.argv)}')
    for k, v in env_state(opts, names):
        log.line(f'  {k:<12} {v}')
    log.line(f'  {"memclass":<12} {MEMCLASS}')
    log.line(f'  {"budget":<12} {memslot_budget():g} GB reserved out of one '
             f'machine-wide ledger (MEMSLOT_BUDGET_GB); every job takes its '
             f'class before it starts')
    for line in memclass_report_lines():
        log.line('  ' + line)
    # Which enumeration produced the fan-out item list. The two differ in a way
    # that matters: the glob fallback picks up whatever transient files happen
    # to be in the repo root, which is the race this line exists to make
    # visible. A reader seeing `glob` in a log knows the sweep's item list was
    # not content-controlled.
    log.line(f'  {"fan-out":<12} {len(MOJO_FILES)} tracked *.mojo items'
             + ('' if _MOJO_FILES_ARE_TRACKED
                else '  (GLOB FALLBACK — not a git checkout)'))
    log.line('')

    if not opts.quiet:
        print(f'suite: {len(names)} tests, -j{opts.jobs}, '
              f'{"serial, output streamed" if opts.jobs == 1 else "parallel"}'
              + (f', MEMLIMIT_GB={override}' if override else '')
              + f', {memslot_budget():g} GB memory budget')
        if override in ('0', '0.0'):
            print('suite: MEMLIMIT_GB=0 — NO memory ceiling on anything, and '
                  'nothing is reserved. Please watch the machine.')

    jobs, per_test = plan_for(names, opts)
    for name in names:
        spec = REGISTRY[name]
        cls = memclass_for(spec)
        if is_disabled(spec):
            # The memclass and the peak still go in the log, and the
            # reservation is recorded as the 0 it is: a disabled job is a
            # record of what a job will cost, and the log is where a reader
            # looks up why this run was cheaper than the registry suggests.
            log.line(f'plan: {name}: DISABLED, 0 job(s), not run '
                     f'(bug doc {spec.disabled} is the switch) '
                     f'mem={cls}={memlimit(cls):g}GB when turned on, '
                     f'reserved {reserved_gb(spec):g} GB now')
            continue
        log.line(f'plan: {name}: {per_test[name]} job(s), driver='
                 f'{getattr(spec, "driver", "fanout")}'
                 + f' mem={cls}={memlimit(cls):g}GB'
                 + (' DEFAULT' if not spec.mem else '')
                 + (' EXCLUSIVE' if spec.excl else '')
                 + (f' after {", ".join(spec.deps)}' if spec.deps else ''))
    log.line('')

    state, results, wall, peak = execute(jobs, per_test, opts, log)
    return report(names, state, results, wall, peak, opts, log)


if __name__ == '__main__':
    sys.exit(main())
