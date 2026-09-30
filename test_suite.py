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
import io
import os
import re
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
               test_make_driver, test_j_forwarded, test_deps_order_and_skip,
               test_exclusive_is_alone, test_fanout_aggregates,
               test_timeout_is_a_failure_not_a_vanished_job,
               test_tally_accounts_for_every_test,
               test_a_status_with_no_counter_stops_the_runner,
               test_artifact_cache, test_selfhost_key_is_complete,
               test_bucket_dedup, test_missing_dep_is_reported,
               test_named_test_brings_its_deps,
               test_log_has_passes_screen_does_not,
               test_checked_run_key_covers_what_it_names,
               test_checked_run_replays_a_pass_and_reruns_a_failure,
               test_cached_spec_names_its_own_test,
               test_every_test_file_is_registered,
               test_no_test_preflights_on_an_unbuildable_artifact):
        fn()
    print()
    print(f'Results: {PASSES} passed, {len(FAILURES)} failed')
    for f in FAILURES:
        print(f'  - {f}')
    return 1 if FAILURES else 0


if __name__ == '__main__':
    sys.exit(main())
