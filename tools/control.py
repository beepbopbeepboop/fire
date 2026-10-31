#!/usr/bin/env python3
"""Task controller: dispatch work items to opencode workers, one git worktree each.

    control.py spawn NAME --claim KEY [--claim KEY ...] (--task TEXT | --task-file F)
    control.py status [--all] [-v] # one line per task that still matters (finished-and-gone ones are hidden; --all lists them)
    control.py prune [--dry-run]   # drop finished-and-gone entries (terminal, no worktree, nothing outside master) from the registry
    control.py claims              # every live claim (workers read this before starting)
    control.py claim NAME --claim KEY ... [--who WHO] [--pid P | --hours H]   # register work done OUTSIDE control (a Claude
                                   # agent, a hand-run opencode, a local model); exits 1 if a live claim conflicts
    control.py release NAME        # drop such a claim
    control.py mark NAME STATE     # set a state by hand (abandoned, integrated, ...)
    control.py report              # regenerate the task table inside CONTROL.html
    control.py guard [--limit-gb 64]   # watchdog: kill any process in our trees past a memory limit
    control.py enqueue NAME --claim K (--task T|--task-file F) [--needs TASK...]   # queue work
    control.py refill [--target 8] # start queued tasks (deps integrated, claims free) up to N running
    control.py priority [NAME...]  # set/show the order finished branches are integrated in (most important first)
    control.py queue               # what is waiting
    control.py restart NAME        # snapshot, stop and continue a worker as NAME-rN from its own branch
    control.py unstick [--idle-min 25]   # restart workers that are stalled (idle log AND no CPU in their tree)
    control.py cleanup [--dry-run] # remove worktrees whose branch is merged, clean, and not running, then delete the merged work/* branches (--no-branches keeps them), then prunes finished registry entries (--no-prune keeps them)
    control.py ps                  # our live workers (not the user's own opencode sessions)
    control.py reap [--dry-run]    # kill leftovers (lean, gcc, ...) in finished workers' trees
    control.py digest NAME         # verdict, commits, diffstat, the worker's REPORT block
    control.py log NAME [-n N]     # tail of a worker's work.log

Layout
  ../work-N/            worktree N on branch work/<name>, created from master
  ../work-N/work.log    EVERYTHING the worker printed (stdout+stderr), append-only
  ../work-N/exitcode    written by the launcher wrapper when the worker exits
  <common-git-dir>/control/tasks.json   the registry (shared by all worktrees)

Sessions that work from a checkout OTHER than the one the fleet runs in (a clone, a hand-run
agent) still reach the fleet's registry: the default is the fleet checkout's .git/control,
overridable with CONTROL_CTL_DIR=<abs path to that checkout's .git/control>.

Claims are how two workers are kept off the same problem. A claim is a string:
`module:os`, `bug:CODEGEN_foo`, or a repo path (`tools/formal_sweep.py`). Two
claims conflict when they are equal or one is a path-prefix of the other, and
`spawn` refuses to start a task whose claims conflict with any task that has
not reached a terminal state. Claims are released by `mark NAME integrated|abandoned|superseded`. A fix for
a task that failed integration is `spawn --base work/<failed> ...` after marking
the failed task `superseded` (the fixer inherits its claims and its commits).

Workers are told (see tools/control_prompt.md) NOT to run the quality gate: that
is the integrator's job (tools/integrate.py), which merges finished branches
together and gates them once.
"""
import argparse, fcntl, json, os, re, shutil, subprocess, sys, time
from contextlib import contextmanager

MAIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARENT = os.path.dirname(MAIN)
POOL_FILE = os.environ.get("CONTROL_POOL_FILE", os.path.join(MAIN, "tools", "pool.json"))


def load_pool():
    """The worker pool (tools/pool.json): named slots, each pinned to ONE model with a fixed count. There is no
    fallback between slots: a task belongs to the slot it was queued for and waits there if that slot is full or banned."""
    return json.load(open(POOL_FILE))


def pool_slot(name):
    for sl in load_pool()["slots"]:
        if sl["name"] == name:
            return sl
    sys.exit("no pool slot named %r in %s" % (name, POOL_FILE))


GATES_FILE = os.path.join(MAIN, "tools", "gates.json")


def gates_cfg():
    """tools/gates.json: what a landing must pass, how often the full gate runs, and which gates are OFF for a backlog.
    An OFF gate is a regex over test names; it is skipped by every gate run, and it must name the doc and the worker
    working the backlog (`control.py gate off`), so no gate is ever dropped silently."""
    return json.load(open(GATES_FILE))


def gate_skip_args():
    out = []
    for pat in gates_cfg().get("off", {}):
        out += ["--skip", pat]
    return out


def pool_total():
    return sum(sl["count"] for sl in load_pool()["slots"])
TERMINAL = {"integrated", "abandoned", "superseded"}


def git(*a, cwd=MAIN, check=True):
    r = subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode:
        sys.exit("git %s failed: %s" % (" ".join(a), r.stderr.strip()))
    return r.stdout.strip()


_CTL_WARNED = []


def ctl_dir():
    """Where the shared registry lives.

    The registry is FLEET state, not checkout state. The default is the
    fleet's own registry (the checkout the fleet runs from); the fleet also
    lands here because it IS that checkout. Override with
    CONTROL_CTL_DIR=<abs path to a .git/control> when the fleet runs from
    a different checkout than this default. The warning below covers the
    default itself pointing at a missing/moved registry. (The previous
    default was this checkout's own .git/control, which in a clone is a
    private, empty registry the fleet never reads — exactly the split that
    was hit on 2026-10-25: `control.py claims` in a clone printed nothing
    while four workers were live in the other tree's registry.)"""
    env = os.environ.get("CONTROL_CTL_DIR")
    if env:
        d = os.path.realpath(env)
    else:
        d = os.path.realpath(os.path.expanduser(
            "~/net/chatgpt/claude/mojo-reference/.git/control"))
        if not _CTL_WARNED and not any(os.path.exists(os.path.join(d, f)) for f in ("tasks.json", "external.json", "feed.json")):
            _CTL_WARNED.append(1)
            sys.stderr.write("warning: control registry %s is empty. If the fleet runs from another "
                             "checkout, set CONTROL_CTL_DIR to that checkout's .git/control, or your "
                             "claims will not be seen by its workers.\n" % d)
    os.makedirs(d, exist_ok=True)
    return d


