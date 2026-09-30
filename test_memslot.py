#!/usr/bin/env python3
"""tools/memslot.py: memory is reserved before a job starts, out of one machine-wide budget.

Scaled down (budget 10 "GB", jobs that just sleep) so it runs in seconds, but the arithmetic is the
one the real numbers use: a job that takes more than half the budget runs alone; jobs that take a
third run three at a time; the sum of live reservations never exceeds the budget.
"""
import json, os, signal, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
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
    return dict(os.environ, MEMSLOT_DIR=d, MEMSLOT_BUDGET_GB="10")


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
    os.environ['MEMSLOT_DIR'] = tempfile.mkdtemp()
    os.environ['MEMSLOT_BUDGET_GB'] = '10'          # same budget the CLI cases used
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
        for k, v in (('MEMSLOT_DIR', old_dir), ('MEMSLOT_BUDGET_GB', old_budget)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    print("Results: %d passed, %d failed" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
