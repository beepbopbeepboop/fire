#!/usr/bin/env python3
"""The registry's "integrated" state means landed: its branch's commits are on master. Covers the two ways it was set
wrongly (2026-11-02: five conflicted or gate-red tasks, superseded by a fixer, were relabelled integrated):
  - control.py mark NAME integrated refuses a task whose branch still has commits master lacks;
  - formal_feed.release_finished never relabels a superseded task.
Uses a temporary ledger directory and stubs the git lookups, so it never reads or writes the live registry."""
import json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control as C
import formal_feed as F
import argparse

_tmp = tempfile.mkdtemp(prefix="integtest_")
C.ctl_dir = lambda: _tmp
FAILS, PASSES = [], []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    (PASSES if cond else FAILS).append(name)


def registry_with(tasks):
    json.dump(tasks, open(os.path.join(_tmp, "tasks.json"), "w"))


def task(state, branch="work/x"):
    return {"name": "t", "state": state, "branch": branch, "pid": 0, "worktree": "/nonexistent", "claims": []}


def mark(name, state):
    C.cmd_mark(argparse.Namespace(name=name, state=state))


def state_after(name):
    return json.load(open(os.path.join(_tmp, "tasks.json")))[name]["state"]


_real_ahead = C.ahead

# control.py mark: integrated only when nothing is left to land
C.ahead = lambda t: 3
registry_with({"x": task("exited-ok")})
try:
    mark("x", "integrated")
    refused = False
except SystemExit:
    refused = True
check("mark integrated refuses a branch with commits master lacks", refused)
check("a refused mark leaves the state alone", state_after("x") == "exited-ok")

mark("x", "superseded")
check("marking a task superseded is allowed with commits off master", state_after("x") == "superseded")

C.ahead = lambda t: 0
mark("x", "integrated")
check("mark integrated is allowed once the branch is on master", state_after("x") == "integrated")
C.ahead = _real_ahead

# formal_feed.release_finished: a superseded task keeps its state; a finished landed one is integrated
calls = []
_real_run = F.subprocess.run
F.subprocess.run = lambda cmd, **kw: calls.append(cmd[-2:]) or type("R", (), {"returncode": 0})()
_real_unlanded = F._unlanded
F._unlanded = lambda t: t.get("_unlanded", False)
_real_load = C.load
try:
    C.load = lambda: {
        "sup": dict(task("superseded"), _unlanded=True),
        "done": dict(task("exited-ok"), _unlanded=False),
        "open": dict(task("exited-ok"), _unlanded=True),
    }
    C.state_of = lambda t: t["state"]
    n = F.release_finished()
    marked = [c[0] for c in calls]
    check("release_finished does not relabel a superseded task", "sup" not in marked)
    check("release_finished marks a finished, landed task integrated", "done" in marked)
    check("release_finished leaves a finished task with unlanded commits alone", "open" not in marked)
finally:
    F.subprocess.run = _real_run
    F._unlanded = _real_unlanded
    C.load = _real_load


# _unlanded: a gone branch is landed only when its recorded tip is on master
F._unlanded = _real_unlanded
_head = C.git("rev-parse", "master")
_off = "c07b5c0634d6060f17029f85229fa2477c8ed232"   # an integration merge that never reached master
check("a gone branch whose recorded tip is on master counts as landed",
      F._unlanded({"branch": "work/no-such-branch-xyz", "tip": _head}) is False)
check("a gone branch whose recorded tip is off master counts as unlanded",
      F._unlanded({"branch": "work/no-such-branch-xyz", "tip": _off}) is True)
check("a gone branch with no recorded tip counts as unlanded",
      F._unlanded({"branch": "work/no-such-branch-xyz"}) is True)

print("%d passed, %d failed" % (len(PASSES), len(FAILS)))
sys.exit(1 if FAILS else 0)
