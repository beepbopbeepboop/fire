#!/usr/bin/env python3
"""tools/memslot.py: memory is reserved before a job starts, out of one machine-wide budget.

Scaled down (budget 10 "GB", jobs that just sleep) so it runs in seconds, but the arithmetic is the
one the real numbers use: a job that takes more than half the budget runs alone; jobs that take a
third run three at a time; the sum of live reservations never exceeds the budget.
"""
import json, os, signal, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
# The in-process cases below call memslot's Python API directly, in THIS process: backfill must be off here
# too, or a small slot sneaks in on the machine's real free memory and the strict arithmetic is bypassed.
os.environ["MEMSLOT_SNEAK_MAX_GB"] = "0"
MEMSLOT = os.path.join(HERE, "tools", "memslot.py")
passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print("PASS  " + name)
    else:
        failed += 1
        print("FAIL  " + name + ("  " + detail if detail else ""))


def env(d):
    # MEMSLOT_HELD="" is not optional: it is what makes this file hermetic when
    # it is itself run as a suite job. The suite hands every job it admits the
    # reservation it holds (MEMSLOT_HELD), so without the clear every wrapper
    # started below would be "covered" by this test's own reservation, queue
    # behind itself, and the arithmetic these cases check would never happen.
    # MEMSLOT_SNEAK_MAX_GB=0 turns backfill OFF: these cases check strict budget arithmetic, which a small
    # job sneaking in on measured free memory would (correctly) bypass. The backfill cases below turn it on.
    return dict(os.environ, MEMSLOT_DIR=d, MEMSLOT_BUDGET_GB="10", MEMSLOT_HELD="", MEMSLOT_SNEAK_MAX_GB="0")


def sneak_env(d, avail, **kw):
    e = env(d)
    e.update(MEMSLOT_SNEAK_MAX_GB="8", MEMSLOT_SNEAK_CAP_GB="32", MEMSLOT_SNEAK_MARGIN_GB="16", MEMSLOT_AVAIL_GB=str(avail))
    e.update({k: str(v) for k, v in kw.items()})
    return e


def start_env(e, gb, secs, label):
    return subprocess.Popen([sys.executable, MEMSLOT, "--gb", str(gb), "--label", label, "--", "sleep", str(secs)],
                            env=e, stderr=subprocess.DEVNULL)


def start(d, gb, secs, label):
    return subprocess.Popen([sys.executable, MEMSLOT, "--gb", str(gb), "--label", label, "--", "sleep", str(secs)],
                            env=env(d), stderr=subprocess.DEVNULL)


def ledger(d):
    return json.load(open(os.path.join(d, "ledger.json")))


def holders(d):
    try:
        return [h["label"] for h in ledger(d)["holders"]]
    except OSError:
        return []


def wait_for(cond, secs=15):
    t = time.time()
    while time.time() - t < secs:
        if cond():
            return True
        time.sleep(0.1)
    return False


