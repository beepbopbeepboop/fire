#!/usr/bin/env python3
"""The light-gate swarm: keep N workers on bugs/ docs, land what they finish, verify after landing.

    CONTROL_MODEL=openrouter/openrouter/free python3 tools/swarm.py [--target 2] [--interval 120]

One pass, repeated:
  1. FEED    keep the queue stocked: each missing worker slot gets the next free bugs/ doc (not FORMAL_*, which
             formal_feed.py owns; not a doc any live task, queued task or external `control.py claim` holds). A doc
             is re-fed as long as nothing says stop. A doc whose bug report carries a line `STOP: <reason>` is NOT fed:
             the feeder logs the reason every pass it reaches that doc. That line is the only stop: there is no retry
             count. Each re-feed logs what the previous attempt produced (commits, or none).
  2. REFILL  `control.py refill --target N --prefix bug-,fix-` -- a worker that finishes frees its slot at once.
  3. LAND    finished bug-*/fix-* branches are merged by `integrate.py --stdlib` (gate = the stdlib compile only); a
             conflicting branch is handed to a merge-fixer worker on the same model (CONTROL_MODEL).
  4. VERIFY  after a landing, `verify_landed.py` (make check + stdlib-dylib) runs in the background on master; red files a
             fix-landed-* task that the next REFILL starts.
The integrator and the verifier each take their own flock, so only one of each ever runs."""
import argparse, glob, hashlib, json, os, re, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import control as C
import integrate as I

SKIP = re.compile(r"^(FORMAL_|COMPILE_FAIL_|MERGE_|OPEN_WORK|PERF_memory_over|DOCS_)")
PREFIXES = ("bug-", "fix-")
STOP = re.compile(r"^STOP:[ \t]*(.+?)[ \t]*$", re.M)   # the stop indicator: a line `STOP: <reason>` in the bug doc


def state_path():
    return os.path.join(C.ctl_dir(), "swarm.json")


def load_state():
    try:
        return json.load(open(state_path()))
    except (OSError, ValueError):
        return {"fed": {}}


def log(msg):
    print("%s %s" % (time.strftime("%T"), msg), flush=True)


def held_claims():
    held = set()
    for t in C.load().values():
        if C.state_of(t) not in C.TERMINAL:
            held.update(t.get("claims", []))
    for f in os.listdir(C.qdir()):
        if f.endswith(".json"):
            held.update(json.load(open(os.path.join(C.qdir(), f))).get("claims", []))
    for e in C.external().values():
        held.update(e["claims"])
    return held


def stop_reason(doc):
    """The reason in the doc's `STOP:` line, or None. A missing doc has no stop (the feed reads it from the glob)."""
    try:
        m = STOP.search(open(os.path.join(C.MAIN, doc_path(doc)), encoding="utf-8").read())
    except OSError:
        return None
    return m.group(1) if m else None


def doc_hash(doc):
    """Content hash of the doc now (None if it is gone): a no-progress attempt is re-fed only once this changes."""
    try:
        return hashlib.sha1(open(os.path.join(C.MAIN, doc_path(doc)), "rb").read()).hexdigest()
    except OSError:
        return None


def bug_docs(base):
    """Every bugs/ doc (rel path without .md) whose base name is `base`."""
    return [os.path.relpath(p, os.path.join(C.MAIN, "bugs"))[:-3]
            for p in glob.glob(os.path.join(C.MAIN, "bugs", "**", base + ".md"), recursive=True)]


def last_attempt(base):
    """Summary of the most recent registry task that held this doc, for the feed log: its commits, or none."""
    tasks = [t for t in C.load().values() if "bug:" + base in t.get("claims", [])]
    if not tasks:
        return None
    t = max(tasks, key=lambda t: t.get("started", ""))
    n = C.ahead(t)
    return "%d commit(s) (%s)" % (n, C.state_of(t)) if n else "NO commit (%s)" % C.state_of(t)


def task_name(doc):
    return ("bug-" + re.sub(r"[^a-z0-9]+", "-", doc.lower()))[:40].rstrip("-")


def doc_path(doc):
    return "bugs/%s.md" % doc


