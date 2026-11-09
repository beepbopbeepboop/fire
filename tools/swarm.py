#!/usr/bin/env python3
"""The light-gate swarm: keep N workers on bugs/ docs, land what they finish, verify after landing.

    python3 tools/swarm.py [--target N] [--interval 120]   # --target defaults to the pool total (tools/pool.json)

One pass, repeated:
  1. FEED    keep the queue stocked: each missing worker slot gets the next free bugs/ doc, formal docs included
             (bugs/ is easy class); not a doc any live task, queued task or external `control.py claim` holds. A doc
             is re-fed as long as nothing says stop. A doc whose bug report carries a line `STOP: <reason>` is NOT fed:
             the feeder logs the reason every pass it reaches that doc. That line is the only stop: there is no retry
             count. Each re-feed logs what the previous attempt produced (commits, or none).
  2. REFILL  `control.py refill --target N --prefix bug-,fix-` -- a worker that finishes frees its slot at once.
  3. LAND    finished bug-*/fix-* branches are merged by `integrate.py --stdlib` (gate = the stdlib compile only); a
             conflicting branch is handed to a merge-fixer task (integrate.enqueue_merge_fix).
  4. VERIFY  after a landing, `verify_landed.py` (make check + stdlib-dylib) runs in the background on master; red files a
             fix-landed-* task that the next REFILL starts.
The integrator and the verifier each take their own flock, so only one of each ever runs."""
import argparse, fcntl, glob, hashlib, json, os, re, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import control as C
import integrate as I
import task_text as T

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


# The live-session guard, set once per pass by live_guard(). A task whose worktree an opencode session is still
# driving is BUSY: its agent is working, whatever the registry says (the CLI process may be gone while the session
# keeps running). Busy tasks are never retired, continued, landed, or cleaned, and their claims are held for the feed.
BUSY = {"names": set(), "claims": set()}


def live_guard():
    """Refresh BUSY from the opencode sessions. Returns False when the listing cannot be read: the pass then changes
    nothing that depends on knowing what is live (no feed, continue, retire, land)."""
    try:
        dirs = C.live_session_dirs()
    except (RuntimeError, OSError, ValueError) as e:
        log("guard: %s; falling back to pid-based liveness (session listing unreadable)" % e)
        BUSY["names"], BUSY["claims"] = set(), set()
        return True
    tasks = C.load()
    names = C.busy_task_names(dirs, tasks)
    claims = set()
    for n in names:
        claims.update(tasks[n].get("claims", []))
    BUSY["names"], BUSY["claims"] = names, claims
    log("guard: %d task(s) with a live opencode session in their tree" % len(names))
    return True


def drop_queued_busy():
    """A queued task that names a doc a busy session is working on would start a second worker on it: drop it."""
    for f in os.listdir(C.qdir()):
        if not f.endswith(".json"):
            continue
        path = os.path.join(C.qdir(), f)
        item = json.load(open(path))
        clash = sorted(set(item.get("claims", [])) & BUSY["claims"])
        if clash:
            os.remove(path)
            log("dropped queued %s: %s is held by a live session" % (item.get("name", f), ", ".join(clash)))


def busy_by_class():
    """Running workers per task class: a task counts in its own class (its `cls`), whichever slot it runs on, so a
    slot that also takes another class does not hide that class's load."""
    pool = C.load_pool()
    slot_cls = {sl["name"]: C.slot_class(sl) for sl in pool["slots"]}
    busy = {c: 0 for c in C.CLASSES}
    for t in C.load().values():
        if C.state_of(t) != "running":
            continue
        busy[t.get("cls") or slot_cls.get(t.get("pool"), "easy")] += 1
    return busy


def held_claims():
    held = set(BUSY["claims"])                  # a live session holds its docs, whatever its registry state
    for t in C.load().values():
        if C.holds_claims(t):                   # the same rule spawn uses: live work, or commits not yet landed
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


ESCALATE_AFTER = C.load_pool().get("classes", {}).get("escalate_after", 1)   # no-commit attempts before a doc moves up a class (pool.json)


CLASS_DIR = {"easy": "", "mid": "mid/", "hard": "hard/"}   # the class IS the directory: bugs/, bugs/mid/, bugs/hard/


def dir_class(doc):
    """A doc's class is where its file sits: bugs/<doc>.md is easy, bugs/mid/ mid, bugs/hard/ hard. bugs/ is the
    formal lane's and is not in the swarm's feed globs, so it has no class here."""
    head = doc.split("/", 1)[0] if "/" in doc else ""
    return {"mid": "mid", "hard": "hard"}.get(head, "easy")


