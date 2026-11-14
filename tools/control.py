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
    control.py cleanup [--dry-run] # remove worktrees whose branch is merged, clean, with no live session or process in them, then delete the merged work/* branches (--no-branches keeps them), then prunes finished registry entries (--no-prune keeps them)
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
import argparse, fcntl, glob, json, os, re, shutil, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fleet_ledger
from contextlib import contextmanager

MAIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARENT = os.path.dirname(MAIN)
POOL_FILE = os.environ.get("CONTROL_POOL_FILE", os.path.join(MAIN, "tools", "pool.json"))


def load_pool():
    """The worker pool (tools/pool.json): named slots, each pinned to ONE model with a fixed count. There is no
    fallback between slots: a task belongs to the slot it was queued for and waits there if that slot is full or banned."""
    return json.load(open(POOL_FILE))


def find_slot(name):
    """The slot named NAME, or None when tools/pool.json no longer has it.

    Internal callers follow a STORED pool name (a task or queue item written under
    an older pool.json). A slot removed since then means that task has no home —
    it is skipped or bounced — not that the whole runner should exit. The CLI's
    explicit `--pool` keeps using `pool_slot`, which stays loud about a typo."""
    for sl in load_pool()["slots"]:
        if sl["name"] == name:
            return sl
    return None


def pool_slot(name):
    sl = find_slot(name)
    if sl is None:
        sys.exit("no pool slot named %r in %s" % (name, POOL_FILE))
    return sl


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


def pid_alive(t):
    """The task's recorded process is still alive."""
    return alive(t.get("pid"))


def finished_done_ok(t):
    """A task the worker finished successfully: exit code 0 and a DONE verdict. sync --restart-dead must never
    restart one, even if its process is gone (restarting supersedes finished work)."""
    ec = os.path.join(t.get("worktree", ""), "exitcode")
    try:
        return open(ec).read().strip() == "0" and verdict(t) == "DONE"
    except OSError:
        return False


def dead_running_tasks(tasks):
    """Registry entries that are running or were recorded as exited-err, whose process is gone, and that never wrote
    an exitcode. A dead worker stays here until it is restarted or superseded, so a restart skipped for want of a
    slot is retried on a later pass (sync marks the dead ones exited-err, so the record matches the pid).

    A task that wrote an exitcode has finished: state_of already says exited-ok/exited-err for it, so
    treating it as a dead worker and restarting it would supersede finished work (2026-11-10: r329 said
    DONE, exited 0, and sync restarted it anyway, superseding a finished task)."""
    return {n for n, t in tasks.items()
            if t.get("state") in ("running", "exited-err") and not pid_alive(t)
            and not os.path.exists(os.path.join(t.get("worktree", ""), "exitcode"))}


def no_restart_reason(t, pool, counts, banned=None):
    """Why a dead worker must NOT be restarted, or None when it may be.

    A slot that is disabled (count 0) or already at its count, or a model that is banned, can only
    fail again — restarting there is what pinned one doc to an expired haiku OAuth session for 335
    rounds. "counts" is alive running tasks keyed by model."""
    m = t.get("model", "")
    sl = next((sl for sl in pool.get("slots", []) if sl.get("model") == m), None)
    if sl is None and t.get("pool"):
        # The slot this task ran on was removed from tools/pool.json. Restarting it
        # would run the model with no slot to charge/recover it, every pass, forever.
        return "pool slot %r is no longer in %s (model %s has no home)" % (t["pool"], POOL_FILE, m)
    if sl is not None and counts.get(m, 0) >= sl.get("count", 0):
        return "slot %s at capacity (%d/%d)" % (sl["name"], counts.get(m, 0), sl.get("count", 0))
    if m in (banned if banned is not None else dead_models()):
        return "model %s is banned" % m
    return None


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


def holds_claims(t):
    """Whether task T still holds its bug claims. Only work holds: a live worker, or commits that have not landed. A
    dead worker that committed nothing holds nothing, so a retry of the same bug is never refused by it (2026-11-01:
    23 such entries, all with no commits, refused every retry for days)."""
    st = state_of(t)
    if st in TERMINAL:
        return False
    if st == "running":
        return True
    return ahead(t) > 0


def ahead(t):
    r = subprocess.run(["git", "rev-list", "--count", "master.." + t["branch"]],
                       cwd=MAIN, capture_output=True, text=True)
    return int(r.stdout.strip() or 0) if r.returncode == 0 else 0


def ahead_since_base(t):
    """Commits the WORKER added since its spawn base.

    `ahead()` counts `master..branch`, but a fixer or a continuation is cut from a branch that
    already has commits master lacks: the fixer that died in its first second still shows the
    five commits of the branch it repairs. `base..branch` is the worker's own contribution — zero
    when it did nothing. Falls back to `ahead` when the base is gone or unreadable, so an unknown
    base can never turn a real attempt into a bounce."""
    base = t.get("base") or "master"
    branch = t.get("branch") or ""
    if not branch or base == branch:
        return ahead(t)
    r = subprocess.run(["git", "rev-list", "--count", base + ".." + branch],
                       cwd=MAIN, capture_output=True, text=True)
    return int(r.stdout.strip() or 0) if r.returncode == 0 else ahead(t)


def next_slot():
    used = [int(m.group(1)) for d in os.listdir(PARENT) if (m := re.fullmatch(r"work-(\d+)", d))]
    return max(used, default=0) + 1


def claim_blocker(claims, tasks):
    """Why a task claiming CLAIMS may not start now, or None. The one place both spawn and refill ask it: refill must
    know before it reserves a slot (a refused spawn that kept its slot starved the whole pool, 2026-11-10: five
    claim-blocked fix-merge tasks took all five easy slots, so qwen never got work)."""
    for other, t in tasks.items():
        if not holds_claims(t):
            continue
        for c in claims:
            for oc in t["claims"]:
                if conflicts(c, oc):
                    return "claim %r conflicts with %r held by task %s (%s, %d commits)" % (
                        c, oc, other, state_of(t), ahead(t))
    ext = external_conflicts(claims)
    if ext:
        return "claim %r conflicts with %r held by external session %s" % (ext[0][1], ext[0][2], ext[0][0])
    return None


