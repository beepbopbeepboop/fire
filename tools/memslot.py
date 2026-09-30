#!/usr/bin/env python3
"""Reserve memory BEFORE a job starts; run it under a ceiling equal to the reservation.

    memslot.py --gb 30 [--label NAME] [--budget-gb N] -- CMD ARGS...   # wait for room, then run CMD
    memslot.py status                                                   # who holds what, who waits

A ceiling that kills a process after it has already eaten the machine (tools/memcap.py) is not
enough: 30 jobs each *allowed* 24 GB is 720 GB of allowance on a 128 GB box, and every one of
them can sit under its own ceiling while the machine collapses (2026-09-29: about 30 compiler
processes at ~30 GB each, killed by hand). So memory is *allocated to a job before it starts*,
out of one machine-wide budget, exactly like a counting semaphore of gigabytes:

  * a 51 GB job takes 51 of the budget; with the default 96 GB budget a second one waits;
  * a 30 GB job takes 30; three run together, a fourth waits;
  * a request larger than the whole budget is refused outright, never queued forever.

The job then runs under `tools/memcap.py` with its ceiling set to *the same number it reserved*,
so the reservation is a hard promise in both directions: the scheduler never admits more than the
budget, and no admitted job may take more than it was given.

Rules that make this safe to share between every worktree, session and the CI runner:

  * ONE ledger for the machine, `~/.gmojo/memslot/ledger.json` (override: MEMSLOT_DIR), updated under an
    exclusive `flock`, written by temp file + rename. It is deliberately outside every worktree.
  * Strict FIFO. A waiting 51 GB request is not starved by an endless stream of small ones that would
    each fit: the head of the queue is admitted first or nobody behind it is.
  * A holder is alive while its `memslot` process OR its job's process is alive. A `memslot` killed with
    SIGKILL leaves the job running, and the reservation must outlive it; a job that has exited frees
    it. Dead holders are pruned on every acquire, so a crash cannot leak budget.
  * The budget is MEMSLOT_BUDGET_GB (default 96: it leaves ~30 GB of a 128 GB machine for the OS and
    for whatever is not going through this tool). It is a promise between cooperating processes, not a
    kernel limit: something that never asks is not counted. `tools/control.py guard` is the backstop.

Two ways to use it, on ONE ledger and ONE set of rules. The command line above is the wrapper, for a
job that needs nothing but to be started. `memslot.Slot` is the in-process reservation, for a caller
that starts the job ITSELF and therefore cannot use a wrapper — `tools/suite.py` cannot, because a
job's timeout must not start counting while it waits its turn for memory, and `tools/ab_run_one.py`
cannot, because its compile is not the whole of what it does. They differ only in who calls
`Popen`; the admission arithmetic, the FIFO, the liveness rules and the file format are the same code
(`acquire`/`release`), which is the whole point of having them here rather than in each caller.

A process may hold SEVERAL reservations at once — the test runner's thread pool has one job per
thread — so a reservation carries an `owner` string and is released by owner. Liveness still keys on
the pid, because that is the thing that actually dies.

A reservation covers the TREE it admitted, and a process already inside one must not take a second.
That is not an optimisation, it is the difference between working and deadlocked: `tools/suite.py`
reserves a job's memclass before spawning it, and the `make mojoc` recipe it spawns is itself
`memslot.py --gb 96 -- …` for the same 96 GB of the same 96 GB budget. Two reservations for one
tree do not fit, so the second queues for a turn that can never come and the gate hangs on its
heaviest step (measured: reproducible in seconds at 1/16 scale, see `test_memslot.py`). So whoever
takes a reservation publishes it in `MEMSLOT_HELD`, and a request inside that tree that the
reservation already covers is served from it — no ledger round-trip, and the ceiling still applied.
A request LARGER than the inherited reservation is a real mismatch (the tree can now reach for more
than its accounting), so it says so on stderr and takes its own reservation anyway: queueing there
would hang, and silently running under a bigger ceiling would be worse.

Set `MEMSLOT_HELD=` (empty) in the environment to opt out and take a fresh reservation regardless —
which is what a TEST of the ledger has to do, or every wrapper it starts would inherit the test's
own reservation and queue behind itself.

Exit status: the command's own, 125 if memcap killed it for exceeding its reservation, 126 if the
request can never fit, 2 on usage errors.
"""
import argparse, fcntl, json, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_BUDGET_GB = 96.0

# The environment variable through which a reservation covers its own tree.
HELD = 'MEMSLOT_HELD'


def ledger_dir():
    d = os.environ.get("MEMSLOT_DIR") or os.path.join(os.path.expanduser("~"), ".gmojo", "memslot")
    os.makedirs(d, exist_ok=True)
    return d


def budget_gb(override=None):
    return float(override if override is not None else os.environ.get("MEMSLOT_BUDGET_GB", DEFAULT_BUDGET_GB))


