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


def test_hold():
    ok = True
    H = "a" * 40
    ok &= check("no record: not held", not S.hold_active(None, H, 3600))
    ok &= check("same doc inside the retry window: held",
                S.hold_active({"hash": H, "at": 1000.0}, H, 3600, now=2000.0))
    ok &= check("same doc after the retry window: released",
                not S.hold_active({"hash": H, "at": 1000.0}, H, 3600, now=1000.0 + 3600))
    ok &= check("doc changed inside the window: released",
                not S.hold_active({"hash": H, "at": 1000.0}, "b" * 40, 3600, now=2000.0))
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
    ok &= check("every doc starts easy, even in bugs/hard/", S.doc_class("hard/CODEGEN_x", {}, "CODEGEN_x") == "easy")
    ok &= check("an escalated class overrides the directory",
                S.doc_class("CODEGEN_x", {"cls": {"CODEGEN_x": "mid"}}, "CODEGEN_x") == "mid")
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
    ok &= check("one no-commit attempt at easy boosts the doc to mid", st["cls"]["CODEGEN_x"] == "mid")
    ok &= check("the failure count restarts after a reclass", st["fails"]["CODEGEN_x"] == 0)
    st2 = {"fails": {}, "no_progress": {"CODEGEN_y": {"hash": "h", "at": 0}}}
    st2["cls"] = {"CODEGEN_y": "hard"}
    for _ in range(S.ESCALATE_AFTER):
        S.reclass_on_failure(st2, "CODEGEN_y", "hard/CODEGEN_y")
    ok &= check("a hard doc stays hard and keeps its hold", st2["cls"]["CODEGEN_y"] == "hard"
                and "CODEGEN_y" in st2["no_progress"])
    return ok


def main():
    ok = True
    ok &= test_hold()
    ok &= test_classes()
    with tempfile.TemporaryDirectory() as tmp:
        ok &= test_limit_detection(tmp)
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