def free_branch(name):
    """`work/<name>`, or the first `work/<name>-N` that no branch holds yet. Never reuses a branch: one that exists may
    carry commits that have not landed."""
    branch, k = "work/" + name, 1
    while git("rev-parse", "--verify", "--quiet", "refs/heads/" + branch, check=False).strip():
        branch, k = "work/%s-%d" % (name, k), k + 1
    return branch


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
        blocked = claim_blocker(a.claim, tasks)
        if blocked:
            sys.exit(blocked)
        n = next_slot()
        wt = os.path.join(PARENT, "work-%d" % n)
        # A branch named work/<name> can already exist: an earlier attempt of the same task left it behind with
        # commits that have not landed. Reusing or deleting it would destroy that work, so the new attempt takes the
        # next free suffix instead (2026-11-11: a queued bug-codegen-dict-slot-reads-refuse-compi failed to spawn
        # every refill cycle on `fatal: a branch named ... already exists`).
        branch = free_branch(a.name)
        git("worktree", "add", "-b", branch, wt, a.base)
        retire_base(a.base)               # a continuation now carries the predecessor's commits: its name can go
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
        # the worker runs under a CPU ceiling (tools/cpu_cap.py): a runaway loop stops itself, and its CPU is recorded
        capped = [sys.executable, os.path.join(MAIN, "tools", "cpu_cap.py"), "wrap", "--name", a.name, "--"] + cmd
        wrapper = 'export TMPDIR=%s PATH=%s:"$PATH"; ( %s ) >> work.log 2>&1 </dev/null; echo $? > exitcode' % (
            sh(os.path.join(wt, ".tmp")), sh(git_shim_dir()), " ".join(map(sh, capped)))
        open(os.path.join(wt, "work.log"), "a").write("=== control: spawned %s on %s at %s ===\n" % (
            a.name, a.model, time.strftime("%F %T")))
        p = subprocess.Popen(["sh", "-c", wrapper], cwd=wt, start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # a pipe to the caller must not outlive spawn
        tasks[a.name] = dict(name=a.name, slot=n, worktree=wt, branch=branch, claims=a.claim,
                             model=a.model, pool=a.pool if sl else None, kind=kind, pid=p.pid,
                             started=time.strftime("%F %T"),
                             base=a.base, files=a.file, task=task, cls=getattr(a, "cls", None),   # what `bounce` needs to put it back on the queue
                             state="running", summary=task.strip().splitlines()[0][:200],
                             **(getattr(a, "meta", None) or {}))   # chain depths ride along (merge_depth, proof_depth)
    fleet_ledger.record_spawn(ctl_dir(), a.name, p.pid, wt, cmd)     # the only processes the fleet may ever signal
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
    `rev-list` over hundreds of tasks is what made status take minutes). Returns None when the merge
    check can't be read (e.g., master unresolvable in the worktree context) so callers never prune
    on an unreadable merge state."""
    r = subprocess.run(["git", "for-each-ref", "--no-merged", "master", "--format=%(refname:short)", "refs/heads/"],
                       capture_output=True, text=True, cwd=MAIN)
    if r.returncode != 0:
        return None
    return set(r.stdout.split())


def done_and_gone(t, unmerged):
    """A finished task with nothing left to look at: terminal state, no worktree directory, and no commits
    outside master (its branch is merged or deleted). Such an entry holds no claim (terminal claims are
    ignored), no process and no work, so `status` hides it and `prune` may drop it. Returns False when
    `unmerged` is None (the merge check can't be read), so callers never prune on an unreadable merge
    state."""
    if unmerged is None:
        # The merge check couldn't be read (e.g., master unresolvable in the worktree context).
        # Don't prune - we can't be sure which branches are merged.
        return False
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
        n_ahead = ahead(t) if (unmerged is not None and t.get("branch") in unmerged) else 0
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
    if unmerged is None:
        print("prune: merge check unreadable (master does not resolve in %s); keeping every entry" % MAIN)
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
    """A bare doc name, a name with the .md suffix, and a bugs/ path, in the top directory or in any one class
    directory (bugs/hard/, bugs/mid/, ...), all mean the same `bug:<name>` claim: the document is the identity, not
    the directory the swarm has moved it to. Namespaced keys (bug:, gate:, ...) pass through. Any other path is refused
    rather than passed through, because a literal path claim conflicts with nothing and admits a second holder."""
    if ":" in c:
        return c
    m = re.fullmatch(r"(?:bugs/(?:[A-Za-z0-9_-]+/)?)?([A-Za-z0-9_]+?)(?:\.md)?", c)
    if not m:
        raise ValueError("not a bug document or claim key: %r" % c)
    return "bug:" + m.group(1)


def external_conflicts(claims, skip=None):
    return [(n, c, oc) for n, e in external().items() if n != skip for c in claims for oc in e["claims"] if conflicts(c, oc)]


def cmd_claim(a):
    """Register claims for work started outside control, so control's workers (and the feeder) stay off it, and the
    caller learns at once if a control worker or another outside session already holds it. Run it again to renew."""
    try:
        claims = [norm_claim(c) for c in a.claim]
    except ValueError as e:
        print("REFUSED: %s" % e)
        sys.exit(2)
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
        if holds_claims(t):                  # the same rule refill and spawn use: a finished worker with no commits holds nothing
            print("%-24s %s" % (name, ", ".join(t["claims"])))
    for name, e in sorted(external().items()):
        print("%-24s %s   [external: %s]" % (name, ", ".join(e["claims"]), e.get("who") or "?"))


def cmd_mark(a):
    with registry() as tasks:
        if a.name not in tasks:
            sys.exit("no such task")
        if a.state == "integrated" and ahead(tasks[a.name]) > 0:
            sys.exit("%s is not integrated: branch %s has %d commit(s) master lacks (land it, or mark it superseded/abandoned)"
                     % (a.name, tasks[a.name]["branch"], ahead(tasks[a.name])))
        tasks[a.name]["state"] = a.state
    print("%s -> %s" % (a.name, a.state))
    if a.state in TERMINAL:
        retire_task(a.name)               # the end of a task cleans up after itself; `cleanup` is only the safety net


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


def free_task_name(name, limit=60):
    """NAME cut to LIMIT characters, then made unique against the registry AND the queue. Truncating before the check
    is the point: two different long names cut to the same 40/60 characters collided on the cut form, which the
    old `name in load()` check on the uncut name never saw, and the second enqueue overwrote the first's queue file
    (or its spawn hit `task ... already exists`). The suffix is a counter, so it is stable and cannot repeat."""
    name = name[:limit].rstrip("-")
    taken = set(load()) | {f[:-5] for f in os.listdir(qdir()) if f.endswith(".json")}
    cand, k = name, 1
    while cand in taken:
        k += 1
        suffix = "-%d" % k
        cand = name[:limit - len(suffix)].rstrip("-") + suffix
    return cand


def cmd_enqueue(a):
    """Queue a task. `refill` starts it when a worker slot is free and every task named in --needs is
    integrated (so work that depends on an unlanded round can be queued now and starts itself)."""
    task = a.task if a.task is not None else open(a.task_file).read()
    if os.path.exists(os.path.join(qdir(), a.name + ".json")):
        sys.exit("task %s is already queued; a second enqueue would overwrite it (use free_task_name)" % a.name)
    # a task queued without --pool runs on whichever slot is free first (see refill); --pool only prefers one
    item = dict(name=a.name, claims=a.claim, base=a.base, task=task, files=a.file, needs=a.needs or [],
                added=time.time(), pool=getattr(a, "pool", None), only=bool(getattr(a, "only", False)),
                cls=getattr(a, "cls", None), meta=getattr(a, "meta", None) or {})
    json.dump(item, open(os.path.join(qdir(), a.name + ".json"), "w"), indent=1)
    print("queued %s (needs: %s)" % (a.name, ", ".join(item["needs"]) or "nothing"))


LIMIT_ERR = re.compile(r"model (is )?(unavailable|not found)|unknown model|usage limit|rate.?limit|quota|\b429\b|too many requests|insufficient (credit|balance)|"
                       r"limit (exceeded|reached)|resets? (at|in) |hit your (weekly |daily |5-hour )?limit", re.I)
AUTH_ERR = re.compile(r"Failed to authenticate|OAuth (session )?expired|could not be refreshed|"
                      r"invalid[_-]?api[_-]?key|401 Unauthorized|Please run .claude.*login", re.I)
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


RESET_MARGIN_S = 300   # a ban that ends at the printed reset time lifts five minutes after it, so the limit has really cleared
RESET_RE = re.compile(r"resets (\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*\(([A-Za-z_/+-]+)\)", re.I)


def next_wall_time(hour, minute, tz, now=None):
    """The epoch time of the next HH:MM in zone TZ strictly after NOW (tomorrow if today's has passed)."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    now = time.time() if now is None else now
    t = datetime.fromtimestamp(now, ZoneInfo(tz)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if t.timestamp() <= now:
        t += timedelta(days=1)
    return t.timestamp()


def replenish_at(sl, now=None):
    """When a daily free tier gets its tokens back: the slot's `replenish` time plus its margin, or None when the slot
    has no daily replenish. pool.json: "replenish": {"tz": "UTC", "at": "00:00", "margin_min": 1}."""
    r = sl.get("replenish")
    if not r:
        return None
    hh, mm = (int(x) for x in r["at"].split(":"))
    return next_wall_time(hh, mm, r["tz"], now) + r.get("margin_min", 1) * 60


def reset_at(text, now=None):
    """The epoch time of the NEXT reset the claude CLI printed in a limit line ("resets 11am (America/Los_Angeles)"),
    or None when the text carries no reset. The next occurrence of that wall-clock time in that zone, strictly after now."""
    m = RESET_RE.search(text or "")
    if not m:
        return None
    hour, minute = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "pm" else 0), int(m.group(2) or 0)
    return next_wall_time(hour, minute, m.group(4), now)


def limit_reset(t):
    """The reset time of the limit that stopped worker T, read from its own log; None if its log names none."""
    lp = os.path.join(t["worktree"], "work.log")
    if not os.path.exists(lp):
        return None
    return reset_at(re.sub(r"\x1b\[[0-9;]*m", "", open(lp, errors="replace").read()[-3000:]))


def mark_dead(model, sl, until=None, now=None):
    """Ban MODEL until UNTIL (a limit's printed reset) when given, else for the slot SL's recovery time. Without a reset,
    the second limit inside a day uses the long window."""
    d, now = _ledger(), time.time() if now is None else now
    prev = d.get(model, {})
    strikes = prev.get("strikes", 0) + 1 if now - prev.get("last", 0) < 86400 else 1
    if until and until > now:
        end = until + RESET_MARGIN_S
    elif replenish_at(sl, now):
        end = replenish_at(sl, now)     # a daily free tier: back when its tokens come back, not a fixed block
    else:
        hours = sl.get("long_recover_days", 0) * 24 if strikes >= 2 and sl.get("long_recover_days") else sl["recover_hours"]
        end = now + hours * 3600
    hours = (end - now) / 3600
    d[model] = {"until": end, "strikes": strikes, "last": now}
    json.dump(d, open(os.path.join(ctl_dir(), LEDGER), "w"), indent=1)
    return hours


PROBE_EVERY_S = 12 * 3600   # a banned daily free tier is asked one word at most this often: they refill once a day
PROBE_TIMEOUT_S = 180


def probe_model(model):
    """True when MODEL answers a one-word prompt. A limit's refusal, a timeout or a missing CLI is no answer."""
    try:
        r = subprocess.run(["opencode", "run", "--model", model, "Reply with the single word PONG."],
                           capture_output=True, text=True, timeout=PROBE_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired):
        return False
    out = re.sub(r"\x1b\[[0-9;]*m", "", r.stdout + r.stderr)
    return r.returncode == 0 and "PONG" in out and not LIMIT_ERR.search(out)


def probe_free_bans(now=None, probe=probe_model):
    """Lift the ban on each banned daily free tier that answers, and drop bans for models no longer in the pool.

    A free tier's ban is a guess (its replenish time), and a limit can land minutes after a replenish, so the tier's
    own answer decides: the ban is lifted at once when the tier answers, and otherwise re-asked every PROBE_EVERY_S.
    A ban is keyed by MODEL, not by slot, so removing the slot never cleared it: a model removed from pool.json kept
    its ledger row forever, and re-adding it inherited the old ban. Removing the model now means removing its ban.

    Returns the models it lifted. Called by refill, so a free tier recovers without a human running `probe-free`."""
    now = time.time() if now is None else now
    d = _ledger()
    slots = load_pool()["slots"]
    pool_models = {sl["model"] for sl in slots}
    removed = [m for m in d if m not in pool_models]
    for m in removed:
        del d[m]
    daily = {sl["model"] for sl in slots if sl.get("replenish")}
    lifted, changed = [], bool(removed)
    for m, e in d.items():
        if m not in daily or e["until"] <= now or now - e.get("probed", 0) < PROBE_EVERY_S:
            continue
        e["probed"] = now
        changed = True
        if probe(m):
            e["until"] = now
            lifted.append(m)
            print("probe: %s answers; its ban is lifted" % m, flush=True)
        else:
            print("probe: %s still refuses; next probe in %d s" % (m, PROBE_EVERY_S), flush=True)
    if changed:
        json.dump(d, open(os.path.join(ctl_dir(), LEDGER), "w"), indent=1)
    return lifted


def cmd_probe_free(a):
    probe_free_bans()


def live_names(tasks):
    """Names of tasks whose worktree still has an opencode session being driven, or None when the session listing
    cannot be read (callers then refuse to act). A recorded pid is NOT enough: a worker's CLI pid can be gone while its
    session keeps running, and state_of then says exited-err for a worker that is still working (2026-11-03: 31 of 52
    'running' tasks had dead pids, so refill counted 2 running and over-filled iceman to 43 of 20)."""
    try:
        return busy_task_names(live_session_dirs(), tasks)
    except Exception as e:      # a listing we cannot read is "unknown", never "nothing is live"
        print("%s live sessions unreadable (%s); refill and reap do nothing this pass" % (
            time.strftime("%T"), str(e)[:160]), flush=True)
        return None


def _working(name, t):
    """A task that has not finished: no terminal or exited state, and no exitcode file. Whether its process or session is
    alive is the caller's question (running_by_slot)."""
    if t.get("state") in TERMINAL or t.get("state") in ("exited-ok", "exited-err"):
        return False
    wt = t.get("worktree", "")
    if wt and not os.path.isdir(wt):      # its worktree is gone (removed, or never made): nothing can be working in it
        return False
    return not os.path.exists(os.path.join(wt, "exitcode"))


def running_by_slot(tasks=None, live=frozenset()):
    """Running workers per pool slot: a task is running when its pid is alive OR it has a live opencode session (`live`,
    from live_names). A worker started before slots existed has no `pool`: it is counted against the slot that owns its
    model, so a slot is never over-filled by workers it does not know about."""
    by_model = {sl["model"]: sl["name"] for sl in load_pool()["slots"]}
    n = {}
    for name, t in (tasks or load()).items():
        # a live opencode session counts only while the task is still working: a session the ledger did not start
        # (or a task already superseded/exited, or one that wrote its exitcode) must not pin its slot. The pid check
        # is not state_of()=="running": a dead pid with a live session is exactly the case the live set exists for.
        if _working(name, t) and (alive(t.get("pid")) or name in live):
            slot = t.get("pool") or by_model.get(t.get("model"))
            n[slot] = n.get(slot, 0) + 1
    return n


def running_by_model(tasks=None, live=frozenset()):
    """Working workers per model, counted exactly as running_by_slot counts them (sync's cap check must agree with
    refill's: it had its own rule, and skipped restarts of workers that had live sessions)."""
    n = {}
    for name, t in (tasks or load()).items():
        if _working(name, t) and (alive(t.get("pid")) or name in live):
            m = t.get("model", "")
            n[m] = n.get(m, 0) + 1
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
    errs = [l for l in lines if re.match(r"\s*Error:", l) or re.search(r"usage limit reached", l, re.I)
            or re.match(r"\s*You've hit your", l)]   # the claude CLI's own limit line
    return any(LIMIT_ERR.search(l) for l in errs)


def dead_on_arrival(t):
    """A worker that never did anything: exited non-zero, no commits, no CONTROL-STATUS, and its log ends in a usage /
    rate limit or an API connection failure. 2026-10-24: 'Go usage limit exceeded' killed every worker the second it
    started, refill and formal_feed replaced each one, and the loop minted ~2,000 worktrees and `work/formalNNNN-docs`
    branches (202 GB) holding no work at all."""
    if state_of(t) != "exited-err" or verdict(t) or ahead_since_base(t):
        return False
    lp = os.path.join(t["worktree"], "work.log")
    if not os.path.exists(lp):
        return False
    tail = re.sub(r"\x1b\[[0-9;]*m", "", open(lp, errors="replace").read()[-3000:])
    return bool(LIMIT_ERR.search(tail) or NET_ERR.search(tail))


def auth_failed(t):
    """The worker's own log ends in an authentication failure: the model cannot be used at all until the
    user re-authenticates, so restarting it on the same model just fails again. Distinct from a usage
    limit (LIMIT_ERR) and a network error (NET_ERR), which is why it needs its own pattern — 2026-11-10:
    haiku's OAuth session expired and one doc was restarted 335 times, each worker dying in 1 s."""
    lp = os.path.join(t["worktree"], "work.log")
    if not os.path.exists(lp):
        return False
    tail = re.sub(r"\x1b\[[0-9;]*m", "", open(lp, errors="replace").read()[-3000:])
    return bool(AUTH_ERR.search(tail))


FINISHING_PREFIXES = ("fix-merge-", "fix-red-", "fix-proof-", "fix-orch-")   # tasks that carry finished work to master
def refill_key(item):
    """Queue order for refill: tasks that finish done work first, then oldest first."""
    return (0 if item["name"].startswith(FINISHING_PREFIXES) else 1, item["added"])


ORCH_POOL = "sonnet-orch"       # the slot reserved for orchestration reviews (tools/pool.json): Sonnet, class "orch", which no doc has
MAX_CAP_REVIEWS = 3              # a task whose cap fires this many times stays capped: the review did not cure it
DEPTH_KEYS = {"merge_depth": ("fix-merge-", "fix-red-"), "proof_depth": ("fix-proof-",)}


def fixer_depth(name, t, key):
    """How deep NAME is in its chain of fixers (key `merge_depth`) or reviewers (`proof_depth`). A recorded depth wins:
    it travels with the task (queue item `meta` -> registry) and is reset to 0 by an orchestration review's FORWARD or
    FIXED. Counting prefixes in the NAME, as this used to, cannot be reset: the name only ever grows."""
    if key in (t or {}):
        return t[key]
    return sum(name.count(p) for p in DEPTH_KEYS[key])


def depth_meta(t, key, name):
    """The `meta` a fixer/reviewer queued from task NAME carries: both depths, with KEY one deeper."""
    m = {k: fixer_depth(name, t, k) for k in DEPTH_KEYS}
    m[key] += 1
    return m


def _cap_slug(name):
    core = re.sub(r"^((fix-merge-|fix-red-|fix-proof-|fix-orch-)+)", "", name)
    return re.sub(r"[^a-z0-9]+", "-", core.lower()).strip("-")[:40] or "task"


def _chain_evidence(name, t):
    """What an orchestration reviewer needs to judge a chain: its tasks, the branch's commits, the swarm log lines."""
    slug = _cap_slug(name)
    rows = []
    for n, x in sorted(load().items(), key=lambda kv: kv[1].get("started", "")):
        if slug[:24] and slug[:24] in re.sub(r"[^a-z0-9]+", "-", n.lower()):
            rows.append("  %-62s %-17s %3d ahead  started %s" % (n[:62], state_of(x), ahead(x), x.get("started", "?")))
    commits = git("log", "--format=%h %ad %s", "--date=format:%m-%d %H:%M", "master.." + t["branch"], check=False).splitlines()
    lines = []
    for lf in ("swarm.out", "swarm.out.2026-11-12"):
        lp = os.path.join(ctl_dir(), lf)
        if os.path.exists(lp):
            lines += [l for l in open(lp, errors="replace").read().splitlines() if slug[:24] in re.sub(r"[^a-z0-9]+", "-", l.lower())]
    return ("Tasks in this chain (oldest first):\n%s\n\nCommits on %s that master lacks (%d):\n%s\n\n"
            "Lines about it in .git/control/swarm.out (%d, last 25 shown):\n%s\n"
            % ("\n".join(rows[-25:]) or "  (none found)", t["branch"], len(commits),
               "\n".join("  " + c[:150] for c in commits[:20]) or "  (none)", len(lines),
               "\n".join("  " + l[:200] for l in lines[-25:]) or "  (none)"))


ORCH_REVIEW_TASK = """You are an ORCHESTRATION REVIEWER. A chain of automated tasks hit a depth cap, and the cap fired instead of the
work finishing. Your job is to find out WHY, and decide whether the cap was right. Read %(doc)s (the evidence), the swarm log
(.git/control/swarm.out), tools/swarm.py, tools/integrate.py and tools/control.py, and doc/ORCHESTRATION.html (what the
flow is meant to do). You start on master.

Capped task: %(name)s (branch %(branch)s). Cap: %(kind)s. Why it fired: %(why)s

Decide EXACTLY ONE:

FORWARD  The chain is making real progress and the orchestration is behaving as designed: each round resolves real work, any
         conflicts come from master moving while rounds run, nothing loops on itself. The cap was simply too tight for this
         chain. The cap will be reset and the chain may continue. Say what shows the progress (commits, conflicts resolved,
         tests passing).
FIXED    The chain is looping because of a DEFECT IN THE ORCHESTRATION (a rule that cannot be satisfied, a task handed back
         over and over, state not cleaned up, a parse that rejects good input). Fix the defect in tools/*.py, with a test
         (tools/test_*.py) that fails without the fix; run it and the neighbouring tools/test_*.py, wrapped in
         `python3 tools/memslot.py --gb 8 --label t --`. Commit it: it lands through the normal landing, and only then is
         the cap reset, so the fixed code is what handles the chain. Name the defect and the commit.
STOP     Neither: the chain is not progressing AND the orchestration is sound (the branch really cannot be merged, or it
         needs a design decision). Say exactly what is needed. The cap stays.

Rules: you are a light worker (no gate, no self-host build, never git stash). Edit only tools/ and docs; do not touch the
capped branch. Do NOT delete %(doc)s: the orchestrator removes it when it applies your verdict. Finish with the REPORT block,
the line `ORCH-VERDICT: FORWARD`, `ORCH-VERDICT: FIXED` or `ORCH-VERDICT: STOP` (exactly one, on its own line), and
CONTROL-STATUS: DONE."""


def enqueue_orch_review(name, kind, why):
    """A depth cap fired on task NAME: queue a Sonnet reviewer (slot ORCH_POOL, pinned) instead of just giving up. The
    reviewer decides FORWARD (reset the cap, the chain continues), FIXED (it fixed the orchestration: reset once that has
    landed) or STOP (stay capped); the verdict is read by swarm.apply_orch_reviews. The work needs a doc to exist (sync
    drops a queued task whose claims name none), so the evidence is written as bugs/ORCH_REVIEW_<slug>.md, which the
    swarm's skip list keeps out of the ordinary feed. Returns True when a review was queued."""
    import argparse as _ap
    t = load().get(name)
    prev = ((t or {}).get("cap_review") or {}).get("n", 0)
    if not t or prev >= MAX_CAP_REVIEWS:
        print("orchestration review: %s hit the cap %d time(s) already; it stays capped" % (name, prev), flush=True)
        return False
    slug = _cap_slug(name)
    base = "ORCH_REVIEW_%s" % slug
    doc = os.path.join(MAIN, "bugs", base + ".md")
    task = ORCH_REVIEW_TASK % dict(doc="bugs/%s.md" % base, name=name, branch=t["branch"], kind=kind, why=why)
    with open(doc, "w") as f:
        f.write("# Orchestration review: %s hit the %s cap\n\n%s\n\n## Evidence\n\n%s\n"
                % (name, kind, task, _chain_evidence(name, t)))
    rname = free_task_name("fix-orch-" + slug)
    cmd_enqueue(_ap.Namespace(name=rname, claim=["bug:" + base], task=task, task_file=None, file=[], base="master",
                              needs=[], model=None, cls=None, pool=ORCH_POOL, only=True))
    with registry() as reg:
        reg[name]["cap_review"] = {"reviewer": rname, "kind": kind, "doc": doc, "n": prev + 1}
    print("orchestration review: %s hit the %s cap; queued %s (Sonnet) to decide FORWARD, FIXED or STOP" % (name, kind, rname),
          flush=True)
    return True


ORCH_VERDICT = re.compile(r"^ORCH-VERDICT:[ \t]*(FORWARD|FIXED|STOP)\b", re.M)


def orch_verdict(t):
    """The reviewer's verdict (FORWARD, FIXED or STOP), read from the end of its worker log; None if it gave none."""
    try:
        txt = open(os.path.join(t["worktree"], "work.log"), errors="replace").read()
    except OSError:
        return None
    m = ORCH_VERDICT.findall(txt)
    return m[-1] if m else None


def reset_cap(name, verdict):
    """FORWARD or FIXED: the capped task may be handed to fixers again, from depth 0, and its review doc goes."""
    with registry() as reg:
        t = reg[name]
        t.pop("merge_capped", None)
        t.pop("fixer", None)
        t["merge_depth"] = 0
        t["proof_depth"] = 0
        cr = t.setdefault("cap_review", {})
        cr["verdict"], cr["applied"] = verdict, time.strftime("%F %T")
        doc = cr.get("doc")
    if doc and os.path.exists(doc):
        os.remove(doc)


CONTROLLER_FILES = {"TASK.md", "TASK_REPORT.md", "work.log", "exitcode", "REPORT.md"}   # written into a worker's tree by the controller, or (REPORT.md / TASK_REPORT.md) the worker's closing report, left untracked


def tree_extras(wt):
    """The entries `git status` shows in worker tree WT that are NOT the controller's own files (TASK.md, work.log,
    exitcode, .tmp/). A finished tree whose only changes are those holds nothing of the worker's: older branches
    still track TASK.md (untracked since 9855b224e), so the controller's own rewrite of it made 58 finished trees
    look dirty for ever and cleanup could never remove them."""
    st = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"],
                        capture_output=True, text=True, cwd=wt).stdout
    return [l[3:] for l in st.splitlines() if l[3:] not in CONTROLLER_FILES and not l[3:].startswith(".tmp/")]


def retire_landed(name):
    """The last step of a landing: its tree and branch go with it, in the same operation, so nothing waits for a later
    cleanup pass. Runs only for a task whose every commit is on master (`ahead == 0`), whose worker is not alive, and
    whose tree holds nothing but the controller's own files; anything else is KEPT and reported (never forced).
    Removes the worktree, deletes the now-merged branch (`-d`, which refuses an unmerged one) and drops the registry
    entry. Returns True when the tree and branch are gone."""
    t = load().get(name)
    if not t or ahead(t) > 0:
        return False
    if alive(t.get("pid")) and state_of(t) == "running":
        print("retire %s: its worker is still running; kept" % name)
        return False
    wt = t["worktree"]
    if os.path.isdir(wt):
        extra = tree_extras(wt)
        if extra:
            print("retire %s: %d uncommitted file(s) in %s (%s); kept" % (name, len(extra), wt, extra[0]))
            return False
        r = subprocess.run(["git", "worktree", "remove", "--force", wt], capture_output=True, text=True, cwd=MAIN)
        if r.returncode != 0:
            print("retire %s: %s; kept" % (name, r.stderr.strip()[:100]))
            return False
    subprocess.run(["git", "worktree", "prune"], cwd=MAIN)
    subprocess.run(["git", "branch", "-d", t["branch"]], capture_output=True, cwd=MAIN)
    with registry() as reg:
        reg.pop(name, None)
    return True


def retire_task(name):
    """What a task's end owes: called when it reaches a terminal state, so the normal path leaves nothing behind.
      - every commit on master (landed, or never committed): retire_landed: tree, branch and registry entry go.
      - unlanded commits, HELD (a gate-red culprit): its tip is saved under refs/archive/<name>, then tree, branch and
        entry go. Nothing will land it; the archive keeps it recoverable.
      - unlanded commits, not held (abandoned because a continuation takes over): only the clean tree goes. The
        branch is the continuation's base; retire_base deletes the name once the successor is cut from it.
    A tree with anything of the worker's in it is never touched. Returns True when anything was retired."""
    t = load().get(name)
    if not t or state_of(t) not in TERMINAL:
        return False
    if ahead(t) == 0:
        return retire_landed(name)
    wt = t["worktree"]
    if os.path.isdir(wt):
        if tree_extras(wt):
            return False
        if subprocess.run(["git", "worktree", "remove", "--force", wt], capture_output=True, cwd=MAIN).returncode != 0:
            return False
        subprocess.run(["git", "worktree", "prune"], cwd=MAIN)
    if t.get("hold"):
        sha = git("rev-parse", t["branch"], check=False)
        if sha and subprocess.run(["git", "update-ref", ARCHIVE_REF + t["branch"], sha], cwd=MAIN).returncode == 0:
            subprocess.run(["git", "branch", "-D", t["branch"]], capture_output=True, cwd=MAIN)
            with registry() as reg:
                reg.pop(name, None)
    return True


def retire_base(base):
    """A continuation was just cut from branch BASE: its commits now live on the successor's branch (same tip), so the
    predecessor's name is deleted when its task is terminal and has no tree. Never deletes a branch whose task is alive."""
    if not base.startswith("work/"):
        return
    owner = next((t for t in load().values() if t.get("branch") == base), None)
    if owner is not None and (state_of(owner) not in TERMINAL or os.path.isdir(owner["worktree"])):
        return
    subprocess.run(["git", "branch", "-D", base], capture_output=True, cwd=MAIN)


def bounce(name, t):
    """Take a dead-on-arrival task back to the QUEUE, leaving no trace: drop its worktree and branch (only after proving
    nothing in it is the worker's: no commits, and nothing beyond the files spawn itself wrote) and re-enqueue it under
    the same name, so the claim, the doc list and the formal%d counter are unchanged. Returns False if it kept the tree."""
    wt = t["worktree"]
    if tree_extras(wt):
        return False
    if t.get("pool") and limit_hit(t):
        _sl = find_slot(t["pool"])
        if _sl is not None:          # the slot may have been removed from pool.json since the task started
            mark_dead(t["model"], _sl, limit_reset(t))   # the ban ends at the printed reset, else the recovery time
    git("worktree", "remove", "--force", wt, check=False)
    git("branch", "-D", t["branch"], check=False)
    with registry() as reg:
        reg.pop(name, None)
    item = dict(name=name, claims=t["claims"], base=t.get("base") or "master", task=t.get("task") or _task_text(t),
                meta={k: t[k] for k in DEPTH_KEYS if k in t},
                files=t.get("files", []), needs=[], added=time.time(), model=t.get("model"), pool=t.get("pool"),
                cls=t.get("cls"))
    json.dump(item, open(os.path.join(qdir(), name + ".json"), "w"), indent=1)
    return True


def doc_class_now(item):
    """The class a queued item runs in.

    A `bug-` task's class is where its doc sits NOW: bugs/ is easy, bugs/mid/ is mid, bugs/hard/ is
    hard (the same rule as swarm.dir_class). Such an item carries the class it was queued in, and a
    reclass moves the file while that item is still waiting, so the stored class goes stale; refill
    must ask the file.

    Any other task keeps the class it was queued with. Controller work chooses its own class
    deliberately — a replan of a hard doc runs at easy, because easy is the class that has a slot —
    and deriving it from the doc would park it at an unserved class forever."""
    if not item.get("name", "").startswith("bug-"):
        return item.get("cls")
    for c in item.get("claims", []):
        if c.startswith("bug:"):
            hits = sorted(glob.glob(os.path.join(MAIN, "bugs", "**", c[4:] + ".md"), recursive=True))
            if hits:
                parts = os.path.relpath(hits[0], os.path.join(MAIN, "bugs")).split(os.sep)
                return "easy" if len(parts) == 1 else {"mid": "mid", "hard": "hard"}.get(parts[0], "easy")
    return item.get("cls")


def _rewrite_queued(item):
    """Write a queued item back to its file (the refill's decisions about it persist from one pass to the next)."""
    with open(os.path.join(qdir(), item["name"] + ".json"), "w") as f:
        json.dump(item, f, indent=1)


def _commit_exists(ref):
    return subprocess.run(["git", "rev-parse", "--verify", "-q", ref + "^{commit}"],
                          capture_output=True, cwd=MAIN).returncode == 0


def pick_slot(item, busy):
    """The slot a queued task starts on now: its preferred slot if that is free, else the first free, unbanned slot in
    pool order; None if every slot is full or banned. `busy` is running_by_slot() plus this pass's starts."""
    if item.get("only"):                       # pinned: its slot or nothing
        _sl = find_slot(item["pool"]) if item.get("pool") else None
        return _sl if _sl is not None and slot_free(_sl, busy) else None
    slots = load_pool()["slots"]
    # A slot whose class is not a work class (`orch`, the reserved Sonnet slot for orchestration reviews) takes only
    # tasks PINNED to it (`only`, above). Without this an UNCLASSED task (the verifier's fix-gate-*) overflowed into it
    # whenever the ordinary slots were full or banned, and ran on paid Sonnet (2026-11-12).
    slots = [x for x in slots if slot_class(x) in CLASSES]
    if item.get("cls"):                        # a classed task stays in its class: its slots or nothing
        slots = [x for x in slots if accepts(x, item["cls"])]
    pref = item.get("pool")
    order = [x for x in slots if x["name"] == pref] + [x for x in slots if x["name"] != pref]
    return next((x for x in order if slot_free(x, busy)), None)


CLASSES = ("easy", "mid", "hard")   # the work classes, weakest model first; a slot without a class is easy


def slot_class(sl):
    return sl.get("class", "easy")


def accepts(sl, cls):
    """A slot takes tasks of its own class and of any class in its `also` list (pool.json)."""
    return slot_class(sl) == cls or cls in sl.get("also", [])


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
    items_all = []
    for f in os.listdir(qdir()):
        if f.endswith(".json"):
            with open(os.path.join(qdir(), f)) as fh:
                items_all.append(json.load(fh))
    tasks = load()
    live_set = live_names(tasks)
    if live_set is None:
        return                            # the session listing is unreadable: we cannot count the slots, so start nothing
    if items_all and not any(slot_free(sl, running_by_slot(tasks, live_set)) for sl in load_pool()["slots"]):
        print("%s refill: every slot with queued work is full or banned (%s), starting nothing" % (
            time.strftime("%T"), ", ".join("%s until %s" % (m, time.strftime("%F %R", time.localtime(u)))
                                           for m, u in dead_models().items()) or "no bans"), flush=True)
        return
    if time.time() < breaker_until():
        print("%s refill: breaker open for %.0f more min, starting nothing" % (
            time.strftime("%T"), (breaker_until() - time.time()) / 60), flush=True)
        return
    busy = running_by_slot(tasks, live_set)
    live = sum(busy.values())
    if a.target is None:
        a.target = max(pool_total(), live)
    # Work that FINISHES something already done goes first: a merge fixer, a proof reviewer or an orchestration reviewer
    # holds a finished branch and its claim, and every pass that starts a fresh doc instead leaves that branch waiting
    # (2026-11-12: 14 proof reviewers sat behind fresh docs while 9 finished branches waited). Then oldest first.
    items = sorted(items_all, key=refill_key)
    started = 0
    items = [i for i in items if i["name"].startswith(tuple(a.prefix.split(",")))]
    # The FORMAL lane is the owner's: its Qwen runs formal* tasks by hand, and the swarm never starts one, on any slot
    # (2026-10-31: queued formal tasks were started on haiku, which is paid and not for the formal lane).
    for it in items:
        if live + started >= a.target and not it["name"].startswith("fix-landed"):
            continue                      # a red master is repaired at once, whatever the slot count
        unmet = [n for n in it["needs"] if not (n in tasks and state_of(tasks[n]) == "integrated")]
        if unmet:
            continue                      # waiting on a task: `control.py queue` says what it waits on
        # A task is not tied to a model: its enqueue slot (`pool`) is only the PREFERRED one. It takes that slot if it is
        # free, else the first free, unbanned slot in pool order. Every slot runs the same kind of work.
        # The class comes from the doc's file NOW, not from the queue entry: a reclass moves the doc while its task is
        # still queued, and a stale "mid" started a hard doc on the mid-only iceman slot (2026-11-03, 46 attempts).
        cls = doc_class_now(it)
        if cls != it.get("cls"):
            print("%s is now %s (queued as %s): it takes a %s slot" % (it["name"], cls, it.get("cls"), cls), flush=True)
            it = dict(it, cls=cls)
            _rewrite_queued(it)           # persisted, so the move is announced once, not on every pass
        base = it.get("base") or "master"
        if base != "master" and not _commit_exists(base):
            # The feed names a base branch (work/formal<N>-docs) that no longer exists; the spawn would fail on every
            # pass forever. The doc is still there on master, so start from master, once.
            print("%s: base %s no longer exists; starting from master" % (it["name"], base), flush=True)
            it = dict(it, base="master")
            _rewrite_queued(it)
        blocked = claim_blocker(it["claims"], tasks)
        if blocked:
            continue                      # a claim held elsewhere: the task waits, and takes no slot (see `queue`)
        sl = pick_slot(it, busy)
        if sl is None:
            continue                      # every slot is full or banned: the task waits
        # a queued name can collide with a registry entry from an earlier attempt of the same chain (2026-10-30: two fixers
        # were skipped on every pass as "already exists"); the task starts under a fresh name instead
        name = it["name"] if it["name"] not in tasks else "%s-%d" % (it["name"][:50], int(time.time() * 1000) % 1000000)
        ns = argparse.Namespace(name=name, claim=it["claims"], task=it["task"], task_file=None,
                                file=it["files"], base=it["base"], model=None, pool=sl["name"], cls=it.get("cls"),
                                meta=it.get("meta"))
        try:
            cmd_spawn(ns)
        except SystemExit as e:
            print("skip %s: %s" % (it["name"], e), flush=True)
            continue                      # refused: no slot was taken, so the next task can use it
        busy[sl["name"]] = busy.get(sl["name"], 0) + 1
        tasks = load()                    # the new worker's claims must block the rest of this pass
        os.remove(os.path.join(qdir(), it["name"] + ".json"))
        started += 1
    waiting = len(items) - started
    print("%s refill: %d running, started %d, %d still queued (target %d)" % (
        time.strftime("%T"), live, started, waiting, a.target), flush=True)


def cmd_gate(a):
    """gate list | gate off PATTERN --reason R --doc bugs/<name> --worker NAME | gate on PATTERN"""
    cfg = gates_cfg()
    if a.action == "list":
        print("landing:", ", ".join(cfg["landing"]), "| full gate: whenever a landing since the last run touches something a gate reads")
        for pat, e in cfg.get("off", {}).items():
            print("OFF  %-40s %s  (doc %s, worker %s, since %s)" % (pat, e["reason"], e["doc"], e["worker"], e["since"]))
        return
    if a.action == "off":
        if not (a.reason and a.doc and a.worker):
            sys.exit("gate off needs --reason, --doc (an existing bugs/ doc) and --worker (who works the backlog)")
        if not os.path.exists(os.path.join(MAIN, a.doc)):
            sys.exit("no such doc: %s" % a.doc)
        gate_off_in(GATES_FILE, a.pattern, a.reason, a.doc, a.worker)
    else:
        if cfg.get("off", {}).pop(a.pattern, None) is None:
            sys.exit("no OFF gate %r" % a.pattern)
        json.dump(cfg, open(GATES_FILE, "w"), indent=2)
    print("gate %s %s" % (a.action, a.pattern))


def gate_off_in(path, pattern, reason, doc, worker):
    """Add one OFF entry to the gates file at PATH (the single writer of tools/gates.json: `gate off` comes through here)."""
    cfg = json.load(open(path))
    cfg.setdefault("off", {})[pattern] = dict(reason=reason, doc=doc, worker=worker, since=time.strftime("%F %T"))
    json.dump(cfg, open(path, "w"), indent=2)


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
    """Every queued task, and what it waits on right now (computed here, so no pass has to log it)."""
    tasks, pool = load(), load_pool()
    busy = running_by_slot(tasks, live_names(tasks) or frozenset())
    for f in sorted(os.listdir(qdir())):
        if not f.endswith(".json"):
            continue
        i = json.load(open(os.path.join(qdir(), f)))
        unmet = [n for n in i["needs"] if not (n in tasks and state_of(tasks[n]) == "integrated")]
        blocked = claim_blocker(i["claims"], tasks)
        if unmet:
            why = "needs %s integrated" % ", ".join(unmet)
        elif blocked:
            why = blocked
        elif pick_slot(i, busy) is None:
            why = "no free slot (%s)" % ", ".join(sl["name"] for sl in pool["slots"] if accepts(sl, i.get("cls") or "easy"))
        else:
            why = "startable now"
        print("%-44s %-22s %s" % (i["name"][:44], ", ".join(i["claims"])[:22], why))


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
    tasks = load()
    print("%-40s %-6s %-5s %-6s %-28s %s" % ("name", "pid", "alive", "cls", "model", "claims"))
    for name, t in sorted(tasks.items()):
        if t.get("state") != "running":
            continue
        pid = t.get("pid")
        alive = False
        if pid:
            try:
                os.kill(pid, 0); alive = True
            except (OSError, ProcessLookupError):
                alive = False
        claims = ",".join(t.get("claims") or [])[:40]
        model = (t.get("model") or t.get("pool") or "?")[:28]
        cls = (t.get("cls") or "?")[:6]
        print("%-40s %-6s %-5s %-6s %-28s %s" % (name[:40], pid, "yes" if alive else "no", cls, model, claims))
    # live process scan
    out = subprocess.run(["ps", "-axww", "-o", "pid=,etime=,rss=,args="], capture_output=True, text=True).stdout
    mine = other = 0
    for line in out.splitlines():
        m = re.search(r"opencode .*(?:--dir |instructions are in )(\S+?)(?:/TASK\.md)?(?:\s|$)", line)
        if m and " run " in line and "sh -c" not in line[:40]:
            mine += 1
        elif re.search(r"/opencode\s*$", line.strip()):
            other += 1
    print("%d live opencode process(es) of ours; %d belong to someone else" % (mine, other))


def cmd_guard(a):
    """Memory watchdog for the groups the fleet started (fleet_ledger). A group whose resident size passes
    --limit-gb is stopped: SIGTERM, then SIGKILL after the grace period, logged in kills.log. A process the fleet
    did not start is never measured against the limit and never signalled. --total-gb caps the sum over all groups.
    Runs once per invocation: loop it from the outside if you want it continuous."""
    limit_kb = int(a.limit_gb * 1048576)
    total_kb = int(a.total_gb * 1048576)
    groups = {}
    for name, t in load().items():
        if state_of(t) != "running":
            continue
        for e in fleet_ledger.entries(ctl_dir(), name):
            groups[e["pgid"]] = name
    sizes = {g: fleet_ledger.group_rss_kb(g) for g in groups}
    for g, kb in sizes.items():
        if kb > limit_kb:
            fleet_ledger._log(ctl_dir(), "guard: group %d (task %s) at %.1f GB over the %.1f GB limit" % (
                g, groups[g], kb / 1048576, a.limit_gb))
            fleet_ledger.kill_group(ctl_dir(), groups[g], "memory over limit")
    if sum(sizes.values()) > total_kb and sizes:
        g = max(sizes, key=sizes.get)
        fleet_ledger._log(ctl_dir(), "guard: fleet total %.1f GB over %.1f GB; largest group %d (task %s)" % (
            sum(sizes.values()) / 1048576, a.total_gb, g, groups[g]))
        fleet_ledger.kill_group(ctl_dir(), groups[g], "fleet total over limit")



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


def _claimed_by_outside(path):
    """True if an outside session (a user's own opencode, a hand-run agent) has claimed this directory or a parent of it.
    A claim is a string; a path claim is compared as a path. Such a tree is never removed."""
    for e in external().values():
        for k in e.get("claims", []):
            if not k.startswith("/") and "/" not in k:
                continue
            kp = os.path.realpath(k)
            if path == kp or path.startswith(kp + os.sep) or kp.startswith(path + os.sep) or kp == path:
                return True
    return False


ARCHIVE_REF = "refs/archive/"
BRANCH_MIN_AGE_S = 24 * 3600     # a branch younger than this is never touched: something may be about to look at it


def classify_retirable_branches():
    """(tips, subsumed, dead) for the `work/*` branches nothing will ever land (see prune_work_branches for the rules).
    A branch checked out in a worktree is still CLASSIFIED: its tree is what has to go first, and cleanup removes that
    tree (clean ones only, with every liveness check) before the branch is deleted."""
    reg = load()
    byb = {t.get("branch"): t for t in reg.values()}
    rows = subprocess.run(["git", "for-each-ref", "--no-merged", "master",
                           "--format=%(refname:short) %(objectname) %(committerdate:unix)", "refs/heads/work/"],
                          capture_output=True, text=True, cwd=MAIN).stdout.splitlines()
    tips = {}
    for r in rows:
        name, sha, when = r.split()
        tips[name] = (sha, int(when))
    if not tips:
        return tips, [], []
    qtext = ""
    for f in os.listdir(qdir()):
        if f.endswith(".json"):
            qtext += open(os.path.join(qdir(), f), errors="replace").read()
    now = time.time()
    ok = {n for n, (sha, when) in tips.items()
          if now - when >= BRANCH_MIN_AGE_S and n not in qtext
          and (byb.get(n) or {}).get("state") != "running"}
    # one call: the tips no other tip contains. A tip not in it is reachable from another branch.
    ind = subprocess.run(["git", "merge-base", "--independent"] + sorted({sha for sha, _ in tips.values()}),
                         capture_output=True, text=True, cwd=MAIN)
    if ind.returncode != 0:
        return tips, [], []
    independent = set(ind.stdout.split())
    keeper = {}                                  # equal tips share a commit: exactly one name must stay
    for n in sorted(tips):
        sha = tips[n][0]
        if n not in ok:                          # a protected name is the keeper for its commit
            keeper[sha] = n
        else:
            keeper.setdefault(sha, n)
    subsumed = [n for n in sorted(ok) if tips[n][0] not in independent or keeper[tips[n][0]] != n]
    dead = []
    for n in sorted(ok - set(subsumed)):
        t = byb.get(n)
        if t is None or (t.get("state") in TERMINAL and t.get("hold")):
            dead.append(n)
    return tips, subsumed, dead


def prune_work_branches(dry_run=False):
    """Retire the `work/*` branches nothing will ever land, so the branch list stays the size of the live work.

    cleanup's `branch -d` only reaches branches already in master. The rest piled up (1,350+ on 2026-11-12): every
    retry, continuation, merge-fix and gate-fix gets a NEW branch, and a task that ends abandoned/superseded leaves
    its commits unmerged for ever. Two lossless rules, in order:

      1. SUBSUMED: the tip is an ancestor of another unmerged work/* tip (a continuation was cut from it, a fixer
         built on it). Every commit stays reachable from that branch, so the name is deleted outright.
      2. DEAD: the task is terminal (integrated/abandoned/superseded) AND held, or there is no task at all (the
         registry forgot it, so nothing can ever land it). Its tip is saved under refs/archive/<name> (invisible to
         `git branch`, immune to gc) and the branch deleted. Recover with `git branch <name> refs/archive/<name>`.

    Never touched: a branch checked out in any worktree (cleanup removes a clean, idle tree first), one younger than
    BRANCH_MIN_AGE_S, a task that is running or finished-and-waiting (it may yet land), an abandoned task NOT held
    (`continue` cuts its successor from it), or a branch named by a queued task. Returns (subsumed, archived) counts."""
    tips, subsumed, dead = classify_retirable_branches()
    out = subprocess.run(["git", "worktree", "list", "--porcelain"], capture_output=True, text=True, cwd=MAIN).stdout
    busy = {l[len("branch refs/heads/"):] for l in out.splitlines() if l.startswith("branch refs/heads/")}
    subsumed = [n for n in subsumed if n not in busy]
    dead = [n for n in dead if n not in busy]
    if dry_run:
        print("would delete %d subsumed and archive %d dead work/* branches" % (len(subsumed), len(dead)))
        return len(subsumed), len(dead)
    for i in range(0, len(subsumed), 100):
        subprocess.run(["git", "branch", "-D"] + subsumed[i:i + 100], capture_output=True, cwd=MAIN)
    for n in dead:
        r = subprocess.run(["git", "update-ref", ARCHIVE_REF + n, tips[n][0]], capture_output=True, cwd=MAIN)
        if r.returncode == 0:                    # delete only once the archive ref is in place
            subprocess.run(["git", "branch", "-D", n], capture_output=True, cwd=MAIN)
    print("deleted %d subsumed work/* branches; archived %d dead ones under %s" % (len(subsumed), len(dead), ARCHIVE_REF))
    return len(subsumed), len(dead)


def cmd_cleanup(a):
    """Remove the worktrees we created and no longer use: a `work-*` tree whose HEAD is already an ancestor of
    master, with a clean tree (no modified or untracked-and-not-ignored files), and no live worker.

    2026-10-04: 403 worktrees held 257 GB. The removal is `git worktree remove` WITHOUT --force, so git
    itself refuses a tree with anything it would lose; unmerged work, dirty trees, running workers and
    `integ` are listed and left alone. Merged work/* branches with no worktree are then deleted with
    `git branch -d` (their commits are on master; `ahead()` reads a missing branch as 0 ahead).
    2026-11-10: a tree a plain PROCESS is working in (a hand-started test run, not a worker, not an
    opencode session, no outside claim) is also left alone — the run's cwd check is rescanned at the
    moment of removal, since the run of one is irreversible."""
    reg = load()
    byw = {os.path.realpath(t["worktree"]): (n, t) for n, t in reg.items()}
    wt, cur = [], {}
    for l in subprocess.run(["git", "worktree", "list", "--porcelain"], capture_output=True, text=True,
                            cwd=MAIN).stdout.splitlines():
        if l.startswith("worktree "):
            cur = {"path": l[9:]}; wt.append(cur)
        elif l.startswith("HEAD "):
            cur["head"] = l[5:]
        elif l.startswith("branch refs/heads/"):
            cur["branch"] = l[len("branch refs/heads/"):]
    retire = set()
    if a.branches:
        _t, _s, _d = classify_retirable_branches()
        retire = set(_s) | set(_d)             # work nothing will land: its clean, idle tree may go too
    try:
        dirs = live_session_dirs()
    except (RuntimeError, OSError, ValueError) as e:
        print("cleanup: %s; removing nothing" % e)     # cannot tell which trees an agent is driving: remove none
        return
    try:
        cwds = live_cwds(jobs=a.jobs)
    except (RuntimeError, OSError, ValueError) as e:
        print("cleanup: %s; removing nothing" % e)     # cannot tell which trees a process is in: remove none
        return
    cands, kept = [], []
    for w in wt:
        p = os.path.realpath(w["path"])
        if not os.path.basename(p).startswith("work-") or os.path.basename(p) == "work-integ":
            continue
        t = byw.get(p)
        if t and state_of(t[1]) == "running":
            kept.append((p, "running")); continue
        if any(d == p or d.startswith(p + os.sep) for d in dirs):
            kept.append((p, "live opencode session")); continue
        if any(c == p or c.startswith(p + os.sep) for c in cwds):
            kept.append((p, "live process in tree")); continue
        if _claimed_by_outside(p):
            kept.append((p, "claimed by an outside session")); continue
        if (w.get("branch") not in retire
                and subprocess.run(["git", "merge-base", "--is-ancestor", w["head"], "master"], cwd=MAIN).returncode != 0):
            kept.append((p, "unmerged")); continue
        cands.append(p)

    # `git status` over a worker tree with a build/ in it is the slow step (~0.1-1 s each, 1900+ trees on
    # 2026-10-23 made the sequential loop outlast a 2-minute command timeout), and it is I/O bound, so fan it out.
    def is_dirty(p):
        return bool(tree_extras(p))             # the controller's own files (TASK.md, work.log, ...) are not dirt
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=a.jobs) as ex:
        dirty = list(ex.map(is_dirty, cands))
    safe = []
    for p, d in zip(cands, dirty):
        (kept if d else safe).append((p, "dirty") if d else p)
    if safe and not a.dry_run:
        # The snapshot above predates the (parallel) git-status fan-out; rescan at the moment of the
        # irreversible step, so a run that started in the gap is still seen.
        try:
            cwds = live_cwds(jobs=a.jobs)
        except (RuntimeError, OSError, ValueError) as e:
            print("cleanup: %s; removing nothing" % e)
            return
        still = []
        for p in safe:
            if any(c == p or c.startswith(p + os.sep) for c in cwds):
                kept.append((p, "live process in tree"))
            else:
                still.append(p)
        safe = still
    done = 0
    for p in safe:
        if a.dry_run:
            print("would remove", p); continue
        r = subprocess.run(["git", "worktree", "remove", "--force", p], capture_output=True, text=True, cwd=MAIN)  # only controller files can differ: is_dirty said so
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
        prune_work_branches(a.dry_run)
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