@contextmanager
def registry():
    """Read-modify-write the registry under an exclusive flock."""
    path = os.path.join(ctl_dir(), "tasks.json")
    with open(path + ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        tasks = json.load(open(path)) if os.path.exists(path) else {}
        yield tasks
        tmp = path + ".tmp"
        json.dump(tasks, open(tmp, "w"), indent=1, sort_keys=True)
        os.replace(tmp, path)


def load():
    path = os.path.join(ctl_dir(), "tasks.json")
    return json.load(open(path)) if os.path.exists(path) else {}


def conflicts(a, b):
    pa, pb = a.rstrip("/").split("/"), b.rstrip("/").split("/")
    n = min(len(pa), len(pb))
    return pa[:n] == pb[:n]


def alive(pid):
    if not pid:          # os.kill(0, 0) signals our own process group and "succeeds": pid 0 is never a live worker
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def state_of(t):
    """running / exited-ok / exited-err, unless a hand-set terminal or later state wins."""
    if t.get("state") not in (None, "running", "exited-ok", "exited-err"):
        return t["state"]
    if alive(t.get("pid", 0)):
        return "running"
    ec = os.path.join(t["worktree"], "exitcode")
    if os.path.exists(ec):
        return "exited-ok" if open(ec).read().strip() == "0" else "exited-err"
    return "exited-err"  # gone with no exit code: killed


def verdict(t):
    """The worker's own last word: DONE / PARTIAL / NEEDS-INFO / BLOCKED, or '' if it never said.

    Read from the last `CONTROL-STATUS: X` (or report `STATUS: X`) line of work.log. For NEEDS-INFO
    the worker also prints `QUESTION: ...` lines, which `status -v` shows."""
    lp = os.path.join(t["worktree"], "work.log")
    if not os.path.exists(lp):
        return ""
    txt = re.sub(r"\x1b\[[0-9;]*m", "", open(lp, errors="replace").read())
    m = re.findall(r"^\s*(?:CONTROL-)?STATUS:\s*(DONE|PARTIAL|NEEDS-INFO|BLOCKED)\s*$", txt, re.M | re.I)
    return m[-1].upper() if m else ""


def questions(t):
    lp = os.path.join(t["worktree"], "work.log")
    txt = re.sub(r"\x1b\[[0-9;]*m", "", open(lp, errors="replace").read()) if os.path.exists(lp) else ""
    return re.findall(r"^\s*QUESTION:\s*(.+)$", txt, re.M)


def ahead(t):
    r = subprocess.run(["git", "rev-list", "--count", "master.." + t["branch"]],
                       cwd=MAIN, capture_output=True, text=True)
    return int(r.stdout.strip() or 0) if r.returncode == 0 else 0


def next_slot():
    used = [int(m.group(1)) for d in os.listdir(PARENT) if (m := re.fullmatch(r"work-(\d+)", d))]
    return max(used, default=0) + 1


def cmd_spawn(a):
    """Start a worker. A task runs on a POOL SLOT (tools/pool.json): its model and runner come from the slot, and it
    never moves to another model. `--model` (a bare model, no slot) is for hand-run experiments only."""
    if getattr(a, "pool", None) is None and getattr(a, "model", None) is None:
        a.pool = load_pool()["default_slot"]          # callers that build a Namespace by hand (autointegrate) pass None
    sl = pool_slot(a.pool) if getattr(a, "pool", None) else None
    a.model = sl["model"] if sl else a.model
    kind = sl["kind"] if sl else "opencode"
    task = a.task if a.task is not None else open(a.task_file).read()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", a.name):
        sys.exit("NAME must be lowercase-kebab")
    with registry() as tasks:
        if a.name in tasks:
            sys.exit("task %s already exists" % a.name)
        for other, t in tasks.items():
            if state_of(t) in TERMINAL:
                continue
            for c in a.claim:
                for oc in t["claims"]:
                    if conflicts(c, oc):
                        sys.exit("claim %r conflicts with %r held by task %s" % (c, oc, other))
        ext = external_conflicts(a.claim)
        if ext:
            sys.exit("claim %r conflicts with %r held by external session %s" % (ext[0][1], ext[0][2], ext[0][0]))
        n = next_slot()
        wt, branch = os.path.join(PARENT, "work-%d" % n), "work/" + a.name
        git("worktree", "add", "-b", branch, wt, a.base)
        os.makedirs(os.path.join(wt, ".tmp"), exist_ok=True)
        prompt = open(os.path.join(MAIN, "tools", "control_prompt.md")).read().format(
            name=a.name, worktree=wt, branch=branch, main=MAIN, task=task.strip(),
            claims=", ".join(a.claim), control=os.path.join(MAIN, "tools", "control.py"))
        for src in a.file:  # reference inputs the worker may read, copied inside its sandbox
            shutil.copy(src, os.path.join(wt, ".tmp", os.path.basename(src)))
        open(os.path.join(wt, "TASK.md"), "w").write(prompt)
        instr = "Your complete instructions are in %s/TASK.md. Read it now and follow it exactly." % wt
        if kind == "claude":
            # Claude Code, headless: the paid Claude tokens. Edits and the shell are allowed inside the worker's own
            # worktree (the prompt confines it there); there is no interactive permission prompt to answer.
            cmd = ["claude", "-p", instr, "--model", a.model, "--permission-mode", "acceptEdits",
                   "--allowedTools", "Read Edit Write Grep Glob Bash"]
        else:
            # opencode v2: --model belongs to `run`, there is no --dir (cwd=wt below)
            cmd = ["opencode", "run", "--model", a.model, "--auto", "--title", a.name, instr]
        os.makedirs(os.path.join(wt, ".tmp"), exist_ok=True)
        wrapper = 'export TMPDIR=%s PATH=%s:"$PATH"; ( %s ) >> work.log 2>&1 </dev/null; echo $? > exitcode' % (
            sh(os.path.join(wt, ".tmp")), sh(git_shim_dir()), " ".join(map(sh, cmd)))
        open(os.path.join(wt, "work.log"), "a").write("=== control: spawned %s on %s at %s ===\n" % (
            a.name, a.model, time.strftime("%F %T")))
        p = subprocess.Popen(["sh", "-c", wrapper], cwd=wt, start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # a pipe to the caller must not outlive spawn
        tasks[a.name] = dict(name=a.name, slot=n, worktree=wt, branch=branch, claims=a.claim,
                             model=a.model, pool=a.pool if sl else None, kind=kind, pid=p.pid,
                             started=time.strftime("%F %T"),
                             base=a.base, files=a.file, task=task,   # what `bounce` needs to put it back on the queue
                             state="running", summary=task.strip().splitlines()[0][:200])
    print("spawned %s: %s (pid %d), log %s/work.log" % (a.name, wt, p.pid, wt))


def git_shim_dir():
    """A directory holding a `git` that refuses `git stash`, to be put first on a worker's PATH.

    The stash list is ONE list shared by every worktree of a repository. Workers follow CLAUDE.md's
    "prefer git stash push", then `git stash pop` — which applies whichever stash is on top, quite possibly
    another worker's (2026-09-29: ten workers popped/applied; one restored the controller's own saved stash
    into its tree, and several trees ended up with hunks their worker never wrote). A worker's safe
    alternatives are a patch file in .tmp/ or a WIP commit on its own branch."""
    d = os.path.join(ctl_dir(), "bin")
    os.makedirs(d, exist_ok=True)
    real = subprocess.run(["sh", "-c", "command -v git"], capture_output=True, text=True).stdout.strip()
    p = os.path.join(d, "git")
    open(p, "w").write("""#!/bin/sh
# installed by tools/control.py: `git stash` is shared across worktrees and is refused for workers
for a in "$@"; do
  case "$a" in -*) continue;; stash) echo "git stash is disabled: the stash list is shared by every worker's worktree, so a pop can apply someone else's changes. Save work with 'git diff > .tmp/name.patch' (restore with 'git apply') or commit it on your branch." >&2; exit 1;; *) break;; esac
done
exec %s "$@"
""" % sh(real))
    os.chmod(p, 0o755)
    return d


def sh(s):
    return "'" + s.replace("'", "'\\''") + "'"


def unmerged_branches():
    """Branches under refs/heads/ with commits that are NOT in master, in ONE git call (a per-task
    `rev-list` over hundreds of tasks is what made status take minutes)."""
    out = subprocess.run(["git", "for-each-ref", "--no-merged", "master", "--format=%(refname:short)", "refs/heads/"],
                         capture_output=True, text=True, cwd=MAIN).stdout
    return set(out.split())


def done_and_gone(t, unmerged):
    """A finished task with nothing left to look at: terminal state, no worktree directory, and no commits
    outside master (its branch is merged or deleted). Such an entry holds no claim (terminal claims are
    ignored), no process and no work, so `status` hides it and `prune` may drop it."""
    return (t.get("state") in TERMINAL and not os.path.isdir(t["worktree"])
            and t.get("branch") not in unmerged)


def cmd_status(a):
    reg = load()
    unmerged = unmerged_branches()
    items = sorted(reg.items(), key=lambda kv: kv[1]["slot"])
    shown = [(n, t) for n, t in items if a.all or not done_and_gone(t, unmerged)]

    def row(nt):
        name, t = nt
        st = state_of(t)
        dirty = len(git("status", "--short", cwd=t["worktree"], check=False).splitlines()) \
            if os.path.isdir(t["worktree"]) else -1
        last = ""
        lp = os.path.join(t["worktree"], "work.log")
        if os.path.exists(lp):
            with open(lp, errors="replace") as f:
                lines = [l for l in f.read().splitlines() if l.strip()]
            last = lines[-1][:90] if lines else ""
        v = verdict(t)
        n_ahead = ahead(t) if t.get("branch") in unmerged else 0
        return st, v, n_ahead, dirty, last
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=16) as ex:
        rows = list(ex.map(row, shown))
    for (name, t), (st, v, n_ahead, dirty, last) in zip(shown, rows):
        print("%-20s work-%-3d %-14s %-10s +%d commits, %d dirty | %s" % (name, t["slot"], st, v or "-", n_ahead, dirty, last))
        if a.verbose and v == "NEEDS-INFO":
            for q in questions(t):
                print("      QUESTION: " + q)
    if len(shown) < len(items):
        print("+%d finished tasks hidden (status --all to list)" % (len(items) - len(shown)))


def cmd_prune(a):
    """Drop DONE-AND-GONE entries (see done_and_gone) from the registry so tasks.json stops growing.
    Never touches a task that is running, has a worktree, has commits outside master, or is in a
    non-terminal state."""
    unmerged = unmerged_branches()
    with registry() as tasks:
        gone = [n for n, t in tasks.items() if done_and_gone(t, unmerged) and state_of(t) != "running"]
        if not a.dry_run:
            for n in gone:
                del tasks[n]
        kept = len(tasks) - (len(gone) if a.dry_run else 0)
    print("%s %d finished registry entries; %d kept" % ("would prune" if a.dry_run else "pruned", len(gone), kept))
    return gone


def external_path():
    return os.path.join(ctl_dir(), "external.json")


def external():
    """Claims held by work this controller did not start (a Claude Code agent, a hand-run opencode, a local model):
    {name: {claims, who, pid, until}}. An entry lapses when its pid is gone or its time is up, so a session that dies
    without `release` does not hold a doc forever."""
    try:
        d = json.load(open(external_path()))
    except (OSError, ValueError):
        return {}
    return {n: e for n, e in d.items() if (alive(e["pid"]) if e.get("pid") else e["until"] > time.time())}


def norm_claim(c):
    """A bare doc name, a name with the .md suffix, and a bugs/ path all mean the same `bug:<name>` claim."""
    if ":" in c:
        return c
    m = re.fullmatch(r"(?:bugs/(?:hard/)?)?([A-Za-z0-9_]+?)(?:\.md)?", c)
    return "bug:" + m.group(1) if m else c


def external_conflicts(claims, skip=None):
    return [(n, c, oc) for n, e in external().items() if n != skip for c in claims for oc in e["claims"] if conflicts(c, oc)]


def cmd_claim(a):
    """Register claims for work started outside control, so control's workers (and the feeder) stay off it, and the
    caller learns at once if a control worker or another outside session already holds it. Run it again to renew."""
    claims = [norm_claim(c) for c in a.claim]
    with registry() as tasks:
        bad = [(n, c, oc) for n, t in tasks.items() if state_of(t) not in TERMINAL for c in claims for oc in t["claims"]
               if conflicts(c, oc)] + external_conflicts(claims, skip=a.name)
        if bad:
            for n, c, oc in bad:
                print("CONFLICT: %s is held by %s (%s)" % (c, n, oc))
            sys.exit(1)
        d = external()
        d[a.name] = dict(claims=claims, who=a.who, pid=a.pid, started=time.strftime("%F %T"),
                         until=time.time() + a.hours * 3600)
        json.dump(d, open(external_path(), "w"), indent=1)
    print("claimed for %s: %s (%s)" % (a.name, ", ".join(claims), "while pid %d lives" % a.pid if a.pid else "%g h" % a.hours))


def cmd_release(a):
    with registry():
        d = external()
        d.pop(a.name, None)
        json.dump(d, open(external_path(), "w"), indent=1)
    print("released", a.name)


def cmd_claims(a):
    for name, t in sorted(load().items()):
        if state_of(t) not in TERMINAL:
            print("%-24s %s" % (name, ", ".join(t["claims"])))
    for name, e in sorted(external().items()):
        print("%-24s %s   [external: %s]" % (name, ", ".join(e["claims"]), e.get("who") or "?"))


def cmd_mark(a):
    with registry() as tasks:
        if a.name not in tasks:
            sys.exit("no such task")
        tasks[a.name]["state"] = a.state
    print("%s -> %s" % (a.name, a.state))


def cmd_log(a):
    print(subprocess.run(["tail", "-n", str(a.n), os.path.join(load()[a.name]["worktree"], "work.log")],
                         capture_output=True, text=True).stdout)


def cmd_digest(a):
    """Compact view of one worker: verdict, commits, diffstat, its REPORT block, log size."""
    t = load()[a.name]
    lp = os.path.join(t["worktree"], "work.log")
    txt = re.sub(r"\x1b\[[0-9;]*m", "", open(lp, errors="replace").read())
    print("%s: %s, verdict %s, log %d lines" % (a.name, state_of(t), verdict(t) or "-", txt.count("\n")))
    print(git("log", "--oneline", "master.." + t["branch"], check=False) or "(no commits)")
    print(git("diff", "--stat", "master..." + t["branch"], check=False)[-1500:])
    m = re.findall(r"=== REPORT.*?=== END REPORT ===", txt, re.S)
    print(m[-1] if m else "(no REPORT block; last log lines:)\n" + "\n".join(txt.strip().splitlines()[-8:]))
    for q in questions(t):
        print("QUESTION: " + q)


def qdir():
    d = os.path.join(ctl_dir(), "queue")
    os.makedirs(d, exist_ok=True)
    return d


def cmd_enqueue(a):
    """Queue a task. `refill` starts it when a worker slot is free and every task named in --needs is
    integrated (so work that depends on an unlanded round can be queued now and starts itself)."""
    task = a.task if a.task is not None else open(a.task_file).read()
    # a task queued without --pool runs on whichever slot is free first (see refill); --pool only prefers one
    item = dict(name=a.name, claims=a.claim, base=a.base, task=task, files=a.file, needs=a.needs or [],
                added=time.time(), pool=getattr(a, "pool", None), only=bool(getattr(a, "only", False)))
    json.dump(item, open(os.path.join(qdir(), a.name + ".json"), "w"), indent=1)
    print("queued %s (needs: %s)" % (a.name, ", ".join(item["needs"]) or "nothing"))


LIMIT_ERR = re.compile(r"model (is )?(unavailable|not found)|unknown model|usage limit|rate.?limit|quota|\b429\b|too many requests|insufficient (credit|balance)|"
                       r"limit (exceeded|reached)|resets? (at|in) ", re.I)
BREAKER_MIN = 30   # after a worker dies on arrival, start nothing new for this long


def breaker_path():
    return os.path.join(ctl_dir(), "breaker.json")


def breaker_until():
    try:
        return json.load(open(breaker_path()))["until"]
    except (OSError, ValueError, KeyError):
        return 0


# A usage limit is per MODEL: it bans that model for the slot's recovery time (tools/pool.json). A second limit within a
# day means the next block is the long one (the paid plan's 30-day window), so the ban escalates to long_recover_days.
LEDGER = "dead_models.json"


def _ledger():
    try:
        raw = json.load(open(os.path.join(ctl_dir(), LEDGER)))
    except (OSError, ValueError):
        return {}
    # the older format stored a bare `until` timestamp per model
    return {m: (e if isinstance(e, dict) else {"until": e, "strikes": 1, "last": 0}) for m, e in raw.items()}


def dead_models():
    """{model: until} for every model whose ban has not expired."""
    return {m: e["until"] for m, e in _ledger().items() if e["until"] > time.time()}


def mark_dead(model, sl):
    """Ban MODEL for the slot SL's recovery time; the second limit inside a day uses the long window."""
    d, now = _ledger(), time.time()
    prev = d.get(model, {})
    strikes = prev.get("strikes", 0) + 1 if now - prev.get("last", 0) < 86400 else 1
    hours = sl.get("long_recover_days", 0) * 24 if strikes >= 2 and sl.get("long_recover_days") else sl["recover_hours"]
    d[model] = {"until": now + hours * 3600, "strikes": strikes, "last": now}
    json.dump(d, open(os.path.join(ctl_dir(), LEDGER), "w"), indent=1)
    return hours


def running_by_slot(tasks=None):
    """Running workers per pool slot. A worker started before slots existed has no `pool`: it is counted against the
    slot that owns its model, so a slot is never over-filled by workers it does not know about."""
    by_model = {sl["model"]: sl["name"] for sl in load_pool()["slots"]}
    n = {}
    for t in (tasks or load()).values():
        if state_of(t) == "running":
            slot = t.get("pool") or by_model.get(t.get("model"))
            n[slot] = n.get(slot, 0) + 1
    return n


def slot_free(sl, busy):
    """A slot takes a task when it has room (count) and its model is not banned."""
    return busy.get(sl["name"], 0) < sl["count"] and sl["model"] not in dead_models()


def limit_hit(t):
    """True only when the worker's own error lines say so: an `Error:` line from the model/provider. A worker that
    READ a file mentioning a rate limit or a quota is not limited (2026-10-28: a read of coro.py marked OpenRouter's
    free router dead for a day)."""
    lp = os.path.join(t["worktree"], "work.log")
    if not os.path.exists(lp):
        return False
    lines = re.sub(r"\x1b\[[0-9;]*m", "", open(lp, errors="replace").read()[-3000:]).splitlines()
    errs = [l for l in lines if re.match(r"\s*Error:", l) or re.search(r"usage limit reached", l, re.I)]
    return any(LIMIT_ERR.search(l) for l in errs)


def dead_on_arrival(t):
    """A worker that never did anything: exited non-zero, no commits, no CONTROL-STATUS, and its log ends in a usage /
    rate limit or an API connection failure. 2026-10-24: 'Go usage limit exceeded' killed every worker the second it
    started, refill and formal_feed replaced each one, and the loop minted ~2,000 worktrees and `work/formalNNNN-docs`
    branches (202 GB) holding no work at all."""
    if state_of(t) != "exited-err" or verdict(t) or ahead(t):
        return False
    lp = os.path.join(t["worktree"], "work.log")
    if not os.path.exists(lp):
        return False
    tail = re.sub(r"\x1b\[[0-9;]*m", "", open(lp, errors="replace").read()[-3000:])
    return bool(LIMIT_ERR.search(tail) or NET_ERR.search(tail))


def bounce(name, t):
    """Take a dead-on-arrival task back to the QUEUE, leaving no trace: drop its worktree and branch (only after proving
    nothing in it is the worker's: no commits, and nothing beyond the files spawn itself wrote) and re-enqueue it under
    the same name, so the claim, the doc list and the formal%d counter are unchanged. Returns False if it kept the tree."""
    wt = t["worktree"]
    mine = {"TASK.md", "work.log", "exitcode", ".tmp/"}
    st = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], capture_output=True, text=True, cwd=wt).stdout
    extra = [l[3:] for l in st.splitlines() if not (l[3:] in mine or l[3:].startswith(".tmp/"))]
    if extra:
        return False
    if t.get("pool") and limit_hit(t):
        mark_dead(t["model"], pool_slot(t["pool"]))   # the task stays on its slot; refill waits for the ban to lift
    git("worktree", "remove", "--force", wt, check=False)
    git("branch", "-D", t["branch"], check=False)
    with registry() as reg:
        reg.pop(name, None)
    item = dict(name=name, claims=t["claims"], base=t.get("base") or "master", task=t.get("task") or _task_text(t),
                files=t.get("files", []), needs=[], added=time.time(), model=t.get("model"), pool=t.get("pool"))
    json.dump(item, open(os.path.join(qdir(), name + ".json"), "w"), indent=1)
    return True


