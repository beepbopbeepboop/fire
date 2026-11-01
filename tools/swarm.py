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


def hold_active(np, h, retry_s, now=None):
    """A no-progress record holds its doc while the doc is unchanged AND the retry window has not passed."""
    if not np:
        return False
    now = time.time() if now is None else now
    return np["hash"] == h and now - np["at"] < retry_s


ESCALATE_AFTER = 1   # a no-commit attempt boosts the doc one class: a work tree that does not finish moves up


def dir_class(doc):
    """Every doc starts at the easy tier, wherever it sits; only failures move it up (reclass_on_failure)."""
    return "easy"


def doc_class(doc, st, base):
    """The class a doc is queued in: its escalated class if it has been reclassed, else its directory's."""
    return st.get("cls", {}).get(base) or dir_class(doc)


def escalate(c):
    i = C.CLASSES.index(c)
    return C.CLASSES[i + 1] if i + 1 < len(C.CLASSES) else None


def feed():
    """Keep every pool slot supplied: each slot gets (its count - running + 1) queued tasks, drawn from the pool's
    `feed` globs (skipping the pool's `skip` prefixes, and any doc a live task or external claim holds). A slot is
    fed only its own tasks; nothing moves between slots."""
    pool = C.load_pool()
    skips = pool.get("skip", [])
    st = load_state()
    held, made = held_claims(), 0
    retry_s = pool.get("retry_hours", 12) * 3600.0
    slot_cls = {sl["name"]: C.slot_class(sl) for sl in pool["slots"]}
    # Each class keeps its own queue: capacity of its live slots, plus one, less what runs and what waits in it.
    cap = {c: sum(sl["count"] for sl in pool["slots"] if C.slot_class(sl) == c) for c in C.CLASSES}
    busy = {c: 0 for c in C.CLASSES}
    for slot, n in C.running_by_slot().items():
        busy[slot_cls.get(slot, "easy")] += n
    queued = {c: 0 for c in C.CLASSES}
    for f in os.listdir(C.qdir()):
        if f.endswith(".json") and f.startswith(PREFIXES):
            item = json.load(open(os.path.join(C.qdir(), f)))
            queued[item.get("cls") or slot_cls.get(item.get("pool"), "easy")] += 1
    need = {c: max(0, cap[c] - busy[c] + 1 - queued[c]) if cap[c] > 0 else 0 for c in C.CLASSES}
    paths = sorted(set(p for g in pool["feed"] for p in glob.glob(os.path.join(C.MAIN, g))))
    for p in paths:
        if not any(need.values()):
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
        cls = doc_class(doc, st, base)
        if need[cls] <= 0:
            continue                           # its class is full: the doc waits for a slot of that class
        np = st.get("no_progress", {}).get(base)
        if isinstance(np, str):                # written before holds expired: start its clock now
            np = {"hash": np, "at": time.time()}
        if hold_active(np, doc_hash(doc), retry_s):
            log("held %s: its last attempt made no commit; retried after %.1f h, or sooner if the doc changes"
                % (doc, retry_s / 3600.0 - (time.time() - np["at"]) / 3600.0))
            continue
        prev = last_attempt(base) if st["fed"].get(doc) else None
        if prev:
            log("re-feed %s: previous attempt %s" % (doc, prev))
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
                            "--task", task, "--cls", cls], capture_output=True, text=True, cwd=C.MAIN)
        st["fed"][doc] = st["fed"].get(doc, 0) + 1
        if r.returncode == 0:
            made += 1
            need[cls] -= 1
    json.dump(st, open(state_path(), "w"), indent=1)
    return made


def refill(target):
    r = subprocess.run([sys.executable, os.path.join(HERE, "control.py"), "refill", "--target", str(target),
                        "--prefix", ",".join(PREFIXES)], capture_output=True, text=True, cwd=C.MAIN)
    return (r.stdout.strip().splitlines() or [""])[-1]


def reclass_on_failure(st, base, doc):
    """Count a no-commit attempt at the doc's class; after ESCALATE_AFTER of them the doc moves up one class and its hold
    is cleared, so the stronger slot can take it at once. The top class keeps its docs (they wait for a hard slot)."""
    fails = st.setdefault("fails", {})
    fails[base] = fails.get(base, 0) + 1
    cur = doc_class(doc, st, base)
    nxt = escalate(cur)
    if nxt and fails[base] >= ESCALATE_AFTER:
        st.setdefault("cls", {})[base] = nxt
        fails[base] = 0
        st.setdefault("no_progress", {}).pop(base, None)
        log("reclass %s: %s -> %s after %d no-commit attempts" % (doc, cur, nxt, ESCALATE_AFTER))


def abandon_empty():
    """A worker that exited with NO commits did nothing to land: free its claim, and record the doc's content hash and
    time so the feeder holds it for pool.json's retry_hours, or until the doc changes, whichever is first. A limit or
    quota kill is not recorded: it bans the slot (control.py), it says nothing about the doc."""
    st = load_state()
    n = 0
    for name, t in C.load().items():
        if name.startswith(PREFIXES) and C.state_of(t) in ("exited-ok", "exited-err") and not C.ahead(t) \
                and not C.git("status", "--short", cwd=t["worktree"], check=False) if os.path.isdir(t.get("worktree", "")) else False:
            subprocess.run([sys.executable, os.path.join(HERE, "control.py"), "mark", name, "abandoned"], capture_output=True)
            # A limit or quota kill says nothing about the doc: the slot is banned for that, the doc is not held.
            if not C.limit_hit(t):
                for c in t.get("claims", []):
                    if c.startswith("bug:"):
                        docs = bug_docs(c[4:])
                        if docs:
                            st.setdefault("no_progress", {})[c[4:]] = {"hash": doc_hash(docs[0]), "at": time.time()}
                            reclass_on_failure(st, c[4:], docs[0])
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
    if "another integrator" in out:                  # the lock is held (the post-landing verifier runs under it)
        return "BUSY", [], [], out
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
        if verdict == "BUSY":
            log("integrator busy (the post-landing verifier holds the lock); landing waits for the next pass")
            break
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
            subprocess.run([sys.executable, os.path.join(HERE, "cpu_cap.py"), "ratchet"], capture_output=True, cwd=C.MAIN)
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