MAX_RESTARTS = 10   # a chain restarted this many times is not progressing: abandon it so the claim is released


def chain_depth(name):
    """How many restarts a task's name records: each "-rN" suffix is one restart, so `X-r2-r2-r5` is depth 3."""
    return len(re.findall(r"-r\d+", name))


def doc_exists_for(claims):
    """Whether a bug doc exists for these claims. The one rule for work: it exists only while its doc does. A
    `bug:NAME` (or `gate:NAME`) claim matches a doc anywhere under MAIN/bugs whose file name contains NAME, with `_`
    read as `-`. Sync and restart both ask this, so they cannot disagree about whether work still has a doc."""
    for c in claims:
        tail = c.split(":")[-1].lower().replace("_", "-")
        for _root, _dirs, files in os.walk(os.path.join(MAIN, "bugs")):
            if any(fn.endswith(".md") and tail in fn.lower().replace("_", "-") for fn in files):
                return True
    return False


def restart(name, why, model=None):
    """Snapshot a worker's uncommitted work, stop it, and continue it as NAME-rN from its own branch.
    Returns the new task's name, or None once the chain is over MAX_RESTARTS: the task is then marked
    abandoned so its claim is released and the doc is re-fed (a fresh worker, possibly a different model)
    instead of round 300 of the same failure. A task whose doc is gone is not continued at all: 197 rounds of
    fix-gate-formal-host-import-shapes ran with no doc behind them (2026-11-10)."""
    t = load()[name]
    if not doc_exists_for(t.get("claims", [])):
        with registry() as reg:
            reg[name]["state"] = "abandoned"
        print("restart refused: %s has no bug doc for its claims %s; work exists only while its doc does"
              % (name, t.get("claims")))
        return None
    # strip any existing -rN suffix so restarts increment instead of nesting: foo-r2 -> foo-r3, not foo-r2-r2
    base = re.sub(r"-r\d+$", "", name)
    wt = t["worktree"]
    git("add", "-A", cwd=wt, check=False)
    git("commit", "-q", "-m", "WIP snapshot by controller: %s's uncommitted edits when it was restarted (%s)" % (name, why),
        cwd=wt, check=False)
    try:
        fleet_ledger.kill_group(ctl_dir(), t["name"], "restart")
    except OSError:
        pass
    # The budget counts the chain's depth, not the free name: stripping one "-rN" leaves a nested base (`X-r2-r2`),
    # and the first free "-r2" under it always looks like round 2, so a chain of 300 restarts never reached the budget
    # (2026-11-10: fix-gate-formal-doc-truth-r2-...-r134 kept restarting against a master that moved every pass).
    depth = chain_depth(name)
    n = 2
    while "%s-r%d" % (base, n) in load():
        n += 1
    if depth + 1 > MAX_RESTARTS or n > MAX_RESTARTS:
        with registry() as reg:
            reg[name]["state"] = "abandoned"
        print("restart budget exhausted: %s would be round %d; marked abandoned so its claim is released" % (name, n))
        return None
    new = "%s-r%d" % (base, n)
    with registry() as reg:
        reg[name]["state"] = "superseded"
    task = ("You CONTINUE task '%s': the previous instance stopped (%s). Everything it had done is on your branch (its last "
            "commit is 'WIP snapshot by controller'); review it, keep what is right, and finish the task. Original task:\n\n%s"
            % (name, why, _task_text(t)))
    ns = argparse.Namespace(name=new, claim=t["claims"], task=task, task_file=None, file=[], base=t["branch"],
                            model=None, pool=t.get("pool"), cls=t.get("cls"))
    cmd_spawn(ns)
    return new