def feed():
    """Keep every pool slot supplied: each slot gets (its count - running + 1) queued tasks, drawn from the pool's
    `feed` globs (skipping the pool's `skip` prefixes, and any doc a live task or external claim holds). A slot is
    fed only its own tasks; nothing moves between slots."""
    pool = C.load_pool()
    skips = pool.get("skip", [])
    st = load_state()
    held, made = held_claims(), 0
    running = C.running_by_slot()
    queued = {}
    for f in os.listdir(C.qdir()):
        if f.endswith(".json") and f.startswith(PREFIXES):
            q = json.load(open(os.path.join(C.qdir(), f))).get("pool")
            queued[q] = queued.get(q, 0) + 1
    # Tasks are not tied to a slot (refill gives each to a free one), so the feeder keeps the WHOLE queue stocked:
    # total capacity + 1, less what runs and what waits. A task is queued with no preferred slot.
    total_need = max(0, C.pool_total() - sum(running.values()) + 1 - sum(queued.values()))
    need = {sl["name"]: 0 for sl in pool["slots"]}
    live_slots = [sl["name"] for sl in pool["slots"] if sl["count"] > 0]
    if live_slots:
        need[live_slots[0]] = total_need
    paths = sorted(set(p for g in pool["feed"] for p in glob.glob(os.path.join(C.MAIN, g))))
    slots = [sl for sl in pool["slots"] if need[sl["name"]] > 0 and sl["count"] > 0]   # count 0: no new runs
    for p in paths:
        if not slots:
            break
        rel = os.path.relpath(p, os.path.join(C.MAIN, "bugs"))
        doc = rel[:-3] if rel.endswith(".md") else rel
        base = os.path.basename(doc)
        if any(base.startswith(x) or x in base for x in skips):
            continue
        if "bug:" + base in held:
            continue
        why = stop_reason(doc)
        if why:
            log("stopped %s: %s" % (doc, why))
            continue
        np = st.get("no_progress", {}).get(base)
        if np and np == doc_hash(doc):
            log("held %s: its last attempt made no commit and the doc has not changed since" % doc)
            continue
        prev = last_attempt(base) if st["fed"].get(doc) else None
        if prev:
            log("re-feed %s: previous attempt %s" % (doc, prev))
        sl = slots[0]
        name = task_name(doc)
        if name in C.load():                   # the 40-char name collides with an old task: make it unique
            name += "-%d" % int(time.time() % 10000)
        task = ("Fix the bug in %s at its ROOT CAUSE. Read the doc's Status/next step first; it may already be fixed "
                "on master (then delete the doc with a pinning test, or report). QUICK tests only: write a small regression "
                "test that FAILS before your fix and passes after (next to the existing tests for that area), and run just "
                "that test plus the one existing test file that covers the code you touched, each wrapped in python3 "
                "tools/memslot.py --gb 8 --label x --. No gate, no stdlib sweep, no self-host build: an integrator gates on "
                "the stdlib compile after you land. If the bug is fully fixed, git rm its doc in the same commit and run "
                "python3 tools/dangling_doc_refs.py --ratchet. Commit, end with a clean tree and the CONTROL-STATUS line." % doc_path(doc))
        r = subprocess.run([sys.executable, os.path.join(HERE, "control.py"), "enqueue", name, "--claim", "bug:" + base,
                            "--task", task], capture_output=True, text=True, cwd=C.MAIN)
        st["fed"][doc] = st["fed"].get(doc, 0) + 1
        if r.returncode == 0:
            made += 1
            need[sl["name"]] -= 1
            if need[sl["name"]] <= 0:
                slots = [x for x in slots if need[x["name"]] > 0]
    json.dump(st, open(state_path(), "w"), indent=1)
    return made


def refill(target):
    r = subprocess.run([sys.executable, os.path.join(HERE, "control.py"), "refill", "--target", str(target),
                        "--prefix", ",".join(PREFIXES)], capture_output=True, text=True, cwd=C.MAIN)
    return (r.stdout.strip().splitlines() or [""])[-1]


def abandon_empty():
    """A worker that exited with NO commits did nothing to land: free its claim, and record the doc's content hash so the
    feeder does not re-feed it until the doc changes (progress is what requeues a doc, not a retry count)."""
    st = load_state()
    n = 0
    for name, t in C.load().items():
        if name.startswith(PREFIXES) and C.state_of(t) in ("exited-ok", "exited-err") and not C.ahead(t) \
                and not C.git("status", "--short", cwd=t["worktree"], check=False) if os.path.isdir(t.get("worktree", "")) else False:
            subprocess.run([sys.executable, os.path.join(HERE, "control.py"), "mark", name, "abandoned"], capture_output=True)
            for c in t.get("claims", []):
                if c.startswith("bug:"):
                    docs = bug_docs(c[4:])
                    if docs:
                        st.setdefault("no_progress", {})[c[4:]] = doc_hash(docs[0])
            n += 1
    json.dump(st, open(state_path(), "w"), indent=1)
    return n


def fresh_first(names, tasks):
    """Branches that have never been tried to land go before any that already failed integration. A failed branch
    must not hold a fresh one back: it can conflict, or turn a batch red, and the fresh branches still land."""
    fresh = [n for n in names if C.state_of(tasks[n]) != "integration-failed"]
    return fresh if fresh else names


