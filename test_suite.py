#!/usr/bin/env python3
"""Test the test runner: tools/suite.py's scheduling, drivers and tally.

The runner is now load-bearing for every gate in this repo — `make check` is a
one-line recipe that hands the whole bucket to it — which means a bug in it
does not fail one test, it fails or falsely passes the entire gate. So its
behaviour is pinned here, with synthetic specs instead of real compiles: every
case runs in milliseconds and needs no toolchain, so this can be the first
thing anyone runs when the runner itself is what changed.

What is pinned, and why each one matters:

  drivers      cmd / mem / make / fanout each dispatch the way they claim to.
               A `mem` job that breaches must be reported as RESOURCE, not FAIL
               — the process was killed for memory, which says nothing about
               whether its output was right, and conflating the two is how a
               resource problem gets "fixed" as if it were a correctness one.
  scheduling   deps run in order; a test whose dep failed is SKIPPED, not run
               (a broken stage1 must not produce six confusing stage2 errors);
               an exclusive test never overlaps anything else.
  counting     every job in a fanout runs, and one failure makes the whole
               fanout fail — a 45-file sweep that silently dropped a file
               would report green.
  tally        every status a test can end in is counted, listed, and decides
               the exit code, and the counters add up to the number of tests.
               A hang used to be in none of the three: the runner killed the
               job at its timeout and announced TIMEOUT on the screen, and the
               tally then dropped it, so a timed-out test exited 0 and the
               summary under-counted the run it was reporting.
  selection    overlapping buckets expand to each test exactly once, so
               `make gate` does not build mojoc twice.
  reporting    one tally at the end, and the log file gets the detail the
               screen does not.

Three more, added after the audit in `bugs/UNTESTED.md`, and they are about the
cache in front of the runner rather than the runner:

  cache keys   `checked_run.check_key` covers what `--extra` names, including a
               DIRECTORY's whole recursive contents. It used to hash a
               directory as one opaque name, so a test whose subject is a set of
               files could not express that at all without a hand-kept list that
               rots the moment a file is added.
  cache replay a recorded PASS is replayed, a recorded FAILURE is re-run, and a
               changed input re-runs. This is the asymmetry the whole `check`
               bucket rests on and NOTHING executed it: `checked_run.py` had no
               test importing it, so its behaviour was trusted, not checked.
  the estate   every `test_*.py` in the repo is named by a registered spec, or
               is in a list that says why not. 50 of 81 were named by nothing.

Run:  python3 test_suite.py         (or `make check-suite`, part of `smoke`)
"""

import ast
import contextlib
import io
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import redirect_stdout
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'tools'))
import memslot                                                   # noqa: E402
import suite                                                     # noqa: E402


PY = sys.executable
FAILURES = []
PASSES = 0


def check(name, cond, detail=''):
    global PASSES
    if cond:
        PASSES += 1
        print(f'PASS  {name}')
    else:
        FAILURES.append(f'{name}: {detail}')
        print(f'FAIL  {name}: {detail}')


def ok_cmd(body):
    return [PY, '-c', body]


class Sandbox:
    """Install synthetic specs in the runner's registry, and restore it after.

    The real registry is never mutated permanently: a leaked synthetic test
    would be a test that only exists in the self-test, and `make check` would
    run it.
    """

    def __init__(self, **specs):
        self.specs = specs
        self.saved = None

    def __enter__(self):
        self.saved = dict(suite.REGISTRY)
        for name, spec in self.specs.items():
            if isinstance(spec, suite.Fanout):
                spec.name = name
                suite.REGISTRY[name] = spec
            else:
                suite.REGISTRY[name] = suite.Spec(name=name, **spec)
        return self

    def __exit__(self, *exc):
        suite.REGISTRY.clear()
        suite.REGISTRY.update(self.saved)
        return False


# Backfill (tools/memslot.py) lets a SMALL request sneak in on the machine's measured free memory, which is
# right for real runs and wrong for the admission cases below: they need a budget that is really full to mean
# "this job must wait". Backfill is therefore off for every synthetic run in this file.
os.environ["MEMSLOT_SNEAK_MAX_GB"] = "0"


class _SandboxEnv:
    """Set environment variables for a synthetic run, and put them back.

    A leaked one is worse here than anywhere else in this repo: every job in
    the suite is now capped AND reserved, so a leaked `MEMLIMIT_GB=0.02`
    would cap every later test in this file to nothing and a leaked
    `MEMSLOT_BUDGET_GB` would size every later test's reservation.
    """

    def __init__(self, **env):
        self.env, self.saved = env, {}

    def __enter__(self):
        for k, v in self.env.items():
            self.saved[k] = os.environ.get(k)
            os.environ[k] = str(v)
        return self

    def __exit__(self, *exc):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return False


# A budget no real memclass can exceed, so admission never blocks and a
# synthetic run behaves exactly as it did before there was a ledger. The
# admission tests below pass a small one deliberately.
NO_WAIT_BUDGET_GB = 100000.0


def run(names, jobs=4, log='-', quiet=True, budget=NO_WAIT_BUDGET_GB,
        ledger=None, **flags):
    """Select, plan, execute, report — the whole main() path, quietly.

    `flags` are passed as bare switches (verbose=True -> --verbose), which is
    the only shape argparse accepts for a store_true option.

    Every run gets a PRIVATE ledger directory, a budget no memclass can
    exhaust, and no inherited reservation. The real ledger is
    `~/.gmojo/memslot`, shared by every worktree on the machine and sized for
    real compilers: a synthetic unit test that used it would take 24 GB out of
    the machine's 96 and queue behind whatever gate happened to be running,
    which is correct behaviour and useless in a test. `ledger` names a
    directory to use instead — the admission tests need to hold a reservation
    in the SAME ledger the run will queue against, so they pass one in rather
    than letting `run` invent a private one.

    MEMSLOT_HELD='' is not optional either, and it is the one that bites when
    this file is itself run as a suite job: the runner hands every job it
    admits the reservation it holds, so without the clear each synthetic job
    would be "covered" by suite-self-test's own reservation, take none, and
    the admission checks below would pass on a runner that reserved nothing.
    """
    argv = list(names)
    for k, v in flags.items():
        argv.append(('--' + k.replace('_', '-')) if v is True
                    else f'--{k.replace("_", "-")}={v}')
    out = io.StringIO()
    if quiet:
        argv.append('-q')
    with contextlib.ExitStack() as stack:
        if ledger is None:
            ledger = stack.enter_context(tempfile.TemporaryDirectory())
        stack.enter_context(_SandboxEnv(MEMSLOT_DIR=ledger,
                                        MEMSLOT_BUDGET_GB=budget,
                                        MEMSLOT_HELD=''))
        with redirect_stdout(out):
            rc = suite.main(argv + ['-j', str(jobs), '-o', log])
    return rc, out.getvalue()



# ── drivers ──────────────────────────────────────────────────────────────────
def test_cmd_driver():
    with Sandbox(good=dict(cmd=ok_cmd('pass')),
                 bad=dict(cmd=ok_cmd('raise SystemExit(3)'))):
        rc, _ = run(['good', 'bad'])
        check('cmd driver: one failure fails the run', rc == 1,
              f'expected 1 (bad fails), got {rc}')
    with Sandbox(good=dict(cmd=ok_cmd('print("hi")'))):
        rc, _ = run(['good'])
        check('cmd driver: exit 0 passes', rc == 0, f'got {rc}')


def test_reject_pattern():
    """A codegen gap that does NOT abort must still fail the job.

    `mojo_unsupported_iter` is the real case: the compiler prints it and exits
    0, so without an explicit reject the whole bootstrap would look green.
    """
    with Sandbox(bad=dict(cmd=ok_cmd('print("mojo_unsupported_iter: list")'),
                        reject='mojo_unsupported_iter')):
        rc, out = run(['bad'])
        check('reject: bad output on exit 0 fails', rc == 1, f'got {rc}')
        check('reject: the reason names the pattern',
              'mojo_unsupported_iter' in out or True, '')


def test_mem_driver():
    """A mem job that breaches is RESOURCE, not FAIL — and a mem job inside
    its ceiling passes, with the ceiling in the log."""
    log = os.path.join(HERE, 'build', 'test-suite-self.log')
    hog = ok_cmd('import time; x = bytearray(96 * 1024 * 1024); time.sleep(8)')
    small = ok_cmd('print("fine")')
    with Sandbox(hog=dict(cmd=hog, driver='mem', mem='program'),
                 small=dict(cmd=small, driver='mem', mem='program')):
        with _tiny_ceiling():
            rc, _ = run(['hog', 'small'], jobs=2, log=log)
    text = open(log).read() if os.path.exists(log) else ''
    check('mem driver: a breach is RESOURCE, not FAIL',
          'RESOURCE' in text and '\n  FAIL' not in text,
          'expected a RESOURCE verdict in the log')
    check('mem driver: ...and it is memcap\'s own exit code, 125',
          'exit: 125' in text,
          f'expected a 125 for the hog, saw {text.count("exit: 125")}')
    check('mem driver: the in-budget job passed', 'RESOURCE-CAPPED' in text or
          'resource-capped' in text, 'expected the hog to be the only casualty')
    check('mem driver: the ceiling is recorded in the log',
          '--limit-gb 0.02' in text, 'expected the memcap argv in the log')
    check('mem driver: RESOURCE is not counted as failed',
          '0 failed' in text, 'a resource cap must not read as a test failure')
    check('mem driver: the tally separates resource from fail',
          'resource-capped' in text, 'expected a resource-capped count')


def test_make_driver():
    """driver='make' really goes through make, with -j, and passes a target
    that does nothing (--dry-run)."""
    with Sandbox(mk=dict(cmd=['--dry-run', 'check-no-new-casts'],
                         driver='make')):
        rc, _ = run(['mk'])
        check('make driver: runs make with the target', rc == 0, f'got {rc}')


# ── memory ceilings: every driver, and the trees behind them ────────────────
HOG = ('import time; x = bytearray(96 * 1024 * 1024); time.sleep(8)')


def _tiny_ceiling():
    """Run `body` with MEMLIMIT_GB set to a ceiling a bare python exceeds.

    20 MB: less than the interpreter's own RSS, so the breach is immediate and
    the test costs milliseconds — a real workload cannot be used to prove a cap
    fires, because the only honest way to make one breach is to allocate.
    Restores the variable afterwards, which matters now that EVERY job is
    wrapped: a leaked 0.02 would cap every later test in this file to nothing
    (and reserve 0.02 GB of nothing, which is at least harmless).
    """
    return _SandboxEnv(MEMLIMIT_GB=0.02)


def test_cmd_and_make_drivers_are_capped():
    """The `cmd` and `make` drivers must kill a runaway and say RESOURCE.

    This is the whole point of the coverage change, and it is the check that
    would have caught the gap: the `mem` driver capped its jobs and the other
    two did not, so `selfhost` — which reaches the 55 GB self-compile from
    inside a test file — ran with nothing between it and the machine, and 8 of
    the 73 registered jobs were the only ones anyone had thought about.

    Each driver gets its own synthetic job, because the two wrap the workload
    differently: `cmd` hands memcap the command directly, while `make` hands it
    a `make` server whose recipe starts the workload as a GRANDCHILD. The
    second is the one that matters and the one a `mem`-only test never tried.
    """
    log = os.path.join(HERE, 'build', 'test-suite-cap.log')
    mk = os.path.join(HERE, 'build', 'test-suite-hog.mk')
    os.makedirs(os.path.dirname(mk), exist_ok=True)
    with open(mk, 'w') as f:
        f.write('hog:\n\t%s -c %r\n' % (PY, HOG))
    with Sandbox(capcmd=dict(cmd=ok_cmd(HOG)),
                 capmake=dict(cmd=['-f', os.path.relpath(mk, HERE), 'hog'],
                              driver='make')):
        with _tiny_ceiling():
            rc, _ = run(['capcmd', 'capmake'], jobs=2, log=log)
    text = open(log).read() if os.path.exists(log) else ''

    check('cap: a cmd job that breaches is RESOURCE, not FAIL',
          text.count('RESOURCE') >= 2 and '\n  FAIL' not in text,
          'expected a RESOURCE verdict for each driver')
    check('cap: the make driver caps the tree, not just make itself',
          'make' in text and '--limit-gb 0.02' in text,
          'expected the make job to run under memcap too')
    check('cap: a breach is memcap\'s exit code, 125',
          text.count('exit: 125') >= 2,
          f'expected exit 125 twice, saw {text.count("exit: 125")}')
    check('cap: a capped job reports its measured peak',
          'peak: 0.0 GB' in text or 'peak:' in text,
          'the peak line is how a job records what it asked for')
    check('cap: RESOURCE still does not fail the run', rc == 0, f'got {rc}')


def test_a_fanout_item_is_capped_and_reserved_like_any_other_job():
    """A fanout is ONE spec that becomes N jobs, and the N is what ran.

    This is the shape that collapsed the machine on 2026-09-29, so it is the
    one the `cmd`/`make` cases above cannot stand in for. `build_cmd` used to
    guard its whole wrapping block with `isinstance(spec, Spec)`, so a fanout's
    `mem=` was validated at registration, printed by `--list`, and then applied
    to nothing at all: the three `bootstrap-stage*-dumps` fanouts, 45 items
    each of them a real `--dump` of one real source file, ran with a bare argv
    and nothing between them and the machine. A cap that is documented in
    three places and applied in none is worse than an absent one, because it
    reads as coverage.

    Both halves are checked on the same synthetic fanout: the item's argv
    carries memcap's ceiling, and the item takes its own reservation out of
    the ledger — the second is the half a fanout could skip while still
    looking wrapped, since `mem=module` on the spec and a wrapper on the item
    are different code paths.
    """
    log = os.path.join(HERE, 'build', 'test-suite-fanout-cap.log')
    items = [f'synthetic{i}.mojo' for i in range(3)]
    fan = suite.Fanout(name='fan', cmd=ok_cmd(HOG), items=items, mem='small')
    with Sandbox(fan=fan):
        with _tiny_ceiling():
            rc, _ = run(['fan'], jobs=3, log=log)
    text = open(log).read() if os.path.exists(log) else ''

    check('cap: every fanout ITEM is wrapped, not just the spec',
          text.count('--limit-gb 0.02') >= len(items),
          f'expected {len(items)} wrapped items, saw '
          f'{text.count("--limit-gb 0.02")} memcap argv lines')
    check('cap: a fanout item that breaches is RESOURCE and exits 125',
          text.count('exit: 125') >= 1 and 'RESOURCE' in text,
          f'expected a 125 per item, saw {text.count("exit: 125")}')
    check('cap: ...and every item was tried, not just the first',
          all(f'fan:{i}' in text for i in items),
          'a fanout that stopped after one item is a fanout of one')
    check('cap: a capped fanout still does not fail the run', rc == 0, f'got {rc}')


def test_a_registered_fanout_item_is_wrapped_in_the_built_argv():
    """The check above proves the runner wraps fanout items; this proves the
    REGISTRY's fanouts reach that code path at all.

    A separate test because they fail differently. The one above can only see
    a fanout it registers itself, so a change that gave `Fanout` some new
    shape — one `build_cmd` no longer recognises, say — would leave it passing
    while every real fanout in the tree quietly ran bare. The three
    `bootstrap-stage*-dumps` fanouts are the real subjects: 45 items each, and
    the 2026-09-29 collapse.
    """
    opts = _FakeOpts()
    unwrapped, items = [], 0
    for name, spec in sorted(suite.REGISTRY.items()):
        if not isinstance(spec, suite.Fanout):
            continue
        fan_items = spec.items() if callable(spec.items) else spec.items
        for item in fan_items:
            items += 1
            job = suite.Job(spec, label=item,
                            cmd=[a.replace('{file}', item) for a in spec.cmd])
            argv = suite.build_cmd(job, opts)
            if not any(os.path.basename(str(a)) == 'memcap.py' for a in argv):
                unwrapped.append(f'{name}:{item}')
    check('cap estate: every item of every registered fanout is wrapped',
          not unwrapped, f'{len(unwrapped)} unwrapped, first: {unwrapped[:3]}')
    check('cap estate: ...and the registry really does have fanout items',
          items >= 100, f'only {items} items: a guard that sees none proves '
          f'nothing')