def pick_slot(item, busy):
    """The slot a queued task starts on now: its preferred slot if that is free, else the first free, unbanned slot in
    pool order; None if every slot is full or banned. `busy` is running_by_slot() plus this pass's starts."""
    if item.get("only"):                       # pinned: its slot or nothing
        return pool_slot(item["pool"]) if item.get("pool") and slot_free(pool_slot(item["pool"]), busy) else None
    order = ([pool_slot(item["pool"])] if item.get("pool") else []) + load_pool()["slots"]
    return next((x for x in order if slot_free(x, busy)), None)


def cmd_refill(a):
    """Fill the pool: each slot in tools/pool.json takes queued tasks, oldest first, up to its own count, and a slot
    whose model is banned takes nothing. --target caps the total across slots (default: the pool's total).
    A task is skipped (stays queued) if a task it needs is not integrated yet, or its claims conflict.

    Circuit breaker: workers that died on arrival (a usage limit, an API outage) are bounced back to the queue with
    their worktree and branch removed, and nothing new starts for BREAKER_MIN minutes. Without it a limit turns this
    loop into a worktree-and-branch factory."""
    bounced = [n for n, t in list(load().items()) if dead_on_arrival(t) and bounce(n, t)]
    if bounced and not dead_models():   # a limit moved the work to another model; only an outage needs the pause
        json.dump({"until": time.time() + BREAKER_MIN * 60, "why": "%d workers died on arrival" % len(bounced)},
                  open(breaker_path(), "w"))
        print("%s refill: %d worker(s) died on arrival (limit/outage), bounced to the queue; no starts for %d min" % (
            time.strftime("%T"), len(bounced), BREAKER_MIN), flush=True)
    items_all = [json.load(open(os.path.join(qdir(), f))) for f in os.listdir(qdir()) if f.endswith(".json")]
    if items_all and not any(slot_free(sl, running_by_slot()) for sl in load_pool()["slots"]):
        print("%s refill: every slot with queued work is full or banned (%s), starting nothing" % (
            time.strftime("%T"), ", ".join("%s until %s" % (m, time.strftime("%F %R", time.localtime(u)))
                                           for m, u in dead_models().items()) or "no bans"), flush=True)
        return
    if time.time() < breaker_until():
        print("%s refill: breaker open for %.0f more min, starting nothing" % (
            time.strftime("%T"), (breaker_until() - time.time()) / 60), flush=True)
        return
    tasks = load()
    if a.target is None:
        a.target = pool_total()
    busy = running_by_slot(tasks)
    live = sum(busy.values())
    items = sorted(items_all, key=lambda i: i["added"])
    started = 0
    items = [i for i in items if i["name"].startswith(tuple(a.prefix.split(",")))]
    for it in items:
        if live + started >= a.target and not it["name"].startswith("fix-landed"):
            continue                      # a red master is repaired at once, whatever the slot count
        if any(state_of(tasks[n]) != "integrated" if n in tasks else True for n in it["needs"]):
            continue
        # A task is not tied to a model: its enqueue slot (`pool`) is only the PREFERRED one. It takes that slot if it is
        # free, else the first free, unbanned slot in pool order. Every slot runs the same kind of work.
        sl = pick_slot(it, busy)
        if sl is None:
            continue                      # every slot is full or banned: the task waits
        # a queued name can collide with a registry entry from an earlier attempt of the same chain (2026-10-30: two fixers
        # were skipped on every pass as "already exists"); the task starts under a fresh name instead
        name = it["name"] if it["name"] not in tasks else "%s-%d" % (it["name"][:50], int(time.time() * 1000) % 1000000)
        ns = argparse.Namespace(name=name, claim=it["claims"], task=it["task"], task_file=None,
                                file=it["files"], base=it["base"], model=None, pool=sl["name"])
        busy[sl["name"]] = busy.get(sl["name"], 0) + 1
        try:
            cmd_spawn(ns)
        except SystemExit as e:
            print("skip %s: %s" % (it["name"], e))
            continue
        os.remove(os.path.join(qdir(), it["name"] + ".json"))
        started += 1
    waiting = len(items) - started
    print("%s refill: %d running, started %d, %d still queued (target %d)" % (
        time.strftime("%T"), live, started, waiting, a.target), flush=True)