def probe(batch):
    """Merge and gate `batch` exactly as a landing would, changing NO state (integrate.py --probe). Returns
    (verdict, merged, failing, out): verdict GREEN/RED/EMPTY; merged is the set that was merged; failing the jobs."""
    r = subprocess.run([sys.executable, os.path.join(HERE, "integrate.py"), "--stdlib", "--probe", "--only"] + batch,
                       capture_output=True, text=True, cwd=C.MAIN)
    out = r.stdout + r.stderr
    pm = re.search(r"^PROBE (GREEN|RED): ?(.*)$", out, re.M)
    if not pm:
        return "EMPTY", [], [], out
    fm = re.search(r"^FAILED_JOBS: ?(.*)$", out, re.M)
    ff = re.search(r"^FAILED_FILES: ?(.*)$", out, re.M)
    failing = (fm.group(1).split() if fm else []) + (ff.group(1).split() if ff else [])
    return pm.group(1), pm.group(2).split(), failing, out


def find_culprit(seq, failing):
    """The branch that turns the gate red when added to the ones before it: binary search for the smallest red prefix
    of `seq` (the whole of `seq` is red, with the jobs `failing`; prefixes before the culprit are green)."""
    lo, hi = 0, len(seq)
    while hi - lo > 1:
        mid = (lo + hi) // 2
        v2, _, f2, _ = probe(seq[:mid])
        if v2 == "RED":
            hi, failing = mid, f2
        else:
            lo = mid
    return seq[hi - 1], failing or []


def land():
    names = [n for n in I.pick_candidates(quiet=True) if n.startswith(PREFIXES)]
    names = fresh_first(names, C.load())
    dirty = set(C.git("diff", "--name-only", "HEAD", cwd=C.MAIN).split())
    if dirty:
        tasks, keep = C.load(), []
        for n in names:
            hit = dirty & set(C.git("diff", "--name-only", "master..." + tasks[n]["branch"], check=False).split())
            if hit:
                log("holding %s: the main checkout has uncommitted edits to %s" % (n, ", ".join(sorted(hit))))
            else:
                keep.append(n)
        names = keep
    if not names:
        return None
    tasks = C.load()
    batch, landed = list(names), False
    while batch:
        verdict, merged, failing, out = probe(batch)
        for c in re.findall(r"^CONFLICT (\S+):", out, re.M):           # a branch that cannot merge: its fixer
            if c in batch:
                log("conflict %s: handing it to a merge fixer" % c)
                I.enqueue_merge_fix(c, tasks[c], out)
                batch.remove(c)
        if verdict == "EMPTY" or not merged:
            break
        if verdict == "GREEN":
            r = subprocess.run([sys.executable, os.path.join(HERE, "integrate.py"), "--stdlib", "--only"] + merged,
                               capture_output=True, text=True, cwd=C.MAIN)
            for line in (r.stdout + r.stderr).splitlines():
                if line.startswith(("GREEN", "RED", "CONFLICT", "another integrator", "master moved")):
                    log(line[:200])
            landed = "GREEN" in (r.stdout + r.stderr)
            break
        # RED: the batch as a whole fails the gate. Find the one branch that breaks it; that branch goes to a fixer
        # with its failing tests named, and the rest of the batch is probed again (and lands when it is green).
        culprit, failing = find_culprit(merged, failing)
        log("red: %s breaks the gate (%s); it goes to a fixer, the rest of the batch continues"
            % (culprit, " ".join(failing) or "jobs unknown"))
        I.enqueue_red_fix(culprit, tasks[culprit], failing)
        batch = [n for n in batch if n != culprit]
    return landed


def verify_async():
    subprocess.Popen([sys.executable, os.path.join(HERE, "verify_landed.py")], cwd=C.MAIN, start_new_session=True,
                     stdout=open(os.path.join(C.ctl_dir(), "verify.out"), "a"), stderr=subprocess.STDOUT)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", type=int, default=None, help="default: the pool's total slots (tools/pool.json)")
    ap.add_argument("--interval", type=int, default=120, help="seconds between passes (0: one pass)")
    a = ap.parse_args()
    if a.target is None:
        a.target = C.pool_total()
    while True:
        try:
            log("feed +%d, abandoned %d; %s" % (feed(), abandon_empty(), refill(a.target)))
            if land():
                verify_async()
                subprocess.run([sys.executable, os.path.join(HERE, "control.py"), "cleanup"], capture_output=True, cwd=C.MAIN)  # landed trees go
                log("landed; post-landing verifier started")
        except Exception as e:      # an unattended loop must survive one bad pass
            log("pass failed: %r" % (e,))
        if not a.interval:
            return
        time.sleep(a.interval)


if __name__ == "__main__":
    main()