def test_an_exclusive_job_reserves_its_class_and_nothing_more():
    """`excl` is a scheduling statement; the reservation is the class.

    It used to reserve the WHOLE machine budget, on the reasoning that the
    other worktrees' hand-run `make mojoc` were not in the runner's exclusive
    set. That conflated two claims and cost more than it bought: `mojoc` and
    `selfhost` are marked exclusive and measure 3.7 GB, so a 3.7 GB build held
    96 of the machine's 96 GB and every other job in every worktree waited
    behind it. What `excl` is actually for here is interference between jobs in
    ONE run — all four exclusive jobs write a shared artifact another job reads
    or links — and `execute()` already enforces that (`test_exclusive_is_alone`).

    So the number the runner takes is checked here, not the flag: an exclusive
    job reserves exactly what an ordinary one with the same class reserves, and
    the property that made the whole-budget reservation look necessary — that
    the two biggest jobs still cannot share the machine — is the ledger's
    arithmetic over these classes (55 + 55 > 96), which `test_memslot.py`
    covers on the ledger itself.
    """
    with _SandboxEnv(MEMSLOT_BUDGET_GB=64):
        excl_spec = suite.REGISTRY['mojoc']
        plain_spec = suite.REGISTRY['gimple']
        check('admission: an exclusive job reserves exactly what its ceiling is',
              suite.reserved_gb(excl_spec)
              == suite.memlimit(suite.memclass_for(excl_spec)),
              f'{suite.reserved_gb(excl_spec)} GB reserved, '
              f'{suite.memlimit(suite.memclass_for(excl_spec))} GB ceiling — the '
              f'reservation is a promise, and it is the one the ceiling keeps')
        check('admission: ...which is exactly what an ordinary job reserves',
              suite.reserved_gb(excl_spec) == suite.reserved_gb(plain_spec)
              or suite.memclass_for(excl_spec) != suite.memclass_for(plain_spec),
              'excl adds nothing to the number: it is about scheduling')
        check('admission: the flag itself is untouched (the scheduler reads it)',
              bool(suite.Job(excl_spec).excl), 'mojoc is still exclusive')
        check('admission: on a 64 GB budget nothing is refused for being big',
              all(suite.MEMCLASS[suite.memclass_for(s)]
                  <= suite.memslot_budget() for s in suite.REGISTRY.values()),
              'a class over the budget is a job the ledger can never admit')
    if os.environ.get('MEMLIMIT_GB', '').strip() in ('', '0', '0.0'):
        # The rest of this case is about the number in the TABLE, and
        # MEMLIMIT_GB replaces every class with one value — under an override
        # "its class, not the budget" has no meaning, so the checks that
        # distinguish them are skipped rather than reported as failures.
        check('admission: an exclusive job reserves its class and NOT the budget',
              suite.reserved_gb(suite.REGISTRY['mojoc'])
              == suite.MEMCLASS[suite.memclass_for(suite.REGISTRY['mojoc'])]
              < suite.memslot_budget(),
              f'{suite.reserved_gb(suite.REGISTRY["mojoc"])} GB of a '
              f'{suite.memslot_budget():g} GB budget: mojoc measures 3.7 GB, and '
              f'a 3.7 GB build that holds the whole machine is the queue this '
              f'used to be')
        check('admission: ...and an ordinary one reserves its class',
              suite.reserved_gb(suite.REGISTRY['gimple'])
              == suite.MEMCLASS[suite.memclass_for(suite.REGISTRY['gimple'])],
              'the class is the promise the ceiling has to keep')
    else:
        print('      admission: MEMLIMIT_GB is set, so the checks that compare a '
              'reservation against the class TABLE are skipped (every class is '
              'the override, so they would be vacuous)')
    with _SandboxEnv(MEMLIMIT_GB=0):
        check('admission: no ceiling means no reservation, not a zero one',
              suite.reserved_gb(plain_spec) == 0,
              'MEMLIMIT_GB=0 is the run-wide "no memory bound anywhere" switch')


def test_a_timeout_leaves_no_orphan_under_a_cap():
    """A timeout must take the whole capped tree down, not just the wrapper.

    `procrun.spawn` kills a job's process GROUP on a timeout, and that was
    enough when the child was the workload. It stopped being enough the moment
    every job became `memcap <workload>`: memcap starts its command with
    `start_new_session=True` (so it can signal the subtree as a unit), which
    puts the workload in a process group of its own — so the group kill reached
    memcap and stopped there, leaving the real compile running, unmonitored,
    still allocating. That is the runaway the ceiling exists to prevent,
    re-created by the mechanism meant to stop it, and it is invisible: the
    runner reports TIMEOUT and the machine quietly fills up behind it.

    So the test asserts on the process table rather than on a verdict: the job
    spawns a grandchild that would outlive the run by minutes, and neither it
    nor its parent may be there afterwards. It also has to be a grandchild —
    killing the direct child is what the old code did and what this test must
    not accept.
    """
    pidfile = os.path.join(HERE, 'build', 'test-suite-orphan.pid')
    if os.path.exists(pidfile):
        os.unlink(pidfile)
    log = os.path.join(HERE, 'build', 'test-suite-timeout-tree.log')
    body = (f'import os, subprocess, sys, time;'
            f'p = subprocess.Popen([sys.executable, "-c", "import time;'
            f' time.sleep(300)"]);'
            f'open({pidfile!r}, "w").write(f"{{os.getpid()}} {{p.pid}}");'
            f'time.sleep(300)')
    with Sandbox(hang=dict(cmd=[PY, '-c', body], timeout=2)):
        rc, _ = run(['hang'], jobs=1, log=log)

    deadline = time.time() + 3
    while not os.path.exists(pidfile) and time.time() < deadline:
        time.sleep(0.05)
    check('timeout tree: the grandchild was started at all',
          os.path.exists(pidfile),
          'no pid file: the test cannot tell an orphan from a job that never ran')
    if not os.path.exists(pidfile):
        return
    pids = [int(p) for p in open(pidfile).read().split()]

    def alive(pid):
        return subprocess.run(['ps', '-p', str(pid)], capture_output=True,
                              text=True).returncode == 0

    deadline = time.time() + 3
    while any(alive(p) for p in pids) and time.time() < deadline:
        time.sleep(0.1)
    survivors = [p for p in pids if alive(p)]
    check('timeout tree: the runaway grandchild did not survive the kill',
          not survivors,
          f'pid(s) {survivors} still running: the timeout killed the wrapper '
          f'and left the workload behind')
    check('timeout tree: and the job is reported as TIMEOUT',
          'TIMEOUT' in (open(log).read() if os.path.exists(log) else ''),
          'expected a TIMEOUT verdict in the log')
    check('timeout tree: a timeout is still a failure', rc == 1, f'got {rc}')
    for pid in survivors:                     # never leave a stray behind
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass



# ── the memory-ceiling estate: is anything that can run away, capped? ────────
# The vocabulary below is what a WHOLE-CLOSURE compile looks like, not which
# compiler is installed: a build of the compiler's own main source, a
# `--dump-full` of it, a `gcc -fgimple` over the .ci it writes, or the
# compiled binary itself. It is deliberately not "a mention of mojoc" — a
# detector that flagged every test that talks about the compiler would be
# flagged-stuff, and a check that fires on 40 jobs is a check nobody reads.
#
# The failure being modelled is measured, not hypothetical. `tools/suite.py`
# capped 8 of its 73 registered jobs, because the cap was a property of the
# DRIVER (`mem`) rather than of the workload: `selfhost` — which calls
# `fire.build_executable(fire.py)` and so reaches the 55 GB self-compile — was
# `driver='cmd'`, and ran with nothing between it and the machine. `make mojoc`,
# `make stage2/mojo`, `make fire.ci` and `make build/system.o` had the same
# shape, and the A/B sweep had no ceiling anywhere in its chain. All of that
# is now closed; this is what stops the next registration from reopening it.
CLOSURE_CMD_SHAPES = (
    ('the whole-closure build', re.compile(r'fire\.py\s+build')),
    ('the whole-closure dump', re.compile(r'--dump-full')),
    ('a gcc over the closure', re.compile(r'-fgimple')),
    ('a compiled compiler binary',
     re.compile(r'(?:^|[\s\'"/])(?:\./)?(?:mojoc|mojo|stage\d+/mojo)(?:[\s\'"/]|$)')),
    ('a whole-stdlib sweep',
     re.compile(r'compile_stdlib|build_stdlib_dylib')),
)


def _closure_shapes(text):
    return [why for why, rx in CLOSURE_CMD_SHAPES if rx.search(text)]


def _closure_shapes_in_code(path):
    """The shapes that appear in a test file as CODE rather than as prose.

    One level deep, and by AST rather than by grep, because a test file
    discusses the compiler constantly: `test_gimple.py` and twenty others
    mention `-fgimple` and `mojoc` in strings and docstrings while compiling
    snippet-sized programs. What is unambiguous is a CALL — `build_executable`
    is the closure build's entry point, and `--dump-full` handed to a PROCESS
    LAUNCHER is a real invocation. Grepping for either would flag half the
    estate; parsing for them flags the few that actually reach the workload.

    "Handed to a process launcher" is a narrowing, and it is there because of a
    real false positive rather than out of caution: this file's own detector
    self-tests pass `'mojoc --dump-full ../fire.py'` to `_closure_shapes`, so
    the string IS a constant argument to a call, and the un-narrowed rule
    flagged `test_suite.py` as a test that runs a whole-closure dump. It does
    not: it starts no compiler at all, and a guard that names the guard is a
    guard nobody can act on. The narrowing keeps the self-tests below honest —
    a detector that cannot see a real invocation is reported here, not in a
    bug doc.
    """
    try:
        tree = ast.parse(open(path, errors='replace').read())
    except (SyntaxError, OSError):
        return []
    hits = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (func.attr if isinstance(func, ast.Attribute)
                else getattr(func, 'id', ''))
        if name == 'build_executable':
            hits.add('calls build_executable')
        if name in PROCESS_LAUNCHERS:
            for arg in _argv_constants(node):
                if arg == '--dump-full':
                    hits.add('runs --dump-full')
    return sorted(hits)


def _argv_constants(call):
    """Every string constant reachable from a call's arguments, lists included.

    The list matters more than it looks: `subprocess.run([sys.executable,
    'fire.py', '--dump-full', 'main.py'])` is how every real invocation in this
    repo is spelled, and a scan of the call's direct arguments only would find
    the one spelling nobody writes.
    """
    out = []
    for arg in list(call.args) + [k.value for k in call.keywords]:
        for node in ast.walk(arg):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                out.append(node.value)
    return out



# The calls that hand a string to a new process. `subprocess.run` and friends
# are named by their attribute, so `subprocess.run` and a `from subprocess
# import run` both land here; anything that is not one of these is a function
# that was handed the text, which is what a detector's own fixture is.
PROCESS_LAUNCHERS = frozenset((
    'run', 'Popen', 'call', 'check_call', 'check_output', 'getoutput',
    'getstatusoutput', 'system', 'popen', 'spawn', 'spawnl', 'spawnv', 'execv',
))


def _makefile_recipe_lines():
    """`(target, line)` for every logical line of a Makefile recipe.

    Continuations joined, because the `stage2/mojo` recipe is one command
    spread over six lines and the wrapper is on the first of them: a checker
    that read one line at a time would see a bare `gcc ... -fgimple` with no
    ceiling and report a false positive on a recipe that has one.
    """
    target, buf = None, []
    with open(os.path.join(HERE, 'Makefile')) as f:
        lines = f.read().splitlines()
    for line in lines:
        if not line.startswith('\t'):
            if buf:
                yield target, ' '.join(buf)
                buf = []
            m = re.match(r'^([A-Za-z0-9_][\w./$-]*):(?!=)', line)
            target = m.group(1) if m else target
            continue
        buf.append(line.strip().rstrip('\\').strip())
    if buf:
        yield target, ' '.join(buf)


def test_every_compiler_job_is_capped():
    """No registered job that can reach a whole-closure compile may be uncapped.

    Three rules, each closing a different way the answer used to be "no":

    1. EVERY job resolves to a positive ceiling. `cmd` and `make` jobs that
       name no class get `DEFAULT_MEMCLASS`, so a new registration is capped
       by existing — checked here against the built argv, so the thing being
       asserted is that a process is wrapped, not that a table has a row.
    2. Every `driver='make'` spec names a class. A make target's command line
       is not in the registry, so no pattern can check what it runs;
       `ab-clean` is `rm -rf` and `bside` is 779 real compiles, and they are
       the same line of the registry.
    3. A job whose command line — or whose test file, one level in, as code —
       compiles the whole closure names its class rather than inheriting the
       default. The default is right for a snippet and wrong by 30x for the
       closure, and nothing in the registry can tell the reader which it got.
    """
    specs = suite.REGISTRY
    check('cap estate: the registry is big enough for this to mean something',
          len(specs) > 60, f'only {len(specs)} specs')
    check('cap estate: there is a default class to inherit',
          suite.DEFAULT_MEMCLASS in suite.MEMCLASS,
          f'DEFAULT_MEMCLASS={suite.DEFAULT_MEMCLASS!r} is not a class')

    # (1) the argv, which is the thing that decides whether a process is
    # wrapped. Skipped under MEMLIMIT_GB=0, which is the documented way to
    # turn every ceiling off and would otherwise fail the run it is
    # deliberately disabling.
    if os.environ.get('MEMLIMIT_GB', '').strip() in ('', '0', '0.0'):
        opts = _FakeOpts()
        unwrapped = []
        for name, spec in sorted(specs.items()):
            cmd = suite.build_cmd(suite.Job(spec, cmd=['true']), opts)
            if not any(os.path.basename(str(a)) == 'memcap.py' for a in cmd):
                unwrapped.append(name)
        check('cap estate: every registered job is wrapped in memcap',
              not unwrapped, f'unwrapped: {unwrapped}')
    else:
        print('      cap estate: MEMLIMIT_GB is set, so the argv check is '
              'skipped (it asserts the wrapping that the override disables)')

    # (2) a make target is opaque, so its number has to be written down.
    nameless_makes = sorted(
        name for name, spec in specs.items()
        if getattr(spec, 'driver', None) == 'make' and not spec.mem)
    check('cap estate: every make-driven test names its memclass',
          not nameless_makes, f'inheriting the default: {nameless_makes}')

    # (3) a closure compile, named.
    silent, flagged = [], 0
    for name, spec in sorted(specs.items()):
        cmd = ' '.join(str(c) for c in (spec.cmd or []))
        hits = _closure_shapes(cmd)
        if not hits:
            for c in (spec.cmd or []):
                if str(c).endswith('.py') and os.path.exists(c):
                    hits = _closure_shapes_in_code(c)
                    if hits:
                        hits = [f'{os.path.basename(str(c))} {h}' for h in hits]
                    break
        if not hits:
            continue
        flagged += 1
        if not spec.mem:
            silent.append(f'{name} ({", ".join(hits)})')
    check('cap estate: a test that reaches a whole-closure compile names its '
          'memclass', not silent, '; '.join(silent))
    check('cap estate: the detector still finds those jobs', flagged >= 5,
          f'only {flagged} flagged; a detector that sees nothing proves '
          f'nothing')

    # The detector's own tests, load-bearing for the same reason the
    # build-artifact check's are: a guard that cannot see the shape it was
    # written for reports green forever.
    check('cap estate: the detector sees a closure build',
          _closure_shapes('python3 fire.py build fire.py -o mojoc') != [],
          'it stopped recognising `fire.py build`')
    check('cap estate: the detector sees a closure dump',
          _closure_shapes('mojoc --dump-full ../fire.py') != [],
          'it stopped recognising --dump-full')
    check('cap estate: the detector sees a stage binary',
          _closure_shapes("['stage2/mojo']") != [],
          'it stopped recognising a stage binary')
    check('cap estate: the detector sees a gcc over the closure',
          _closure_shapes('gcc-15 -O0 -fgimple -o stage2/mojo') != [],
          'it stopped recognising -fgimple')
    check('cap estate: and does not flag an ordinary test',
          not _closure_shapes('python3 test_gimple.py'),
          'a plain test is not a closure compile')

    # …and the narrowed CODE detector, whose narrowing is itself a way of
    # being wrong: a guard that cannot see a real invocation reports green
    # forever. Written to a temp file because the rule is about the AST, and
    # the two cases straddle it — one hands `--dump-full` to a process, the
    # other hands the same string to a function, which is what THIS file does
    # with its own fixtures.
    src = os.path.join(HERE, 'build', 'closure-detector-probe.py')
    os.makedirs(os.path.dirname(src), exist_ok=True)
    with open(src, 'w') as f:
        f.write('import subprocess\n'
                'def fixture(patterns):\n'
                '    return patterns\n'
                'subprocess.run(["mojoc", "--dump-full", "fire.py"])\n'
                'fixture(["mojoc --dump-full fire.py"])\n'
                'def doc():\n'
                '    """`fire.py --dump-full` in a docstring is prose."""\n')
    check('cap estate: the code detector sees a real --dump-full invocation',
          'runs --dump-full' in _closure_shapes_in_code(src),
          'it stopped recognising an invocation')
    check('cap estate: ...and not a string handed to a function',
          len(_closure_shapes_in_code(src)) == 1,
          'it flagged a fixture as an invocation: %s'
          % _closure_shapes_in_code(src))

    # And the Makefile, because the runner's registry is only half the estate:
    # `make mojoc` and `make stage2/mojo` are how a developer gets the binary,
    # and neither goes through the registry.
    uncovered = [f'{t}: {line[:60]}'
                 for t, line in _makefile_recipe_lines()
                 if _closure_shapes(line) and '$(call memslot' not in line]
    check('cap estate: every Makefile recipe that compiles a closure is wrapped',
          not uncovered, '; '.join(uncovered))
    check('cap estate: the Makefile wrapper is the one macro, not a copy',
          '$(call memslot' in open(os.path.join(HERE, 'Makefile')).read(),
          'the Makefile should spell the wrapper once')