def cmd_gate(a):
    """gate list | gate off PATTERN --reason R --doc bugs/<name> --worker NAME | gate on PATTERN"""
    cfg = gates_cfg()
    if a.action == "list":
        print("landing:", ", ".join(cfg["landing"]), "| full every", cfg["full_every_minutes"], "min")
        for pat, e in cfg.get("off", {}).items():
            print("OFF  %-40s %s  (doc %s, worker %s, since %s)" % (pat, e["reason"], e["doc"], e["worker"], e["since"]))
        return
    if a.action == "off":
        if not (a.reason and a.doc and a.worker):
            sys.exit("gate off needs --reason, --doc (an existing bugs/ doc) and --worker (who works the backlog)")
        if not os.path.exists(os.path.join(MAIN, a.doc)):
            sys.exit("no such doc: %s" % a.doc)
        cfg.setdefault("off", {})[a.pattern] = dict(reason=a.reason, doc=a.doc, worker=a.worker,
                                                  since=time.strftime("%F %T"))
    else:
        if cfg.get("off", {}).pop(a.pattern, None) is None:
            sys.exit("no OFF gate %r" % a.pattern)
    json.dump(cfg, open(GATES_FILE, "w"), indent=2)
    print("gate %s %s" % (a.action, a.pattern))


def priority_list():
    try:
        return json.load(open(os.path.join(ctl_dir(), "priority.json")))
    except (OSError, ValueError):
        return []