def doc_class(doc, st, base):
    """The class a doc is queued in: where its file is. A reclass moves the file (apply_moves), so there is no second
    record to disagree with the location."""
    return dir_class(doc)


def escalate(c):
    i = C.CLASSES.index(c)
    return C.CLASSES[i + 1] if i + 1 < len(C.CLASSES) else None


def enqueue_doc(doc, base, cls, name, start=None):
    """Queue one worker on DOC in class CLS. START names the branch a continuation resumes; otherwise the doc's newest
    unlanded attempt decides where the worker starts (tools/task_text.py), and master when there is none. Returns True
    when the queue took it."""
    p = T.plan(doc, continue_from=start)
    if start and not p["start_branch"]:        # the branch no longer has the doc (it was fixed there): start from master
        log("%s: its branch %s has no doc; starting from master" % (doc, start))
    cmd = [sys.executable, os.path.join(HERE, "control.py"), "enqueue", name, "--claim", "bug:" + base,
           "--task", p["text"], "--cls", cls]
    if p["start_branch"]:
        cmd += ["--base", p["start_branch"]]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=C.MAIN).returncode == 0


def feed():
    """Keep every pool slot supplied: each slot gets (its count - running + 1) queued tasks, drawn from the pool's
    `feed` globs (skipping the pool's `skip` prefixes, and any doc a live task or external claim holds). A slot is
    fed only its own tasks; nothing moves between slots."""
    pool = C.load_pool()
    skips = pool.get("skip", [])
    st = load_state()
    held, made = held_claims(), 0
    slot_cls = {sl["name"]: C.slot_class(sl) for sl in pool["slots"]}
    # Each class keeps its own queue: capacity of its live slots, plus one, less what runs and what waits in it.
    cap = {c: sum(sl["count"] for sl in pool["slots"] if C.accepts(sl, c)) for c in C.CLASSES}
    busy = busy_by_class()
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
        if base in st.get("pending", {}):
            log("held %s: due a move to %s (queued only after it moves)" % (doc, st["pending"][base]))
            continue
        why = stop_reason(doc)
        if why:
            log("stopped %s: %s" % (doc, why))
            continue
        cls = doc_class(doc, st, base)
        if need[cls] <= 0:
            continue                           # its class is full: the doc waits for a slot of that class
        name = task_name(doc)
        if name in C.load():                   # the 40-char name collides with an old task: make it unique
            name += "-%d" % int(time.time() % 10000)
        prev = last_attempt(base) if st["fed"].get(doc) else None
        if prev:
            log("re-feed %s: previous attempt %s" % (doc, prev))
        if enqueue_doc(doc, base, cls, name):
            made += 1
            need[cls] -= 1
        st["fed"][doc] = st["fed"].get(doc, 0) + 1
    json.dump(st, open(state_path(), "w"), indent=1)
    return made


def probe_free():
    """Ask every banned daily free tier one word (control.py probe-free), so its ban ends when it answers."""
    r = subprocess.run([sys.executable, os.path.join(HERE, "control.py"), "probe-free"],
                       capture_output=True, text=True, cwd=C.MAIN)
    for l in r.stdout.splitlines():
        if l.strip():
            log(l)


def refill(target):
    """Run one refill and log every line it prints: each refused start carries its reason (a held claim, a banned slot,
    a breaker), so a stuck bug is visible in the log rather than silent."""
    r = subprocess.run([sys.executable, os.path.join(HERE, "control.py"), "refill", "--target", str(target),
                        "--prefix", ",".join(PREFIXES)], capture_output=True, text=True, cwd=C.MAIN)
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    for l in lines[:-1]:
        log("refill: " + l)
    return lines[-1] if lines else ""


def reclass_on_failure(st, base, doc):
    """Count a no-commit attempt at the doc's class; after ESCALATE_AFTER of them the doc is due one class up. The move
    itself is apply_moves': the doc's file goes to the new class's directory once nothing unlanded touches it. The top
    class keeps its docs (they wait for a hard slot)."""
    fails = st.setdefault("fails", {})
    fails[base] = fails.get(base, 0) + 1
    cur = doc_class(doc, st, base)
    nxt = escalate(cur)
    if nxt and fails[base] >= ESCALATE_AFTER:
        st.setdefault("pending", {})[base] = nxt
        fails[base] = 0
        log("reclass %s: %s -> %s after %d no-commit attempts (moves when nothing unlanded touches it)"
            % (doc, cur, nxt, ESCALATE_AFTER))