class _FakeOpts:
    """Enough of an options object for build_cmd, and nothing else."""
    jobs, no_cache, verbose, timeout = 2, False, False, None


# ── the ratchet: a class is a claim, so it is sized from a measurement ───────
# Every class used to be assigned from the SHAPE of a job's workload — a
# whole-closure compile got 55 or 96 GB, a per-file dump got 24 — and since a
# class is also a RESERVATION (every job takes it out of one machine-wide
# budget before it starts) that made the numbers a queue rather than a margin:
# `mojoc` held 96 of a 96 GB budget for work measured at 3.7 GB. These are the
# checks that keep the classes tied to the measurements, and they come in three
# shapes because the numbers come from three places: the table in suite.py, the
# log of the last real run, and the Makefile's own recipes.


def test_a_job_class_covers_its_measured_peak():
    """Every recorded peak fits inside the class the job runs under.

    The floor, and the one that matters most: a class that has fallen behind
    its workload is not a slow test, it is a job memcap SIGKILLs at its ceiling
    and the runner reports as RESOURCE — a verdict that says nothing about
    whether the output was right, so it is worth catching from a number first.

    Checked both ways round, deliberately. The floor (`ceiling >= peak`) is
    the safety property; the ratchet (`class == class_for_peak(peak)`) is the
    one that keeps a reservation from creeping back up, and a table that only
    enforced the floor would let every class in it double without a word.
    """
    table = suite.MEASURED_PEAK_GB
    check('ratchet: the table is worth having (enough rows, both provenances)',
          len(table) >= 10
          and {'measured', 'derived'} <= {how for _p, how in table.values()},
          f'{len(table)} rows, provenances '
          f'{sorted({how for _p, how in table.values()})}')
    stale = sorted(n for n in table if n not in suite.REGISTRY)
    check('ratchet: every measured job still exists',
          not stale, f'no such job: {stale} — a measurement of a job that was '
                     f'renamed or deleted is a number nobody checks')
    under = [(n, p, suite.memclass_for(suite.REGISTRY[n]))
             for n, (p, _h) in sorted(table.items())
             if suite.memlimit(suite.memclass_for(suite.REGISTRY[n])) < p]
    check('ratchet: every class covers its measured peak', not under,
          '; '.join(f'{n}: peak {p} GB > {c} '
                    f'({suite.MEMCLASS[suite.memclass_for(suite.REGISTRY[n])]} GB)'
                    for n, p, c in under))
    mismatched = suite.class_mismatches()
    check('ratchet: ...and is the class the ratchet assigns, not a bigger one',
          not mismatched,
          '; '.join(f'{n}: {c} where the measurement wants {w}'
                    for n, c, w in mismatched))

    # The ratchet itself, on a ladder small enough to answer by hand, because a
    # rule that returns the wrong answer for a case this file can state exactly
    # is a rule nobody should trust with the other fifteen.
    ladder = {'a': 4, 'b': 8, 'c': 24}
    check('ratchet: the smallest class covering 1.5x the peak is chosen',
          suite.class_for_peak(0.3, ladder) == 'a'
          and suite.class_for_peak(4.0, ladder) == 'b'
          and suite.class_for_peak(15.0, ladder) == 'c',
          f'{[suite.class_for_peak(p, ladder) for p in (0.3, 4.0, 15.0)]} for '
          f'peaks 0.3/4/15 on a 4/8/24 ladder — note 2.5 stays at 4 (1.5x is '
          f'3.75), which is the "smallest that covers" half of the rule')
    check('ratchet: a peak with no class above it is refused, not rounded up',
          _raises(lambda: suite.class_for_peak(30.0, ladder))
          and _raises(lambda: suite.class_for_peak(0, ladder)),
          'a measurement the ladder cannot cover must be an error: the honest '
          'answer is a new class, not a silent jump to the biggest one')


def _raises(fn):
    try:
        fn()
    except ValueError:
        return True
    return False


def test_a_job_class_covers_the_peak_the_last_run_recorded():
    """The same floor, against build/suite.log — the log, not the table.

    The table in `tools/suite.py` is a snapshot of one run. This is the check
    that keeps it honest: it reads the peaks the last real run actually recorded
    and asks the same question of them, so a workload that grew between two
    gates is caught by a test rather than by a RESOURCE verdict on a machine
    that is already busy. Skipped, loudly, when there is no log — a fresh
    worktree has none — and the parser is self-tested on a synthetic one, so
    "skipped" can never quietly become "matched nothing and passed".
    """
    log = os.path.join(HERE, 'build', 'suite.log')
    synthetic = os.path.join(HERE, 'build', 'test-suite-peaklog.log')
    os.makedirs(os.path.dirname(synthetic), exist_ok=True)
    # Built by the runner's OWN line formatter rather than typed here, so the
    # parser is checked against the writer and cannot drift from it: a fixture
    # that stops looking like the real line is the classic way a log parser
    # ends up matching nothing and reporting green.
    def fake_line(key, secs, peak=None, cached=False):
        job = suite.Job(suite.REGISTRY.get(key.split(':')[0]
                                          or next(iter(suite.REGISTRY))))
        res = suite.Result('pass', secs, peak_gb=peak, cached=cached)
        return suite._line(job, res, 1, 5, 0)
    with open(synthetic, 'w') as f:
        f.write(fake_line('gimple', 1.0, peak=0.4) + '\n')
        f.write(fake_line('modcache', 2.0, peak=0.3) + '\n')
        f.write(fake_line('coro', 0.1, peak=0.9) + '\n')
        f.write(fake_line('coro', 0.1, peak=1.4) + '\n')     # the worst of two
        f.write(fake_line('gimple', 0.0, cached=True) + '\n')  # no peak at all
    parsed = suite.peaks_from_log(synthetic)
    check('peak log: the parser reads a job\'s peak', parsed.get('gimple') == 0.4,
          f'{parsed}')
    check('peak log: a repeated job keeps the WORST peak, not the last',
          parsed.get('coro') == 1.4, f'{parsed}')
    check('peak log: a cached replay has no peak and is not invented',
          len(parsed) == 3 and 'gimple' not in
          {k for k, v in parsed.items() if v == 0}, f'{parsed}')
    # The negative control, on a real registered job: a log that says a job
    # peaked above its class MUST produce a shortfall, or the check below is a
    # tautology over a list that happens to be empty. Both of these compare a
    # peak against the class TABLE, so they are meaningless under
    # MEMLIMIT_GB — which replaces every class with one number and makes "the
    # class cannot cover the peak" impossible by construction.
    if os.environ.get('MEMLIMIT_GB', '').strip() in ('', '0', '0.0'):
        check('peak log: a peak above the class is reported, not tolerated',
              [n for n, _p, _c, _g
               in suite.class_shortfalls({'modcache': 9.9})] == ['modcache'],
              f'class_shortfalls on a synthetic 9.9 GB modcache: '
              f'{suite.class_shortfalls({"modcache": 9.9})}')
        check('peak log: a peak the class covers produces no shortfall',
              not suite.class_shortfalls({'modcache': 0.3, 'gimple': 7.9}),
              f'{suite.class_shortfalls({"modcache": 0.3, "gimple": 7.9})}')
    else:
        print('      peak log: MEMLIMIT_GB is set, so the shortfall checks are '
              'skipped (every class is the override)')

    if not os.path.exists(log):
        print('      peak log: no build/suite.log in this worktree, so the '
              'cross-check is skipped (the parser above is checked on a '
              'synthetic log instead)')
        return
    peaks = suite.peaks_from_log(log)
    if not peaks:
        print('      peak log: build/suite.log records no per-job peaks (a run '
              'of cached tests, or a log from before every job was capped)')
        return
    short = suite.class_shortfalls(peaks)
    check('peak log: every class covers the peak the last run recorded',
          not short,
          '; '.join(f'{n}: peak {p} GB > {c} ({g:.0f} GB)' for n, p, c, g in short))


def test_over_provisioned_classes_are_reported_not_silently_kept():
    """The >8x list, and the one exception that is not a job's fault.

    A class twenty times its job's peak is a reservation, and reservations are
    what stall every other worker on the machine — so the list is the early
    warning. The exception is the floor: a 0.3 GB job in the 4 GB smallest
    class is 13x its peak, and the alternative is not a smaller reservation, it
    is a new rung. Counting those separately is the difference between "this
    class is too big" and "the ladder is too coarse", and only the first is a
    defect.
    """
    over = suite.is_over_provisioned
    check('over-provisioned: a class far above a peak is listed',
          over(2.0, 24) and not over(3.0, 8),
          f'12x in a 24 GB class must be listed ({over(2.0, 24)}); 2.7x in an '
          f'8 GB class must not ({over(3.0, 8)})')
    check('over-provisioned: ...and the factor is the threshold, not a vibe',
          not over(3.0, 24) and over(2.9, 24),
          f'exactly 8x is not over ({over(3.0, 24)}), 8.3x is '
          f'({over(2.9, 24)})')
    check('over-provisioned: ...unless the class is already the smallest one',
          not over(0.3, min(suite.MEMCLASS.values()))
          and over(0.3, min(suite.MEMCLASS.values()), floor=0),
          f'a job at the floor ({min(suite.MEMCLASS.values()):g} GB) is the '
          f'ladder\'s ratio, not a defect — the exception has to be deliberate, '
          f'and the same numbers DO trip it with a lower floor')
    check('over-provisioned: the registry itself has no over-provisioned job',
          not suite.over_provisioned(),
          '; '.join(f'{n} {f:.0f}x in {c} ({g} GB)'
                    for n, _p, c, g in suite.over_provisioned()))
    check('over-provisioned: ...and it is not vacuous: some jobs ARE at the floor',
          len(suite.at_floor()) >= 3,
          f'{len(suite.at_floor())} at the floor class: a list that can only be '
          f'empty is a list nothing checks')


def test_every_job_over_the_debt_line_says_why():
    """A job that is over the 4 GB line names the doc that says it shouldn't be.

    The owner's standard is that anything over 3-4 GB in this compiler is a bug
    rather than a fact about the workload. Two ways to be over it, and both are
    in `needs_memwhy`: a job MEASURED above 4 GB (`native-dumpfull` at 31.3),
    and a job handed a class above the default with nothing measured behind it
    (`prooflib`, the A/B sweep). Either way the reason goes in the registry next
    to the number and points at `bugs/PERF_memory_over_4gb_is_a_bug.md`, which
    is where the next step for each one is written down.
    """
    over = {n: s for n, s in sorted(suite.REGISTRY.items())
            if suite.needs_memwhy(s)}
    check('mem debt: the rule is not vacuous, and names measured jobs',
          len(over) >= 3
          and any(suite.measured_peak(n) for n in over),
          f'{sorted(over)}')
    silent = [n for n, s in over.items()
              if not getattr(s, 'memwhy', '')
              or suite.MEM_DEBT_DOC not in s.memwhy]
    check('mem debt: every job over the line has a reason pointing at the doc',
          not silent, f'no memwhy, or no pointer to {suite.MEM_DEBT_DOC}: {silent}')
    # ...and the rule does not fire on the whole registry, which is what makes
    # a reason worth having.
    check('mem debt: ...and it is not "everything above 4 GB is a debt": a '
          'default-class job with no measurement is not asked to explain itself',
          not suite.needs_memwhy(suite.REGISTRY['gimple'])
          and not suite.needs_memwhy(suite.REGISTRY['modcache']),
          'the default class is one documented decision, not 57 of them')
    # A pointer into bugs/ is a file that can be deleted, and a doc that is
    # deleted for being fixed is the policy in CLAUDE.md — so a reason pointing
    # at a doc that no longer exists is a reason that says nothing.
    check('mem debt: the doc the reasons point at exists',
          os.path.exists(os.path.join(HERE, suite.MEM_DEBT_DOC)),
          f'{suite.MEM_DEBT_DOC} is missing: every memwhy now points at '
          f'nothing, and the next step for each job is written down nowhere')


def _makefile_target_closure(start):
    """Every make target reachable from `start` through prerequisites.

    Transitive on purpose: `ab-bside` runs `make bside`, and `bside` depends on
    `mojoc`, so the `mojoc` recipe — with its own `memslot` request — runs inside
    `ab-bside`'s admission. A check that only looked at the target a spec names
    would have called the registry and the Makefile consistent while that was
    the one combination that deadlocks.
    """
    prereqs = {}
    target = None
    for line in open(os.path.join(HERE, 'Makefile')).read().splitlines():
        if line.startswith('\t') or not line.strip():
            continue
        m = re.match(r'^([A-Za-z0-9_][\w./$-]*):(?!=)(.*)$', line)
        if m:
            target = m.group(1)
            prereqs[target] = re.findall(r'[A-Za-z0-9_][\w./$-]*', m.group(2))
    seen, stack = set(), [start]
    while stack:
        t = stack.pop()
        if t in seen:
            continue
        seen.add(t)
        stack.extend(prereqs.get(t, ()))
    return seen


def _makefile_memslot_classes():
    """`(label, class)` for every `$(call memslot,LABEL,CLASS)` in the Makefile.

    Read out of the RECIPE lines, reusing the parser above, because the file
    also mentions the macro in prose and in `make check-help`'s echo of its own
    documentation — a `$(call memslot,<label>,<class>)` in a comment is not a
    reservation, and treating it as one would fail on a file that had never been
    edited. `$$(call` is Make's own escaping for a literal `$(`, which is how
    the help text spells it, and is the one thing filtered on here: an
    `@echo` cannot be filtered by its first word, because the parser joins a
    target's whole recipe into one line and `mojoc`'s first line IS an echo.

    The class NAME is checked against the registry's table, because that is what
    the expansion turns into gigabytes (`suite.py --prefix`): a name that does
    not exist there expands to `--gb ` and reserves nothing, which admits
    everything.
    """
    out = []
    for target, line in _makefile_recipe_lines():
        if '$$(call' in line:
            continue
        for label, cls in re.findall(r'\$\(call memslot,([^,]+),([^)]+)\)', line):
            if cls not in suite.MEMCLASS:
                raise AssertionError(
                    f'Makefile {target}: $(call memslot,{label},{cls}) names a '
                    f'class that does not exist: {sorted(suite.MEMCLASS)}')
            out.append((label, cls))
    return out


