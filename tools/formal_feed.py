#!/usr/bin/env python3
"""Keep the formal worker queue stocked, so a worker that ends is replaced by a formal worker.

`control.py refill` starts queued tasks while slots are free; this is the other half: it makes sure
there ARE startable tasks. Each pass:

  1. releases the claims of finished tasks (state exited/superseded -> integrated), because a task
     that has stopped must not block a queued task that names the same doc (its branch is landed by
     a merger, which does not need the claim);
  2. counts the queued tasks whose claims no RUNNING task holds (the startable ones);
  3. if fewer than --min-ready are startable, enqueues more, from two sources in order:
       a. FORMAL_*.md docs nobody holds (no running task, no queued task), --docs-per-task each;
       b. the project backlog tools/formal_projects.json (each key is enqueued once, ever; the used
          keys are recorded in <git-common-dir>/control/feed.json).

Run it as a loop beside refill:  python3 tools/formal_feed.py --interval 600
"""
import argparse, glob, json, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import control as C  # noqa: E402

CONTEXT = ("Context: formal backend (arm64 + x86-64 Mach-O, Lean proofs). `export PATH=/opt/homebrew/bin:$PATH`; "
           "Lean ONLY through formal/lean.py::run_lean; narrow tests via `python3 tools/memslot.py --gb 8 --label t -- ...`; "
           "no gate for formal; >3-4 GB is a bug; never `git checkout <path>`/`git stash`. Check `python3 tools/control.py "
           "claims` and `git branch --no-merged master | grep formal` first (a merger may be landing overlapping work). "
           "Every fix gets a test and a commit; file what you cannot fix as bugs/FORMAL_*.md (no duplicates). "
           "The latest sweep map (`ls -t bugs/FORMAL_sweep_work_map_*.md | head -1`) says where the corpus stands.\n\n")


def state_path():
    return os.path.join(C.ctl_dir(), "feed.json")


def load_state():
    try:
        return json.load(open(state_path()))
    except (OSError, ValueError):
        return {"used": [], "n": 50}


def save_state(s):
    json.dump(s, open(state_path(), "w"), indent=1)


def queued():
    out = []
    for f in sorted(os.listdir(C.qdir())):
        if f.endswith(".json"):
            out.append(json.load(open(os.path.join(C.qdir(), f))))
    return out


def running_claims(tasks):
    held = set()
    for t in tasks.values():
        if C.state_of(t) == "running":
            held.update(t.get("claims", []))
    return held


def release_finished():
    n = 0
    for name, t in C.load().items():
        if C.state_of(t) in ("exited-ok", "exited-err", "superseded"):
            r = subprocess.run([sys.executable, os.path.join(HERE, "control.py"), "mark", name, "integrated"],
                               capture_output=True, text=True)
            n += r.returncode == 0
    return n


def free_docs(held, q):
    taken = set(held)
    for it in q:
        taken.update(it["claims"])
    out = []
    for p in sorted(glob.glob(os.path.join(C.MAIN, "bugs", "FORMAL_*.md"))):
        b = os.path.basename(p)[:-3]
        if "sweep_work_map" in b or b == "FORMAL_known_limits":
            continue
        if "bug:" + b not in taken:
            out.append(b)
    return out


def enqueue(name, claims, text):
    cmd = [sys.executable, os.path.join(HERE, "control.py"), "enqueue", name, "--task", text]
    for c in claims:
        cmd += ["--claim", c]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=C.MAIN)
    return r.stdout.strip() or r.stderr.strip()


def feed(min_ready, docs_per_task, dry):
    released = 0 if dry else release_finished()
    tasks = C.load()
    held = running_claims(tasks)
    q = queued()
    startable = [it for it in q if not (set(it["claims"]) & held)]
    made = []
    st = load_state()
    need = min_ready - len(startable)
    rules = open(os.path.join(HERE, "formal_worker_rules.md")).read()
    while need > 0:
        docs = free_docs(held, q)
        if len(docs) >= max(2, docs_per_task // 2):
            take = docs[:docs_per_task]
            st["n"] += 1
            name = "formal%d-docs" % st["n"]
            text = (CONTEXT + "Work through these FORMAL bug docs in order, fixing as many as you can at the ROOT CAUSE; "
                    "each is yours alone. Read each doc's Status/next step first; a doc may already be fixed (delete it "
                    "with a pinning test), and a doc that vanishes on master was consolidated: move on:\n"
                    + "\n".join("  - bugs/%s.md" % d for d in take) + "\n\n" + rules)
            claims = ["bug:" + d for d in take]
        else:
            backlog = [p for p in json.load(open(os.path.join(HERE, "formal_projects.json"))) if p["key"] not in st["used"]]
            if not backlog:
                break
            p = backlog[0]
            st["used"].append(p["key"])
            name = "formal%d-%s" % (st["n"] + 1, p["key"])
            st["n"] += 1
            text = CONTEXT + "PROJECT (not doc-driven; start by MEASURING what the backend does today against CPython, " \
                             "write the oracle table first, then fix/implement in slices).\n\n" + p["text"] + "\n\n" + rules
            claims = ["project:" + p["key"]]
        made.append((name, claims))
        if not dry:
            print(enqueue(name, claims, text), flush=True)
            q = queued()
        else:
            print("would enqueue", name, claims[:2], flush=True)
            q.append({"claims": claims})
        need -= 1
    if not dry:
        save_state(st)
    print("%s feed: released %d finished tasks, %d startable queued, enqueued %d" % (
        time.strftime("%T"), released, len(startable), len(made)), flush=True)
    return len(made)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-ready", type=int, default=6, help="keep at least this many startable queued tasks")
    ap.add_argument("--docs-per-task", type=int, default=8)
    ap.add_argument("--interval", type=int, default=0, help="loop forever, seconds between passes (0: once)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    while True:
        feed(a.min_ready, a.docs_per_task, a.dry_run)
        if not a.interval:
            return
        time.sleep(a.interval)


if __name__ == "__main__":
    main()
