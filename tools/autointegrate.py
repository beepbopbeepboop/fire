#!/usr/bin/env python3
"""Run integration unattended. THE ALGORITHM: merge EVERY finished branch into the integrator, gate it ONCE, fix what
breaks, and land everything when it is green. One run clears the whole backlog; serial one-at-a-time grows it.

  1. BATCH   all finished branches (priority order) are merged onto master and the full gate runs once, with any red job
             confirmed by re-running just those jobs alone (load flakes are not verdicts). Green: the whole batch lands.
  2. BISECT  only if it goes wrong. The jobs that failed ARE the test case: probe the first half of the merge order with
             just those jobs (right track / wrong track, minutes, no side effects), then half of what is left, ... ~log2(n)
             probes name the first bad branch. That branch is set aside and handed to a fixer; everything else is
             re-batched and lands in one gate. Each red batch removes at least one culprit, so it always terminates.
  3. FAST LANE  test-infrastructure-only branches skip the project gate (owner's policy) and land first.

Conflicting branches are not blockers: integrate.py leaves them out and queues a merge fixer for each, and they join a
later batch.

    autointegrate.py [--interval-min 3]

Safeguards, because nobody is watching:
  * The integrator's own flock means a second round cannot start while one runs, and the gate's
    memory reservations (tools/memslot.py) queue it behind any other heavy job.
  * A branch set aside as the first bad one is not retried until its head CHANGES (a new commit); its fixer
    produces that commit.
  * Conflicts are not left for a human: integrate.py enqueues a merge worker for each one and marks the
    conflicting task superseded, and the refill loop (control.py refill) starts it.
  * Master only ever moves by the integrator's fast-forward after a green full gate.
"""
import argparse, hashlib, json, os, re, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control as C
import integrate as I

STATE = os.path.join(C.ctl_dir(), "autointegrate.json")


def log(msg):
    print("%s %s" % (time.strftime("%F %T"), msg), flush=True)


def load_state():
    try:
        return json.load(open(STATE))
    except (OSError, ValueError):
        return {"red_sets": []}


def head_sha(name):
    t = C.load()[name]
    return subprocess.run(["git", "rev-parse", "--short", t["branch"]], cwd=C.MAIN, capture_output=True, text=True).stdout.strip()