def inherited_gb():
    """The gigabytes an ANCESTOR of this process already reserved, 0.0 for none.

    Read from the environment rather than from the ledger because the ancestor
    is in a DIFFERENT PROCESS TREE from the one that holds the reservation:
    `tools/suite.py` admits a job, then the job's recipe runs
    `memslot.py -- …`, and by the time that wrapper asks, the pids on the
    holder entries are its grandparent's. The env var is how the reservation
    reaches down into the tree it covers.
    """
    raw = (os.environ.get(HELD) or '').strip()
    if not raw:
        return 0.0
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 0.0


def covering(gb, label):
    """(already_covered, inherited) for a request of `gb` inside this tree.

    The mismatch case is separated out because it is a genuine bug in the
    caller and the two answers are opposite: covered means run it now from the
    ancestor's reservation, not covered means the caller is reaching for more
    memory than the tree was admitted for, and it has to queue (or fail) for it
    like anyone else.
    """
    have = inherited_gb()
    if have and gb > have + 1e-9:
        print("memslot: %s wants %.1f GB but this process tree was only "
              "admitted for %.1f GB (%s); taking a separate reservation, and "
              "the ceiling it is given is larger than its accounting"
              % (label, gb, have, HELD), file=sys.stderr, flush=True)
        return False, have
    return bool(have), have


def _alive(pid):
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (TypeError, ValueError):
        # A pid that is not a pid is not a running process. Reached only by a
        # ledger file some other tool wrote, but reading it must not be a
        # crash: an admission loop that dies on a bad ledger would release
        # nothing and wedge the whole machine's queue.
        return False


class Ledger:
    """Read-modify-write the shared ledger under an exclusive flock."""

    def __enter__(self):
        d = ledger_dir()
        self.path = os.path.join(d, "ledger.json")
        self.lock = open(os.path.join(d, "ledger.lock"), "w")
        fcntl.flock(self.lock, fcntl.LOCK_EX)
        try:
            self.data = json.load(open(self.path))
        except (OSError, ValueError):
            self.data = {}
        self.data.setdefault("holders", [])
        self.data.setdefault("queue", [])
        self.data.setdefault("next_ticket", 1)
        # prune the dead: a holder lives while its memslot or its job lives; a waiter while its memslot does
        self.data["holders"] = [h for h in self.data["holders"] if _alive(h["pid"]) or _alive(h.get("job", 0))]
        self.data["queue"] = [q for q in self.data["queue"] if _alive(q["pid"])]
        return self

    def __exit__(self, *exc):
        tmp = self.path + ".tmp%d" % os.getpid()
        json.dump(self.data, open(tmp, "w"), indent=1)
        os.replace(tmp, self.path)
        fcntl.flock(self.lock, fcntl.LOCK_UN)
        self.lock.close()

    def used(self):
        return sum(h["gb"] for h in self.data["holders"])


def acquire(gb, label, budget, poll=0.5, announce=True, owner=""):
    """Block until `gb` fits under `budget` and this request is first in line; return its ticket.

    `owner` names the reservation inside this process, so one process can hold
    several (the test runner does, one per worker thread) and still release
    exactly the one it means. Liveness is NOT keyed on it: a holder lives while
    the pid that took the reservation is alive, or while the job it started is.
    """
    if gb > budget:
        raise ValueError("request of %.1f GB exceeds the whole budget of %.1f GB" % (gb, budget))
    with Ledger() as L:
        ticket = L.data["next_ticket"]
        L.data["next_ticket"] += 1
        L.data["queue"].append({"ticket": ticket, "pid": os.getpid(), "owner": owner,
                                "gb": gb, "label": label, "t": time.time()})
    told = False
    while True:
        with Ledger() as L:
            head = min(L.data["queue"], key=lambda q: q["ticket"]) if L.data["queue"] else None
            if head and head["ticket"] == ticket and L.used() + gb <= budget + 1e-9:
                L.data["queue"] = [q for q in L.data["queue"] if q["ticket"] != ticket]
                L.data["holders"].append({"pid": os.getpid(), "owner": owner, "job": 0,
                                          "gb": gb, "label": label, "t": time.time()})
                return ticket
            used, ahead = L.used(), sum(1 for q in L.data["queue"] if q["ticket"] < ticket)
        if announce and not told:
            print("memslot: %s wants %.1f GB; %.1f of %.1f in use, %d ahead in line: waiting" % (
                label, gb, used, budget, ahead), file=sys.stderr, flush=True)
            told = True
        time.sleep(poll)


def note_job(pid, owner=""):
    """Record the job's pid on our holder entry, so the reservation outlives a killed memslot."""
    with Ledger() as L:
        for h in L.data["holders"]:
            if h["pid"] == os.getpid() and h.get("owner", "") == owner:
                h["job"] = pid