def main():
    # three 3-GB jobs fit (9 <= 10); a fourth waits until one leaves
    with tempfile.TemporaryDirectory() as d:
        ps = [start(d, 3, 4, "j%d" % i) for i in range(4)]
        check("three 3 GB jobs run together", wait_for(lambda: len(holders(d)) == 3))
        time.sleep(1.0)
        check("the fourth 3 GB job waits (9 + 3 > 10)", len(holders(d)) == 3, str(holders(d)))
        peak = 0
        while any(p.poll() is None for p in ps):
            try: peak = max(peak, sum(h["gb"] for h in ledger(d)["holders"]))
            except OSError: pass
            time.sleep(0.1)
        check("reserved memory never exceeded the budget", peak <= 10 + 1e-9, "peak %.1f" % peak)
        check("all four eventually ran and exited 0", all(p.returncode == 0 for p in ps))

    # a job over half the budget runs alone
    with tempfile.TemporaryDirectory() as d:
        big = start(d, 6, 3, "big")
        wait_for(lambda: holders(d) == ["big"])
        small = start(d, 5, 1, "small")
        time.sleep(1.0)
        check("a 6 GB job excludes a 5 GB one (11 > 10)", holders(d) == ["big"], str(holders(d)))
        big.wait(); small.wait()
        check("the waiting job runs after the big one leaves", small.returncode == 0)

    # strict FIFO: a big request at the head is not starved by small ones behind it
    with tempfile.TemporaryDirectory() as d:
        a = start(d, 4, 3, "a"); wait_for(lambda: holders(d) == ["a"])
        b = start(d, 8, 1, "b_big"); time.sleep(0.6)     # cannot fit next to a: waits at the head
        c = start(d, 2, 1, "c_small"); time.sleep(0.6)   # WOULD fit next to a, but is behind b_big
        check("a small request does not jump a waiting big one", holders(d) == ["a"], str(holders(d)))
        for p in (a, b, c): p.wait()
        check("all three completed", all(p.returncode == 0 for p in (a, b, c)))

    # a request larger than the whole budget is refused, not queued forever
    with tempfile.TemporaryDirectory() as d:
        p = start(d, 11, 1, "toobig")
        check("a request over the whole budget is refused (exit 126)", p.wait(timeout=10) == 126)

    # crash safety: memslot SIGKILLed, its job keeps running -> reservation persists; job exits -> freed
    with tempfile.TemporaryDirectory() as d:
        p = start(d, 7, 3, "orphan")
        wait_for(lambda: holders(d) == ["orphan"] and ledger(d)["holders"][0].get("job"))
        p.kill(); p.wait()
        q = start(d, 5, 1, "blocked")
        time.sleep(1.0)
        check("a killed memslot does not free the reservation while its job still runs", "orphan" in holders(d) and q.poll() is None,
              str(holders(d)))
        check("...and the reservation is freed when the job ends", wait_for(lambda: q.poll() is not None, 15) and q.returncode == 0)

    # the ceiling is the reservation: a job that exceeds it is killed (memcap exit 125)
    with tempfile.TemporaryDirectory() as d:
        r = subprocess.run([sys.executable, MEMSLOT, "--gb", "0.05", "--label", "hog", "--", sys.executable, "-c",
                            "b=bytearray(400*1024*1024); import time; time.sleep(5)"], env=env(d),
                           capture_output=True, text=True, timeout=60)
        check("a job over its own reservation is killed (exit 125)", r.returncode == 125, "rc=%s" % r.returncode)

    # ── the in-process reservation (memslot.Slot) ────────────────────────────
    # The one tools/suite.py and tools/ab_run_one.py use, because they start the
    # job themselves and a timeout must not run while a job waits for memory. It
    # is the same ledger, so it has to obey the same arithmetic — including from
    # inside ONE process, where every holder shares a pid and the only way to
    # tell them apart is the owner.
    sys.path.insert(0, os.path.join(HERE, 'tools'))
    import memslot                                                  # noqa: E402
    old_dir = os.environ.get('MEMSLOT_DIR')
    old_budget = os.environ.get('MEMSLOT_BUDGET_GB')
    old_held = os.environ.get('MEMSLOT_HELD')
    os.environ['MEMSLOT_DIR'] = tempfile.mkdtemp()
    os.environ['MEMSLOT_BUDGET_GB'] = '10'          # same budget the CLI cases used
    os.environ['MEMSLOT_HELD'] = ''                 # see env() above
    try:
        # two slots in this one process: the second must wait for the first
        a = memslot.Slot(7, 'slotA').acquire()
        waited = []

        def take_b():
            s = memslot.Slot(5, 'slotB').acquire()
            waited.append(s)
            time.sleep(0.2)
            s.release()

        t = threading.Thread(target=take_b, daemon=True)
        t.start()
        time.sleep(1.0)
        check('in-process: two slots in one process queue like two processes',
              len(waited) == 0 and memslot.reserved_gb() == 7,
              'reserved %.1f GB, second slot taken=%s' % (memslot.reserved_gb(), bool(waited)))
        a.release()
        t.join(10)
        check('in-process: the waiting slot is admitted when the first is released',
              len(waited) == 1 and waited[0].waited >= 0.5,
              'the second slot waited %.2fs' % (waited[0].waited if waited else -1))
        check('in-process: everything is given back at the end',
              memslot.reserved_gb() == 0, '%.1f GB still reserved' % memslot.reserved_gb())

        # release frees exactly ONE holder when a process holds several
        x = memslot.Slot(3, 'x').acquire()
        y = memslot.Slot(3, 'y').acquire()
        x.release()
        check('in-process: releasing one slot does not free the other',
              memslot.reserved_gb() == 3, '%.1f GB left' % memslot.reserved_gb())
        y.release()

        # note_job is what makes the reservation outlive a killed scheduler
        z = memslot.Slot(2, 'z').acquire()
        z.note_job(os.getpid())
        held = json.load(open(os.path.join(os.environ['MEMSLOT_DIR'], 'ledger.json')))['holders']
        check('in-process: the job pid is recorded on the holder entry',
              any(h.get('job') for h in held), str(held))
        z.release()
    finally:
        for k, v in (('MEMSLOT_DIR', old_dir), ('MEMSLOT_BUDGET_GB', old_budget),
                     ('MEMSLOT_HELD', old_held)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    # ── a reservation covers the tree it admitted ─────────────────────────────
    # Without this, `make mojoc` never finishes: tools/suite.py reserves the
    # job's class (stage, 96 GB, the whole budget) and the recipe it spawns is
    # itself `memslot.py --gb 96 -- ...` for the same 96 GB of the same
    # budget. Two claims on one tree do not fit, so the second queues for a
    # turn its own parent is holding. Scaled to 6 of 6, the case below took
    # longer than any timeout before the fix and 0.6s after it.
    with tempfile.TemporaryDirectory() as d:
        os.environ['MEMSLOT_DIR'] = d
        os.environ['MEMSLOT_BUDGET_GB'] = '6'
        os.environ['MEMSLOT_HELD'] = ''
        parent = memslot.Slot(6, 'mojoc', budget=6).acquire()
        try:
            child_env = dict(os.environ, **memslot.held_env(6))
            t0 = time.time()
            r = subprocess.run([sys.executable, MEMSLOT, "--gb", "6", "--label", "mojoc-recipe",
                                "--", sys.executable, "-c", "print('recipe ran')"],
                               env=child_env, capture_output=True, text=True, timeout=30)
            check("a wrapper inside an admitted tree is not made to queue behind it",
                  r.returncode == 0 and 'recipe ran' in r.stdout,
                  "rc=%s after %.1fs: %s" % (r.returncode, time.time() - t0, r.stderr.strip()))
            check("...and the tree is still capped at what it reserved",
                  '--limit-gb 6' not in r.stdout and 'ceiling 6.0 GB' in r.stdout,
                  'the ceiling must still be applied: ' + r.stdout.strip()[:120])
            check("...and the parent's reservation is untouched by it",
                  memslot.reserved_gb() == 6, '%.1f GB' % memslot.reserved_gb())

            # A request the inherited reservation does NOT cover is a real
            # mismatch: the tree was admitted for 6 and this asks for 8, which
            # would let it reach past its own accounting. It has to queue for
            # the ledger like anyone else. The budget is 12 here so that 8
            # FITS the machine — what it does not fit is the 6 the tree was
            # already admitted for, which is the mismatch being tested.
            os.environ['MEMSLOT_BUDGET_GB'] = '12'
            over = dict(os.environ, **memslot.held_env(6))
            q = subprocess.Popen([sys.executable, MEMSLOT, "--gb", "8", "--label", "too-big",
                                  "--", "sleep", "1"], env=over,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            time.sleep(1.0)
            check("a wrapper asking for MORE than the tree was admitted queues",
                  q.poll() is None, 'it ran anyway: the tree can now reach for '
                  'more than its accounting')
            q.kill(); q.wait()
            os.environ['MEMSLOT_BUDGET_GB'] = '6'
            gone = subprocess.run([sys.executable, MEMSLOT, "--gb", "9", "--label", "over-budget",
                                   "--", "true"], env=dict(os.environ, MEMSLOT_HELD=""),
                                  capture_output=True, text=True, timeout=30)
            check("...and over the whole budget with nothing inherited is refused (126)",
                  gone.returncode == 126, 'rc=%s' % gone.returncode)
        finally:
            parent.release()
            check("...and releasing the parent frees the whole tree",
                  memslot.reserved_gb() == 0, '%.1f GB left' % memslot.reserved_gb())
            os.environ['MEMSLOT_HELD'] = ''

    # A tree that holds the WHOLE budget and a recipe that asks for more than
    # its class. This used to be reachable through `excl` (which reserved the
    # whole budget, whatever the class), and since 2026-09-30 it is not: an
    # exclusive job reserves its class like any other, and the escape hatch
    # below is for the case that remains — MEMSLOT_BUDGET_GB set below a
    # memclass, e.g. 64 with a `stage` job, where the tree holds all 64 and the
    # recipe asks for 96. Nothing is left to reserve and nothing is left to
    # overrun — nothing else can be admitted at all — so it runs, and the
    # ceiling still applies. Refusing it (126) would take `make mojoc` down for
    # a budget setting that is meant to be supported.
    with tempfile.TemporaryDirectory() as d:
        os.environ['MEMSLOT_DIR'] = d
        os.environ['MEMSLOT_BUDGET_GB'] = '64'
        os.environ['MEMSLOT_HELD'] = ''
        parent = memslot.Slot(64, 'stage-excl', budget=64).acquire()
        try:
            r = subprocess.run([sys.executable, MEMSLOT, "--gb", "96", "--label", "stage2/mojo",
                                "--", sys.executable, "-c", "print('stage ran')"],
                               env=dict(os.environ, **memslot.held_env(64)),
                               capture_output=True, text=True, timeout=30)
            check("a wrapper under a whole-budget reservation is covered whatever it asks for",
                  r.returncode == 0 and 'stage ran' in r.stdout,
                  "rc=%s: %s" % (r.returncode, r.stderr.strip()[:160]))
            check("...and its own ceiling is still the one applied",
                  'ceiling 96.0 GB' in r.stdout, r.stdout.strip()[:120])
        finally:
            parent.release()

    # ── a POOL: one admitted reservation as the ceiling on its own fan-out ───
    # The hole this closes is bugs/MEMCAP_ab_sweep_per_file_reservations_are_
    # covered_by_the_parent.md. `ab-aside`/`ab-bside` are `make` jobs admitted
    # for `program` (55 GB) and their recipe is `make -j20`, one
    # `tools/ab_run_one.py` per file. Every child asked for its own per-file
    # `module` class, `covering()` said "already accounted for" because 24 <= 55,
    # and each took NOTHING from the ledger — so the ledger's view of the
    # machine was a single 55 GB holder against an allowance of twenty 24 GB
    # ceilings. A per-process ceiling is not a bound on a sum: that is the
    # 2026-09-29 shape (~30 processes at 30-43 GB each, every one inside its own
    # ceiling) and it is what the reservation exists to prevent.
    #
    # Scaled to fit the file's arithmetic: a parent admitted for 6 of 10, a pool
    # of 6, and three children of 3. Two fit inside the parent's own
    # reservation; the third has to wait, which is the whole difference.
    with tempfile.TemporaryDirectory() as d:
        os.environ['MEMSLOT_DIR'] = d
        os.environ['MEMSLOT_BUDGET_GB'] = '10'
        os.environ['MEMSLOT_HELD'] = ''
        parent = memslot.Slot(6, 'ab-bside', budget=10).acquire()
        try:
            child = dict(os.environ, **memslot.held_env(6, pool='ab-bside'))
            probe = ("import sys, time, os; sys.path.insert(0, %r); import memslot;"
                     "s = memslot.Slot(3, 'file' + sys.argv[1], pool=True).acquire();"
                     "print('in', flush=True); time.sleep(2); s.release()"
                     % os.path.join(HERE, 'tools'))
            kids = [subprocess.Popen([sys.executable, '-c', probe, str(i)],
                                     env=child, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True)
                    for i in range(3)]
            time.sleep(1.2)
            # The POOL LEDGER is the instrument, not process liveness: a child
            # blocked on the pool is alive too, and a `readline()` on its pipe
            # blocks until it is admitted, which is the very thing under test.
            pool_file = os.path.join(d, 'ledger-ab-bside.json')
            pool = json.load(open(pool_file)) if os.path.exists(pool_file) else {}
            in_pool = pool.get('holders', [])
            check("a pool bounds a fan-out by the reservation that admitted it",
                  len(in_pool) == 2 and sum(h['gb'] for h in in_pool) == 6,
                  f'{len(in_pool)} children hold {sum(h["gb"] for h in in_pool)} '
                  f'of the 6 GB pool; a third would be 9 of the 6 reserved')
            check("...and the machine ledger is not double-counted: it carries "
                  "the parent alone",
                  memslot.reserved_gb() == 6,
                  f'{memslot.reserved_gb()} GB on the machine ledger; the '
                  f"pool's usage is INSIDE the parent's reservation, not in "
                  f"addition to it")
            for p in kids:
                p.wait(timeout=30)
            check("...and the third is admitted once the first two are done",
                  all(p.returncode == 0 for p in kids),
                  f'{[p.returncode for p in kids]}')
            left = json.load(open(pool_file))['holders'] if os.path.exists(pool_file) else []
            check("...leaving no pool reservation behind", left == [],
                  f'{left}; a pool entry that outlives its children is a leak '
                  f'in the ledger')

            # A child that does NOT opt in is unaffected: it is covered by the
            # inherited reservation, as `make mojoc`'s recipe is.
            r = subprocess.run([sys.executable, MEMSLOT, "--gb", "6", "--label", "recipe",
                                "--", "true"], env=child,
                               capture_output=True, text=True, timeout=30)
            check("a child that does not opt into the pool is still covered by "
                  "its ancestor's reservation",
                  r.returncode == 0, 'rc=%s' % r.returncode)
            # …and one that asks for MORE than the pool falls back to the
            # machine-wide ledger rather than waiting forever for a turn its own
            # parent is holding. The budget is 16 here so that 9 FITS the
            # machine: what it does not fit is the pool's 6, which is the
            # fallback being tested.
            os.environ['MEMSLOT_BUDGET_GB'] = '16'
            over = dict(os.environ, **memslot.held_env(6, pool='ab-bside'))
            t0 = time.time()
            big = subprocess.run([sys.executable, '-c', probe.replace('3,', '9,'), '0'],
                                 env=over, capture_output=True, text=True, timeout=30)
            check("a child asking for more than the pool takes its own "
                  "reservation instead of deadlocking on the parent's",
                  big.returncode == 0 and time.time() - t0 < 10,
                  f'rc={big.returncode} after {time.time() - t0:.1f}s: '
                  f'{big.stderr.strip()[-160:]}')
        finally:
            parent.release()
            os.environ['MEMSLOT_HELD'] = ''

    # ---- backfill: small jobs sneak in on measured free memory and never delay the head of the queue
    with tempfile.TemporaryDirectory() as d:
        big = start(d, 10, 6, "big")                         # takes the WHOLE budget
        wait_for(lambda: holders(d) == ["big"])
        s1 = start_env(sneak_env(d, 60), 3, 2, "small")      # 60 GB free, margin 16: 60 - 3 >= 16
        check("a small job sneaks in beside a full-budget holder when plenty is free",
              wait_for(lambda: "small" in holders(d), 6), str(holders(d)))
        check("...and is recorded as a sneak in the ledger",
              any(h.get("sneak") for h in ledger(d)["holders"] if h["label"] == "small"))
        s1.wait(); big.wait()
    with tempfile.TemporaryDirectory() as d:
        big = start(d, 10, 4, "big")
        wait_for(lambda: holders(d) == ["big"])
        low = start_env(sneak_env(d, 12), 3, 1, "low")       # 12 free: 12 - 3 = 9 < margin 16: must wait
        time.sleep(1.5)
        check("it does NOT sneak when measured free memory minus its size is under the margin", holders(d) == ["big"], str(holders(d)))
        big.wait(); low.wait()
        check("...and runs normally once the holder leaves", low.returncode == 0)
    with tempfile.TemporaryDirectory() as d:
        big = start(d, 10, 6, "big"); wait_for(lambda: holders(d) == ["big"])
        nine = start_env(sneak_env(d, 80), 9, 1, "nine")     # over SNEAK_MAX (8): never sneaks, however much is free
        time.sleep(1.5)
        check("a request over the sneak size limit never sneaks", holders(d) == ["big"], str(holders(d)))
        big.wait(); nine.wait()
    with tempfile.TemporaryDirectory() as d:
        e = sneak_env(d, 80, MEMSLOT_SNEAK_CAP_GB=4)
        big = start(d, 10, 6, "big"); wait_for(lambda: holders(d) == ["big"])
        a = start_env(e, 3, 5, "a"); wait_for(lambda: "a" in holders(d), 6)
        b = start_env(e, 3, 1, "b"); time.sleep(1.5)
        check("total sneaking is capped (3 + 3 > 4): the second waits", "b" not in holders(d) and "a" in holders(d), str(holders(d)))
        for p_ in (big, a, b): p_.wait()
    with tempfile.TemporaryDirectory() as d:
        # a sneaker does not count against the budget, so it cannot delay the job at the head of the queue
        a = start(d, 6, 4, "a"); wait_for(lambda: holders(d) == ["a"])
        sn = start_env(sneak_env(d, 80), 3, 4, "sn"); wait_for(lambda: "sn" in holders(d), 6)
        head = start(d, 4, 1, "head")                        # 6 + 4 = 10 fits the budget; the 3 GB sneaker must not block it
        check("a sneaker never delays a request that fits the budget", wait_for(lambda: "head" in holders(d) or head.poll() is not None, 6))
        for p_ in (a, sn, head): p_.wait()
    with tempfile.TemporaryDirectory() as d:
        # an unmeasurable machine never reads as plenty
        e = sneak_env(d, 80); e.pop("MEMSLOT_AVAIL_GB"); e["PATH"] = "/nonexistent"
        r = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0,%r); import memslot; print(memslot.avail_gb())" % os.path.join(HERE, "tools")],
                           env=e, capture_output=True, text=True)
        check("with no vm_stat, avail_gb() is None (no sneaking on a missing measurement)", r.stdout.strip() == "None", r.stdout + r.stderr)

    print("Results: %d passed, %d failed" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
