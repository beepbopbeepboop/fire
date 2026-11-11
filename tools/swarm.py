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
import argparse, fcntl, glob, hashlib, json, os, re, subprocess, sys, time, traceback
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

# The code this process is running, and the lock fd that proves it is the one swarm. Both are set in
# main() before the first pass; stale_code() compares the hash to the files now.
_CODE_HASH = None
_LOCK_FD = None
SCRIPT = os.path.abspath(__file__)


def code_hash():
    """Hash of every tools/*.py (name + contents): the code the swarm runs. Cheap (a few dozen small
    files) and content-based, so touching a file without changing it does not count as a change."""
    h = hashlib.sha1()
    for p in sorted(glob.glob(os.path.join(HERE, "*.py"))):
        h.update(os.path.relpath(p, HERE).encode())
        with open(p, "rb") as f:
            h.update(f.read())
    return h.hexdigest()


def stale_code():
    """Re-exec when tools/*.py no longer matches the code this process loaded. Python read the module
    once at start, so a fix landed after that (e2aca65eb, the reclass crash) keeps failing in memory
    every pass until a human restarts the swarm — 157 identical crashes in swarm.out. Re-exec at the
    pass boundary: the pid is unchanged, so the workers the swarm spawned stay its children. The lock
    fd is closed first, or the new image would see its own lock and exit. Never raises."""
    if _CODE_HASH is None or code_hash() == _CODE_HASH:
        return False
    log("tools/*.py changed (%s -> %s); reloading the swarm" % (_CODE_HASH[:8], code_hash()[:8]))
    global _LOCK_FD
    if _LOCK_FD is not None:
        try:
            os.close(_LOCK_FD)
        except OSError:
            pass
        _LOCK_FD = None
    try:
        os.execv(sys.executable, [sys.executable, SCRIPT] + sys.argv[1:])
    except Exception as e:                       # exec failed: keep the old code, try again next pass
        log("reload failed: %r; keeping the code this process loaded" % (e,))
    return False


def live_guard():
    """Refresh BUSY from the opencode sessions. Returns False when the listing cannot be read: the pass then changes
    nothing that depends on knowing what is live (no feed, continue, retire, land)."""
    try:
        dirs = C.live_session_dirs()
    except (RuntimeError, OSError, ValueError) as e:
        # fail closed: with no listing, "nothing is live" is unknown, and feeding or landing on that guess is how a
        # live worker gets a second one on its doc (2026-11-03). The pass does its bookkeeping and nothing else.
        log("guard: %s; session listing unreadable, this pass feeds and lands nothing" % e)
        BUSY["names"], BUSY["claims"] = set(), set()
        return False
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
    slot that also takes another class does not hide that class's load. Stale registry entries (a dead pid still
    marked running) are not counted, or a dead worker would pin its class at capacity forever."""
    pool = C.load_pool()
    slot_cls = {sl["name"]: C.slot_class(sl) for sl in pool["slots"]}
    busy = {c: 0 for c in C.CLASSES}
    tasks = C.load()
    live = C.live_names(tasks) or frozenset()        # the same working rule as control.running_by_slot
    for name, t in tasks.items():
        if C._working(name, t) and (C.alive(t.get("pid")) or name in live):
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


def skip_hits(base, skips):
    """The pool's skip patterns that a doc's base name matches (empty when it is a real bug doc). The one test every
    path that picks docs uses: the feed, the replan, and the explanation of a wedged doc."""
    return [x for x in skips if base.startswith(x) or x in base]


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
    """Keep every pool slot supplied: enqueue queued tasks until the total running + queued reaches the pool's total
    slot count (plus one buffer), drawn from the pool's `feed` globs (skipping the pool's `skip` prefixes, and any doc
    a live task or external claim holds). A doc's class decides which slots may run it (pick_slot), not whether it may
    be queued: we do not limit by class, only by each slot's own count."""
    pool = C.load_pool()
    skips = pool.get("skip", [])
    st = load_state()
    held, made = held_claims(), 0
    busy_slot = C.running_by_slot()
    # free slots, not total queued: queued tasks whose slots are full or whose class has no
    # slot must not block a free slot from getting work.
    need_total = sum(max(0, sl["count"] - busy_slot.get(sl["name"], 0)) for sl in pool["slots"])
    paths = sorted(set(p for g in pool["feed"] for p in glob.glob(os.path.join(C.MAIN, g))))
    for p in paths:
        if need_total <= 0:
            log("feed: no free slot anywhere in the pool; %d doc(s) not considered this pass" % len(paths))
            break
        rel = os.path.relpath(p, os.path.join(C.MAIN, "bugs"))
        doc = rel[:-3] if rel.endswith(".md") else rel
        base = os.path.basename(doc)
        reason = block_reason(doc, st, pool, busy_slot, held)
        if reason:
            continue                       # the reason is a view (swarm.py --feed / --why), not a line per pass
        cls = doc_class(doc, st, base)
        name = task_name(doc)
        if name in C.load():                   # the 40-char name collides with an old task: make it unique
            log("renamed %s: %s is already in the registry" % (doc, name))
            name += "-%d" % int(time.time() % 10000)
        prev = last_attempt(base) if st["fed"].get(doc) else None
        if prev:
            log("re-feed %s: previous attempt %s" % (doc, prev))
        if not enqueue_doc(doc, base, cls, name):
            log("FAILED to queue %s (class %s)" % (doc, cls))
            continue
        made += 1
        need_total -= 1
        sl = C.pick_slot({"pool": None, "cls": cls}, busy_slot)
        if sl:
            busy_slot[sl["name"]] = busy_slot.get(sl["name"], 0) + 1
        else:
            log("queued %s but no slot accepts class %s" % (doc, cls))
        st["fed"][doc] = st["fed"].get(doc, 0) + 1
    json.dump(st, open(state_path(), "w"), indent=1)
    return made


