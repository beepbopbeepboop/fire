#!/usr/bin/env python3
"""The feeder's stop indicator: a `STOP: <reason>` line in a bug doc is the only thing that keeps it off the queue.

    python3 tools/test_swarm_feed.py

Uses a temporary tree (C.MAIN is pointed at it), so the live registry and bugs/ are never read."""
import os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import control as C
import swarm as S


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    return cond


def test_holds():
    """Only work holds a claim: a live worker, or commits not yet landed. A dead entry with no commits holds nothing."""
    ok = True
    real_ahead = C.ahead
    try:
        C.ahead = lambda t: t["_ahead"]
        live = {"state": "running", "pid": os.getpid(), "_ahead": 0}
        ok &= check("a live worker holds its claims", C.holds_claims(live))
        dead0 = {"state": "integration-failed", "pid": 0, "worktree": "/nowhere", "_ahead": 0}
        ok &= check("an integration-failed entry with no commits holds nothing", not C.holds_claims(dead0))
        deadw = {"state": "integration-failed", "pid": 0, "worktree": "/nowhere", "_ahead": 2}
        ok &= check("a dead entry with commits holds until they land", C.holds_claims(deadw))
        done = {"state": "integrated", "pid": 0, "worktree": "/nowhere", "_ahead": 3}
        ok &= check("an integrated entry holds nothing", not C.holds_claims(done))
    finally:
        C.ahead = real_ahead
    return ok


def test_limit_detection(tmp):
    def wt(text):
        d = os.path.join(tmp, "wt%d" % len(os.listdir(tmp)))
        os.makedirs(d)
        open(os.path.join(d, "work.log"), "w").write(text)
        return {"worktree": d}
    ok = True
    ok &= check("claude CLI weekly limit line is a limit",
                C.limit_hit(wt("=== spawned ===\nYou've hit your weekly limit \u00b7 resets 11am\n")))
    ok &= check("a worker that merely READ a rate-limit text is not limited",
                not C.limit_hit(wt("> read file\n    if rate limit exceeded: retry\n")))
    return ok


def test_classes():
    ok = True
    ok &= check("a doc at the top of bugs/ is easy", S.doc_class("CODEGEN_x", {}, "CODEGEN_x") == "easy")
    ok &= check("a doc in bugs/hard/ is hard, from its location", S.doc_class("hard/CODEGEN_x", {}, "CODEGEN_x") == "hard")
    ok &= check("a doc in bugs/mid/ is mid, from its location", S.doc_class("mid/CODEGEN_x", {}, "CODEGEN_x") == "mid")
    ok &= check("the top class has nothing above it", S.escalate("hard") is None)
    ok &= check("easy escalates to mid, mid to hard", S.escalate("easy") == "mid" and S.escalate("mid") == "hard")

    real_pool = C.load_pool
    C.load_pool = lambda: {"slots": [
        {"name": "haiku", "model": "h", "count": 2, "kind": "claude", "class": "easy"},
        {"name": "sonnet", "model": "s", "count": 1, "kind": "claude", "class": "mid"},
        {"name": "opus", "model": "o", "count": 1, "kind": "claude", "class": "hard"}]}
    try:
        busy = {}
        ok &= check("a mid task goes to the mid slot, never an easy one",
                    C.pick_slot({"cls": "mid", "pool": None}, busy)["name"] == "sonnet")
        busy = {"sonnet": 1}
        ok &= check("a mid task with its mid slot full waits, even with easy slots free",
                    C.pick_slot({"cls": "mid", "pool": None}, busy) is None)
        ok &= check("an unclassed task takes the first free slot in pool order",
                    C.pick_slot({"pool": None}, {})["name"] == "haiku")
    finally:
        C.load_pool = real_pool

    st = {"fails": {}}
    for _ in range(S.ESCALATE_AFTER):
        S.reclass_on_failure(st, "CODEGEN_x", "CODEGEN_x")
    ok &= check("the failures due a reclass are pending a file move", st["pending"]["CODEGEN_x"] == "mid")
    ok &= check("the failure count restarts after a reclass", st["fails"]["CODEGEN_x"] == 0)
    st2 = {"fails": {}}
    for _ in range(S.ESCALATE_AFTER):
        S.reclass_on_failure(st2, "CODEGEN_y", "hard/CODEGEN_y")
    ok &= check("a hard doc stays hard", "CODEGEN_y" not in st2.get("pending", {}))
    return ok