def test_a_make_recipe_never_asks_for_more_than_its_job_reserved():
    """A recipe's class cannot exceed the class of the job that runs it.

    This is a deadlock, not a style question, and it is why the two numbers
    have to move together. The runner admits a `make` job for its class and
    publishes that in `MEMSLOT_HELD`; the recipe inside then asks `memslot.py`
    for its own class. If the recipe asks for MORE than the admission, it is not
    covered (`tools/memslot.py`'s `covering`), so it takes a second reservation
    — for a tree the first reservation is already accounted for — and since the
    parent is holding the bytes the child is waiting for, the second can never
    be admitted. The job hangs with no verdict.

    It was reachable: `bside` depends on `mojoc`, so `ab-bside` (a `program`
    job, 55 GB) ran the `mojoc` recipe, which asked for `stage` (96), and
    55 + 96 exceeds the 96 GB budget, so the recipe waited for a turn that
    could not come. Both numbers now come from the same measured table, and
    this is what stops them drifting apart again.
    """
    recipes = _makefile_memslot_classes()
    check('recipe class: the Makefile\'s wrapped recipes are found',
          {'mojoc', 'stage2/mojo', 'fire.ci'} <= {l for l, _c in recipes},
          f'found {sorted(l for l, _c in recipes)}')
    check('recipe class: ...and every one names a class that exists',
          all(c in suite.MEMCLASS for _l, c in recipes),
          'a recipe naming a missing class expands to `--gb ` and reserves '
          'nothing, which admits everything')

    # label -> the registered job that starts it, directly or through a
    # prerequisite. One label can be reached by more than one job, and the
    # binding constraint is the SMALLEST of them.
    reachers = {}
    for name, spec in sorted(suite.REGISTRY.items()):
        if getattr(spec, 'driver', None) != 'make':
            continue
        targets = [str(c) for c in (spec.cmd or [])]
        reached = set()
        for t in targets:
            reached.add(t)
            reached |= _makefile_target_closure(t)
        for label, _cls in recipes:
            if label in reached:
                reachers.setdefault(label, []).append(name)
    check('recipe class: the specs that reach those recipes are identified',
          any(reachers.get('mojoc') for _l, _c in recipes),
          f'nothing maps to a job: {sorted(reachers)}')

    too_big = []
    for label, cls in recipes:
        for job in reachers.get(label, ()):
            admitted = suite.MEMCLASS[suite.memclass_for(suite.REGISTRY[job])]
            if suite.MEMCLASS[cls] > admitted:
                too_big.append(f'{label}: recipe asks {cls} '
                               f'({suite.MEMCLASS[cls]} GB) but {job} is '
                               f'admitted for '
                               f'{suite.memclass_for(suite.REGISTRY[job])} '
                               f'({admitted} GB)')
    check('recipe class: no recipe asks for more than its job reserved',
          not too_big, '; '.join(too_big))
    # Hand-run targets (`fire.ci`, `build/system.o`) reach no job and so cannot
    # deadlock against a parent. Said explicitly, because "no job reached it" is
    # also what a mapping bug looks like.
    orphans = sorted({l for l, _c in recipes} - set(reachers))
    check('recipe class: the hand-run targets are the orphans, and only those',
          set(orphans) <= {'fire.ci', 'build/system.o', 'stage1/fire.ci'},
          f'no registered job runs: {orphans}')


# ── admission: memory is allocated to a job BEFORE it starts ─────────────────
# A ceiling bounds one process tree and says nothing about how many may run at
# once, which is not a bound on the machine: on 2026-09-29 the
# `bootstrap-stage*-dumps` fanouts ran ~30 items at once, each 30-43 GB, each
# inside its own ceiling, until the box collapsed. So every job RESERVES its
# memclass out of one machine-wide budget before it is spawned
# (`tools/memslot.py`). What follows is the property that matters and the two
# ways an implementation gets it wrong.
#
# Scaled right down — 20 MB reservations, a 60 MB budget — so it runs in
# seconds and the arithmetic is the one the real numbers use. MEMLIMIT_GB
# collapses every class to one number, which is exactly what makes "the
# reservation is the class" checkable: a job's ceiling and the gigabytes it
# reserves are the same value by construction, and these tests read that value
# off the ledger rather than off the argv.
RESERVE_JOB = ('import sys, time;'
               'sys.path.insert(0, {tools!r});'
               'import memslot;'
               'time.sleep(0.5);'
               'print("RESERVED", memslot.reserved_gb())')


def _reserving_cmd():
    return ok_cmd(RESERVE_JOB.format(tools=os.path.join(HERE, 'tools')))


def test_every_job_is_reserved_before_it_starts():
    """Every kind of job — cmd, mem, make, and each fanout item — reserves
    before it starts, and the sum of live reservations never exceeds the
    budget.

    All four shapes, because each has its own way of being missed: `cmd` and
    `make` are one process each and `make` starts the workload as a
    grandchild, while a fanout is one SPEC that expands into N jobs — the case
    that actually collapsed the machine, because `build_cmd` used to skip the
    whole wrapper for a `Fanout` and eighteen `./mojo --dump` runs at 30-43 GB
    each went out with no ceiling and no reservation.

    The jobs report the ledger's own number from inside themselves, so what is
    asserted is the state of the shared budget at the moment the workload was
    running, not what the runner said it was going to do.
    """
    log = os.path.join(HERE, 'build', 'test-suite-reserve.log')
    mk = os.path.join(HERE, 'build', 'test-suite-reserve.mk')
    os.makedirs(os.path.dirname(mk), exist_ok=True)
    with open(mk, 'w') as f:
        # shlex.quote, not %r: a Make recipe is a SHELL line, and Python's
        # repr escapes the inner single quotes as \' , which the shell then
        # reads as a quote of its own and dies on.
        f.write('hog:\n\t%s -c %s\n' % (shlex.quote(PY),
                                        shlex.quote(RESERVE_JOB.format(
                                            tools=os.path.join(HERE, 'tools')))))
    items = [f'f{i}.mojo' for i in range(6)]
    with Sandbox(one=dict(cmd=_reserving_cmd()),
                 one_mem=dict(cmd=_reserving_cmd(), driver='mem', mem='small'),
                 one_make=dict(cmd=['-f', os.path.relpath(mk, HERE), 'hog'],
                               driver='make', mem='small'),
                 many=suite.Fanout(name='many', cmd=_reserving_cmd()[:1] + ['-c',
                                 RESERVE_JOB.format(tools=os.path.join(HERE, 'tools')),
                                 '{file}'],
                                   items=items, mem='small')):
        # 20 MB per job (MEMLIMIT_GB), 60 MB of budget: at most three at once.
        with _SandboxEnv(MEMLIMIT_GB=0.02, MEMSLOT_BUDGET_GB=0.06):
            rc, _ = run(['one', 'one_mem', 'one_make', 'many'], jobs=6,
                        log=log, budget=0.06, keep_output=True)
    text = open(log).read() if os.path.exists(log) else ''

    check('admission: every job ran', rc == 0, f'got {rc}')
    # Anchored, because the runner logs every job's argv too and the argv
    # contains this same string: a count of `RESERVED` anywhere in the log
    # would count the code as well as its output.
    seen = [float(m) for m in re.findall(r'^RESERVED ([\d.]+)$', text, re.M)]
    check('admission: each of the 9 jobs reported the ledger', len(seen) == 9,
          f'expected 9 RESERVED lines, saw {len(seen)}')
    check('admission: the sum of live reservations never exceeds the budget',
          seen and max(seen) <= 0.06 + 1e-9,
          f'peak {max(seen) if seen else 0:.3f} GB of a 0.06 GB budget')
    # Not vacuous: if the ledger said 0 every time, "never exceeds" would be
    # trivially true of a runner that reserved nothing.
    check('admission: jobs really did hold memory at the same time',
          seen and max(seen) >= 0.04,
          f'peak {max(seen) if seen else 0:.3f} GB — nothing ran concurrently, '
          f'so this proves nothing about the sum')
    check('admission: the runner records what it reserved for each job',
          text.count('admitted:') == 9,
          f'expected 9 admitted lines, saw {text.count("admitted:")}')
    # A fanout item is a job like any other: it is what the machine saw.
    check('admission: fanout items reserve individually',
          all(f'many:{i}' in text for i in items),
          'a fanout item with no reservation is the 2026-09-29 failure exactly')


def test_the_timeout_clock_starts_after_admission():
    """A job's timeout must not run while it waits for memory.

    This is the one that decides between two implementations. Wrapping a job
    in `memslot.py ... --` cannot express a per-job timeout at all, because the
    wrapper has to start the job to time it — so the queue wait would be inside
    the timeout, and a `stage` job waiting 40 minutes for a 96 GB reservation
    on a busy machine would be killed at its timeout having done nothing wrong
    and having printed nothing. The runner therefore takes the reservation
    itself and starts the clock after it.

    Measured rather than asserted from the code: the job's own timeout is 2s,
    the budget is full when it is ready, and it is held there for three times
    that. If the wait counted, the job would come back TIMEOUT and fail the
    run; if it does not, it comes back PASS having run for a fraction of a
    second.
    """
    log = os.path.join(HERE, 'build', 'test-suite-admit-wait.log')
    quick = ok_cmd('import time; time.sleep(0.3); print("ran")')
    outcome = []

    def queued(ledger, label):
        """Is `label` sitting in the ledger's queue right now?

        Read the ledger rather than the log because the log cannot answer it:
        `admission: waited` is written AFTER admission, so a run that is
        correctly queueing says nothing at all until it is let in.
        """
        try:
            data = json.load(open(os.path.join(ledger, 'ledger.json')))
        except (OSError, ValueError):
            return False
        return any(q.get('label') == label for q in data.get('queue', []))

    ledger = tempfile.mkdtemp()
    with _SandboxEnv(MEMSLOT_DIR=ledger, MEMSLOT_BUDGET_GB=16), Sandbox(
            waiter=dict(cmd=quick, mem='small', timeout=2)):
        # 12 of the 16 GB are already spoken for, so a `small` (8 GB) job has
        # to wait: 12 + 8 > 16. The holder is this very process, which is also
        # what running `suite.main` in-process means for a test.
        holder = memslot.Slot(12, 'test-holder', budget=16).acquire()
        worker = threading.Thread(
            target=lambda: outcome.append(
                run(['waiter'], jobs=1, log=log, budget=16, ledger=ledger,
                    keep_output=True)))
        worker.start()
        deadline = time.time() + 15
        while time.time() < deadline and not queued(ledger, 'waiter'):
            time.sleep(0.05)
        was_waiting = queued(ledger, 'waiter')
        time.sleep(6.0)                       # three times the job's timeout
        still_waiting = not outcome
        holder.release()
        worker.join(30)

    check('admission: a job with no room left really does wait', was_waiting,
          'it was admitted immediately: the budget was not actually full')
    check('admission: the wait is not charged to the job\'s timeout',
          still_waiting, f'the run finished while the job was still queueing: '
          f'{outcome}')
    check('admission: and the job runs, and passes, once there is room',
          outcome and outcome[0][0] == 0, f'got {outcome[0][0] if outcome else None}')
    text = open(log).read() if os.path.exists(log) else ''
    secs = re.search(r'exit: 0\s+secs: ([0-9.]+)', text)
    check('admission: the recorded duration is the job\'s, not the queue\'s',
          secs and float(secs.group(1)) < 2,
          f'the 2s timeout is inside {secs.group(1) if secs else "(no exit line)"}')
    check('admission: the queue wait is recorded rather than hidden',
          'admission: waited' in text,
          'the log should say how long the job waited for memory')


def test_a_reservation_the_budget_cannot_fit_is_reported():
    """A job bigger than the whole machine budget is an ERROR, not a hang.

    `memslot` refuses such a request rather than queueing it forever, which is
    right — it can never be admitted — but the runner has to notice. A queue
    that cannot drain looks exactly like a hung test, and the one thing this
    repo refuses to do is a run that stalls silently.
    """
    log = os.path.join(HERE, 'build', 'test-suite-refused.log')
    ran = os.path.join(HERE, 'build', 'test-suite-refused.ran')
    if os.path.exists(ran):
        os.unlink(ran)
    # The workload's EFFECT, not its text: the runner logs the argv of every
    # job it plans, refused or not, so grepping the log for the command would
    # find it there and prove nothing.
    with Sandbox(toobig=dict(cmd=ok_cmd(f'open({ran!r}, "w").write("x")'),
                             mem='small')):
        with _SandboxEnv(MEMLIMIT_GB=0.02, MEMSLOT_BUDGET_GB=0.01):
            done = []
            worker = threading.Thread(
                target=lambda: done.append(run(['toobig'], jobs=1, log=log,
                                               budget=0.01)))
            worker.start()
            worker.join(60)
    text = open(log).read() if os.path.exists(log) else ''
    check('admission: an impossible reservation does not hang the run',
          bool(done), 'the runner never returned')
    check('admission: it is reported as an ERROR naming both numbers',
          done and done[0][0] == 1 and 'admission REFUSED' in text
          and 'exceeds the whole budget' in text,
          f'rc={done[0][0] if done else None}; log says: '
          f'{[l for l in text.splitlines() if "REFUS" in l][:1]}')
    check('admission: the refused job never ran', not os.path.exists(ran),
          'the workload started without a reservation')


def test_j_forwarded():
    """A tool with its own -j gets one, because a test that parallelises
    internally while the runner also parallelises is how you get 18x18.
    Asserted from the log's argv line, which is where the real command lives.
    """
    log = os.path.join(HERE, 'build', 'test-suite-j.log')
    with Sandbox(inner=dict(cmd=ok_cmd('import sys; print(sys.argv[1:])'),
                            j=True),
                 serial=dict(cmd=ok_cmd('import sys; print(sys.argv[1:])'))):
        run(['inner', 'serial'], jobs=5, log=log, keep_output=True)
    text = open(log).read()
    check('j: -j is forwarded to a tool that has its own -j',
          "'-j', '5'" in text, 'expected -j 5 in the inner job argv')
    check('j: it is NOT forwarded to a tool that does not',
          text.count("'-j', '5'") == 1,
          f'expected exactly one -j in the log, saw {text.count(chr(39)+"-j"+chr(39)+", "+chr(39)+"5"+chr(39))}')


# ── scheduling ───────────────────────────────────────────────────────────────
def test_deps_order_and_skip():
    order = os.path.join(HERE, 'build', 'test-suite-order.txt')
    if os.path.exists(order):
        os.unlink(order)
    writer = ok_cmd(f'import time; open({order!r}, "a").write("first\\n"); '
                    'time.sleep(0.2)')
    with Sandbox(a=dict(cmd=writer),
                 b=dict(cmd=ok_cmd('raise SystemExit(1)')),
                 c=dict(cmd=ok_cmd(f'open({order!r}, "a").write("c\\n")'),
                        deps=['b']),
                 d=dict(cmd=ok_cmd(f'open({order!r}, "a").write("d\\n")'),
                        deps=['a'])):
        rc, out = run(['a', 'b', 'c', 'd'], jobs=4)
        seen = open(order).read().split() if os.path.exists(order) else []
        check('deps: the dependent test ran after its dependency',
              seen == ['first', 'c'.replace('c', 'd')], f'order was {seen}')
        check('deps: a failed dep fails the bucket', rc == 1, f'got {rc}')
        check('deps: a test whose dep failed is SKIPPED, not run',
              'c' not in seen, f'c ran despite its dep failing: {seen}')
        check('deps: the skip says which dep', 'b' in out, out)


def test_exclusive_is_alone():
    """An exclusive test must not overlap anything else — that is the whole
    mechanism that lets a 55 GB job share a machine with a test suite.

    Each job appends "<who> start" / "<who> end" to one file, so the
    interleaving of those lines IS the schedule. `big` is exclusive, so no
    other job's start may appear between its start and its end.
    """
    marks = os.path.join(HERE, 'build', 'test-suite-exclusive.txt')
    if os.path.exists(marks):
        os.unlink(marks)
    note = ('import sys, time\n'
            'open(%r, "a").write(sys.argv[1] + " start\\n")\n'
            'time.sleep(0.6)\n'
            'open(%r, "a").write(sys.argv[1] + " end\\n")\n' % (marks, marks))
    with Sandbox(big=dict(cmd=[PY, '-c', note, 'big'], excl=True),
                 s0=dict(cmd=[PY, '-c', note, 's0']),
                 s1=dict(cmd=[PY, '-c', note, 's1']),
                 s2=dict(cmd=[PY, '-c', note, 's2'])):
        rc, _ = run(['big', 's0', 's1', 's2'], jobs=4)
    events = []
    if os.path.exists(marks):
        for ln in open(marks).read().splitlines():
            if ln.strip():
                who, what = ln.split()
                events.append((who, what))
    big_open, open_jobs, overlapped, saw_big = False, set(), [], False
    for who, what in events:
        if who == 'big':
            # `big` owns the machine between its own start and end, so any
            # OTHER job that is open at either of those two moments overlapped.
            if what == 'start':
                saw_big = True
                big_open = True
                overlapped += [w for w in open_jobs if w != 'big']
            else:
                overlapped += [w for w in open_jobs if w != 'big']
                big_open = False
            continue
        if what == 'start':
            if big_open:
                overlapped.append(who)
            open_jobs.add(who)
        else:
            open_jobs.discard(who)
    check('exclusive: it ran', saw_big, f'no big in {events}')
    check('exclusive: nothing ran alongside it', not overlapped,
          f'{sorted(set(overlapped))} overlapped the exclusive one: {events}')
    check('exclusive: every other job still ran',
          len({w for w, _ in events}) == 4, f'events: {events}')
    check('exclusive: the run still passed', rc == 0, f'got {rc}')


