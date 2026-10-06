#!/usr/bin/env python3
"""Task controller: dispatch work items to opencode workers, one git worktree each.

    control.py spawn NAME --claim KEY [--claim KEY ...] (--task TEXT | --task-file F)
    control.py status              # one line per task: state, commits, tree, last log line
    control.py claims              # every live claim (workers read this before starting)
    control.py mark NAME STATE     # set a state by hand (abandoned, integrated, ...)
    control.py report              # regenerate the task table inside CONTROL.html
    control.py guard [--limit-gb 64]   # watchdog: kill any process in our trees past a memory limit
    control.py enqueue NAME --claim K (--task T|--task-file F) [--needs TASK...]   # queue work
    control.py refill [--target 8] # start queued tasks (deps integrated, claims free) up to N running
    control.py priority [NAME...]  # set/show the order finished branches are integrated in (most important first)
    control.py queue               # what is waiting
    control.py restart NAME        # snapshot, stop and continue a worker as NAME-rN from its own branch
    control.py unstick [--idle-min 25]   # restart workers that are stalled (idle log AND no CPU in their tree)
    control.py cleanup [--dry-run] # remove worktrees whose branch is merged, clean, and not running
    control.py ps                  # our live workers (not the user's own opencode sessions)
    control.py reap [--dry-run]    # kill leftovers (lean, gcc, ...) in finished workers' trees
    control.py digest NAME         # verdict, commits, diffstat, the worker's REPORT block
    control.py log NAME [-n N]     # tail of a worker's work.log

Layout
  ../work-N/            worktree N on branch work/<name>, created from master
  ../work-N/work.log    EVERYTHING the worker printed (stdout+stderr), append-only
  ../work-N/exitcode    written by the launcher wrapper when the worker exits
  <common-git-dir>/control/tasks.json   the registry (shared by all worktrees)

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
MODEL = os.environ.get("CONTROL_MODEL", "opencode/space-bunny-free")
TERMINAL = {"integrated", "abandoned", "superseded"}


def git(*a, cwd=MAIN, check=True):
    r = subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode:
        sys.exit("git %s failed: %s" % (" ".join(a), r.stderr.strip()))
    return r.stdout.strip()


def ctl_dir():
    d = os.path.join(os.path.realpath(os.path.join(MAIN, git("rev-parse", "--git-common-dir"))), "control")
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
    a.model = a.model or MODEL            # callers that build a Namespace by hand (autointegrate) pass None
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
        cmd = ["opencode", "--model", a.model, "run", "--auto", "--dir", wt, "--title", a.name,
               "Your complete instructions are in %s/TASK.md. Read it now and follow it exactly." % wt]
        os.makedirs(os.path.join(wt, ".tmp"), exist_ok=True)
        wrapper = 'export TMPDIR=%s PATH=%s:"$PATH"; ( %s ) >> work.log 2>&1 </dev/null; echo $? > exitcode' % (
            sh(os.path.join(wt, ".tmp")), sh(git_shim_dir()), " ".join(map(sh, cmd)))
        open(os.path.join(wt, "work.log"), "a").write("=== control: spawned %s on %s at %s ===\n" % (
            a.name, a.model, time.strftime("%F %T")))
        p = subprocess.Popen(["sh", "-c", wrapper], cwd=wt, start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # a pipe to the caller must not outlive spawn
        tasks[a.name] = dict(name=a.name, slot=n, worktree=wt, branch=branch, claims=a.claim,
                             model=a.model, pid=p.pid, started=time.strftime("%F %T"),
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


def cmd_status(a):
    for name, t in sorted(load().items(), key=lambda kv: kv[1]["slot"]):
        st = state_of(t)
        dirty = len(git("status", "--short", cwd=t["worktree"], check=False).splitlines()) \
            if os.path.isdir(t["worktree"]) else -1
        last = ""
        lp = os.path.join(t["worktree"], "work.log")
        if os.path.exists(lp):
            lines = [l for l in open(lp, errors="replace").read().splitlines() if l.strip()]
            last = lines[-1][:90] if lines else ""
        v = verdict(t)
        print("%-20s work-%-3d %-14s %-10s +%d commits, %d dirty | %s" % (name, t["slot"], st, v or "-", ahead(t), dirty, last))
        if a.verbose and v == "NEEDS-INFO":
            for q in questions(t):
                print("      QUESTION: " + q)


def cmd_claims(a):
    for name, t in sorted(load().items()):
        if state_of(t) not in TERMINAL:
            print("%-24s %s" % (name, ", ".join(t["claims"])))


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
    item = dict(name=a.name, claims=a.claim, base=a.base, task=task, files=a.file, needs=a.needs or [],
                added=time.time(), model=a.model)
    json.dump(item, open(os.path.join(qdir(), a.name + ".json"), "w"), indent=1)
    print("queued %s (needs: %s)" % (a.name, ", ".join(item["needs"]) or "nothing"))


def cmd_refill(a):
    """Keep --target workers running: start queued tasks, oldest first, while slots are free.
    A task is skipped (stays queued) if a task it needs is not integrated yet, or its claims conflict."""
    tasks = load()
    live = sum(1 for t in tasks.values() if state_of(t) == "running")
    items = sorted((json.load(open(os.path.join(qdir(), f))) for f in os.listdir(qdir()) if f.endswith(".json")),
                   key=lambda i: i["added"])
    started = 0
    for it in items:
        if live + started >= a.target:
            break
        if any(state_of(tasks[n]) != "integrated" if n in tasks else True for n in it["needs"]):
            continue
        ns = argparse.Namespace(name=it["name"], claim=it["claims"], task=it["task"], task_file=None,
                                file=it["files"], base=it["base"], model=it["model"] or MODEL)
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
    arguments: ours are launched with `--model M run --auto --dir <PARENT>/work-N`, theirs have neither."""
    tasks = {os.path.realpath(t["worktree"]): n for n, t in load().items()}
    out = subprocess.run(["ps", "-axww", "-o", "pid=,etime=,rss=,args="], capture_output=True, text=True).stdout
    mine = other = 0
    for line in out.splitlines():
        m = re.search(r"opencode .*--dir (\S+)", line)
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
    `integ` are listed and left alone. Branches are kept (they are merged, so they cost nothing, and the
    registry and `control.py status` read them)."""
    reg = load()
    byw = {os.path.realpath(t["worktree"]): (n, t) for n, t in reg.items()}
    wt, cur = [], {}
    for l in subprocess.run(["git", "worktree", "list", "--porcelain"], capture_output=True, text=True,
                            cwd=MAIN).stdout.splitlines():
        if l.startswith("worktree "):
            cur = {"path": l[9:]}; wt.append(cur)
        elif l.startswith("HEAD "):
            cur["head"] = l[5:]
    safe, kept = [], []
    for w in wt:
        p = os.path.realpath(w["path"])
        if not os.path.basename(p).startswith("work-") or os.path.basename(p) == "work-integ":
            continue
        t = byw.get(p)
        if t and state_of(t[1]) == "running":
            kept.append((p, "running")); continue
        if subprocess.run(["git", "merge-base", "--is-ancestor", w["head"], "master"], cwd=MAIN).returncode != 0:
            kept.append((p, "unmerged")); continue
        if subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=p).stdout.strip():
            kept.append((p, "dirty")); continue
        safe.append(p)
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


def restart(name, why):
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
    ns = argparse.Namespace(name=new, claim=t["claims"], task=task, task_file=None, file=[], base=t["branch"], model=t["model"])
    cmd_spawn(ns)
    return new


def cmd_restart(a):
    print("restarted as", restart(a.name, a.why))


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
    s.add_argument("--model", default=MODEL); s.set_defaults(f=cmd_spawn)
    s = sub.add_parser("status"); s.add_argument("-v", "--verbose", action="store_true"); s.set_defaults(f=cmd_status)
    sub.add_parser("claims").set_defaults(f=cmd_claims)
    s = sub.add_parser("mark"); s.add_argument("name"); s.add_argument("state"); s.set_defaults(f=cmd_mark)
    s = sub.add_parser("log"); s.add_argument("name"); s.add_argument("-n", type=int, default=40); s.set_defaults(f=cmd_log)
    s = sub.add_parser("digest"); s.add_argument("name"); s.set_defaults(f=cmd_digest)
    s = sub.add_parser("cleanup"); s.add_argument("--dry-run", action="store_true"); s.set_defaults(f=cmd_cleanup)
    s = sub.add_parser("guard"); s.add_argument("--limit-gb", type=float, default=55); s.add_argument("--total-gb", type=float, default=90)
    s.add_argument("--interval", type=float, default=3); s.add_argument("--once", action="store_true")
    s.add_argument("--lean-wall-min", type=float, default=45, help="kill a lean process in our trees past this many wall minutes")
    s.add_argument("--lean-cpu-min", type=float, default=90, help="... or this many CPU minutes (all threads)")
    s.add_argument("--runaway-min", type=float, default=120, help="kill a fire.py build / test_*.py / sweep / probe in our trees past this many wall minutes")
    s.set_defaults(f=cmd_guard)
    s = sub.add_parser("enqueue"); s.add_argument("name"); s.add_argument("--claim", action="append", required=True)
    g = s.add_mutually_exclusive_group(required=True); g.add_argument("--task"); g.add_argument("--task-file")
    s.add_argument("--file", action="append", default=[]); s.add_argument("--base", default="master")
    s.add_argument("--needs", nargs="*"); s.add_argument("--model", default=None); s.set_defaults(f=cmd_enqueue)
    s = sub.add_parser("refill"); s.add_argument("--target", type=int, default=8); s.set_defaults(f=cmd_refill)
    s = sub.add_parser("priority"); s.add_argument("names", nargs="*"); s.set_defaults(f=cmd_priority)
    sub.add_parser("queue").set_defaults(f=cmd_queue)
    s = sub.add_parser("memtrim"); s.add_argument("--floor", type=float, default=4.0)
    s.add_argument("--interval", type=float, default=3.0); s.add_argument("--once", action="store_true"); s.set_defaults(f=cmd_memtrim)
    s = sub.add_parser("restart"); s.add_argument("name"); s.add_argument("--why", default="restarted by the controller"); s.set_defaults(f=cmd_restart)
    s = sub.add_parser("unstick"); s.add_argument("--idle-min", type=float, default=25); s.add_argument("--dry-run", action="store_true"); s.set_defaults(f=cmd_unstick)
    s = sub.add_parser("hold"); s.add_argument("name"); s.add_argument("--release", action="store_true"); s.set_defaults(f=cmd_hold)
    sub.add_parser("ps").set_defaults(f=cmd_ps)
    s = sub.add_parser("reap"); s.add_argument("--dry-run", action="store_true"); s.set_defaults(f=cmd_reap)
    sub.add_parser("report").set_defaults(f=cmd_report)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