def test_apply_moves(tmp):
    """A pending reclass is a git mv of the doc, its path citations rewritten, one docs-only commit on master. A dirty
    cited file makes it wait instead of being swept into the commit."""
    import subprocess as sp
    ok = True
    repo = os.path.join(tmp, "repo")
    ctl = os.path.join(tmp, "ctl")
    os.makedirs(os.path.join(repo, "bugs"))
    os.makedirs(ctl)
    def g(*a):
        return sp.run(["git", *a], cwd=repo, capture_output=True, text=True).stdout
    g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
    open(os.path.join(repo, "bugs", "CODEGEN_x.md"), "w").write("# x\n")
    open(os.path.join(repo, "NOTE.md"), "w").write("see bugs/CODEGEN_x.md for detail\n")
    open(os.path.join(repo, "other.txt"), "w").write("unrelated\n")
    open(os.path.join(repo, "bugs", "CODEGEN_y.md"), "w").write("# y, see bugs/CODEGEN_x.md and bugs/CODEGEN_y.md\n")
    g("add", "-A"); g("commit", "-qm", "init")
    saved = (C.MAIN, C.ctl_dir, S.state_path)
    C.MAIN = repo
    C.ctl_dir = lambda: ctl
    S.state_path = lambda: os.path.join(tmp, "swarm.json")
    try:
        open(os.path.join(repo, "NOTE.md"), "a").write("edit in progress\n")   # the user's uncommitted edit
        st = {"pending": {"CODEGEN_x": "mid"}}
        S.apply_moves(st)
        ok &= check("a dirty cited file makes the reclass wait", st["pending"] == {"CODEGEN_x": "mid"}
                    and os.path.exists(os.path.join(repo, "bugs", "CODEGEN_x.md")))
        open(os.path.join(repo, "NOTE.md"), "w").write("see bugs/CODEGEN_x.md for detail\n")   # the fixture, restored
        st = {"pending": {"CODEGEN_x": "mid", "CODEGEN_y": "mid"}}
        S.apply_moves(st)
        ok &= check("the doc moves into bugs/mid/", os.path.exists(os.path.join(repo, "bugs", "mid", "CODEGEN_x.md"))
                    and not os.path.exists(os.path.join(repo, "bugs", "CODEGEN_x.md")))
        ok &= check("the citation is rewritten to the new path",
                    open(os.path.join(repo, "NOTE.md")).read() == "see bugs/mid/CODEGEN_x.md for detail\n")
        ok &= check("the move is committed, with the other file untouched",
                    "other.txt" not in g("show", "--name-only", "--format=", "HEAD").split()
                    and "bugs/mid/CODEGEN_x.md" in g("show", "--name-only", "--format=", "HEAD").split())
        ok &= check("a doc citing another moved doc is rewritten, not left pointing at the old path",
                    open(os.path.join(repo, "bugs", "mid", "CODEGEN_y.md")).read()
                    == "# y, see bugs/mid/CODEGEN_x.md and bugs/mid/CODEGEN_y.md\n")
        ok &= check("the pending entry is cleared", st["pending"] == {})
    finally:
        C.MAIN, C.ctl_dir, S.state_path = saved
    return ok


def test_task_text():
    """A fresh worker is told the doc's path; one that starts from an earlier attempt is told the branch, its commit
    count and the path the doc has on that branch (which differs from master after a reclass)."""
    ok = True
    plain = S.task_text("mid/CODEGEN_x")
    ok &= check("a fresh task names the doc on master", "bugs/mid/CODEGEN_x.md" in plain and "branch" not in plain)
    cont = S.task_text("mid/CODEGEN_x", branch="work/y", path="bugs/CODEGEN_x.md", ahead=3)
    ok &= check("a continuation names its branch, commit count and the doc's path there",
                "work/y" in cont and "3 commit(s)" in cont and "bugs/CODEGEN_x.md" in cont)
    return ok


def main():
    ok = True
    ok &= test_holds()
    ok &= test_task_text()
    ok &= test_classes()
    with tempfile.TemporaryDirectory() as tmp:
        ok &= test_limit_detection(tmp)
        ok &= test_apply_moves(tmp)
    with tempfile.TemporaryDirectory() as tmp:
        C.MAIN = tmp
        os.makedirs(os.path.join(tmp, "bugs"))
        open(os.path.join(tmp, "bugs", "plain.md"), "w").write("# A bug\n\n## Status\n\nOPEN.\n")
        open(os.path.join(tmp, "bugs", "stopped.md"), "w").write(
            "# A bug\n\nSTOP: needs the owner's decision on FORMAL scope\n\n## Status\n")
        ok &= check("a doc without a STOP line has no stop", S.stop_reason("plain") is None)
        ok &= check("the STOP line gives its reason", S.stop_reason("stopped") ==
                    "needs the owner's decision on FORMAL scope")
        ok &= check("a missing doc has no stop", S.stop_reason("nope") is None)
        open(os.path.join(tmp, "bugs", "mention.md"), "w").write(
            "# A bug\n\nThe word STOP: appears mid-line, and the note says do not stop.\n")
        ok &= check("STOP: mid-line is not a stop marker", S.stop_reason("mention") is None)
    tasks = {"a": {"state": "exited-ok"}, "b": {"state": "integration-failed"}, "c": {"state": "exited-err"}}
    _state = C.state_of
    C.state_of = lambda t: t["state"]
    ok &= check("fresh branches go before failed ones", S.fresh_first(["b", "a", "c"], tasks) == ["a", "c"])
    ok &= check("with only failed branches left, they are tried", S.fresh_first(["b"], tasks) == ["b"])
    C.state_of = _state
    # the culprit search: a fake probe that is red once the culprit is in the prefix
    _probe = S.probe
    for bad, seq in [("c", ["a", "b", "c", "d", "e"]), ("a", ["a", "b", "c"]), ("e", ["a", "b", "c", "d", "e"])]:
        S.probe = lambda s, bad=bad: ("RED", s, ["job-" + bad], "") if bad in s else ("GREEN", s, [], "")
        ok &= check("the culprit search finds %s in %s" % (bad, seq), S.find_culprit(seq, ["job-" + bad])[0] == bad)
    S.probe = _probe
    print("all passed" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