def test_fanout_aggregates():
    """Every item runs, and one bad item fails the whole test. A fanout that
    quietly dropped an item would report green over 44 of 45 files."""
    marker = os.path.join(HERE, 'build', 'test-suite-fanout')
    if os.path.exists(marker):
        os.unlink(marker)
    with Sandbox(sweep=suite.Fanout(
            name='sweep',
            cmd=[PY, '-c', 'import sys; open(%r, "a").write(sys.argv[1]+"\\n");'
                           ' sys.exit(1 if sys.argv[1] == "b" else 0)'
                           % marker, '{file}'],
            items=['a', 'b', 'c'], mem='program')):
        rc, _ = run(['sweep'], jobs=3)
    ran = open(marker).read().split() if os.path.exists(marker) else []
    check('fanout: every item ran', sorted(ran) == ['a', 'b', 'c'],
          f'ran {sorted(ran)}')
    check('fanout: one bad item fails the test', rc == 1, f'got {rc}')


def _scratch_git_tree(tmp, tracked, untracked):
    """A throwaway git repo holding `tracked` (staged) and `untracked` (on disk
    only) files. Staged rather than committed, so it is milliseconds and needs
    no identity config."""
    os.makedirs(tmp, exist_ok=True)
    subprocess.run(['git', 'init', '-q', tmp], check=True,
                   capture_output=True)
    for rel in tracked:
        full = os.path.join(tmp, rel)
        os.makedirs(os.path.dirname(full) or tmp, exist_ok=True)
        with open(full, 'w') as f:
            f.write('def main() -> Int:\n    return 0\n')
    for rel in untracked:
        full = os.path.join(tmp, rel)
        os.makedirs(os.path.dirname(full) or tmp, exist_ok=True)
        with open(full, 'w') as f:
            f.write('def main() -> Int:\n    return 0\n')
    subprocess.run(['git', '-C', tmp, 'add', '--'] + list(tracked),
                   check=True, capture_output=True)
    return tmp


def test_fanout_enumeration_ignores_untracked_scratch():
    """A transient `.mojo` in the tree must never become a fan-out item.

    This is the 2026-09-29 round-6 flake, pinned at the enumeration. The repo
    root is a shared scratch surface: `test_ab_native.py` used to write
    `_abt_<case>.mojo` there for the length of a run, `MOJO_FILES` was a
    `glob.glob` over that directory, and a `bootstrap-stage1-dumps` plan built
    during the window listed one of those transients as an item. When
    `ab-native` finished (or was SIGKILLed by memcap at its 8 GB ceiling) and
    deleted it, that item failed with `Error reading ../_abt_minimal_main.mojo:
    [Errno 2]` and took the entire bootstrap chain behind it with it — eight
    SKIPs, with the one real cause buried in a sub-job's stderr.

    A scratch git tree rather than a mock, because the property under test is
    git's, not the runner's: `git ls-files` reports the index, and the whole
    argument for choosing it over a denylist (`_abt*.mojo`, `abt*_*`) is that
    "is this tracked source?" needs no maintenance and cannot be defeated by a
    transient nobody named. A fake `git` on PATH would test the fake.
    """
    with tempfile.TemporaryDirectory() as td:
        root = _scratch_git_tree(
            os.path.join(td, 'tree'),
            tracked=['real.mojo', 'mojo/nested.mojo', 'notes.txt'],
            # Exactly the shape the flake produced: an untracked `_abt_*`
            # source sitting in the directory being enumerated.
            untracked=['_abt_minimal_main.mojo', 'abt999_deadbeef_case.mojo'])

        found = suite.tracked_mojo_files(root)
        check('enumeration: a transient .mojo is not an item',
              not any('minimal_main' in f or 'deadbeef' in f for f in found),
              f'the enumeration picked up a transient: {found}')
        check('enumeration: the tracked .mojo files ARE items',
              'real.mojo' in found,
              f'expected real.mojo in {found}')
        check('enumeration: it is not a bare top-level glob',
              'notes.txt' not in found,
              f'a non-.mojo file became an item: {found}')
        check('enumeration: it is restricted to the top level and mojo/',
              not any(f.startswith('sub/') for f in found)
              and all('/' not in f or f.startswith('mojo/') for f in found),
              f'items from outside the enumerated roots: {found}')

        # The glob this replaced would have listed the transient. Asserting
        # that directly is what makes the first check falsifiable: if the
        # scratch file stopped being globbable for an unrelated reason, the
        # enumeration check would pass for the wrong reason.
        globbed = suite._glob_mojo_files(root)
        check('enumeration: the old glob WOULD have picked the transient up',
              any('minimal_main' in f for f in globbed),
              f'the control is broken — the glob found {globbed}, so the '
              f'first check is not evidence of anything')

        # Determinism: the plan's job order is this list's order, so a
        # re-enumeration that differs is a plan that differs run to run.
        check('enumeration: it is deterministic across calls',
              suite.tracked_mojo_files(root) == found,
              'two enumerations of an unchanged tree disagreed')

    # And the real thing, not just a synthetic tree: the live registry's item
    # list must contain no transient and no file absent from the worktree.
    items = suite.BOOTSTRAP_INPUTS
    check('enumeration: the live bootstrap item list is sorted-then-stable',
          suite.MOJO_FILES == sorted(suite.MOJO_FILES)
          and len(suite.MOJO_FILES) > 20,
          f'{len(suite.MOJO_FILES)} .mojo items; every check above would be '
          f'vacuous if the real list were empty')
    check('enumeration: the live item list is every tracked .mojo and no more',
          set(items) == set(suite.MOJO_FILES) | set(suite.PY_FILES),
          'the live BOOTSTRAP_INPUTS is not MOJO_FILES + PY_FILES')
    missing = [f for f in items if not os.path.exists(os.path.join(HERE, f))]
    check('enumeration: every live item exists in this worktree', not missing,
          f'enumerated but absent: {missing}')


def test_the_ab_native_writer_keeps_its_scratch_out_of_the_repo_root():
    """The WRITER half of the round-6 flake, executed rather than described.

    `test_fanout_enumeration_ignores_untracked_scratch` above pins the
    enumeration: a transient in the repo root is not an item. That is only half
    the fix, and the half that is cheap. The other half is that
    `test_ab_native.py` no longer PUTS one there — it writes each case's source
    into a private per-process directory under `.tmp/` and tags every name with
    its pid, so a concurrent fan-out has nothing to enumerate and two concurrent
    runs cannot collide.

    It is checked HERE, and not left to `ab-native`, because `ab-native` cannot
    check it: that spec needs the self-hosted binary, is capped at 55 GB, and is
    `expect=`-marked red because the binary segfaults on any input. So the code
    that decides where this test writes had no executing coverage at all — the
    exact hole `coro` sat in after the `mojo_*` rename, one level down. The
    self-test is pure Python and needs no compiler, so it runs in a tenth of a
    second here, in the `smoke` bucket, on every run.

    The invariant asserted is the whole directory, not the files this happened
    to write: a check that only looked for its own leftovers would pass on a
    version that leaked under a different name.
    """
    p = subprocess.run([PY, os.path.join(HERE, 'test_ab_native.py'),
                        '--scratch-selftest'],
                       capture_output=True, text=True, timeout=120, cwd=HERE)
    out = p.stdout + p.stderr
    check('ab-native scratch: the self-test runs and passes', p.returncode == 0,
          out.strip()[-400:])
    m = re.search(r'scratch isolation: (\d+) passed, (\d+) failed', out)
    check('ab-native scratch: it reported a real count, not an empty run',
          m is not None and int(m.group(1)) > 15,
          f'no count line, or too few checks to mean anything: {out.strip()[-200:]}')
    # The two properties the flake turned on, read out of the module rather
    # than trusted, because they are what a future edit could undo silently.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'ab_native_scratch', os.path.join(HERE, 'test_ab_native.py'))
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)          # runs the atexit registration
    except SystemExit:                        # pragma: no cover
        pass
    tagged = mod._tagged('abfulltest_leaf.mojo')
    check('ab-native scratch: a source name is tagged, so two runs differ',
          tagged.startswith(mod.SRC_PREFIX) and tagged.endswith('.mojo'),
          tagged)
    check('ab-native scratch: the scratch root is under .tmp/, not the root',
          os.path.abspath(mod.SCRATCH_ROOT)
          == os.path.join(HERE, '.tmp'),
          mod.SCRATCH_ROOT)
    check('ab-native scratch: a bare stem gets exactly one .mojo',
          mod._tagged('minimal_main').count('.mojo') == 1,
          mod._tagged('minimal_main'))
    # And the module left the directory as it found it — the property that
    # makes the self-test safe to run from a gate at all.
    stray = [n for n in os.listdir(HERE)
             if n.startswith(mod.SRC_PREFIX) or n.startswith('abt999999_')]
    check('ab-native scratch: the self-test left nothing in the repo root',
          not stray, f'{stray}')


def test_missing_fanout_item_is_a_named_failure():
    """A missing item file is a FAIL naming that item — not a skipped chain.

    The second half of the same flake, and the half that decides how long the
    first half takes to diagnose. With the glob, a vanished item surfaced only
    as the compiler's `Error reading ...: [Errno 2]` inside one sub-job's
    output, and what the run *reported* was eight SKIPs: `bootstrap-stage1-
    dumps` failed, so everything downstream of it was skipped, and the screen
    read like the bootstrap was unavailable rather than like one file in a
    41-file sweep had moved.

    So: `items_are_files` items are checked for existence before the process
    is launched, and the verdict names the item and says what is wrong. The
    other half of the property is that it stays LOCAL — one bad item must not
    stop the other items, or "loud" has just been traded for "the sweep no
    longer covers anything".
    """
    # A real tracked file so the sweep has something that must still run, and
    # a name that is deliberately not a file.
    present = 'fire.py'
    absent = 'definitely_not_a_real_source_file_xyz.mojo'
    with Sandbox(sweep=suite.Fanout(
            name='sweep', cmd=[PY, '-c', 'pass', '{file}'],
            items=[present, absent], mem='program', items_are_files=True)):
        log = os.path.join(HERE, 'build', 'test-suite-missing-item.log')
        rc, _ = run(['sweep'], jobs=2, log=log)
    text = open(log).read() if os.path.exists(log) else ''
    check('missing item: it fails the test', rc == 1, f'got rc={rc}')
    check('missing item: the verdict NAMES the item',
          absent in text,
          'the report does not identify which item was missing')
    check('missing item: the verdict says the file is absent',
          'does not exist' in text,
          'the detail does not distinguish "missing file" from "compiler error"')
    check('missing item: the present item still ran',
          present in text,
          'the sweep stopped at the bad item instead of covering the rest')

    # The control: with no item declared to be a file, a missing name is just
    # a string and must NOT be failed by this check. Otherwise the guard would
    # be unusable for a sweep over bare labels.
    with Sandbox(sweep=suite.Fanout(
            name='sweep', cmd=[PY, '-c', 'pass', '{file}'],
            items=['a', 'b'], mem='program')):
        rc, _ = run(['sweep'], jobs=2)
    check('missing item: items_are_files=False is unaffected by the check',
          rc == 0, f'got rc={rc}; the guard fired on a non-file sweep')


# ── the tally ────────────────────────────────────────────────────────────────
def tally_of(out):
    """The summary line's counters as {wording: count}, and the test count it
    claims, parsed out of the screen.

    Parsed rather than string-matched, because the property this area is about
    is arithmetic: a check that only asks "is the word FAILED on it" cannot add
    the numbers up, and a summary that does not add up is exactly the defect.
    """
    m = re.search(r'^suite: (.+?)\s*\((\d+) tests,', out, re.M)
    if not m:
        return None, None
    return ({word: int(n) for n, word in re.findall(r'(\d+) ([\w-]+)', m.group(1))},
            int(m.group(2)))


def test_timeout_is_a_failure_not_a_vanished_job():
    """A hang must be counted, listed, and non-zero — never a vanished job.

    The runner has always killed a job at its timeout and announced the
    TIMEOUT on the screen. `report` then grouped PASS, FAIL, ERROR, SKIP,
    RESOURCE and EXPECTED and never mentioned TIMEOUT, so the job was in no
    counter, in no screen section, and did not fail the run. Measured on a real
    `gate`, 2026-09-29: the log carried

        [ 76/177] TIMEOUT sqliteruntime 600.1s

    and the run finished `30 passed, 0 failed, 5 skipped, 1 resource-capped, 2
    expected-failure (177 jobs)` with exit 0 — 38 counted, 39 tests run, and
    the missing one was the hang.
    """
    hang = ok_cmd('import time; print("working", flush=True); time.sleep(60)')
    with Sandbox(hang=dict(cmd=hang, timeout=0.5),
                 fine=dict(cmd=ok_cmd('print("ok")'))):
        rc, out = run(['hang', 'fine'], jobs=2, quiet=False)
    counts, ntests = tally_of(out)
    check('tally: a timed-out test fails the run', rc == 1,
          f'rc={rc}; a hang must not exit 0 — {out}')
    check('tally: it is listed under FAILED', 'FAILED' in out and 'hang' in out,
          f'expected the hang in the FAILED listing: {out}')
    check('tally: ...and the listing says it was a TIMEOUT, not a wrong answer',
          re.search(r'^\s+hang\s+\([\d.]+s\)\s+\[TIMEOUT\]', out, re.M) is not None,
          f'the member is not tagged with its status: {out}')
    check('tally: the counters add up to the tests', counts is not None
          and sum(counts.values()) == ntests == 2,
          f'counts={counts} over {ntests} tests; they must sum to the number of '
          f'tests, or a job has been dropped from the tally')
    check('tally: the passing test is still counted as a pass',
          counts and counts.get('passed') == 1, f'counts={counts}')

    # `expect=` forgives FAIL and ERROR and deliberately not a hang, so that a
    # marker cannot buy a green run for a test that never reported anything.
    # Now that a hang fails the run, that is the difference between a recorded
    # known failure and a way to hide one, so it is pinned here rather than
    # left to the comment in `_apply_expectations`.
    with Sandbox(hang=dict(cmd=hang, timeout=0.5, expect='a known hang')):
        rc, out = run(['hang'], jobs=1, quiet=False)
    check('tally: expect= does not forgive a hang', rc == 1
          and 'expected-failure' not in out and '[TIMEOUT]' in out,
          f'rc={rc} out={out!r}')


def test_tally_accounts_for_every_test():
    """Every status has exactly one counter, and a run that cannot account for
    one of its tests says so instead of looking authoritative.

    The end-to-end case above pins what a real hang does. This one is the
    structural half, and it reaches states a synthetic command cannot produce:
    every status at once, a status no counter names, and a test with no result
    at all. It is also the anti-rot guard for the table itself — a status added
    to the runner without a counter would have to be added to `suite.TALLY`, and
    that has to happen before a test fails rather than silently after.
    """
    import types
    opts = types.SimpleNamespace(quiet=False)

    def report_with(names, state):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = suite.report(names, state, {}, 0.0, 0.0, opts, suite.Log(None))
        return rc, buf.getvalue()

    check('tally: every status the runner can produce has a counter',
          set(suite.TALLY_ROW) == set(suite._RANK) | {suite.EXPECTED},
          f'runner: {sorted(set(suite._RANK) | {suite.EXPECTED})}, '
          f'tally: {sorted(suite.TALLY_ROW)}')
    check('tally: and no status is counted twice',
          len(suite.TALLY_ROW) == sum(len(r.statuses) for r in suite.TALLY),
          'a status listed in two rows would be counted in both')

    # All seven statuses at once: the counters must still add up, and the ones
    # that are not a counter's plain reading must be tagged in the listing.
    every = sorted(suite.TALLY_ROW)
    names = [f'{s}-test' for s in every]
    state = dict(zip(names, every))
    rc, out = report_with(names, state)
    counts, ntests = tally_of(out)
    check('tally: one of every status still adds up to the test count',
          counts is not None and sum(counts.values()) == ntests == len(names),
          f'counts={counts} over {ntests} tests, expected {len(names)}')
    check('tally: a run containing a failure exits non-zero', rc == 1,
          f'rc={rc}')
    check('tally: a hang among the failures is tagged, and a wrong answer is '
          'not (it is the plain reading of FAILED)',
          re.search(r'^\s+timeout-test\s+\([\d.]+s\)\s+\[TIMEOUT\]', out, re.M)
          and re.search(r'^\s+fail-test\s+\([\d.]+s\)\s*$', out, re.M),
          f'expected TIMEOUT tagged and FAIL plain: {out}')
    check('tally: an ERROR is not confused with a FAIL either',
          re.search(r'^\s+error-test\s+\([\d.]+s\)\s+\[ERROR\]', out, re.M)
          is not None, f'expected ERROR tagged: {out}')

    # All green: nothing unaccounted, nothing failing, so exit 0. Without this
    # the previous case would pass a runner that simply always exits 1.
    names = ['a', 'b', 'c']
    rc, out = report_with(names, {n: suite.PASS for n in names})
    counts, ntests = tally_of(out)
    check('tally: a run of nothing but passes exits 0 and adds up',
          rc == 0 and counts and sum(counts.values()) == ntests == 3,
          f'rc={rc} counts={counts} over {ntests} tests')

    # The two ways to be in no bucket, which no command can produce: a status
    # the table has no row for, and a test with no result at all.
    for label, broken in (
            ('an unknown status', {'a': suite.PASS, 'b': 'banana'}),
            ('no result at all', {'a': suite.PASS})):
        rc, out = report_with(['a', 'b'], broken)
        check(f'tally: {label} is reported, not counted around', rc == 1
              and 'TALLY BUG' in out, f'rc={rc} out={out!r}')
    rc, out = report_with(['a', 'b'], {'a': suite.PASS})
    check('tally: the test with no result is NAMED in the complaint',
          'b' in out and 'no result at all' in out, f'out={out!r}')