def run_integrate(*args):
    r = subprocess.run([sys.executable, os.path.join(C.MAIN, "tools", "integrate.py")] + list(args), capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def failed_jobs(tree_log):
    """The FAILED section of a suite/gate log, as text, for a fixer's task."""
    try:
        txt = open(tree_log, errors="replace").read()
    except OSError:
        return ""
    m = re.search(r"^FAILED:\n(.*?)(?=^[A-Z-]+.*:\n|^suite:)", txt, re.S | re.M)
    return (m.group(1) if m else "")[:1500].strip()


def enqueue_fixer(name, why):
    t = C.load()[name]
    if name.startswith("fix-screen-fix-screen-"):
        log("%s failed its screen again after two fix attempts: leaving it for a human" % name); return
    import argparse as _ap
    task = ("Branch %s (a finished worker branch; its task: %s) FAILS the integrator's quick tier ON ITS OWN, merged alone onto the "
            "current master. Failing jobs: %s. You start on the branch. Reproduce the failing job(s) narrowly (for the self-host "
            "build: python3 tools/memslot.py --gb 8 --label repro -- python3 fire.py build fire.py -o .tmp/mojoc; for the "
            "others run the named job's own test file, each under memslot --gb 8), find the change in the branch that causes it "
            "(`git diff master...HEAD`, bisect its commits), and fix it properly without losing what the branch delivers; the "
            "branch's own tests must still pass. Light worker: no gate. Never use git stash. Commit; finish with the REPORT block "
            "and a CONTROL-STATUS line. Excerpt of the failure:\n%s" % (t["branch"], t["summary"][:150], why.splitlines()[0] if why else "?", why))
    fname = "fix-screen-" + name
    if fname in C.load():
        fname += "-%d" % int(time.time() % 100000)
    C.cmd_enqueue(_ap.Namespace(name=fname[:60], claim=t["claims"] or ["task:" + fname], task=task, task_file=None, file=[],
                                base=t["branch"], needs=[], model=None))
    with C.registry() as reg:
        reg[name]["state"] = "superseded"


def parse(out, key):
    for line in out.splitlines():
        if line.startswith(key + ":"):
            return line.split(":", 1)[1].split()
    return []


def probe(prefix, failed_jobs_):
    """Right track / wrong track: merge exactly `prefix` and run ONLY the jobs that failed. Minutes, no side effects."""
    rc, out = run_integrate("--only", *prefix, "--jobs", *failed_jobs_, "--no-fixers")
    return rc == 0 and "--jobs run finished" in out


def bisect_first_bad(merged, failed_jobs_):
    """`merged` (ordered) fails `failed_jobs_` as a whole. Return k with merged[:k] passing them and merged[:k+1] failing:
    merged[k] is the first branch that breaks them. Each probe tests half of what is left (100%, 50%, 25%, 12%, ...), so ~log2(n)
    probes of just the failing jobs find it."""
    lo, hi = 0, len(merged)            # invariant: prefix lo passes (the empty one does), prefix hi fails
    while hi - lo > 1:
        mid = (lo + hi) // 2
        ok = probe(merged[:mid], failed_jobs_)
        log("  probe %d/%d branches on %s: %s" % (mid, len(merged), ",".join(failed_jobs_), "right track" if ok else "WRONG track"))
        if ok:
            lo = mid
        else:
            hi = mid
    return lo


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--interval-min", type=float, default=3, help="sleep only when there is nothing to do or the integrator is busy")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    while True:
        st = load_state()
        red = st.setdefault("red", {})
        busy = False
        # FAST LANE FIRST: test-infrastructure-only branches need no project gate (owner's policy) and cost minutes.
        for name in sorted(I.pick_candidates(quiet=True), key=C.priority_key):
            if name in I.pick_candidates(quiet=True) and I.infra_only(C.load()[name]["branch"]):
                log("%s touches only test infrastructure: fast lane (no project gate)" % name)
                rc, out = run_integrate("--only", name, "--fast")
                log("%s: rc=%d %s" % (name, rc, " | ".join(l for l in out.splitlines() if l.startswith(("GREEN", "RED", "NOT test", "CONFLICT")))[:240]))
                if "another integrator" in out:
                    busy = True; break
        did = False
        if not busy:
            # THE ALGORITHM: merge EVERY finished branch (priority order), run the gate ONCE, land everything if it is green.
            batch = [n for n in sorted(I.pick_candidates(quiet=True), key=C.priority_key)
                     if not I.infra_only(C.load()[n]["branch"]) and red.get(n) != head_sha(n)]
            if batch:
                did = True
                log("BATCH: all %d finished branches merged, one gate: %s" % (len(batch), ", ".join(batch)[:300]))
                rc, out = run_integrate("--only", *batch)
                merged, failed = parse(out, "MERGED"), parse(out, "FAILED_JOBS")
                tail = [l for l in out.splitlines() if l.startswith(("GREEN", "RED", "CONFLICT", "the red did NOT"))]
                log("batch result rc=%d merged=%d failed jobs=%s %s" % (rc, len(merged), failed or "-", " | ".join(tail)[:200]))
                if "another integrator" in out:
                    busy = True
                elif rc != 0 and merged:
                    # Only if it goes wrong: step back and BISECT. The failing jobs ARE the test case: probe halves with just them.
                    if not failed:
                        log("red but no failing job could be named: setting the whole batch aside for a human"); 
                        for n in merged: red[n] = head_sha(n)
                    else:
                        k = bisect_first_bad(merged, failed)
                        culprit = merged[k]
                        log("first bad branch: %s (the %d before it pass %s)" % (culprit, k, ",".join(failed)))
                        red[culprit] = head_sha(culprit)
                        why = "breaks " + ",".join(failed) + " when merged after " + (merged[k - 1] if k else "master")
                        try:
                            enqueue_fixer(culprit, why + "\n" + failed_jobs(os.path.join(I.INTEG, "gate.log")))
                        except Exception as e:
                            log("could not queue a fixer for %s: %s" % (culprit, e))
                    json.dump(st, open(STATE, "w"))
                    # the next iteration re-batches everything except the culprit: one gate lands the rest
        if a.once:
            return
        if busy or not did:
            time.sleep(a.interval_min * 60)


if __name__ == "__main__":
    main()