def release(owner=""):
    """Give back this process's reservation(s) named `owner`. Returns how many."""
    with Ledger() as L:
        keep_h = [h for h in L.data["holders"]
                  if not (h["pid"] == os.getpid() and h.get("owner", "") == owner)]
        freed = len(L.data["holders"]) - len(keep_h)
        L.data["holders"] = keep_h
        L.data["queue"] = [q for q in L.data["queue"]
                           if not (q["pid"] == os.getpid() and q.get("owner", "") == owner)]
    return freed


class Slot:
    """One in-process reservation, for a caller that starts the job itself.

        with memslot.Slot(24, 'bside:foo.mojo') as slot:
            proc = subprocess.Popen(...)
            slot.note_job(proc.pid)     # optional, but see below

    The CLI wrapper is not an option for a scheduler: it would have to start
    the job to time it, and a job's timeout must not run while it waits for
    memory. A `stage` job can wait a long time for a 96 GB reservation on a
    busy machine, and a timeout that counted the queue would kill jobs that
    had done nothing wrong.

    `note_job` is what makes the reservation survive this process being
    SIGKILLed: the entry stays while the job's own pid is alive, and is
    pruned as soon as the job is gone. Without it a killed runner would free
    its reservations while the compilers it started were still running —
    which is the collapse this file exists to prevent.

    A reservation already held by an ANCESTOR of this process covers this one
    (`covering` above), and in that case `acquire` returns immediately and the
    release is a no-op. The two that must not both happen are the runner's own
    admission and the `memslot.py` wrapper in the recipe it admitted.
    """

    __slots__ = ('gb', 'label', 'budget', 'owner', 'ticket', 'waited', 'covered')

    def __init__(self, gb, label, budget=None, owner=None):
        self.gb, self.label = float(gb), label
        self.budget = budget_gb(budget)
        self.owner = owner if owner is not None else f"{os.getpid()}:{label}"
        self.ticket = None
        self.waited = 0.0
        self.covered, _ = covering(self.gb, label)

    def acquire(self):
        t0 = time.time()
        try:
            if not self.covered:
                self.ticket = acquire(self.gb, self.label, self.budget, owner=self.owner)
        finally:
            self.waited = time.time() - t0
        return self

    def note_job(self, pid):
        if self.ticket is not None:
            note_job(pid, self.owner)

    def release(self):
        if self.ticket is not None:
            self.ticket = None
            release(self.owner)

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()
        return False


def held_env(gb):
    """The `MEMSLOT_HELD` value to hand a child, so a reservation covers its tree.

    Every caller that takes a reservation should put this in the environment
    of the process it starts — that is what stops the tree from taking a
    second, contradictory reservation, and it is why the variable carries the
    gigabytes rather than a flag: a nested request is compared against the
    number it was admitted for, and a mismatch is reported.
    """
    return {HELD: f'{float(gb):g}'}


def reserved_gb():
    """How much of the budget is currently reserved. Cheap enough to poll."""
    with Ledger() as L:
        return L.used()


def status():
    with Ledger() as L:
        b = budget_gb()
        print("budget %.1f GB, reserved %.1f GB, free %.1f GB" % (b, L.used(), b - L.used()))
        for h in L.data["holders"]:
            print("  HOLD %6.1f GB  pid %-6d job %-6s %s (%.0fs)" % (
                h["gb"], h["pid"], h.get("job") or "-", h["label"], time.time() - h["t"]))
            if h.get("owner"):
                print("        owner %s" % h["owner"])
        for q in sorted(L.data["queue"], key=lambda q: q["ticket"]):
            print("  WAIT %6.1f GB  pid %-6d #%-4d %s (%.0fs)" % (
                q["gb"], q["pid"], q["ticket"], q["label"], time.time() - q["t"]))


def main(argv):
    if argv[1:2] == ["status"]:
        return status()
    ap = argparse.ArgumentParser(prog="memslot", description=__doc__.split("\n")[0])
    ap.add_argument("--gb", type=float, required=True, help="memory to reserve, and the job's hard ceiling")
    ap.add_argument("--label", default=None)
    ap.add_argument("--budget-gb", type=float, default=None, help="machine-wide budget (default MEMSLOT_BUDGET_GB or 96)")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args(argv[1:])
    cmd = a.cmd[1:] if a.cmd[:1] == ["--"] else a.cmd
    if not cmd:
        ap.error("no command given")
    label = a.label or os.path.basename(cmd[0])
    covered, _ = covering(a.gb, label)
    if not covered:
        try:
            acquire(a.gb, label, budget_gb(a.budget_gb))
        except ValueError as e:
            print("memslot: refused: %s" % e, file=sys.stderr)
            return 126
    try:
        proc = subprocess.Popen([sys.executable, os.path.join(HERE, "memcap.py"), "--limit-gb", str(a.gb),
                                 "--label", label, "--"] + cmd)
        if not covered:
            note_job(proc.pid)
        return proc.wait()
    finally:
        if not covered:
            release()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
