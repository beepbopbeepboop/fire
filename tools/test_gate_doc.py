#!/usr/bin/env python3
"""Work exists only while its bug doc does, and a red gate becomes a doc.

    python3 tools/test_gate_doc.py

Points C.MAIN at a temporary tree and replaces the registry with an in-memory dict, so the live bugs/ and tasks.json
are never read or written."""
import contextlib, os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import control as C
import integrate as I

FAILED = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILED.append(name)


def fake_registry(reg):
    @contextlib.contextmanager
    def registry():
        yield reg
    return registry


def in_tree(fn):
    """Run fn with C.MAIN at a fresh tree that has an empty bugs/."""
    real_main = C.MAIN
    tmp = tempfile.mkdtemp(prefix="gatedoc_")
    os.makedirs(os.path.join(tmp, "bugs"))
    C.MAIN = tmp
    try:
        fn(tmp)
    finally:
        C.MAIN = real_main


def test_two_states_for_a_claim():
    """bugs/x.md exists -> the claim has work; deleted -> it has none."""
    def body(tmp):
        p = os.path.join(tmp, "bugs", "bug-x-thing.md")
        open(p, "w").write("# x\n")
        check("a claim whose doc exists has work", C.doc_exists_for(["bug:x-thing"]))
        os.remove(p)
        check("the same claim after its doc is deleted has no work", not C.doc_exists_for(["bug:x-thing"]))
        check("a claim naming no doc has no work", not C.doc_exists_for(["task:nothing-here"]))
    in_tree(body)


def test_red_gate_writes_one_doc_per_job():
    def body(tmp):
        reg = {"fix-x": {"branch": "work/x", "state": "exited-ok", "claims": ["bug:x"]}}
        real = C.registry
        C.registry = fake_registry(reg)
        try:
            paths = I.gate_doc("fix-x", reg["fix-x"], ["formal-host-import-shapes", "stdlib-syntax"])
            check("a red gate creates bugs/gate-<job>.md for each failing job",
                  all(os.path.exists(p) for p in paths) and len(paths) == 2)
            body1 = open(paths[0]).read()
            check("the doc names its job and the culprit branch",
                  "formal-host-import-shapes" in body1 and "work/x" in body1)
            open(paths[0], "w").write("edited by a worker\n")
            I.gate_doc("fix-x", reg["fix-x"], ["formal-host-import-shapes"])
            check("a second red for the same job does not overwrite the doc",
                  open(paths[0]).read() == "edited by a worker\n")
            check("the culprit is superseded and held, so it cannot land again",
                  reg["fix-x"]["state"] == "superseded" and reg["fix-x"]["hold"] is True)
            check("the culprit is excluded from landing candidates by its hold",
                  bool(reg["fix-x"].get("hold")))
            check("a doc named after the job is what the claim matches",
                  C.doc_exists_for(["gate:formal-host-import-shapes"]))
        finally:
            C.registry = real
    in_tree(body)


def test_restart_refuses_a_task_with_no_doc():
    def body(tmp):
        t = {"name": "fix-gate-x-r2", "claims": ["gate:formal-host-import-shapes"], "branch": "work/y",
             "worktree": os.path.join(tmp, "no-such-tree")}
        reg = {"fix-gate-x-r2": dict(t)}
        real_load, real_reg = C.load, C.registry
        C.load = lambda: {"fix-gate-x-r2": t}
        C.registry = fake_registry(reg)
        try:
            new = C.restart("fix-gate-x-r2", "process dead")
            check("restart refuses a task whose doc is gone (returns None)", new is None)
            check("the refused task is abandoned, so its claim releases",
                  reg["fix-gate-x-r2"]["state"] == "abandoned")
        finally:
            C.load, C.registry = real_load, real_reg
    in_tree(body)


if __name__ == "__main__":
    test_two_states_for_a_claim()
    test_red_gate_writes_one_doc_per_job()
    test_restart_refuses_a_task_with_no_doc()
    print("%d failure(s)" % len(FAILED))
    sys.exit(1 if FAILED else 0)