def cmd_restart(a):
    new = restart(a.name, a.why, a.model)
    print("restarted as %s" % new if new else "not restarted: %s (over the restart budget, marked abandoned)" % a.name)


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
            new = restart(name, "stalled %.0f min with no CPU (a network error?)" % idle)
            print("   restarted as %s" % new if new else "   not restarted: %s (over the restart budget)" % name)
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
                new = restart(name, "died of a network error")
                print("   restarted as %s" % new if new else "   not restarted: %s (over the restart budget)" % name)


def descendants(pid):
    """Every process under PID (its children, their children, and so on), from the live process table. A job a worker's
    shell started (a test, a build) is one of these while the worker lives; once its parent dies the job is reparented
    to launchd and the walk loses it, which is why reap also matches on the worktree (below)."""
    out = subprocess.run(["ps", "-axo", "pid=,ppid="], capture_output=True, text=True).stdout
    kids = {}
    for line in out.splitlines():
        f = line.split()
        if len(f) == 2 and f[0].isdigit() and f[1].isdigit():
            kids.setdefault(int(f[1]), []).append(int(f[0]))
    found, todo = [], [pid]
    while todo:
        for k in kids.get(todo.pop(), []):
            if k not in found:
                found.append(k)
                todo.append(k)
    return found


SESSION_WINDOW_S = 900   # an opencode session updated this recently is still working