def deleted_on_a_branch(base):
    """Whether some branch has deleted this doc: the one git query the DONE ratchet needs, run before anything else."""
    r = subprocess.run(["git", "log", "--all", "--diff-filter=D", "--oneline", "--",
                        "bugs/%s.md" % base, "bugs/mid/%s.md" % base, "bugs/hard/%s.md" % base],
                       capture_output=True, text=True, cwd=C.MAIN)
    return bool(r.stdout.strip())


def landable(base):
    """The tasks whose landing would resolve BASE: a DONE verdict, commits master lacks, and not
    already handed to a fixer. Cheap on purpose — only the tasks that name this doc, so `why` stays
    fast where a full pick_candidates sweep (a `git status` per worktree) would not be."""
    claim = "bug:" + base
    return [n for n, t in C.load().items()
            if claim in t.get("claims", []) and C.verdict(t) == "DONE"
            and C.ahead(t) > 0 and not t.get("fixer")]


def claim_held(base):
    """Whether BUG:BASE's claim is held, and by what. Cheap: only the tasks that name this doc pay
    for holds_claims (which runs `git rev-list` per task), not the whole registry."""
    claim = "bug:" + base
    if claim in BUSY["claims"]:
        return "a live opencode session is driving its tree"
    for n, t in C.load().items():
        if claim in t.get("claims", []) and C.holds_claims(t):
            return "task %s (%s)" % (n, C.state_of(t))
    for f in os.listdir(C.qdir()):
        if f.endswith(".json"):
            it = json.load(open(os.path.join(C.qdir(), f)))
            if claim in it.get("claims", []):
                return "queued task %s" % it.get("name", f)
    for n, e in C.external().items():
        if claim in e.get("claims", []):
            return "external claim %s" % n
    return None