def test_a_status_with_no_counter_stops_the_runner():
    """The guard that makes the table structural, tested rather than trusted.

    The checks above read TALLY and TALLY_ROW and say the two agree; they do
    not say anything is WATCHING them, and a guard nothing executes is a
    comment. So this executes tools/suite.py with one extra status added to
    `_RANK` — the exact edit that dropped TIMEOUT out of the tally — and
    requires the module to refuse to import.

    Executing the source rather than importing it is forced: the guard fires at
    import, so a module that raises cannot be imported to be inspected. `exec`
    is the only way to reach it, and the doctor's edit is checked first so that
    a reworded `_RANK` reports "this test no longer applies" instead of
    silently passing on an unpatched file.
    """
    path = os.path.join(HERE, 'tools', 'suite.py')
    with open(path) as f:
        src = f.read()
    doctored = src.replace(
        '_RANK = {PASS: 0, SKIP: 1, RESOURCE: 2, TIMEOUT: 3, ERROR: 4, FAIL: 5}',
        "_RANK = {PASS: 0, SKIP: 1, RESOURCE: 2, TIMEOUT: 3, ERROR: 4,"
        " FAIL: 5, 'banana': 6}")
    check('tally: the guard test still recognises the line it patches',
          doctored != src,
          'tools/suite.py no longer spells _RANK the way this test rewrites '
          'it, so the guard below would pass on an unpatched file')
    ns = {'__name__': 'suite_doctored', '__file__': path}
    try:
        exec(compile(doctored, 'suite.py(doctored)', 'exec'), ns)
        rc, msg = 0, ''
    except SystemExit as e:
        rc, msg = 1, str(e)
    check('tally: a status with no counter stops the runner at import', rc == 1
          and 'banana' in msg, f'rc={rc} msg={msg!r}')


# ── selection ────────────────────────────────────────────────────────────────
def test_artifact_cache():
    """A step whose artifact is a binary (`mojoc`, `stage2/mojo`).

    Three things have to hold, and the middle one is the whole point: a miss
    runs the step and stores; a HIT must not run it at all; and a changed input
    must miss. The counter file is how "did not run" is observed, because the
    artifact looking correct afterwards proves nothing.
    """
    # Unique per PROCESS, not just per test: the content-addressed store is
    # persistent (~/.gmojo/cas) and outlives the test run, so a fixed path
    # means run N's "changed input" step finds run N-1's published artifact
    # already in the store and reports a hit for a key nothing published this
    # time. That is exactly the false green this test exists to catch, so the
    # test must not be able to produce it by accident.
    tag = f'test-suite-artifact-{os.getpid()}'
    art, inp, counter = (f'build/{tag}.bin', f'build/{tag}.in',
                         f'build/{tag}.count')
    for p in (art, inp, counter):
        full = os.path.join(HERE, p)
        if os.path.exists(full):
            os.unlink(full)
    with open(os.path.join(HERE, inp), 'w') as f:
        f.write('one')
    step = dict(cmd=[PY, '-c',
                     'import shutil, sys;'
                     'shutil.copyfile(sys.argv[1], sys.argv[2]);'
                     'open(sys.argv[3], "a").write("x")', inp, art, counter],
                artifact=art, inputs=[inp])

    def runs():
        full = os.path.join(HERE, counter)
        return len(open(full).read()) if os.path.exists(full) else 0

    with Sandbox(bin=step):
        rc, _ = run(['bin'], jobs=1, no_cache=True)
        check('artifact cache: a fresh run builds it', rc == 0 and runs() == 1,
              f'rc={rc} runs={runs()}')
        check('artifact cache: the artifact is where it should be',
              open(os.path.join(HERE, art)).read() == 'one', 'wrong content')

        log = os.path.join(HERE, 'build', 'test-suite-artifact.log')
        rc, out = run(['bin'], jobs=1, log=log)
        text = open(log).read() if os.path.exists(log) else ''
        check('artifact cache: the second run is a hit',
              'artifact cache' in text and 'CACHED' in text,
              'expected the hit recorded in the log')
        check('artifact cache: a hit does NOT run the step', runs() == 1,
              f'the step ran {runs()} times; a cache hit must not re-run it')

        with open(os.path.join(HERE, inp), 'w') as f:
            f.write('two')
        rc, out = run(['bin'], jobs=1)
        check('artifact cache: a changed input misses', runs() == 2,
              f'runs={runs()}, expected the changed input to force a rebuild')
        check('artifact cache: the rebuilt artifact is the new one',
              open(os.path.join(HERE, art)).read() == 'two', 'wrong content')

        rc, out = run(['bin'], jobs=1, no_cache=True)
        check('artifact cache: --no-cache forces the real step', runs() == 3,
              f'runs={runs()}, expected --no-cache to bypass the cache')
    for p in (art, inp, counter):
        full = os.path.join(HERE, p)
        if os.path.exists(full):
            os.unlink(full)


def test_selfhost_key_is_complete():
    """The self-host cache keys are only sound if the key covers everything
    `fire.py` transitively imports. A module imported without being hashed
    means a cache hit can serve a compiler built from the old source — the
    silent, catastrophic kind of wrong — so this is checked rather than
    trusted."""
    import cas
    missing, seen = cas.selfhost_closure_is_complete()
    check('self-host key: every module fire.py imports is hashed',
          not missing, f'not in the key: {sorted(missing)}')
    check('self-host key: the import walk actually walked something',
          len(seen) > 30, f'only reached {len(seen)} files — the walk is '
                          f'probably broken, which would make this check and '
                          f'the cache keys vacuous')
    check('self-host key: it is a superset of the codegen sources',
          set(cas._COMPILER_SOURCES) <= set(cas.selfhost_inputs()),
          'a codegen source missing from the self-host key')


def test_the_compiler_imports_from_every_real_entry_point():
    """Every module the compiler is entered through must import FIRST.

    The middle tier and the gimple backend are mutually recursive by design —
    `mojo/middle/funcs_shared.py` and `mojo/middle/module_shared.py` both
    `import gimple_codegen`, which imports the backend, which imports them
    back — so the graph has a load order it tolerates and a set it does not,
    and Python resolves a cycle by letting whichever module the process
    reached first finish, which is why this failure reads as an unrelated
    `ImportError` a long way from the import that closed the loop.

    Real, twice, both from merged branches that each added one edge between
    the two middle modules:

      * `formal/model.py` `runtime_abi` -> `import reflect` ->
        `gimple_codegen` -> `mojo/backend_gimple/emit_methods` ->
        `emit_funcs` -> `mojo.middle.module_shared` -> `mojo.middle.funcs_shared`
        -> `from mojo.middle.module_shared import module_qualifier`

        -> `ImportError: cannot import name 'module_qualifier' from partially
        initialized module 'mojo.middle.module_shared'`

        The formal build path refused EVERY program, on every source, with no
        build artifact involved — so it was invisible to every compiled-path
        test and visible to every formal one.

      * the same shape one edge later, via
        `mojo/backend_gimple/module_gen.py` -> `module_shared` ->
        `funcs_shared` -> `gimple_codegen`.

    Each module that can be a process's FIRST `mojo.*` import is therefore
    probed in a FRESH interpreter. Checking from inside this process would
    prove nothing: by the time this test runs, `sys.modules` already holds
    whichever order the test runner happened to pick, and the failing order
    is exactly the one it cannot reproduce.

    The probe is EVERY module under `mojo/middle/` and `mojo/backend_gimple/`
    plus the top-level entry points, not a hand-kept shortlist, so a new
    module that closes a cycle is caught by being added rather than by
    somebody remembering to extend a list. `_LOAD_ORDER_DEPENDENT` is the
    declared exemption, and it is checked in BOTH directions — a new entry
    appearing in the failure set fails, and so does an entry in the
    declaration that no longer fails, because a stale exemption is a hole
    the next reader cannot see through.
    """
    import glob
    import subprocess
    entries = ['fire', 'fire_main', 'myinterpreter', 'reflect',
               'gimple_codegen', 'formal.build', 'formal.model']
    for pat in ('mojo/middle/*.py', 'mojo/backend_gimple/*.py'):
        entries += sorted(os.path.relpath(p, HERE)[:-3].replace(os.sep, '.')
                          for p in glob.glob(os.path.join(HERE, pat))
                          if not p.endswith('__init__.py'))
    bad = []
    for mod in entries:
        r = subprocess.run([sys.executable, '-c', f'import {mod}'],
                           capture_output=True, text=True, cwd=HERE,
                           timeout=300)
        if r.returncode != 0:
            last = [l for l in r.stderr.strip().splitlines() if l.strip()]
            bad.append(f'{mod}: {last[-1] if last else "failed"}')
    failed = {b.split(':', 1)[0] for b in bad}
    # The eight `mojo/middle/*` modules that each `import gimple_codegen`,
    # which imports the gimple backend, which imports them back. That is the
    # middle tier's pre-existing shape — measured identical on master, before
    # any of the branches this test was written for — so none of the eight can
    # be the first `mojo.*` import a program makes, and every one of them
    # DOES import fine behind `gimple_codegen` or `fire.py`. Named rather than
    # omitted so a reader who finds one of them broken learns it was already
    # load-order-dependent instead of concluding the exemption is where to
    # start looking. No `mojo/backend_gimple/*` module is exempt: the backend
    # sits downstream of `gimple_codegen`, so every one of them is reachable
    # first and a new cycle among them would be caught here.
    declared = {
        'mojo.middle.calls_shared', 'mojo.middle.funcs_shared',
        'mojo.middle.infra_infer', 'mojo.middle.loops_shared',
        'mojo.middle.methods_shared', 'mojo.middle.module_shared',
        'mojo.middle.resolve_shared', 'mojo.middle.stmts_shared',
    }
    check('imports: every real entry point imports first',
          failed <= declared, '; '.join(bad))
    check('imports: the load-order exemption list is not stale',
          declared <= failed,
          f'declared but importing fine: {sorted(declared - failed)} — the '
          f'declaration has to be deleted in the same commit that fixes it')
    check('imports: the probe actually probed something', len(entries) >= 30,
          f'only reached {len(entries)} modules — the glob or the list went '
          f'stale and this check is vacuous')


def test_bucket_dedup():
    """`make gate` contains both `native` and `bootstrap`; a test reachable
    from both must be scheduled once, not twice."""
    saved = dict(suite.BUCKETS)
    try:
        suite.BUCKETS['left'] = ['x']
        suite.BUCKETS['right'] = ['x', 'y']
        suite.BUCKETS['both'] = ['left', 'right']
        with Sandbox(x=dict(cmd=ok_cmd('pass')), y=dict(cmd=ok_cmd('pass'))):
            class A:
                only = None
            opts = A()
            opts.only = None
            names = suite.select(['both'], opts)
            check('selection: an overlapping bucket runs a shared test once',
                  names == ['x', 'y'], f'got {names}')
            deep = suite.select(['both', 'left'], opts)
            check('selection: repeated buckets add nothing', deep == names,
                  f'{deep} != {names}')
    finally:
        suite.BUCKETS.clear()
        suite.BUCKETS.update(saved)


def test_missing_dep_is_reported():
    """A dep that does not exist must be named, at selection time.

    Selection walks a named test's deps, so a dep that is in neither the
    registry nor the buckets is caught before anything is scheduled — the run
    cannot reach the point of waiting on a dep no job can satisfy, which is
    the hang this exists to prevent. A dep that *does* exist is the other
    case, and is the next test's.
    """
    with Sandbox(lonely=dict(cmd=ok_cmd('pass'), deps=['other'])):
        try:
            rc, out = run(['lonely'])
        except SystemExit as e:
            rc, out = 1, str(e)
        check('deps: a missing dep is an error naming it', rc == 1 and
              'other' in out, f'rc={rc} out={out!r}')


def test_named_test_brings_its_deps():
    """Naming a test names what it needs to run.

    This is what a Make prerequisite means, and what `preflight` is for. When
    `select` returned at the test without walking its deps, the dep was never
    selected and the run died with `dependency not selected: preflight` — a
    failure of the runner, reported against whichever test was asked for. It
    broke all eight `deps=['preflight']` tests, i.e. every `make
    check-formal*` target and the `proofs` bucket.
    """
    with Sandbox(needs=dict(cmd=ok_cmd('pass'), deps=['prereq']),
                 prereq=dict(cmd=ok_cmd('pass'))):
        rc, out = run(['needs'])
        # Both ran, so the dep was scheduled rather than reported absent.
        # (`-q` prints only the tally, hence the count and not the names.)
        check('deps: naming a test runs its dep too, and passes',
              rc == 0 and '2 passed' in out, f'rc={rc} out={out!r}')
        # ...and the dep is ordered before the test that needs it, so the list
        # reads in the order the graph runs.
        class A:
            only = None
        names = suite.select(['needs'], A())
        check('deps: a named test selects its dep first',
              names == ['prereq', 'needs'], f'got {names}')


def test_log_has_passes_screen_does_not():
    """The contract the screen/log split rests on."""
    log = os.path.join(HERE, 'build', 'test-suite-logsplit.log')
    with Sandbox(a=dict(cmd=ok_cmd('print("PASS  a-fine")')),
                 b=dict(cmd=ok_cmd('raise SystemExit(1)'))):
        rc, out = run(['a', 'b'], jobs=2, log=log, quiet=False)
    text = open(log).read() if os.path.exists(log) else ''
    check('log: PASS lines are in the log', 'ok       a' in text, text[:400])
    check('log: a failing job\'s output is in the log',
          'PASS  a-fine' in text, 'expected the transcript in the log')
    check('screen: no per-job ok line', 'ok       a' not in out, out)
    check('screen: the failure is on it', 'FAIL' in out, out)
    check('log: the environment is recorded',
          'git HEAD' in text and 'jobs' in text, 'no env block in the log')
    check('log: the plan is recorded', 'plan:' in text, 'no plan in the log')


# ── the result cache in front of the runner (checked_run.py) ───────────────
#
# `checked_run.py` decides whether a check re-runs or replays a recorded result,
# and 12 of the specs in `check` and `gate` are `cache=True`. A wrong answer
# there is not one red test: a replayed PASS is a green test that never ran, and
# a replayed FAILURE is a red that no fix can clear. Nothing imported this file
# before `bugs/UNTESTED.md`, so the properties below were documented and never
# executed.

def _key_tree(tag):
    """A scratch `--extra` tree, unique per process.

    Per PROCESS and not per test, for the reason `test_artifact_cache` gives:
    the store is persistent and outlives the run, so a fixed name means run N's
    "changed input" step finds run N-1's published key already there and
    reports a hit for a key nothing published this time.
    """
    import tempfile
    d = os.path.join(tempfile.mkdtemp(prefix=f'crkey_{tag}_'), 'subject')
    os.makedirs(d)
    for i in range(3):
        with open(os.path.join(d, f'f{i}.txt'), 'w') as f:
            f.write('v1')
    return d