def priority_key(name):
    """Sort key for integration order: listed names first, in listed order (a listed entry also matches
    a task whose name contains it, so `round8` covers the whole fix-merge chain), then everything else."""
    for i, p in enumerate(priority_list()):
        if name == p or p in name:
            return (0, i)
    return (1, 0)


def cmd_priority(a):
    if a.names:
        json.dump(a.names, open(os.path.join(ctl_dir(), "priority.json"), "w"))
    print("integration priority: " + " > ".join(priority_list() or ["(none: slot order)"]))


def cmd_queue(a):
    for f in sorted(os.listdir(qdir())):
        if f.endswith(".json"):
            i = json.load(open(os.path.join(qdir(), f)))
            print("%-28s needs: %-40s claims: %s" % (i["name"], ", ".join(i["needs"]) or "-", ", ".join(i["claims"])))


def cmd_hold(a):
    """Hold (or release) a task: a held task is never picked up by the integrator, but is otherwise a normal task
    (it still counts as running, is watched by unstick, and can finish). Used to pipeline: batch 2 is built while batch 1 is
    still being gated, and is released when batch 1 has landed."""
    with registry() as reg:
        if a.name not in reg:
            sys.exit("no such task")
        if a.release:
            reg[a.name].pop("hold", None)
        else:
            reg[a.name]["hold"] = True
    print("%s %s" % (a.name, "released" if a.release else "held"))


def cmd_ps(a):
    """Our workers' live opencode processes, told apart from the user's own opencode sessions by their
    arguments: ours are launched with `run --model M --auto ... <PARENT>/work-N/TASK.md` (opencode v1: `--model M run --auto
    --dir <PARENT>/work-N`), theirs have neither."""
    tasks = {os.path.realpath(t["worktree"]): n for n, t in load().items()}
    out = subprocess.run(["ps", "-axww", "-o", "pid=,etime=,rss=,args="], capture_output=True, text=True).stdout
    mine = other = 0
    for line in out.splitlines():
        m = re.search(r"opencode .*(?:--dir |instructions are in )(\S+?)(?:/TASK\.md)?(?:\s|$)", line)
        if m and " run " in line and "sh -c" not in line[:40]:
            pid, et, rss, _ = line.split(None, 3)
            print("%-24s pid %-6s up %-10s %5.0f MB" % (tasks.get(os.path.realpath(m.group(1)), "?"), pid, et, int(rss) / 1024))
            mine += 1
        elif re.search(r"/opencode\s*$", line.strip()):
            other += 1
    print("%d of our workers alive; %d other opencode process(es) belong to someone else" % (mine, other))


def cmd_guard(a):
    """Memory watchdog for OUR trees: SIGKILL any process whose cwd is inside a worker worktree (or the
    integrator tree) once its resident size passes --limit-gb, and, because a per-process cap is defeated by
    fan-out width, kill the largest such process whenever their SUM passes --total-gb. Says so in the log.

    Why: the gate's own jobs run under tools/memcap.py, but a worker's direct `fire.py build` / self-host
    compile does not, and this compiler has a known 190 GB+ blow-up (bugs/CODEGEN_bootstrap_resource_blowup.md).
    2026-09-29 the user had to kill a 200 GB+ mojo compile by hand. The default limit is above the 55 GB the
    `program` memclass is measured to need, so honest big jobs are not touched. RSS undercounts a process the
    OS has compressed or swapped, so this is a floor on protection, not a guarantee. Never touches a process
    outside our trees."""
    def tree_roots():
        # Recomputed every pass: workers are spawned all day, and a list taken once at start-up
        # stopped covering every worktree created after the guard did (2026-10-03: two orphaned
        # `lean` processes at 154 and 286 CPU-minutes ran for an hour inside work-337, a worktree
        # born after the guard, and the lean time bound never matched their cwd).
        return [os.path.realpath(p) for p in
                [t["worktree"] for t in load().values()] + [os.path.join(PARENT, "work-integ")]]
    roots = tree_roots()
    limit_kb = int(a.limit_gb * 1048576)
    total_kb = int(a.total_gb * 1048576)

    def cwd_of(pid):
        r = subprocess.run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"], capture_output=True, text=True).stdout
        m = re.search(r"^n(.*)$", r, re.M)
        return os.path.realpath(m.group(1)) if m else ""

    def kill(pid, why, rss, args):
        print("%s guard: killed pid %d at %.1f GB (%s): %s" % (
            time.strftime("%F %T"), pid, rss / 1048576, why, args[:110]), flush=True)
        try: os.kill(pid, 9)
        except OSError: pass

    while True:
        roots = tree_roots()
        out = subprocess.run(["ps", "-axo", "pid=,rss=,args="], capture_output=True, text=True).stdout
        big = []                                     # processes over 1 GB that live in our trees
        for line in out.splitlines():
            f = line.split(None, 2)
            if len(f) < 3 or not f[1].isdigit() or int(f[1]) < 1048576 or "control.py guard" in f[2]:
                continue
            c = cwd_of(int(f[0]))
            if any(c == x or c.startswith(x + os.sep) for x in roots):
                big.append((int(f[1]), int(f[0]), f[2]))
        for rss, pid, args in list(big):             # per-process ceiling
            if rss >= limit_kb:
                kill(pid, "over the %.0f GB per-process limit" % a.limit_gb, rss, args)
                big.remove((rss, pid, args))
        # Total budget: a per-process cap is defeated by fan-out width (2026-09-29: ~30 processes at ~30 GB
        # each, none over any per-process limit, collapsed the machine). Kill the largest until under budget.
        big.sort(reverse=True)
        while big and sum(b[0] for b in big) > total_kb:
            rss, pid, args = big.pop(0)
            kill(pid, "tree total over the %.0f GB budget" % a.total_gb, rss, args)
        _guard_lean_time(roots, a, cwd_of, kill)
        _guard_runaway(roots, a, cwd_of, kill)
        if a.once:
            return
        time.sleep(a.interval)


