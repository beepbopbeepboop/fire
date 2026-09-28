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

Exclusive tests are dispatched only when nothing else is running, and while
one is running nothing else is started — which is what makes a 55 GB job safe
to leave running on a 128 GB box without anyone having to remember not to run
two at once.
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

# Every source the bootstrap stages dump: top-level *.mojo, mojo/*.mojo, and
# the core .py files. Same globs the Makefile's MOJO_FILES/PY_FILES used.
MOJO_FILES = (sorted(os.path.basename(p) for p in glob.glob(os.path.join(REPO, '*.mojo')))
             + sorted(os.path.relpath(p, REPO)
                      for p in glob.glob(os.path.join(REPO, 'mojo', '*.mojo'))))
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
# RESOURCE verdict instead of a machine-destroying one. The classes that are
# *known* to pass 10 GB are `program` and `stage`; those are the ones the cap
# is load-bearing for, and their numbers come from measurement:
#
#   program  a whole-transitive-closure self-compile (`--dump-full fire.py`,
#            the compiler's own ~180-module closure). Healthy -O2 peak measured
#            at 55.8 GB RSS; a runaway on 2026-09-26 passed 192 GB and had to
#            be killed by hand. 55 is the healthy peak, not a guess.
#   stage    one bootstrap stage: the closure plus `gcc -fgimple` over the
#            resulting 40 MB translation unit. The largest footprint ever
#            observed *completing* for a self-compile is ~96 GB (macOS peak
#            footprint, 2026-09-25 flag probe, all three -O levels); RSS runs
#            below that, so 96 does not fire on a healthy run.
#   module   a single module of that closure — one `--dump` of one source file,
#            natively. Growth here is cumulative over the closure rather than
#            per file (bugs/CODEGEN_bootstrap_resource_blowup.md), so this is
#            headroom, not a measurement.
#   small    a mojoc run over a snippet-sized input (the A/B corpus).
#
# Override with MEMLIMIT_GB (absolute, all classes) or MEMLIMIT_GB=0 (no cap at
# all, loudly).
MEMCLASS = {
    'small': 8,
    'module': 24,
    'program': 55,
    'stage': 96,
}


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


