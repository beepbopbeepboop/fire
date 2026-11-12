#!/usr/bin/env python3
"""control.retire_landed: landing a task removes its worktree and branch in the same operation (no later cleanup).

Throwaway repo, control.MAIN pointed at it. Cases: (1) landed task whose tree differs only in controller files
(TASK.md rewritten, work.log) is fully retired: tree, branch and registry entry gone; (2) a landed task with a real
uncommitted file is KEPT, never forced; (3) a task with commits not on master is KEPT."""
import json, os, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def g(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True, env=ENV).stdout.strip()


def main():
    with tempfile.TemporaryDirectory() as d:
        repo = os.path.join(d, "repo"); os.makedirs(repo)
        ctl = os.path.join(d, "ctl"); os.makedirs(ctl)
        g(repo, "init", "-q", "-b", "master")
        open(os.path.join(repo, "TASK.md"), "w").write("old tracked brief\n")   # an OLD branch still tracks TASK.md
        g(repo, "add", "."); g(repo, "commit", "-q", "-m", "root")
        reg = {}
        for n in ("landed-clean", "landed-dirty", "unlanded"):
            wt = os.path.join(d, "work-" + n)
            g(repo, "worktree", "add", "-q", "-b", "work/" + n, wt, "master")
            g(wt, "commit", "-q", "--allow-empty", "-m", n)
            reg[n] = {"branch": "work/" + n, "worktree": wt, "state": "exited-ok", "claims": ["bug:" + n], "pid": 0}
        g(repo, "merge", "-q", "--no-edit", "work/landed-clean"); g(repo, "merge", "-q", "--no-edit", "work/landed-dirty")
        w = lambda n: reg[n]["worktree"]
        open(os.path.join(w("landed-clean"), "TASK.md"), "w").write("the controller rewrote this\n")
        open(os.path.join(w("landed-clean"), "work.log"), "w").write("log\n")
        open(os.path.join(w("landed-dirty"), "half_done.py"), "w").write("x = 1\n")
        json.dump(reg, open(os.path.join(ctl, "tasks.json"), "w"))
        os.environ["CONTROL_CTL_DIR"] = ctl
        control.MAIN = repo

        assert control.retire_landed("landed-clean") is True
        assert not os.path.exists(w("landed-clean")), "tree must be gone"
        assert "work/landed-clean" not in g(repo, "branch", "--list", "work/*"), "branch must be gone"
        assert "landed-clean" not in json.load(open(os.path.join(ctl, "tasks.json"))), "registry entry must be gone"

        assert control.retire_landed("landed-dirty") is False
        assert os.path.exists(os.path.join(w("landed-dirty"), "half_done.py")), "real uncommitted work must survive"
        assert control.retire_landed("unlanded") is False
        assert os.path.isdir(w("unlanded")) and "work/unlanded" in g(repo, "branch", "--list", "work/*")

        # the other ends of a task: abandoned with no commits, abandoned with a continuation due, held culprit
        for n, hold in (("ab-empty", False), ("ab-cont", False), ("ab-held", True)):
            wt = os.path.join(d, "work-" + n)
            g(repo, "worktree", "add", "-q", "-b", "work/" + n, wt, "master")
            if n != "ab-empty":
                g(wt, "commit", "-q", "--allow-empty", "-m", n)
            r = json.load(open(os.path.join(ctl, "tasks.json")))
            r[n] = {"branch": "work/" + n, "worktree": wt, "state": "abandoned", "claims": [], "pid": 0, "hold": hold}
            json.dump(r, open(os.path.join(ctl, "tasks.json"), "w"))
        br = lambda: set(g(repo, "branch", "--format=%(refname:short)", "--list", "work/*").split())
        assert control.retire_task("ab-empty") and "work/ab-empty" not in br(), "no commits: all gone"
        assert control.retire_task("ab-cont") and not os.path.exists(os.path.join(d, "work-ab-cont")), "tree goes"
        assert "work/ab-cont" in br(), "a continuation's base branch stays until the successor is cut"
        control.retire_base("work/ab-cont")
        assert "work/ab-cont" not in br(), "once the successor exists the predecessor's name goes"
        assert control.retire_task("ab-held") and "work/ab-held" not in br()
        assert g(repo, "for-each-ref", "--format=%(refname:short)", "refs/archive/") == "archive/work/ab-held", "archived"
        assert control.retire_base("work/unlanded") is None and "work/unlanded" in br(), "a live task's branch is never deleted"
    print("test_control_retire_landed: ok")


if __name__ == "__main__":
    main()
