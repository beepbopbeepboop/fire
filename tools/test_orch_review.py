#!/usr/bin/env python3
"""A depth cap queues an orchestration reviewer (Sonnet, pinned) that answers FORWARD, FIXED or STOP.

Checks: (1) fixer depth is recorded and travels (a recorded depth wins over counting prefixes in the name; a fixer is one
deeper); (2) enqueue_orch_review writes the evidence doc, queues a task pinned to the reserved slot with a claim naming
that doc, records `cap_review`, and gives up after MAX_CAP_REVIEWS; (3) apply_orch_reviews: FORWARD resets the cap at
once; FIXED waits until the reviewer has LANDED (its entry is gone) and only then resets; STOP and no-verdict leave the
cap; a still-running reviewer is waited on. A reset zeroes both depths, clears merge_capped/fixer and removes the doc."""
import argparse, json, os, sys, tempfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control as C, swarm as S


def main():
    with tempfile.TemporaryDirectory() as d:
        ctl = os.path.join(d, "ctl"); os.makedirs(os.path.join(ctl, "queue"))
        os.makedirs(os.path.join(d, "main", "bugs"))
        os.environ["CONTROL_CTL_DIR"] = ctl
        patches = [mock.patch.object(C, "MAIN", os.path.join(d, "main")), mock.patch.object(C, "git", lambda *a, **k: ""),
                   mock.patch.object(S, "log", lambda m: print("LOG:", m))]
        for p in patches: p.start()
        try:
            # (1) depth
            t = {"branch": "work/x"}
            assert C.fixer_depth("fix-merge-fix-merge-bug-x", t, "merge_depth") == 2, "counted from the name"
            assert C.fixer_depth("fix-merge-fix-merge-bug-x", dict(t, merge_depth=0), "merge_depth") == 0, "a recorded depth wins"
            m = C.depth_meta(dict(t, merge_depth=1, proof_depth=1), "merge_depth", "n")
            assert m == {"merge_depth": 2, "proof_depth": 1}, m

            # (2) enqueue_orch_review
            name = "fix-merge-fix-merge-fix-merge-bug-codegen-foo"
            reg = {name: {"branch": "work/foo", "state": "abandoned", "merge_capped": "cap", "started": "2026-11-12 10:00:00",
                          "worktree": os.path.join(d, "w0"), "merge_depth": 3}}
            json.dump(reg, open(os.path.join(ctl, "tasks.json"), "w"))
            queued = []
            with mock.patch.object(C, "cmd_enqueue", lambda ns: queued.append(ns)), \
                 mock.patch.object(C, "free_task_name", lambda n, limit=60: n):
                assert C.enqueue_orch_review(name, "merge-fix depth", "depth 3") is True
                ns = queued[0]
                assert ns.pool == C.ORCH_POOL and ns.only is True and ns.name == "fix-orch-bug-codegen-foo"
                doc = os.path.join(d, "main", "bugs", "ORCH_REVIEW_bug-codegen-foo.md")
                assert os.path.exists(doc) and ns.claim == ["bug:ORCH_REVIEW_bug-codegen-foo"]
                assert "ORCH-VERDICT: FORWARD" in ns.task and "FIXED" in ns.task and "STOP" in ns.task
                cr = C.load()[name]["cap_review"]
                assert cr["reviewer"] == ns.name and cr["n"] == 1 and cr["doc"] == doc
                reg2 = C.load(); reg2[name]["cap_review"]["n"] = C.MAX_CAP_REVIEWS
                json.dump(reg2, open(os.path.join(ctl, "tasks.json"), "w"))
                assert C.enqueue_orch_review(name, "merge-fix depth", "again") is False and len(queued) == 1, "gives up after MAX"

            # (3) verdicts
            def setup(verdict, reviewer_state="exited-ok", reviewer_present=True):
                wt = os.path.join(d, "rev-%s" % verdict); os.makedirs(wt, exist_ok=True)
                open(os.path.join(wt, "work.log"), "w").write("REPORT\n" + ("ORCH-VERDICT: %s\n" % verdict if verdict else "") + "CONTROL-STATUS: DONE\n")
                open(doc, "w").write("review doc\n")
                r = {name: {"branch": "work/foo", "state": "abandoned", "merge_capped": "cap", "fixer": "f", "merge_depth": 3,
                            "proof_depth": 2, "worktree": os.path.join(d, "w0"),
                            "cap_review": {"reviewer": "rev", "kind": "k", "doc": doc, "n": 1}}}
                if reviewer_present:
                    r["rev"] = {"branch": "work/rev", "worktree": wt, "state": reviewer_state}
                json.dump(r, open(os.path.join(ctl, "tasks.json"), "w"))
            with mock.patch.object(C, "state_of", lambda t: t["state"]):
                setup("FORWARD"); S.apply_orch_reviews(); t0 = C.load()[name]
                assert "merge_capped" not in t0 and "fixer" not in t0 and t0["merge_depth"] == 0 and t0["proof_depth"] == 0
                assert t0["cap_review"]["verdict"] == "FORWARD" and not os.path.exists(doc), "FORWARD resets at once, doc removed"

                setup("FIXED"); S.apply_orch_reviews(); t0 = C.load()[name]
                assert t0.get("merge_capped") and t0["cap_review"]["verdict"] == "FIXED", "FIXED is recorded, cap kept"
                S.apply_orch_reviews(); assert C.load()[name].get("merge_capped"), "still waiting while the reviewer is not landed"
                reg3 = C.load(); del reg3["rev"]; json.dump(reg3, open(os.path.join(ctl, "tasks.json"), "w"))
                S.apply_orch_reviews(); t0 = C.load()[name]
                assert "merge_capped" not in t0 and t0["merge_depth"] == 0, "reset once the fix has landed"

                setup("STOP"); S.apply_orch_reviews(); t0 = C.load()[name]
                assert t0.get("merge_capped") and t0["cap_review"]["applied"] == "STOP", "STOP leaves the cap"
                setup(None); S.apply_orch_reviews(); t0 = C.load()[name]
                assert t0.get("merge_capped") and t0["cap_review"]["applied"] == "no verdict"
                setup("FORWARD", reviewer_state="running"); S.apply_orch_reviews(); t0 = C.load()[name]
                assert t0.get("merge_capped") and not t0["cap_review"].get("applied"), "a running reviewer is waited on"
                setup("FORWARD", reviewer_present=False); S.apply_orch_reviews(); t0 = C.load()[name]
                assert t0.get("merge_capped") and t0["cap_review"]["applied"] == "no verdict", "a vanished reviewer: stays capped"
        finally:
            for p in patches: p.stop()
    # (4) the reserved slot takes only tasks pinned to it
    pool = {"slots": [{"name": "haiku", "model": "m1", "count": 0, "class": "easy"},
                      {"name": C.ORCH_POOL, "model": "m2", "count": 1, "class": "orch"}]}
    with mock.patch.object(C, "load_pool", lambda: pool), mock.patch.object(C, "dead_models", lambda: {}):
        assert C.pick_slot({"name": "fix-gate-x", "cls": None}, {}) is None, "an unclassed task must not overflow into the orch slot"
        assert C.pick_slot({"name": "x", "cls": "mid"}, {}) is None
        got = C.pick_slot({"name": "fix-orch-x", "pool": C.ORCH_POOL, "only": True}, {})
        assert got and got["name"] == C.ORCH_POOL, "a pinned review gets it"
    print("test_orch_review: ok")


if __name__ == "__main__":
    main()