# ── Registry ─────────────────────────────────────────────────────────────────
class Spec:
    """One named test.

    driver  'cmd' | 'mem' | 'make'
    mem     memclass name; required iff driver == 'mem'
    deps    test names that must pass first
    extra   files whose content affects the outcome (feeds checked_run's key)
    cache   wrap in checked_run.py so an unchanged input replays its result
    j       forward `-j <slots>` to a command that has its own -j
    excl    needs the machine to itself
    reject  fail if this pattern appears in the output even on exit 0
    cwd    run in this repo-relative directory
    env     extra environment for this test's process
    artifact  a binary this step produces, cached by the content of its real
              inputs (see ArtifactCache); `inputs` are the files, on top of the
              self-host closure, that its key folds in
    """
    __slots__ = ('name', 'cmd', 'driver', 'mem', 'deps', 'extra', 'cache',
                 'j', 'excl', 'reject', 'timeout', 'cwd', 'env', 'desc',
                 'artifact', 'inputs', 'expect')

    def __init__(self, name, cmd, driver='cmd', mem=None, deps=(), extra=(),
                 cache=False, j=False, excl=False, reject=None, timeout=None,
                 cwd=None, env=None, desc='', artifact=None, inputs=(),
                 expect=''):
        self.name, self.cmd, self.driver, self.mem = name, cmd, driver, mem
        self.deps, self.extra, self.cache = tuple(deps), tuple(extra), cache
        self.j, self.excl, self.reject = j, excl, reject
        self.timeout, self.cwd = timeout, cwd
        self.env, self.desc = dict(env or {}), desc
        self.artifact, self.inputs = artifact, tuple(inputs)
        self.expect = expect
        if driver == 'mem' and mem is None:
            raise ValueError(f"{name}: driver 'mem' without a memclass")
        if driver != 'mem' and mem is not None:
            raise ValueError(f"{name}: memclass {mem!r} on a non-mem driver")
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
    """
    __slots__ = ('name', 'cmd', 'items', 'cwd', 'env', 'mem', 'deps', 'excl',
                 'reject', 'timeout', 'desc', 'expect')

    def __init__(self, name, cmd, items, cwd=None, env=None, mem=None,
                 deps=(), excl=False, reject=None, timeout=None, desc='',
                 expect=''):
        self.name, self.cmd = name, list(cmd)
        self.items = list(items) if not callable(items) else items
        self.cwd, self.env, self.mem = cwd, dict(env or {}), mem
        self.deps, self.excl, self.reject = tuple(deps), excl, reject
        self.timeout, self.desc = timeout, desc
        self.expect = expect

        if mem is None:
            raise ValueError(f"{name}: a fanout runs the compiler per item; "
                             f"it needs a memclass")


REGISTRY: dict[str, object] = {}


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
test('runner', [PY, 'test_runner.py'], cache=True,
     extra=['test_runner.py', 'myinterpreter.py', 'fire.py', 'fire_main.py',
            RUNTIME_SRC, RUNTIME_HDR],
     desc='compile-and-execute runner over a hand-written corpus')
test('modcache', [PY, 'test_module_cache.py'], cache=True,
     extra=GIMPLE_SOURCES + ['test_module_cache.py', 'myinterpreter.py',
                             'fire.py', 'fire_main.py'],
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
test('rthdrscan', [PY, 'test_runtime_header_scan.py'], cache=True,
     extra=['test_runtime_header_scan.py', 'reflect.py', RUNTIME_SRC,
            RUNTIME_HDR, 'runtime/fire_sqlite3.h', 'runtime/fire_zlib.h',
            'runtime/fire_ssl.h', 'runtime/fire_ncurses.h',
            'runtime/fire_python.h'],
     desc='runtime header export scan sees every declaration')
test('selfhost', [PY, 'test_selfhost.py'], cache=True,
     extra=GIMPLE_SOURCES + ['fire_compiler.py', 'myinterpreter.py', 'fire.py',
                             'fire_main.py', 'test_selfhost.py'],
     desc='the compiler compiles itself to a linked binary, cleanly')
test('runtimediff', [PY, 'test_runtime_diff.py'], cache=True,
     extra=GIMPLE_SOURCES + ['fire_compiler.py', 'myinterpreter.py', 'fire.py',
                             'test_runtime_diff.py'],
     desc='interpreter vs JIT: identical stdout and exit code')
test('linkmode', [PY, 'test_link_mode.py'], cache=True,
     extra=GIMPLE_SOURCES + ['fire_compiler.py', 'myinterpreter.py', 'fire.py',
                             'driver.py', 'test_link_mode.py'],
     desc='the real driver.compile_program link-mode pipeline')
test('no-new-casts', [PY, 'test_no_new_container_casts.py'], cache=True,
     extra=GIMPLE_SOURCES + ['test_no_new_container_casts.py'],
     desc='grow-only allowlist on ad-hoc container casts (text scan)')
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
test('gimplerunner', [PY, 'test_gimple_runner.py'], cache=True,
     extra=GIMPLE_SOURCES + ['test_gimple_runner.py', 'build_config.py',
                             RUNTIME_SRC, RUNTIME_HDR, 'gimple_codegen.py'],
     desc='compile-and-execute: plain programs, structs, closures, stdlib calls')
test('gimplegenerators', [PY, 'test_gimple_generator_runner.py'], cache=True,
     extra=GIMPLE_SOURCES + ['test_gimple_generator_runner.py',
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
     extra=['test_examples_parse.py', 'fire_compiler.py'],
     desc='every formal/examples/*.mojo parses; decorator arg shapes distinct')

test('preflight', [PY, '-c',
                   'import fire_compiler, gimple_codegen; '
                   'assert fire_compiler.Parser; print("parser+codegen OK")'],
     desc='import-level smoke check of the parser and codegen')
# The runner tests itself. `make check` is a one-line recipe that hands the
# whole bucket to tools/suite.py, so a bug in the runner does not fail one
# test — it fails or falsely passes the entire gate. This is synthetic specs
# and synthetic commands: no toolchain, milliseconds, so it can be the first
# thing anyone runs when the runner is what changed.
test('suite-self-test', [PY, 'test_suite.py'], cache=True,
     extra=['test_suite.py', 'tools/suite.py', 'tools/procrun.py'],
     desc='the runner: drivers, deps, exclusivity, fanout, tally, log split')
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
# `bootstrap-stage2-dumps` (below) carries `expect=SELFHOST_STAGE2_STALL`.
# It used to carry the old `SELFHOST_SEGV` marker, and that reason string was
# MEASURED FALSE on 2026-09-27 and corrected rather than left to rot. The
# original SIGSEGV is fixed (BLOW.md §0): `./mojoc --dump-full` on a two-line
# program is now exit 0 / 12.1 MB / 94.6 M instructions, re-measured on this
# tree. What the stage2 dumps actually do now is NOT a segfault — the marker
# below names the real blocker, because a marker that says "segfault" would
# hide the real regression class: a silent-wrong-answer `mojo_unsupported_iter`
# no-op, which the runner flags per sub-job and which NO exit code reports.
#
# The marker is still correct to KEEP — the step's 47 sub-jobs do not all
# produce a byte-identical dump — but its reason now names the true upstream
# cause, which is the self-hosting bootstrap pre-pass's cost
# (bugs/CODEGEN_bootstrap_resource_blowup.md, localised 2026-09-27: 58.6 GB
# / 1.24 T instructions / SIGTRAP on a real self-host input, a never-frees
# accumulator of ~670M small objects).
SELFHOST_STAGE2_STALL = (
    'the self-hosted binary no longer segfaults (re-measured 2026-09-27: '
    'exit 0 on a two-line program, 12.1 MB, 94.6 M instructions) but still '
    'does not reproduce the reference dumps — sub-jobs return '
    '`mojo_unsupported_iter` no-ops or a wrong dump, a silent-wrong-answer '
    'class that no exit code reports. The upstream cause is the '
    'self-hosting bootstrap pre-pass cost: 58.6 GB / 1.24 T instructions on '
    'a real self-host input, localised (not fixed) in '
    'bugs/CODEGEN_bootstrap_resource_blowup.md, 2026-09-27 section')
# `ab-native`/`native-dumpfull` no longer segfault (verified 2026-09-27,
# BLOW.md §0) but are STILL red for a different, real reason: their corpora
# legitimately trigger this compiler's self-hosting bootstrap pre-pass
# (a genuine, do_imports=True sibling-import compile with files placed at
# the repo root on purpose — see test_ab_native.py's DUMP_FULL_TESTS
# docstring), and that pre-pass itself is extremely expensive per call
# (~15-30 GB, ~15-25s — see BLOW.md §0's "NOT closed" addendum for the
# measured repro and hot-stack profile: mojo_cstr_region_eq/
# mojo_set_add_int/_set_grow dominating, the same signature as the original
# bug this doc fixed, just now correctly SCOPED to only the cases that
# should trigger it at all). Update this reason (not just delete it) once
# that per-call cost is actually brought down — see BLOW.md for the
# specific next-step suggestions (cross-call caching across the three
# `_selfhost_*` seed passes within one process; degenerate-hashing check on
# the tokenizer's `MojoSet` usage).
SELFHOST_TOKENIZE_BLOWUP = (
    'no longer segfaults, but the self-hosting bootstrap pre-pass this '
    'corpus legitimately triggers costs ~15-30 GB / ~15-25s per call — see '
    'BLOW.md §0 "NOT closed" for the measured repro and root-cause status')
test('mojoc', ['mojoc'], driver='make', excl=True,
     artifact='mojoc', inputs=[MOJO_MAIN] + PY_FILES + [RUNTIME_SRC, RUNTIME_HDR],
     desc='build the one managed native compiler (-O2 -g0)')
test('ab-native', [PY, 'test_ab_native.py'], driver='mem', mem='small',
     deps=['mojoc'], excl=True, cache=True, extra=['test_ab_native.py'],
     expect=SELFHOST_TOKENIZE_BLOWUP,
     desc='python vs native codegen, byte-for-byte, over the A/B corpus')
test('native-dumpfull', [PY, 'test_native_dumpfull.py'], driver='mem',
     mem='program', deps=['mojoc'], excl=True, cache=True,
     extra=['test_native_dumpfull.py'],
     expect=SELFHOST_TOKENIZE_BLOWUP,
     desc="the native --dump-full ARTIFACT, diffed against the reference")

# ── stdlib ───────────────────────────────────────────────────────────────────
test('stdlib-tests', [PY, 'test_stdlib.py'],
     desc='every stdlib test/benchmark through interpreter and JIT')
# Fresh by design: reusing the built dylib would make "did this module fall
# back to source" unanswerable, and that skip count is the signal CLAUDE.md's
# gate step 2 asks for. The output path is now PER-ARCH --
# build/libmojostdlib.<arch>.dylib, not build/libmojostdlib.dylib -- because the
# architecture is part of the link key, so one file cannot hold both. Exclusive
# because it deletes and rewrites a shared artifact that other tests link
# against.
test('stdlib-dylib', [PY, '-c',
                      'import build_stdlib_dylib as b; b.build_stdlib()'],
     excl=True, timeout=3600,
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
test('sqliteruntime', [PY, 'test_sqlite3_runtime.py'],
     deps=['preflight'], timeout=600,
     desc='optional-unit link mechanism: derivation, probe, and every '
          'test_sqlite3*.mojo built+linked+RUN on both pipelines')

test('stdlib-syntax', [PY, 'compile_stdlib.py'], j=True, timeout=7200,
     desc='gcc -fsyntax-only on the generated GIMPLE, whole stdlib tree')

# ── bootstrap: an ordered graph, not one recipe ─────────────────────────────
# The 192 GB workload lives in here four times over (stage1's, stage2's and
# stage3's transitive dumps, plus gcc over the closure) and until now none of
# those four was capped — only check-native-dumpfull's one instance of the
# same workload was. Every step below that runs a mojoc, or the compiler over
# a whole closure, names a memclass.
test('bootstrap-clean', ['rm', '-rf', 'stage1', 'stage2', 'stage3'],
     desc='wipe the stage trees (see the Makefile note on stale artifacts)')

fanout('bootstrap-stage1-dumps',
       [PY, '../fire.py', '--dump', '../{file}'],
       items=BOOTSTRAP_INPUTS, cwd='stage1',
       env={'PYTHONPATH': '..'}, mem='module',
       deps=['bootstrap-clean'], reject='mojo_unsupported_iter',
       desc='stage1: python dumps every .mojo and core .py source')
# Must stay AFTER the per-file dumps above: that loop writes fire.ci into
# stage1/ from fire.py as a single module, and this transitive-closure dump
# has to be the last writer of that name or stage2 links a skeleton.
test('bootstrap-stage1-transitive',
     [PY, '../fire.py', '--dump-full', '../' + MOJO_MAIN],
     driver='mem', mem='program', cwd='stage1', env={'PYTHONPATH': '..'},
     deps=['bootstrap-stage1-dumps'],
     desc='stage1: the one transitive-closure fire.ci that stage2 compiles')

# The gcc -O0 -fgimple compile of the 40 MB closure into a real binary. Its
# artifact is cached by the content of stage1/fire.ci plus the runtime sources
# and the exact argv (BOOTSTRAP_OPT, the gcc, the link flags all fold in
# through the argv), which is a textbook content-addressed build: a miss costs
# a few minutes, and a wrong hit could not survive its own output being
# compared by `verify` a few steps later.
test('bootstrap-stage2-cc', ['stage2/mojo'], driver='make',
     deps=['bootstrap-stage1-transitive'],
     artifact='stage2/mojo', inputs=['stage1/fire.ci', RUNTIME_SRC, RUNTIME_HDR],
     desc='gcc -fgimple + link: stage1/fire.ci -> stage2/mojo')

fanout('bootstrap-stage2-dumps',
       ['./mojo', '--dump', '../{file}'],
       items=BOOTSTRAP_INPUTS, cwd='stage2',
       env={'MOJO_HOME': '..', 'PYTHONPATH': '..'}, mem='module',
       deps=['bootstrap-stage2-cc'], reject='mojo_unsupported_iter',
       expect=SELFHOST_STAGE2_STALL,
       desc='stage2: the compiled binary dumps every source')
# Same ordering constraint as stage1's: the per-file loop writes fire.ci into
# stage2/ from a single-module dump, so the closure dump has to go last or
# `verify` compares a full closure against a skeleton.
test('bootstrap-stage2-transitive',
     ['./mojo', '--dump-full', '../' + MOJO_MAIN],
     driver='mem', mem='program', cwd='stage2',
     env={'MOJO_HOME': '..', 'PYTHONPATH': '..'},
     deps=['bootstrap-stage2-dumps'],
     desc='stage2: the compiled binary compiles itself, transitively')

fanout('bootstrap-stage3-dumps',
       ['../stage2/mojo', '--dump', '../{file}'],
       items=BOOTSTRAP_INPUTS, cwd='stage3',
       env={'MOJO_HOME': '..', 'PYTHONPATH': '..'}, mem='module',
       deps=['bootstrap-stage2-transitive'], reject='mojo_unsupported_iter',
       desc='stage3: same binary, fresh dir (idempotency)')
test('bootstrap-stage3-transitive',
     ['../stage2/mojo', '--dump-full', '../' + MOJO_MAIN],
     driver='mem', mem='program', cwd='stage3',
     env={'MOJO_HOME': '..', 'PYTHONPATH': '..'},
     deps=['bootstrap-stage3-dumps'],
     desc='stage3: same binary again (idempotency of the closure)')

test('bootstrap-verify', [PY, 'tools/bootstrap_verify.py'],
     deps=['bootstrap-stage3-transitive'],
     desc='stage1 == stage2 == stage3 for every generated file')
test('bootstrap-validate', [PY, 'bootstrap-validate.mojo'],
     deps=['bootstrap-stage3-transitive'],
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
test('prooflib', [PY, '-c',
                  'import os, formal.lean as L; '
                  'L.ensure_library(L.find_lean(), '
                  'os.path.join(L._default_root(), "lib"))'],
     timeout=2400,
     desc='build lib/*.olean once — 27MB, ~80s, and 16-way duplicated '
          'without this step')

test('formal', [PY, 'test_formal.py'], j=True,
     deps=['preflight', 'prooflib'],
     desc='every formal/examples/*.mojo typechecks its generated Lean proof')
test('formal-run', [PY, 'test_formal_run.py'], deps=['preflight'],
     desc='formal arm64 executables that actually build AND run (no lean)')
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
test('formal-dylib', [PY, 'test_formal_dylib.py'],
     deps=['preflight', 'prooflib'],
     desc='formal dylib emission, Mach-O re-read, dlopen, prove')
test('formal-imports', [PY, 'test_formal_imports.py'],
     deps=['preflight', 'prooflib'],
     desc='formal import surface')
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

# ── the A/B sweep: Make's own job server, so driver='make' ─────────────────
test('ab-clean', ['ab-clean'], driver='make',
     desc='drop aside/ bside/ ab.mk and the per-file locks')
test('ab-aside', ['aside'], driver='make', deps=['ab-clean'],
     desc='per-file python-reference dumps for the whole A/B corpus')
test('ab-bside', ['bside'], driver='make', deps=['ab-aside'],
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
              'linkmode', 'no-new-casts', 'nonlocal', 'gimplerunner',
              'gimplegenerators', 'interporacle', 'examples-parse',
              'rthdrscan', 'runtimedylib', 'sqliteruntime',
              'formal-sweep-truth', 'formal-link-accounting', 'silentnoop'],

    # CLAUDE.md's documented quality gate, in full: the everyday gate, plus
    # every step that is slow, memory-hungry, or both. The heavyweight steps
    # are exclusive, so `gate` is safe to leave running on a 128 GB box even
    # though it will touch it.
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
    'native': ['mojoc', 'ab-native', 'native-dumpfull'],

    # The two stdlib build gates: the from-scratch dylib (whose "fell back to
    # source" count is the signal) and the whole-tree syntax check.
    'stdlib': ['stdlib-dylib', 'stdlib-syntax'],
    # The stdlib test/benchmark corpus, through interpreter and JIT. Not part
    # of the gate: it is a much longer sweep than a build check.
    'stdlib-corpus': ['stdlib-tests'],

    'proofs': ['formal', 'formal-call-proofgen',
               'formal-run', 'formal-dylib', 'formal-imports',
               'formal-sweep', 'formal-sweep-truth',
               'formal-link-accounting', 'formal-runtime-link', 'formal-x86',
               'formal-x86-endtoend', 'formal-x86-model'],
    'x86': ['formal-x86', 'formal-x86-endtoend', 'formal-x86-model'],
    'coroutine': ['coro', 'coro-nested-capture'],
    'smoke': ['preflight', 'suite-self-test'],
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


PASS, FAIL, SKIP, RESOURCE, TIMEOUT, ERROR, EXPECTED = (
    'pass', 'fail', 'skip', 'resource', 'timeout', 'error', 'expected')
# Worst-first, so one bad job decides a multi-job test's verdict. A plain FAIL
# outranks a RESOURCE one: a wrong answer is a more actionable report than a
# process that ran out of memory.
_RANK = {PASS: 0, SKIP: 1, RESOURCE: 2, TIMEOUT: 3, ERROR: 4, FAIL: 5}


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
    if isinstance(spec, Fanout):
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
               + ['--rerun-failures']
               + (['--no-cache'] if opts.no_cache else [])
               + ['--'] + cmd)
    if isinstance(spec, Spec) and spec.driver == 'mem':
        limit = memlimit(spec.mem)
        if limit > 0:
            # ABSOLUTE, not repo-relative: a `mem` job may run in another
            # directory (bootstrap's stage1/stage2/stage3 trees), and
            # `python3 tools/memcap.py` then resolves against THAT cwd and
            # dies with "can't open file .../stage1/tools/memcap.py" before
            # the wrapped command ever runs.
            cmd = [PY, os.path.join(HERE, 'memcap.py'),
                   '--limit-gb', str(limit),
                   '--label', job.key, '--'] + cmd
        elif isinstance(spec, Spec) and spec.mem:
            log_warn_no_cap(spec)
    if isinstance(spec, Spec) and spec.j:
        cmd = cmd + ['-j', str(opts.jobs)]
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
    if isinstance(spec, Spec) and spec.driver == 'mem':
        log.line(f'  memcap: {spec.mem} class, ceiling {memlimit(spec.mem)} GB')

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

    t0 = time.time()
    cwd = os.path.join(REPO, job.cwd) if job.cwd else REPO
    if job.cwd:
        # Created here, at execution time, rather than in the plan: a stage
        # directory has to exist by the time its first job runs, and the step
        # that wipes it (bootstrap-clean) runs before both.
        os.makedirs(cwd, exist_ok=True)
    try:
        run = procrun.spawn(cmd, cwd=cwd, env=env,
                            timeout=spec.timeout or opts.timeout,
                            stream=(opts.jobs == 1 or opts.verbose))
    except OSError as exc:
        return Result(ERROR, detail=f'could not launch: {exc}')
    secs = time.time() - t0
    peak = _peak_from(run.out)
    log.line(f'  exit: {run.rc}   secs: {secs:.1f}'
             + (f'   peak: {peak:.1f} GB' if peak is not None else ''))

    if run.timed_out:
        res = Result(TIMEOUT, secs, f'still running after '
                                    f'{spec.timeout or opts.timeout}s — killed',
                     peak_gb=peak, output=run.out)
    elif run.rc == 125 and isinstance(spec, Spec) and spec.driver == 'mem':
        # memcap's own exit code. A RESOURCE failure, not a verdict: the
        # process was killed for memory before it finished, so it says nothing
        # about whether the output was right.
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


def _peak_from(text):
    """The peak memcap reported, in GB, if this job was capped.

    Rounded away below 0.1 GB: memcap prints one decimal, so a 40 MB job
    reports "0.0 GB" and a stream of those is noise in a report whose whole
    point is that the big numbers stand out.
    """
    m = re.findall(r'peak (?:observed before the kill: )?([\d.]+) GB', text)
    peak = float(m[-1]) if m else None
    return peak if peak is not None and peak >= 0.1 else None


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


def execute(jobs, per_test, opts, log: Log):
    """Run the plan. Returns (state, results, wall, peak_gb)."""
    order = {j.key: i for i, j in enumerate(jobs)}
    state: dict[str, str] = {}
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
                if all(state[d] == PASS for d in job.spec.deps):
                    ready.append(job)
                else:
                    blocked.append(job)
            # A test whose dep failed never runs — make's behaviour, and the
            # reason a broken stage1 does not produce six confusing stage2
            # errors instead of one.
            for job in blocked:
                del waiting[job.key]
                failed = [d for d in job.spec.deps if state[d] != PASS]
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
                         + ('   [exclusive: machine to itself]' if job.excl else ''))
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

    _apply_expectations(per_test, state, log)
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
def _apply_expectations(per_test, state, log):
    for name in per_test:
        spec = REGISTRY.get(name)
        reason = getattr(spec, 'expect', '') or ''
        if not reason:
            continue
        status = state.get(name)
        if status in (FAIL, ERROR):
            state[name] = EXPECTED
            log.notice(f'  EXPECTED {name}  ({reason})', force=True)
        elif status == PASS:
            state[name] = FAIL
            log.notice(f'  FAIL     {name}  (marked expect={reason!r} but it '
                       f'PASSES — drop the marker and fix whatever it was '
                       f'waiting for)', force=True)


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
        TIMEOUT: 'TIMEOUT', ERROR: 'ERROR', EXPECTED: 'EXPECTED'}


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
    def group(status):
        return [n for n in names if state.get(n) == status]

    passed = group(PASS)
    failed = group(FAIL) + group(ERROR)
    resource, skipped = group(RESOURCE), group(SKIP)
    expected = group(EXPECTED)
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

    parts = [f'{len(passed)} passed', f'{len(failed)} failed',
             f'{len(skipped)} skipped']
    if resource:
        parts.append(f'{len(resource)} resource-capped')
    if expected:
        parts.append(f'{len(expected)} expected-failure')
    tail = f'{len(results)} jobs, {cached} replayed from cache, {wall:.1f}s wall'
    if peak:
        tail += f', peak {peak:.1f} GB'
    tally = f'suite: {", ".join(parts)}  ({tail})'
    log.line('')
    log.line(tally)

    if not opts.quiet:
        print()
        print('─' * 78)
        for label, members in (
                ('FAILED', failed),
                ('RESOURCE-CAPPED (not a verdict on the output)', resource),
                ('EXPECTED (known-broken, tracked not hidden)', expected),
                ('SKIPPED', skipped)):
            if not members:
                continue
            print(f'{label}:')
            for name in members:
                why = getattr(REGISTRY.get(name), 'expect', '') or ''
                print(f'  {name}  ({secs[name]:.0f}s)'
                      + (f'  — {why}' if why else ''))
    print(tally + (f'   log: {log.path}' if log.path else ''))
    return 0 if not failed else 1


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


def print_list():
    print('MEMCLASS (GB ceiling, whole process tree):')
    for name, gb in sorted(MEMCLASS.items(), key=lambda kv: kv[1]):
        print(f'  {name:<8} {gb:>4}')
    if os.environ.get('MEMLIMIT_GB'):
        print(f'  MEMLIMIT_GB={os.environ["MEMLIMIT_GB"]} overrides all of the above')
    print('\nTESTS:')
    for name in sorted(REGISTRY):
        spec = REGISTRY[name]
        if isinstance(spec, Fanout):
            how = f'fanout x{len(spec.items)} mem={spec.mem}'
        else:
            how = spec.driver + (f' mem={spec.mem}' if spec.mem else '')
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
        print(f'  {name:<30} {how:<34} ['
              f'{",".join(buckets_containing(name))}]')
        if spec.desc:
            print(f'  {"":<30} {spec.desc}')
        if getattr(spec, 'expect', ''):
            print(f'  {"":<30} expected to fail: {spec.expect}')
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
        mark = '  [exclusive]' if REGISTRY[n].excl else ''
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
    ap.add_argument('--timeout', type=float, default=None,
                    help='per-job timeout in seconds (default: none)')
    ap.add_argument('--list', action='store_true',
                    help='print the registry and exit')
    ap.add_argument('--dry-run', action='store_true',
                    help='print the plan and its ordering, run nothing')
    opts = ap.parse_args(argv)
    if opts.jobs < 1:
        ap.error('-j must be >= 1')
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
    log.line('')

    if not opts.quiet:
        print(f'suite: {len(names)} tests, -j{opts.jobs}, '
              f'{"serial, output streamed" if opts.jobs == 1 else "parallel"}'
              + (f', MEMLIMIT_GB={override}' if override else ''))
        if override in ('0', '0.0'):
            print('suite: MEMLIMIT_GB=0 — NO memory ceiling on anything. '
                  'Please watch the machine.')

    jobs, per_test = plan_for(names, opts)
    for name in names:
        spec = REGISTRY[name]
        log.line(f'plan: {name}: {per_test[name]} job(s), driver='
                 f'{getattr(spec, "driver", "fanout")}'
                 + (f' mem={spec.mem}' if spec.mem else '')
                 + (' EXCLUSIVE' if spec.excl else '')
                 + (f' after {", ".join(spec.deps)}' if spec.deps else ''))
    log.line('')

    state, results, wall, peak = execute(jobs, per_test, opts, log)
    return report(names, state, results, wall, peak, opts, log)


if __name__ == '__main__':
    sys.exit(main())