def _ps_time(s):
    """`ps` etime/time -> seconds. Formats: [[dd-]hh:]mm:ss, with a fractional seconds part on `time`."""
    days = 0
    if "-" in s:
        d, s = s.split("-", 1); days = int(d)
    parts = [float(x) for x in s.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    return days * 86400 + parts[0] * 3600 + parts[1] * 60 + parts[2]


def _guard_lean_time(roots, a, cwd_of, kill):
    """Wall-clock and CPU upper bound on Lean 4 processes in OUR trees.

    2026-10-02 the user killed ten `lean` processes, some with HUNDREDS of CPU-hours: a valid inductive proof
    checks in seconds to minutes, so anything past these limits is a non-terminating elaboration (a `simp` /
    `decide` / kernel reduction loop that `maxHeartbeats` does not meter), not a slow proof. CPU time is
    counted across Lean's threads, so it grows faster than the wall clock. Applies to `lean` itself, not to
    `lake`/shell wrappers, and only to processes whose cwd is inside a worker worktree or the integrator tree.
    The same bounds belong in the code that launches Lean (formal/lean.py); this is the net under every
    launcher that has not been taught them, including a worker's ad-hoc `lean` run."""
    out = subprocess.run(["ps", "-axo", "pid=,etime=,time=,args="], capture_output=True, text=True).stdout
    for line in out.splitlines():
        f = line.split(None, 3)
        if len(f) < 4 or not re.search(r"(^|/)lean( |$)", f[3].split(" -", 1)[0]):
            continue
        try:
            wall, cpu = _ps_time(f[1]), _ps_time(f[2])
        except ValueError:
            continue
        if wall < a.lean_wall_min * 60 and cpu < a.lean_cpu_min * 60:
            continue
        c = cwd_of(int(f[0]))
        if any(c == x or c.startswith(x + os.sep) for x in roots):
            kill(int(f[0]), "lean past its bound: %.0f min wall, %.0f min CPU (limits %g / %g)" % (
                wall / 60, cpu / 60, a.lean_wall_min, a.lean_cpu_min), 0, f[3])


def _guard_runaway(roots, a, cwd_of, kill):
    """Wall-clock bound on a worker's compiler builds and test runs in OUR trees.

    2026-10-02: twelve `fire.py build --formal ... std/python/bindings.mojo` processes, up to 1.6 DAYS old and
    each burning ~55% of a core, plus two `test_formal_math.py` runs 10 hours old, were found left behind by
    workers that had since finished: a non-terminating compile (“`fire.py build --formal` on `std/python/bindings.mojo` never terminates”)
    that nothing bounded. Any `fire.py build` / `test_*.py` / `formal_sweep.py` / probe script that is still
    running after --runaway-min minutes (default 120; the longest legitimate one is the self-host build at ~25 min)
    is killed. The gate and the integrator run through tools/suite.py (its own timeouts), so their processes are
    named `suite.py`, not matched here."""
    out = subprocess.run(["ps", "-axo", "pid=,etime=,args="], capture_output=True, text=True).stdout
    for line in out.splitlines():
        f = line.split(None, 2)
        if len(f) < 3 or "control.py" in f[2] or "opencode" in f[2] or "suite.py" in f[2]:
            continue
        if not re.search(r"Python\S*\s.*(fire\.py build|/test_\w+\.py|\btest_\w+\.py|formal_sweep\.py|\.tmp/\S+\.py)", f[2]) \
                and not re.search(r"^(\S*python\S*)\s+(\S*fire\.py build|\S*test_\w+\.py|\S*formal_sweep\.py|\.tmp/\S+\.py)", f[2]):
            continue
        try:
            wall = _ps_time(f[1])
        except ValueError:
            continue
        if wall < a.runaway_min * 60:
            continue
        c = cwd_of(int(f[0]))
        if any(c == x or c.startswith(x + os.sep) for x in roots):
            kill(int(f[0]), "runaway: %.0f min wall (limit %g)" % (wall / 60, a.runaway_min), 0, f[2])


def cmd_cleanup(a):
    """Remove the worktrees we created and no longer use: a `work-*` tree whose HEAD is already an ancestor of
    master, with a clean tree (no modified or untracked-and-not-ignored files), and no live worker.

    2026-10-04: 403 worktrees held 257 GB. The removal is `git worktree remove` WITHOUT --force, so git
    itself refuses a tree with anything it would lose; unmerged work, dirty trees, running workers and
    `integ` are listed and left alone. Merged work/* branches with no worktree are then deleted with
    `git branch -d` (their commits are on master; `ahead()` reads a missing branch as 0 ahead)."""
    reg = load()
    byw = {os.path.realpath(t["worktree"]): (n, t) for n, t in reg.items()}
    wt, cur = [], {}
    for l in subprocess.run(["git", "worktree", "list", "--porcelain"], capture_output=True, text=True,
                            cwd=MAIN).stdout.splitlines():
        if l.startswith("worktree "):
            cur = {"path": l[9:]}; wt.append(cur)
        elif l.startswith("HEAD "):
            cur["head"] = l[5:]
    cands, kept = [], []
    for w in wt:
        p = os.path.realpath(w["path"])
        if not os.path.basename(p).startswith("work-") or os.path.basename(p) == "work-integ":
            continue
        t = byw.get(p)
        if t and state_of(t[1]) == "running":
            kept.append((p, "running")); continue
        if subprocess.run(["git", "merge-base", "--is-ancestor", w["head"], "master"], cwd=MAIN).returncode != 0:
            kept.append((p, "unmerged")); continue
        cands.append(p)

    # `git status` over a worker tree with a build/ in it is the slow step (~0.1-1 s each, 1900+ trees on
    # 2026-10-23 made the sequential loop outlast a 2-minute command timeout), and it is I/O bound, so fan it out.
    def is_dirty(p):
        return bool(subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True,
                                   cwd=p).stdout.strip())
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=a.jobs) as ex:
        dirty = list(ex.map(is_dirty, cands))
    safe = []
    for p, d in zip(cands, dirty):
        (kept if d else safe).append((p, "dirty") if d else p)
    done = 0
    for p in safe:
        if a.dry_run:
            print("would remove", p); continue
        r = subprocess.run(["git", "worktree", "remove", p], capture_output=True, text=True, cwd=MAIN)
        if r.returncode == 0: done += 1
        else: print("kept", p, r.stderr.strip()[:100])
    subprocess.run(["git", "worktree", "prune"], cwd=MAIN)
    from collections import Counter
    print("%s %d worktrees; left alone: %s" % ("would remove" if a.dry_run else "removed",
          len(safe) if a.dry_run else done, dict(Counter(r for _, r in kept))))

    # A merged branch with no worktree left costs nothing in disk but 1900+ of them made every `git branch` /
    # `for-each-ref` listing unreadable and every fetch announce each one as new. `git branch -d` (not -D)
    # refuses anything not fully merged into HEAD, and refuses a branch still checked out in any worktree.
    if a.branches:
        names = subprocess.run(["git", "for-each-ref", "--merged", "master", "--format=%(refname:short)",
                                "refs/heads/work/"], capture_output=True, text=True, cwd=MAIN).stdout.split()
        checked_out = {l[len("branch refs/heads/"):] for l in subprocess.run(
            ["git", "worktree", "list", "--porcelain"], capture_output=True, text=True, cwd=MAIN
        ).stdout.splitlines() if l.startswith("branch refs/heads/")}
        gone = [n for n in names if n not in checked_out]
        if a.dry_run:
            print("would delete %d merged branches" % len(gone))
        elif gone:
            for i in range(0, len(gone), 200):
                subprocess.run(["git", "branch", "-d"] + gone[i:i + 200], capture_output=True, cwd=MAIN)
            print("deleted %d merged work/* branches" % len(gone))
    if a.prune:
        cmd_prune(a)