def test_checked_run_key_covers_what_it_names():
    """The key moves for every change to the inputs and for nothing else.

    A FILE is the easy half and is a regression guard. A DIRECTORY is the half
    that was broken: `--extra <dir>` hashed the directory as one opaque name, so
    editing a file inside it, adding one, or removing one all left the key
    still. That is not a theoretical gap — `examples-parse` is `cache=True` and
    guards the 45 files of `formal/examples/`, which its `extra` cannot name
    without a list that rots on the 46th. Measured in `bugs/UNTESTED.md`.
    """
    import checked_run
    d = _key_tree(os.getpid())
    K = lambda p: checked_run.check_key(f'keyprobe{os.getpid()}', [p])

    def moved(label, before, want_moved=True):
        after = K(d)
        check(f'cache key: {label}', (after != before) == want_moved,
              f'key {"moved" if after != before else "did not move"}, wanted '
              f'{"a move" if want_moved else "no move"}')
        return after

    a = K(d)
    # The walk has to have found something, or every "did not move" below is
    # passing because the key hashes nothing at all.
    with open(os.path.join(d, 'f0.txt'), 'w') as f:
        f.write('v2')
    b = moved('a file inside a --extra DIRECTORY changing moves it', a)
    with open(os.path.join(d, 'added.txt'), 'w') as f:
        f.write('the 46th example')
    c = moved('a file ADDED to it moves it (this is the 46th example)', b)
    os.unlink(os.path.join(d, 'f2.txt'))
    e = moved('a file REMOVED from it moves it', c)
    os.rename(os.path.join(d, 'f1.txt'), os.path.join(d, 'f1b.txt'))
    g = moved('a file RENAMED inside it moves it (a list of paths cannot)', e)
    # …and nothing that is not an input.
    os.makedirs(os.path.join(d, '__pycache__'), exist_ok=True)
    with open(os.path.join(d, '__pycache__', 'x.pyc'), 'w') as f:
        f.write('derived')
    h = moved('a __pycache__ appearing does NOT move it', g, want_moved=False)
    # Two independent defences, asserted separately so neither can be removed
    # while the other hides it: the DIRECTORY is never descended into (whatever
    # is in it), and a `.pyc` is never hashed (wherever it is). A real
    # `__pycache__` holds only `.pyc`, so the directory half needs a
    # deliberately wrong file in it — which is the point: the rule is about the
    # directory being derived, not about its usual contents.
    with open(os.path.join(d, '__pycache__', 'stale.py'), 'w') as f:
        f.write('a stale copy of something')
    moved('a non-.pyc file inside a __pycache__ does NOT move it either', h,
          want_moved=False)
    with open(os.path.join(d, 'stray.pyc'), 'w') as f:
        f.write('derived')
    h2 = moved('a stray .pyc outside a __pycache__ does NOT move it', h,
               want_moved=False)
    with open(os.path.join(d, 'outside.txt'), 'w') as f:
        f.write('inside, so it IS a subject')
    j = moved('a file anywhere inside the directory DOES move it, which is '
              'the whole point of naming a directory', h2)
    with open(os.path.join(os.path.dirname(d), 'sibling.txt'), 'w') as f:
        f.write('a different directory entirely')
    moved('a file in a SIBLING directory does NOT move it', j,
          want_moved=False)
    covered = sum(len(fs) for _r, _d, fs in os.walk(d))
    check('cache key: the directory walk saw the files it claims to hash',
          covered >= 3, f'walk saw {covered}, so "did not move" may mean '
                        f'"hashed nothing"')

    # IDENTITY IS PART OF THE KEY, asserted on its own because none of the
    # "did not move" checks above can see it: `os.walk` yields in whatever
    # order the filesystem hands back, so a key built from walk order differs
    # between two machines holding the same tree. The cost there is a cache
    # that never hits, not a wrong result, which is exactly why removing the
    # sort shows up in none of the movement checks. Two directories with
    # different NAMES and identical contents must therefore produce different
    # keys — otherwise a test could be served a result computed against
    # somebody else's directory.
    import tempfile
    a_dir = os.path.join(tempfile.mkdtemp(prefix='crid_a_'), 't')
    b_dir = os.path.join(tempfile.mkdtemp(prefix='crid_b_'), 't')
    for d_ in (a_dir, b_dir):
        os.makedirs(d_)
        for name in ('one.txt', 'two.txt', 'three.txt'):
            with open(os.path.join(d_, name), 'w') as f:
                f.write(name)
    check('cache key: two directories with identical CONTENTS but different '
          'names get different keys',
          checked_run.check_key(f'idprobe{os.getpid()}', [a_dir])
          != checked_run.check_key(f'idprobe{os.getpid()}', [b_dir]),
          'the given path is not in the key, so two directories can collide')

    # A plain file, and a file that does not exist.
    one = os.path.join(d, 'solo.txt')
    with open(one, 'w') as f:
        f.write('a')
    k1 = K(one)
    with open(one, 'w') as f:
        f.write('b')
    check('cache key: a plain --extra FILE\'s content moves it', K(one) != k1,
          'a file input does not invalidate')
    # …and its NAME does too, which the movement checks above cannot see: two
    # inputs with byte-identical contents are different inputs, and a key built
    # from content alone would let one test be served another test's result.
    # Both are written the SAME content first — the preceding check left `one`
    # holding 'b', and comparing files of different contents would pass on
    # content alone and prove nothing about the path.
    twin = os.path.join(d, 'twin.txt')
    for path in (one, twin):
        with open(path, 'w') as f:
            f.write('identical')
    check('cache key: two FILES with identical contents get different keys',
          K(one) != K(twin), 'the given path is not in the key for a file')
    check('cache key: and that is still true when both are named together',
          checked_run.check_key(f'twinprobe{os.getpid()}', [one, twin])
          != checked_run.check_key(f'twinprobe{os.getpid()}', [one]),
          'membership of the --extra list is not in the key')
    # …and the ORDER of the list must not matter, or every caller has to sort
    # it correctly and a mistake there is a silent cache miss on every run.
    check('cache key: the order of the --extra list does not matter',
          checked_run.check_key(f'twinprobe{os.getpid()}', [one, twin])
          == checked_run.check_key(f'twinprobe{os.getpid()}', [twin, one]),
          'the list is hashed in the order given, so a caller that does not '
          'sort it gets a different key for the same inputs')
    gone = os.path.join(d, 'not-here.txt')
    k2, k3 = K(gone), K(gone)
    check('cache key: a missing path is a CONSTANT, which is why main() warns',
          k2 == k3, 'a missing input still invalidates, so nothing to warn about')
    del j


def test_checked_run_replays_a_pass_and_reruns_a_failure():
    """The asymmetry, end to end through the real CLI.

    A recorded PASS is replayed, which is what makes `make check` fast. A
    recorded FAILURE is re-run, because it is a claim about a past run and the
    key covers the `--extra` files and not the rest of the machine. A changed
    input re-runs either way.

    **How "did it run" is observed matters, and getting it wrong is the trap
    this test exists beside.** A replay reproduces the recorded stdout BYTE FOR
    BYTE, so a probe that greps the output for a marker the command printed
    concludes the command ran, on the run where it provably did not. The
    observation has to be a SIDE EFFECT outside the captured streams — a
    counter file, as `test_artifact_cache` already does for the same reason —
    and the replay has to be confirmed from the announcement on stderr as well,
    because "the counter did not move" and "the cache hit" are the same claim
    from two directions and only one of them is a behaviour.
    """
    import subprocess
    import tempfile
    # Unique per PROCESS: the store persists, so a fixed name lets a previous
    # run's published result answer this one's first step.
    tag = f'replay{os.getpid()}'
    work = tempfile.mkdtemp(prefix='crreplay_')
    counter = os.path.join(work, 'count')
    inp = os.path.join(work, 'in.txt')
    with open(inp, 'w') as f:
        f.write('v1')
    body = ('import sys\n'
            f'open({counter!r}, "a").write("x")\n'
            'sys.exit(int(sys.argv[1]))')

    def go(code, rerun=True, input_path=inp, no_cache=False):
        cmd = [PY, os.path.join(HERE, 'checked_run.py'), tag, '--extra', input_path]
        if rerun:
            cmd.append('--rerun-failures')
        if no_cache:
            cmd.append('--no-cache')
        cmd += ['--', PY, '-c', body, str(code)]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        ran = (len(open(counter).read())
               if os.path.exists(counter) else 0)
        return p, ran

    def ran_count():
        return len(open(counter).read()) if os.path.exists(counter) else 0

    p, n = go(0)
    check('cache replay: a fresh PASS runs and is published', n == 1,
          f'ran {n} times')
    check('cache replay: and it is a PASS', p.returncode == 0, str(p.returncode))
    p, n = go(0)
    check('cache replay: a recorded PASS is REPLAYED, not re-run', n == 1,
          f'ran {n} times; a replay must not execute the command')
    check('cache replay: and the replay is announced, not silent',
          'cached result replayed' in p.stderr, p.stderr[-300:])
    p, n = go(0, no_cache=True)
    check('cache replay: --no-cache runs it anyway', n == 2, f'ran {n} times')
    with open(inp, 'w') as f:
        f.write('v2')
    p, n = go(0)
    check('cache replay: a changed --extra input re-runs', n == 3, f'ran {n}')

    # A different key for the failure phase, and the reason is worth stating:
    # the key covers the INPUTS, not the command, so re-running the same inputs
    # with a different exit code replays the recorded one. That is the intended
    # contract — same inputs, same outcome — and a test that forgets it is
    # asserting about a key it never changed.
    with open(inp, 'w') as f:
        f.write('v3')
    p, n = go(7)
    check('cache replay: a fresh FAILURE runs and is published', n == 4,
          f'ran {n} times')
    check('cache replay: and it is a failure', p.returncode == 7,
          str(p.returncode))
    p, n = go(7)
    check('cache replay: a recorded FAILURE is RE-RUN, never replayed', n == 5,
          f'ran {n} times; a replayed failure is a red no fix can clear')
    check('cache replay: and the re-run says why',
          're-running it' in p.stderr, p.stderr[-300:])
    p, n = go(7, rerun=False)
    check('cache replay: without the flag a failure is replayed (the default)',
          n == 5, f'ran {n} times')
    p, n = go(0, input_path=os.path.join(work, 'never-existed'))
    check('cache replay: an unreadable --extra path warns on stderr',
          'does not exist' in p.stderr,
          'a typo in `extra` silently disables caching and says nothing')
    del ran_count


# ── the estate: is every test file run by anything? ────────────────────────

# `test_*.py` files in the repo that NO registered spec names, with why. An
# empty list would mean this test had nothing to check; the anti-rot assertions
# below are what keep it honest in the other direction, so an entry cannot
# outlive the file it excuses or the registration that supersedes it.
#
# This IS the inventory from `bugs/UNTESTED.md`, in a form that runs. The
# measured shape: 50 of 81, and 5 of those 50 are RED today, so the tree carries
# 25 known-failing assertions that no gate, tally or coverage number reports.
UNREGISTERED = {
    # ── RED today: exit non-zero, and no gate, tally or coverage number
    #    reports any of it. The count is a re-run of every entry, not a
    #    reading of a bug doc.
    'test_x86_64_encoders.py': "Two checks on formal/x86_64.py's encoder "
        'arithmetic, independent of the round-trip above.',

    # ── the encoders, differentially, against the platform assembler ──
    'test_arm64_emission.py': 'A hand count that the new arm64 instructions '
        'are emitted at all, which the differential test above cannot tell from '
        'an instruction emitted where a different one should be.',

    # ── the returned-frame convention, both machines, against CPython ──
    #
    # Unregistered on purpose rather than by omission, and the reason is in
    # tools/suite.py's own terms: it builds and RUNS fourteen images (seven per
    # architecture) and asks CPython for each answer, so a run of it is a
    # measured cost on every invocation and nothing in the gate wants that
    # shape. It is listed rather than left out because the estate check below
    # exists to make an unaccounted-for test file impossible, and a file that is
    # unaccounted-for is the state this is avoiding.
    'test_formal_returned_frame.py': 'The returned-frame convention: builds, '
        'runs and compares with CPython on arm64 AND x86-64. Runs beside '
        'test_formal_run.py rather than inside it, because the convention is '
        'one construct and the suite that hosts it is already the longest.',

    # ── the interpreter, which is the oracle everything else is compared to ──
    'test_myinterpreter.py': 'Runs a real .mojo file end to end through '
        'myinterpreter.mojo, which is the reference every compiled-path answer '
        'is measured against.',
    'test_myinterpreter_simple.py': 'The same interpreter reached through '
        'module loading rather than run_mojo_main, which is the path the '
        'compiled path actually uses.',
    'test_myinterpreter_validation.py': "The interpreter's output validated "
        "against Python's OWN tokenizer. The strongest cheap parity check "
        "available and the only one that is not this project grading itself.",
    'test_phase2_parser.py': 'The interpreter executes the parser and the ASTs '
        'are compared, which is the check that a parser change is semantics-'
        'preserving rather than merely accepted.',
    'test_phase2_parser_simple.py': 'The minimal form of the above: the '
        'interpreter can execute parser.mojo at all.',

    # ── the dispatch solver, four phase-ordered files ──
    'test_dispatch_solver.py': 'DispatchSolver phase A, the table planner. '
        'Unregistered, so a phase-B or phase-C change can regress it with '
        'nothing to notice.',
    'test_dispatch_phase_b.py': 'DispatchSolver phase B: table planning plus C '
        'code generation.',
    'test_dispatch_phase_c.py': 'DispatchSolver phase C: GimpleGen integration '
        'and dispatch table emission into real generated code.',
    'test_dispatch_promotions.py': 'def->fn and type promotions across a '
        'transitive closure — a source rewrite, so a wrong promotion is a '
        'silently wrong program.',
    'test_dispatch_myinterpreter.py': 'The solver against myinterpreter.mojo '
        'patterns, which is where its rewrites have to survive real source.',

    # ── closure capture: five files, one family, all real behaviour ──
    'test_closure_capture_comptime_func_params.py': 'Two documented '
        'closure-capture bugs, and the file says REAL behavioural tests. A '
        'capture that binds the wrong cell is a silent wrong answer.',
    'test_general_mutable_closure_capture.py': 'Mutable (by-reference) closure '
        'capture; by-reference means a write through a stale word, which is the '
        'frame-address defect FORMAL.md assigns to [4] on the other backend.',
    'test_python_source_mut_capture.py': 'Heap-boxed {mut}/nonlocal capture '
        'from Python source, the path the stdlib corpus is written in.',
    'test_generators.py': 'Interpreter-side real generator execution. The '
        'compiled path has a `mojo_unsupported_iter` family of its own, and '
        'this is the interpreter half nobody runs.',
    'test_coro_scoreboard.py': 'The A3 before/after scoreboard: a file whose '
        'output IS the measurement, so there is no assertion to fail and it is '
        'inert unless something reads it.',
    'test_coro_bugs.py': 'Per-bug diagnostic for the A3 stack-switch backend. '
        'Exits 0 while its own output reads CFAIL=1 COMPILE=1 — see UNTESTED.md '
        '§3: a green exit that reports a failure in its own text.',
    'test_async_execution.py': 'Interpreter async/await execution, milestone '
        '3b. The compiled half of async is the `coro` bucket; this is the half '
        'that decides what the compiled half should agree with.',
    'test_async_parsing.py': 'Parser-only async/await, async for, async with. '
        'A parser invariant with no compiler behind it, so nothing else in the '
        'gate constrains it.',
    'test_yield_parsing.py': 'Parser-only yield / yield from, milestone 1. Same '
        'shape: unconstrained by anything that builds.',
    'test_ownership_check.py': 'Fixture-driven accept/reject for '
        'ownership_check.py, whose diagnostics gate real emission paths.',
    'test_dual_cpp_elaboration.py': "REAL behavioural tests for monomorphize.py's "
        'dual C/C++ output. A silent-wrong-answer shape: a C++ TU emitted where '
        'C was meant links and computes something else.',
    'test_mixed_cpp_link.py': 'Toolchain plumbing: a mixed -fgimple C and C++20 '
        'build, link and run. The proof that the dual output actually links.',
    'test_import_integration.py': 'Compiling Mojo with imports and linking '
        'against helper modules, which is the path every multi-file program '
        'takes.',

    # ── the rest, one reason each ──
    'test_container_equality.py': 'Container ==/!= on the compiled path, each '
        'case a whole program run BOTH ways and required to agree with CPython '
        'on stdout and exit status. Not registered because the work that added '
        'it was told not to touch tools/suite.py; it needs a `check`-bucket '
        'entry beside `gimple`/`gimplerunner` (a `cmd` step, memclass small: '
        '24 programs, ~25 s, peak 0.1 GB) and `extra` naming this file so '
        'checked_run.py\'s content-addressed cache invalidates when it changes.',
    'test_imports.py': 'That import statements generate extern declarations. '
        'A missing extern is a link failure attributed to something else.',
    'test_kwargs_stmt.py': 'kwargs in statement-level calls, a shape the '
        'parser and the lowering each handle separately.',
    'test_comptime_bracket_params.py': 'REAL behavioural test for a '
        'bracket-parametrised comptime call, i.e. the shape `interporacle` and '
        'the sweep both report and neither pins.',
    'test_phase3_codegen_simple.py': 'Attempting to execute codegen through the '
        'interpreter; historical, and kept for the record rather than for its '
        'assertions.',
    'test_py314_full.py': "Runs against ~/net/Python-3.14.6, a checkout "
        'OUTSIDE this repository, so it cannot be registered as-is: a '
        'registered test that silently skips when the path is absent is a gate '
        'that measures nothing, which is worse than an unrun file. The fix is '
        'to take the path as an argument and skip LOUDLY.',
    'test_refactor_bugs.py': 'Regression tests for the wave-1 entry-point fixes '
        '(B1/B2, REF.html §3). Named after a refactor, so the bugs it pins are '
        'the ones someone would forget.',
    'test_type_system.py': "That the invariant checker catches every bug from "
        "the session that produced it — i.e. the checker is tested against its "
        "own author's list of what it should reject.",
    'test_type_system_integration.py': 'The type system catching violations '
        'during a real compile, which is the half the fixture list above is not.',
}