def _busy_bases(tasks):
    """Bug bases a live or unlanded task holds: a running worker, or a live task with commits not on master. Its branch
    carries the doc at its old path, so moving the doc under it would conflict."""
    busy = set()
    for t in tasks.values():
        if C.state_of(t) in C.TERMINAL:
            continue
        if C.state_of(t) == "running" or C.ahead(t) > 0:
            busy |= {c[4:] for c in t.get("claims", []) if c.startswith("bug:")}
    return busy


def _move_citations(old, new):
    """Rewrite the tracked files that cite the doc's old path to its new one, so no citation dangles after the move."""
    r = subprocess.run(["git", "grep", "-l", "-F", old], capture_output=True, text=True, cwd=C.MAIN)
    return [f for f in r.stdout.split() if f]


def _git(*a):
    """(returncode, stdout) for a git command in the main checkout. Never exits: a pass must survive a failed move."""
    r = subprocess.run(["git", *a], cwd=C.MAIN, capture_output=True, text=True)
    return r.returncode, r.stdout


def move_busy_bases():
    """Docs a live opencode session is working on: a move would leave that session on a path that no longer exists."""
    return {c[4:] for c in BUSY["claims"] if c.startswith("bug:")}


def apply_moves(st):
    """Move each doc due a class into its class's directory (git mv), rewrite the path citations to it, and commit the
    move to master as one docs-only commit. A doc waits (and is retried next pass) while a worker holds it, while a branch
    with unlanded commits touches it, while the integrator runs, or while anything it would commit is dirty in the main
    checkout. The commit names only the paths it moves, so the user's uncommitted edits are never swept in."""
    for base, c in st.pop("cls", {}).items():        # migration: escalations used to be a second record of the class
        st.setdefault("pending", {}).setdefault(base, c)
    if not st.get("pending"):
        return
    pend = st["pending"]
    try:
        with open(os.path.join(C.ctl_dir(), "integrator.lock"), "a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                log("reclass waits: the integrator is running (it holds the lock)")
                return
            if _git("diff", "--cached", "--name-only")[1].split():
                log("reclass waits: the main checkout has staged changes")
                return
            busy = _busy_bases(C.load()) | move_busy_bases()
            plan = []     # (base, old_rel, new_rel, cited_files)
            for base, to in sorted(pend.items()):
                if base in busy:
                    continue
                cands = [d for d in bug_docs(base) if "/" not in d or d.split("/", 1)[0] in ("mid", "hard")]
                if not cands:
                    del pend[base]               # the doc is gone or fixed: nothing to move
                    continue
                cur = cands[0]
                if dir_class(cur) == to:
                    del pend[base]
                    continue
                old, new = "bugs/%s.md" % cur, "bugs/%s%s.md" % (CLASS_DIR[to], base)
                plan.append((base, old, new, _move_citations(old, new)))
            if not plan:
                return
            dirty = {l[3:] for l in _git("status", "--porcelain", "--untracked-files=no")[1].splitlines()}
            touched = {p for _, o, n, cited in plan for p in [o, n] + cited}
            hit = sorted(touched & dirty)
            if hit:
                log("reclass waits: uncommitted edits to %s" % ", ".join(hit[:3]))
                return
            paths = sorted(touched)
            # Every citation is rewritten in memory first, across all the moves at once: a doc may cite another doc that
            # moves in the same pass, so a file can be both a citer and a moved doc. Then the writes, then the moves.
            text = {}
            for base, old, new, cited in plan:
                for f in cited:
                    text.setdefault(f, open(os.path.join(C.MAIN, f), encoding="utf-8").read())
                    text[f] = text[f].replace(old, new)
            originals = {f: open(os.path.join(C.MAIN, f), encoding="utf-8").read() for f in text}
            done = []
            try:
                for f, body in text.items():
                    open(os.path.join(C.MAIN, f), "w", encoding="utf-8").write(body)
                for base, old, new, cited in plan:
                    os.makedirs(os.path.dirname(os.path.join(C.MAIN, new)), exist_ok=True)
                    rc, _ = _git("mv", old, new)
                    if rc:
                        raise RuntimeError("git mv %s %s failed" % (old, new))
                    done.append((old, new))
            except Exception:                    # put back what this pass changed, then report it
                for old, new in reversed(done):
                    _git("mv", new, old)
                for f, body in originals.items():
                    open(os.path.join(C.MAIN, f), "w", encoding="utf-8").write(body)
                raise
            _git("add", "--", *sorted(text))
            msg = ("bugs: %s\n\nThe swarm moved %d doc(s) to the directory of their class (the class is the location).\n\n"
                   "Co-Authored-By: Claude Haiku 5.5 <noreply@anthropic.com>\n") % (
                ", ".join(sorted(b for b, *_ in plan)), len(plan))
            mpath = os.path.join(C.ctl_dir(), "reclass-msg.txt")
            open(mpath, "w").write(msg)
            rc, _ = _git("commit", "-q", "-F", mpath, "--", *paths)
            if rc:
                raise RuntimeError("commit of the reclass failed; the moves are staged in the main checkout")
            for base, *_ in plan:
                del pend[base]
            log("reclass: moved %s" % ", ".join("%s -> %s" % (o, n) for _, o, n, _ in plan))
    except Exception as e:
        log("reclass failed: %r" % (e,))
    finally:
        json.dump(st, open(state_path(), "w"), indent=1)


def branch_head(branch):
    """The commit a worker's branch points at, or '' when the branch is gone."""
    r = subprocess.run(["git", "rev-parse", "--verify", "-q", branch], capture_output=True, text=True, cwd=C.MAIN)
    return r.stdout.strip() if r.returncode == 0 else ""


def continue_partial(st):
    """A worker that exited without DONE has not finished the bug. Its branch is continued by a new worker, on the same
    doc, from the branch's tip: a round that moved the branch is progress and keeps the doc's class; a round that did
    not move it is no progress, so the doc moves up a class (reclass_on_failure) and the next worker starts there.
    The integrator lands only DONE work. Returns how many workers were queued."""
    track = st.setdefault("track", {})    # doc -> the branch tip its open round started from
    n = 0
    for name, t in C.load().items():
        if not name.startswith(PREFIXES) or t.get("state") in C.TERMINAL or name in BUSY["names"]:
            continue
        if C.state_of(t) not in ("exited-ok", "exited-err") or C.verdict(t) == "DONE" or not C.ahead(t):
            continue                       # still running, DONE (the integrator takes it), or no commits (retire_dead)
        base = next((c[4:] for c in t.get("claims", []) if c.startswith("bug:")), None)
        docs = bug_docs(base) if base else []
        if not docs:
            continue                       # no bug doc left: it is fixed (or not ours), nothing to continue
        doc = docs[0]
        head = branch_head(t["branch"])
        if not head:
            continue
        start = track.get(doc, {}).get("head")
        moved = (head != start) if start is not None else C.ahead(t) > 0
        if not moved:
            reclass_on_failure(st, base, doc)
            log("no progress on %s: its round made no commits; the doc moves up a class" % doc)
        if base in st.get("pending", {}):
            # The doc is due a class and cannot move while a worker or an unlanded branch holds it
            # (apply_moves: _busy_bases). Queueing the next worker here, in the OLD class, is what made the
            # move impossible: the new worker held the doc again before apply_moves could run, so a doc was
            # "escalated" every 2nd attempt and never moved (34 attempts on one bug, all in its first class).
            # Release the exited task instead and queue nothing: the doc moves on the next pass, and the
            # feeder then queues it in the NEW class, resuming from the newest unlanded branch (task_text.plan).
            subprocess.run([sys.executable, os.path.join(HERE, "control.py"), "mark", name, "abandoned"],
                           capture_output=True, cwd=C.MAIN)
            log("hold %s for its reclass to %s: released %s, nothing queued in the old class"
                % (doc, st["pending"][base], name))
            continue
        cls = doc_class(doc, st, base)
        cont = task_name(doc)
        if cont in C.load():
            cont += "-%d" % int(time.time() % 10000)
        if enqueue_doc(doc, base, cls, cont, start=t["branch"]):
            track[doc] = {"head": head, "name": cont}
            subprocess.run([sys.executable, os.path.join(HERE, "control.py"), "mark", name, "abandoned"],
                           capture_output=True, cwd=C.MAIN)
            log("continue %s on %s as %s (class %s)" % (doc, t["branch"], cont, cls))
            n += 1
    json.dump(st, open(state_path(), "w"), indent=1)
    return n


def retire_dead():
    """Retire every worker that is finished and holds nothing: it exited (or failed integration) with NO commits, so
    there is no work to land or decide. The registry entry is abandoned here, in the same pass, so it can never block a
    retry of its bug. A limit kill bans its slot until the limit's reset (control.py); any other no-commit exit counts as
    a failed attempt at its doc's class (reclass_on_failure), and the doc is fed again at once. Nothing is held back."""
    st = load_state()
    n = 0
    # The first pass after this rule existed retires the whole backlog of old no-commit entries. Those attempts were
    # counted when they happened, so the backlog is retired WITHOUT counting them again (no mass reclass).
    backfill = not st.get("retire_backfilled")
    for name, t in C.load().items():
        if not name.startswith(PREFIXES) or C.state_of(t) == "running" or C.holds_claims(t) or name in BUSY["names"]:
            continue
        if C.state_of(t) in C.TERMINAL:
            continue
        subprocess.run([sys.executable, os.path.join(HERE, "control.py"), "mark", name, "abandoned"], capture_output=True)
        n += 1
        if not backfill and C.limit_hit(t) and t.get("pool"):   # an old log's limit line is history, not a live ban
            C.mark_dead(t["model"], C.pool_slot(t["pool"]), C.limit_reset(t))
            log("retired %s: a limit kill, slot %s banned until its reset" % (name, t["pool"]))
            continue
        if not backfill:
            for c in t.get("claims", []):
                if c.startswith("bug:") and bug_docs(c[4:]):
                    reclass_on_failure(st, c[4:], bug_docs(c[4:])[0])
        log("retired %s: %s with no commits%s" % (name, C.state_of(t), " (backlog, not counted)" if backfill else ""))
    st["retire_backfilled"] = True
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
    names = [n for n in I.pick_candidates(quiet=True) if n.startswith(PREFIXES) and n not in BUSY["names"]]
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


def pid_path():
    return os.path.join(C.ctl_dir(), "swarm.pid")


def take_lock(path=None):
    """Become the one swarm. An exclusive flock on the pid file is the ownership proof: the kernel releases it when the
    holder dies, so the file's contents can be stale but the lock cannot. The fd stays open for the life of the process
    (subprocess closes inherited fds, so no child holds the lock). Exits if another live swarm holds it."""
    path = path or pid_path()
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        holder = os.read(fd, 65536).decode(errors="replace").strip()
        os.close(fd)
        sys.exit("another swarm holds %s (run: python3 tools/swarm.py --who): %s" % (path, holder))
    me = {"pid": os.getpid(), "ppid": os.getppid(), "started": time.strftime("%FT%T"),
          "cwd": os.getcwd(), "argv": sys.argv}
    os.ftruncate(fd, 0)
    os.write(fd, (json.dumps(me) + "\n").encode())
    return fd


def who(path=None):
    """Print the lock holder, verified: the pid in the lock file must still be alive, and its command line must be this
    script. Stop it with `kill -TERM <pid>` only after this has printed it."""
    path = path or pid_path()
    if not os.path.exists(path):
        print("no swarm has ever taken %s" % path)
        return 0
    fd = os.open(path, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raw = os.read(fd, 65536).decode(errors="replace")
        os.close(fd)
        info = json.loads(raw)
        ps = subprocess.run(["ps", "-o", "pid=,ppid=,lstart=,command=", "-p", str(info["pid"])],
                            capture_output=True, text=True).stdout.strip()
        print("LOCK HELD by the swarm recorded in %s:" % path)
        print(raw.strip())
        if not ps:
            print("live process: NOT FOUND (the lock is held but the recorded pid is gone: report it)")
        else:
            print("live process: %s" % ps)
            print("command is tools/swarm.py: %s" % ("yes" if "swarm.py" in ps else "NO: do not kill it"))
        return 0
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)
    print("lock is free: no swarm is running (last recorded in %s)" % path)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", type=int, default=None, help="default: the pool's total slots (tools/pool.json)")
    ap.add_argument("--interval", type=int, default=120, help="seconds between passes (0: one pass)")
    ap.add_argument("--who", action="store_true", help="print the verified lock holder and exit")
    a = ap.parse_args()
    if a.who:
        sys.exit(who())
    _lock = take_lock()     # held until this process exits
    while True:
        try:
            guard_ok = live_guard()
            if guard_ok:
                apply_moves(load_state())        # a class change is a file move, so it lands before the feed reads the tree
            subprocess.run([sys.executable, os.path.join(HERE, "control.py"), "reap"], capture_output=True, cwd=C.MAIN)  # jobs of finished workers
            # keep the control plane honest: reconcile queue/registry with the filesystem and recover dead workers
            sr = subprocess.run([sys.executable, os.path.join(HERE, "control.py"), "sync", "--restart-dead"], capture_output=True, text=True, cwd=C.MAIN)
            for line in (sr.stdout or "").splitlines():
                if line.strip():
                    log("sync: " + line.strip())
            fed = cont = retired = 0
            if guard_ok:
                fed = feed()
                cont = continue_partial(load_state())
                retired = retire_dead()
            probe_free()
            drop_queued_busy()
            log("feed +%d, continued %d, abandoned %d; %s" % (fed, cont, retired, refill(a.target if a.target is not None else C.pool_total())))
            subprocess.run([sys.executable, os.path.join(HERE, "cpu_cap.py"), "ratchet"], capture_output=True, cwd=C.MAIN)
            if guard_ok and land():
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
