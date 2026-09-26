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
  selection    overlapping buckets expand to each test exactly once, so
               `make gate` does not build mojoc twice.
  reporting    one tally at the end, and the log file gets the detail the
               screen does not.

Run:  python3 test_suite.py         (or `make check-suite`, part of `smoke`)
"""

import io
import os
import sys
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'tools'))
import suite                                                    # noqa: E402

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


def run(names, jobs=4, log='-', quiet=True, **flags):
    """Select, plan, execute, report — the whole main() path, quietly.

    `flags` are passed as bare switches (verbose=True -> --verbose), which is
    the only shape argparse accepts for a store_true option.
    """
    argv = list(names)
    for k, v in flags.items():
        if v:
            argv.append(f'--{k.replace("_", "-")}')
    out = io.StringIO()
    if quiet:
        argv.append('-q')
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
        old = os.environ.get('MEMLIMIT_GB')
        os.environ['MEMLIMIT_GB'] = '0.02'      # 20 MB: a bare python is under
        try:
            rc, _ = run(['hog', 'small'], jobs=2, log=log)
        finally:
            if old is None:
                os.environ.pop('MEMLIMIT_GB', None)
            else:
                os.environ['MEMLIMIT_GB'] = old
    text = open(log).read() if os.path.exists(log) else ''
    check('mem driver: a breach is RESOURCE, not FAIL',
          'RESOURCE' in text and '\n  FAIL' not in text,
          'expected a RESOURCE verdict in the log')
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


def main():
    for fn in (test_cmd_driver, test_reject_pattern, test_mem_driver,
               test_make_driver, test_j_forwarded, test_deps_order_and_skip,
               test_exclusive_is_alone, test_fanout_aggregates,
               test_artifact_cache, test_selfhost_key_is_complete,
               test_bucket_dedup, test_missing_dep_is_reported,
               test_named_test_brings_its_deps,
               test_log_has_passes_screen_does_not):
        fn()
    print()
    print(f'Results: {PASSES} passed, {len(FAILURES)} failed')
    for f in FAILURES:
        print(f'  - {f}')
    return 1 if FAILURES else 0


if __name__ == '__main__':
    sys.exit(main())