def block_reason(doc, st, pool, busy, held):
    """The first feed condition that keeps DOC from being queued now, or None when it may be queued. The one verdict
    the feed and the views share, so a view can never disagree with what the feed does. `held` is the set of
    'bug:BASE' claims held now (held_claims()); `busy` is running_by_slot()."""
    base = os.path.basename(doc)
    cls = doc_class(doc, st, base)
    if skip_hits(base, pool.get("skip", [])):
        return "skip pattern: its name matches %s from the pool's skip list" % skip_hits(base, pool.get("skip", []))
    if "bug:" + base in held:
        return "held: a live task or an external claim holds it"
    np = T.no_progress_reason(base)
    if np:
        return np
    if deleted_on_a_branch(base):          # cheap git check first: landable() reads the registry
        done = landable(base)
        if done:
            return "DONE ratchet: a branch deleted it; %d DONE task(s) will land it (e.g. %s)" % (len(done), done[0])
    if base in st.get("pending", {}):
        return "held: due a reclass to %s (queued only after the doc moves)" % st["pending"][base]
    stop = stop_reason(doc)
    if stop:
        return "STOP line in the doc: %s" % stop
    split = split_reason(doc)
    if split:
        return "SPLIT: decomposed into parts that carry the work (%s)" % split
    if not any(C.accepts(sl, cls) and C.slot_free(sl, busy) for sl in pool["slots"]):
        return "no free %s slot (%s)" % (cls, ", ".join(
            "%s count %d busy %d%s" % (sl["name"], sl["count"], busy.get(sl["name"], 0),
                                       ", banned" if sl["model"] in C.dead_models() else "")
            for sl in pool["slots"] if C.accepts(sl, cls)) or "no slot takes class " + cls)
    return None


def _doc_rel(doc):
    """A bugs/ path, or a path relative to bugs/, with or without .md, as the bare doc name the feed uses."""
    if doc.startswith("bugs/"):
        doc = doc[5:]
    return doc[:-3] if doc.endswith(".md") else doc


def why(doc):
    """Why DOC is not being fed right now, with the detail the feed does not compute per pass (which task holds it, and
    the in-flight state). Answers 'this bug is wedged and nothing says why' without waiting for a pass."""
    pool = C.load_pool()
    st = load_state()
    doc = _doc_rel(doc)
    base = os.path.basename(doc)
    reason = block_reason(doc, st, pool, C.running_by_slot(), held_claims())
    if reason and reason.startswith("held:"):
        reason = "held: %s" % (claim_held(base) or "a live task or an external claim holds it")
    if reason:
        return reason
    name = task_name(doc)
    if name in C.load():
        return "in flight: task %s is %s" % (name, C.state_of(C.load()[name]))
    return "would be fed on the next pass"


def feed_view():
    """Every doc the feed considers, with the reason it waits or 'eligible', grouped by reason. Computed now, from the
    same block_reason the feed uses; nothing is logged for it."""
    pool = C.load_pool()
    st, busy, held = load_state(), C.running_by_slot(), held_claims()
    groups = {}
    for p in sorted(set(x for g in pool["feed"] for x in glob.glob(os.path.join(C.MAIN, g)))):
        doc = _doc_rel(os.path.relpath(p, os.path.join(C.MAIN, "bugs")))
        reason = block_reason(doc, st, pool, busy, held) or "eligible"
        groups.setdefault(reason.split(" (")[0].split(":")[0], []).append(doc)
    for key in sorted(groups, key=lambda k: (k == "eligible", -len(groups[k]))):
        print("%5d  %s" % (len(groups[key]), key))
        if key == "eligible" or "-v" in sys.argv:
            for d in groups[key][:20]:
                print("        %s" % d)
    return 0


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
        log(l if l.startswith("refill:") else "refill: " + l)   # control.py labels its own lines
    return lines[-1] if lines else ""


SPLIT = re.compile(r"^SPLIT:[ \t]*(.+?)[ \t]*$", re.M)   # a doc decomposed into parts by a replan


def split_reason(doc):
    """The parts listed in the doc's `SPLIT:` line, or None. A SPLIT doc's parts carry the work, so
    the feeder leaves the original alone (it stays at its class — the ladder is one-way)."""
    try:
        with open(os.path.join(C.MAIN, doc_path(doc)), encoding="utf-8") as f:
            m = SPLIT.search(f.read())
    except OSError:
        return None
    return m.group(1) if m else None