def live_session_dirs(window_s=SESSION_WINDOW_S, listing=None):
    """Directories of opencode sessions updated within `window_s`: an agent that is still driving a worktree, even when
    the registry task that owns the tree has exited (its CLI process is gone but the session on the service keeps
    running). `listing` is the parsed `opencode session list --format json` (injectable for tests); raises if the
    listing cannot be read, so the caller can refuse to act rather than guess."""
    if listing is None:
        r = subprocess.run(["opencode", "session", "list", "--format", "json"], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise RuntimeError("opencode session list failed: " + (r.stderr or r.stdout).strip()[:200])
        listing = json.loads(r.stdout)
    now_ms = time.time() * 1000
    return {os.path.realpath(s["directory"]) for s in listing
            if s.get("directory") and now_ms - s.get("updated", 0) <= window_s * 1000}


def live_cwds(jobs=16):
    """The working directory of every live process, as a set of realpaths.

    2026-11-10: `cleanup` removed a detached work-* tree at master while a full gimple-runner run was
    working in it, because none of its protections see a plain process — the registry knows only workers
    IT started, `opencode session list` only sessions the service drives, and outside claims only what
    someone registered. A detached tree at master with a hand-started run passes every check, and
    `git worktree remove` (without --force) agrees, since an in-progress run writes only ignored files.
    A live process whose cwd is a tree or under one means the tree is in use, whatever its state says.

    `ps` is the process table here (one call, ~50-100 ms; see procrun) and `lsof -d cwd` is the only
    way to read a macOS process's directory, per-pid (~50 ms each, so the pids fan out). Raises when
    the table cannot be read, like `live_session_dirs`: a cleanup that cannot tell which trees a
    process is in removes nothing, so a dead `lsof` must fail the call, not return an empty set that
    reads as "nothing is running anywhere"."""
    if not shutil.which("lsof"):
        raise RuntimeError("lsof is not available; cannot read process cwds")
    r = subprocess.run(["ps", "-axo", "pid="], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ps failed: " + (r.stderr or r.stdout).strip()[:200])
    pids = [int(x) for x in r.stdout.split()]

    def one(pid):
        try:
            o = subprocess.run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
                               capture_output=True, text=True, timeout=30).stdout
        except (OSError, subprocess.SubprocessError):
            return ""
        for line in o.splitlines():
            if line.startswith("n"):
                return os.path.realpath(line[1:])
        return ""

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        return {c for c in ex.map(one, pids) if c}


def busy_task_names(dirs, tasks):
    """The names of tasks whose worktree contains (or is) one of the live session directories."""
    busy = set()
    for n, t in tasks.items():
        root = os.path.realpath(t.get("worktree", "/nonexistent"))
        if any(d == root or d.startswith(root + os.sep) for d in dirs):
            busy.add(n)
    return busy


def cmd_reap(a):
    """Stop the leftover process groups of finished workers. Only groups the fleet recorded at spawn (fleet_ledger):
    never a process found by its working directory, command or port. A process started by anyone else, including a
    user's own opencode session in a worktree, is never signalled. A group whose leader has exited is logged and left."""
    tasks = load()
    live_set = live_names(tasks)
    if live_set is None:
        return                            # cannot tell a finished worker from a live session: signal nothing
    for name, t in tasks.items():
        if state_of(t) == "running" or name in live_set:   # a live session is never "finished", whatever its pid says
            continue
        for e in fleet_ledger.entries(ctl_dir(), name):
            members = fleet_ledger.group_members(e["pgid"])
            if not members:
                continue
            if a.dry_run:
                print("would stop %s group %d: %s" % (name, e["pgid"], "; ".join("%d %s" % (p, c[:60]) for p, c in members)))
        if not a.dry_run:
            fleet_ledger.kill_group(ctl_dir(), name, "reap: task finished")
    print("reap: %s" % ("dry run; nothing signalled" if a.dry_run else "done; see kills.log"))



def cmd_sync(a):
    '''Reconcile the queue and registry with the filesystem and live processes.

    - Queue entries whose bug doc no longer exists on disk are stale: drop them.
    - Queue entries whose class drifted from the doc's current class: rewrite.
    - Registry tasks marked 'running' whose process is dead: report (not auto-fixed).
    --dry-run: report only, change nothing.'''
    import os as _os
    dry = getattr(a, "dry_run", False)
    restart_dead = getattr(a, "restart_dead", False)
    tasks = load()
    removed = []
    rewritten = []
    for f in sorted(_os.listdir(qdir())):
        if not f.endswith(".json"):
            continue
        path = _os.path.join(qdir(), f)
        with open(path) as fh:
            it = json.load(fh)
        doc_exists = False
        if it.get("files"):
            doc_exists = any(_os.path.exists(c) for c in it["files"])
        else:
            doc_exists = doc_exists_for(it.get("claims", []))
        if not doc_exists:
            removed.append(it["name"])
            if not dry:
                _os.remove(path)
            continue
        new_cls = doc_class_now(it)
        if new_cls != it.get("cls"):
            rewritten.append((it["name"], it.get("cls"), new_cls))
            if not dry:
                it2 = dict(it, cls=new_cls)
                _rewrite_queued(it2)
    if removed:
        print("sync: queued stale removed=%d%s" % (len(removed), " (dry-run)" if dry else ""))
    for n in removed:
        print("  removed %s" % n)
    if rewritten:
        print("sync: queued class-rewritten=%d" % len(rewritten))
    for n, old, new in rewritten:
        print("  %s: %s -> %s" % (n, old, new))
    live = live_names(tasks)
    # A task is dead when its recorded pid is gone. The opencode session listing is
    # unreliable (times out, or keeps stale sessions), so it must not mask a dead pid.
    dead_running = sorted(dead_running_tasks(tasks))
    if dead_running and not dry and live is not None:
        # A pid that is gone is not running. Record that, so the registry stops saying "running" for a worker that is
        # not (2026-11-10: a killed README worker stayed "running" for hours, shown by ps and claims). A task whose
        # session is still live is left alone, and an unreadable listing (live is None) changes nothing.
        with registry() as reg:
            for n in dead_running:
                if n not in live and n in reg and reg[n].get("state") == "running":
                    reg[n]["state"] = "exited-err"
    if dead_running:
        print("sync: running-but-dead-in-registry=%d" % len(dead_running))
        for n in dead_running:
            print("  %s" % n)
    if dead_running and restart_dead and not dry:
        pool = load_pool()
        counts = running_by_model(tasks, live_names(tasks) or frozenset())
        for n in dead_running:
            t = tasks.get(n, {})
            if t.get("worktree") and not os.path.isdir(t["worktree"]):
                # a dead worker whose worktree is gone cannot be restarted: retire it, so it stops holding its claim and
                # its slot (2026-11-10: a killed README worker was counted against qwen-local on every pass)
                with registry() as ts:
                    ts[n]["state"] = "abandoned"
                print("  abandoned %s: its worktree %s is gone" % (n, t["worktree"]))
                continue
            # A task the worker finished successfully must never be restarted: it is done, not dead.
            if finished_done_ok(t):
                print("  skipped %s: verdict DONE with exit code 0" % n)
                continue
            # DONE ratchet: if every doc claim's doc is gone (deleted on master), the task
            # is already resolved; mark superseded instead of restarting it forever.
            claims = [c for c in t.get("claims", []) if c.startswith("bug:")]
            if claims and not any(os.path.exists(os.path.join(MAIN, "bugs", c[4:] + ".md")) or
                                  os.path.exists(os.path.join(MAIN, "bugs", "mid", c[4:] + ".md")) or
                                  os.path.exists(os.path.join(MAIN, "bugs", "hard", c[4:] + ".md")) or
                                  os.path.exists(os.path.join(MAIN, "bugs", "formal", c[4:] + ".md"))
                                  for c in claims):
                with registry() as ts:
                    ts[n]["state"] = "superseded"
                print("  superseded %s: all its docs are gone" % n)
                continue
            m = t.get("model", "")
            sl = next((sl for sl in pool.get("slots", []) if sl.get("model") == m), None)
            # An authentication failure means the model cannot be used at all until the user
            # re-authenticates: ban it, so nothing starts it again, rather than restarting a worker
            # that dies in 1 s (2026-11-10: haiku's OAuth expired; one doc went 335 rounds on it).
            if sl is not None and m not in dead_models() and auth_failed(t):
                hours = mark_dead(m, sl)
                print("  banned %s for %.1f h: its worker could not authenticate" % (m, hours))
                continue
            # Pool guard: never restart a worker whose slot is disabled (count 0) or already full,
            # and never one whose model is banned — a banned model's new worker only fails again.
            reason = no_restart_reason(t, pool, counts)
            if reason:
                print("  skipped %s: %s" % (n, reason))
                continue
            try:
                new = restart(n, "process dead (sync --restart-dead)", None)
                if new is None:
                    continue
                counts[m] = counts.get(m, 0) + 1
                print("  restarted %s -> %s" % (n, new))
            except Exception as e:
                print("  FAILED to restart %s: %s" % (n, e))
    elif dead_running and not dry:
        print("  (not auto-fixed; use control.py mark NAME abandoned/exited-err by hand, or --restart-dead)")

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
    s.add_argument("--cls", choices=CLASSES, default=None, help="the work class: only slots of this class take it")
    s.set_defaults(f=cmd_enqueue)
    sub.add_parser("probe-free", help="lift the ban on any daily free tier that answers a one-word prompt").set_defaults(f=cmd_probe_free)
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
    s = sub.add_parser("sync"); s.add_argument("--dry-run", action="store_true"); s.add_argument("--restart-dead", action="store_true"); s.set_defaults(f=cmd_sync)
    sub.add_parser("report").set_defaults(f=cmd_report)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
