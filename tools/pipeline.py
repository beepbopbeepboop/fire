#!/usr/bin/env python3
"""A CHAIN of batches: each stage pulls in the one before it, so every stage already contains everything the earlier stages merged
(master included) and no stage ever merges master separately.

    pipeline.py --stage1 batch1-sync --stage2 stage2merge

  1. batch 1 merges master in (its own agent: `batch1-sync`).
  2. batch 2 (`stage2merge`, built on the OLD batch-1 tree plus the remaining branches) pulls the synced batch 1 in: a clean merge
     is automatic, a conflicting one gets an agent (`stage2-pull1`). Done as soon as both are finished, without waiting for the gate.
  3. Batch 2 stays HELD until batch 1 has landed on master; then it is released and the integrator gates it, a piece-fixer repairs
     what breaks, and it lands when clean.
"""
import argparse, os, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control as C


def log(m):
    print("%s %s" % (time.strftime("%F %T"), m), flush=True)


def family(name):
    t = C.load()
    return sorted((n for n in t if n == name or n.startswith(name + "-r")), key=lambda n: t[n]["slot"])


def running(name):
    t = C.load()
    return any(C.state_of(t[n]) == "running" for n in family(name))


def snapshot(n):
    wt = C.load()[n]["worktree"]
    C.git("add", "-A", cwd=wt, check=False)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=wt).returncode != 0:
        C.git("commit", "-q", "-m", "WIP snapshot by controller: the worker exited with uncommitted work", cwd=wt, check=False)


def latest(name):
    t = C.load()
    done = [n for n in family(name) if C.ahead(t[n]) > 0]
    return done[-1] if done else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage1", required=True); ap.add_argument("--stage2", required=True)
    a = ap.parse_args()
    while running(a.stage1) or running(a.stage2):
        time.sleep(30)
    for n in family(a.stage1) + family(a.stage2):
        snapshot(n)
    s1, s2 = latest(a.stage1), latest(a.stage2)
    if not (s1 and s2):
        log("stage 1 (%s) or stage 2 (%s) produced no commits: nothing to chain" % (s1, s2)); return
    t = C.load()
    b1, wt2 = t[s1]["branch"], t[s2]["worktree"]
    log("batch 2 (%s) pulls batch 1 (%s) in" % (s2, b1))
    r = subprocess.run(["git", "merge", "--no-edit", b1], cwd=wt2, capture_output=True, text=True)
    final = s2
    if r.returncode != 0:
        subprocess.run(["git", "merge", "--abort"], cwd=wt2)
        import argparse as _ap
        name = "stage2-pull1"
        task = ("Your branch %s is BATCH 2: the old batch-1 tree plus the remaining finished branches, already merged. BATCH 1 has since been FIXED and "
                "SYNCED WITH MASTER (branch %s: the piece-fixer's repairs, and the owner's new-modular stdlib work from master). Run `git merge %s` into your "
                "branch and resolve every conflict keeping BOTH sides' intent (batch 1's repairs and the owner's new-modular work are the newer ground truth; "
                "batch 2's merged branches must be preserved). Make the tree coherent (a helper changed on one side, called the old way on the other; a duplicated "
                "registration or fix: consolidate). Fixes of any size are fine. Run the narrow tests for the files each resolution touches, and python3 "
                "test_suite.py. Do NOT run the project gate. Never use git stash. Commit; finish with the REPORT block and CONTROL-STATUS: DONE."
                % (t[s2]["branch"], b1, b1))
        C.cmd_spawn(_ap.Namespace(name=name, claim=["task:" + name], task=task, task_file=None, file=[], base=t[s2]["branch"], model=None))
        with C.registry() as reg:
            reg[name]["hold"] = True
        log("conflicts: agent %s merging batch 1 into batch 2" % name)
        while running(name):
            time.sleep(30)
        for n in family(name):
            snapshot(n)
        final = latest(name) or s2
    else:
        log("clean merge: batch 2 now contains batch 1")
    # 3. release batch 2 only once batch 1 is on master
    while subprocess.run(["git", "merge-base", "--is-ancestor", b1, "master"], cwd=C.MAIN).returncode != 0:
        time.sleep(60)
    with C.registry() as reg:
        for n in family(a.stage2) + [final]:
            if n in reg:
                reg[n].pop("hold", None)
    log("batch 1 is on master: batch 2 (%s) released to the integrator" % final)


if __name__ == "__main__":
    main()