def unserved_classes(pool=None):
    """Classes the pool documents but cannot serve: no slot of that class has any count.

    A doc at such a class can never be worked, and the escalation ladder has no way out of it —
    2026-11-10: `hard` is documented as "bugs/hard/*.md (Opus 5.5)" while opus has count 0 and has
    never run a task, so 25 hard docs sat there with no path forward."""
    pool = pool or C.load_pool()
    out = {}
    for cls in C.CLASSES:
        slots = [sl for sl in pool["slots"] if C.accepts(sl, cls)]
        if not any(sl.get("count", 0) > 0 for sl in slots):
            out[cls] = [sl["name"] for sl in slots]
    return out


REPLAN_TASK = """You REPLAN a bug doc. You do NOT fix the bug.

Read %(doc)s. It sits at a class the pool cannot serve (%(cls)s has no slot: %(slots)s), so it can
never be worked as written. Decompose it instead:

1. Decide the parts. Each part is a self-contained piece of work with its own acceptance check,
   small enough for a class the pool CAN serve: %(servable)s. Never file a part at %(cls)s.
2. File each part as a new doc named "<base>-part1", "<base>-part2", ... under bugs/ or bugs/mid/
   — the highest class you can argue it needs, within %(servable)s. Commit each new doc.
3. Add one line at the top of the ORIGINAL doc: SPLIT: <base>-part1, <base>-part2, ...
   Commit it. The original stays at its class; its parts carry the work.
4. Finish with the REPORT block and CONTROL-STATUS: DONE.

Do not try to fix the bug yourself. Do not delete the original doc."""


def replan_unserved():
    """Queue a replan for every doc at a class the pool cannot serve. Returns how many.

    This is the only way such a doc can move without breaking the ladder: an easy worker decomposes
    it into parts filed at classes that DO have capacity, and the original is marked SPLIT."""
    pool = C.load_pool()
    unserved = unserved_classes(pool)
    if not unserved:
        return 0
    servable = [c for c in C.CLASSES if c not in unserved]
    made = 0
    for cls, slots in sorted(unserved.items()):
        for path in sorted(glob.glob(os.path.join(C.MAIN, "bugs", cls, "*.md"))):
            base = os.path.basename(path)[:-3]
            if skip_hits(base, pool.get("skip", [])):
                continue                  # an index or README is not a bug doc: nothing to split (2026-11-10: a
                                          # replan of bugs/hard/README.md was queued and ran on qwen)
            name = "fix-replan-" + re.sub(r"[^a-z0-9]+", "-", base.lower())[:40].rstrip("-")
            qpath = os.path.join(C.qdir(), name + ".json")
            if os.path.exists(qpath):
                # self-heal: sync used to rewrite a queued task's class from its doc, which parked
                # every replan at the unserved class it was meant to escape
                it = json.load(open(qpath))
                if it.get("cls") != "easy":
                    old = it.get("cls")
                    it["cls"] = "easy"
                    with open(qpath, "w") as f:
                        json.dump(it, f, indent=1)
                    log("replan %s: corrected its queued class %s -> easy" % (name, old))
                continue
            if name in C.load() or split_reason("%s/%s" % (cls, base)) or claim_held(base):
                continue
            text = REPLAN_TASK % {"doc": "bugs/%s/%s.md" % (cls, base), "cls": cls,
                                  "slots": ", ".join(slots), "servable": ", ".join(servable)}
            subprocess.run([sys.executable, os.path.join(HERE, "control.py"), "enqueue", name,
                            "--claim", "bug:" + base, "--task", text, "--cls", "easy"],
                           capture_output=True, text=True, cwd=C.MAIN)
            log("replan bugs/%s/%s.md: class %s has no slot (%s); queued %s to split it into parts at %s"
                % (cls, base, cls, ", ".join(slots), name, ", ".join(servable)))
            made += 1
    return made


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
            busy_bases = {c[4:] for t in C.load().values() if C.state_of(t) == "running"
                          for c in t.get("claims", []) if c.startswith("bug:")}
            busy = busy_bases | move_busy_bases()
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
        log("reclass failed: %r\n%s" % (e, traceback.format_exc()))
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