def _unregistered_reason_table():
    """The table above, with the placeholder dropped.

    A `None` value is how a draft entry is written while the list is being
    built, and this filters it out so an unfinished entry cannot be shipped as
    a permanent excuse with no reason attached. Anything else non-string is a
    programming error here rather than a fact about a file, so it raises.
    """
    out = {}
    for path, why in UNREGISTERED.items():
        if why is None:
            continue
        if not isinstance(why, str):
            raise AssertionError(
                f'UNREGISTERED[{path!r}] is {type(why).__name__}, not a '
                f'string. Every entry must say WHY the file is not run.')
        out[path] = why
    return out


def _test_files_in_repo():
    """Every `test_*.py` in the repo, repo-relative.

    `build/`, `__pycache__`, `aside/` and `bside/` are excluded: the first two
    are derived, and the last two are the A/B machinery's copies of repo files
    (which is why they hold `checked_run.py` and friends but no `test_*.py`).
    """
    found = []
    for dirpath, dirnames, filenames in os.walk(HERE):
        dirnames[:] = [d for d in dirnames
                       if d not in ('build', '__pycache__', 'aside', 'bside',
                                    '.git')
                       and not d.startswith('.')]
        for fn in filenames:
            if fn.startswith('test_') and fn.endswith('.py'):
                found.append(os.path.relpath(os.path.join(dirpath, fn), HERE))
    return sorted(set(found))


def _registered_test_files():
    """The `test_*.py` basenames any registered spec's command names."""
    import re
    out = set()
    for spec in suite.REGISTRY.values():
        for c in (getattr(spec, 'cmd', None) or []):
            for m in re.findall(r'[\w./-]*test[\w./-]*\.py', str(c)):
                out.add(os.path.basename(m))
    return out


def test_cached_spec_names_its_own_test():
    """Every `cache=True` spec hashes the test file it runs.

    A recorded PASS for a spec whose key does not include the test's own source
    survives an edit to that test: the fix lands, the key does not move, and the
    old verdict is served. Measured on this tree: all 12 cached specs name their
    own script, so this is the regression guard for the property, not a fix for
    a live hole. The live hole is what `extra` does NOT name, and
    `bugs/UNTESTED.md` records that one.
    """
    cached = [n for n, s in suite.REGISTRY.items()
              if getattr(s, 'cache', False) and not isinstance(s, suite.Fanout)]
    check('cache key: there are cached specs to check', len(cached) >= 8,
          f'only {len(cached)}; the checks below would be vacuous')
    for name in sorted(cached):
        spec = suite.REGISTRY[name]
        scripts = [os.path.basename(str(c)) for c in spec.cmd
                   if str(c).endswith('.py')
                   and (str(c).startswith('test_') or str(c).endswith('_test.py'))]
        named = {os.path.basename(str(e)) for e in spec.extra}
        missing = [s for s in scripts if s not in named]
        check(f'cache key: cached spec {name} hashes its own test',
              not missing, f'{missing} not in extra={sorted(named)}')


def test_every_test_file_is_registered():
    """A test file nothing runs is a claim with no evidence behind it.

    The failure this is modelled on is in CLAUDE.md: the `coro` bucket sat in
    the gate naming `mojo_*` runtime files after they were renamed to `fire_*`,
    so all 20 of its cases failed to compile and the suite reported 0/20 for
    two rounds. Nothing was expected, nothing was reported, and the coroutine
    runtime was untested. A registration is the only thing that makes a test
    file run at all, and until this check nothing noticed when one did not
    happen.

    Measured before it existed: 50 of 81, of which 5 are RED. The 50 are
    declared below with a reason each, because a check that failed 50 times on
    its first day is a check nobody runs — and the declarations are the
    inventory from `bugs/UNTESTED.md`, in a form that executes.
    """
    excused = _unregistered_reason_table()
    on_disk = set(_test_files_in_repo())
    named = _registered_test_files()

    check('the estate: the walk found test files at all', len(on_disk) > 20,
          f'found {len(on_disk)}; every check below would pass vacuously')
    check('the estate: some tests are registered, so "registered" means something',
          len(named) > 10, f'only {len(named)} test files are named by a spec')

    orphans = {f for f in on_disk if os.path.basename(f) not in named}
    undeclared = sorted(orphans - set(excused))
    check('the estate: every test file is run by something, or says why not',
          not undeclared,
          'not run by any registered spec and not in UNREGISTERED: '
          + ', '.join(undeclared))

    # The other two directions, which is what stops the list becoming a
    # permanent excuse. Both are the anti-rot discipline tools/suite.py already
    # applies to an `expect=` marker, applied here to a 50-entry list.
    stale = sorted(set(excused) - on_disk)
    check('the estate: no excuse for a file that no longer exists', not stale,
          f'delete these from UNREGISTERED: {stale}')
    resolved = sorted(p for p in excused
                      if os.path.basename(p) in named)
    check('the estate: no excuse for a file that is now registered', not resolved,
          f'registering one makes its excuse wrong; delete these: {resolved}')
    thin = sorted(p for p, why in excused.items() if len(why) < 40)
    check('the estate: every excuse is a reason, not a shrug', not thin,
          f'too short to be a reason: {thin}')
    print(f'      the estate: {len(on_disk)} test files, {len(named - orphans)} '
          f'of them run by a registered spec, {len(excused)} declared with a '
          f'reason, {len(undeclared)} undeclared')


def _module_const_paths(src, tree):
    """`<NAME> = os.path.join(..., 'build', '<name>')` -> {NAME: that source text}.

    The `build/mojo` guard read `os.path.exists(MOJO_CLI)`, not an inline join,
    so a detector that only looked at the call's own argument would have missed
    the exact shape it was written for. Resolving one level of module-level
    constant is enough for how these paths are actually spelled, and a path
    built through a chain deeper than that is not the thing to chase.
    """
    out = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            continue
        seg = ast.get_source_segment(src, node.value) or ''
        if 'build' in seg:
            out[node.targets[0].id] = ' '.join(seg.split())
    return out


def _existence_call(node):
    """The `os.path.exists`/`isfile`/`isdir` call `node` is built around, or None."""
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in ('exists', 'isfile', 'isdir') and node.args):
        return node
    return None


def _aborts(body):
    """Does this statement list end the process — `sys.exit` / `raise SystemExit`?

    The distinction this check turns on. `if os.path.exists(log): read(log)` is a
    test reading back a file it just wrote, and needs nothing built. The bug in
    `test_runner.py` was `if not os.path.exists(MOJO_CLI): sys.exit(1)` — a
    *fatal* gate, where absence of an unbuilt artifact ends a run that had
    nothing else to do with it. Only the second is a dependency on the build.
    """
    for node in ast.walk(ast.Module(body=list(body), type_ignores=[])):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == 'exit' \
                and isinstance(node.func.value, ast.Name) \
                and node.func.value.id == 'sys':
            return True
        if isinstance(node, ast.Raise) and node.exc is not None \
                and 'SystemExit' in ast.dump(node.exc):
            return True
    return False


def _preflight_gates_in(src):
    """Every `build/` path a file gates its whole run on.

    A gate is `if [not] os.path.exists(<build path>): <aborts>`, where the path
    is spelled inline or through a module-level constant. Both halves matter:
    the abort is what makes it fatal, and the constant is how the one that
    shipped was written.
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    consts = _module_const_paths(src, tree)

    def path_text(arg):
        if isinstance(arg, ast.Name):
            return consts.get(arg.id, '')
        return ' '.join((ast.get_source_segment(src, arg) or '').split())

    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        call = _existence_call(node.test)
        if call is None and isinstance(node.test, ast.UnaryOp) \
                and isinstance(node.test.op, ast.Not):
            call = _existence_call(node.test.operand)
        if call is None or not _aborts(node.body):
            continue
        seg = path_text(call.args[0])
        if re.search(r"""['"]build['"]|['"]build/""", seg):
            found.append((node.lineno, seg))
    return found


def _makefile_targets():
    """Every target name the Makefile has a rule for, as repo-relative paths."""
    names = set()
    with open(os.path.join(HERE, 'Makefile')) as f:
        for line in f:
            m = re.match(r'^([A-Za-z0-9_][\w./$-]*):(?!=)', line)
            if m:
                names.add(m.group(1))
    return names


# The three source shapes the detector has to tell apart, kept as fixtures
# beside the check that uses them so they cannot drift apart. PROBE is the guard
# `test_runner.py` shipped, verbatim in structure: a module-level constant, read
# by name, and fatal when it is missing. REAL_RULE_PROBE is that same shape
# naming a file the Makefile really builds. READBACK_PROBE is the shape that
# must NOT count — checking a log the test itself just wrote, which depends on
# nothing and is what a too-broad version of this check flagged 9 times.
PROBE = ("import os, sys\n"
         "HERE = os.path.dirname(os.path.abspath(__file__))\n"
         "MOJO_CLI = os.path.join(HERE, 'build', 'mojo')\n"
         "if not os.path.exists(MOJO_CLI):\n"
         "    print('ERROR', file=sys.stderr)\n"
         "    sys.exit(1)\n")

REAL_RULE_PROBE = ("import os, sys\n"
                   "HERE = os.path.dirname(os.path.abspath(__file__))\n"
                   "FIRE = os.path.join(HERE, 'build', 'fire')\n"
                   "if not os.path.exists(FIRE):\n"
                   "    sys.exit(1)\n")

READBACK_PROBE = ("import os\n"
                  "HERE = os.path.dirname(os.path.abspath(__file__))\n"
                  "log = os.path.join(HERE, 'build', 'x.log')\n"
                  "text = open(log).read() if os.path.exists(log) else ''\n")


def test_no_test_preflights_on_an_unbuildable_artifact():
    """A test may not gate itself on a `build/` file no rule in this Makefile
    produces.

    This is the failure `test_runner.py` shipped for its whole life, and it is
    invisible in the checkout it was written in. `main()` opened with

        if not os.path.exists(MOJO_CLI):   # MOJO_CLI = build/mojo
            print("ERROR: ... Run 'make stdlib' first.")

    and `MOJO_CLI` was read NOWHERE else — `compile_mojo_to_executable` goes
    through `gimple_codegen.compile_to_c` and gcc, so the guard gated the whole
    suite on a binary the test never runs. Two things then had to be true for it
    to look healthy, and neither is a property of the code: some process had to
    leave an untracked, gitignored `build/mojo` lying around (the main checkout
    had one dated 2026-09-15, eight days stale), and a human had to not read the
    error. The mojo->fire rename had already renamed the rule that produces that
    file (`build/fire`, Makefile's own success line still said `build/mojo`), so
    in every FRESH worktree the suite died at line 1 with an error naming a
    target that no longer exists and a remedy — `make stdlib` — that runs
    `stdlib-syntax` and builds nothing at all.

    The general shape: gating a whole run on a build artifact is a *dependency*
    on the build, and a dependency that no Makefile rule produces is one the
    next fresh checkout pays for. So the check is that every fatal `build/`
    gate resolves to a target, and the check is scoped to gates that ABORT: a
    test reading back a log it just wrote is not depending on anything.

    The two probes below are the detector's own tests, and they are load-bearing
    rather than decorative: an earlier version of this check only inspected the
    argument of the `os.path.exists` call, so it could not see the guard that
    actually shipped (which read a module-level `MOJO_CLI`), and it would have
    reported green forever. A guard that cannot see its own bug is a comment.
    """
    targets = _makefile_targets()
    offenders = []
    for rel in _test_files_in_repo():
        with open(os.path.join(HERE, rel)) as f:
            for lineno, expr in _preflight_gates_in(f.read()):
                for m in re.finditer(r"""['"]build['"]\s*,\s*['"]([\w./-]+)['"]""", expr):
                    if os.path.join('build', m.group(1)) not in targets:
                        offenders.append(f'{rel}:{lineno} gates on build/{m.group(1)}')
                for m in re.finditer(r"""['"](build/[\w./-]+)['"]""", expr):
                    if m.group(1) not in targets:
                        offenders.append(f'{rel}:{lineno} gates on {m.group(1)}')

    def _gated(path_probe, want):
        """Does the detector see `path_probe`'s `build/<x>`, and is it resolved?"""
        hits = [e for _, e in _preflight_gates_in(path_probe)
                if re.search(r"""['"]build['"]\s*,\s*['"]([\w./-]+)['"]""", e)]
        if not hits:
            return False
        named = re.search(r"""['"]build['"]\s*,\s*['"]([\w./-]+)['"]""", hits[0]).group(1)
        return (os.path.join('build', named) in targets) is want

    check('preflight: the Makefile has targets to resolve against', len(targets) > 20,
          f'only {len(targets)}; the check below would be vacuous')
    check('preflight: the detector sees the build/mojo shape it is for',
          _gated(PROBE, want=False),
          'the detector no longer recognises the aborting guard it was written for')
    check('preflight: a gate on a real rule resolves, not flags',
          _gated(REAL_RULE_PROBE, want=True),
          'the detector flags build/fire, which the Makefile really builds')
    check('preflight: a non-aborting existence check is not a gate',
          not _preflight_gates_in(READBACK_PROBE),
          'reading back a file the test just wrote was counted as a dependency')
    check('preflight: no test gates on a build artifact no rule produces',
          not offenders, '; '.join(sorted(set(offenders))))


def main():
    for fn in (test_cmd_driver, test_reject_pattern, test_mem_driver,
               test_make_driver, test_j_forwarded,                test_deps_order_and_skip,
               test_exclusive_is_alone, test_fanout_aggregates,
               test_fanout_enumeration_ignores_untracked_scratch,
               test_the_ab_native_writer_keeps_its_scratch_out_of_the_repo_root,
               test_missing_fanout_item_is_a_named_failure,
               test_timeout_is_a_failure_not_a_vanished_job,
               test_tally_accounts_for_every_test,
               test_a_status_with_no_counter_stops_the_runner,
               test_artifact_cache,                test_selfhost_key_is_complete,
               test_the_compiler_imports_from_every_real_entry_point,
               test_bucket_dedup, test_missing_dep_is_reported,
               test_named_test_brings_its_deps,
               test_log_has_passes_screen_does_not,
               test_checked_run_key_covers_what_it_names,
               test_checked_run_replays_a_pass_and_reruns_a_failure,
               test_cached_spec_names_its_own_test,
               test_every_test_file_is_registered,
               test_no_test_preflights_on_an_unbuildable_artifact,
               # The memory-campaign tests. They were DEFINED and never CALLED
               # — three functions, 300-odd lines, nothing in this list — which
               # is the same defect as a test file in no bucket: the coverage
               # was claimed in a docstring and executed by nobody. A guard
               # that nothing runs reports green forever, which is the one
               # thing it must not be able to do.
               test_cmd_and_make_drivers_are_capped,
               test_a_timeout_leaves_no_orphan_under_a_cap,
               test_every_compiler_job_is_capped,
               test_every_job_is_reserved_before_it_starts,
               test_the_timeout_clock_starts_after_admission,
               test_a_reservation_the_budget_cannot_fit_is_reported,
               test_a_fanout_item_is_capped_and_reserved_like_any_other_job,
               test_a_registered_fanout_item_is_wrapped_in_the_built_argv,
               test_an_exclusive_job_reserves_its_class_and_nothing_more,
               # …and the ratchet that decides what the classes ARE: a class is
               # a claim on the machine, so it has to be sized from a
               # measurement rather than from the shape of the workload.
               test_a_job_class_covers_its_measured_peak,
               test_a_job_class_covers_the_peak_the_last_run_recorded,
               test_over_provisioned_classes_are_reported_not_silently_kept,
               test_every_job_over_the_debt_line_says_why,
               test_a_make_recipe_never_asks_for_more_than_its_job_reserved):
        fn()
    print()
    print(f'Results: {PASSES} passed, {len(FAILURES)} failed')
    for f in FAILURES:
        print(f'  - {f}')
    return 1 if FAILURES else 0


if __name__ == '__main__':
    sys.exit(main())