def cmd_memtrim(a):
    """Right-size the memory ledger to what holders actually use, so waiting jobs are admitted.

    A reservation is an upper bound (a 96 GB holder may really use 4). Backfill in tools/memslot.py lets small
    requests sneak in on measured free memory, but that logic runs inside each WAITING client, and every
    worker's worktree carries its own (older) copy of memslot.py. The ledger is the one thing they all share, so
    this lowers each holder's entry to `max(--floor, 1.6 x its tree's RSS + 1)`, never above what it reserved
    (`gb_orig`), and raises it again as the job grows. Old clients then see room and admit themselves. The job's
    own memcap ceiling is untouched (it is still killed at what it asked for); what is relaxed is only the
    scheduler's worst-case assumption."""
    sys.path.insert(0, os.path.join(MAIN, "tools"))
    import memslot, procrun
    GB = 1024 ** 3
    while True:
        ppid, rss = procrun.ps_table()
        with memslot.Ledger() as L:
            for h in L.data["holders"]:
                job = h.get("job") or 0
                if h.get("sneak") or not job:
                    continue
                orig = h.setdefault("gb_orig", h["gb"])
                b, n = procrun.tree_rss(job, ppid, rss)
                if not n:
                    continue
                h["gb"] = round(min(orig, max(a.floor, b / GB * 1.6 + 1.0)), 2)
        if a.once:
            return
        time.sleep(a.interval)


def _task_text(t):
    """The original task, pulled back out of the worker's TASK.md (between '## The task' and '## Rules')."""
    try:
        txt = open(os.path.join(t["worktree"], "TASK.md")).read()
    except OSError:
        return t["summary"]
    m = re.search(r"## The task\n\n(.*?)\n\n## Rules", txt, re.S)
    return m.group(1) if m else t["summary"]


def restart(name, why, model=None):
    """Snapshot a worker's uncommitted work, stop it, and continue it as NAME-rN from its own branch."""
    t = load()[name]
    wt = t["worktree"]
    git("add", "-A", cwd=wt, check=False)
    git("commit", "-q", "-m", "WIP snapshot by controller: %s's uncommitted edits when it was restarted (%s)" % (name, why),
        cwd=wt, check=False)
    try:
        os.killpg(t["pid"], 15)
    except OSError:
        pass
    n = 2
    while "%s-r%d" % (name, n) in load():
        n += 1
    new = "%s-r%d" % (name, n)
    with registry() as reg:
        reg[name]["state"] = "superseded"
    task = ("You CONTINUE task '%s': the previous instance stopped (%s). Everything it had done is on your branch (its last "
            "commit is 'WIP snapshot by controller'); review it, keep what is right, and finish the task. Original task:\n\n%s"
            % (name, why, _task_text(t)))
    ns = argparse.Namespace(name=new, claim=t["claims"], task=task, task_file=None, file=[], base=t["branch"],
                            model=None, pool=t.get("pool"))
    cmd_spawn(ns)
    return new


def cmd_restart(a):
    print("restarted as", restart(a.name, a.why, a.model))


def cmd_unstick(a):
    """Restart workers that have stalled: log idle for --idle-min AND nothing in their process tree using CPU.

    A network error (or a dropped model request) leaves opencode alive but waiting forever; a long compile or test
    also leaves the log quiet, which is why the CPU of the tree is part of the test, not just the silence."""
    ppid, rss = None, None
    out = subprocess.run(["ps", "-axo", "pid=,ppid=,pcpu="], capture_output=True, text=True).stdout
    kids, cpu = {}, {}
    for line in out.splitlines():
        f = line.split()
        if len(f) == 3:
            kids.setdefault(int(f[1]), []).append(int(f[0])); cpu[int(f[0])] = float(f[2])
    for name, t in list(load().items()):
        if state_of(t) != "running":
            continue
        lp = os.path.join(t["worktree"], "work.log")
        idle = (time.time() - os.path.getmtime(lp)) / 60 if os.path.exists(lp) else 0
        stack, busy = [t["pid"]], 0.0
        while stack:
            pid = stack.pop()
            busy += cpu.get(pid, 0.0)
            stack.extend(kids.get(pid, ()))
        print("%-32s idle %5.1f min, tree cpu %5.1f%%%s" % (name, idle, busy, "  <- STALLED" if idle >= a.idle_min and busy < 3.0 else ""))
        if idle >= a.idle_min and busy < 3.0 and not a.dry_run:
            print("   restarted as", restart(name, "stalled %.0f min with no CPU (a network error?)" % idle))
    cmd_unstick_dead(a)


NET_ERR = re.compile(r"Cannot connect to API|Unable to connect|ECONNRESET|ETIMEDOUT|ENOTFOUND|fetch failed|socket hang up|"
                     r"network error|Is the computer able to access the url", re.I)


def cmd_unstick_dead(a):
    """Restart workers that DIED of a network error: exited non-zero, said no CONTROL-STATUS, and the tail of the log
    shows an API connection failure (2026-09-30: 'Error: Cannot connect to API: Unable to connect')."""
    for name, t in list(load().items()):
        if state_of(t) != "exited-err" or verdict(t):
            continue
        lp = os.path.join(t["worktree"], "work.log")
        if not os.path.exists(lp):
            continue
        tail = re.sub(r"\x1b\[[0-9;]*m", "", open(lp, errors="replace").read()[-3000:])
        if NET_ERR.search(tail):
            print("%-32s died of a network error: " % name + tail.strip().splitlines()[-1][:80])
            if not a.dry_run:
                print("   restarted as", restart(name, "died of a network error"))