LAND_BATCH = 8   # branches landed per pass: a larger batch merges them all into one gate run and one conflict storm


def land():
    names = [n for n in I.pick_candidates(quiet=True) if n.startswith(PREFIXES) and n not in BUSY["names"]]
    names = fresh_first(names, C.load())
    held = names[LAND_BATCH:]
    names = names[:LAND_BATCH]
    if held:
        log("land: %d more finished branch(es) waiting behind the batch cap of %d: %s"
            % (len(held), LAND_BATCH, ", ".join(held[:3]) + (" ..." if len(held) > 3 else "")))
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
        log("red: %s breaks the gate (%s); it is held and bugs/gate-<job>.md is the work, the rest of the batch continues"
            % (culprit, " ".join(failing) or "jobs unknown"))
        I.gate_doc(culprit, tasks[culprit], failing)
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
    ap.add_argument("--log-file", default=os.path.join(C.ctl_dir(), "swarm.out"), help="file to write pass log to (default: .git/control/swarm.out)")
    ap.add_argument("--who", action="store_true", help="print the verified lock holder and exit")
    ap.add_argument("--why", metavar="DOC", default=None,
                    help="print why a bug doc is not being fed (a bugs/ path or a base name), and exit")
    ap.add_argument("--feed", action="store_true", help="show, grouped by reason, every doc the feed considers and why it waits")
    a = ap.parse_args()
    if a.feed:
        sys.exit(feed_view())
    if a.who:
        sys.exit(who())
    if a.why:
        sys.exit(why(a.why))
    # redirect output to the log file so it is captured without a shell redirect
    if a.log_file:
        os.makedirs(os.path.dirname(os.path.abspath(a.log_file)), exist_ok=True)
        _lf = open(a.log_file, "a", buffering=1)
        sys.stdout = _lf
        sys.stderr = _lf
    global _CODE_HASH, _LOCK_FD
    _LOCK_FD = take_lock()     # held until this process exits
    _CODE_HASH = code_hash()   # the code this process runs; a change means re-exec (stale_code)
    while True:
        try:
            stale_code()            # a landed tools/*.py fix must reach this process, not wait for a restart
            guard_ok = live_guard()
            if guard_ok:
                apply_moves(load_state())        # a class change is a file move, so it lands before the feed reads the tree
            subprocess.run([sys.executable, os.path.join(HERE, "control.py"), "reap"], capture_output=True, cwd=C.MAIN)  # jobs of finished workers
            # keep the control plane honest: reconcile queue/registry with the filesystem and recover dead workers
            sr = subprocess.run([sys.executable, os.path.join(HERE, "control.py"), "sync", "--restart-dead"], capture_output=True, text=True, cwd=C.MAIN)
            for line in (sr.stdout or "").splitlines():
                if line.strip():
                    text = line.strip()
                    log(text if text.startswith("sync:") else "sync: " + text)   # control.py labels its own lines
            # safe, conservative cleanup every pass: only removes merged/clean/idle trees with no outside claim
            cr = subprocess.run([sys.executable, os.path.join(HERE, "control.py"), "cleanup"], capture_output=True, text=True, cwd=C.MAIN)
            for line in (cr.stdout or "").splitlines():
                if line.strip() and ("removed" in line.lower() or "deleted" in line.lower() or "worktree" in line.lower()):
                    log("cleanup: " + line.strip())
            fed = cont = retired = 0
            if guard_ok:
                unserved = unserved_classes()
                if unserved:
                    log("config: class(es) with docs but no slot: %s" % ", ".join(
                        "%s (%s count 0)" % (c, "/".join(s)) for c, s in sorted(unserved.items())))
                replanned = replan_unserved()
                if replanned:
                    log("replan: queued %d replan task(s) for docs at an unserved class" % replanned)
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