def cmd_reap(a):
    """Kill processes still running with their cwd inside the worktree of a task whose worker has exited.

    Workers' tests start `lean` proof checks (and gcc, fire.py builds) that outlive the test run when the
    worker times out or moves on; reparented to launchd they burn a core each for hours (2026-09-29: 8 lean
    processes, 4-6 h old, from three long-finished workers, took a third of the machine and pushed the gate's
    jobs past their timeouts). Only trees of tasks that are NOT running are touched; anything else on the
    machine (another session's processes) is left alone."""
    live = {os.path.realpath(t["worktree"]) for t in load().values() if state_of(t) == "running"}
    dead = {os.path.realpath(t["worktree"]): n for n, t in load().items() if state_of(t) != "running"}
    out = subprocess.run(["lsof", "-d", "cwd", "-Fpn"], capture_output=True, text=True).stdout
    pid, victims = None, []
    for line in out.splitlines():
        if line.startswith("p"):
            pid = int(line[1:])
        elif line.startswith("n") and pid:
            cwd = os.path.realpath(line[1:])
            for root, name in dead.items():
                if (cwd == root or cwd.startswith(root + os.sep)) and pid != os.getpid():
                    victims.append((pid, name))
    for pid, name in victims:
        cmd = subprocess.run(["ps", "-o", "etime=,command=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()[:110]
        print("%s pid %d: %s" % ("would kill" if a.dry_run else "kill", pid, name + " | " + cmd))
        if not a.dry_run:
            try: os.kill(pid, 15)
            except OSError: pass
    print("%d process(es)" % len(victims))


def cmd_report(a):
    rows = []
    for name, t in sorted(load().items(), key=lambda kv: kv[1]["slot"]):
        rows.append("<tr><td>%s</td><td>work-%d</td><td>%s</td><td>%s</td><td>%d</td><td>%s</td><td>%s</td></tr>" % (
            name, t["slot"], state_of(t) + (" / " + verdict(t) if verdict(t) else ""), t["started"], ahead(t), ", ".join(t["claims"]), t["summary"]))
    block = ("<!--TASKS:BEGIN-->\n<table><tr><th>task</th><th>tree</th><th>state</th><th>started</th>"
             "<th>commits</th><th>claims</th><th>work</th></tr>\n%s\n</table>\n<!--TASKS:END-->" % "\n".join(rows))
    p = os.path.join(MAIN, "CONTROL.html")
    src = open(p).read()
    new = re.sub(r"<!--TASKS:BEGIN-->.*?<!--TASKS:END-->", lambda m: block, src, flags=re.S)
    open(p, "w").write(new)
    print("CONTROL.html task table updated (%d tasks)" % len(rows))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("spawn"); s.add_argument("name")
    s.add_argument("--claim", action="append", required=True)
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--task"); g.add_argument("--task-file")
    s.add_argument("--file", action="append", default=[], help="copy into the worker's .tmp/ (workers cannot read outside their tree)")
    s.add_argument("--base", default="master", help="branch to start from (a fix task starts from the failed task's branch)")
    s.add_argument("--pool", default=None, help="the pool slot to run on (default: the pool's default_slot)")
    s.add_argument("--model", default=None, help="a bare model, outside the pool (hand-run experiments only)")
    s.set_defaults(f=cmd_spawn)
    s = sub.add_parser("status"); s.add_argument("-v", "--verbose", action="store_true"); s.add_argument("--all", action="store_true"); s.set_defaults(f=cmd_status)
    sub.add_parser("claims").set_defaults(f=cmd_claims)
    s = sub.add_parser("gate"); s.add_argument("action", choices=["list", "off", "on"]); s.add_argument("pattern", nargs="?", default="")
    s.add_argument("--reason", default=""); s.add_argument("--doc", default=""); s.add_argument("--worker", default="")
    s.set_defaults(f=cmd_gate)
    s = sub.add_parser("claim"); s.add_argument("name"); s.add_argument("--claim", action="append", required=True)
    s.add_argument("--who", default=""); s.add_argument("--pid", type=int, default=0)
    s.add_argument("--hours", type=float, default=12); s.set_defaults(f=cmd_claim)
    s = sub.add_parser("release"); s.add_argument("name"); s.set_defaults(f=cmd_release)
    s = sub.add_parser("mark"); s.add_argument("name"); s.add_argument("state"); s.set_defaults(f=cmd_mark)
    s = sub.add_parser("log"); s.add_argument("name"); s.add_argument("-n", type=int, default=40); s.set_defaults(f=cmd_log)
    s = sub.add_parser("digest"); s.add_argument("name"); s.set_defaults(f=cmd_digest)
    s = sub.add_parser("cleanup"); s.add_argument("--dry-run", action="store_true")
    s.add_argument("--no-prune", dest="prune", action="store_false", help="keep finished registry entries")
    s.add_argument("--no-branches", dest="branches", action="store_false", help="keep merged work/* branches")
    s.add_argument("-j", "--jobs", type=int, default=16, help="parallel `git status` checks")
    s.set_defaults(f=cmd_cleanup)
    s = sub.add_parser("prune"); s.add_argument("--dry-run", action="store_true"); s.set_defaults(f=cmd_prune)
    s = sub.add_parser("guard"); s.add_argument("--limit-gb", type=float, default=55); s.add_argument("--total-gb", type=float, default=90)
    s.add_argument("--interval", type=float, default=3); s.add_argument("--once", action="store_true")
    s.add_argument("--lean-wall-min", type=float, default=45, help="kill a lean process in our trees past this many wall minutes")
    s.add_argument("--lean-cpu-min", type=float, default=90, help="... or this many CPU minutes (all threads)")
    s.add_argument("--runaway-min", type=float, default=120, help="kill a fire.py build / test_*.py / sweep / probe in our trees past this many wall minutes")
    s.set_defaults(f=cmd_guard)
    s = sub.add_parser("enqueue"); s.add_argument("name"); s.add_argument("--claim", action="append", required=True)
    g = s.add_mutually_exclusive_group(required=True); g.add_argument("--task"); g.add_argument("--task-file")
    s.add_argument("--file", action="append", default=[]); s.add_argument("--base", default="master")
    s.add_argument("--needs", nargs="*"); s.add_argument("--pool", default=None, help="the pool slot this task prefers")
    s.add_argument("--only", action="store_true", help="the task runs ONLY on its --pool slot (waits for it, never moves)")
    s.set_defaults(f=cmd_enqueue)
    s = sub.add_parser("refill"); s.add_argument("--target", type=int, default=None, help="default: the pool's total slots")
    s.add_argument("--prefix", default="", help="start only queued tasks whose name begins with this"); s.set_defaults(f=cmd_refill)
    s = sub.add_parser("priority"); s.add_argument("names", nargs="*"); s.set_defaults(f=cmd_priority)
    sub.add_parser("queue").set_defaults(f=cmd_queue)
    s = sub.add_parser("memtrim"); s.add_argument("--floor", type=float, default=4.0)
    s.add_argument("--interval", type=float, default=3.0); s.add_argument("--once", action="store_true"); s.set_defaults(f=cmd_memtrim)
    s = sub.add_parser("restart"); s.add_argument("name"); s.add_argument("--why", default="restarted by the controller"); s.add_argument("--model", default=None); s.set_defaults(f=cmd_restart)
    s = sub.add_parser("unstick"); s.add_argument("--idle-min", type=float, default=25); s.add_argument("--dry-run", action="store_true"); s.set_defaults(f=cmd_unstick)
    s = sub.add_parser("hold"); s.add_argument("name"); s.add_argument("--release", action="store_true"); s.set_defaults(f=cmd_hold)
    sub.add_parser("ps").set_defaults(f=cmd_ps)
    s = sub.add_parser("reap"); s.add_argument("--dry-run", action="store_true"); s.set_defaults(f=cmd_reap)
    sub.add_parser("report").set_defaults(f=cmd_report)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
